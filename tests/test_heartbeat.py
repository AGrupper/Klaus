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
    # Hermetic guard: since 2026-06-11 the local .env carries a real
    # TICK_BRAIN_API_KEY, so an earlier test's load_dotenv(override=True) can
    # leave it in os.environ and this pass would make a LIVE Groq call and
    # alter the sent message. Mock it like every other collaborator here.
    monkeypatch.setattr(heartbeat, "_run_tick_brain_pass", lambda s, **k: None)
    async def _noop_drain(bot, now, cfg): pass
    monkeypatch.setattr(heartbeat, "_drain_quiet_queue", _noop_drain)
    sent = []
    sent_kwargs = []
    async def _send(bot, text, **kw):
        sent.append(text)
        sent_kwargs.append(kw)
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)
    noon = datetime(2026, 5, 19, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    asyncio.run(heartbeat.run_tick(object(), now=noon))
    assert sent == ["composed"]
    # WR-02 / D-07 regression: heartbeat sends carry the "alert" push class
    # (a non-default class must flow from at least one cron caller).
    assert sent_kwargs[0].get("message_class") == "alert"


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
        "nightly-backstop", "autonomous-tick", "run-sync", "biometric-sync",
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


# ---------------------------------------------------------------------------
# Phase 29 Plan 05 — _check_push_health (PUSH-03, Pattern 9, D-13/D-14)
# ---------------------------------------------------------------------------

def _mock_push_stores(monkeypatch, subscriptions, settings):
    """Patch memory.firestore_db.PushSubscriptionStore/HubSettingsStore so
    _check_push_health() never reaches real Firestore."""
    from unittest.mock import MagicMock, patch
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    mock_sub_store = MagicMock()
    mock_sub_store.list_all.return_value = subscriptions
    mock_settings_store = MagicMock()
    mock_settings_store.get.return_value = settings

    return patch("memory.firestore_db.PushSubscriptionStore", return_value=mock_sub_store), \
        patch("memory.firestore_db.HubSettingsStore", return_value=mock_settings_store)


def test_check_push_health_flags_failure_streak(monkeypatch):
    """Condition 1: any subscription failure_count >= 3 -> critical signal."""
    from core import heartbeat
    subs = [
        {"endpoint": "https://fcm.example/abc", "user_agent": "iPhone Safari",
         "failure_count": 3, "last_success_at": None},
    ]
    settings = {"telegram_mirror_enabled": True, "push_enabled_at": "2026-06-27T00:00:00+00:00"}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, subs, settings)
    with patch_sub, patch_settings:
        signals = heartbeat._check_push_health()

    matches = [s for s in signals if s.fingerprint.startswith("push:failure-streak:")]
    assert len(matches) == 1
    assert matches[0].severity == heartbeat.SEVERITY_CRITICAL
    assert matches[0].area == "push"


def test_check_push_health_no_subscriptions_mirror_on_is_warning(monkeypatch):
    """Condition 2: push enabled, zero subs, mirror ON -> warning (Telegram covers it)."""
    from core import heartbeat
    settings = {"telegram_mirror_enabled": True, "push_enabled_at": "2026-06-27T00:00:00+00:00"}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, [], settings)
    with patch_sub, patch_settings:
        signals = heartbeat._check_push_health()

    matches = [s for s in signals if s.fingerprint == "push:no-subscription"]
    assert len(matches) == 1
    assert matches[0].severity == heartbeat.SEVERITY_WARNING


def test_check_push_health_no_subscriptions_mirror_off_is_critical(monkeypatch):
    """Condition 2: push enabled, zero subs, mirror OFF -> critical (no safety net left)."""
    from core import heartbeat
    settings = {"telegram_mirror_enabled": False, "push_enabled_at": "2026-06-27T00:00:00+00:00"}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, [], settings)
    with patch_sub, patch_settings:
        signals = heartbeat._check_push_health()

    matches = [s for s in signals if s.fingerprint == "push:no-subscription"]
    assert len(matches) == 1
    assert matches[0].severity == heartbeat.SEVERITY_CRITICAL


