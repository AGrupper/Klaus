# tests/test_heartbeat.py
from __future__ import annotations
import os
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
os.environ.setdefault("GCP_PROJECT_ID", "klaus-agent")

from datetime import datetime
from zoneinfo import ZoneInfo


def _dt(hour, minute, isoweekday=2):
    # 2026-05-18 is a Monday (isoweekday 1); offset to hit the requested weekday.
    day = 17 + isoweekday
    return datetime(2026, 5, day, hour, minute, tzinfo=ZoneInfo("Asia/Jerusalem"))


def test_signal_fields():
    from core.heartbeat import Signal, SEVERITY_CRITICAL
    s = Signal(
        fingerprint="cron:morning-briefing:stale",
        severity=SEVERITY_CRITICAL,
        area="cron",
        title="morning-briefing did not run",
        detail="last run 30h ago",
        remediation="Check Cloud Scheduler job klaus-morning-briefing.",
    )
    assert s.fingerprint == "cron:morning-briefing:stale"
    assert s.severity == "critical"


def test_heartbeat_config_defaults():
    from memory.firestore_db import _HEARTBEAT_CONFIG_DEFAULTS as d
    assert d["enabled"] is True
    assert d["digest_hour"] == 9
    assert d["weekly_digest_day"] == 1
    assert d["reping_interval_hours"] == 24
    assert d["quiet_start"] == "22:00"


def test_in_quiet_hours_spans_midnight():
    from core.heartbeat import _in_quiet_hours
    cfg = {"quiet_start": "22:00", "quiet_end": "07:00", "timezone": "Asia/Jerusalem"}
    assert _in_quiet_hours(cfg, _dt(23, 30)) is True
    assert _in_quiet_hours(cfg, _dt(3, 0)) is True
    assert _in_quiet_hours(cfg, _dt(12, 0)) is False


def test_tiers_for_now():
    from core.heartbeat import (_tiers_for_now, SEVERITY_CRITICAL,
                                SEVERITY_WARNING, SEVERITY_FYI)
    cfg = {"digest_hour": 9, "weekly_digest_day": 1, "timezone": "Asia/Jerusalem"}
    assert _tiers_for_now(cfg, _dt(9, 5, isoweekday=1)) == {
        SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_FYI}
    assert _tiers_for_now(cfg, _dt(9, 5, isoweekday=2)) == {
        SEVERITY_CRITICAL, SEVERITY_WARNING}
    assert _tiers_for_now(cfg, _dt(15, 0, isoweekday=2)) == {SEVERITY_CRITICAL}


def test_check_cron_health_flags_stale(monkeypatch):
    from core import heartbeat
    from datetime import timezone, timedelta
    stale = datetime.now(timezone.utc) - timedelta(hours=40)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "morning-briefing": {"last_run_at": stale, "consecutive_failures": 0, "last_ok": True},
    })
    signals = heartbeat.check_cron_health()
    assert any(s.fingerprint == "cron:morning-briefing:stale" for s in signals)
    assert all(s.severity == heartbeat.SEVERITY_CRITICAL for s in signals)


def test_check_cron_health_flags_failure_streak(monkeypatch):
    from core import heartbeat
    from datetime import timezone
    fresh = datetime.now(timezone.utc)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "ingest-chats": {"last_run_at": fresh, "consecutive_failures": 3, "last_ok": False},
    })
    signals = heartbeat.check_cron_health()
    assert any(s.fingerprint == "cron:ingest-chats:failing" for s in signals)


def test_collect_signals_filters_by_tier(monkeypatch):
    from core import heartbeat
    crit = heartbeat.Signal("x:y:z", heartbeat.SEVERITY_CRITICAL, "cron", "t", "d", "fix")
    warn = heartbeat.Signal("a:b:c", heartbeat.SEVERITY_WARNING, "token", "t", "d", "fix")
    monkeypatch.setattr(heartbeat, "check_cron_health", lambda: [crit])
    monkeypatch.setattr(heartbeat, "check_tokens", lambda: [warn])
    monkeypatch.setattr(heartbeat, "check_degradation", lambda: [])
    monkeypatch.setattr(heartbeat, "check_deployment", lambda: [])
    signals = heartbeat._collect_signals(tiers={heartbeat.SEVERITY_CRITICAL})
    assert crit in signals and warn not in signals


