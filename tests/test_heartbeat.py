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
    async def _noop_drain(bot, now, cfg): pass
    monkeypatch.setattr(heartbeat, "_drain_quiet_queue", _noop_drain)
    sent = []
    async def _send(bot, text, **kw): sent.append(text)
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)
    noon = datetime(2026, 5, 19, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    asyncio.run(heartbeat.run_tick(object(), now=noon))
    assert sent == ["composed"]


def test_cron_heartbeat_rejects_unauthenticated(monkeypatch):
    # Import app first so load_dotenv(override=True) fires before we patch.
    from fastapi.testclient import TestClient
    from interfaces.web_server import app
    monkeypatch.setenv("CRON_DEV_BYPASS", "false")
    monkeypatch.delenv("CLOUD_RUN_URL", raising=False)
    monkeypatch.delenv("CLOUD_SCHEDULER_SA_EMAIL", raising=False)
    with TestClient(app) as client:
        resp = client.post("/cron/heartbeat")
    assert resp.status_code == 401


def test_autonomous_tick_staleness_threshold_is_one_hour():
    """Phase 18 AUTO-06: _CRON_MAX_STALENESS_HOURS must register 'autonomous-tick' = 1h.

    The cron schedule is */20 7-21, so 1 hour = 3 missed ticks — a clear
    "something's wrong" alert signal per RESEARCH Pitfall 5.
    """
    from core.heartbeat import _CRON_MAX_STALENESS_HOURS
    assert "autonomous-tick" in _CRON_MAX_STALENESS_HOURS, (
        "autonomous-tick must be registered in _CRON_MAX_STALENESS_HOURS so "
        "check_cron_health() will alert on stale autonomous ticks (AUTO-06)."
    )
    threshold = _CRON_MAX_STALENESS_HOURS["autonomous-tick"]
    assert threshold == 1, (
        f"autonomous-tick threshold must be 1 hour (3 missed 20-min ticks); "
        f"got {threshold!r}"
    )


def test_all_cron_jobs_have_staleness_entry():
    """Sanity: all known job-ids are registered and have plausible thresholds.

    Updated in Phase 20: weekly-training-review uses 170h (7d + 2h slack) so
    the upper bound is raised from 100h to 200h to accommodate weekly crons.
    """
    from core.heartbeat import _CRON_MAX_STALENESS_HOURS
    # WS2: proactive-alerts + reflect were retired (folded into the nightly review);
    # nightly-backstop is the daily journal/nightly guarantee that replaced reflect.
    expected_subset = {
        "morning-briefing", "ingest-chats", "ingest-chat-exports",
        "nightly-backstop", "autonomous-tick",
    }
    missing = expected_subset - set(_CRON_MAX_STALENESS_HOURS.keys())
    assert not missing, f"Missing staleness entries: {missing}"
    # The retired jobs must NOT linger in the staleness list (they'd false-alarm).
    retired = {"proactive-alerts", "reflect"} & set(_CRON_MAX_STALENESS_HOURS.keys())
    assert not retired, f"Retired jobs still monitored (will false-alarm): {retired}"
    # All thresholds should be reasonable (0 < h <= 200 covers weekly crons up to 8d slack).
    for job_id, hours in _CRON_MAX_STALENESS_HOURS.items():
        assert 0 < hours <= 200, (
            f"{job_id} threshold {hours} is implausible (must be 0 < h <= 200)"
        )


def test_weekly_training_review_staleness_threshold():
    """Phase 20 REVIEW-04: _CRON_MAX_STALENESS_HOURS['weekly-training-review'] == 170.

    170h = 7 days + 2h slack — catches a broken Sunday job within the
    second weekly window without spurious alerts during a normal week gap.
    """
    from core.heartbeat import _CRON_MAX_STALENESS_HOURS
    assert "weekly-training-review" in _CRON_MAX_STALENESS_HOURS, (
        "weekly-training-review must be registered in _CRON_MAX_STALENESS_HOURS "
        "(Phase 20 — heartbeat must detect a missed Sunday review)."
    )
    threshold = _CRON_MAX_STALENESS_HOURS["weekly-training-review"]
    assert threshold == 170, (
        f"weekly-training-review threshold must be 170h (7d + 2h slack); got {threshold!r}"
    )


def test_check_code_detects_drift_and_todos(tmp_path):
    from core.heartbeat import check_code, SEVERITY_FYI

    # Create a fake repo with a CLAUDE.md referencing a non-existent path
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "some text\n```text\nKlaus/\n├── nonexistent_file.py\n```\nmore text\n",
        encoding="utf-8",
    )
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    src = core_dir / "foo.py"
    src.write_text("# TODO: fix this\n# FIXME: and this\n")

    signals = check_code(repo_root=tmp_path)
    assert all(s.severity == SEVERITY_FYI for s in signals)
    assert all(s.area == "code" for s in signals)


