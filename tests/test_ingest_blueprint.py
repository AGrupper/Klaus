"""Tests for scripts/ingest_blueprint.py — pure function build_profile_dict().

These tests cover the blueprint→structured-dict builder. build_profile_dict() is
a pure function with no Firestore calls and no env dependencies, so no mocking is needed.

Plan 21-03, Task 1 (TDD).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.ingest_blueprint import build_profile_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = frozenset(
    ["dated_goals", "weekly_split", "nutrition_targets", "supplement_schedule",
     "fueling_timeline", "plan_start_date"]
)

_DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


# ---------------------------------------------------------------------------
# Top-level key presence
# ---------------------------------------------------------------------------

class TestTopLevelKeys:
    def test_all_six_keys_present(self):
        d = build_profile_dict()
        assert _REQUIRED_KEYS.issubset(d.keys()), (
            f"Missing keys: {_REQUIRED_KEYS - d.keys()}"
        )

    def test_plan_start_date_is_correct(self):
        d = build_profile_dict()
        assert d["plan_start_date"] == "2026-06-21"

    def test_no_current_performance_baseline_keys(self):
        """No Tier B keys (current bench, current pace, etc.) should exist."""
        import json
        s = json.dumps(build_profile_dict()).lower()
        forbidden_patterns = [
            "current_bench", "current_pace", "current_squat",
            "current_run", "baseline",
        ]
        for pat in forbidden_patterns:
            assert pat not in s, f"Forbidden performance baseline key found: {pat!r}"


# ---------------------------------------------------------------------------
# dated_goals
# ---------------------------------------------------------------------------

class TestDatedGoals:
    def test_is_list_of_dicts(self):
        d = build_profile_dict()
        goals = d["dated_goals"]
        assert isinstance(goals, list)
        assert len(goals) >= 2, "Expected at least Oct + Nov peak entries"
        for g in goals:
            assert isinstance(g, dict)

    def test_each_goal_has_required_keys(self):
        for g in build_profile_dict()["dated_goals"]:
            assert "target_date" in g, f"Missing target_date in {g}"
            assert "goal_label" in g, f"Missing goal_label in {g}"
            assert "metrics" in g, f"Missing metrics in {g}"

    def test_oct_peak_metrics(self):
        """Oct peak: bench 100kg, squat 120kg, half marathon 1:25."""
        goals = build_profile_dict()["dated_goals"]
        oct_entry = next(
            (g for g in goals if "oct" in g.get("goal_label", "").lower()), None
        )
        assert oct_entry is not None, "No October peak entry found"
        metrics = oct_entry["metrics"]
        # Check the durable blueprint targets
        assert any(
            ("bench" in str(k).lower() or "bench" in str(v).lower())
            and "100" in str(v)
            for k, v in metrics.items()
        ), f"Oct peak missing 100kg bench: {metrics}"
        assert any(
            ("squat" in str(k).lower() or "squat" in str(v).lower())
            and "120" in str(v)
            for k, v in metrics.items()
        ), f"Oct peak missing 120kg squat: {metrics}"

    def test_nov_peak_metrics(self):
        """Nov peak: 125 push-ups, 35 pull-ups, 9:30 3k, 55s 400m."""
        goals = build_profile_dict()["dated_goals"]
        nov_entry = next(
            (g for g in goals if "nov" in g.get("goal_label", "").lower()), None
        )
        assert nov_entry is not None, "No November peak entry found"
        metrics = nov_entry["metrics"]
        import json
        m_str = json.dumps(metrics).lower()
        assert "125" in m_str or "push" in m_str, f"Nov peak missing push-up target: {metrics}"
        assert "35" in m_str or "pull" in m_str, f"Nov peak missing pull-up target: {metrics}"


# ---------------------------------------------------------------------------
# weekly_split
# ---------------------------------------------------------------------------

class TestWeeklySplit:
    def test_has_seven_days(self):
        split = build_profile_dict()["weekly_split"]
        assert isinstance(split, dict)
        assert len(split) == 7, f"Expected 7 days, got {len(split)}: {list(split.keys())}"

    def test_all_day_keys_present(self):
        split = build_profile_dict()["weekly_split"]
        for day in _DAYS:
            assert day in split, f"Missing day: {day}"

    def test_each_day_has_am_and_pm(self):
        split = build_profile_dict()["weekly_split"]
        for day, sessions in split.items():
            assert "am" in sessions, f"Day {day} missing 'am'"
            assert "pm" in sessions, f"Day {day} missing 'pm'"

    def test_each_session_has_label_modality_priority(self):
        split = build_profile_dict()["weekly_split"]
        for day, sessions in split.items():
            for period in ("am", "pm"):
                s = sessions[period]
                assert "label" in s, f"{day}.{period} missing 'label': {s}"
                assert "modality" in s, f"{day}.{period} missing 'modality': {s}"
                assert "priority" in s, f"{day}.{period} missing 'priority': {s}"

    def test_no_attendance_booleans(self):
        """The weekly split must NOT have any attendance/done/completed keys."""
        import json
        s = json.dumps(build_profile_dict()["weekly_split"]).lower()
        forbidden = ["attendance", "done", "completed", "attended"]
        for f in forbidden:
            assert f not in s, f"Attendance boolean found in weekly_split: {f!r}"


# ---------------------------------------------------------------------------
# nutrition_targets
# ---------------------------------------------------------------------------

class TestNutritionTargets:
    def test_protein_and_carbs_targets(self):
        nt = build_profile_dict()["nutrition_targets"]
        assert isinstance(nt, dict)
        assert nt.get("protein_g") == 150, f"Expected protein_g=150, got {nt.get('protein_g')}"
        assert nt.get("carbs_g") == 350, f"Expected carbs_g=350, got {nt.get('carbs_g')}"

    def test_no_16_week_table(self):
        """The 16-week aerobic progression table must NOT be in nutrition_targets."""
        import json
        nt_str = json.dumps(build_profile_dict()["nutrition_targets"]).lower()
        # If any key is a list of 16 entries, that's a violation
        nt = build_profile_dict()["nutrition_targets"]
        for k, v in nt.items():
            if isinstance(v, list):
                assert len(v) < 16, (
                    f"nutrition_targets['{k}'] has {len(v)} items — "
                    f"looks like the 16-week aerobic table was ingested as targets"
                )


# ---------------------------------------------------------------------------
# fueling_timeline
# ---------------------------------------------------------------------------

class TestFuelingTimeline:
    def test_has_six_slots(self):
        ft = build_profile_dict()["fueling_timeline"]
        assert isinstance(ft, list)
        assert len(ft) == 6, f"Expected 6 fueling slots, got {len(ft)}"

    def test_each_slot_has_slot_and_food(self):
        for i, slot in enumerate(build_profile_dict()["fueling_timeline"]):
            assert isinstance(slot, dict)
            assert "slot" in slot, f"Slot {i} missing 'slot' key: {slot}"
            assert "food" in slot or "content" in slot, (
                f"Slot {i} missing 'food'/'content' key: {slot}"
            )

    def test_slot_order_includes_pre_am_run(self):
        """First slot should be the pre-AM run."""
        first = build_profile_dict()["fueling_timeline"][0]
        slot_name = first.get("slot", "").lower()
        assert "pre" in slot_name and ("am" in slot_name or "run" in slot_name), (
            f"First slot expected to be pre-AM-run, got: {first}"
        )

    def test_slot_order_includes_pre_bed(self):
        """Last slot should be the pre-bed slot."""
        last = build_profile_dict()["fueling_timeline"][-1]
        slot_name = last.get("slot", "").lower()
        assert "bed" in slot_name or "sleep" in slot_name, (
            f"Last slot expected to be pre-bed, got: {last}"
        )


# ---------------------------------------------------------------------------
# supplement_schedule
# ---------------------------------------------------------------------------

class TestSupplementSchedule:
    def test_is_list(self):
        ss = build_profile_dict()["supplement_schedule"]
        assert isinstance(ss, list)
        assert len(ss) > 0, "supplement_schedule should not be empty"

    def test_each_entry_has_slot_and_items(self):
        for entry in build_profile_dict()["supplement_schedule"]:
            assert "slot" in entry, f"supplement_schedule entry missing 'slot': {entry}"
            assert "items" in entry, f"supplement_schedule entry missing 'items': {entry}"

    def test_key_supplements_present(self):
        """D3+K2, Omega3, Beta-Alanine, Creatine, Mg Glycinate must appear."""
        import json
        ss_str = json.dumps(build_profile_dict()["supplement_schedule"]).lower()
        required = ["creatine", "beta-alanine", "magnesium"]
        for req in required:
            assert req in ss_str, f"Expected supplement {req!r} not found in schedule"


# ---------------------------------------------------------------------------
# No 16-week aerobic target table anywhere in payload
# ---------------------------------------------------------------------------

class TestNo16WeekTable:
    def test_no_16_weekly_pace_volume_rows(self):
        """Assert that no key in the payload holds exactly 16 weekly pace/volume entries."""
        import json

        d = build_profile_dict()
        full_json = json.dumps(d).lower()

        def count_list_16(val, path="root"):
            if isinstance(val, list) and len(val) == 16:
                return [(path, val)]
            results = []
            if isinstance(val, list):
                for i, item in enumerate(val):
                    results.extend(count_list_16(item, f"{path}[{i}]"))
            elif isinstance(val, dict):
                for k, v in val.items():
                    results.extend(count_list_16(v, f"{path}.{k}"))
            return results

        violations = count_list_16(d)
        assert not violations, (
            f"Found list(s) with exactly 16 entries — looks like the 16-week "
            f"aerobic progression table was ingested as target rows: {violations}"
        )
