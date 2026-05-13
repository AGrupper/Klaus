# tests/test_morning_briefing.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import os


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")
    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")


@pytest.fixture
def bot():
    b = AsyncMock()
    b.send_message = AsyncMock()
    return b


# --- Plain text fallback tests (no mocking complexity) ---

def test_plain_text_fallback_all_sections_present():
    """Fallback renders all 5 sections even when all data is missing."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None,
        "calendar": None,
        "email": None,
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": "No tasks today, sir.", "overdue": [], "today": [], "due_today": []},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "Good morning, sir." in result
    assert "📅 Schedule" in result
    assert "Nothing on the calendar today, sir." in result
    assert "📧 Email" in result
    assert "No actionable email this morning, sir." in result
    assert "✅ Tasks" in result
    assert "No tasks today, sir." in result
    assert "📚 https://readwise.io/dailyreview" in result


def test_plain_text_fallback_with_events():
    """Fallback renders events correctly."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None,
        "calendar": [
            {"start": "2026-05-12T09:30:00+03:00", "end": "2026-05-12T10:30:00+03:00",
             "summary": "Team standup"},
        ],
        "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "09:30" in result
    assert "Team standup" in result


def test_plain_text_fallback_task_data_unavailable():
    """When staleness_warning is set, it replaces the tasks section body."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": "Task data unavailable, sir."},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "Task data unavailable, sir." in result


def test_plain_text_fallback_no_tasks_at_all():
    """When no tasks, overdue, or due_today, renders 'No tasks today' message."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "No tasks today, sir." in result


def test_plain_text_fallback_with_overdue_tasks():
    """Overdue tasks are rendered with [!] prefix."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {
            "staleness_warning": None,
            "overdue": [{"title": "Call dentist", "area": "Health"}],
            "today": [],
            "due_today": [],
        },
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "[!] Call dentist" in result
    assert "Health" in result


def test_plain_text_fallback_with_emails():
    """Email section renders sender and subject."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None, "calendar": [], "email": [
            {"sender": "boss@example.com", "subject": "Q2 Review"},
        ],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "boss@example.com" in result
    assert "Q2 Review" in result


# --- LLM composition tests ---

def test_compose_briefing_llm_failure_falls_back():
    """If LLM fails, _compose_briefing returns plain-text fallback."""
    from core.morning_briefing import _compose_briefing
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": "No tasks today, sir.", "overdue": [], "today": [], "due_today": []},
    }
    # LLMClient is imported lazily inside _compose_briefing; patch the source module.
    with patch("core.llm_client.LLMClient", side_effect=Exception("LLM down")), \
         patch("pathlib.Path.read_text", return_value="System prompt for {today_date}"):
        result = _compose_briefing(data, "2026-05-12")
    assert "Good morning, sir." in result
    assert "📅 Schedule" in result
    assert "📚 https://readwise.io/dailyreview" in result


def test_compose_briefing_uses_llm_when_available():
    """If LLM succeeds and returns text, that text is used."""
    from core.morning_briefing import _compose_briefing
    data = {"weather": None, "calendar": [], "email": [], "garmin": {"state": 2}, "tasks": {}}
    mock_client = MagicMock()
    mock_client.chat.return_value = {"text": "Good morning, Sir! All clear today.", "tool_calls": [], "stop_reason": "end_turn"}
    # Patch at the source module so the lazy import picks up the mock.
    with patch("core.llm_client.LLMClient", return_value=mock_client), \
         patch("pathlib.Path.read_text", return_value="System prompt for {today_date}"):
        result = _compose_briefing(data, "2026-05-12")
    assert result == "Good morning, Sir! All clear today."


def test_compose_briefing_llm_empty_text_falls_back():
    """If LLM returns empty text, fallback is used."""
    from core.morning_briefing import _compose_briefing
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }
    mock_client = MagicMock()
    mock_client.chat.return_value = {"text": "", "tool_calls": [], "stop_reason": "end_turn"}
    with patch("core.llm_client.LLMClient", return_value=mock_client), \
         patch("pathlib.Path.read_text", return_value="System prompt"):
        result = _compose_briefing(data, "2026-05-12")
    assert "Good morning, sir." in result


# --- Garmin sync detection tests ---

def test_fetch_garmin_safe_returns_none_on_exception():
    """_fetch_garmin_safe returns None when garmin_tool raises."""
    with patch("mcp_tools.garmin_tool.fetch_garmin_today", side_effect=Exception("auth failed")):
        # Reimport to get fresh reference
        import importlib
        import core.morning_briefing as mb
        result = mb._fetch_garmin_safe()
    assert result is None