def test_check_push_health_no_signal_when_push_not_enabled(monkeypatch):
    """No push_enabled_at yet (pre-rollout) -> no no-subscription signal noise."""
    from core import heartbeat
    settings = {"telegram_mirror_enabled": True, "push_enabled_at": None}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, [], settings)
    with patch_sub, patch_settings:
        signals = heartbeat._check_push_health()

    assert signals == []


def test_check_push_health_flags_stale_delivery(monkeypatch):
    """Condition 3: subs exist but none delivered successfully in 48h -> warning."""
    from core import heartbeat
    from datetime import datetime, timezone, timedelta
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    subs = [
        {"endpoint": "https://fcm.example/abc", "user_agent": "iPhone Safari",
         "failure_count": 0, "last_success_at": stale_ts},
    ]
    settings = {"telegram_mirror_enabled": True, "push_enabled_at": "2026-06-27T00:00:00+00:00"}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, subs, settings)
    with patch_sub, patch_settings:
        signals = heartbeat._check_push_health()

    matches = [s for s in signals if s.fingerprint == "push:delivery-stale"]
    assert len(matches) == 1
    assert matches[0].severity == heartbeat.SEVERITY_WARNING


def test_check_push_health_no_stale_signal_within_48h(monkeypatch):
    """A recent last_success_at within 48h suppresses the delivery-stale signal."""
    from core import heartbeat
    from datetime import datetime, timezone, timedelta
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    subs = [
        {"endpoint": "https://fcm.example/abc", "user_agent": "iPhone Safari",
         "failure_count": 0, "last_success_at": recent_ts},
    ]
    settings = {"telegram_mirror_enabled": True, "push_enabled_at": "2026-06-27T00:00:00+00:00"}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, subs, settings)
    with patch_sub, patch_settings:
        signals = heartbeat._check_push_health()

    assert not any(s.fingerprint == "push:delivery-stale" for s in signals)


def test_check_push_health_registered_in_collect_signals_tuple(monkeypatch):
    """_check_push_health must run every tick (not weekly-only)."""
    from core import heartbeat
    settings = {"telegram_mirror_enabled": True, "push_enabled_at": None}
    patch_sub, patch_settings = _mock_push_stores(monkeypatch, [], settings)
    monkeypatch.setattr(heartbeat, "check_cron_health", lambda: [])
    monkeypatch.setattr(heartbeat, "check_tokens", lambda: [])
    monkeypatch.setattr(heartbeat, "check_degradation", lambda: [])
    monkeypatch.setattr(heartbeat, "check_deployment", lambda: [])
    called = {"push": False}

    def _spy():
        called["push"] = True
        return []

    monkeypatch.setattr(heartbeat, "_check_push_health", _spy)
    with patch_sub, patch_settings:
        heartbeat._collect_signals(tiers={heartbeat.SEVERITY_CRITICAL})
    assert called["push"] is True


# ---------------------------------------------------------------------------
# Phase 30.5 Plan 05 — daily cost tripwire (BRAIN-04, D-01..D-04)
# ---------------------------------------------------------------------------

def _mock_tripwire_stores(monkeypatch, *, summary, already_fired):
    """Patch memory.firestore_db.LLMUsageStore/CostTripwireLogStore so
    check_daily_spend() never reaches real Firestore."""
    from unittest.mock import MagicMock, patch
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    mock_usage_store = MagicMock()
    mock_usage_store.summary_for_date.return_value = summary
    mock_tripwire_store = MagicMock()
    mock_tripwire_store.already_fired.return_value = already_fired

    return (
        patch("memory.firestore_db.LLMUsageStore", return_value=mock_usage_store),
        patch("memory.firestore_db.CostTripwireLogStore", return_value=mock_tripwire_store),
        mock_tripwire_store,
    )


