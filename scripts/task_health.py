"""Report the task-list health figures behind the success criteria.

The design at docs/superpowers/specs/2026-08-14-klaus-task-partnership-design.md
sets numeric targets against a 2026-08-14 baseline: 17 real to-dos, 1 dated,
0 with deadlines, 2 filed, median age 116 days. This prints the same figures so
the targets can actually be checked.

Read-only. Every number comes from the Things mirror; no new storage.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/task_health.py
"""
from __future__ import annotations

import statistics
from datetime import date


def summarize(tasks: list[dict], today: str) -> dict:
    """Count the success-criteria figures over normalized Things to-dos.

    Args:
        tasks: normalized to-dos from ``things_tool.live_todos()``.
        today: ISO date the ages are measured against.

    Returns:
        Counts plus median and oldest age in days.  Both ages are ``None`` when
        no to-do carries a usable ``created_at`` — a report must never divide by
        zero on an empty list.

        The median is **truncated** to whole days, not rounded: these are whole
        elapsed days, and rounding an even-length median of 39.5 up to 40 would
        report an age no to-do actually has.
    """
    reference = date.fromisoformat(today)
    ages = [
        (reference - date.fromisoformat(str(task["created_at"])[:10])).days
        for task in tasks
        if task.get("created_at")
    ]
    return {
        "total": len(tasks),
        "dated": sum(1 for t in tasks if t.get("due_date")),
        "with_deadline": sum(1 for t in tasks if t.get("hard_deadline_at")),
        "filed": sum(1 for t in tasks if t.get("project_name") or t.get("area_name")),
        "median_age_days": int(statistics.median(ages)) if ages else None,
        "oldest_age_days": max(ages) if ages else None,
    }


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(override=True)
    import mcp_tools.things_tool as things

    state, _head = things.replay_journal(things.fetch_history_key()["history-key"])
    report = summarize(things.live_todos(state), things.today_iso())
    baseline = {"total": 17, "dated": 1, "with_deadline": 0, "filed": 2,
                "median_age_days": 116}
    for key, value in report.items():
        was = baseline.get(key)
        suffix = f"   (2026-08-14 baseline: {was})" if was is not None else ""
        print(f"{key:18} {value}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
