"""No-model alert rules for the subscription-first runtime."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest


TZ = ZoneInfo("Asia/Jerusalem")

# The runner tests below fire at 14:00; a morning run earlier that day is what
# holds the alert window open for them.
MORNING_RUN = [{"routine": "morning", "created_at": "2026-08-08T07:10:00+03:00"}]


def test_rules_only_surface_explicit_time_bound_conditions():
    from core.routines.alerts import evaluate_explicit_rules

    now = datetime(2026, 8, 8, 14, 20, tzinfo=TZ)
    snapshot = {
        "tasks": [
            {"id": "hard", "title": "Submit form", "hard_deadline_at": "2026-08-08T15:00:00+03:00"},
            {"id": "untimed", "title": "Read someday"},
        ],
        "habits_pending": [{"id": "walk", "name": "Walk"}],
        "today": {"calendar": {"timed": []}},
    }
    alerts = evaluate_explicit_rules(snapshot, [], [], now=now)

    assert [alert["kind"] for alert in alerts] == ["hard_deadline"]
    assert "Submit form" in alerts[0]["text"]


def test_rules_detect_due_followup_calendar_overlap_and_travel_conflict():
    from core.routines.alerts import evaluate_explicit_rules

    now = datetime(2026, 8, 8, 14, 20, tzinfo=TZ)
    snapshot = {
        "tasks": [],
        "habits_pending": [],
        "today": {
            "calendar": {
                "timed": [
                    {
                        "id": "one",
                        "title": "First",
                        "start": "2026-08-08T14:30:00+03:00",
                        "end": "2026-08-08T15:30:00+03:00",
                    },
                    {
                        "id": "two",
                        "title": "Second",
                        "start": "2026-08-08T15:00:00+03:00",
                        "end": "2026-08-08T16:00:00+03:00",
                        "leave_by": "2026-08-08T14:15:00+03:00",
                    },
                ]
            }
        },
    }
    alerts = evaluate_explicit_rules(
        snapshot,
        [{"id": "f1", "note": "Call the clinic", "due_at": now.isoformat()}],
        [],
        now=now,
    )
    kinds = {alert["kind"] for alert in alerts}
    assert {"timed_followup", "calendar_conflict", "travel_conflict"} <= kinds


def test_rules_include_only_critical_automation_failures():
    from core.routines.alerts import evaluate_explicit_rules

    alerts = evaluate_explicit_rules(
        {"tasks": [], "habits_pending": [], "today": {"calendar": {"timed": []}}},
        [],
        [
            {"fingerprint": "cron:x", "severity": "critical", "title": "x failed"},
            {"fingerprint": "cron:y", "severity": "warning", "title": "y delayed"},
        ],
        now=datetime(2026, 8, 8, 14, 0, tzinfo=TZ),
    )
    assert [alert["topic_key"] for alert in alerts] == ["automation:cron:x"]


def test_runner_deduplicates_topics_and_marks_followup_after_success():
    import asyncio
    from core.routines.alerts import run_rule_evaluator

    sent = []
    marked = []
    logged = []
    result = asyncio.run(
        run_rule_evaluator(
            now=datetime(2026, 8, 8, 14, 0, tzinfo=TZ),
            snapshot_loader=lambda: {
                "tasks": [],
                "habits_pending": [],
                "today": {"calendar": {"timed": []}},
            },
            due_followups_loader=lambda _now: [
                {"id": "f1", "note": "Call", "due_at": "2026-08-08T14:00:00+03:00"},
                {"id": "f2", "note": "Write", "due_at": "2026-08-08T14:00:00+03:00"},
            ],
            infrastructure_loader=lambda: [],
            runs_loader=lambda: MORNING_RUN,
            prior_topics_loader=lambda _day: ["followup:f2"],
            push_sender=lambda text, kind, *_args: sent.append((text, kind)) or {"sent": 1},
            outreach_logger=lambda day, entry: logged.append((day, entry)),
            followup_marker=lambda followup_id: marked.append(followup_id),
        )
    )

    assert result["sent"] == 1
    assert marked == ["f1"]
    assert len(logged) == 1


def test_alert_push_carries_topic_key_as_tag():
    """The push tag must equal topic_key so reading in the Hub's bell can
    dismiss the delivered lock-screen notification (Paper Hub)."""
    import asyncio

    from core.routines.alerts import run_rule_evaluator

    calls = []
    asyncio.run(
        run_rule_evaluator(
            now=datetime(2026, 8, 8, 14, 0, tzinfo=TZ),
            snapshot_loader=lambda: {
                "tasks": [],
                "habits_pending": [],
                "today": {"calendar": {"timed": []}},
            },
            due_followups_loader=lambda _now: [
                {"id": "f1", "note": "Call", "due_at": "2026-08-08T14:00:00+03:00"},
            ],
            infrastructure_loader=lambda: [],
            runs_loader=lambda: MORNING_RUN,
            prior_topics_loader=lambda _day: [],
            push_sender=lambda *args: calls.append(args) or {"sent": 1},
            outreach_logger=lambda _day, _entry: None,
            followup_marker=lambda _followup_id: None,
        )
    )

    assert len(calls) == 1
    # (text, message_class, destination, title, external_url, tag)
    assert calls[0][5] == "followup:f1"
    assert calls[0][4] is None  # alerts never carry an external URL


def test_subscription_heartbeat_collects_retained_infrastructure_checkers():
    from core.routines import heartbeat

    expected = [
        heartbeat.Signal(
            fingerprint="deploy:failed",
            severity="critical",
            area="deployment",
            title="Latest deployment failed",
            detail="revision did not become ready",
            remediation="Inspect Cloud Build and Cloud Run logs.",
        )
    ]
    with patch("core.routines.heartbeat.check_cron_health", return_value=expected), patch(
        "core.routines.heartbeat.check_mcp_routine_health", return_value=[]
    ), patch("core.routines.heartbeat._check_push_health", return_value=[]), patch(
        "core.routines.heartbeat.check_deployment_identity", return_value=[]
    ):
        result = heartbeat.collect_deterministic_signals(datetime(2026, 8, 8, 12, 0, tzinfo=TZ))

    assert result == expected



# --------------------------------------------------------------------------- #
# The alert window                                                             #
# --------------------------------------------------------------------------- #

def _run(routine: str, at: str) -> dict:
    return {"routine": routine, "created_at": at}


def test_window_follows_the_most_recent_wake_or_sleep_signal():
    from core.routines.alerts import alert_window_open

    now = datetime(2026, 8, 19, 14, 0, tzinfo=TZ)
    woke = _run("morning", "2026-08-19T07:05:00+03:00")
    slept = _run("nightly", "2026-08-19T13:00:00+03:00")

    assert alert_window_open([woke], now) is True
    # Newest first or oldest first, the newest signal is the one that counts.
    assert alert_window_open([slept, woke], now) is False
    assert alert_window_open([woke, slept], now) is False


def test_window_ignores_the_weekly_review():
    """Sunday's weekly review says nothing about whether Amit is awake."""
    from core.routines.alerts import alert_window_open

    now = datetime(2026, 8, 19, 14, 0, tzinfo=TZ)
    runs = [
        _run("weekly", "2026-08-19T13:30:00+03:00"),
        _run("nightly", "2026-08-19T13:00:00+03:00"),
    ]
    # The weekly run is the newest of the three, but a review is not a wake
    # signal — the 13:00 nightly is what decides, and it closed the day.
    assert alert_window_open(runs, now) is False