def test_daily_cost_alert_threshold_defaults_on_malformed_env(monkeypatch):
    """T-30.5-13: a malformed KLAUS_DAILY_COST_ALERT falls back to $5.0, never raises."""
    from core import heartbeat
    monkeypatch.setenv("KLAUS_DAILY_COST_ALERT", "not-a-number")
    assert heartbeat._parse_daily_cost_alert_threshold() == 5.0


def test_daily_cost_alert_threshold_parses_valid_env(monkeypatch):
    from core import heartbeat
    monkeypatch.setenv("KLAUS_DAILY_COST_ALERT", "12.5")
    assert heartbeat._parse_daily_cost_alert_threshold() == 12.5


def test_daily_cost_alert_threshold_defaults_when_unset(monkeypatch):
    from core import heartbeat
    monkeypatch.delenv("KLAUS_DAILY_COST_ALERT", raising=False)
    assert heartbeat._parse_daily_cost_alert_threshold() == 5.0


def test_check_daily_spend_under_threshold_returns_none(monkeypatch):
    from core import heartbeat
    monkeypatch.setenv("KLAUS_DAILY_COST_ALERT", "5")
    summary = {"total_cost_usd": 1.23, "smart_cost_usd": 1.0, "worker_cost_usd": 0.23}
    patch_usage, patch_tripwire, mock_tripwire = _mock_tripwire_stores(
        monkeypatch, summary=summary, already_fired=False)
    with patch_usage, patch_tripwire:
        result = heartbeat.check_daily_spend()
    assert result is None
    mock_tripwire.mark_fired.assert_not_called()


def test_check_daily_spend_already_fired_returns_none(monkeypatch):
    from core import heartbeat
    monkeypatch.setenv("KLAUS_DAILY_COST_ALERT", "5")
    summary = {"total_cost_usd": 12.0, "smart_cost_usd": 10.0, "worker_cost_usd": 2.0}
    patch_usage, patch_tripwire, mock_tripwire = _mock_tripwire_stores(
        monkeypatch, summary=summary, already_fired=True)
    with patch_usage, patch_tripwire:
        result = heartbeat.check_daily_spend()
    assert result is None
    mock_tripwire.mark_fired.assert_not_called()


def test_check_daily_spend_over_threshold_composes_alert(monkeypatch):
    from core import heartbeat
    monkeypatch.setenv("KLAUS_DAILY_COST_ALERT", "5")
    summary = {
        "total_cost_usd": 12.0, "smart_cost_usd": 9.0, "worker_cost_usd": 2.5,
        "cost_tripwire_cost_usd": 0.5,
        "total_cache_read_tokens": 800, "total_in_tokens": 200,
    }
    patch_usage, patch_tripwire, mock_tripwire = _mock_tripwire_stores(
        monkeypatch, summary=summary, already_fired=False)
    monkeypatch.setattr(heartbeat, "_compose_spend_alert", lambda payload: "composed alert text")
    with patch_usage, patch_tripwire:
        result = heartbeat.check_daily_spend()
    assert result is not None
    assert result["text"] == "composed alert text"
    assert result["summary"] == summary
    assert "date" in result
    # mark_fired must NOT be called here — Task 2 gates it on successful send.
    mock_tripwire.mark_fired.assert_not_called()


def test_check_daily_spend_never_raises_on_store_error(monkeypatch):
    """T-30.5-13/blocking-error safety: any internal error returns None, never raises."""
    from core import heartbeat
    from unittest.mock import patch
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    with patch("memory.firestore_db.LLMUsageStore", side_effect=RuntimeError("boom")):
        result = heartbeat.check_daily_spend()
    assert result is None


def test_cost_drivers_ranks_top_purposes_by_cost():
    from core.heartbeat import _cost_drivers
    summary = {
        "total_cost_usd": 12.0, "smart_cost_usd": 9.0, "worker_cost_usd": 2.5,
        "cost_tripwire_cost_usd": 0.5,
    }
    drivers = _cost_drivers(summary, top_n=2)
    assert drivers == [("smart", 9.0), ("worker", 2.5)]


