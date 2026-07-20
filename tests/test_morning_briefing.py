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


def test_prompt_uses_coaching_context_only_when_present():
    """Light morning note: coaching/nutrition context is optional, used only when real."""
    content = open("prompts/morning_briefing.md", encoding="utf-8").read()
    lowered = content.lower()
    assert "nutrition_targets" in lowered
    # The note must treat coaching context as optional, not a mandatory section
    assert "only if there's something real" in lowered or "use only" in lowered


# --- Plain text fallback tests (no mocking complexity) ---

def test_plain_text_fallback_is_light_note_no_email_no_readwise():
    """Light fallback: warm opener + Today section, no email block, no readwise link."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None,
        "calendar": None,
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": "Task data unavailable.", "overdue": [], "today": [], "due_today": []},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert result.startswith("Morning.")
    assert "Today:" in result
    assert "Nothing on the calendar." in result
    # The heavy briefing sections are gone
    assert "📧 Email" not in result
    assert "readwise.io" not in result
    assert "sir" not in result.lower()


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
    """When nothing's on and no overdue tasks, the light note just states that."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None, "calendar": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "Nothing on the calendar." in result
    # No overdue → no task line at all (light)
    assert "overdue" not in result.lower()


def test_plain_text_fallback_with_overdue_tasks():
    """Overdue tasks render as a single light count line, not a labeled section."""
    from core.morning_briefing import _plain_text_fallback
    data = {
        "weather": None, "calendar": [],
        "garmin": {"state": 2},
        "tasks": {
            "staleness_warning": None,
            "overdue": [{"title": "Call dentist", "area": "Health"}],
            "today": [],
            "due_today": [],
        },
    }
    result = _plain_text_fallback(data, "2026-05-12")
    assert "overdue" in result.lower()
    assert "Call dentist" in result


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
    assert result.startswith("Morning.")
    assert "Today:" in result


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
    assert result.startswith("Morning.")


# --- Phase 30.5 Plan 06 (BRAIN-01) — SMART_AGENT_FALLBACK_* Gemini compose fallback ---

def test_compose_briefing_brain_fails_gemini_fallback_composes(monkeypatch):
    """Brain raises -> SMART_AGENT_FALLBACK_* Gemini compose is used (not the plain template)."""
    from core.morning_briefing import _compose_briefing
    monkeypatch.setenv("SMART_AGENT_FALLBACK_BACKEND", "gemini")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_API_KEY", "test-fallback-key")
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }

    call_count = {"n": 0}

    def _client_factory(*args, **kwargs):
        call_count["n"] += 1
        client = MagicMock()
        if call_count["n"] == 1:
            # Primary (brain) call raises.
            client.chat.side_effect = Exception("brain down")
        else:
            # Fallback (Gemini) call succeeds.
            client.chat.return_value = {
                "text": "Gemini-composed briefing text.",
                "tool_calls": [], "stop_reason": "end_turn",
            }
        return client

    with patch("core.llm_client.LLMClient", side_effect=_client_factory), \
         patch("pathlib.Path.read_text", return_value="System prompt for {today_date}"):
        result = _compose_briefing(data, "2026-05-12")

    assert result == "Gemini-composed briefing text."
    assert not result.startswith("Morning.")


def test_compose_briefing_brain_and_fallback_fail_returns_plain_template(monkeypatch):
    """Brain + Gemini fallback both raise -> deterministic _plain_text_fallback returned."""
    from core.morning_briefing import _compose_briefing
    monkeypatch.setenv("SMART_AGENT_FALLBACK_BACKEND", "gemini")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_API_KEY", "test-fallback-key")
    data = {
        "weather": None, "calendar": [], "email": [],
        "garmin": {"state": 2},
        "tasks": {"staleness_warning": None, "overdue": [], "today": [], "due_today": []},
    }
    with patch("core.llm_client.LLMClient", side_effect=Exception("all LLMs down")), \
         patch("pathlib.Path.read_text", return_value="System prompt for {today_date}"):
        result = _compose_briefing(data, "2026-05-12")
    assert result.startswith("Morning.")
    assert "Today:" in result


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


