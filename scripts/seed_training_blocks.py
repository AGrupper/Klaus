"""Idempotent seed script: create 4 training block docs in Firestore training_blocks/.

Builds the 4 mesocycle block docs from the blueprint's 16-week training plan
(docs/hybrid_athlete_blueprint.md §4) and writes them to `training_blocks/` via
`BlockStore.upsert(merge=True)`. Also primes the `current_block_id` FK on
`users/amit` via `UserProfileStore.update`.

Usage:
    python scripts/seed_training_blocks.py [--dry-run] [--force]

Flags:
    --dry-run   Print the JSON payload without writing to Firestore.
    --force     Re-seed over existing blocks (e.g. after date corrections).

Re-running without --force is safe: the script declines to overwrite when blocks
already exist in the collection.

Locked block table (23-01-PLAN.md closed_sets / D-01/D-02/D-03):
  Block 1: "Aerobic Base"                          2026-06-21 → 2026-07-18  status "active"
  Block 2: "Capacity Build"                        2026-07-19 → 2026-08-15  status "pending"
  Block 3: "Deep Waters → Peak Engine"             2026-08-16 → 2026-09-12  status "pending"
  Block 4: "Race Specificity → Taper → Race Week"  2026-09-13 → 2026-10-10  status "pending"

All blocks: focus_facets = 5 standard facets; weekly_split_override = None;
benchmark_due = False; notes = "".
Status is bookkeeping metadata only — get_current() resolves by date range, so
seeding Blocks 2-4 as "pending" does NOT prevent them from becoming current as
their dates arrive (D-01).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)   # INVARIANT: override=True always

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure builder — no Firestore, no env dependencies
# ---------------------------------------------------------------------------

# 5-facet closed set (D-06) — must match _BENCHMARK_FACETS in memory/firestore_db.py
_FOCUS_FACETS = [
    "bench_press_1rm",
    "squat_1rm",
    "push_ups",
    "pull_ups",
    "threshold_pace",
]


def _label_to_slug(label: str) -> str:
    """Convert a block label to a Firestore-safe slug for the doc ID.

    Rules:
    - Lowercase
    - "→" and spaces → underscores
    - Collapse consecutive underscores
    - Strip leading/trailing underscores
    """
    slug = label.lower()
    slug = slug.replace("→", "_")
    slug = re.sub(r"[\s]+", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    slug = slug.strip("_")
    return slug


def build_blocks_list() -> list[dict]:
    """Build and return the 4 mesocycle block dicts from the blueprint.

    Source of truth: docs/hybrid_athlete_blueprint.md §4 (16-week training plan)
    and 23-01-PLAN.md closed_sets block.

    Returns a list of 4 block dicts ordered by start_date. Dates are contiguous
    and non-overlapping (required for date-range get_current to resolve exactly
    one block in-cycle).

    No Firestore imports or env vars — pure computation.
    """
    _raw = [
        {
            "label": "Aerobic Base",
            "start_date": "2026-06-21",
            "end_date": "2026-07-18",
            "status": "active",   # seed Block 1 active (its range includes anchor day 2026-06-21)
        },
        {
            "label": "Capacity Build",
            "start_date": "2026-07-19",
            "end_date": "2026-08-15",
            "status": "pending",
        },
        {
            "label": "Deep Waters → Peak Engine",
            "start_date": "2026-08-16",
            "end_date": "2026-09-12",
            "status": "pending",
        },
        {
            "label": "Race Specificity → Taper → Race Week",
            "start_date": "2026-09-13",
            "end_date": "2026-10-10",
            "status": "pending",   # D-02: Block 4 is race week — NEVER gets a benchmark
        },
    ]

    blocks = []
    for raw in _raw:
        label = raw["label"]
        start = raw["start_date"]
        slug = _label_to_slug(label)
        block_id = f"{start}_{slug}"
        blocks.append({
            "block_id": block_id,
            "label": label,
            "start_date": start,
            "end_date": raw["end_date"],
            "status": raw["status"],
            "focus_facets": list(_FOCUS_FACETS),
            "weekly_split_override": None,
            "notes": "",
            "benchmark_due": False,   # D-02: all blocks start False; set by cron near block end
        })

    return blocks


# ---------------------------------------------------------------------------
# Idempotent seed + main
# ---------------------------------------------------------------------------

def seed_if_absent(
    project_id: str,
    database: str = "(default)",
    force: bool = False,
) -> bool:
    """Seed the 4 training blocks if the collection is empty (or if force=True).

    Idempotency gate: if BlockStore.get_all() returns a non-empty list and
    force=False, logs a warning and returns False (no writes).

    When seeding (empty collection or force=True):
    1. Upserts all 4 blocks via BlockStore.upsert (merge=True — safe to re-run).
    2. Primes current_block_id FK on users/amit to Block 1's block_id via
       UserProfileStore.update (merge=True — only touches current_block_id).

    Args:
        project_id: GCP project ID.
        database:   Firestore database ID (default "(default)").
        force:      If True, seed even when blocks already exist.

    Returns:
        True if blocks were (re-)seeded; False if skipped (already exists + !force).
    """
    from memory.firestore_db import BlockStore, UserProfileStore

    block_store = BlockStore(project_id=project_id, database=database)
    existing = block_store.get_all()

    if existing and not force:
        logger.warning(
            "training_blocks collection already has %d docs. "
            "Pass --force to re-seed.",
            len(existing),
        )
        return False

    blocks = build_blocks_list()
    for block in blocks:
        block_store.upsert(block)
        logger.info("Upserted block: %s (%s → %s)", block["label"], block["start_date"], block["end_date"])

    # Prime the current_block_id FK on users/amit to Block 1
    profile_store = UserProfileStore(project_id=project_id, database=database)
    profile_store.update({"current_block_id": blocks[0]["block_id"]})
    logger.info("Primed current_block_id → %r", blocks[0]["block_id"])

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotent seed script: create 4 mesocycle training blocks in "
            "Firestore training_blocks/ from the hybrid athlete blueprint."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the JSON payload without writing to Firestore.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-seed over existing blocks (e.g. after date corrections). "
            "Without this flag the script declines to overwrite when blocks "
            "are already present."
        ),
    )
    args = parser.parse_args()

    blocks = build_blocks_list()

    if args.dry_run:
        print(json.dumps(blocks, indent=2, ensure_ascii=False))
        logger.info("--dry-run: payload printed above, no Firestore write performed.")
        return

    try:
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        seeded = seed_if_absent(project_id=project_id, database=database, force=args.force)
        if seeded:
            logger.info(
                "Seed complete — 4 training blocks written to training_blocks/. "
                "current_block_id primed to Block 1 (%s).",
                blocks[0]["block_id"],
            )
    except Exception:
        logger.error("Seed failed", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
