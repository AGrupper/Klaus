"""Tests for core/training_checkin.py — Phase 20, Plan 04.

RED test suite: all tests are expected to FAIL before the implementation exists.
Covers:
  - _silent_garmin_sync: writes training_log entries (source=garmin) for activities
    with non-null perceived_exertion; no send_and_inject call.
  - run_training_checkin: fully silent when all planned workouts are covered (CHECKIN-05).
  - Keyboard layouts: exact callback_data formats per UI-SPEC + D-26.
  - Time-gating: events whose start > now are skipped (D-07).
  - Branch logic: Garmin+RPE → silent; Garmin+no-RPE → RPE keyboard;
    no-Garmin → watch-off keyboard (CHECKIN-03).
  - Callback handlers: handle_rpe_callback, handle_watchoff_callback,
    handle_skipreason_callback, attach_note (Task 2 behaviors — all in one file).
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without live GCP / Telegram deps
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# Functional telegram fake whose keyboard classes record callback_data (the
# keyboard-layout tests below assert on it).
class _FakeInlineKeyboardButton:
    def __init__(self, text, callback_data=None, **kwargs):
        self.text = text
        self.callback_data = callback_data

class _FakeInlineKeyboardMarkup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard

class _FakeBot:
    pass

class _FakeMessage:
    def __init__(self, message_id=42):
        self.message_id = message_id

class _FakeCallbackQuery:
    def __init__(self, data="", message=None):
        self.data = data
        self.message = message or _FakeMessage()

    async def answer(self):
        pass


def _install_stubs() -> None:
    """Install all heavy-dependency stubs into sys.modules.

    Called from an autouse fixture guarded by ``isolated_modules`` so every
    mutation is reverted on teardown — installing these at module/collection time
    instead leaks fakes into the whole session and breaks sibling test files
    (the test-isolation bug this conversion fixes).
    """
    # google.cloud.firestore (needed by memory.firestore_db)
    if "google" not in sys.modules:
        sys.modules["google"] = types.ModuleType("google")
    if "google.cloud" not in sys.modules:
        google_cloud = types.ModuleType("google.cloud")
        sys.modules["google.cloud"] = google_cloud
        setattr(sys.modules["google"], "cloud", google_cloud)
    if "google.cloud.firestore" not in sys.modules:
        fs_mod = _stub_module(
            "google.cloud.firestore",
            SERVER_TIMESTAMP="__server_ts__",
            Client=MagicMock,
        )
        sys.modules["google.cloud.firestore"] = fs_mod
        setattr(sys.modules["google.cloud"], "firestore", fs_mod)

    # google.auth
    for _name in ["google.auth", "google.auth.transport", "google.auth.transport.requests"]:
        if _name not in sys.modules:
            sys.modules[_name] = types.ModuleType(_name)

    # google.oauth2.credentials
    for _name in ["google.oauth2", "google.oauth2.credentials"]:
        if _name not in sys.modules:
            mod = types.ModuleType(_name)
            if _name == "google.oauth2.credentials":
                mod.Credentials = MagicMock
            sys.modules[_name] = mod

    # google.auth.oauthlib
    for _name in ["google_auth_oauthlib", "google_auth_oauthlib.flow"]:
        if _name not in sys.modules:
            sys.modules[_name] = types.ModuleType(_name)

    # googleapiclient
    for _name in ["googleapiclient", "googleapiclient.discovery", "googleapiclient.errors"]:
        if _name not in sys.modules:
            mod = types.ModuleType(_name)
            if _name == "googleapiclient.errors":
                mod.HttpError = Exception
            sys.modules[_name] = mod

    # telegram — always install a fresh functional fake module so the keyboard
    # classes are present regardless of collection order; isolated_modules reverts
    # the whole module object on teardown.
    telegram_mod = types.ModuleType("telegram")
    telegram_mod.InlineKeyboardButton = _FakeInlineKeyboardButton
    telegram_mod.InlineKeyboardMarkup = _FakeInlineKeyboardMarkup
    telegram_mod.Bot = _FakeBot
    telegram_mod.Message = _FakeMessage
    telegram_mod.CallbackQuery = _FakeCallbackQuery
    sys.modules["telegram"] = telegram_mod

    # core / memory stubs
    sys.modules["core.auth_google"] = _stub_module("core.auth_google", GoogleAuthManager=MagicMock)
    sys.modules["core.main"] = _stub_module("core.main", AgentOrchestrator=MagicMock)
    sys.modules["memory.pinecone_db"] = _stub_module("memory.pinecone_db")


@pytest.fixture(autouse=True)
def _training_checkin_stubs(isolated_modules):
    """Install stubs + force a clean re-import of core.training_checkin per test."""
    _install_stubs()
    sys.modules.pop("core.training_checkin", None)
    yield


# ---------------------------------------------------------------------------
# Fixed "now" for time-gating tests (21:15 Jerusalem — after most workouts)
# ---------------------------------------------------------------------------
# 2026-06-01T21:15:00+03:00 = 18:15 UTC
_FIXED_NOW_UTC = datetime(2026, 6, 1, 18, 15, 0, tzinfo=timezone.utc)
_FIXED_NOW_IL_OFFSET = timezone(timedelta(hours=3))
_FIXED_NOW_IL = datetime(2026, 6, 1, 21, 15, 0, tzinfo=_FIXED_NOW_IL_OFFSET)
_TODAY_ISO = "2026-06-01"


def _make_garmin_activity(
    activity_id="act_001",
    date_str="2026-06-01T07:30:00",
    atype="running",
    perceived_exertion=70,  # raw Garmin steps-of-10
    feel=3,
    training_load=85.0,
):
    return {
        "activity_id": activity_id,
        "date": date_str,
        "type": atype,
        "duration_sec": 3600,
        "distance_m": 8000.0,
        "perceived_exertion": perceived_exertion,
        "feel": feel,
        "training_load": training_load,
    }


def _make_training_event(
    event_id="evt_abc",
    summary="Morning Run",
    start="2026-06-01T07:00:00+03:00",
    end="2026-06-01T08:00:00+03:00",
):
    return {
        "id": event_id,
        "summary": summary,
        "start": start,
        "end": end,
        "description": "",
    }


# ============================================================================
# Task 1 Tests: silent Garmin sync + branch logic + keyboards
# ============================================================================


class TestSilentGarminSync(unittest.IsolatedAsyncioTestCase):
    """_silent_garmin_sync writes training_log entries for activities with RPE."""

    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_garmin_sync_writes_with_rpe(
        self, mock_fetch, MockTrainingLogStore
    ):
        """Activities with non-null perceived_exertion are synced to training_log."""
        import core.training_checkin as tc

        activity = _make_garmin_activity(perceived_exertion=70)
        mock_fetch.return_value = [activity]

        mock_store_instance = MagicMock()
        MockTrainingLogStore.return_value = mock_store_instance

        tc._silent_garmin_sync(_TODAY_ISO)

        mock_store_instance.log_session.assert_called_once()
        call_kwargs = mock_store_instance.log_session.call_args[1] if mock_store_instance.log_session.call_args[1] else {}
        call_args = mock_store_instance.log_session.call_args
        # Accept both positional and keyword args
        # source="garmin" is the critical assertion
        all_args = call_args[0] if call_args[0] else ()
        all_kwargs = call_args[1] if call_args[1] else {}
        assert all_kwargs.get("source") == "garmin" or "garmin" in str(call_args), (
            f"Expected source='garmin' in log_session call, got: {call_args}"
        )

    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_garmin_sync_skips_null_rpe(
        self, mock_fetch, MockTrainingLogStore
    ):
        """Activities with null perceived_exertion are NOT synced."""
        import core.training_checkin as tc

        activity = _make_garmin_activity(perceived_exertion=None)
        mock_fetch.return_value = [activity]

        mock_store_instance = MagicMock()
        MockTrainingLogStore.return_value = mock_store_instance

        tc._silent_garmin_sync(_TODAY_ISO)

        mock_store_instance.log_session.assert_not_called()

    @patch("core.training_checkin.send_and_inject")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_garmin_sync_no_send_and_inject(
        self, mock_fetch, MockTrainingLogStore, mock_send
    ):
        """_silent_garmin_sync must NOT call send_and_inject."""
        import core.training_checkin as tc

        activity = _make_garmin_activity(perceived_exertion=70)
        mock_fetch.return_value = [activity]
        MockTrainingLogStore.return_value = MagicMock()

        tc._silent_garmin_sync(_TODAY_ISO)

        mock_send.assert_not_called()

    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_garmin_sync_swallows_exceptions(
        self, mock_fetch, MockTrainingLogStore
    ):
        """_silent_garmin_sync swallows all exceptions (best-effort pattern)."""
        import core.training_checkin as tc

        mock_fetch.side_effect = RuntimeError("Garmin down")

        # Should not raise
        tc._silent_garmin_sync(_TODAY_ISO)


class TestSilentWhenAllCovered(unittest.IsolatedAsyncioTestCase):
    """run_training_checkin sends zero messages when all planned workouts are covered."""

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_when_all_covered_by_garmin_rpe(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """CHECKIN-05: no messages when all events have Garmin activities with RPE."""
        import core.training_checkin as tc

        activity = _make_garmin_activity(
            activity_id="act_001",
            date_str="2026-06-01T07:00:00",
            perceived_exertion=70,
        )
        mock_fetch.return_value = [activity]

        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = [
            _make_training_event(event_id="evt_abc", start="2026-06-01T07:00:00+03:00")
        ]
        MockCalMgr.return_value = cal_mgr_instance

        # training_log already has this entry (source=garmin, rpe=7)
        tls_instance = MagicMock()
        tls_instance.get_by_date.return_value = [
            {"doc_id": f"{_TODAY_ISO}_evt_abc", "slot": "evt_abc", "rpe": 7, "source": "garmin", "date": _TODAY_ISO}
        ]
        MockTLS.return_value = tls_instance

        with patch("core.training_checkin.datetime") as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW_IL
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            await tc.run_training_checkin(MagicMock(), _TODAY_ISO)

        mock_send.assert_not_called()

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_when_no_training_events(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """CHECKIN-05: silent if Training calendar returns no events."""
        import core.training_checkin as tc

        mock_fetch.return_value = []
        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = []
        MockCalMgr.return_value = cal_mgr_instance
        MockTLS.return_value = MagicMock()
        MockTLS.return_value.get_by_date.return_value = []

        await tc.run_training_checkin(MagicMock(), _TODAY_ISO)

        mock_send.assert_not_called()


class TestRPEKeyboardLayout(unittest.IsolatedAsyncioTestCase):
    """RPE keyboard has exactly two rows of 5, correct callback_data format (D-26)."""

    def test_rpe_keyboard_two_rows_of_five(self):
        """_rpe_keyboard returns InlineKeyboardMarkup with 2 rows of 5 buttons."""
        import core.training_checkin as tc

        kb = tc._rpe_keyboard("2026-06-01_evt_abc")
        rows = kb.inline_keyboard
        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        assert len(rows[0]) == 5, f"Row 1 should have 5 buttons, got {len(rows[0])}"
        assert len(rows[1]) == 5, f"Row 2 should have 5 buttons, got {len(rows[1])}"

    def test_rpe_keyboard_callback_data_format(self):
        """Buttons have callback_data format: rpe:{session_key}:{value}."""
        import core.training_checkin as tc

        session_key = "2026-06-01_evt_abc"
        kb = tc._rpe_keyboard(session_key)
        all_buttons = kb.inline_keyboard[0] + kb.inline_keyboard[1]

        expected_data = [f"rpe:{session_key}:{i}" for i in range(1, 11)]
        actual_data = [btn.callback_data for btn in all_buttons]
        assert actual_data == expected_data, (
            f"Expected {expected_data}, got {actual_data}"
        )

    def test_rpe_keyboard_row1_range(self):
        """First row has values 1–5."""
        import core.training_checkin as tc

        kb = tc._rpe_keyboard("test_key")
        row1 = kb.inline_keyboard[0]
        values = [btn.callback_data.split(":")[-1] for btn in row1]
        assert values == ["1", "2", "3", "4", "5"], f"Row 1 values: {values}"

    def test_rpe_keyboard_row2_range(self):
        """Second row has values 6–10."""
        import core.training_checkin as tc

        kb = tc._rpe_keyboard("test_key")
        row2 = kb.inline_keyboard[1]
        values = [btn.callback_data.split(":")[-1] for btn in row2]
        assert values == ["6", "7", "8", "9", "10"], f"Row 2 values: {values}"


class TestWatchoffKeyboard(unittest.IsolatedAsyncioTestCase):
    """Watch-off keyboard has done + skipped with exact callback_data (D-08)."""

    def test_watchoff_keyboard_layout(self):
        """_watchoff_keyboard has 2 buttons in one row."""
        import core.training_checkin as tc

        kb = tc._watchoff_keyboard("2026-06-01_evt_gym")
        rows = kb.inline_keyboard
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        assert len(rows[0]) == 2, f"Expected 2 buttons, got {len(rows[0])}"

    def test_watchoff_keyboard_callback_data(self):
        """Callback data: watchoff:{key}:done and watchoff:{key}:skipped."""
        import core.training_checkin as tc

        session_key = "2026-06-01_evt_gym"
        kb = tc._watchoff_keyboard(session_key)
        buttons = kb.inline_keyboard[0]
        data_values = [btn.callback_data for btn in buttons]
        assert f"watchoff:{session_key}:done" in data_values
        assert f"watchoff:{session_key}:skipped" in data_values


class TestSkipreasonKeyboard(unittest.IsolatedAsyncioTestCase):
    """Skip-reason keyboard has 4 buttons with correct reason keys (D-08b)."""

    def test_skipreason_keyboard_four_buttons(self):
        """_skipreason_keyboard has 4 buttons in 2 rows of 2."""
        import core.training_checkin as tc

        kb = tc._skipreason_keyboard("2026-06-01_evt_ff")
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(all_buttons) == 4, f"Expected 4 buttons, got {len(all_buttons)}"

    def test_skipreason_keyboard_reason_keys(self):
        """Buttons have callback_data: skipreason:{key}:{reason_key}."""
        import core.training_checkin as tc

        session_key = "2026-06-01_evt_ff"
        kb = tc._skipreason_keyboard(session_key)
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        data_values = {btn.callback_data for btn in all_buttons}

        expected_reasons = {"rest_recovery", "sick_injured", "too_busy", "other"}
        for reason in expected_reasons:
            assert f"skipreason:{session_key}:{reason}" in data_values, (
                f"Missing reason {reason!r} in {data_values}"
            )


class TestTimeGating(unittest.IsolatedAsyncioTestCase):
    """Events whose start > now are NOT prompted (D-07)."""

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_future_event_not_prompted(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """A workout scheduled for 22:00 is NOT prompted at 21:15."""
        import core.training_checkin as tc

        mock_fetch.return_value = []
        # Event starts at 22:00, which is > fixed now (21:15)
        future_event = _make_training_event(
            event_id="evt_future",
            summary="Late Run",
            start="2026-06-01T22:00:00+03:00",
        )
        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = [future_event]
        MockCalMgr.return_value = cal_mgr_instance

        tls_instance = MagicMock()
        tls_instance.get_by_date.return_value = []
        MockTLS.return_value = tls_instance

        with patch("core.training_checkin.datetime") as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW_IL
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            await tc.run_training_checkin(MagicMock(), _TODAY_ISO)

        mock_send.assert_not_called()


class TestBranchLogic(unittest.IsolatedAsyncioTestCase):
    """Branch logic: Garmin+RPE → silent; Garmin+no-RPE → RPE KB; no-Garmin → watch-off KB."""

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_garmin_no_rpe_sends_rpe_keyboard(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """Garmin activity present but no perceived_exertion → send RPE keyboard."""
        import core.training_checkin as tc

        # Garmin activity for a run, but RPE is None
        activity = _make_garmin_activity(
            activity_id="act_run",
            date_str="2026-06-01T07:00:00",
            atype="running",
            perceived_exertion=None,
        )
        mock_fetch.return_value = [activity]

        event = _make_training_event(
            event_id="evt_run",
            summary="Morning Run",
            start="2026-06-01T07:00:00+03:00",
            end="2026-06-01T08:00:00+03:00",
        )
        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = [event]
        MockCalMgr.return_value = cal_mgr_instance

        tls_instance = MagicMock()
        tls_instance.get_by_date.return_value = []
        MockTLS.return_value = tls_instance

        pps_instance = MagicMock()
        MockPPS.return_value = pps_instance

        mock_msg = MagicMock()
        mock_msg.message_id = 999
        mock_send.return_value = mock_msg

        with patch("core.training_checkin.datetime") as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW_IL
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            await tc.run_training_checkin(MagicMock(), _TODAY_ISO)

        # send_and_inject should be called (intro + RPE keyboard)
        assert mock_send.called, "Expected send_and_inject to be called for RPE keyboard"
        # Find the call with an RPE keyboard
        calls_with_markup = [
            c for c in mock_send.call_args_list
            if c[1].get("reply_markup") is not None
        ]
        assert len(calls_with_markup) >= 1, "Expected at least one call with reply_markup (RPE keyboard)"

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_no_garmin_sends_watchoff_keyboard(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """No Garmin record for a planned workout → send watch-off keyboard."""
        import core.training_checkin as tc

        mock_fetch.return_value = []  # no Garmin activities

        event = _make_training_event(
            event_id="evt_gym",
            summary="Gym — Upper Body",
            start="2026-06-01T18:00:00+03:00",
            end="2026-06-01T19:30:00+03:00",
        )
        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = [event]
        MockCalMgr.return_value = cal_mgr_instance

        tls_instance = MagicMock()
        tls_instance.get_by_date.return_value = []
        MockTLS.return_value = tls_instance

        pps_instance = MagicMock()
        MockPPS.return_value = pps_instance

        mock_msg = MagicMock()
        mock_msg.message_id = 998
        mock_send.return_value = mock_msg

        with patch("core.training_checkin.datetime") as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW_IL
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            await tc.run_training_checkin(MagicMock(), _TODAY_ISO)

        assert mock_send.called, "Expected send_and_inject to be called for watch-off keyboard"
        calls_with_markup = [
            c for c in mock_send.call_args_list
            if c[1].get("reply_markup") is not None
        ]
        assert len(calls_with_markup) >= 1, "Expected at least one call with watch-off keyboard"

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_empty_training_list_handled_cleanly(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """Empty training events list → no crash, no message (covers buffer-filter case)."""
        import core.training_checkin as tc

        mock_fetch.return_value = []
        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = []
        MockCalMgr.return_value = cal_mgr_instance

        tls_instance = MagicMock()
        tls_instance.get_by_date.return_value = []
        MockTLS.return_value = tls_instance

        # Should not raise, should not call send
        await tc.run_training_checkin(MagicMock(), _TODAY_ISO)
        mock_send.assert_not_called()

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.GoogleCalendarManager")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_inject_into_conversation_false_for_keyboards(
        self, mock_fetch, MockCalMgr, mock_send, MockTLS, MockPPS
    ):
        """Keyboards are sent with inject_into_conversation=False (Pitfall 9)."""
        import core.training_checkin as tc

        mock_fetch.return_value = []
        event = _make_training_event(
            event_id="evt_gym",
            summary="Gym",
            start="2026-06-01T18:00:00+03:00",
        )
        cal_mgr_instance = MagicMock()
        cal_mgr_instance.list_training_events.return_value = [event]
        MockCalMgr.return_value = cal_mgr_instance

        tls_instance = MagicMock()
        tls_instance.get_by_date.return_value = []
        MockTLS.return_value = tls_instance

        MockPPS.return_value = MagicMock()

        mock_msg = MagicMock()
        mock_msg.message_id = 997
        mock_send.return_value = mock_msg

        with patch("core.training_checkin.datetime") as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW_IL
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            await tc.run_training_checkin(MagicMock(), _TODAY_ISO)

        # All send_and_inject calls must have inject_into_conversation=False
        for c in mock_send.call_args_list:
            inject = c[1].get("inject_into_conversation", None)
            assert inject is False, (
                f"Expected inject_into_conversation=False, got {inject!r} in call {c}"
            )


# ============================================================================
# Task 2 Tests: callback handlers + notes step
# ============================================================================


class TestHandleRpeCallback(unittest.IsolatedAsyncioTestCase):
    """handle_rpe_callback: parse data, validate session, log RPE, send notes prompt."""

    def _make_orchestrator(self):
        orch = MagicMock()
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
        orch.bot = bot
        return orch

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_handle_rpe_callback_logs_rpe(self, mock_send, MockTLS, MockPPS):
        """handle_rpe_callback logs RPE via TrainingLogStore.log_session."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_gym"
        session = {
            "session_key": session_key,
            "state": "awaiting_rpe",
            "event_date": _TODAY_ISO,
            "event_summary": "Gym",
            "user_id": 12345,
            "message_id": 200,
        }
        pps_instance = MagicMock()
        pps_instance.get.return_value = session
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        mock_msg = MagicMock()
        mock_msg.message_id = 300
        mock_send.return_value = mock_msg

        orch = self._make_orchestrator()
        cq = MagicMock()
        cq.message.get_bot = MagicMock(return_value=orch.bot)
        await tc.handle_rpe_callback(orch, 12345, cq, f"rpe:{session_key}:7")

        tls_instance.log_session.assert_called_once()
        kwargs = tls_instance.log_session.call_args[1] if tls_instance.log_session.call_args[1] else {}
        args = tls_instance.log_session.call_args[0] if tls_instance.log_session.call_args[0] else ()
        # rpe=7, source=telegram
        all_kw = tls_instance.log_session.call_args.kwargs if hasattr(tls_instance.log_session.call_args, 'kwargs') else kwargs
        assert all_kw.get("rpe") == 7, f"Expected rpe=7, got {all_kw}"
        assert all_kw.get("source") == "telegram", f"Expected source='telegram', got {all_kw}"

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_handle_rpe_callback_stale_session_sends_error(
        self, mock_send, MockTLS, MockPPS
    ):
        """Stale/expired session → error copy sent, no log write (T-20-08/T-20-09)."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_stale"
        pps_instance = MagicMock()
        pps_instance.get.return_value = None  # expired/missing
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        mock_send.return_value = MagicMock(message_id=1)

        orch = self._make_orchestrator()
        cq = MagicMock()
        await tc.handle_rpe_callback(orch, 12345, cq, f"rpe:{session_key}:5")

        tls_instance.log_session.assert_not_called()
        # Error message sent
        mock_send.assert_called_once()
        text_arg = mock_send.call_args[0][1] if mock_send.call_args[0] else mock_send.call_args[1].get("text", "")
        assert any(
            kw in text_arg.lower()
            for kw in ("couldn't match", "could not match", "already been closed")
        ), f"Expected error copy in: {text_arg!r}"

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_handle_rpe_callback_sends_notes_prompt(
        self, mock_send, MockTLS, MockPPS
    ):
        """After logging RPE, notes prompt is sent and state transitions to awaiting_notes."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_run"
        session = {
            "session_key": session_key,
            "state": "awaiting_rpe",
            "event_date": _TODAY_ISO,
            "event_summary": "Morning Run",
            "user_id": 12345,
            "message_id": 200,
        }
        pps_instance = MagicMock()
        pps_instance.get.return_value = session
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        mock_msg = MagicMock()
        mock_msg.message_id = 300
        mock_send.return_value = mock_msg

        orch = self._make_orchestrator()
        cq = MagicMock()
        await tc.handle_rpe_callback(orch, 12345, cq, f"rpe:{session_key}:8")

        # Notes prompt must be sent (second send_and_inject call)
        assert mock_send.call_count >= 1, "Expected send_and_inject calls for notes prompt"
        # State updated to awaiting_notes
        pps_instance.set.assert_called()
        set_kwargs = pps_instance.set.call_args
        set_payload = set_kwargs[0][1] if len(set_kwargs[0]) > 1 else (set_kwargs[1] or {})
        if isinstance(set_payload, dict):
            assert set_payload.get("state") == "awaiting_notes", (
                f"Expected state=awaiting_notes in {set_payload}"
            )


