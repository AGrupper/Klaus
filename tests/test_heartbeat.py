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
