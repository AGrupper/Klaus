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