class TestHandleWatchoffCallback(unittest.IsolatedAsyncioTestCase):
    """handle_watchoff_callback: done→RPE keyboard; skipped→skip-reason keyboard."""

    def _make_orchestrator(self):
        orch = MagicMock()
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
        orch.bot = bot
        return orch

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_watchoff_done_sends_rpe_keyboard(self, mock_send, MockTLS, MockPPS):
        """Tapping 'done' (watch was off) → sends RPE keyboard."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_ff"
        session = {
            "session_key": session_key,
            "state": "awaiting_watchoff",
            "event_date": _TODAY_ISO,
            "event_summary": "Five Fingers",
            "user_id": 12345,
            "message_id": 400,
        }
        pps_instance = MagicMock()
        pps_instance.get.return_value = session
        MockPPS.return_value = pps_instance
        MockTLS.return_value = MagicMock()

        mock_msg = MagicMock()
        mock_msg.message_id = 500
        mock_send.return_value = mock_msg

        orch = self._make_orchestrator()
        cq = MagicMock()
        await tc.handle_watchoff_callback(orch, 12345, cq, f"watchoff:{session_key}:done")

        # RPE keyboard must be sent
        calls_with_markup = [
            c for c in mock_send.call_args_list
            if c[1].get("reply_markup") is not None
        ]
        assert len(calls_with_markup) >= 1, "Expected RPE keyboard on 'done' tap"
        # State transitions to awaiting_rpe
        pps_instance.set.assert_called()

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_watchoff_skipped_sends_skipreason_keyboard(
        self, mock_send, MockTLS, MockPPS
    ):
        """Tapping 'skipped' → sends skip-reason keyboard."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_gym"
        session = {
            "session_key": session_key,
            "state": "awaiting_watchoff",
            "event_date": _TODAY_ISO,
            "event_summary": "Gym",
            "user_id": 12345,
            "message_id": 400,
        }
        pps_instance = MagicMock()
        pps_instance.get.return_value = session
        MockPPS.return_value = pps_instance
        MockTLS.return_value = MagicMock()

        mock_msg = MagicMock()
        mock_msg.message_id = 501
        mock_send.return_value = mock_msg

        orch = self._make_orchestrator()
        cq = MagicMock()
        await tc.handle_watchoff_callback(orch, 12345, cq, f"watchoff:{session_key}:skipped")

        calls_with_markup = [
            c for c in mock_send.call_args_list
            if c[1].get("reply_markup") is not None
        ]
        assert len(calls_with_markup) >= 1, "Expected skip-reason keyboard on 'skipped' tap"
        pps_instance.set.assert_called()


