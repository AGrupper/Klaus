"""Replace the retired blueprint's goals in users/amit with the real ones.

Safe to re-run — it overwrites dated_goals wholesale rather than appending.

Run once, on 2026-08-21 or later:

    PYTHONPATH=. .venv/bin/python scripts/active/retire_blueprint_goals.py          # dry run
    PYTHONPATH=. .venv/bin/python scripts/active/retire_blueprint_goals.py --apply

Why this exists rather than `update_plan` through Klaus: `weekly_split` is a
nested map, and every write path Klaus has uses `set(merge=True)`. Firestore
deep-merges nested maps, so writing `{"weekly_split": {}}` leaves all seven
weekdays exactly where they were. Only the DELETE_FIELD sentinel actually
clears it, and no MCP tool can send a sentinel.

The stored goals were the October/November blueprint: a 100kg bench, 35
pull-ups, 125 push-ups, a 9:30 3K and a 16:59 5K. Amit restated them on
2026-08-21 — see the `goals` section of docs/USER.md, which is the source this
mirrors.
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from google.cloud import firestore  # noqa: E402

from memory.stores import base  # noqa: E402

DATED_GOALS = [
    {"target_date": "2026-10-09", "goal_label": "5K race",
     "metrics": {"five_k_time": "17:30"}},
    {"target_date": "2026-10-28", "goal_label": "15K race",
     "metrics": {"fifteen_k_pace": "4:00/km"}},
    # Label stays short: it is rendered in the Hub's training row as
    # "Week N of M — <label>". The date is a mid-November estimate; Amit does not
    # know the real one yet and has no way to check, so this is deliberately
    # approximate rather than false precision.
    {"target_date": "2026-11-15", "goal_label": "November test day",
     "metrics": {"pull_ups": 26, "push_ups": 85, "3k_time": "9:45", "400m_time": "56s"}},
]


def main() -> int:
    apply = "--apply" in sys.argv
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        print("GCP_PROJECT_ID is unset — nothing to do.")
        return 1
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")

    client = base._make_firestore_client(project_id, database)
    ref = client.collection("users").document("amit")

    current = (ref.get().to_dict() or {})
    print("BEFORE")
    print("  dated_goals :", json.dumps(current.get("dated_goals"), ensure_ascii=False))
    print("  weekly_split:", sorted((current.get("weekly_split") or {}).keys()))

    payload = {
        "dated_goals": DATED_GOALS,
        "weekly_split": firestore.DELETE_FIELD,
        "athletic_goals": [],
        "updated_at": firestore.SERVER_TIMESTAMP,
    }

    print("\nAFTER")
    print("  dated_goals :", json.dumps(DATED_GOALS, ensure_ascii=False))
    print("  weekly_split: <deleted>")

    if not apply:
        print("\nDry run — pass --apply to write.")
        return 0

    ref.set(payload, merge=True)
    after = (ref.get().to_dict() or {})
    ok = "weekly_split" not in after and len(after.get("dated_goals") or []) == 3
    print("\nApplied. weekly_split cleared:", "weekly_split" not in after,
          "| dated_goals:", len(after.get("dated_goals") or []))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
