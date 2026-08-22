"""The current training block, derived from Amit's dated goals.

`current_block(dated_goals, today_iso, anchor_iso)` is a pure function:
- No I/O, no Firestore reads, no network. Never calls date.today() — the caller
  supplies today_iso (the CR-01 timezone lesson, same as projection.py).
- Never raises. Returns None when there is no block to report.

WHY THIS REPLACED THE OLD BLOCKS
--------------------------------
Blocks used to be documents seeded from a 16-week half-marathon blueprint, with
labels like "Deep Waters -> Peak Engine". Klaus reported them as "week 9 of 16,
Deep Waters -> Peak Engine", and Amit's response on 2026-08-21 was "I don't
really know what that means." He was not rejecting the week count — he asked to
keep it, along with how far through the block he is and how close its goal is.
What he was rejecting was a phase name from a plan he was not following.

So a block is now just the run-up to his next dated goal. That has three
properties the seeded blocks did not:

  - It maintains itself. When a race passes, the next block starts the next day.
    No start_block call, no re-seeding, nothing to go stale.
  - Its goal is a real target he cares about, so "am I close to the block's goal"
    is a question with an answer.
  - It ends. When every goal is behind him this returns None, rather than
    reporting a position in a plan that no longer exists — which is exactly the
    failure being corrected here.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Where the first block starts when no goal precedes it. Amit's current training
# period began here; it is only a fallback for the earliest block, since every
# later block starts the day after the previous goal.
DEFAULT_ANCHOR = "2026-06-21"


def _slug(text: str) -> str:
    """Lowercase, underscore-joined, punctuation stripped. Stable for a given label."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return cleaned or "goal"


def _as_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def current_block(
    dated_goals,
    today_iso: str,
    *,
    anchor_iso: str = DEFAULT_ANCHOR,
) -> dict | None:
    """Return the block running up to the next dated goal, or None.

    Args:
        dated_goals: Profile `dated_goals` — [{target_date, goal_label, metrics}].
                     Entries with an unparseable target_date are skipped rather
                     than poisoning the whole answer.
        today_iso:   "YYYY-MM-DD" (Asia/Jerusalem calendar date).
        anchor_iso:  Start of the first block, used only when no goal precedes
                     the upcoming one.

    Returns:
        None, or a JSON-safe dict:
          block_id        "{goal_date}_{slug}" — stable for the whole block, so
                          benchmarks logged weeks apart group together
          goal_label, goal_date, metrics, start_date,
          week_num        1-based, never exceeds total_weeks
          total_weeks     length of the block in weeks, minimum 1
          days_out        days until the goal; 0 on the day itself
          fraction_elapsed  0.0 at the start, 1.0 on the goal day
    """
    try:
        today = _as_date(today_iso)
        if today is None or not isinstance(dated_goals, (list, tuple)):
            return None

        parsed = []
        for goal in dated_goals:
            if not isinstance(goal, dict):
                continue
            target = _as_date(goal.get("target_date"))
            if target is not None:
                parsed.append((target, goal))
        if not parsed:
            return None
        parsed.sort(key=lambda pair: pair[0])

        # The goal day is still inside its own block — a race is not over until
        # it has been run.
        upcoming = next((pair for pair in parsed if pair[0] >= today), None)
        if upcoming is None:
            return None
        goal_date, goal = upcoming

        prior = [target for target, _ in parsed if target < goal_date]
        if prior:
            start = max(prior) + timedelta(days=1)
        else:
            start = _as_date(anchor_iso) or _as_date(DEFAULT_ANCHOR)
            if start is None:
                return None

        # A goal added mid-block, or an anchor later than today, must not produce
        # a negative week. Clamp rather than report nonsense.
        if start > today:
            start = today

        span_days = max((goal_date - start).days, 0)
        elapsed_days = max((today - start).days, 0)

        total_weeks = max(span_days // 7 + 1, 1)
        week_num = min(elapsed_days // 7 + 1, total_weeks)

        label = goal.get("goal_label") or "next goal"
        return {
            # Derived from the goal, not from today, so every call inside the block
            # returns the same id — log_benchmark is handed this by Klaus, and an
            # id that drifted would scatter one block's benchmarks across many.
            "block_id": f"{goal_date.isoformat()}_{_slug(label)}",
            "goal_label": label,
            "goal_date": goal_date.isoformat(),
            "metrics": goal.get("metrics") or {},
            "start_date": start.isoformat(),
            "week_num": week_num,
            "total_weeks": total_weeks,
            "days_out": max((goal_date - today).days, 0),
            "fraction_elapsed": round(elapsed_days / span_days, 3) if span_days else 1.0,
        }
    except Exception:
        logger.warning("current_block(%r) failed", today_iso, exc_info=True)
        return None