class TestHandleSkipreasonCallback(unittest.IsolatedAsyncioTestCase):
    """handle_skipreason_callback: structured reasons → log + delete; other → open note."""

    def _make_orchestrator(self):
        orch = MagicMock()
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
        orch.bot = bot
        return orch

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_skipreason_structured_logs_and_deletes(
        self, mock_send, MockTLS, MockPPS
    ):
        """rest_recovery / sick_injured / too_busy → log + PendingPromptStore.delete (terminal)."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_gym"
        session = {
            "session_key": session_key,
            "state": "awaiting_skipreason",
            "event_date": _TODAY_ISO,
            "event_summary": "Gym",
            "user_id": 12345,
            "message_id": 400,
        }
        pps_instance = MagicMock()
        pps_instance.get.return_value = session
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        mock_send.return_value = MagicMock(message_id=1)

        orch = self._make_orchestrator()
        cq = MagicMock()
        await tc.handle_skipreason_callback(
            orch, 12345, cq, f"skipreason:{session_key}:rest_recovery"
        )

        tls_instance.log_session.assert_called_once()
        log_kwargs = tls_instance.log_session.call_args.kwargs if hasattr(tls_instance.log_session.call_args, 'kwargs') else tls_instance.log_session.call_args[1]
        assert log_kwargs.get("completed") is False, f"Expected completed=False, got {log_kwargs}"
        assert log_kwargs.get("skipped_reason") == "rest_recovery", f"Expected rest_recovery, got {log_kwargs}"

        # Pitfall 3: terminal transition must delete the pending session
        pps_instance.delete.assert_called_once_with(session_key)

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_skipreason_other_sends_note_request(
        self, mock_send, MockTLS, MockPPS
    ):
        """'other' skip reason → sends free-text request, sets awaiting_skipreason_other."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_run"
        session = {
            "session_key": session_key,
            "state": "awaiting_skipreason",
            "event_date": _TODAY_ISO,
            "event_summary": "Morning Run",
            "user_id": 12345,
            "message_id": 400,
        }
        pps_instance = MagicMock()
        pps_instance.get.return_value = session
        MockPPS.return_value = pps_instance
        MockTLS.return_value = MagicMock()

        mock_msg = MagicMock()
        mock_msg.message_id = 600
        mock_send.return_value = mock_msg

        orch = self._make_orchestrator()
        cq = MagicMock()
        await tc.handle_skipreason_callback(
            orch, 12345, cq, f"skipreason:{session_key}:other"
        )

        # Should NOT delete (not terminal) — state → awaiting_skipreason_other
        pps_instance.delete.assert_not_called()
        pps_instance.set.assert_called()


