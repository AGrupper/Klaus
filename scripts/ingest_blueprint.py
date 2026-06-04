"""Idempotent seed script: ingest docs/hybrid_athlete_blueprint.md → Firestore users/amit.

Builds the v4.0 structured profile dict from the in-repo blueprint (source of truth)
and writes it to `users/amit` via `UserProfileStore.update(merge=True)`.

Usage:
    python scripts/ingest_blueprint.py [--dry-run] [--force]

Flags:
    --dry-run   Print the JSON payload without writing to Firestore.
    --force     Re-ingest over existing v4.0 fields (e.g. after blueprint edits).

Re-running without --force is safe: the script declines to overwrite when v4.0
fields (detected via plan_start_date presence) already exist.

Locked narrowings (21-CONTEXT.md):
  1. The 16-week aerobic pace/volume table (Section 4) is NEVER stored as tracked
     target rows — at most a loose directional note string.
  2. No current-performance baselines — dated_goals holds Tier A targets only.

Source: docs/hybrid_athlete_blueprint.md (committed df696c4, stable)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)          # INVARIANT: override=True always

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure builder — no Firestore, no env dependencies
# ---------------------------------------------------------------------------

def build_profile_dict() -> dict:
    """Build and return the v4.0 structured profile dict from the blueprint.

    Source of truth: docs/hybrid_athlete_blueprint.md
    Content transcribed from the stable, committed blueprint document.
    All values are Tier A targets only — no current-performance baselines.

    Returns a dict with exactly these six keys:
        dated_goals, weekly_split, nutrition_targets, supplement_schedule,
        fueling_timeline, plan_start_date
    """
    # ------------------------------------------------------------------
    # Section 1: Performance Objectives — dated peak goals
    # Blueprint: Oct peak (100kg bench, 120kg squat, 1:25 HM)
    #            Nov peak (125 push-ups, 35 pull-ups, 9:30 3k, 55s 400m)
    # ------------------------------------------------------------------
    dated_goals = [
        {
            "target_date": "2026-10-31",
            "goal_label": "October Peak — Absolute Strength + Half Marathon",
            "metrics": {
                "bench_press_kg": 100,
                "squat_kg": 120,
                "half_marathon_time": "1:25:00",
            },
        },
        {
            "target_date": "2026-11-30",
            "goal_label": "November Peak — Calisthenics + Speed",
            "metrics": {
                "push_ups": 125,
                "pull_ups": 35,
                "3k_time": "9:30",
                "400m_time": "55s",
            },
        },
    ]

    # ------------------------------------------------------------------
    # Section 2: AM/PM Split — 7-day flexible training template
    # Encoded as session shape (label, modality, priority).
    # This is a TEMPLATE, NOT an attendance contract.
    # Modalities: run / lift / calisthenics / mobility / rest
    # NO keys named: done, completed, attended, attendance
    # ------------------------------------------------------------------
    weekly_split = {
        "sunday": {
            "am": {
                "label": "Passive Rest / Sleep In",
                "modality": "rest",
                "priority": "recovery",
            },
            "pm": {
                "label": "Mixed Practice (Sprints, VO2 Max, Calisthenics)",
                "modality": "calisthenics",
                "priority": "high — quality work after full morning rest",
            },
        },
        "monday": {
            "am": {
                "label": "Easy Run (Leg flush from Sunday)",
                "modality": "run",
                "priority": "low — flush/recovery pace only",
            },
            "pm": {
                "label": "Lower Body A — Heavy Absolute Strength",
                "modality": "lift",
                "priority": "high — primary strength day",
            },
        },
        "tuesday": {
            "am": {
                "label": "Medium Long Run + 6x20s Strides",
                "modality": "run",
                "priority": "medium — aerobic volume + neuromuscular activation",
            },
            "pm": {
                "label": "Upper Body A — Heavy Push/Pull + Dropset",
                "modality": "lift",
                "priority": "high — primary upper strength day",
            },
        },
        "wednesday": {
            "am": {
                "label": "Threshold Run (The 1:25 HM Engine)",
                "modality": "run",
                "priority": "high — key aerobic quality session",
            },
            "pm": {
                "label": "Lower Body B — Speed/Hypertrophy + Core",
                "modality": "lift",
                "priority": "medium — speed/power focus",
            },
        },
        "thursday": {
            "am": {
                "label": "Easy Run (Active Recovery)",
                "modality": "run",
                "priority": "low — active recovery; effort strictly easy",
            },
            "pm": {
                "label": "Upper Body B — Volume/Capacity",
                "modality": "lift",
                "priority": "medium — volume ceiling day",
            },
        },
        "friday": {
            "am": {
                "label": "Long Run (Endurance Focus)",
                "modality": "run",
                "priority": "high — primary aerobic endurance session",
            },
            "pm": {
                "label": "Mobility, Injury Prevention & Sauna",
                "modality": "mobility",
                "priority": "medium — recovery quality matters for Saturday rest",
            },
        },
        "saturday": {
            "am": {
                "label": "Complete Rest / Light Flush Movement",
                "modality": "rest",
                "priority": "full recovery — no structured load",
            },
            "pm": {
                "label": "Complete Passive Rest",
                "modality": "rest",
                "priority": "full recovery",
            },
        },
    }

    # ------------------------------------------------------------------
    # Section 6: Fueling Architecture (150g Protein / 350g Carbs)
    # 6 ordered slots.
    # Section 4 (16-week aerobic table) is NOT ingested as target rows —
    # stored only as a loose directional note string.
    # ------------------------------------------------------------------
    fueling_timeline = [
        {
            "slot": "pre-am-run",
            "timing": "Before AM run",
            "food": "30-50g simple carbs (banana / electrofuel) + Coffee",
            "supplements": [],
        },
        {
            "slot": "post-am-run",
            "timing": "After AM run (reload)",
            "food": "Massive carbohydrate hit (oats / rice / sourdough) + 3-4 whole eggs",
            "supplements": ["Vitamin D3+K2", "Omega 3"],
        },
        {
            "slot": "mid-day",
            "timing": "Mid-day (sustained engine)",
            "food": "Lean beef / steak, complex carbs, and leafy greens",
            "supplements": [],
        },
        {
            "slot": "pm-pre-lift",
            "timing": "30-60 minutes before PM lift",
            "food": "Electrofuel or fruit",
            "supplements": ["Beta-Alanine"],
        },
        {
            "slot": "pm-post-lift",
            "timing": "After PM lift (rebuild)",
            "food": "High protein (beef / poultry) and easily digestible carbs",
            "supplements": ["Creatine"],
        },
        {
            "slot": "pre-bed",
            "timing": "30-60 minutes before sleep",
            "food": "Light snack if needed",
            "supplements": ["Magnesium Glycinate", "Zinc", "Copper"],
        },
    ]

    supplement_schedule = [
        {
            "slot": "post-am-run",
            "items": ["Vitamin D3+K2", "Omega 3"],
            "note": "Take with the post-run reload meal",
        },
        {
            "slot": "pm-pre-lift",
            "items": ["Beta-Alanine"],
            "note": "30-60 minutes before lift",
        },
        {
            "slot": "pm-post-lift",
            "items": ["Creatine"],
            "note": "Add to shake or water",
        },
        {
            "slot": "pre-bed",
            "items": ["Magnesium Glycinate", "Zinc", "Copper"],
            "note": "30-60 minutes before sleep — parasympathetic support",
        },
    ]

    nutrition_targets = {
        "protein_g": 150,
        "carbs_g": 350,
        "fueling_slots": [
            "pre-am-run", "post-am-run", "mid-day",
            "pm-pre-lift", "pm-post-lift", "pre-bed",
        ],
        # Loose directional note only — NOT a tracked 16-week target structure.
        # Paces and volumes here are for general orientation; Amit adjusts week-to-week.
        "aerobic_reference_note": (
            "16-week aerobic progression (Section 4): target HM pace 4:01/km, "
            "Zone 2 range 4:50-5:30/km. Long runs scale 16km→26km over 16 weeks "
            "with deload weeks at W4/8/12. Treat as directional context only — "
            "never as per-week contracts."
        ),
    }

    return {
        "dated_goals": dated_goals,
        "weekly_split": weekly_split,
        "nutrition_targets": nutrition_targets,
        "supplement_schedule": supplement_schedule,
        "fueling_timeline": fueling_timeline,
        "plan_start_date": "2026-06-21",
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest docs/hybrid_athlete_blueprint.md structured fields into "
            "Firestore users/amit via UserProfileStore.update (merge=True)."
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
            "Re-ingest over existing v4.0 fields (e.g. after blueprint edits). "
            "Without this flag the script declines to overwrite when v4.0 fields "
            "are already present."
        ),
    )
    args = parser.parse_args()

    payload = build_profile_dict()

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info("--dry-run: payload printed above, no Firestore write performed.")
        return

    # Construct Firestore client
    try:
        from memory.firestore_db import UserProfileStore

        store = UserProfileStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )

        # Idempotency gate: check whether v4.0 fields already exist
        if not args.force:
            existing = store.load()
            if existing.get("plan_start_date"):
                logger.warning(
                    "v4.0 fields already present (plan_start_date=%r). "
                    "Pass --force to re-ingest.",
                    existing["plan_start_date"],
                )
                return

        # Bump the schema marker so the stored doc's version matches the v4.0
        # structure it now holds. merge=True only touches keys in the payload, so
        # without this the marker would stay at the legacy value (1) and mislead
        # any future schema migration that keys off schema_version.
        store.update({**payload, "schema_version": 2})
        logger.info(
            "Blueprint ingested successfully into users/amit (plan_start_date=%s, schema_version=2).",
            payload["plan_start_date"],
        )

    except Exception:
        logger.error("Ingest failed", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