def test_briefing_send_uses_briefing_message_class(bot):
    """WR-02 / D-07 regression: the briefing cron threads message_class=
    "briefing" into send_and_inject so the push TTL class system is actually
    exercised by cron callers (was dead config — every cron sent 'default')."""
    with patch("core.morning_briefing._get_state", return_value={}), \
         patch("core.morning_briefing._set_state"), \
         patch("core.morning_briefing._gather_data", return_value={}), \
         patch("core.morning_briefing._compose_briefing", return_value="Good morning, sir."), \
         patch("core.scheduled_message.send_and_inject", new_callable=AsyncMock) as mock_send:
        from core.morning_briefing import run_morning_briefing
        asyncio.run(run_morning_briefing(bot, "2026-05-12", dedup=False))
    assert mock_send.call_args.kwargs.get("message_class") == "briefing"


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


# ---------------------------------------------------------------------------
# Phase 19 — nutrition recap + Postgres biometrics writeback
# (NUTR-05 + GARMIN-05; Pitfall 4 silent-omit; best-effort writeback)
# ---------------------------------------------------------------------------

class TestPhase19MorningBriefing:
    """_gather_data extensions: yesterday's meals + biometrics writeback."""

    def _stub_other_sources(self):
        """Patch context for the non-Phase-19 sources so a single test can focus
        on either the nutrition aggregation OR the Postgres writeback."""
        return [
            patch("mcp_tools.weather_tool.fetch_weather", return_value=None),
            patch("core.tools._get_calendar_tool"),
            patch("core.tools._get_gmail_tool"),
            patch("memory.firestore_db.TaskStore", **{"return_value.get_today_and_overdue.return_value": {"overdue": [], "today": []}}),
        ]

    def test_aggregates_yesterday_meals(self, monkeypatch):
        """Non-empty MealStore.get_day_aggregate → data['nutrition'] set."""
        import core.morning_briefing as mb
        fake_agg = {
            "meal_count": 3,
            "totals": {"calories": 2000, "protein_g": 120, "carbs_g": 200, "fat_g": 70},
            "by_type": {1: 1, 2: 1, 3: 1},
            "biggest_gap_minutes": 240.0,
            "meals": [],
        }
        stubs = self._stub_other_sources()
        for s in stubs:
            s.start()
        try:
            with patch("memory.firestore_db.MealStore") as MS, \
                 patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=None):
                MS.return_value.get_day_aggregate.return_value = fake_agg
                data = mb._gather_data("2026-05-26")
        finally:
            for s in stubs:
                s.stop()
        assert data.get("nutrition") == fake_agg

    def test_no_nutrition_key_when_empty(self, monkeypatch):
        """Empty aggregate ({}) → 'nutrition' key NOT in data (silent omit / Pitfall 4)."""
        import core.morning_briefing as mb
        stubs = self._stub_other_sources()
        for s in stubs:
            s.start()
        try:
            with patch("memory.firestore_db.MealStore") as MS, \
                 patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=None):
                MS.return_value.get_day_aggregate.return_value = {}  # empty
                data = mb._gather_data("2026-05-26")
        finally:
            for s in stubs:
                s.stop()
        assert "nutrition" not in data  # NUTR-07: silent omit precondition

    def test_meal_aggregate_failure_does_not_block_briefing(self, monkeypatch):
        """MealStore raises → briefing still completes, nutrition key absent."""
        import core.morning_briefing as mb
        stubs = self._stub_other_sources()
        for s in stubs:
            s.start()
        try:
            with patch("memory.firestore_db.MealStore", side_effect=RuntimeError("firestore down")), \
                 patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=None):
                # MUST NOT RAISE
                data = mb._gather_data("2026-05-26")
        finally:
            for s in stubs:
                s.stop()
        assert "nutrition" not in data
        assert isinstance(data, dict)

    def test_writes_biometrics_to_postgres(self, monkeypatch):
        """Garmin fetch returns today's data → write_today_biometrics called once."""
        import core.morning_briefing as mb
        fake_garmin = {"date": "2026-05-26", "resting_hr": 50, "hrv_overnight": 60, "sleep_score": 80}
        write_mock = MagicMock()
        stubs = self._stub_other_sources()
        for s in stubs:
            s.start()
        try:
            with patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=fake_garmin), \
                 patch("mcp_tools.garmin_tool.write_today_biometrics_to_postgres", write_mock), \
                 patch("memory.firestore_db.MealStore") as MS:
                MS.return_value.get_day_aggregate.return_value = {}
                mb._gather_data("2026-05-26")
        finally:
            for s in stubs:
                s.stop()
        # garmin.state == 1 (date matches) → writeback fires
        assert write_mock.called

    def test_postgres_outage_does_not_block_briefing(self, monkeypatch):
        """write_today_biometrics raises → briefing data still complete."""
        import core.morning_briefing as mb
        stubs = self._stub_other_sources()
        for s in stubs:
            s.start()
        try:
            with patch("mcp_tools.garmin_tool.fetch_garmin_today",
                       return_value={"date": "2026-05-26", "resting_hr": 50}), \
                 patch("mcp_tools.garmin_tool.write_today_biometrics_to_postgres",
                       side_effect=RuntimeError("DB down")), \
                 patch("memory.firestore_db.MealStore") as MS:
                MS.return_value.get_day_aggregate.return_value = {}
                # MUST NOT RAISE
                data = mb._gather_data("2026-05-26")
        finally:
            for s in stubs:
                s.stop()
        assert isinstance(data, dict)

    def test_writeback_skipped_when_garmin_state_2(self, monkeypatch):
        """Garmin returns None (no data → state=2) → writeback NOT called."""
        import core.morning_briefing as mb
        write_mock = MagicMock()
        stubs = self._stub_other_sources()
        for s in stubs:
            s.start()
        try:
            with patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=None), \
                 patch("mcp_tools.garmin_tool.write_today_biometrics_to_postgres", write_mock), \
                 patch("memory.firestore_db.MealStore") as MS:
                MS.return_value.get_day_aggregate.return_value = {}
                mb._gather_data("2026-05-26")
        finally:
            for s in stubs:
                s.stop()
        # state=2 (no data) → writeback should be skipped
        assert not write_mock.called