def test_cache_hit_rate_computes_fraction():
    from core.heartbeat import _cache_hit_rate
    summary = {"total_cache_read_tokens": 800, "total_in_tokens": 200}
    rate = _cache_hit_rate(summary)
    assert abs(rate - 0.8) < 1e-9


def test_cache_hit_rate_zero_when_no_data():
    from core.heartbeat import _cache_hit_rate
    assert _cache_hit_rate({}) == 0.0


def test_spend_plain_text_fallback_contains_key_numbers():
    from core.heartbeat import _spend_plain_text_fallback
    payload = {
        "date": "2026-07-16", "total_cost_usd": 12.0, "threshold": 5.0,
        "top_drivers": [("smart", 9.0), ("worker", 2.5)], "cache_hit_rate": 0.8,
    }
    msg = _spend_plain_text_fallback(payload)
    assert "12.00" in msg
    assert "5.00" in msg
    assert "smart" in msg and "9.00" in msg
    assert "80%" in msg


def test_compose_spend_alert_uses_purpose_cost_tripwire(monkeypatch):
    """D-04/T-30.5-15: the compose call must use purpose='cost_tripwire' (auditable cost)."""
    from core import heartbeat
    captured = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def chat(self, *, messages, system, purpose):
            captured["purpose"] = purpose
            return {"text": "a real Klaus-composed alert"}

    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")
    monkeypatch.setattr("core.llm_client.LLMClient", _FakeClient)
    payload = {
        "date": "2026-07-16", "total_cost_usd": 12.0, "threshold": 5.0,
        "top_drivers": [("smart", 9.0)], "cache_hit_rate": 0.8,
    }
    result = heartbeat._compose_spend_alert(payload)
    assert result == "a real Klaus-composed alert"
    assert captured["purpose"] == "cost_tripwire"


def test_compose_spend_alert_falls_back_on_llm_failure(monkeypatch):
    """D-04: if the Sonnet compose call fails, use the deterministic template."""
    from core import heartbeat

    class _RaisingClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, *, messages, system, purpose):
            raise RuntimeError("Anthropic is down")

    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")
    monkeypatch.setattr("core.llm_client.LLMClient", _RaisingClient)
    payload = {
        "date": "2026-07-16", "total_cost_usd": 12.0, "threshold": 5.0,
        "top_drivers": [("smart", 9.0)], "cache_hit_rate": 0.8,
    }
    result = heartbeat._compose_spend_alert(payload)
    assert "12.00" in result
    assert "5.00" in result


# ---------------------------------------------------------------------------
# Phase 30.5 Plan 05 Task 2 — wiring _send_daily_spend_alert into run_tick
# ---------------------------------------------------------------------------

def test_send_daily_spend_alert_sends_and_marks_fired_on_success(monkeypatch):
    """The tripwire is sent via send_and_inject, then mark_fired is called
    only after that send succeeds."""
    import asyncio
    from core import heartbeat

    alert = {"date": "2026-07-16", "text": "spend alert text", "summary": {"total_cost_usd": 12.0}}
    monkeypatch.setattr(heartbeat, "check_daily_spend", lambda: alert)

    sent = []
    async def _send(bot, text, **kw):
        sent.append((text, kw))
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)

    marked = {}
    class _FakeTripwireStore:
        def __init__(self, **kwargs):
            pass
        def mark_fired(self, date_str, summary):
            marked["date"] = date_str
            marked["summary"] = summary
    monkeypatch.setattr("memory.firestore_db.CostTripwireLogStore", _FakeTripwireStore)

    asyncio.run(heartbeat._send_daily_spend_alert(object()))

    assert sent == [("spend alert text", {"inject_into_conversation": True, "message_class": "alert"})]
    assert marked == {"date": "2026-07-16", "summary": {"total_cost_usd": 12.0}}


