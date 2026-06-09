"""One-off seed of Amit's performance-fueling anchors into the training profile.

Usage:
    python scripts/seed_nutrition_targets.py [--dry-run]

Writes the `nutrition_targets` block into users/amit via
``UserProfileStore.update`` (merge=True — leaves every other profile field
untouched). These are ANCHORS, not a fixed daily wall: Klaus derives the actual
per-day target from these plus the day's training load (see prompts/meal_audit.md).

Values reflect Amit's stated context: ~75 kg bodyweight (70–80 range), a
build/gain trajectory, eating for performance. Re-runnable — merge overwrites
only the nutrition_targets key.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Performance-fueling anchors (see plan + prompts/meal_audit.md).
NUTRITION_TARGETS: dict = {
    "bodyweight_kg": 75,
    "goal": "gain_build",
    "protein_g_per_kg": [1.8, 2.2],
    "protein_g_floor": 150,
    "calorie_posture": "slight_surplus",
    "fiber_g_floor": 30,
    "carb_periodization": (
        "Carbs scale with the day's training load: high on heavy lift / "
        "long-run days (fuel + recovery), moderate on easy days, lower on "
        "full rest. Emphasize pre- and post-session carbs."
    ),
    "notes": (
        "Anchors only — Klaus derives the day's actual target from today's "
        "training context (session type, ACWR, recent load)."
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the anchors and the current profile value without writing.",
    )
    args = parser.parse_args()

    from memory.firestore_db import UserProfileStore

    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

    current = store.load().get("nutrition_targets")
    logger.info("Current nutrition_targets: %s", current)
    logger.info("Seeding nutrition_targets: %s", NUTRITION_TARGETS)

    if args.dry_run:
        logger.info("--dry-run: no write performed.")
        return

    # Clean REPLACE of the nutrition_targets map (not a deep-merge): use
    # DocumentReference.update with a top-level field key, which overwrites the
    # whole map value. UserProfileStore.update() uses set(merge=True), which
    # would deep-merge and leave stale legacy keys behind, so we go direct here.
    # Other profile fields (dated_goals, weekly_split, ...) are untouched because
    # update() only writes the fields named.
    from memory.firestore_db import firestore as _fs
    store._doc_ref.update({
        "nutrition_targets": NUTRITION_TARGETS,
        "updated_at": _fs.SERVER_TIMESTAMP,
    })
    logger.info("Seeded (clean replace). New value: %s", store.load().get("nutrition_targets"))


if __name__ == "__main__":
    main()