# ---------------------------------------------------------------------------
# TestPhase19MealAuditWiringMorningBriefing — NUTR-08 (Plan 19-05 Task 5)
# ---------------------------------------------------------------------------


class TestPhase19MealAuditWiringMorningBriefing:
    def test_morning_briefing_source_references_meal_audit(self):
        """NUTR-08 wiring: core/morning_briefing.py must reference prompts/meal_audit.md."""
        src = open("core/morning_briefing.py", encoding="utf-8").read()
        assert "meal_audit.md" in src, (
            "core/morning_briefing.py is missing prompts/meal_audit.md load — "
            "NUTR-08 wiring broken"
        )

    def test_morning_briefing_loads_meal_audit_nonempty(self):
        """NUTR-08: the meal_audit content must load and be non-empty (file-existence path)."""
        from pathlib import Path
        ma = Path("prompts/meal_audit.md")
        assert ma.exists()
        body = ma.read_text(encoding="utf-8")
        assert body.strip(), "prompts/meal_audit.md is empty"


# ====================================================================== #
# Phase 23 Plan 04 — block state in the morning briefing (BLOCK-01/D-04)  #
# ====================================================================== #

from contextlib import contextmanager


def _block_doc(label="Aerobic Base", end_date="2026-07-18",
               start_date="2026-06-21", benchmark_due=False,
               doc_id="2026-06-21_aerobic_base"):
    return {
        "doc_id": doc_id,
        "block_id": doc_id,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "focus_facets": ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"],
        "status": "active",
        "benchmark_due": benchmark_due,
    }


@contextmanager
def _quiet_gather(block_store):
    """Neutralize every heavy _gather_data collaborator so the block gather is the
    only meaningful work — keeps these tests fast and deterministic."""
    with patch("memory.firestore_db.BlockStore", block_store), \
         patch("memory.firestore_db.MealStore") as ms, \
         patch("core.tools._get_calendar_tool", side_effect=Exception("no cal")), \
         patch("core.tools._get_gmail_tool", side_effect=Exception("no mail")), \
         patch("mcp_tools.weather_tool.fetch_weather", side_effect=Exception("no wx")), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=None), \
         patch("memory.firestore_db.TaskStore", **{"return_value.get_today_and_overdue.return_value": {"overdue": [], "today": []}}):
        ms.return_value.get_day_aggregate.return_value = None
        yield


def test_gather_data_includes_block_state():
    """BLOCK-01: an active block surfaces data['block'] with derived week_num."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = _block_doc()
    with _quiet_gather(bs):
        data = _gather_data("2026-06-28")
    assert "block" in data
    assert data["block"]["week_num"] == 2  # (28-21)//7 + 1
    assert data["block"]["label"] == "Aerobic Base"
    assert data["block"]["end_date"] == "2026-07-18"
    assert "pre_cycle_countdown" not in data


def test_gather_data_precycle_countdown():
    """D-04: before the anchor with no active block, surface a pre-cycle countdown."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    with _quiet_gather(bs):
        data = _gather_data("2026-06-12")
    assert data.get("pre_cycle_countdown") == 9  # 21 - 12
    assert "block" not in data


