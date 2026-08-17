"""One-off: group existing slot-based habits into the two starter routines.

Paper Hub migration — creates "Morning routine" (Morning + Noon slots) and
"Nightly routine" (Evening + Bedtime slots) and stamps ``routine_id`` on every
active habit that doesn't have one yet. Completion history is untouched; the
``slot`` field is kept on each habit for back-compat.

Idempotent: routines are looked up by name before creating, and habits that
already carry a ``routine_id`` are skipped. Safe to re-run.

Run locally (needs GCP creds + .env):
    .venv/bin/python -m scripts.migrate_habits_to_routines
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SLOT_TO_ROUTINE = {
    "Morning": "Morning routine",
    "Noon": "Morning routine",
    "Evening": "Nightly routine",
    "Bedtime": "Nightly routine",
}
# anchor_time places each routine in the Today timeline (morning above the
# day's first meeting, nightly at the end) instead of collecting at the bottom.
_ROUTINE_SEEDS = [
    {"name": "Morning routine", "emoji": "☀️", "order": 0,
     "anchor_time": "07:00", "color": "#B0762A"},
    {"name": "Nightly routine", "emoji": "🌙", "order": 1,
     "anchor_time": "21:30", "color": "#4C4C8F"},
]


def main() -> int:
    load_dotenv(override=True)  # override: shell exports must not shadow .env
    from memory.firestore_db import HabitStore, RoutineStore

    project = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    if not project:
        logger.error("GCP_PROJECT_ID is not set — aborting")
        return 1

    routine_store = RoutineStore(project, database)
    habit_store = HabitStore(project, database)

    # Ensure the two starter routines exist (by name, idempotent)
    existing = {r.get("name"): r for r in routine_store.list_all()}
    routines_by_name: dict[str, dict] = {}
    for seed in _ROUTINE_SEEDS:
        if seed["name"] in existing:
            routines_by_name[seed["name"]] = existing[seed["name"]]
            logger.info("Routine %r already exists (%s)", seed["name"], existing[seed["name"]]["id"])
        else:
            created = routine_store.create(dict(seed))
            routines_by_name[seed["name"]] = created
            logger.info("Created routine %r (%s)", seed["name"], created["id"])

    # Stamp routine_id on active habits that lack one
    migrated = skipped = 0
    for habit in habit_store.list_active():
        if habit.get("routine_id"):
            skipped += 1
            continue
        slot = habit.get("slot", "Morning")
        routine = routines_by_name[_SLOT_TO_ROUTINE.get(slot, "Morning routine")]
        habit_store.update(habit["id"], {"routine_id": routine["id"]})
        migrated += 1
        logger.info("  %s (%s slot) → %s", habit.get("name"), slot, routine["name"])

    logger.info("Done: %d migrated, %d already assigned.", migrated, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