def test_send_daily_spend_alert_no_alert_sends_nothing(monkeypatch):
    """Second heartbeat tick on the same date: check_daily_spend returns None
    (already_fired) -> no send, no mark_fired call."""
    import asyncio
    from core import heartbeat

    monkeypatch.setattr(heartbeat, "check_daily_spend", lambda: None)

    sent = []
    async def _send(bot, text, **kw):
        sent.append(text)
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)

    marked = {"called": False}
    class _FakeTripwireStore:
        def __init__(self, **kwargs):
            pass
        def mark_fired(self, date_str, summary):
            marked["called"] = True
    monkeypatch.setattr("memory.firestore_db.CostTripwireLogStore", _FakeTripwireStore)

    asyncio.run(heartbeat._send_daily_spend_alert(object()))

    assert sent == []
    assert marked["called"] is False


def test_send_daily_spend_alert_send_failure_leaves_not_fired(monkeypatch):
    """A simulated send failure must NOT call mark_fired — retry-safe on the
    next tick (mirrors OutreachLogStore D-10 gating)."""
    import asyncio
    from core import heartbeat

    alert = {"date": "2026-07-16", "text": "spend alert text", "summary": {"total_cost_usd": 12.0}}
    monkeypatch.setattr(heartbeat, "check_daily_spend", lambda: alert)

    async def _failing_send(bot, text, **kw):
        raise RuntimeError("Telegram send failed")
    monkeypatch.setattr(heartbeat, "send_and_inject", _failing_send)

    marked = {"called": False}
    class _FakeTripwireStore:
        def __init__(self, **kwargs):
            pass
        def mark_fired(self, date_str, summary):
            marked["called"] = True
    monkeypatch.setattr("memory.firestore_db.CostTripwireLogStore", _FakeTripwireStore)

    # Never raises into the caller (wrapped in try/except).
    asyncio.run(heartbeat._send_daily_spend_alert(object()))

    assert marked["called"] is False