def test_gather_data_block_failure_silent():
    """Pitfall 4: a BlockStore failure sets neither key and never raises."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.side_effect = RuntimeError("firestore down")
    with _quiet_gather(bs):
        data = _gather_data("2026-06-28")
    assert "block" not in data
    assert "pre_cycle_countdown" not in data


def test_gather_data_postcycle_no_active_silent():
    """Post-cycle with no active block: neither key (silent omit)."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    with _quiet_gather(bs):
        data = _gather_data("2026-11-01")
    assert "block" not in data
    assert "pre_cycle_countdown" not in data


# ====================================================================== #
# Phase 24 Plan 05 — coaching topic dedup + prior-day recap (COACH-05)   #
# ====================================================================== #


@contextmanager
def _quiet_gather_with_topics(block_store, coaching_topic_store):
    """Neutralize all heavy collaborators, leaving only block + coaching topic gather."""
    with patch("memory.firestore_db.BlockStore", block_store), \
         patch("memory.firestore_db.CoachingTopicStore", coaching_topic_store), \
         patch("memory.firestore_db.MealStore") as ms, \
         patch("core.tools._get_calendar_tool", side_effect=Exception("no cal")), \
         patch("core.tools._get_gmail_tool", side_effect=Exception("no mail")), \
         patch("mcp_tools.weather_tool.fetch_weather", side_effect=Exception("no wx")), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=None), \
         patch("memory.firestore_db.TaskStore", **{"return_value.get_today_and_overdue.return_value": {"overdue": [], "today": []}}):
        ms.return_value.get_day_aggregate.return_value = None
        yield


def test_gather_data_includes_coaching_topics_today_and_yesterday():
    """COACH-05 / D-08: _gather_data sets coaching_topics_today and coaching_topics_yesterday."""
    from core.morning_briefing import _gather_data

    bs = MagicMock()
    bs.return_value.get_current.return_value = None

    cts = MagicMock()
    # topics_today called twice: once for today, once for yesterday
    cts.return_value.topics_today.side_effect = [
        ["protein-miss"],   # today
        ["skipped-session:threshold-run"],  # yesterday
    ]

    with _quiet_gather_with_topics(bs, cts):
        data = _gather_data("2026-06-28")

    assert "coaching_topics_today" in data
    assert "coaching_topics_yesterday" in data
    assert data["coaching_topics_today"] == ["protein-miss"]
    assert data["coaching_topics_yesterday"] == ["skipped-session:threshold-run"]
    # COACH-05 conservative-writer producer: yesterday's unresolved misses are the
    # topics the briefing recaps and records into today's doc post-send.
    assert data["coaching_topics_included"] == ["skipped-session:threshold-run"]


def test_gather_data_coaching_topics_fail_open():
    """COACH-05: CoachingTopicStore failure → both keys set to [] (fail-open, never raises)."""
    from core.morning_briefing import _gather_data

    bs = MagicMock()
    bs.return_value.get_current.return_value = None

    cts = MagicMock()
    cts.side_effect = RuntimeError("firestore down")

    with _quiet_gather_with_topics(bs, cts):
        data = _gather_data("2026-06-28")

    assert data.get("coaching_topics_today") == []
    assert data.get("coaching_topics_yesterday") == []
    assert data.get("coaching_topics_included") == []


def test_gather_data_coaching_topics_today_empty_when_no_topics():
    """When CoachingTopicStore has no topics for today or yesterday, both keys are []."""
    from core.morning_briefing import _gather_data

    bs = MagicMock()
    bs.return_value.get_current.return_value = None

    cts = MagicMock()
    cts.return_value.topics_today.return_value = []

    with _quiet_gather_with_topics(bs, cts):
        data = _gather_data("2026-06-28")

    assert data["coaching_topics_today"] == []
    assert data["coaching_topics_yesterday"] == []
    # No prior-day misses → nothing to recap/record.
    assert data["coaching_topics_included"] == []