def test_window_opens_at_the_fallback_hour_when_the_wake_trigger_misses():
    from core.routines.alerts import alert_window_open

    # Went to bed at 00:30, and the morning Shortcut never fired.
    runs = [_run("nightly", "2026-08-19T00:30:00+03:00")]

    assert alert_window_open(runs, datetime(2026, 8, 19, 8, 0, tzinfo=TZ)) is False
    assert alert_window_open(runs, datetime(2026, 8, 19, 10, 29, tzinfo=TZ)) is False
    assert alert_window_open(runs, datetime(2026, 8, 19, 10, 30, tzinfo=TZ)) is True


def test_a_nap_closes_the_day_and_the_fallback_does_not_undo_it():
    """Amit's call: Focus on = day over, whenever it comes. The fallback must
    not then reopen it an hour later — that would make the choice meaningless."""
    from core.routines.alerts import alert_window_open

    runs = [
        _run("nightly", "2026-08-19T16:00:00+03:00"),
        _run("morning", "2026-08-19T07:00:00+03:00"),
    ]
    assert alert_window_open(runs, datetime(2026, 8, 19, 17, 0, tzinfo=TZ)) is False
    assert alert_window_open(runs, datetime(2026, 8, 19, 22, 0, tzinfo=TZ)) is False
    # Next morning, the wake trigger having failed too — now it reopens.
    assert alert_window_open(runs, datetime(2026, 8, 20, 11, 0, tzinfo=TZ)) is True


def test_window_closes_itself_when_the_sleep_trigger_misses():
    from core.routines.alerts import alert_window_open

    runs = [_run("morning", "2026-08-19T07:00:00+03:00")]

    assert alert_window_open(runs, datetime(2026, 8, 19, 23, 0, tzinfo=TZ)) is True
    assert alert_window_open(runs, datetime(2026, 8, 20, 2, 0, tzinfo=TZ)) is True
    # 20 hours after waking, stop polling on his behalf.
    assert alert_window_open(runs, datetime(2026, 8, 20, 4, 0, tzinfo=TZ)) is False