def test_run_tick_invokes_daily_spend_alert(monkeypatch):
    """run_tick must call _send_daily_spend_alert as a separate guarded step,
    outside _collect_signals/_tiers_for_now."""
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core import heartbeat

    monkeypatch.setattr(heartbeat, "_load_config", lambda: {
        "enabled": True, "quiet_start": "22:00", "quiet_end": "07:00",
        "timezone": "Asia/Jerusalem", "digest_hour": 9,
        "weekly_digest_day": 1, "reping_interval_hours": 24})
    monkeypatch.setattr(heartbeat, "_collect_signals", lambda **k: [])
    monkeypatch.setattr(heartbeat, "_register_incidents", lambda crits, cfg: [])
    monkeypatch.setattr(heartbeat, "_resolve_absent", lambda fps: None)
    monkeypatch.setattr(heartbeat, "_run_tick_brain_pass", lambda s, **k: None)

    async def _noop_drain(bot, now, cfg):
        pass
    monkeypatch.setattr(heartbeat, "_drain_quiet_queue", _noop_drain)

    called = {"spend": False}
    async def _spy_spend(bot):
        called["spend"] = True
    monkeypatch.setattr(heartbeat, "_send_daily_spend_alert", _spy_spend)

    noon = datetime(2026, 5, 19, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    asyncio.run(heartbeat.run_tick(object(), now=noon))

    assert called["spend"] is True


# ---------------------------------------------------------------------------
# Plan 32-05 Task 3 — check_groq_budget() (MEM-06, D-07): 80% + fallback-spike
# alert, once/day, mirrors check_daily_spend()'s shape.
# ---------------------------------------------------------------------------

def _mock_groq_budget_stores(monkeypatch, *, ledger_today, usage_today, already_alerted):
    """Patch memory.firestore_db.GroqTokenLedgerStore/LLMUsageStore so
    check_groq_budget() never reaches real Firestore."""
    from unittest.mock import MagicMock, patch
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    mock_ledger_store = MagicMock()
    mock_ledger_store.today.return_value = ledger_today
    mock_ledger_store.already_alerted.return_value = already_alerted
    mock_usage_store = MagicMock()
    mock_usage_store.summary.return_value = usage_today

    return (
        patch("memory.firestore_db.GroqTokenLedgerStore", return_value=mock_ledger_store),
        patch("memory.firestore_db.LLMUsageStore", return_value=mock_usage_store),
        mock_ledger_store,
    )


def test_check_groq_budget_under_threshold_no_spike_returns_none(monkeypatch):
    """(b) Below 160K and no fallback spike -> no alert."""
    from core import heartbeat
    patch_ledger, patch_usage, mock_ledger = _mock_groq_budget_stores(
        monkeypatch,
        ledger_today={"total_tokens": 50_000},
        usage_today={"tick_fallback_calls": 1, "tick_autonomous_fallback_calls": 0},
        already_alerted=False,
    )
    with patch_ledger, patch_usage:
        result = heartbeat.check_groq_budget()
    assert result is None
    mock_ledger.mark_alerted.assert_not_called()


def test_check_groq_budget_over_threshold_composes_alert(monkeypatch):
    """(a) At/over 160K -> fires exactly one alert (per call)."""
    from core import heartbeat
    patch_ledger, patch_usage, mock_ledger = _mock_groq_budget_stores(
        monkeypatch,
        ledger_today={"total_tokens": 160_000},
        usage_today={"tick_fallback_calls": 1, "tick_autonomous_fallback_calls": 0},
        already_alerted=False,
    )
    monkeypatch.setattr(heartbeat, "_compose_groq_budget_alert", lambda payload: "composed groq alert")
    with patch_ledger, patch_usage:
        result = heartbeat.check_groq_budget()
    assert result is not None
    assert result["text"] == "composed groq alert"
    assert result["summary"]["total_tokens"] == 160_000
    assert result["summary"]["over_budget"] is True
    assert "date" in result
    # mark_alerted must NOT be called here — the caller gates it on send.
    mock_ledger.mark_alerted.assert_not_called()


def test_check_groq_budget_already_alerted_returns_none(monkeypatch):
    """(a) Suppressed on a second same-day call."""
    from core import heartbeat
    patch_ledger, patch_usage, mock_ledger = _mock_groq_budget_stores(
        monkeypatch,
        ledger_today={"total_tokens": 180_000},
        usage_today={},
        already_alerted=True,
    )
    with patch_ledger, patch_usage:
        result = heartbeat.check_groq_budget()
    assert result is None
    mock_ledger.mark_alerted.assert_not_called()


def test_check_groq_budget_fallback_spike_raises_alert(monkeypatch):
    """(c) A fallback-purpose call-count spike raises an alert even when the
    raw token total is well under 80%."""
    from core import heartbeat
    patch_ledger, patch_usage, mock_ledger = _mock_groq_budget_stores(
        monkeypatch,
        ledger_today={"total_tokens": 5_000},
        usage_today={"tick_fallback_calls": 8, "tick_autonomous_fallback_calls": 5},
        already_alerted=False,
    )
    monkeypatch.setattr(heartbeat, "_compose_groq_budget_alert", lambda payload: "spike alert")
    with patch_ledger, patch_usage:
        result = heartbeat.check_groq_budget()
    assert result is not None
    assert result["summary"]["spiking"] is True
    assert result["summary"]["fallback_calls"] == 13
    assert result["summary"]["over_budget"] is False


def test_check_groq_budget_no_spike_below_threshold_no_alert(monkeypatch):
    """Fallback calls under the spike threshold, and under 80% token budget
    -> no alert."""
    from core import heartbeat
    patch_ledger, patch_usage, mock_ledger = _mock_groq_budget_stores(
        monkeypatch,
        ledger_today={"total_tokens": 10_000},
        usage_today={"tick_fallback_calls": 3, "tick_autonomous_fallback_calls": 2},
        already_alerted=False,
    )
    with patch_ledger, patch_usage:
        result = heartbeat.check_groq_budget()
    assert result is None


def test_check_groq_budget_never_raises_on_store_error(monkeypatch):
    """(d) A ledger read failure degrades to no-alert without raising."""
    from core import heartbeat
    from unittest.mock import patch
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    with patch("memory.firestore_db.GroqTokenLedgerStore", side_effect=RuntimeError("boom")):
        result = heartbeat.check_groq_budget()
    assert result is None


def test_groq_budget_plain_text_fallback_contains_key_numbers():
    from core.heartbeat import _groq_budget_plain_text_fallback
    payload = {
        "total_tokens": 165_000, "cap": 200_000, "fraction": 0.825,
        "over_budget": True, "fallback_calls": 3, "fallback_threshold": 10,
        "spiking": False,
    }
    msg = _groq_budget_plain_text_fallback(payload)
    assert "165,000" in msg
    assert "200,000" in msg
    assert "82%" in msg


def test_groq_budget_plain_text_fallback_mentions_spike():
    from core.heartbeat import _groq_budget_plain_text_fallback
    payload = {
        "total_tokens": 5_000, "cap": 200_000, "fraction": 0.025,
        "over_budget": False, "fallback_calls": 15, "fallback_threshold": 10,
        "spiking": True,
    }
    msg = _groq_budget_plain_text_fallback(payload)
    assert "15" in msg
    assert "10" in msg


def test_compose_groq_budget_alert_uses_purpose_groq_budget_tripwire(monkeypatch):
    """The compose call must use purpose='groq_budget_tripwire' (auditable cost)."""
    from core import heartbeat
    captured = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def chat(self, *, messages, system, purpose):
            captured["purpose"] = purpose
            return {"text": "a real Klaus-composed groq budget alert"}

    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")
    monkeypatch.setattr("core.llm_client.LLMClient", _FakeClient)
    payload = {
        "date": "2026-07-22", "total_tokens": 165_000, "cap": 200_000,
        "fraction": 0.825, "over_budget": True, "fallback_calls": 1,
        "fallback_threshold": 10, "spiking": False,
    }
    result = heartbeat._compose_groq_budget_alert(payload)
    assert result == "a real Klaus-composed groq budget alert"
    assert captured["purpose"] == "groq_budget_tripwire"


def test_compose_groq_budget_alert_falls_back_on_llm_failure(monkeypatch):
    """If the Sonnet compose call fails, use the deterministic template."""
    from core import heartbeat

    class _RaisingClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, *, messages, system, purpose):
            raise RuntimeError("Anthropic is down")

    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")
    monkeypatch.setattr("core.llm_client.LLMClient", _RaisingClient)
    payload = {
        "date": "2026-07-22", "total_tokens": 165_000, "cap": 200_000,
        "fraction": 0.825, "over_budget": True, "fallback_calls": 1,
        "fallback_threshold": 10, "spiking": False,
    }
    result = heartbeat._compose_groq_budget_alert(payload)
    assert "165,000" in result
    assert "200,000" in result