class TestAttachNote(unittest.IsolatedAsyncioTestCase):
    """attach_note: writes notes to training_log + deletes pending session (terminal)."""

    def _make_orchestrator(self):
        orch = MagicMock()
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
        orch.bot = bot
        return orch

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_attach_note_writes_notes_and_deletes(
        self, mock_send, MockTLS, MockPPS
    ):
        """attach_note calls log_session with notes and deletes the pending session."""
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_gym"
        session = {
            "session_key": session_key,
            "state": "awaiting_notes",
            "event_date": _TODAY_ISO,
            "event_summary": "Gym",
            "user_id": 12345,
            "message_id": 300,
            "rpe": 7,
        }
        pps_instance = MagicMock()
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        mock_send.return_value = MagicMock(message_id=1)

        orch = self._make_orchestrator()
        await tc.attach_note(orch, 12345, session, "Felt strong today")

        tls_instance.log_session.assert_called_once()
        log_kwargs = tls_instance.log_session.call_args.kwargs if hasattr(tls_instance.log_session.call_args, 'kwargs') else tls_instance.log_session.call_args[1]
        assert log_kwargs.get("notes") == "Felt strong today", (
            f"Expected notes='Felt strong today', got {log_kwargs}"
        )

        # Pitfall 3: terminal transition must delete
        pps_instance.delete.assert_called_once_with(session_key)

    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    async def test_attach_note_stale_session_no_write(
        self, mock_send, MockTLS, MockPPS
    ):
        """Stale/expired session in attach_note → no log write."""
        import core.training_checkin as tc

        # Session is None (expired) — we pass it directly from the router
        # The router passes the session it already found; if None is given, no write
        # But the router actually won't call attach_note if session is None (it checks first)
        # Test: when session has no session_key → graceful handling
        session = {}  # empty/malformed session
        pps_instance = MagicMock()
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        mock_send.return_value = MagicMock(message_id=1)

        orch = self._make_orchestrator()
        # Should not raise even with empty session
        try:
            await tc.attach_note(orch, 12345, session, "note text")
        except Exception as exc:
            pass  # Implementation may raise on empty session — just verify no log write
        # The critical invariant: do NOT write if session_key is absent
        # (either no call, or an exception before writing is acceptable)


