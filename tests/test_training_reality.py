"""Planned-vs-actual training reconciliation (carried v6 requirement WB-04).

The reconciler exists so no reasoning surface has to guess whether a planned
session actually happened. Guessing is what made Klaus ask about a workout the
user had already done.
"""
from __future__ import annotations

from core.training_reality import reconcile_training_reality


TODAY = "2026-08-15"


def _day(reality: dict, date: str) -> dict:
    """Return the reconciled entry for one date."""
    matches = [day for day in reality["days"] if day["date"] == date]
    assert matches, f"{date} missing from window {reality['window']}"
    return matches[0]


def test_planned_session_with_hevy_evidence_reads_as_completed():
    """The anti-re-ask case: a logged Hevy workout satisfies its planned slot."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-14", "slot": "evt1", "type": "Gym",
             "planned": True, "completed": False, "plan_status": "planned"},
        ],
        strength_sessions=[
            {"date": "2026-08-14", "workout_id": "hv1", "title": "Upper Body"},
        ],
        garmin_activities=[],
    )

    sessions = _day(reality, "2026-08-14")["sessions"]

    assert [s["status"] for s in sessions] == ["completed"]
    assert "hevy:hv1" in sessions[0]["evidence"]


def test_past_planned_session_without_evidence_reads_as_missed():
    """Nothing happened and the day is gone — that is a real gap, not silence."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-13", "slot": "evt2", "type": "Run",
             "planned": True, "completed": False, "plan_status": "planned"},
        ],
        strength_sessions=[],
        garmin_activities=[],
    )

    assert [s["status"] for s in _day(reality, "2026-08-13")["sessions"]] == ["missed"]


def test_future_planned_session_is_still_planned_not_missed():
    """Tomorrow's session has not been missed yet."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-16", "slot": "evt3", "type": "Run",
             "planned": True, "completed": False, "plan_status": "planned"},
        ],
        strength_sessions=[],
        garmin_activities=[],
    )

    assert [s["status"] for s in _day(reality, "2026-08-16")["sessions"]] == ["planned"]


def test_moved_session_is_not_reported_missed_on_its_old_date():
    """A session moved off a date must not read as a gap on that date."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-13", "slot": "evt4", "type": "Gym",
             "planned": False, "completed": False, "plan_status": "moved"},
            {"date": "2026-08-14", "slot": "evt4", "type": "Gym",
             "planned": True, "completed": False, "plan_status": "planned"},
        ],
        strength_sessions=[
            {"date": "2026-08-14", "workout_id": "hv2", "title": "Gym"},
        ],
        garmin_activities=[],
    )

    assert [s["status"] for s in _day(reality, "2026-08-13")["sessions"]] == ["moved"]
    assert [s["status"] for s in _day(reality, "2026-08-14")["sessions"]] == ["completed"]


def test_garmin_activity_without_a_planned_row_reads_as_unplanned():
    """Training that was never planned still belongs in the picture."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[],
        strength_sessions=[],
        garmin_activities=[
            {"activity_id": 991, "date": "2026-08-14 07:12:33", "type": "running"},
        ],
    )

    sessions = _day(reality, "2026-08-14")["sessions"]

    assert [s["status"] for s in sessions] == ["unplanned"]
    assert "garmin:991" in sessions[0]["evidence"]


def test_explicitly_skipped_session_keeps_its_reason():
    """A session the user said they skipped is not the same as one they missed."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-13", "slot": "evt5", "type": "Run", "planned": True,
             "completed": False, "skipped_reason": "sick_injured"},
        ],
        strength_sessions=[],
        garmin_activities=[],
    )

    session = _day(reality, "2026-08-13")["sessions"][0]

    assert session["status"] == "skipped"
    assert session["skipped_reason"] == "sick_injured"


def test_window_covers_a_week_back_through_tomorrow():
    """The reconciled window is today-7d..tomorrow, oldest first.

    Three days was too thin to answer "what training have I done lately": on
    real data it surfaced a single session. Training is a weekly cycle, and the
    weekly review needs a full week, so a week is the useful default.
    """
    reality = reconcile_training_reality(
        today=TODAY, training_log=[], strength_sessions=[], garmin_activities=[],
    )

    assert reality["window"] == {"start": "2026-08-08", "end": "2026-08-16"}
    assert [day["date"] for day in reality["days"]][:2] == ["2026-08-08", "2026-08-09"]
    assert len(reality["days"]) == 9


