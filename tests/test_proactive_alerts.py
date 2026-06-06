# tests/test_proactive_alerts.py
from __future__ import annotations

import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Must import the module before any @patch decorators reference it,
# otherwise Python can't resolve "core.proactive_alerts.<attr>" at decoration time.
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
import core.proactive_alerts  # noqa: E402  (side-effect import for patch resolution)


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@patch("core.proactive_alerts._already_sent", return_value=True)
def test_skips_when_already_sent(mock_already_sent, mock_bot):
    """No Telegram send if we already processed this date."""
    from core.proactive_alerts import run_proactive_alerts
    asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_not_called()


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts", return_value=[])
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_no_alerts_marks_processed_no_send(
    mock_cal, mock_home, mock_weather, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """If no issues found, mark processed with alert_sent=False and don't send."""
    mock_cal.return_value.list_events.return_value = []
    # fetch_weather is imported locally inside run_proactive_alerts;
    # patch at source module so the local import gets the mock.
    with patch("mcp_tools.weather_tool.fetch_weather", side_effect=Exception("no weather")):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_not_called()
    mock_mark.assert_called_once_with("2026-05-12", alert_sent=False)


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_sends_telegram_when_alerts_found(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """When alerts detected, send Telegram and mark processed with alert_sent=True."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    # Patch _compose_alert directly so the test exercises the send path,
    # not the fallback path, regardless of env vars.
    with patch("core.proactive_alerts._compose_alert", return_value="LLM-produced alert text"):
        with patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
            from core.proactive_alerts import run_proactive_alerts
            asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_called_once()
    call_text = mock_bot.send_message.call_args.kwargs.get("text", "")
    assert call_text == "LLM-produced alert text"
    mock_mark.assert_called_once_with("2026-05-12", alert_sent=True)


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_plain_text_fallback_on_llm_failure(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """If LLM composition fails, fall back to plain text (still sends)."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    # LLMClient is imported locally inside _compose_alert; patch at source module
    with patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        with patch("core.llm_client.LLMClient", side_effect=Exception("LLM down")):
            from core.proactive_alerts import run_proactive_alerts
            asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_called_once()
    # Should still have sent something (plain-text fallback)
    call_text = mock_bot.send_message.call_args.kwargs.get("text", "")
    assert call_text.startswith("Tomorrow (2026-05-12) — heads up, Sir:")


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_recovery_concern_injected_into_alert_context(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """RECOVERY-03 / D-16: when compute_recovery_concern returns a concern, it is
    injected into the alerts_context handed to _compose_alert (evening path parity
    with the morning briefing)."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    concern = {"level": "strong", "acwr": 1.6, "hrv_status": "unbalanced",
               "sleep_score": 52, "intensity": "high"}
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return "LLM-produced alert text"

    # compute_recovery_concern + fetch_garmin_today are imported locally inside
    # run_proactive_alerts; patch at their source modules so the local imports resolve.
    with patch("core.training_checkin.compute_recovery_concern", return_value=concern), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value={"date": "2026-05-12"}), \
         patch("core.proactive_alerts._compose_alert", side_effect=_capture), \
         patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))

    assert captured["ctx"].get("recovery_concern") == concern
    mock_bot.send_message.assert_called_once()


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_no_recovery_concern_key_when_none(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """D-13 no-fabrication: when compute_recovery_concern returns None, the
    recovery_concern key is absent from alerts_context (no 'all clear' placeholder)."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return "LLM-produced alert text"

    with patch("core.training_checkin.compute_recovery_concern", return_value=None), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value={"date": "2026-05-12"}), \
         patch("core.proactive_alerts._compose_alert", side_effect=_capture), \
         patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))

    assert "recovery_concern" not in captured["ctx"]


# ====================================================================== #
# Phase 23 Plan 03 — end-of-block benchmark trigger (BLOCK-02)            #
# ====================================================================== #

# The block-end check constructs BlockStore from env; ensure a project id exists.
os.environ.setdefault("GCP_PROJECT_ID", "test-project")

_FACETS = ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"]


def _block(
    *,
    label="Aerobic Base",
    start_date="2026-06-21",
    end_date="2026-07-18",
    benchmark_due=False,
    doc_id="2026-06-21_aerobic_base",
):
    return {
        "doc_id": doc_id,
        "block_id": doc_id,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "focus_facets": list(_FACETS),
        "status": "active",
        "benchmark_due": benchmark_due,
    }