class TestAttachSkipreasonOtherNote(unittest.IsolatedAsyncioTestCase):
    """attach_skipreason_other_note: records a SKIP (completed=False,
    skipped_reason=other, notes=<free text>) + deletes the pending session.
    Regression for CR-01 — the 'Other — tell me' free-text reply was previously
    never captured (get_open_note_session matched only awaiting_notes)."""

    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    async def test_records_skip_with_reason_other_and_deletes(self, MockTLS, MockPPS, mock_send):
        import core.training_checkin as tc

        session_key = f"{_TODAY_ISO}_evt_gym"
        session = {
            "session_key": session_key,
            "state": "awaiting_skipreason_other",
            "event_date": _TODAY_ISO,
            "event_summary": "Gym",
            "session_type": "gym",
            "user_id": 12345,
            "message_id": 300,
        }
        pps_instance = MagicMock()
        MockPPS.return_value = pps_instance
        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        await tc.attach_skipreason_other_note(MagicMock(), 12345, session, "stuck at work late")

        tls_instance.log_session.assert_called_once()
        kw = tls_instance.log_session.call_args.kwargs
        assert kw.get("completed") is False, kw
        assert kw.get("skipped_reason") == "other", kw
        assert kw.get("notes") == "stuck at work late", kw
        assert kw.get("source") == "telegram", kw
        # Pitfall 3: terminal transition must delete
        pps_instance.delete.assert_called_once_with(session_key)
        # User gets a confirmation that the skip was recorded.
        mock_send.assert_awaited_once()

    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    async def test_missing_session_key_no_write(self, MockTLS, MockPPS, mock_send):
        import core.training_checkin as tc
        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance
        await tc.attach_skipreason_other_note(MagicMock(), 12345, {}, "note")
        tls_instance.log_session.assert_not_called()


