"""One-shot re-sync of Garmin run details into RunDetailStore.

Why this exists: before the lapDTOs-primary fix, every stored run's ``splits``
were the type-aggregated typed-splits buckets (total run time vs total walk
time), not the actual recorded laps. RunDetailStore.upsert is idempotent on
activity_id and ``set(merge=True)`` replaces the splits array wholesale, so a
direct refetch cleanly overwrites the stale aggregate docs.

Usage (local, Garmin creds + GCP_PROJECT_ID from .env):
    python scripts/resync_run_details.py --days 45 --only-typed
    python scripts/resync_run_details.py --days 7 --dry-run

Flags:
    --days N       look-back window (default 30)
    --dry-run      list what would be refetched; write nothing
    --only-typed   skip docs whose splits already came from lapDTOs
                   (docs without a splits_source field — all pre-fix docs —
                   count as stale and are refetched)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("resync_run_details")


def resync(days: int, dry_run: bool, only_typed: bool) -> dict:
    """Refetch + upsert run details for the window. Returns a summary dict."""
    from core.run_ingest import REQUEST_DELAY_SEC, _store
    from mcp_tools.garmin_tool import (
        RUNNING_ACTIVITY_TYPES,
        fetch_garmin_activities,
        fetch_run_detail_raw,
        normalize_run_detail,
    )

    store = _store()
    activities = fetch_garmin_activities(days)
    candidates = [
        a for a in activities
        if (a.get("type") in RUNNING_ACTIVITY_TYPES) and a.get("activity_id") is not None
    ]
    logger.info("window %sd: %s activities, %s runs", days, len(activities), len(candidates))

    refetched = skipped = failed = 0
    for activity in candidates:
        aid = str(activity["activity_id"])
        existing = store.get_run(aid)
        if only_typed and existing and existing.get("splits_source") == "laps":
            skipped += 1
            logger.info("skip  %s %s — already per-lap", aid, existing.get("date"))
            continue
        if dry_run:
            refetched += 1
            logger.info(
                "would refetch %s %s %s (current splits_source=%s)",
                aid, activity.get("type"), activity.get("date"),
                (existing or {}).get("splits_source"),
            )
            continue
        try:
            raw = fetch_run_detail_raw(aid)
            doc = normalize_run_detail(
                activity, raw["details"], raw["splits"], raw["hr_zones"],
                typed_splits=raw.get("typed_splits", {}),
            )
            store.upsert(doc)
            refetched += 1
            logger.info(
                "resynced %s %s %s → splits_source=%s, %s laps",
                aid, doc.get("type"), doc.get("date"),
                doc.get("splits_source"), len(doc.get("splits") or []),
            )
        except Exception:
            failed += 1
            logger.warning("resync failed for %s", aid, exc_info=True)
        time.sleep(REQUEST_DELAY_SEC)

    summary = {"runs": len(candidates), "refetched": refetched, "skipped": skipped, "failed": failed}
    logger.info("done: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-typed", action="store_true")
    args = parser.parse_args()
    resync(days=args.days, dry_run=args.dry_run, only_typed=args.only_typed)


if __name__ == "__main__":
    main()