def test_send_groq_budget_alert_sends_and_marks_alerted_on_success(monkeypatch):
    """The tripwire is sent via send_and_inject, then mark_alerted is called
    only after that send succeeds (D-10 gating)."""
    import asyncio
    from core import heartbeat

    alert = {"date": "2026-07-22", "text": "groq budget alert text",
              "summary": {"total_tokens": 165_000}}
    monkeypatch.setattr(heartbeat, "check_groq_budget", lambda: alert)

    sent = []
    async def _send(bot, text, **kw):
        sent.append((text, kw))
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)

    marked = {}
    class _FakeLedgerStore:
        def __init__(self, **kwargs):
            pass
        def mark_alerted(self, date_str, summary):
            marked["date"] = date_str
            marked["summary"] = summary
    monkeypatch.setattr("memory.firestore_db.GroqTokenLedgerStore", _FakeLedgerStore)

    asyncio.run(heartbeat._send_groq_budget_alert(object()))

    assert sent == [("groq budget alert text",
                      {"inject_into_conversation": True, "message_class": "alert"})]
    assert marked == {"date": "2026-07-22", "summary": {"total_tokens": 165_000}}


def test_send_groq_budget_alert_no_alert_sends_nothing(monkeypatch):
    """check_groq_budget returns None (below threshold / already alerted)
    -> no send, no mark_alerted call."""
    import asyncio
    from core import heartbeat

    monkeypatch.setattr(heartbeat, "check_groq_budget", lambda: None)

    sent = []
    async def _send(bot, text, **kw):
        sent.append(text)
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)

    marked = {"called": False}
    class _FakeLedgerStore:
        def __init__(self, **kwargs):
            pass
        def mark_alerted(self, date_str, summary):
            marked["called"] = True
    monkeypatch.setattr("memory.firestore_db.GroqTokenLedgerStore", _FakeLedgerStore)

    asyncio.run(heartbeat._send_groq_budget_alert(object()))

    assert sent == []
    assert marked["called"] is False