def test_run_morning_briefing_writes_topics_after_send(bot):
    """T-24-17: add_topic is called only AFTER successful send_and_inject (write-after-send discipline)."""
    add_topic_calls = []

    def fake_add_topic(date_str, topic):
        add_topic_calls.append((date_str, topic))

    mock_cts_instance = MagicMock()
    mock_cts_instance.add_topic.side_effect = fake_add_topic

    mock_cts_class = MagicMock(return_value=mock_cts_instance)

    today_data_with_topics = {
        "coaching_topics_today": [],
        "coaching_topics_yesterday": [],
        "coaching_topics_included": ["protein-miss", "skipped-session:threshold-run"],
    }

    with patch("core.morning_briefing._get_state", return_value={}), \
         patch("core.morning_briefing._set_state"), \
         patch("core.morning_briefing._gather_data", return_value=today_data_with_topics), \
         patch("core.morning_briefing._compose_briefing", return_value="Briefing text"), \
         patch("core.scheduled_message.send_and_inject", new_callable=AsyncMock) as mock_send, \
         patch("memory.firestore_db.CoachingTopicStore", mock_cts_class):
        from core.morning_briefing import run_morning_briefing
        import asyncio
        asyncio.run(run_morning_briefing(bot, "2026-06-28", dedup=False))

    # send was called
    mock_send.assert_called_once()
    # add_topic was called for each included topic
    assert len(add_topic_calls) == 2
    assert ("2026-06-28", "protein-miss") in add_topic_calls
    assert ("2026-06-28", "skipped-session:threshold-run") in add_topic_calls


def test_run_morning_briefing_no_topic_write_when_send_fails(bot):
    """T-24-17: add_topic must NOT be called if send_and_inject raises (write-after-send)."""
    add_topic_calls = []

    mock_cts_instance = MagicMock()
    mock_cts_instance.add_topic.side_effect = lambda d, t: add_topic_calls.append((d, t))
    mock_cts_class = MagicMock(return_value=mock_cts_instance)

    today_data_with_topics = {
        "coaching_topics_included": ["protein-miss"],
    }

    with patch("core.morning_briefing._get_state", return_value={}), \
         patch("core.morning_briefing._set_state"), \
         patch("core.morning_briefing._gather_data", return_value=today_data_with_topics), \
         patch("core.morning_briefing._compose_briefing", return_value="Briefing"), \
         patch("core.scheduled_message.send_and_inject",
               new_callable=AsyncMock, side_effect=RuntimeError("telegram down")), \
         patch("memory.firestore_db.CoachingTopicStore", mock_cts_class):
        from core.morning_briefing import run_morning_briefing
        import asyncio
        try:
            asyncio.run(run_morning_briefing(bot, "2026-06-28", dedup=False))
        except RuntimeError:
            pass  # send failure propagates — that's fine

    # No topic writes should have happened
    assert add_topic_calls == []


def test_morning_briefing_prompt_integrated_block_instruction():
    """D-18: the morning briefing prompt must instruct an integrated session+recovery+fueling block."""
    content = open("prompts/morning_briefing.md", encoding="utf-8").read()
    lower = content.lower()
    # Check for integrated block instruction keywords
    assert any(kw in lower for kw in ["integrated", "one block", "single block", "weave"]), (
        "prompts/morning_briefing.md missing D-18 integrated block instruction"
    )


def test_morning_briefing_prompt_prior_day_recap_instruction():
    """D-08: the morning briefing prompt must instruct prior-day unresolved-miss recap."""
    content = open("prompts/morning_briefing.md", encoding="utf-8").read()
    lower = content.lower()
    assert any(kw in lower for kw in ["prior", "yesterday", "prior-day"]), (
        "prompts/morning_briefing.md missing D-08 prior-day recap instruction"
    )


def test_morning_briefing_prompt_dedup_instruction():
    """D-02: the morning briefing prompt must instruct dedup (don't repeat today's topics)."""
    content = open("prompts/morning_briefing.md", encoding="utf-8").read()
    lower = content.lower()
    assert any(kw in lower for kw in ["coaching_topics_today", "dedup", "already raised", "do not repeat"]), (
        "prompts/morning_briefing.md missing D-02 dedup instruction"
    )


# ---------------------------------------------------------------------------
# Bodyweight single-source-of-truth: _sync_bodyweight_from_garmin
# ---------------------------------------------------------------------------