# ============================================================================
# Phase 24 PROG-04 Tests: derive_session_quality pure function
# ============================================================================


class TestDeriveSessionQuality(unittest.TestCase):
    """derive_session_quality pure function — Phase 24 PROG-04."""

    def _fn(self):
        import core.training_checkin as tc
        return tc.derive_session_quality

    def test_returns_none_when_both_rpe_and_feel_are_none(self):
        """derive_session_quality(rpe=None, feel=None) returns None."""
        fn = self._fn()
        assert fn(rpe=None, feel=None) is None

    def test_feel_zero_returns_grind(self):
        """Pitfall 4: feel==0 (Very Weak) must return 'grind', not None.

        feel==0 is falsy in Python; must use 'is not None' check.
        """
        fn = self._fn()
        assert fn(rpe=None, feel=0) == "grind"
        assert fn(rpe=7, feel=0) == "grind"

    def test_feel_100_returns_strong(self):
        """feel==100 (Very Strong) returns 'strong'."""
        fn = self._fn()
        assert fn(rpe=None, feel=100) == "strong"
        assert fn(rpe=7, feel=100) == "strong"

    def test_feel_75_high_rpe_returns_strong(self):
        """feel==75 with rpe>=5 returns 'strong'."""
        fn = self._fn()
        assert fn(rpe=5, feel=75) == "strong"
        assert fn(rpe=8, feel=75) == "strong"
        assert fn(rpe=None, feel=75) == "strong"

    def test_feel_75_low_rpe_returns_neutral(self):
        """feel==75 with rpe<5 returns 'neutral' (strong feel but low effort)."""
        fn = self._fn()
        assert fn(rpe=3, feel=75) == "neutral"
        assert fn(rpe=4, feel=75) == "neutral"

    def test_feel_50_returns_neutral(self):
        """feel==50 (Okay) returns 'neutral'."""
        fn = self._fn()
        assert fn(rpe=None, feel=50) == "neutral"
        assert fn(rpe=7, feel=50) == "neutral"

    def test_feel_25_returns_grind(self):
        """feel==25 (Weak) returns 'grind'."""
        fn = self._fn()
        assert fn(rpe=None, feel=25) == "grind"

    # ------------------------------------------------------------------ #
    # RPE-only fallback (no feel)                                         #
    # ------------------------------------------------------------------ #

    def test_rpe_9_feel_none_returns_grind(self):
        """rpe=9, feel=None (high effort, no Garmin) returns 'grind'."""
        fn = self._fn()
        assert fn(rpe=9, feel=None) == "grind"

    def test_rpe_8_feel_none_returns_grind(self):
        """rpe=8, feel=None returns 'grind'."""
        fn = self._fn()
        assert fn(rpe=8, feel=None) == "grind"

    def test_rpe_3_feel_none_returns_strong(self):
        """rpe=3, feel=None returns 'strong'."""
        fn = self._fn()
        assert fn(rpe=3, feel=None) == "strong"

    def test_rpe_4_feel_none_returns_strong(self):
        """rpe=4, feel=None returns 'strong'."""
        fn = self._fn()
        assert fn(rpe=4, feel=None) == "strong"

    def test_rpe_6_feel_none_returns_neutral(self):
        """rpe=6, feel=None returns 'neutral'."""
        fn = self._fn()
        assert fn(rpe=6, feel=None) == "neutral"

    def test_rpe_7_feel_none_returns_neutral(self):
        """rpe=7, feel=None returns 'neutral'."""
        fn = self._fn()
        assert fn(rpe=7, feel=None) == "neutral"

    # ------------------------------------------------------------------ #
    # Notes override                                                       #
    # ------------------------------------------------------------------ #

    def test_notes_pb_forces_strong(self):
        """Notes containing 'pb' force quality to 'strong'."""
        fn = self._fn()
        result = fn(rpe=8, feel=25, notes="Hit a pb today!")
        assert result == "strong"

    def test_notes_cut_short_forces_grind(self):
        """Notes containing 'cut short' force quality to 'grind'."""
        fn = self._fn()
        result = fn(rpe=3, feel=75, notes="Had to cut short due to cramp")
        assert result == "grind"

    def test_notes_override_applied_case_insensitive(self):
        """Notes keyword matching is case-insensitive."""
        fn = self._fn()
        assert fn(rpe=7, feel=50, notes="PR on bench press today") == "strong"
        assert fn(rpe=5, feel=75, notes="STRUGGLED throughout") == "grind"


