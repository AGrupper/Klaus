"""No-model daytime alert rules for the subscription-first runtime."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Jerusalem")


def test_rules_only_surface_explicit_time_bound_conditions():
    from core.routines.alerts import evaluate_daytime_rules

    now = datetime(2026, 8, 8, 14, 20, tzinfo=TZ)
    snapshot = {
        "tasks": [
            {"id": "hard", "title": "Submit form", "hard_deadline_at": "2026-08-08T15:00:00+03:00"},
            {"id": "untimed", "title": "Read someday"},
        ],
        "habits_pending": [{"id": "walk", "name": "Walk"}],
        "today": {"calendar": {"timed": []}},
    }
    alerts = evaluate_daytime_rules(snapshot, [], [], now=now)

    assert [alert["kind"] for alert in alerts] == ["hard_deadline"]
    assert "Submit form" in alerts[0]["text"]


def test_rules_detect_due_followup_calendar_overlap_and_travel_conflict():
    from core.routines.alerts import evaluate_daytime_rules

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
    alerts = evaluate_daytime_rules(
        snapshot,
        [{"id": "f1", "note": "Call the clinic", "due_at": now.isoformat()}],
        [],
        now=now,
    )
    kinds = {alert["kind"] for alert in alerts}
    assert {"timed_followup", "calendar_conflict", "travel_conflict"} <= kinds


def test_rules_include_only_critical_automation_failures():
    from core.routines.alerts import evaluate_daytime_rules

    alerts = evaluate_daytime_rules(
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
            prior_topics_loader=lambda _day: ["followup:f2"],
            push_sender=lambda text, kind: sent.append((text, kind)) or {"sent": 1},
            outreach_logger=lambda day, entry: logged.append((day, entry)),
            followup_marker=lambda followup_id: marked.append(followup_id),
        )
    )

    assert result["sent"] == 1
    assert marked == ["f1"]
    assert len(logged) == 1


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