def test_send_groq_budget_alert_send_failure_leaves_not_alerted(monkeypatch):
    """A simulated send failure must NOT call mark_alerted — retry-safe on
    the next tick (mirrors OutreachLogStore/CostTripwireLogStore D-10 gating)."""
    import asyncio
    from core import heartbeat

    alert = {"date": "2026-07-22", "text": "groq budget alert text",
              "summary": {"total_tokens": 165_000}}
    monkeypatch.setattr(heartbeat, "check_groq_budget", lambda: alert)

    async def _failing_send(bot, text, **kw):
        raise RuntimeError("Telegram send failed")
    monkeypatch.setattr(heartbeat, "send_and_inject", _failing_send)

    marked = {"called": False}
    class _FakeLedgerStore:
        def __init__(self, **kwargs):
            pass
        def mark_alerted(self, date_str, summary):
            marked["called"] = True
    monkeypatch.setattr("memory.firestore_db.GroqTokenLedgerStore", _FakeLedgerStore)

    # Never raises into the caller (wrapped in try/except).
    asyncio.run(heartbeat._send_groq_budget_alert(object()))

    assert marked["called"] is False


def test_run_tick_invokes_groq_budget_alert(monkeypatch):
    """run_tick must call _send_groq_budget_alert as a separate guarded step,
    alongside _send_daily_spend_alert."""
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core import heartbeat

    monkeypatch.setattr(heartbeat, "_load_config", lambda: {
        "enabled": True, "quiet_start": "22:00", "quiet_end": "07:00",
        "timezone": "Asia/Jerusalem", "digest_hour": 9,
        "weekly_digest_day": 1, "reping_interval_hours": 24})
    monkeypatch.setattr(heartbeat, "_collect_signals", lambda **k: [])
    monkeypatch.setattr(heartbeat, "_register_incidents", lambda crits, cfg: [])
    monkeypatch.setattr(heartbeat, "_resolve_absent", lambda fps: None)
    monkeypatch.setattr(heartbeat, "_run_tick_brain_pass", lambda s, **k: None)

    async def _noop_spend(bot):
        pass
    monkeypatch.setattr(heartbeat, "_send_daily_spend_alert", _noop_spend)

    async def _noop_drain(bot, now, cfg):
        pass
    monkeypatch.setattr(heartbeat, "_drain_quiet_queue", _noop_drain)

    called = {"groq_budget": False}
    async def _spy_groq_budget(bot):
        called["groq_budget"] = True
    monkeypatch.setattr(heartbeat, "_send_groq_budget_alert", _spy_groq_budget)

    noon = datetime(2026, 5, 19, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    asyncio.run(heartbeat.run_tick(object(), now=noon))

    assert called["groq_budget"] is True

