"""No-model alert rules for the subscription-first runtime."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest


TZ = ZoneInfo("Asia/Jerusalem")


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
            routines_loader=lambda: [],
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
            routines_loader=lambda: [],
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
# Routine reminders                                                            #
# --------------------------------------------------------------------------- #

MORNING = {
    "id": "r1",
    "name": "Morning routine",
    "emoji": "☀️",
    "anchor_time": "07:00",
    "remind": True,
}
DAILY = [{"effective_from": "2026-01-01", "days": "daily"}]
MEMBERS = [
    {"id": "h1", "routine_id": "r1", "schedule_history": DAILY},
    {"id": "h2", "routine_id": "r1", "schedule_history": DAILY},
    {"id": "other", "routine_id": "r2", "schedule_history": DAILY},
]


def test_reminder_fires_in_window_when_the_routine_is_unfinished():
    from core.routines.alerts import evaluate_routine_reminders

    alerts = evaluate_routine_reminders(
        [MORNING], MEMBERS, {"h1": {}}, now=datetime(2026, 8, 19, 7, 10, tzinfo=TZ)
    )

    assert len(alerts) == 1
    assert alerts[0]["kind"] == "routine_reminder"
    assert alerts[0]["topic_key"] == "routine-reminder:r1:2026-08-19"
    assert alerts[0]["message_class"] == "habit_nudge"
    assert alerts[0]["destination"] == "/routines"
    assert alerts[0]["text"] == "☀️ Morning routine, Sir — 1 of 2 still open."


def test_reminder_stays_silent_when_nothing_is_left_to_do():
    from core.routines.alerts import evaluate_routine_reminders

    now = datetime(2026, 8, 19, 7, 10, tzinfo=TZ)
    assert evaluate_routine_reminders(
        [MORNING], MEMBERS, {"h1": {}, "h2": {}}, now=now
    ) == []


def test_reminder_stays_silent_when_the_day_schedules_nothing():
    from core.routines.alerts import evaluate_routine_reminders

    # 2026-08-19 is a Wednesday; these members only run on Mondays.
    mondays = [{"effective_from": "2026-01-01", "days": [0]}]
    members = [{"id": "h1", "routine_id": "r1", "schedule_history": mondays}]
    assert evaluate_routine_reminders(
        [MORNING], members, {}, now=datetime(2026, 8, 19, 7, 10, tzinfo=TZ)
    ) == []


def test_reminder_needs_both_the_switch_and_a_time():
    from core.routines.alerts import evaluate_routine_reminders

    now = datetime(2026, 8, 19, 7, 10, tzinfo=TZ)
    unarmed = {**MORNING, "remind": False}
    absent = {key: value for key, value in MORNING.items() if key != "remind"}
    untimed = {**MORNING, "anchor_time": None}

    assert evaluate_routine_reminders([unarmed], MEMBERS, {}, now=now) == []
    assert evaluate_routine_reminders([absent], MEMBERS, {}, now=now) == []
    assert evaluate_routine_reminders([untimed], MEMBERS, {}, now=now) == []


def test_reminder_window_opens_at_the_anchor_and_closes_an_hour_later():
    from core.routines.alerts import evaluate_routine_reminders

    def fired(hour: int, minute: int) -> bool:
        return bool(
            evaluate_routine_reminders(
                [MORNING], MEMBERS, {}, now=datetime(2026, 8, 19, hour, minute, tzinfo=TZ)
            )
        )

    assert not fired(6, 50)     # before the anchor
    assert fired(7, 0)          # exactly on it
    assert fired(7, 59)         # last catch-up tick
    assert not fired(8, 0)      # window closed


def test_reminder_window_never_runs_past_midnight():
    from core.routines.alerts import evaluate_routine_reminders

    late = {**MORNING, "anchor_time": "23:30"}
    assert evaluate_routine_reminders(
        [late], MEMBERS, {}, now=datetime(2026, 8, 19, 23, 40, tzinfo=TZ)
    )
    # 00:10 the next day is inside anchor+60min in wall-clock terms only —
    # it is a different day, with a different topic key and a fresh routine.
    assert evaluate_routine_reminders(
        [late], MEMBERS, {}, now=datetime(2026, 8, 20, 0, 10, tzinfo=TZ)
    ) == []


def test_runner_delivers_reminders_at_night():
    """There are no quiet hours (removed 2026-08-19) — a routine anchored at
    23:00 reminds him at 23:00, and the rest of the engine runs alongside it."""
    import asyncio
    from core.routines.alerts import run_rule_evaluator

    calls = []
    logged = []
    result = asyncio.run(
        run_rule_evaluator(
            now=datetime(2026, 8, 19, 23, 10, tzinfo=TZ),
            routines_loader=lambda: [{**MORNING, "anchor_time": "23:00"}],
            habits_loader=lambda: MEMBERS,
            completions_loader=lambda _day: {},
            prior_topics_loader=lambda _day: [],
            push_sender=lambda *args: calls.append(args) or {"sent": 1},
            outreach_logger=lambda day, entry: logged.append((day, entry)),
            snapshot_loader=lambda: {
                "tasks": [
                    {"id": "t1", "title": "Renew passport",
                     "hard_deadline_at": "2026-08-20T00:00:00+03:00"},
                ],
                "habits_pending": [],
                "today": {"calendar": {"timed": []}},
            },
            due_followups_loader=lambda _now: [],
            infrastructure_loader=lambda: [],
            followup_marker=lambda _followup_id: None,
        )
    )

    # The reminder AND the midnight deadline, both at 23:10.
    assert result == {"evaluated": 2, "sent": 2, "reminders_sent": 1}
    assert {entry["kind"] for _day, entry in logged} == {
        "routine_reminder", "hard_deadline"
    }
    text, message_class, destination, title, external_url, tag = calls[0]
    assert message_class == "habit_nudge"
    assert destination == "/routines"
    assert external_url is None
    assert tag == "routine-reminder:r1:2026-08-19"
    assert logged[0][1]["kind"] == "routine_reminder"


def test_runner_reminds_once_a_day_and_reads_no_habits_to_learn_it():
    """A second tick inside the window must neither push again nor pay for the
    habit/completion reads that would only prove what the log already says."""
    import asyncio
    from core.routines.alerts import run_rule_evaluator

    reads = []

    def habits_loader():
        reads.append("habits")
        return MEMBERS

    result = asyncio.run(
        run_rule_evaluator(
            now=datetime(2026, 8, 19, 7, 30, tzinfo=TZ),
            routines_loader=lambda: [MORNING],
            habits_loader=habits_loader,
            completions_loader=lambda _day: {},
            prior_topics_loader=lambda _day: ["routine-reminder:r1:2026-08-19"],
            push_sender=lambda *args: pytest.fail("reminded twice in one day"),
            outreach_logger=lambda _day, _entry: None,
            snapshot_loader=lambda: {
                "tasks": [], "habits_pending": [], "today": {"calendar": {"timed": []}}
            },
            due_followups_loader=lambda _now: [],
            infrastructure_loader=lambda: [],
            followup_marker=lambda _followup_id: None,
        )
    )

    assert result["sent"] == 0
    assert reads == []