def test_record_cron_run_ok_resets_failures(monkeypatch):
    import memory.firestore_db as fdb
    captured = {}
    class _Doc:
        def set(self, payload, merge): captured.update(payload)
    class _Col:
        def document(self, _id): return _Doc()
    class _Client:
        def collection(self, _name): return _Col()
    monkeypatch.setattr(fdb, "_make_firestore_client", lambda *a, **k: _Client())
    fdb.record_cron_run("ingest-chats", ok=True)
    assert captured["job_id"] == "ingest-chats"
    assert captured["last_ok"] is True
    assert captured["consecutive_failures"] == 0


def test_check_degradation_flags_high_fallback(monkeypatch):
    from core import heartbeat
    monkeypatch.setattr(heartbeat, "_read_fallback_count_today", lambda: 25)
    monkeypatch.setattr(heartbeat, "_read_cloud_run_5xx", lambda: 0)
    signals = heartbeat.check_degradation()
    assert any(s.fingerprint == "degradation:fallback-rate" for s in signals)
    assert all(s.severity == heartbeat.SEVERITY_WARNING for s in signals)


def test_check_deployment_flags_failed_deploy(monkeypatch):
    from core import heartbeat
    monkeypatch.setattr(heartbeat, "_latest_deploy_status",
                        lambda: {"conclusion": "failure", "head_sha": "abc123def"})
    monkeypatch.setattr(heartbeat, "_live_revision_sha", lambda: "abc123def")
    signals = heartbeat.check_deployment()
    assert any(s.fingerprint == "deployment:last-deploy-failed" for s in signals)
    assert any(s.severity == heartbeat.SEVERITY_CRITICAL for s in signals)


def test_plain_text_fallback_groups_by_severity():
    from core.heartbeat import (_plain_text_fallback, Signal,
                                SEVERITY_CRITICAL, SEVERITY_WARNING)
    msg = _plain_text_fallback([
        Signal("a:b:c", SEVERITY_CRITICAL, "cron", "Cron down", "stale 40h", "Check scheduler."),
        Signal("d:e:f", SEVERITY_WARNING, "token", "Token expiring", "3 days left", "Refresh it."),
    ])
    assert "Cron down" in msg and "Check scheduler." in msg
    assert msg.index("Cron down") < msg.index("Token expiring")


def test_incident_store_should_ping_logic():
    from memory.firestore_db import IncidentStore
    from datetime import datetime, timezone, timedelta
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    assert IncidentStore._should_ping(None, reping_interval_hours=24) is True
    assert IncidentStore._should_ping({"last_pinged": recent}, reping_interval_hours=24) is False
    assert IncidentStore._should_ping({"last_pinged": old}, reping_interval_hours=24) is True


def test_run_tick_pings_new_critical(monkeypatch):
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core import heartbeat
    monkeypatch.setattr(heartbeat, "_load_config", lambda: {
        "enabled": True, "quiet_start": "22:00", "quiet_end": "07:00",
        "timezone": "Asia/Jerusalem", "digest_hour": 9,
        "weekly_digest_day": 1, "reping_interval_hours": 24})
    crit = heartbeat.Signal("cron:x:stale", heartbeat.SEVERITY_CRITICAL,
                            "cron", "t", "d", "fix")
    monkeypatch.setattr(heartbeat, "_collect_signals", lambda **k: [crit])
    monkeypatch.setattr(heartbeat, "_compose_message", lambda s: "composed")
    monkeypatch.setattr(heartbeat, "_register_incidents",
                        lambda crits, cfg: [crit])
    monkeypatch.setattr(heartbeat, "_resolve_absent", lambda fps: None)
    monkeypatch.setattr(heartbeat, "_drain_quiet_queue",
                        lambda bot, now, cfg: None)
    sent = []
    async def _send(bot, text, **kw): sent.append(text)
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)
    noon = datetime(2026, 5, 19, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    asyncio.run(heartbeat.run_tick(object(), now=noon))
    assert sent == ["composed"]