def test_window_fails_toward_alerting_when_it_knows_nothing():
    """No runs at all — including RoutineRunStore.list_recent having failed and
    returned [] — must give a plain day, never a silent one."""
    from core.routines.alerts import alert_window_open

    assert alert_window_open([], datetime(2026, 8, 19, 4, 0, tzinfo=TZ)) is False
    assert alert_window_open([], datetime(2026, 8, 19, 12, 0, tzinfo=TZ)) is True
    # Unparseable timestamps are the same kind of "we don't know".
    assert alert_window_open(
        [_run("nightly", "not-a-date")], datetime(2026, 8, 19, 12, 0, tzinfo=TZ)
    ) is True


def test_a_closed_window_never_builds_the_life_snapshot():
    """The whole point of the gate: outside Amit's day this pass costs one
    query, not a calendar/tasks/health gather."""
    import asyncio
    from core.routines.alerts import run_rule_evaluator

    result = asyncio.run(
        run_rule_evaluator(
            now=datetime(2026, 8, 19, 4, 0, tzinfo=TZ),
            runs_loader=lambda: [_run("nightly", "2026-08-19T00:30:00+03:00")],
            snapshot_loader=lambda: pytest.fail("built the snapshot while closed"),
            due_followups_loader=lambda _now: pytest.fail("read follow-ups while closed"),
            infrastructure_loader=lambda: pytest.fail("ran heartbeat while closed"),
            prior_topics_loader=lambda _day: pytest.fail("read outreach while closed"),
            push_sender=lambda *args: pytest.fail("pushed while closed"),
        )
    )

    assert result == {"evaluated": 0, "sent": 0, "window_open": False}


# --------------------------------------------------------------------------- #
# Which night a wind-down belongs to                                           #
# --------------------------------------------------------------------------- #

def _night_of(local: datetime) -> str:
    """nightly_target_date_now() as it would answer at `local`."""
    from unittest.mock import patch as _patch

    import interfaces.routes.triggers as triggers

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return local.astimezone(tz) if tz else local

    with _patch.object(triggers, "datetime", FrozenDatetime):
        return triggers.nightly_target_date_now()


def test_a_wind_down_is_named_after_the_evening_it_started():
    """A night belongs to the evening it began, not the calendar date the
    clock happens to show — 00:15 on the 20th is still the night of the 19th."""
    assert _night_of(datetime(2026, 8, 19, 22, 0, tzinfo=TZ)) == "2026-08-19"
    assert _night_of(datetime(2026, 8, 19, 23, 59, tzinfo=TZ)) == "2026-08-19"
    assert _night_of(datetime(2026, 8, 20, 0, 15, tzinfo=TZ)) == "2026-08-19"
    assert _night_of(datetime(2026, 8, 20, 0, 59, tzinfo=TZ)) == "2026-08-19"
    # Past the 01:00 rollover, a new night has begun.
    assert _night_of(datetime(2026, 8, 20, 1, 0, tzinfo=TZ)) == "2026-08-20"
    assert _night_of(datetime(2026, 8, 20, 12, 0, tzinfo=TZ)) == "2026-08-20"


def test_the_backstop_checks_the_night_that_closed_not_the_one_starting():
    """The regression this fixes: Amit slept at 22:00, the backstop had already
    claimed that key, and his real trigger deduplicated itself into silence for
    three nights running.

    The backstop runs at 01:30 — half an hour INTO a new night — so deriving
    its target from the clock would hand it the night he has not gone to bed
    for yet. It must look one night further back.
    """
    from unittest.mock import patch as _patch

    import interfaces.routes.triggers as triggers

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime(2026, 8, 21, 1, 30, tzinfo=TZ)
            return moment.astimezone(tz) if tz else moment

    with _patch.object(triggers, "datetime", FrozenDatetime):
        checked = triggers.night_just_ended()

    # It checks the night Amit's 22:00 bedtime on the 20th belongs to...
    assert checked == "2026-08-20"
    assert checked == _night_of(datetime(2026, 8, 20, 22, 0, tzinfo=TZ))
    # ...and NOT the night that began 30 minutes ago, which is still his to claim.
    assert checked != _night_of(datetime(2026, 8, 21, 1, 30, tzinfo=TZ))


def test_the_backstop_still_catches_a_night_that_was_never_triggered():
    from unittest.mock import patch as _patch

    import interfaces.routes.triggers as triggers

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime(2026, 8, 22, 1, 30, tzinfo=TZ)
            return moment.astimezone(tz) if tz else moment

    with _patch.object(triggers, "datetime", FrozenDatetime):
        assert triggers.night_just_ended() == "2026-08-21"


def test_two_wind_downs_in_one_night_are_the_same_night():
    """Focus toggled off and on again at 23:50 and 00:30 must not open a
    second night."""
    assert _night_of(datetime(2026, 8, 19, 23, 50, tzinfo=TZ)) == _night_of(
        datetime(2026, 8, 20, 0, 30, tzinfo=TZ)
    )
