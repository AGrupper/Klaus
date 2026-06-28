"""Clear a stale cron failure-streak so the heartbeat stops re-alerting.

Usage:
    python scripts/reset_cron_streak.py <job-id> [--dry-run]
    python scripts/reset_cron_streak.py --list

Why this exists
---------------
`core/heartbeat.py:check_cron_health` raises a CRITICAL `cron:<job>:failing`
signal purely on `heartbeat_runs/<job>.consecutive_failures >= 3`. That counter
ONLY resets on a *successful* run (`memory/firestore_db.py:record_cron_run`).

So when a low-frequency cron (e.g. weekly-training-review, Sundays only) fails a
few times and you then deploy a fix, the streak stays frozen at its last value
until the NEXT scheduled run actually succeeds — and the heartbeat keeps pinging
the same "failed Nx in a row" message every `reping_interval_hours` (24h) in the
meantime. The system has no way to know you already fixed it.

This script is the explicit "I fixed it" lever: it zeroes the streak and resolves
the open incident so the nag stops immediately. If the fix were wrong, the next
real run simply re-raises the alert legitimately.

It does NOT touch `last_run_at` / `last_ok_at` (those stay truthful) and it does
NOT mark a fake success — it only clears the failure *count*.

Re-runnable and idempotent.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv

load_dotenv(override=True)

from memory.firestore_db import _make_firestore_client


def _client():
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _make_firestore_client(project_id, database)


def list_streaks() -> None:
    """Print every cron ledger entry with a non-zero failure streak."""
    client = _client()
    rows = []
    for snap in client.collection("heartbeat_runs").stream():
        doc = snap.to_dict() or {}
        n = doc.get("consecutive_failures", 0)
        if n:
            rows.append((snap.id, n, doc.get("last_ok_at"), doc.get("last_run_at")))
    if not rows:
        print("No crons currently in a failure streak. ✔")
        return
    print(f"{'job_id':<28} {'fails':>5}  last_ok_at")
    for job_id, n, last_ok_at, _ in sorted(rows, key=lambda r: -r[1]):
        print(f"{job_id:<28} {n:>5}  {last_ok_at}")


def reset_streak(job_id: str, *, dry_run: bool) -> int:
    """Zero the failure counter for job_id and resolve its open incident.

    Returns a process exit code (0 = ok / nothing to do, 2 = job unknown).
    """
    client = _client()
    ledger_ref = client.collection("heartbeat_runs").document(job_id)
    snap = ledger_ref.get()
    if not snap.exists:
        print(
            f"No heartbeat_runs ledger entry for {job_id!r}. "
            f"Run with --list to see known job-ids."
        )
        return 2

    before = snap.to_dict() or {}
    streak = before.get("consecutive_failures", 0)
    print(f"{job_id}: consecutive_failures = {streak} (last_ok_at={before.get('last_ok_at')})")

    if dry_run:
        print("[dry-run] would set consecutive_failures=0 and resolve "
              f"incident cron:{job_id}:failing")
        return 0

    if streak == 0:
        print("Already 0 — nothing to clear.")
    else:
        ledger_ref.set({"consecutive_failures": 0}, merge=True)
        print("Cleared failure streak → 0.")

    # Resolve the open incident so the 24h re-ping stops now. (The next heartbeat
    # tick would auto-resolve it via _resolve_absent once the signal disappears,
    # but close it explicitly so there's no in-between ping.)
    incident_ref = client.collection("heartbeat_incidents").document(
        f"cron:{job_id}:failing")
    inc = incident_ref.get()
    if inc.exists and (inc.to_dict() or {}).get("status") == "open":
        incident_ref.set(
            {"status": "resolved", "resolved_at": datetime.now(timezone.utc)},
            merge=True,
        )
        print("Resolved open incident cron:%s:failing." % job_id)
    else:
        print("No open incident to resolve.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_id", nargs="?",
                        help="Cron job-id as recorded in heartbeat_runs "
                             "(e.g. weekly-training-review).")
    parser.add_argument("--list", action="store_true",
                        help="List all crons currently in a failure streak and exit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing.")
    args = parser.parse_args()

    if args.list:
        list_streaks()
        return 0
    if not args.job_id:
        parser.error("provide a job-id, or use --list")
    return reset_streak(args.job_id, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