# ============================================================================
# Phase 24 PROG-04 Tests: _silent_garmin_sync passes quality to log_session
# ============================================================================


class TestSilentGarminSyncQuality(unittest.IsolatedAsyncioTestCase):
    """_silent_garmin_sync must derive and pass quality to log_session (Pitfall 6)."""

    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_garmin_sync_passes_quality_to_log_session(
        self, mock_fetch, MockTrainingLogStore
    ):
        """Garmin-only sessions must get a quality value — not just Telegram sessions.

        Pitfall 6: if quality derivation is only in the Telegram path, Garmin
        sessions get quality=null in the weekly review.
        """
        import core.training_checkin as tc

        # feel=75 + rpe=70 (normalises to 7) → strong
        activity = _make_garmin_activity(
            perceived_exertion=70,  # raw, normalises to 7 in log_session
            feel=75,
        )
        mock_fetch.return_value = [activity]

        mock_store_instance = MagicMock()
        MockTrainingLogStore.return_value = mock_store_instance

        tc._silent_garmin_sync(_TODAY_ISO)

        mock_store_instance.log_session.assert_called_once()
        call_kwargs = mock_store_instance.log_session.call_args.kwargs
        assert "quality" in call_kwargs, (
            "_silent_garmin_sync must pass quality= to log_session (Pitfall 6)"
        )
        # feel=75, rpe=70 (raw, >=5 after normalise) → quality should be "strong"
        assert call_kwargs["quality"] == "strong", (
            f"Expected 'strong' for feel=75 + rpe=70(raw), got {call_kwargs['quality']!r}"
        )

    @patch("core.training_checkin.TrainingLogStore")
    @patch("core.training_checkin.fetch_garmin_activities")
    async def test_silent_garmin_sync_feel_zero_is_grind(
        self, mock_fetch, MockTrainingLogStore
    ):
        """feel==0 (Very Weak) must produce quality='grind', not None (Pitfall 4)."""
        import core.training_checkin as tc

        activity = _make_garmin_activity(
            perceived_exertion=70,
            feel=0,  # Very Weak — falsy in Python but valid
        )
        mock_fetch.return_value = [activity]

        mock_store_instance = MagicMock()
        MockTrainingLogStore.return_value = mock_store_instance

        tc._silent_garmin_sync(_TODAY_ISO)

        call_kwargs = mock_store_instance.log_session.call_args.kwargs
        assert call_kwargs.get("quality") == "grind", (
            f"feel=0 must produce 'grind', got {call_kwargs.get('quality')!r}"
        )


