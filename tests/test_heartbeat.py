"""Tests for the deterministic Claude-first infrastructure heartbeat."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def test_retained_scheduler_staleness_is_reported_without_legacy_jobs(monkeypatch):
    """A missed deterministic scheduler produces a critical health signal."""
    from core import heartbeat

    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    monkeypatch.setattr(
        heartbeat,
        "_read_cron_ledger",
        lambda: {"deterministic-alerts": {"last_run_at": stale, "consecutive_failures": 0}},
    )
    signals = heartbeat.check_cron_health()

    assert any(signal.fingerprint == "cron:deterministic-alerts:stale" for signal in signals)
    assert "autonomous-tick" not in heartbeat._CRON_MAX_STALENESS_HOURS
    assert "ingest-chats" not in heartbeat._CRON_MAX_STALENESS_HOURS


def test_push_health_reports_missing_subscriptions_without_telegram_fallback(monkeypatch):
    """Enabled Web Push with no browser subscription is a critical infrastructure signal."""
    from core import heartbeat

    subscriptions = MagicMock()
    subscriptions.list_all.return_value = []
    settings = MagicMock()
    settings.get.return_value = {"push_enabled_at": "2026-08-12T08:00:00+00:00"}
    with patch("memory.firestore_db.PushSubscriptionStore", return_value=subscriptions), patch(
        "memory.firestore_db.HubSettingsStore", return_value=settings
    ):
        signals = heartbeat._check_push_health()

    assert [signal.fingerprint for signal in signals] == ["push:subscriptions:missing"]


def test_deployment_identity_uses_runtime_metadata_not_github_polling(monkeypatch):
    """The health surface names the serving Cloud Run revision without network polling."""
    from core.heartbeat import deployment_identity

    monkeypatch.setenv("K_SERVICE", "klaus-agent")
    monkeypatch.setenv("K_REVISION", "klaus-agent-00042")
    assert deployment_identity()["revision"] == "klaus-agent-00042"


def test_collects_scheduler_mcp_push_and_deployment_checks(monkeypatch):
    """All retained health domains participate in deterministic alert evaluation."""
    from core import heartbeat

    expected = heartbeat.Signal("mcp:ok", "warning", "mcp", "MCP", "detail", "fix")
    monkeypatch.setattr(heartbeat, "check_cron_health", lambda now=None: [])
    monkeypatch.setattr(heartbeat, "check_mcp_routine_health", lambda: [expected])
    monkeypatch.setattr(heartbeat, "_check_push_health", lambda: [])
    monkeypatch.setattr(heartbeat, "check_deployment_identity", lambda: [])
    assert heartbeat.collect_deterministic_signals() == [expected]