def test_evidence_outside_the_window_is_ignored():
    """Reconciliation answers about the window, not the whole history."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-07-01", "slot": "old", "type": "Gym", "planned": True},
        ],
        strength_sessions=[
            {"date": "2026-07-01", "workout_id": "hv-old", "title": "Gym"},
        ],
        garmin_activities=[],
    )

    assert all(day["sessions"] == [] for day in reality["days"])


def test_completed_training_log_row_counts_as_its_own_evidence():
    """A session logged complete in chat needs no Garmin or Hevy confirmation."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-14", "slot": "evt6", "type": "Run",
             "planned": True, "completed": True},
        ],
        strength_sessions=[],
        garmin_activities=[],
    )

    assert [s["status"] for s in _day(reality, "2026-08-14")["sessions"]] == ["completed"]


def test_get_training_reality_is_a_read_tool_on_both_mcp_endpoints():
    """Reconciliation is useless if no reasoning surface can reach it.

    Both the live agent and the morning/nightly/weekly routines need it, and it
    only reads, so it belongs in READ_TOOLS rather than either write set.
    """
    from core.tools import TOOL_SCHEMAS, _HANDLERS
    from interfaces.mcp_server import (
        INTERACTIVE_TOOLS,
        READ_TOOLS,
        ROUTINE_TOOLS,
        WRITE_TOOLS,
    )

    assert "get_training_reality" in {schema["name"] for schema in TOOL_SCHEMAS}
    assert "get_training_reality" in _HANDLERS
    assert "get_training_reality" in READ_TOOLS
    assert "get_training_reality" not in WRITE_TOOLS
    assert "get_training_reality" in INTERACTIVE_TOOLS
    assert "get_training_reality" in ROUTINE_TOOLS


def test_extra_evidence_beyond_the_planned_count_reads_as_unplanned():
    """Two workouts against one planned slot means one was extra."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-14", "slot": "evt7", "type": "Gym", "planned": True},
        ],
        strength_sessions=[
            {"date": "2026-08-14", "workout_id": "hv3", "title": "Upper"},
            {"date": "2026-08-14", "workout_id": "hv4", "title": "Lower"},
        ],
        garmin_activities=[],
    )

    statuses = sorted(s["status"] for s in _day(reality, "2026-08-14")["sessions"])

    assert statuses == ["completed", "unplanned"]


def test_missing_evidence_source_never_produces_a_missed_verdict():
    """A degraded source means we cannot see, not that nothing happened.

    Garmin returning 502 is routine. If that turned every past planned session
    into "missed", Klaus would confidently tell Amit he skipped a session he
    actually did — the exact failure this module exists to prevent, inverted.
    """
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-13", "slot": "evt8", "type": "Easy Run",
             "planned": True, "completed": False, "plan_status": "planned"},
        ],
        strength_sessions=[],
        garmin_activities=[],
        evidence_sources_degraded=True,
    )

    session = _day(reality, "2026-08-13")["sessions"][0]

    assert session["status"] == "unverified"


def test_degraded_sources_still_confirm_sessions_that_have_evidence():
    """Positive evidence is still proof even when another source is down."""
    reality = reconcile_training_reality(
        today=TODAY,
        training_log=[
            {"date": "2026-08-13", "slot": "evt9", "type": "Gym",
             "planned": True, "completed": False, "plan_status": "planned"},
        ],
        strength_sessions=[
            {"date": "2026-08-13", "workout_id": "hv9", "title": "Gym"},
        ],
        garmin_activities=[],
        evidence_sources_degraded=True,
    )

    assert [s["status"] for s in _day(reality, "2026-08-13")["sessions"]] == ["completed"]


def test_build_marks_reality_degraded_when_a_source_fails(monkeypatch):
    """The gather wrapper must pass its own degradation into the reconciler."""
    import core.training_reality as module

    monkeypatch.setattr(module, "_read_training_log", lambda *a, **k: (None, "training_log"))
    monkeypatch.setattr(module, "_read_strength_sessions", lambda *a, **k: ([], None))
    monkeypatch.setattr(module, "_read_garmin_activities", lambda *a, **k: ([], None))

    reality = module.build_training_reality()

    assert reality["degraded"] == ["training_log"]
    assert reality["evidence_complete"] is False
