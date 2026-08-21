"""Tests for core/training/goal_blocks.py — the goal-derived training block.

The block Amit sees used to be a phase of a 16-week half-marathon build, labelled
"Deep Waters -> Peak Engine". He said of it: "I don't really know what that means."
What he asked for instead is which week he is in, how far through the block he is,
and how close the block's goal is. So a block is now simply the run-up to his next
dated goal, and it maintains itself as each race passes.
"""
from __future__ import annotations

from core.training.goal_blocks import current_block

GOALS = [
    {"target_date": "2026-10-09", "goal_label": "5K race",
     "metrics": {"five_k_time": "17:30"}},
    {"target_date": "2026-10-28", "goal_label": "15K race",
     "metrics": {"fifteen_k_pace": "4:00/km"}},
    {"target_date": "2026-11-15", "goal_label": "November test day",
     "metrics": {"pull_ups": 26}},
]
ANCHOR = "2026-06-21"


class TestBlockIdentity:
    def test_block_is_the_run_up_to_the_next_goal(self):
        b = current_block(GOALS, "2026-08-21", anchor_iso=ANCHOR)
        assert b["goal_label"] == "5K race"
        assert b["goal_date"] == "2026-10-09"

    def test_first_block_starts_at_the_anchor(self):
        """With no goal behind it, the block runs from the training anchor."""
        b = current_block(GOALS, "2026-08-21", anchor_iso=ANCHOR)
        assert b["start_date"] == ANCHOR

    def test_later_block_starts_the_day_after_the_previous_goal(self):
        """Once a race is behind him the next block begins itself — no start_block call."""
        b = current_block(GOALS, "2026-10-20", anchor_iso=ANCHOR)
        assert b["goal_label"] == "15K race"
        assert b["start_date"] == "2026-10-10"

    def test_goal_day_itself_is_still_inside_its_block(self):
        b = current_block(GOALS, "2026-10-09", anchor_iso=ANCHOR)
        assert b["goal_label"] == "5K race"
        assert b["days_out"] == 0

    def test_returns_none_once_every_goal_is_past(self):
        """No invented block. The absence is the honest answer — this is the
        failure the old code made, reporting a week of a plan that had ended."""
        assert current_block(GOALS, "2026-12-01", anchor_iso=ANCHOR) is None

    def test_returns_none_without_goals(self):
        assert current_block([], "2026-08-21", anchor_iso=ANCHOR) is None


class TestWeekCounting:
    def test_week_one_is_the_first_seven_days(self):
        assert current_block(GOALS, "2026-06-21", anchor_iso=ANCHOR)["week_num"] == 1
        assert current_block(GOALS, "2026-06-27", anchor_iso=ANCHOR)["week_num"] == 1

    def test_week_two_starts_on_day_eight(self):
        assert current_block(GOALS, "2026-06-28", anchor_iso=ANCHOR)["week_num"] == 2

    def test_the_old_week_nine_of_sixteen_is_true_again_pointed_at_the_5k(self):
        """The retired blueprint was not wrong about the arithmetic — 16 weeks from
        2026-06-21 lands two days past the 5K. Only the label was wrong."""
        b = current_block(GOALS, "2026-08-21", anchor_iso=ANCHOR)
        assert (b["week_num"], b["total_weeks"]) == (9, 16)

    def test_week_never_exceeds_total(self):
        b = current_block(GOALS, "2026-10-09", anchor_iso=ANCHOR)
        assert b["week_num"] <= b["total_weeks"]


class TestProgress:
    def test_days_out_counts_down_to_the_goal(self):
        assert current_block(GOALS, "2026-10-02", anchor_iso=ANCHOR)["days_out"] == 7

    def test_fraction_through_block_runs_zero_to_one(self):
        start = current_block(GOALS, "2026-06-21", anchor_iso=ANCHOR)
        end = current_block(GOALS, "2026-10-09", anchor_iso=ANCHOR)
        assert start["fraction_elapsed"] == 0.0
        assert end["fraction_elapsed"] == 1.0

    def test_target_metrics_ride_along(self):
        """"Am I close to the goal" needs the goal's numbers, not just its name."""
        b = current_block(GOALS, "2026-08-21", anchor_iso=ANCHOR)
        assert b["metrics"] == {"five_k_time": "17:30"}


class TestNeverRaises:
    def test_malformed_goals_are_skipped_not_fatal(self):
        junk = [{"target_date": "not-a-date", "goal_label": "junk"}, GOALS[0]]
        assert current_block(junk, "2026-08-21", anchor_iso=ANCHOR)["goal_label"] == "5K race"

    def test_garbage_input_returns_none(self):
        assert current_block("not a list", "2026-08-21", anchor_iso=ANCHOR) is None
        assert current_block(GOALS, "nonsense", anchor_iso=ANCHOR) is None

    def test_bad_anchor_falls_back_rather_than_raising(self):
        b = current_block(GOALS, "2026-08-21", anchor_iso="nonsense")
        assert b is None or b["goal_label"] == "5K race"