def test_autonomous_tick_overnight_staleness_is_suppressed(monkeypatch):
    """Verify that during overnight quiet hours (23:00 to 07:59 local),
    autonomous-tick staleness check is skipped entirely.
    """
    from core import heartbeat
    from datetime import timezone, timedelta
    
    # Case A: Daytime (e.g. 12:00 Jerusalem) -> should alert
    # 2026-05-19 12:00 Jerusalem is 2026-05-19 09:00 UTC
    day_now = datetime(2026, 5, 19, 9, 0, tzinfo=timezone.utc)
    day_stale = day_now - timedelta(hours=2)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "autonomous-tick": {"last_run_at": day_stale, "consecutive_failures": 0, "last_ok": True},
    })
    
    class MockDatetimeDay:
        @classmethod
        def now(cls, tz=None):
            return day_now
    monkeypatch.setattr(heartbeat, "datetime", MockDatetimeDay)

    signals = heartbeat.check_cron_health()
    assert any(s.fingerprint == "cron:autonomous-tick:stale" for s in signals), "Expected staleness alert during daytime"

    # Case B: Overnight (e.g. 23:00 Jerusalem) -> should be suppressed
    # 2026-05-19 23:00 Jerusalem is 2026-05-19 20:00 UTC
    night_now = datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc)
    night_stale = night_now - timedelta(hours=2)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "autonomous-tick": {"last_run_at": night_stale, "consecutive_failures": 0, "last_ok": True},
    })
    
    class MockDatetimeNight:
        @classmethod
        def now(cls, tz=None):
            return night_now
    monkeypatch.setattr(heartbeat, "datetime", MockDatetimeNight)

    signals = heartbeat.check_cron_health()
    assert not any(s.fingerprint == "cron:autonomous-tick:stale" for s in signals), "Expected overnight staleness to be suppressed"

    # Case C: Boundary (e.g. 22:00 Jerusalem) -> should alert (not suppressed)
    # 2026-05-19 22:00 Jerusalem is 2026-05-19 19:00 UTC
    border_now = datetime(2026, 5, 19, 19, 0, tzinfo=timezone.utc)
    border_stale = border_now - timedelta(hours=2)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "autonomous-tick": {"last_run_at": border_stale, "consecutive_failures": 0, "last_ok": True},
    })
    
    class MockDatetimeBorder:
        @classmethod
        def now(cls, tz=None):
            return border_now
    monkeypatch.setattr(heartbeat, "datetime", MockDatetimeBorder)

    signals = heartbeat.check_cron_health()
    assert any(s.fingerprint == "cron:autonomous-tick:stale" for s in signals), "Expected staleness alert at 22:00"


def test_check_code_hierarchical_directory_parsing(tmp_path):
    """Verify that hierarchical directory trees in CLAUDE.md are correctly parsed."""
    from core.heartbeat import check_code

    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "some text\n"
        "```text\n"
        "Klaus/\n"
        "├── docs/\n"
        "│   ├── PRD.md              # product requirements\n"
        "│   └── nested/\n"
        "│       └── config.json\n"
        "└── root_file.py\n"
        "```\n"
        "more text\n",
        encoding="utf-8",
    )
    
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "PRD.md").write_text("PRD contents")
    
    nested_dir = docs_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "config.json").write_text("{}")
    
    (tmp_path / "root_file.py").write_text("print(1)")

    signals = check_code(repo_root=tmp_path)
    drift_signals = [s for s in signals if s.fingerprint == "code:docs-drift"]
    assert len(drift_signals) == 0, f"Expected 0 drift signals, got: {[s.detail for s in drift_signals]}"


# ---------------------------------------------------------------------------
# Phase 19.1 HEALTHKIT-06 — staleness threshold regression guards
# ---------------------------------------------------------------------------

def test_healthkit_sync_staleness_threshold_is_48_hours():
    """Regression guard for Phase 19.1 D-18 + HEALTHKIT-06."""
    from core.heartbeat import _CRON_MAX_STALENESS_HOURS
    assert _CRON_MAX_STALENESS_HOURS["healthkit-sync"] == 48


def test_healthkit_sync_present_in_staleness_dict():
    """Catches accidental dict-key removal."""
    from core.heartbeat import _CRON_MAX_STALENESS_HOURS
    assert "healthkit-sync" in _CRON_MAX_STALENESS_HOURS