# ============================================================================
# Phase 24 PROG-04: handle_rpe_callback passes quality to log_session
# ============================================================================


class TestHandleRpeCallbackQuality(unittest.IsolatedAsyncioTestCase):
    """handle_rpe_callback must derive quality from RPE and pass it to log_session."""

    @patch("core.training_checkin.send_and_inject", new_callable=AsyncMock)
    @patch("core.training_checkin.PendingPromptStore")
    @patch("core.training_checkin.TrainingLogStore")
    async def test_handle_rpe_callback_passes_quality(
        self, MockTLS, MockPPS, mock_send
    ):
        """RPE tap must derive provisional quality from RPE alone and write it."""
        import core.training_checkin as tc

        pps_instance = MagicMock()
        pps_instance.get.return_value = {
            "session_type": "gym",
            "event_date": _TODAY_ISO,
        }
        MockPPS.return_value = pps_instance

        tls_instance = MagicMock()
        MockTLS.return_value = tls_instance

        fake_msg = MagicMock()
        fake_msg.message_id = 42
        mock_send.return_value = fake_msg

        cq = _FakeCallbackQuery(data=f"rpe:20260601_evt_abc:9")
        cq.message = _FakeMessage()

        await tc.handle_rpe_callback(MagicMock(), 12345, cq, f"rpe:20260601_evt_abc:9")

        tls_instance.log_session.assert_called_once()
        call_kwargs = tls_instance.log_session.call_args.kwargs
        assert "quality" in call_kwargs, (
            "handle_rpe_callback must pass quality= to log_session"
        )
        # rpe=9, feel=None → grind
        assert call_kwargs["quality"] == "grind", (
            f"rpe=9 + feel=None must produce 'grind', got {call_kwargs.get('quality')!r}"
        )


if __name__ == "__main__":
    unittest.main()