class TestEvaluateBenchmarkState:
    """Unit tests for the pure _evaluate_benchmark_state state machine (D-02/D-07/D-08/D-09)."""

    def test_no_benchmark_due_block_4(self):
        """D-02: Block 4 (race week) never benchmarks, even within 3 days."""
        from core.proactive_alerts import _evaluate_benchmark_state
        b = _block(label="Race Specificity → Taper → Race Week", end_date="2026-10-10")
        assert _evaluate_benchmark_state(b, "2026-10-09", 75, 80, 1.0) is None

    def test_more_than_3_days_returns_none(self):
        from core.proactive_alerts import _evaluate_benchmark_state
        assert _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-10", 75, 80, 1.0) is None

    def test_none_block_returns_none(self):
        from core.proactive_alerts import _evaluate_benchmark_state
        assert _evaluate_benchmark_state(None, "2026-07-16", 75, 80, 1.0) is None

    def test_validity_gate_pass(self):
        """benchmark_due + HRV 70/80 (87.5%) + ACWR 1.0 → window_open."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 70, 80, 1.0)
        assert s and s["state"] == "benchmark_window_open"
        assert s["facets"] == _FACETS

    def test_validity_gate_fail_hrv(self):
        """HRV 55/80 (68.75% < 70%) → deferred."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 55, 80, 1.0)
        assert s and s["state"] == "benchmark_deferred"

    def test_validity_gate_fail_acwr(self):
        """ACWR 1.35 (> 1.2) → deferred even with good HRV."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 75, 80, 1.35)
        assert s and s["state"] == "benchmark_deferred"

    def test_stale_window(self):
        """today > end_date with red gate → stale (one caveated prompt, D-09)."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-19", 55, 80, 1.35)
        assert s and s["state"] == "benchmark_stale"

    def test_gate_unknown_passes(self):
        """Missing hrv_baseline → gate unknown → PASS (err toward prompting)."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 75, None, None)
        assert s and s["state"] == "benchmark_window_open"

    def test_deferred_message_has_number(self):
        """D-08: deferred payload carries hrv_overnight + % of baseline for the numeric reason."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 55, 80, 1.0)
        assert s["hrv_overnight"] == 55
        assert s["hrv_pct"] == round(55 / 80 * 100)  # 69


def _near_end_block1():
    """Block 1 whose end_date is 2 days from now (Asia/Jerusalem)."""
    from core.proactive_alerts import _TZ
    from datetime import datetime as _dt, timedelta as _td
    end = (_dt.now(_TZ).date() + _td(days=2)).isoformat()
    return _block(end_date=end)


@patch("core.proactive_alerts._already_sent", return_value=True)
def test_benchmark_check_before_dedup_gate(mock_already_sent, mock_bot):
    """Pitfall 3 / T-23-11: set_benchmark_due runs BEFORE the _already_sent gate,
    so the flag is still set even when the cron already sent for this date."""
    mock_bs = MagicMock()
    mock_bs.return_value.get_current.return_value = _near_end_block1()
    with patch("memory.firestore_db.BlockStore", mock_bs):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-07-16"))
    mock_bs.return_value.set_benchmark_due.assert_called_once()


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts", return_value=[])
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_benchmark_only_night_still_sends(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """BLOCK-02 SC / T-23-10: a benchmark-only deload night (no weather/overload/travel
    alert) must NOT hit the no-alert early return — it still composes and sends."""
    mock_cal.return_value.list_events.return_value = []
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return "LLM alert text"

    mock_bs = MagicMock()
    mock_bs.return_value.get_current.return_value = _near_end_block1()
    with patch("memory.firestore_db.BlockStore", mock_bs), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today",
               return_value={"hrv_overnight": 75, "hrv_baseline": 80}), \
         patch("mcp_tools.garmin_tool.compute_acwr_from_db", return_value={"ratio": 1.0}), \
         patch("core.training_checkin.compute_recovery_concern", return_value=None), \
         patch("core.proactive_alerts._compose_alert", side_effect=_capture), \
         patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2099-01-01"))

    assert captured.get("ctx", {}).get("benchmark", {}).get("state") == "benchmark_window_open"
    mock_bot.send_message.assert_called_once()