class TestBodyweightGarminSync:
    def test_skips_garmin_when_already_synced_today(self):
        """Once-daily guard: if bodyweight_synced_on == today, do NOT hit Garmin."""
        import core.morning_briefing as mb
        store = MagicMock()
        store.load.return_value = {"bodyweight_kg": 73.0, "bodyweight_synced_on": "2026-06-09"}
        with patch("mcp_tools.garmin_tool.fetch_garmin_weight") as fetch:
            result = mb._sync_bodyweight_from_garmin(store, "2026-06-09")
        fetch.assert_not_called()
        store.update.assert_not_called()
        assert result == 73.0

    def test_updates_profile_with_new_garmin_weight(self):
        """A fresh Garmin weight is written to bodyweight_kg + stamps synced_on."""
        import core.morning_briefing as mb
        store = MagicMock()
        store.load.return_value = {"bodyweight_kg": 73.0, "bodyweight_synced_on": "2026-06-01"}
        with patch("mcp_tools.garmin_tool.fetch_garmin_weight", return_value=74.0):
            result = mb._sync_bodyweight_from_garmin(store, "2026-06-09")
        assert result == 74.0
        patch_arg = store.update.call_args.args[0]
        assert patch_arg["bodyweight_kg"] == 74.0
        assert patch_arg["bodyweight_synced_on"] == "2026-06-09"

    def test_keeps_last_known_when_garmin_has_no_weight(self):
        """No Garmin value → keep stored weight, do NOT overwrite bodyweight_kg."""
        import core.morning_briefing as mb
        store = MagicMock()
        store.load.return_value = {"bodyweight_kg": 73.0, "bodyweight_synced_on": "2026-06-01"}
        with patch("mcp_tools.garmin_tool.fetch_garmin_weight", return_value=None):
            result = mb._sync_bodyweight_from_garmin(store, "2026-06-09")
        assert result == 73.0
        patch_arg = store.update.call_args.args[0]
        assert "bodyweight_kg" not in patch_arg          # not overwritten
        assert patch_arg["bodyweight_synced_on"] == "2026-06-09"  # attempt stamped


def test_gather_data_includes_recovery_deviation_when_flagged():
    """recovery_deviation surfaces in the gather only when the baseline math flags."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    rd = {"flags": ["hrv_low"], "hrv_overnight": 52.0, "hrv_baseline_7d": 61.0,
          "hrv_deviation_pct": -14.8, "days_of_data": 7}
    with _quiet_gather(bs), \
         patch("core.recovery_metrics.get_recovery_deviation", return_value=rd):
        data = _gather_data("2026-06-28")
    assert data["recovery_deviation"] == rd


def test_gather_data_omits_recovery_deviation_when_none():
    """Silent-omit: no deviation → no key (never an 'all clear' placeholder)."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    with _quiet_gather(bs), \
         patch("core.recovery_metrics.get_recovery_deviation", return_value=None):
        data = _gather_data("2026-06-28")
    assert "recovery_deviation" not in data


def test_gather_data_recovery_deviation_failure_is_isolated():
    """A recovery_metrics blow-up must never break the briefing gather."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    with _quiet_gather(bs), \
         patch("core.recovery_metrics.get_recovery_deviation",
               side_effect=RuntimeError("pg down")):
        data = _gather_data("2026-06-28")
    assert "recovery_deviation" not in data


# ====================================================================== #
# Phase 31 Plan 05 — standing directive veto (DIR-03 / D-21 / D-22)      #
# ====================================================================== #


def test_gather_data_reads_standing_directives():
    """DIR-03: _gather_data best-effort reads StandingDirectiveStore.list_active()."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    fake_directives = [{"id": "abc", "text": "Skip morning briefings while I'm away"}]
    sds = MagicMock()
    sds.return_value.list_active.return_value = fake_directives
    with _quiet_gather(bs), \
         patch("memory.firestore_db.StandingDirectiveStore", sds):
        data = _gather_data("2026-06-28")
    assert data["standing_directives"] == fake_directives


def test_gather_data_standing_directives_fail_open():
    """A StandingDirectiveStore failure must never block the briefing gather."""
    from core.morning_briefing import _gather_data
    bs = MagicMock()
    bs.return_value.get_current.return_value = None
    sds = MagicMock(side_effect=RuntimeError("firestore down"))
    with _quiet_gather(bs), \
         patch("memory.firestore_db.StandingDirectiveStore", sds):
        data = _gather_data("2026-06-28")
    assert data["standing_directives"] == []


