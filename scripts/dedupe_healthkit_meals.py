"""One-off cleanup of duplicate HealthKit meal documents in Firestore.

Usage:
    python scripts/dedupe_healthkit_meals.py [--days N] [--apply]

Background
----------
Before the 2026-06-09 source_id fix, the iOS Shortcut's repeated daily syncs
(it re-sends the whole day on every Lifesum close) created a NEW Firestore
document each time a meal-time's calorie total drifted between syncs — because
the synthetic source_id embedded the integer calories. Meals piled up and daily
totals roughly doubled.

MealStore.get_day now de-duplicates at read time, so totals are already correct
without running this. This script is purely storage hygiene: it deletes the
stale duplicate documents so the raw collection matches what readers see.

Strategy (mirrors the read-time dedup):
    For each calendar day, group meal docs by (timestamp, source). Within a
    group keep the most-recently-written doc (max updated_at) and delete the
    rest. Documents whose source is not "healthkit" are left untouched.

Default is a DRY RUN. Pass --apply to actually delete.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / ".env"), override=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")


def _is_newer(candidate, incumbent) -> bool:
    if candidate is None:
        return False
    if incumbent is None:
        return True
    try:
        return candidate > incumbent
    except TypeError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30,
                        help="How many days back to scan (default 30).")
    parser.add_argument("--apply", action="store_true",
                        help="Actually delete duplicates (default: dry run).")
    args = parser.parse_args()

    from memory.firestore_db import _make_firestore_client

    client = _make_firestore_client(
        os.environ["GCP_PROJECT_ID"],
        os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    col = client.collection("meals")

    today = datetime.now(_TZ).date()
    total_dupes = 0
    for i in range(args.days):
        day = (today - timedelta(days=i)).isoformat()
        sub = col.document(day).collection("timestamps")
        # (timestamp, source) -> (updated_at, doc_id) of the keeper
        best: dict[tuple, tuple] = {}
        to_delete: list[str] = []
        for snap in sub.stream():
            d = snap.to_dict() or {}
            key = (d.get("timestamp", ""), d.get("source"))
            updated_at = d.get("updated_at")
            prev = best.get(key)
            if prev is None:
                best[key] = (updated_at, snap.id)
            elif _is_newer(updated_at, prev[0]):
                to_delete.append(prev[1])           # demote old keeper
                best[key] = (updated_at, snap.id)
            else:
                to_delete.append(snap.id)            # this one is the dupe
        if to_delete:
            total_dupes += len(to_delete)
            logger.info("%s: %d duplicate doc(s) %s", day, len(to_delete),
                        "DELETING" if args.apply else "(dry-run)")
            if args.apply:
                for doc_id in to_delete:
                    sub.document(doc_id).delete()

    logger.info("Done. %d duplicate doc(s) %s across %d days.",
                total_dupes, "deleted" if args.apply else "found (dry-run)", args.days)


if __name__ == "__main__":
    main()
