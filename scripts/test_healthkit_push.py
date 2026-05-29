#!/usr/bin/env python3
"""Operator-run smoke test for the HealthKit nutrition bridge webhook.

Sends a synthetic HealthKit payload to the deployed /cron/healthkit-sync
endpoint, verifies the Firestore doc lands at meals/{YYYY-MM-DD}/timestamps/
healthkit:test-{ts}, prompts to delete the test doc(s).

Usage:
    export HEALTHKIT_WEBHOOK_TOKEN=<the-token-from-secret-manager>
    export GCP_PROJECT_ID=klaus-agent  # lowercase per CLAUDE.md invariant
    python scripts/test_healthkit_push.py \\
        --url https://klaus-agent-XXXX.run.app/cron/healthkit-sync \\
        --count 2

Exit codes:
    0 — push 200 + Firestore doc(s) verified + cleanup acknowledged
    1 — anything else (auth fail, 4xx/5xx, Firestore mismatch)

Phase 19.1 — HEALTHKIT-08 / D-20.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HealthKit webhook smoke test")
    p.add_argument(
        "--url",
        required=True,
        help="Full https URL to /cron/healthkit-sync",
    )
    p.add_argument(
        "--count",
        type=int,
        default=2,
        help="Number of synthetic samples to push",
    )
    p.add_argument(
        "--token-env",
        default="HEALTHKIT_WEBHOOK_TOKEN",
        help="Env var holding the bearer token",
    )
    p.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip the delete-test-docs prompt",
    )
    return p.parse_args()


def _build_synthetic_payload(count: int) -> tuple[dict, int]:
    """Synthetic payload matching mcp_tools.healthkit_tool.HealthKitPayload.

    Path B (live UAT 2026-05-30): the wire format is FLAT — one
    HKQuantitySample per row. Each synthetic "meal" emits 4 flat samples
    (Energy / Protein / Carbs / Fat) tagged with a distinct ``food_item``
    so the server-side aggregator buckets them into ``count`` distinct
    per-meal Firestore docs.

    The ``uuid`` prefix ``test-{ts_marker}-`` flows through to the
    fallback ``source_id`` (uuid is NOT in _KNOWN_SOURCE_NAMES) so the
    resulting Firestore docs are trivially identifiable for cleanup
    via the source_id prefix ``healthkit:test-{ts_marker}-`` (D-20).
    """
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    ts_marker = int(time.time())
    samples = []
    for i in range(count):
        for qtype, value in (
            ("DietaryEnergyConsumed_kcal", 500.0 + i * 10),
            ("DietaryProtein_g", 30.0),
            ("DietaryCarbohydrates_g", 60.0),
            ("DietaryFatTotal_g", 18.0),
        ):
            samples.append({
                "uuid": f"test-{ts_marker}-{i}",
                "start_date": now.isoformat(),
                "quantity_type": qtype,
                "value": value,
                "metadata": {},
                "food_item": f"smoke-test-meal-{i}",
            })
    return {"samples": samples}, ts_marker


def _post(url: str, token: str, payload: dict) -> tuple[int, dict]:
    try:
        import requests  # type: ignore
    except ImportError:
        print(
            "ERROR: requests not installed; pip install requests",
            file=sys.stderr,
        )
        sys.exit(2)
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:500]}
    return resp.status_code, body


def _verify_firestore(ts_marker: int, count: int) -> list[str]:
    from memory.firestore_db import MealStore

    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    project_id = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    meals = MealStore(project_id=project_id, database=database).get_day(today)
    prefix = f"healthkit:test-{ts_marker}-"
    found = [m for m in meals if m.get("source_id", "").startswith(prefix)]
    if len(found) != count:
        print(
            f"MISMATCH: posted {count} samples, found {len(found)} Firestore "
            f"docs with prefix {prefix}"
        )
    else:
        print(f"OK: found {count} Firestore docs with prefix {prefix}")
    return [m["source_id"] for m in found]


def main() -> int:
    args = _parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        print(
            f"ERROR: env var {args.token_env} is empty",
            file=sys.stderr,
        )
        return 1

    payload, ts_marker = _build_synthetic_payload(args.count)
    status, body = _post(args.url, token, payload)
    print(f"POST {args.url} → {status} {body}")
    if status != 200:
        return 1

    source_ids = _verify_firestore(ts_marker, args.count)
    if len(source_ids) != args.count:
        return 1

    if args.no_cleanup:
        print("--no-cleanup set; leaving test docs in place")
        return 0

    ans = input(
        f"Delete {len(source_ids)} test docs? [y/N]: "
    ).strip().lower()
    if ans == "y":
        # Use raw Firestore client as primary path — MealStore.delete is
        # not part of the verified contract; avoid scope creep.
        from google.cloud import firestore  # type: ignore

        project_id = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
        database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
        db = firestore.Client(project=project_id, database=database)
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        for sid in source_ids:
            try:
                db.collection("meals").document(today).collection(
                    "timestamps"
                ).document(sid).delete()
            except Exception as exc:
                print(f"WARN: could not delete {sid}: {exc}")
        print(f"Deleted {len(source_ids)} test docs.")
    else:
        print("Skipped cleanup; test docs remain in Firestore.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