class TestParseBriefingSkip:
    """_parse_briefing_skip mirrors core.autonomous._parse_followup_action exactly."""

    def test_parses_skip_true_with_reason(self):
        from core.morning_briefing import _parse_briefing_skip
        text = (
            'Not writing a briefing this morning.\n'
            '```json\n{"skip": true, "reason": "Amit asked for no morning notes this week"}\n```'
        )
        skip, reason, polished = _parse_briefing_skip(text)
        assert skip is True
        assert reason == "Amit asked for no morning notes this week"
        assert polished == "Not writing a briefing this morning."

    def test_no_json_block_defaults_to_no_skip(self):
        from core.morning_briefing import _parse_briefing_skip
        text = "Morning. Quiet one today."
        skip, reason, polished = _parse_briefing_skip(text)
        assert skip is False
        assert reason == ""
        assert polished == text

    def test_malformed_json_defaults_to_no_skip_and_strips_block(self):
        from core.morning_briefing import _parse_briefing_skip
        text = 'Morning note here.\n```json\n{not valid json}\n```'
        skip, reason, polished = _parse_briefing_skip(text)
        assert skip is False
        assert reason == ""
        assert polished == "Morning note here."

    def test_empty_text(self):
        from core.morning_briefing import _parse_briefing_skip
        assert _parse_briefing_skip("") == (False, "", "")

    def test_skip_false_explicit(self):
        from core.morning_briefing import _parse_briefing_skip
        text = 'Morning note.\n```json\n{"skip": false}\n```'
        skip, reason, polished = _parse_briefing_skip(text)
        assert skip is False
        assert reason == ""
        assert polished == "Morning note."


def test_run_morning_briefing_directive_skip_no_send_no_writes(bot):
    """DIR-03 / D-21 / D-22: a covering directive skip must NOT call send_and_inject
    and must NOT write structured/daily_note data (hub /api/today contract, T-31-09)."""
    skip_text = (
        'Skipping this morning.\n'
        '```json\n{"skip": true, "reason": "Standing directive: no morning briefings this week"}\n```'
    )
    with patch("core.morning_briefing._get_state", return_value={}), \
         patch("core.morning_briefing._set_state") as mock_set, \
         patch("core.morning_briefing._gather_data", return_value={}), \
         patch("core.morning_briefing._compose_briefing", return_value=skip_text), \
         patch("core.scheduled_message.send_and_inject", new_callable=AsyncMock) as mock_send, \
         patch("memory.firestore_db.SelfStateStore") as sss_cls:
        from core.morning_briefing import run_morning_briefing
        result = asyncio.run(run_morning_briefing(bot, "2026-07-20", dedup=False))

    assert result is True
    mock_send.assert_not_called()
    sss_cls.return_value.set.assert_not_called()

    # status set distinctly — T-31-08: never conflated with "sent"/"failed"
    status_calls = [c for c in mock_set.call_args_list if c.args and c.args[1].get("status")]
    assert any(c.args[1]["status"] == "skipped_by_directive" for c in status_calls)

    # No structured / daily_note write on a directive skip (T-31-09)
    for c in mock_set.call_args_list:
        fields = c.args[1]
        assert "structured" not in fields
        assert "daily_note" not in fields
        assert "daily_note_date" not in fields


def test_run_morning_briefing_non_skip_sends_and_writes_structured(bot):
    """No covering directive → normal send + normal structured/daily_note write."""
    today_data = {"calendar": [{"summary": "Standup"}], "tasks": {"today": [], "overdue": []}}
    with patch("core.morning_briefing._get_state", return_value={}), \
         patch("core.morning_briefing._set_state") as mock_set, \
         patch("core.morning_briefing._gather_data", return_value=today_data), \
         patch("core.morning_briefing._compose_briefing", return_value="Good morning."), \
         patch("core.scheduled_message.send_and_inject", new_callable=AsyncMock) as mock_send, \
         patch("memory.firestore_db.SelfStateStore") as sss_cls:
        from core.morning_briefing import run_morning_briefing
        result = asyncio.run(run_morning_briefing(bot, "2026-07-20", dedup=False))

    assert result is False
    mock_send.assert_called_once()
    structured_calls = [c for c in mock_set.call_args_list if "structured" in c.args[1]]
    assert structured_calls
    sss_cls.return_value.set.assert_called_once()
    daily_note_fields = sss_cls.return_value.set.call_args.args[0]
    assert daily_note_fields["daily_note"] == "Good morning."