def test_fetch_garmin_safe_returns_none_when_no_sleep():
    """_fetch_garmin_safe returns None when Garmin returns data without sleep fields."""
    import core.morning_briefing as mb
    today = "2026-05-12"
    garmin_data = {"date": today, "sleep_score": None, "sleep_hours": None, "hrv_status": "BALANCED"}
    with patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=garmin_data):
        result = mb._fetch_garmin_safe(today)
    assert result is None


def test_fetch_garmin_safe_returns_data_when_sleep_score_present():
    """_fetch_garmin_safe returns data when sleep_score is present."""
    import core.morning_briefing as mb
    today = "2026-05-12"
    garmin_data = {"date": today, "sleep_score": 78, "sleep_hours": 7.5, "hrv_status": "BALANCED"}
    with patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=garmin_data):
        result = mb._fetch_garmin_safe(today)
    assert result is not None
    assert result["sleep_score"] == 78


# --- State machine tests ---

@pytest.mark.skip(reason="datetime mocking complexity — covered by CLI smoke test")
def test_handle_tick_skips_when_already_sent(bot):
    """Tick exits silently if today's briefing is already sent."""
    from datetime import datetime as real_dt
    from zoneinfo import ZoneInfo
    now = real_dt(2026, 5, 12, 7, 30, tzinfo=ZoneInfo("Asia/Jerusalem"))
    with patch("core.morning_briefing._get_state", return_value={"status": "sent"}), \
         patch("core.morning_briefing.datetime") as mock_dt, \
         patch("core.morning_briefing._set_state") as mock_set:
        mock_dt.now.return_value = now
        from core.morning_briefing import handle_tick
        asyncio.run(handle_tick(bot))
    mock_set.assert_not_called()
    bot.send_message.assert_not_called()


@pytest.mark.skip(reason="datetime mocking complexity — covered by CLI smoke test")
def test_handle_tick_pending_no_garmin_does_nothing(bot):
    """If Garmin hasn't synced yet, tick exits without setting state."""
    from datetime import datetime as real_dt, timedelta as real_td
    from zoneinfo import ZoneInfo
    now = real_dt(2026, 5, 12, 7, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    with patch("core.morning_briefing._get_state", return_value={"status": "pending"}), \
         patch("core.morning_briefing._set_state") as mock_set, \
         patch("core.morning_briefing._fetch_garmin_safe", return_value=None), \
         patch("core.morning_briefing.datetime") as mock_dt, \
         patch("core.morning_briefing.timedelta", real_td):
        mock_dt.now.return_value = now
        from core.morning_briefing import handle_tick
        asyncio.run(handle_tick(bot))
    mock_set.assert_not_called()


@pytest.mark.skip(reason="datetime mocking complexity — covered by CLI smoke test")
def test_handle_tick_sync_detected_fires_briefing(bot):
    """If state is sync_detected, the briefing fires and state is set to sent."""
    from datetime import datetime as real_dt
    from zoneinfo import ZoneInfo
    now = real_dt(2026, 5, 12, 7, 10, tzinfo=ZoneInfo("Asia/Jerusalem"))
    with patch("core.morning_briefing._get_state", return_value={"status": "sync_detected", "retry_count": 0}), \
         patch("core.morning_briefing._set_state") as mock_set, \
         patch("core.morning_briefing.run_morning_briefing", new_callable=AsyncMock) as mock_run, \
         patch("core.morning_briefing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        from core.morning_briefing import handle_tick
        asyncio.run(handle_tick(bot))
    mock_run.assert_called_once()
    set_calls = mock_set.call_args_list
    assert any(call[0][1].get("status") == "sent" for call in set_calls)


def test_manual_trigger_bypasses_dedup(bot):
    """run_morning_briefing with dedup=False fires even if state is 'sent'."""
    # send_and_inject is a lazy import inside run_morning_briefing; patch at its source.
    with patch("core.morning_briefing._get_state", return_value={"status": "sent"}), \
         patch("core.morning_briefing._set_state"), \
         patch("core.morning_briefing._gather_data", return_value={}), \
         patch("core.morning_briefing._compose_briefing", return_value="Good morning, sir."), \
         patch("core.scheduled_message.send_and_inject", new_callable=AsyncMock) as mock_send:
        from core.morning_briefing import run_morning_briefing
        asyncio.run(run_morning_briefing(bot, "2026-05-12", dedup=False))
    mock_send.assert_called_once()


def test_dedup_skips_when_already_sent(bot):
    """run_morning_briefing with dedup=True skips if state is 'sent'."""
    # When dedup blocks, _gather_data and send_and_inject are never reached.
    with patch("core.morning_briefing._get_state", return_value={"status": "sent"}), \
         patch("core.morning_briefing._set_state") as mock_set, \
         patch("core.morning_briefing._gather_data") as mock_gather:
        from core.morning_briefing import run_morning_briefing
        asyncio.run(run_morning_briefing(bot, "2026-05-12", dedup=True))
    mock_gather.assert_not_called()
    mock_set.assert_not_called()
