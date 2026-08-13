"""Diff Klaus's generated Things payload against a Things-authored one.

READ-ONLY. Writes nothing, and never references the commit endpoint.

Things Cloud accepts malformed records and fails *later* — a wrong note checksum
took down both of Amit's clients on 2026-08-13 with an assertion inside the sync
replay. So the safe way to validate a write is to build the payload locally and
compare it against one the real app produced for an equivalent to-do, rather than
committing it and watching what happens.

Usage::

    .venv/bin/python scripts/diff_things_payload.py --title reference

Create the reference to-do in Things first, with as many features set as
possible (note, When, deadline, reminder, tag, checklist, repeat, project).
"""
from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

load_dotenv(override=True)

import mcp_tools.things_tool as things  # noqa: E402

# Fields Klaus never authors: server-assigned, ordering, or Things-internal
# bookkeeping. Differences here are expected and not bugs.
_IGNORED = {"cd", "md", "ix", "ti", "lai", "sp", "icsd", "icc"}


def _fetch_state() -> dict:
    account = things.fetch_history_key()
    state, _ = things.replay_journal(account["history-key"])
    return state


def _find(state: dict, title: str) -> tuple[str, dict] | None:
    for uuid, payload in state.items():
        if payload.get("_class") == things.CLASS_TASK and payload.get("tt") == title:
            return uuid, payload
    return None


def _describe(state: dict, uuid: str, payload: dict) -> None:
    """Print the Things-authored record plus anything that references it."""
    print("=" * 72)
    print(f"THINGS-AUTHORED RECORD  ({uuid})")
    print("=" * 72)
    print(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True))

    checklist = [
        (u, p) for u, p in state.items()
        if p.get("_class") == things.CLASS_CHECKLIST and uuid in (p.get("ts") or [])
    ]
    if checklist:
        print(f"\n--- {len(checklist)} checklist item(s) (ChecklistItem3) ---")
        for u, p in checklist:
            print(f"  {u}: {json.dumps(p, ensure_ascii=False, sort_keys=True)}")

    if payload.get("rr"):
        print("\n--- recurrence rule (rr) ---")
        print(json.dumps(payload["rr"], indent=1, sort_keys=True))
        spawned = [
            (u, p.get("tt"), things.day_to_iso(p.get("sr")))
            for u, p in state.items() if uuid in (p.get("rt") or [])
        ]
        print(f"spawned instances pointing back via rt: {spawned}")


def _mine(payload: dict, state: dict) -> dict:
    """Build what Klaus would send for an equivalent to-do."""
    note = payload.get("nt") or {}
    project = (payload.get("pr") or [None])[0]
    area = (payload.get("ar") or [None])[0]
    _uuid, record = things.build_create(
        payload.get("tt") or "",
        notes=note.get("v") or None,
        due_date=things.day_to_iso(payload.get("sr")),
        due_time=things.seconds_to_hhmm(payload.get("ato")),
        hard_deadline_at=things.day_to_iso(payload.get("dd")),
        project_id=project,
        area_id=area,
        tag_ids=payload.get("tg") or None,
    )
    return record["p"]


def _diff(theirs: dict, mine: dict) -> int:
    print("\n" + "=" * 72)
    print("DIFF — Klaus's payload vs Things'")
    print("=" * 72)

    missing = sorted(set(theirs) - set(mine) - _IGNORED)
    extra = sorted(set(mine) - set(theirs) - _IGNORED)
    if missing:
        print(f"\n!! keys Things sends that Klaus does NOT: {missing}")
    if extra:
        print(f"\n!! keys Klaus sends that Things does NOT: {extra}")

    problems = len(missing) + len(extra)
    print()
    for key in sorted(set(theirs) & set(mine)):
        if key in _IGNORED:
            continue
        t, m = theirs[key], mine[key]
        if t == m:
            print(f"  ok    {key:6} {json.dumps(t, ensure_ascii=False)[:58]}")
        else:
            problems += 1
            print(f"  DIFF  {key:6} things={json.dumps(t, ensure_ascii=False)[:44]}")
            print(f"        {'':6} klaus ={json.dumps(m, ensure_ascii=False)[:44]}")

    print("\n" + ("PAYLOADS MATCH — safe to write" if problems == 0
                  else f"{problems} mismatch(es) — fix before writing"))
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="reference",
                        help="title of the reference to-do created in Things")
    args = parser.parse_args()

    state = _fetch_state()
    found = _find(state, args.title)
    if not found:
        titles = sorted(
            p.get("tt", "") for p in state.values()
            if p.get("_class") == things.CLASS_TASK and p.get("tt")
        )
        raise SystemExit(
            f"No to-do titled {args.title!r}. Titles present:\n  "
            + "\n  ".join(titles[:40])
        )

    uuid, payload = found
    _describe(state, uuid, payload)
    _diff(payload, _mine(payload, state))


if __name__ == "__main__":
    main()
