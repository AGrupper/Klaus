"""Wave 0 + Wave 2 test scaffold for Phase 18-06: Autonomous Orchestrator.

Covers AUTO-01, AUTO-02, AUTO-03 + BLOCKER regression guards + Pitfall
protections (Pitfalls 2, 3, 4, 6) + WARNING 2/3/4/5 fixes.

Mock strategy
-------------
Firestore + google.* libraries are mocked at the ``sys.modules`` level
BEFORE any ``core.autonomous`` / ``memory.*`` import — mirrors
``tests/test_reflection.py`` and ``tests/test_main_render_smart_system.py``.

The module-level ``_orchestrator_singleton`` in ``core.autonomous`` is
reset to ``None`` between tests via a ``pytest`` fixture so each test sees
a clean state (BLOCKER 5a-related state hygiene).

Test catalogue
--------------
Task 1 (Layer-0 + helpers + new firestore method):
  - test_pre_flight_imports_resolve                                (BLOCKER 1)
  - test_gather_situation_isolation                                (AUTO-02)
  - test_gather_situation_now_context_block                        (D-08 + WARNING 3)
  - test_gather_situation_empty_signal_detection                   (D-11)
  - test_synthesize_topic_key_for_each_trigger_type                (Pitfall 4)
  - test_build_triage_prompt_substitutes_all_placeholders          (D-08)
  - test_quiet_situation_skips_tick_brain                          (BLOCKER 2 / SC-3)
  - test_calendar_overload_triggers_non_empty                      (BLOCKER 2)
  - test_calendar_overlap_triggers_non_empty                       (BLOCKER 2)
  - test_calendar_with_single_non_conflicting_event_is_quiet       (BLOCKER 2)
  - test_now_context_tick_index_at_7_00_is_1                       (WARNING 3)
  - test_now_context_tick_index_at_21_00_is_43                     (WARNING 3)
  - test_now_context_tick_index_clamps_for_early_hours             (WARNING 3)
  - test_hours_since_contact_no_record_renders_as_unknown_in_prompt (WARNING 4)
  - test_load_prompt_resolves_paths_correctly                      (WARNING 2)
  - test_firestore_conversation_get_last_user_timestamp_returns_none_when_empty
                                                                    (BLOCKER 1)
  - test_malformed_json_block_stripped_from_polished_text          (WARNING 5)

Task 2 (run_autonomous_tick + Layer-2 + follow-up + singleton):
  - test_run_autonomous_tick_empty_skip_does_not_call_tick_brain   (SC-3)
  - test_run_autonomous_tick_triage_no                             (D-20)
  - test_run_autonomous_tick_triage_yes_compose_yes                (D-10/D-18)
  - test_run_autonomous_tick_triage_yes_compose_fail_falls_back_to_draft (D-19)
  - test_layer2_returns_smart_loop_error_sentinel_falls_back_to_draft (BLOCKER 3)
  - test_layer2_smart_system_has_placeholders_resolved             (BLOCKER 5b)
  - test_orchestrator_is_module_singleton                          (BLOCKER 5a)
  - test_outreach_log_on_success_only                              (D-10 / Pitfall 3)
  - test_synthetic_message_does_not_pollute_history                (Pitfall 2)
  - test_defer_force_fire_at_three                                 (D-14 / Pitfall 6)
  - test_topic_key_fallback                                        (D-07 / Pitfall 4)
  - test_followup_fire_skips_tick_brain                            (D-13)
  - test_layer2_followup_send_action_marks_done                    (D-13)
  - test_layer2_followup_defer_below_three_does_not_send           (D-14 / NOTE 2)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


# ---------------------------------------------------------------------------
# sys.modules mock — installed BEFORE any core.autonomous / memory import
# ---------------------------------------------------------------------------

def _safe_mock_module(name: str) -> None:
    if name in sys.modules:
        return
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent in sys.modules and isinstance(sys.modules[parent], MagicMock):
            sys.modules[name] = MagicMock()
            return
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = MagicMock()


def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore + auth stubs into sys.modules.

    Mirrors the pattern from tests/test_reflection.py and
    tests/test_main_render_smart_system.py so the tested modules import
    cleanly without real Google API libraries installed.
    """
    if "google.cloud.firestore" not in sys.modules:
        import types
        try:
            import google
        except ImportError:
            google = types.ModuleType("google")
            sys.modules["google"] = google

        try:
            import google.cloud
            google_cloud_mod = sys.modules["google.cloud"]
        except ImportError:
            google_cloud_mod = types.ModuleType("google.cloud")
            sys.modules["google.cloud"] = google_cloud_mod
            if not hasattr(google, "cloud"):
                setattr(google, "cloud", google_cloud_mod)

        firestore_mock = MagicMock()

        class _Increment:
            def __init__(self, value):
                self.value = value
            def __repr__(self):
                return f"Increment({self.value!r})"

        firestore_mock.Increment = _Increment
        firestore_mock.SERVER_TIMESTAMP = object()
        firestore_mock.ArrayUnion = MagicMock()

        sys.modules["google.cloud.firestore"] = firestore_mock
        google_cloud_mod.firestore = firestore_mock
        if not hasattr(google, "cloud"):
            google.cloud = google_cloud_mod


        _safe_mock_module("google.api_core")
        _safe_mock_module("google.api_core.exceptions")
        _safe_mock_module("google.cloud.firestore_v1")
        _safe_mock_module("google.cloud.firestore_v1.base_query")

    _safe_mock_module("google.auth")
    _safe_mock_module("google.auth.exceptions")
    _safe_mock_module("google.auth.transport")
    _safe_mock_module("google.auth.transport.requests")
    _safe_mock_module("google.oauth2")
    _safe_mock_module("google.oauth2.credentials")
    _safe_mock_module("google.oauth2.service_account")
    _safe_mock_module("google_auth_oauthlib")
    _safe_mock_module("google_auth_oauthlib.flow")
    _safe_mock_module("googleapiclient")
    _safe_mock_module("googleapiclient.errors")
    _safe_mock_module("googleapiclient.discovery")

    _safe_mock_module("dotenv")


_TZ = ZoneInfo("Asia/Jerusalem")


# Bound per-test by the autouse fixture below. We deliberately do NOT install the
# mock or import core.autonomous at module/collection time — that leaks fake
# google.* / memory.firestore_db modules into sys.modules for the whole session
# and breaks sibling test files.
autonomous = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_orchestrator_singleton(isolated_modules):
    """Install stubs + import core.autonomous against them, then reset the module
    singleton between tests (BLOCKER 5a state hygiene). isolated_modules reverts
    every sys.modules mutation on teardown."""
    global autonomous
    import importlib
    _install_firestore_mock()
    sys.modules.pop("core.autonomous", None)
    sys.modules.pop("memory.firestore_db", None)  # re-bind against the mocked google
    autonomous = importlib.import_module("core.autonomous")
    autonomous._orchestrator_singleton = None
    yield
    autonomous._orchestrator_singleton = None


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def fixed_now():
    """A stable Israel-local tick datetime — Thursday 2026-05-21 10:20."""
    return datetime(2026, 5, 21, 10, 20, tzinfo=_TZ)


def _empty_situation(now: datetime) -> dict:
    """Build an explicitly empty situation dict (Layer-0 quiet)."""
    return {
        "calendar": [],
        "ticktick_overdue": [],
        "unread_email_count": 0,
        "due_followups": [],
        "hours_since_contact": None,
        "recent_journal_digest": "",
        "self_state": {},
        "today_outreach_log": [],
        "now_context": autonomous._now_context(now),
        "empty": True,
    }


def _live_situation(now: datetime, **overrides) -> dict:
    """Build a non-empty situation dict — at least one overdue task by default."""
    sit = {
        "calendar": [],
        "ticktick_overdue": [{"title": "ship plan 06", "due": "2026-05-21"}],
        "unread_email_count": 0,
        "due_followups": [],
        "hours_since_contact": 2.0,
        "recent_journal_digest": "",
        "self_state": {"current_focus": "phase 18", "mood": "focused"},
        "today_outreach_log": [],
        "now_context": autonomous._now_context(now),
        "empty": False,
    }
    sit.update(overrides)
    return sit


# ---------------------------------------------------------------------------
# Task 1 — Pre-flight + Layer 0 helpers + new firestore method
# ---------------------------------------------------------------------------

def test_pre_flight_imports_resolve():
    """BLOCKER 1 guard — REAL API import paths must resolve.

    If CONTEXT/RESEARCH ever names were re-introduced (CalendarManager,
    TickTickManager, GmailManager), these imports would fail and this guard
    would catch it before runtime.
    """
    from mcp_tools.calendar_tool import GoogleCalendarManager  # noqa: F401
    from mcp_tools.gmail_tool import GmailTool                # noqa: F401
    from memory.firestore_conversation import (                # noqa: F401
        FirestoreConversationStore,
    )


def test_gather_situation_isolation(fixed_now):
    """AUTO-02 — one source raising must not mask the other 7."""
    # Make calendar gather raise — every other source uses normal mocks.
    raising_calendar = MagicMock()
    raising_calendar.list_events.side_effect = RuntimeError("kaboom")

    with patch("core.tools._get_calendar_tool", return_value=raising_calendar), \
         patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
         patch("core.tools._get_gmail_tool") as get_gm, \
         patch("memory.firestore_db.FollowupStore") as fs_cls, \
         patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
         patch("memory.firestore_db.JournalStore") as js_cls, \
         patch("memory.firestore_db.SelfStateStore") as ss_cls, \
         patch("memory.firestore_db.OutreachLogStore") as ols_cls:
        get_gm.return_value.list_unread.return_value = []
        fs_cls.return_value.list_due.return_value = []
        conv_cls.return_value.get_last_user_timestamp.return_value = None
        js_cls.return_value.get.return_value = None
        ss_cls.return_value.get.return_value = {}
        ols_cls.return_value.topics_today.return_value = []

        out = autonomous.gather_situation(fixed_now)

    # All 8 keys present + now_context + empty (+ training_evidence).
    for k in (
        "calendar", "ticktick_overdue", "unread_email_count", "due_followups",
        "hours_since_contact", "recent_journal_digest", "self_state",
        "today_outreach_log", "now_context", "empty", "training_evidence",
    ):
        assert k in out, f"key {k} missing"
    # Calendar fallback to []; the rest still gathered.
    assert out["calendar"] == []
    assert out["ticktick_overdue"] == []


def test_gather_situation_parallel_fanout_completes_all_keys(fixed_now):
    """The thread-pool fan-out fills every gather key even when one source
    raises inside a worker thread (sentinel, no sibling poisoning)."""
    with patch("core.tools._get_calendar_tool") as get_cal, \
         patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
         patch("core.tools._get_gmail_tool") as get_gm, \
         patch("memory.firestore_db.FollowupStore") as fs_cls, \
         patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
         patch("memory.firestore_db.JournalStore") as js_cls, \
         patch("memory.firestore_db.SelfStateStore") as ss_cls, \
         patch("memory.firestore_db.OutreachLogStore") as ols_cls, \
         patch("memory.firestore_db.MealStore") as ms_cls, \
         patch("mcp_tools.garmin_tool.fetch_garmin_training_status",
               return_value={"status": "PRODUCTIVE"}), \
         patch("mcp_tools.garmin_tool.compute_acwr_from_db",
               return_value={"ratio": 1.1}):
        get_cal.return_value.list_events.return_value = []
        get_gm.return_value.list_unread.return_value = []
        fs_cls.return_value.list_due.return_value = []
        conv_cls.return_value.get_last_user_timestamp.return_value = None
        js_cls.return_value.get.return_value = None
        ss_cls.return_value.get.return_value = {}
        ols_cls.return_value.topics_today.return_value = []
        # Meals source raises INSIDE its worker thread → sentinel [].
        ms_cls.return_value.get_day.side_effect = RuntimeError("kaboom in thread")

        out = autonomous.gather_situation(fixed_now)

    for k in (
        "calendar", "ticktick_overdue", "unread_email_count", "due_followups",
        "hours_since_contact", "recent_journal_digest", "self_state",
        "today_outreach_log", "meals_since_last_tick", "training_status",
        "acwr", "now_context", "empty", "training_evidence",
    ):
        assert k in out, f"key {k} missing"
    assert out["meals_since_last_tick"] == []          # sentinel, not poison
    assert out["training_status"] == {"status": "PRODUCTIVE"}  # sibling intact
    assert out["acwr"] == {"ratio": 1.1}


def test_gather_situation_now_context_block(fixed_now):
    """D-08 — now_context contains the 5 required keys; tick_total == 43."""
    with patch("core.tools._get_calendar_tool"), \
         patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
         patch("core.tools._get_gmail_tool") as get_gm, \
         patch("memory.firestore_db.FollowupStore") as fs_cls, \
         patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
         patch("memory.firestore_db.JournalStore"), \
         patch("memory.firestore_db.SelfStateStore"), \
         patch("memory.firestore_db.OutreachLogStore"):
        get_gm.return_value.list_unread.return_value = []
        fs_cls.return_value.list_due.return_value = []
        conv_cls.return_value.get_last_user_timestamp.return_value = None

        out = autonomous.gather_situation(fixed_now)

    nc = out["now_context"]
    for k in ("now_iso", "now_local", "tick_index", "tick_total", "last_tick_at"):
        assert k in nc, f"now_context missing key {k}"
    assert nc["tick_total"] == 43, "WARNING 3 — tick_total must be 43"


def test_gather_situation_empty_signal_detection(fixed_now):
    """D-11 — fully empty sources => empty=True."""
    with patch("core.tools._get_calendar_tool") as get_cal, \
         patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
         patch("core.tools._get_gmail_tool") as get_gm, \
         patch("memory.firestore_db.FollowupStore") as fs_cls, \
         patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
         patch("memory.firestore_db.JournalStore"), \
         patch("memory.firestore_db.SelfStateStore"), \
         patch("memory.firestore_db.OutreachLogStore"):
        get_cal.return_value.list_events.return_value = []
        get_gm.return_value.list_unread.return_value = []
        fs_cls.return_value.list_due.return_value = []
        conv_cls.return_value.get_last_user_timestamp.return_value = None

        out = autonomous.gather_situation(fixed_now)

    assert out["empty"] is True


def test_synthesize_topic_key_for_each_trigger_type(fixed_now):
    """Pitfall 4 — every trigger label yields a non-empty topic_key."""
    sit = _live_situation(fixed_now)
    # overdue with title
    overdue_key = autonomous._synthesize_topic_key("overdue", sit)
    assert overdue_key.startswith("overdue:auto-"), overdue_key
    # silence, gap, quiet
    for trig in ("silence", "gap", "quiet"):
        key = autonomous._synthesize_topic_key(trig, sit)
        assert key.startswith(f"{trig}:tick-"), key
    # followup with id
    sit_fu = _live_situation(fixed_now, due_followups=[{"id": "fu123"}])
    fu_key = autonomous._synthesize_topic_key("followup", sit_fu)
    assert fu_key == "followup:fu123", fu_key
    # empty string never returned
    for trig in ("", None, "general"):
        key = autonomous._synthesize_topic_key(trig, sit)
        assert key, f"trigger {trig!r} returned empty key"


def test_build_triage_prompt_substitutes_all_placeholders(fixed_now):
    """Resulting prompt contains representative substrings from each input block."""
    sit = _live_situation(
        fixed_now,
        unread_email_count=3,
        recent_journal_digest="[2026-05-20] wrapped Plan 04",
        today_outreach_log=["overdue:auto-ship-it"],
    )
    prompt = autonomous._build_triage_prompt(sit, "TRIAGE-SYSTEM-IGNORED")

    # Snapshot block (JSON)
    assert "ticktick_overdue" in prompt
    assert "ship plan 06" in prompt
    # self-state
    assert "current_focus: phase 18" in prompt
    assert "mood: focused" in prompt
    # journal
    assert "wrapped Plan 04" in prompt
    # now_context — tick count rendered
    assert "tick " in prompt
    assert "of 43" in prompt
    # outreach
    assert "overdue:auto-ship-it" in prompt


def test_quiet_situation_skips_tick_brain(fixed_now):
    """BLOCKER 2 / SC-3 — single non-conflicting calendar event must stay quiet."""
    # One standup event 10:00–10:30; no overdue, no followups.
    today = fixed_now.replace(hour=0, minute=0)
    standup_start = today.replace(hour=10, minute=0).isoformat()
    standup_end   = today.replace(hour=10, minute=30).isoformat()
    sit = {
        "calendar": [{"summary": "Standup", "start": standup_start, "end": standup_end}],
        "ticktick_overdue": [],
        "due_followups": [],
        "now_context": autonomous._now_context(fixed_now),
    }
    assert autonomous._is_empty_signals(sit) is True


def test_calendar_overload_triggers_non_empty(fixed_now):
    """BLOCKER 2 — >2 events in the next 2h flips _calendar_has_gap_or_overload True."""
    now_ctx = autonomous._now_context(fixed_now)
    # 3 events all starting within next 2h.
    e1_s = (fixed_now + timedelta(minutes=15)).isoformat()
    e1_e = (fixed_now + timedelta(minutes=45)).isoformat()
    e2_s = (fixed_now + timedelta(minutes=50)).isoformat()
    e2_e = (fixed_now + timedelta(minutes=80)).isoformat()
    e3_s = (fixed_now + timedelta(minutes=85)).isoformat()
    e3_e = (fixed_now + timedelta(minutes=115)).isoformat()
    events = [
        {"start": e1_s, "end": e1_e},
        {"start": e2_s, "end": e2_e},
        {"start": e3_s, "end": e3_e},
    ]
    # Use the now_iso the helper expects — derived from fixed_now (already aware).
    now_ctx["now_iso"] = fixed_now.isoformat()
    assert autonomous._calendar_has_gap_or_overload(events, now_ctx) is True
    sit = {
        "calendar": events,
        "ticktick_overdue": [],
        "due_followups": [],
        "now_context": now_ctx,
    }
    assert autonomous._is_empty_signals(sit) is False


def test_calendar_overlap_triggers_non_empty(fixed_now):
    """BLOCKER 2 — two events with overlapping ranges signal."""
    now_ctx = autonomous._now_context(fixed_now)
    now_ctx["now_iso"] = fixed_now.isoformat()
    a_s = fixed_now.replace(hour=11, minute=0).isoformat()
    a_e = fixed_now.replace(hour=12, minute=0).isoformat()
    b_s = fixed_now.replace(hour=11, minute=30).isoformat()
    b_e = fixed_now.replace(hour=12, minute=30).isoformat()
    events = [{"start": a_s, "end": a_e}, {"start": b_s, "end": b_e}]
    assert autonomous._calendar_has_gap_or_overload(events, now_ctx) is True

def test_calendar_has_gap_or_overload_naive_aware_mix(fixed_now):
    """Verify that a mix of offset-naive (all-day) and offset-aware (timed) calendar events does not raise a TypeError."""
    now_ctx = autonomous._now_context(fixed_now)
    now_ctx["now_iso"] = fixed_now.isoformat()
    # Timed event (offset-aware)
    timed_s = fixed_now.replace(hour=11, minute=0).isoformat()
    timed_e = fixed_now.replace(hour=12, minute=0).isoformat()
    # 1. Non-overlapping all-day event (offset-naive start/end format YYYY-MM-DD on a different day)
    all_day_s1 = "2026-05-22"
    all_day_e1 = "2026-05-23"
    events_non_overlap = [
        {"start": timed_s, "end": timed_e},
        {"start": all_day_s1, "end": all_day_e1},
    ]
    # This should complete successfully and return False (since there is no overlap)
    assert autonomous._calendar_has_gap_or_overload(events_non_overlap, now_ctx) is False

    # 2. Overlapping all-day event (offset-naive start/end format YYYY-MM-DD on the same day)
    all_day_s2 = "2026-05-21"
    all_day_e2 = "2026-05-22"
    events_overlap = [
        {"start": timed_s, "end": timed_e},
        {"start": all_day_s2, "end": all_day_e2},
    ]
    # This should complete successfully and return True (since they overlap)
    assert autonomous._calendar_has_gap_or_overload(events_overlap, now_ctx) is True



def test_calendar_with_single_non_conflicting_event_is_quiet(fixed_now):
    """BLOCKER 2 — single isolated event is NOT a signal."""
    now_ctx = autonomous._now_context(fixed_now)
    now_ctx["now_iso"] = fixed_now.isoformat()
    s = fixed_now.replace(hour=14, minute=0).isoformat()
    e = fixed_now.replace(hour=14, minute=30).isoformat()
    events = [{"start": s, "end": e}]
    assert autonomous._calendar_has_gap_or_overload(events, now_ctx) is False


def test_now_context_tick_index_at_7_00_is_1():
    """WARNING 3 — tick at 7:00 is the first of the day, index 1."""
    nc = autonomous._now_context(datetime(2026, 5, 21, 7, 0, tzinfo=_TZ))
    assert nc["tick_index"] == 1


def test_now_context_tick_index_at_21_00_is_43():
    """WARNING 3 — tick at 21:00 is the last of the day, index 43."""
    nc = autonomous._now_context(datetime(2026, 5, 21, 21, 0, tzinfo=_TZ))
    assert nc["tick_index"] == 43


def test_now_context_tick_index_clamps_for_early_hours():
    """WARNING 3 — pre-7:00 manual runs clamp to index 1 without erroring."""
    nc = autonomous._now_context(datetime(2026, 5, 21, 3, 0, tzinfo=_TZ))
    assert nc["tick_index"] >= 1
    assert nc["tick_index"] <= 43


def test_hours_since_contact_no_record_renders_as_unknown_in_prompt(fixed_now):
    """WARNING 4 — None hours_since_contact -> 'unknown', NEVER '999'."""
    sit = _live_situation(fixed_now, hours_since_contact=None)
    prompt = autonomous._build_triage_prompt(sit, "")
    assert "unknown" in prompt
    assert "999" not in prompt


def test_gather_hours_since_contact_uses_allowed_user_ids_env(monkeypatch, fixed_now):
    """The gather reads the first entry of TELEGRAM_ALLOWED_USER_IDS — the
    codebase-wide convention. It originally read a TELEGRAM_USER_ID var that
    exists nowhere in the deployment, so it queried user 0 and returned None
    on all 823 live ticks (silence trigger never had data)."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789,987654321")
    store = MagicMock()
    store.get_last_user_timestamp.return_value = fixed_now - timedelta(hours=3)
    with patch(
        "memory.firestore_conversation.FirestoreConversationStore",
        return_value=store,
    ):
        result = autonomous._gather_hours_since_contact(fixed_now, "proj", "db")
    store.get_last_user_timestamp.assert_called_once_with(123456789)
    assert result == 3.0


def test_gather_hours_since_contact_env_unset_returns_none(monkeypatch, fixed_now):
    """No TELEGRAM_ALLOWED_USER_IDS -> None (unknown), never a user-0 query."""
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    with patch(
        "memory.firestore_conversation.FirestoreConversationStore",
    ) as store_cls:
        result = autonomous._gather_hours_since_contact(fixed_now, "proj", "db")
    assert result is None
    store_cls.return_value.get_last_user_timestamp.assert_not_called()


def test_load_prompt_resolves_paths_correctly():
    """WARNING 2 — _load_prompt uses core/main.py's relative-path strategy."""
    text = autonomous._load_prompt("prompts/autonomous_triage.md")
    # File exists and returns substantive content
    assert text
    assert len(text) > 100  # the triage prompt is substantial


def test_firestore_conversation_get_last_user_timestamp_returns_none_when_empty():
    """BLOCKER 1 — new method returns None on empty conversation."""
    from memory.firestore_conversation import FirestoreConversationStore

    # Build the store without going through __init__ (which would try to
    # connect to real Firestore). Stub the _col attribute the method reads.
    store = FirestoreConversationStore.__new__(FirestoreConversationStore)
    col = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = False
    col.document.return_value.get.return_value = snapshot
    store._col = col

    assert store.get_last_user_timestamp(42) is None


def test_malformed_json_block_stripped_from_polished_text():
    """WARNING 5 — malformed JSON block is stripped from the polished text.

    The regex pattern requires balanced braces ``{.*?}`` to detect a block;
    once detected, an unparseable interior must NOT leak to the user — the
    polished text is the body BEFORE the block.
    """
    text = (
        "Some message body here.\n"
        "```json {malformed: not valid, bad: json}```\n"
    )
    action, polished = autonomous._parse_followup_action(text)
    assert action == "send"
    assert "malformed" not in polished
    assert "Some message body here." in polished


# ---------------------------------------------------------------------------
# Task 2 — run_autonomous_tick + Layer 2 + follow-up + singleton
# ---------------------------------------------------------------------------

def test_run_autonomous_tick_empty_skip_does_not_call_tick_brain(mock_bot, fixed_now):
    """SC-3 — empty Layer 0 returns early; no tick-brain call, no send."""
    with patch.object(autonomous, "gather_situation",
                      return_value=_empty_situation(fixed_now)) as gather, \
         patch("core.tick_brain.TickBrain") as tb_cls, \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        decision = asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    gather.assert_called_once()
    tb_cls.assert_not_called()
    send.assert_not_called()
    assert decision["skipped"] == "empty"
    assert decision["sent"] is False


def test_run_autonomous_tick_triage_no(mock_bot, fixed_now):
    """Triage returns should_act=False — no Layer-2, no send."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {"should_act": False, "reason": "all quiet"}
    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2") as compose, \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        decision = asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    tb_instance.think.assert_called_once()
    compose.assert_not_called()
    send.assert_not_called()
    assert decision["sent"] is False


def test_run_autonomous_tick_triage_yes_compose_yes(mock_bot, fixed_now):
    """Happy path — triage yes, compose yes, send + outreach_log append."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {
        "should_act": True,
        "reason": "overdue task",
        "draft": "Sir, plan 06 is overdue.",
        "topic_key": "overdue:plan-06",
    }
    ols_instance = MagicMock()
    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2",
                      return_value="Sir, plan 06 is overdue. Care to ship?"), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        decision = asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    # send_and_inject called with the final composed text + inject=True
    send.assert_called_once()
    args, kwargs = send.call_args
    assert args[0] is mock_bot
    assert "Sir, plan 06 is overdue. Care to ship?" in args[1]
    assert kwargs.get("inject_into_conversation") is True

    # OutreachLogStore.append called with topic_key + final
    ols_instance.append.assert_called_once()
    entry = ols_instance.append.call_args[0][1]
    assert entry["topic_key"] == "overdue:plan-06"
    assert "Care to ship" in entry["final"]

    assert decision["sent"] is True


def test_run_autonomous_tick_triage_yes_compose_fail_falls_back_to_draft(mock_bot, fixed_now):
    """D-19 — Layer 2 raises => fall back to tick-brain draft + still ship + still log."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {
        "should_act": True,
        "reason": "overdue task",
        "draft": "Sir, plan 06 is overdue.",
        "topic_key": "overdue:plan-06",
    }
    ols_instance = MagicMock()
    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2", side_effect=RuntimeError("boom")), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        decision = asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    send.assert_called_once()
    args, kwargs = send.call_args
    assert args[1] == "Sir, plan 06 is overdue."
    assert kwargs.get("inject_into_conversation") is True

    ols_instance.append.assert_called_once()
    entry = ols_instance.append.call_args[0][1]
    assert entry["final"] == "Sir, plan 06 is overdue."

    assert decision["sent"] is True


def test_layer2_returns_smart_loop_error_sentinel_falls_back_to_draft(mock_bot, fixed_now):
    """BLOCKER 3 — _compose_layer2 returning the sentinel string is detected as failure."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {
        "should_act": True,
        "reason": "overdue",
        "draft": "Plan 06 needs your attention, Sir.",
        "topic_key": "overdue:plan-06",
    }
    sentinel_text = (
        "I'm afraid I encountered a connectivity issue, Sir. "
        "Please try again in a moment."
    )
    ols_instance = MagicMock()
    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2", return_value=sentinel_text), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    # Sent text MUST be the draft, NOT the sentinel.
    args, _ = send.call_args
    assert "connectivity issue" not in args[1]
    assert args[1] == "Plan 06 needs your attention, Sir."
    # OutreachLog records the draft as final (D-19 fallback).
    entry = ols_instance.append.call_args[0][1]
    assert entry["final"] == "Plan 06 needs your attention, Sir."


def test_layer2_smart_system_has_placeholders_resolved(fixed_now):
    """BLOCKER 5b — smart_system passed to _run_smart_loop has NO placeholders."""
    sit = _live_situation(fixed_now)

    # Build a fake orchestrator whose render_smart_system replaces placeholders.
    fake_orchestrator = MagicMock()
    def _render(template: str) -> str:
        return (
            template
            .replace("{self_md}", "SELF-MD-RESOLVED")
            .replace("{self_state}", "STATE-RESOLVED")
            .replace("{journal_digest}", "JOURNAL-RESOLVED")
            .replace("{today_date}", "Friday, May 22, 2026")
        )
    fake_orchestrator.render_smart_system.side_effect = _render
    fake_orchestrator._run_smart_loop.return_value = "ok"

    with patch.object(autonomous, "_get_orchestrator", return_value=fake_orchestrator):
        autonomous._compose_layer2(sit, "draft", "reason")

    # Capture the smart_system arg passed to _run_smart_loop (2nd positional).
    call = fake_orchestrator._run_smart_loop.call_args
    smart_system_passed = call.args[1]
    for token in ("{self_md}", "{self_state}", "{journal_digest}", "{today_date}"):
        assert token not in smart_system_passed, (
            f"placeholder {token} survived render before _run_smart_loop"
        )


def test_orchestrator_is_module_singleton():
    """BLOCKER 5a — _get_orchestrator returns the SAME instance on repeat calls."""
    # Patch AgentOrchestrator constructor to a counted MagicMock.
    fake_instance = MagicMock(name="FakeOrchestrator")
    with patch("core.main.AgentOrchestrator", return_value=fake_instance) as ctor:
        o1 = autonomous._get_orchestrator()
        o2 = autonomous._get_orchestrator()

    assert o1 is o2, "singleton broke — second call returned a different object"
    assert ctor.call_count == 1, (
        f"AgentOrchestrator constructed {ctor.call_count} times, expected 1"
    )


def test_outreach_log_on_success_only(mock_bot, fixed_now):
    """D-10 / Pitfall 3 — send failure MUST skip OutreachLogStore.append."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {
        "should_act": True, "reason": "x", "draft": "draft text", "topic_key": "x:y",
    }
    ols_instance = MagicMock()
    failing_send = AsyncMock(side_effect=RuntimeError("telegram down"))

    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2", return_value="composed text"), \
         patch("core.scheduled_message.send_and_inject", new=failing_send), \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        decision = asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    failing_send.assert_called_once()
    ols_instance.append.assert_not_called()
    assert decision["sent"] is False


def test_synthetic_message_does_not_pollute_history(mock_bot, fixed_now):
    """Pitfall 2 — autonomous tick must NEVER route through handle_message
    and must NEVER append to conversation history via the orchestrator."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {
        "should_act": True, "reason": "x", "draft": "d", "topic_key": "k",
    }
    fake_orchestrator = MagicMock()
    fake_orchestrator.handle_message = MagicMock()
    fake_orchestrator.conversation_manager = MagicMock()
    fake_orchestrator.render_smart_system.side_effect = lambda t: t
    fake_orchestrator._run_smart_loop.return_value = "composed"

    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_get_orchestrator", return_value=fake_orchestrator), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()), \
         patch("memory.firestore_db.OutreachLogStore"), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    fake_orchestrator.handle_message.assert_not_called()
    fake_orchestrator.conversation_manager.append.assert_not_called()


def test_defer_force_fire_at_three(mock_bot, fixed_now):
    """D-14 / Pitfall 6 — defer_count >= 3 force-fires despite LLM saying defer."""
    fu = {
        "id": "fu-force",
        "due_at": (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(),
        "note": "ping about plan 06",
        "defer_count": 3,
    }
    sit = _live_situation(fixed_now, due_followups=[fu])

    fs_instance = MagicMock()
    ols_instance = MagicMock()

    # Layer 2 says defer — handler must override because defer_count >= 3.
    with patch.object(autonomous, "_compose_followup_layer2",
                      return_value='polished text\n```json {"action": "defer"}```'), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch("memory.firestore_db.FollowupStore", return_value=fs_instance), \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance):
        outcome = asyncio.run(
            autonomous._compose_followup(mock_bot, fu, sit, fixed_now)
        )

    assert outcome == "force_fired"
    send.assert_called_once()
    fs_instance.mark_done.assert_called_once_with("fu-force")
    fs_instance.defer.assert_not_called()


def test_topic_key_fallback(mock_bot, fixed_now):
    """D-07 / Pitfall 4 — missing topic_key from tick-brain triggers synthesis."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {
        "should_act": True,
        "reason": "overdue work",
        "draft": "draft text",
        # NO topic_key key
    }
    ols_instance = MagicMock()
    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2", return_value="composed"), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()), \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    ols_instance.append.assert_called_once()
    entry = ols_instance.append.call_args[0][1]
    assert entry["topic_key"], "topic_key should be non-empty (synthesised)"
    assert entry["topic_key"].startswith("overdue:auto-"), (
        f"expected synthesised overdue topic_key, got {entry['topic_key']!r}"
    )


def test_followup_fire_skips_tick_brain(mock_bot, fixed_now):
    """D-13 — follow-up branch is dedicated; tick-brain may still run for triage
    but the follow-up itself is handled by _compose_followup directly."""
    fu = {
        "id": "fu1",
        "due_at": (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(),
        "note": "remember groceries",
        "defer_count": 0,
    }
    # Make a non-empty situation that ONLY has the followup (no overdue tasks).
    sit = _live_situation(
        fixed_now,
        ticktick_overdue=[],
        due_followups=[fu],
    )
    sit["empty"] = False  # followups force non-empty

    tb_instance = MagicMock()
    tb_instance.think.return_value = {"should_act": False, "reason": "all quiet"}

    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_followup", new=AsyncMock(return_value="sent")) as compose_fu, \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()), \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))

    # D-13 — _compose_followup is called for the due follow-up.
    compose_fu.assert_called_once()
    # The fid we passed.
    assert compose_fu.call_args[0][1] is fu


def test_layer2_followup_send_action_marks_done(mock_bot, fixed_now):
    """Layer-2 returns action=send => mark_done + send + outreach_log."""
    fu = {
        "id": "fu-send",
        "due_at": (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(),
        "note": "the ping note",
        "defer_count": 0,
    }
    sit = _live_situation(fixed_now, due_followups=[fu])
    fs_instance = MagicMock()
    ols_instance = MagicMock()

    with patch.object(autonomous, "_compose_followup_layer2",
                      return_value='Polished body.\n```json {"action": "send"}```'), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch("memory.firestore_db.FollowupStore", return_value=fs_instance), \
         patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance):
        outcome = asyncio.run(autonomous._compose_followup(mock_bot, fu, sit, fixed_now))

    assert outcome == "sent"
    send.assert_called_once()
    fs_instance.mark_done.assert_called_once_with("fu-send")
    ols_instance.append.assert_called_once()


def test_layer2_followup_defer_below_three_does_not_send(mock_bot, fixed_now):
    """defer_count < 3 + action=defer => FollowupStore.defer called, send NOT called."""
    original_due = (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc)
    fu = {
        "id": "fu-defer",
        "due_at": original_due.isoformat(),
        "note": "the ping",
        "defer_count": 1,
    }
    sit = _live_situation(fixed_now, due_followups=[fu])
    fs_instance = MagicMock()

    with patch.object(autonomous, "_compose_followup_layer2",
                      return_value='```json {"action": "defer"}```'), \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch("memory.firestore_db.FollowupStore", return_value=fs_instance):
        outcome = asyncio.run(autonomous._compose_followup(mock_bot, fu, sit, fixed_now))

    assert outcome == "deferred"
    send.assert_not_called()
    fs_instance.defer.assert_called_once()
    # NOTE 2 — new_due = original_due + 1h
    _fid, new_due_at = fs_instance.defer.call_args[0]
    expected_new_due = (original_due + timedelta(hours=1)).isoformat()
    assert new_due_at == expected_new_due, (
        f"defer must push original_due+1h (NOTE 2). got {new_due_at!r}, expected {expected_new_due!r}"
    )


# ---------------------------------------------------------------------------
# M-5 — Sentinel/main.py constant coupling (post-review hardening, 2026-05-23)
# ---------------------------------------------------------------------------

def test_sentinel_substring_matches_main_constant():
    """M-5 — autonomous's Layer-2 failure detection keys on a substring of
    ``core.main.CONNECTIVITY_ERROR_TEXT``. If anyone edits the canned message
    in main.py and forgets to update _SMART_LOOP_ERROR_SENTINELS here, D-19
    fallback silently breaks. Imported lazily to avoid pulling core.main into
    every test session — only this guard needs it.
    """
    from core.main import CONNECTIVITY_ERROR_TEXT

    assert autonomous._SMART_LOOP_ERROR_SENTINELS, (
        "_SMART_LOOP_ERROR_SENTINELS must not be empty"
    )
    for sentinel in autonomous._SMART_LOOP_ERROR_SENTINELS:
        assert sentinel in CONNECTIVITY_ERROR_TEXT, (
            f"sentinel {sentinel!r} no longer matches core.main.CONNECTIVITY_ERROR_TEXT "
            f"({CONNECTIVITY_ERROR_TEXT!r}) — update both sides or D-19 fallback "
            "silently breaks"
        )


# ---------------------------------------------------------------------------
# Phase 19 — gather extensions (meals + training_status + acwr)
# ---------------------------------------------------------------------------

class TestPhase19Gather:
    def _patch_existing_sources(self):
        """Helper context-manager building — patches the 8 existing gather sources
        to no-op stubs so we can isolate Phase-19 source behavior."""
        return [
            patch("core.tools._get_calendar_tool"),
            patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}),
            patch("core.tools._get_gmail_tool"),
            patch("memory.firestore_db.FollowupStore"),
            patch("memory.firestore_conversation.FirestoreConversationStore"),
            patch("memory.firestore_db.JournalStore"),
            patch("memory.firestore_db.SelfStateStore"),
            patch("memory.firestore_db.OutreachLogStore"),
        ]

    def test_gather_includes_phase19_keys(self, fixed_now, monkeypatch):
        """gather_situation returns 3 new keys with mocked values."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        fake_meals = [{"source_id": "x:1", "timestamp": "2026-05-21T13:00+03:00", "calories": 500}]
        fake_status = {"vo2_max": 51.7, "training_status": "PRODUCTIVE", "load_focus": "BALANCED"}
        fake_acwr = {"acute": 80.0, "chronic": 75.0, "ratio": 1.07}

        mock_meal_store = MagicMock()
        mock_meal_store.get_day.return_value = fake_meals

        existing = self._patch_existing_sources()
        for p in existing:
            p.start()
        try:
            with patch("memory.firestore_db.MealStore", return_value=mock_meal_store), \
                 patch("mcp_tools.garmin_tool.fetch_garmin_training_status", return_value=fake_status), \
                 patch("mcp_tools.garmin_tool.compute_acwr_from_db", return_value=fake_acwr):
                result = autonomous.gather_situation(fixed_now)
        finally:
            for p in existing:
                p.stop()

        assert result.get("meals_since_last_tick") == fake_meals
        assert result.get("training_status") == fake_status
        assert result.get("acwr") == fake_acwr

    def test_gather_phase19_source_failure_isolation(self, fixed_now, monkeypatch):
        """Each new source raises independently → others still populated."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        # Phase 19.3: meals now read from MealStore.get_day() (not Google Fit).
        failing_meal_store = MagicMock()
        failing_meal_store.get_day.side_effect = RuntimeError("firestore down")
        existing = self._patch_existing_sources()
        for p in existing:
            p.start()
        try:
            with patch("memory.firestore_db.MealStore", return_value=failing_meal_store), \
                 patch("mcp_tools.garmin_tool.fetch_garmin_training_status", return_value={"vo2_max": 50}), \
                 patch("mcp_tools.garmin_tool.compute_acwr_from_db", side_effect=RuntimeError("pg down")):
                result = autonomous.gather_situation(fixed_now)
        finally:
            for p in existing:
                p.stop()

        # Meals source failed → empty list sentinel
        assert result.get("meals_since_last_tick") == []
        # Training status succeeded → real value
        assert result.get("training_status") == {"vo2_max": 50}
        # ACWR failed → ratio: None sentinel
        assert result.get("acwr") == {"ratio": None}

    def test_meal_in_meals_since_last_tick_makes_signals_not_empty(self):
        """NUTR-04: a non-empty meals list is a trigger for the autonomous tick."""
        situation = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [{"source_id": "x:1"}],
            "training_status": {},
            "acwr": {"ratio": None},
            "now_context": {},
        }
        assert autonomous._is_empty_signals(situation) is False

    def test_training_status_and_acwr_alone_keep_signals_empty(self):
        """training_status + acwr are CONTEXT only — not triggers (NUTR-04 boundary)."""
        situation = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [],
            "training_status": {"vo2_max": 51.7, "training_status": "PRODUCTIVE"},
            "acwr": {"ratio": 1.6},
            "now_context": {},
        }
        # Even with high ACWR, signals are empty — training context never triggers
        assert autonomous._is_empty_signals(situation) is True

    def test_long_silence_alone_is_a_signal(self):
        """hours_since_contact >= threshold wakes tick-brain on an empty day —
        otherwise silence-only days never reach the silence trigger at all."""
        situation = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [],
            "hours_since_contact": 11.5,
            "now_context": {},
        }
        assert autonomous._is_empty_signals(situation) is False

    def test_short_or_unknown_silence_keeps_signals_empty(self):
        """Below-threshold hsc and None (unknown) must NOT wake tick-brain."""
        base = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [],
            "now_context": {},
        }
        assert autonomous._is_empty_signals({**base, "hours_since_contact": 2.0}) is True
        assert autonomous._is_empty_signals({**base, "hours_since_contact": None}) is True

    def test_triage_prompt_includes_phase19_keys(self):
        """_build_triage_prompt JSON snapshot includes the 3 new keys."""
        situation = {
            "calendar": [],
            "ticktick_overdue": [],
            "unread_email_count": 0,
            "due_followups": [],
            "hours_since_contact": 2.0,
            "recent_journal_digest": "",
            "self_state": {},
            "today_outreach_log": [],
            "now_context": {"label": "afternoon"},
            "meals_since_last_tick": [{"source_id": "x:1", "calories": 500}],
            "training_status": {"vo2_max": 51.7},
            "acwr": {"acute": 80.0, "chronic": 75.0, "ratio": 1.07},
        }
        prompt = autonomous._build_triage_prompt(situation, "")
        assert "meals_since_last_tick" in prompt
        assert "training_status" in prompt
        assert "acwr" in prompt


# ---------------------------------------------------------------------------
# TestPhase19MealAuditWiring — NUTR-08 runtime wiring (Plan 19-05 Task 5)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestNativeOverdueGather + TestJobsDict — Phase 27 Wave 0 scaffold (27-03)
# ---------------------------------------------------------------------------


class TestNativeOverdueGather:
    """Native task overdue gather in core/autonomous.py.

    Covers TASK-05 / D-17: _gather_native_overdue replaces _gather_ticktick_overdue
    while keeping the same return shape [{title, due}, ...].
    """

    def test_gather_native_overdue_exists_in_autonomous(self):
        """core/autonomous.py must define _gather_native_overdue (not _gather_ticktick_overdue)."""
        import core.autonomous as auto
        assert hasattr(auto, "_gather_native_overdue"), (
            "_gather_native_overdue not found in core.autonomous"
        )
        assert not hasattr(auto, "_gather_ticktick_overdue"), (
            "_gather_ticktick_overdue still present — must be renamed"
        )

    def test_gather_native_overdue_returns_list_of_title_due_dicts(self):
        """_gather_native_overdue() must return [{title: str, due: str}, ...] shape."""
        from unittest.mock import MagicMock, patch
        import core.autonomous as auto

        fake_store = MagicMock()
        fake_store.get_overdue.return_value = [
            {"task_id": "abc", "title": "Buy milk", "due_date": "2026-06-17",
             "status": "active", "list_id": "inbox"},
        ]
        with patch("memory.firestore_db.TaskStore", return_value=fake_store):
            result = auto._gather_native_overdue()

        assert isinstance(result, list), "must return a list"
        assert len(result) == 1
        item = result[0]
        assert set(item.keys()) == {"title", "due"}, (
            f"must have exactly {{title, due}} keys, got {set(item.keys())}"
        )
        assert item["title"] == "Buy milk"
        assert item["due"] == "2026-06-17"

    def test_gather_native_overdue_reads_from_task_store_not_ticktick(self):
        """_gather_native_overdue source must import from memory.firestore_db.TaskStore,
        NOT from mcp_tools.ticktick_tool."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        # The function body must reference TaskStore
        assert "TaskStore" in src, "core/autonomous.py must import TaskStore"
        # And _gather_native_overdue must not call ticktick_tool.get_today_tasks
        func_start = src.find("def _gather_native_overdue")
        assert func_start != -1, "_gather_native_overdue not found in source"
        # Find end of function (next def or class at same indentation)
        func_body = src[func_start:func_start + 800]
        assert "ticktick_tool" not in func_body, (
            "_gather_native_overdue body must not reference ticktick_tool"
        )

    def test_gather_native_overdue_returns_empty_list_on_exception(self):
        """_gather_native_overdue must never raise — returns [] on any error."""
        from unittest.mock import patch, MagicMock
        import core.autonomous as auto

        with patch("memory.firestore_db.TaskStore", side_effect=Exception("boom")):
            result = auto._gather_native_overdue()

        assert result == [], f"must return [] on exception, got {result!r}"


class TestJobsDict:
    """Jobs dict key name in core/autonomous.py.

    Covers TASK-05 / D-17: situation key 'ticktick_overdue' MUST be preserved
    (zero prompt changes) even after the data source swap.
    """

    def test_ticktick_overdue_key_present_in_jobs_dict(self):
        """The jobs dict source must still contain the key 'ticktick_overdue' (D-17)."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        assert '"ticktick_overdue"' in src, (
            'The string "ticktick_overdue" must remain in core/autonomous.py (D-17)'
        )

    def test_jobs_dict_ticktick_overdue_value_is_gather_native_overdue(self):
        """The 'ticktick_overdue' key must map to _gather_native_overdue in source."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        # The jobs dict entry must reference _gather_native_overdue
        assert '"ticktick_overdue": _gather_native_overdue' in src, (
            '"ticktick_overdue" entry must point to _gather_native_overdue, '
            "not the old _gather_ticktick_overdue"
        )


class TestPhase19MealAuditWiring:
    def test_autonomous_source_references_meal_audit(self):
        """NUTR-08 wiring: core/autonomous.py must reference prompts/meal_audit.md."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        assert "meal_audit.md" in src, (
            "core/autonomous.py is missing prompts/meal_audit.md load — "
            "NUTR-08 wiring broken"
        )

    def test_autonomous_loads_meal_audit_prompt_nonempty(self):
        """NUTR-08: the loaded meal_audit content must end up in the brain compose template."""
        import core.autonomous as au
        content = au._load_prompt("prompts/meal_audit.md")
        assert content, "meal_audit.md loaded empty — prompt file missing or unreadable"
        assert "Meal Audit" in content or "meal" in content.lower()

    def test_autonomous_has_two_meal_audit_load_sites(self):
        """NUTR-08: both _compose_layer2 and _compose_followup_layer2 must append meal_audit."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        # Expect at least 2 references — one per brain-compose entry point
        assert src.count("meal_audit.md") >= 2, (
            f"core/autonomous.py must reference meal_audit.md at least 2 times "
            f"(found {src.count('meal_audit.md')})"
        )


# ---------------------------------------------------------------------------
# Phase 28 Plan 03 — habit_pending Layer-0 gather + threading (HABIT-05)
# ---------------------------------------------------------------------------


class TestPhase28HabitGather:
    """Tests for _gather_habit_adherence, habit_pending in jobs/empty/triage/compose.

    Covers D-15 (per-slot salience as trigger), D-16 (streak passed through),
    D-17 (per-item-per-day dedup via CoachingTopicStore).
    """

    def test_get_habit_adherence_tool_registered(self):
        """HABIT-05: 'get_habit_adherence' must be in _HANDLERS and TOOL_SCHEMAS."""
        from core.tools import _HANDLERS, TOOL_SCHEMAS
        assert "get_habit_adherence" in _HANDLERS, (
            "'get_habit_adherence' missing from _HANDLERS"
        )
        schema_names = [s["name"] for s in TOOL_SCHEMAS]
        assert "get_habit_adherence" in schema_names, (
            "'get_habit_adherence' missing from TOOL_SCHEMAS"
        )

    def test_handle_get_habit_adherence_filters(self, monkeypatch):
        """Handler returns JSON of pending items; slot/type args filter the list."""
        import json as _json
        from unittest.mock import MagicMock, patch as _patch
        from core import tools

        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        pending_items = [
            {"habit_id": "h1", "name": "Creatine", "type": "supplement",
             "slot": "Morning", "streak": 5, "dose": "5g"},
            {"habit_id": "h2", "name": "Meditation", "type": "habit",
             "slot": "Evening", "streak": 3, "dose": None},
        ]
        mock_store = MagicMock()
        mock_store.get_pending_today.return_value = pending_items

        with _patch("memory.firestore_db.HabitStore", return_value=mock_store):
            # No filters — all items returned
            result_all = _json.loads(tools._HANDLERS["get_habit_adherence"]({}))
            assert len(result_all) == 2

            # Filter by slot=Morning
            result_slot = _json.loads(
                tools._HANDLERS["get_habit_adherence"]({"slot": "Morning"})
            )
            assert len(result_slot) == 1
            assert result_slot[0]["habit_id"] == "h1"

            # Filter by type=habit
            result_type = _json.loads(
                tools._HANDLERS["get_habit_adherence"]({"type": "habit"})
            )
            assert len(result_type) == 1
            assert result_type[0]["habit_id"] == "h2"

    def test_habit_gather_returns_empty_on_error(self):
        """_gather_habit_adherence returns [] when HabitStore raises (sentinel)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import patch as _patch
        import core.autonomous as auto

        now = datetime(2026, 6, 30, 10, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))

        with _patch("memory.firestore_db.HabitStore", side_effect=Exception("db down")):
            result = auto._gather_habit_adherence(now, "test-proj", "(default)")

        assert result == [], f"Must return [] on exception, got {result!r}"

    def test_habit_pending_makes_signals_nonempty(self):
        """D-15: a non-empty habit_pending list makes _is_empty_signals return False."""
        import core.autonomous as auto

        situation = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [],
            "hours_since_contact": None,
            "now_context": {},
            "habit_pending": [{"habit_id": "h1", "name": "Creatine", "streak": 5}],
        }
        assert auto._is_empty_signals(situation) is False, (
            "_is_empty_signals must return False when habit_pending is non-empty (D-15)"
        )

    def test_empty_habit_pending_keeps_signals_empty(self):
        """An empty habit_pending list must NOT trigger non-empty (only non-empty list matters)."""
        import core.autonomous as auto

        situation = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [],
            "hours_since_contact": None,
            "now_context": {},
            "habit_pending": [],
        }
        assert auto._is_empty_signals(situation) is True, (
            "_is_empty_signals must return True when habit_pending is [] (no pending items)"
        )

    def test_habit_gather_dedups_already_nudged(self):
        """D-17: items already nudged today (CoachingTopicStore) are excluded from gather."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import MagicMock, patch as _patch
        import core.autonomous as auto

        now = datetime(2026, 6, 30, 10, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
        today_iso = "2026-06-30"

        pending = [
            {"habit_id": "h1", "name": "Creatine", "type": "supplement",
             "slot": "Morning", "streak": 5, "dose": "5g"},
            {"habit_id": "h2", "name": "Meditation", "type": "habit",
             "slot": "Evening", "streak": 3, "dose": None},
        ]
        mock_store = MagicMock()
        mock_store.get_pending_today.return_value = pending

        mock_cts = MagicMock()
        # h1 already nudged today; h2 not
        already_nudged = {f"habit-nudge:h1:{today_iso}"}
        mock_cts.has_topic.side_effect = lambda d, t: t in already_nudged

        with _patch("memory.firestore_db.HabitStore", return_value=mock_store), \
             _patch("memory.firestore_db.CoachingTopicStore", return_value=mock_cts):
            result = auto._gather_habit_adherence(now, "test-proj", "(default)")

        # Only h2 survives dedup
        assert len(result) == 1, f"Expected 1 item after dedup, got {len(result)}: {result}"
        assert result[0]["habit_id"] == "h2"

    def test_triage_prompt_includes_habit_pending(self, fixed_now):
        """_build_triage_prompt JSON snapshot includes habit_pending key (D-16)."""
        import core.autonomous as auto

        situation = {
            "calendar": [],
            "ticktick_overdue": [],
            "unread_email_count": 0,
            "due_followups": [],
            "hours_since_contact": 2.0,
            "recent_journal_digest": "",
            "self_state": {},
            "today_outreach_log": [],
            "now_context": {"label": "morning"},
            "meals_since_last_tick": [],
            "training_status": {},
            "acwr": {"ratio": None},
            "habit_pending": [
                {"habit_id": "h1", "name": "Creatine", "type": "supplement",
                 "slot": "Morning", "streak": 5, "dose": "5g"}
            ],
        }
        prompt = auto._build_triage_prompt(situation, "")
        assert "habit_pending" in prompt, (
            "_build_triage_prompt must include 'habit_pending' in the situation snapshot"
        )
        assert "Creatine" in prompt, (
            "_build_triage_prompt must serialize the habit_pending list (D-16: streak context)"
        )

    def test_compose_layer2_includes_habit_pending(self, fixed_now):
        """_compose_layer2 snap_summary includes habit_pending key (D-16)."""
        import core.autonomous as auto

        situation = {
            "calendar": [],
            "ticktick_overdue": [],
            "unread_email_count": 0,
            "due_followups": [],
            "hours_since_contact": 2.0,
            "recent_journal_digest": "",
            "self_state": {},
            "today_outreach_log": [],
            "now_context": {},
            "meals_since_last_tick": [],
            "training_status": {},
            "acwr": {"ratio": None},
            "habit_pending": [
                {"habit_id": "h1", "name": "Omega-3", "type": "supplement",
                 "slot": "Morning", "streak": 10, "dose": "1 cap"}
            ],
        }
        fake_orchestrator = MagicMock()
        fake_orchestrator.render_smart_system.side_effect = lambda t: t
        captured_snap = {}

        def _capture_args(messages, smart_sys, worker_sys):
            captured_snap["content"] = messages[0]["content"]
            return "ok"

        fake_orchestrator._run_smart_loop.side_effect = _capture_args

        with patch.object(auto, "_get_orchestrator", return_value=fake_orchestrator):
            auto._compose_layer2(situation, "draft", "reason")

        content = captured_snap.get("content", "")
        assert "habit_pending" in content, (
            "_compose_layer2 snap_summary must include 'habit_pending'"
        )
        assert "Omega-3" in content, (
            "_compose_layer2 snap_summary must serialize the habit_pending list"
        )

    def test_habit_pending_key_in_jobs_dict(self):
        """core/autonomous.py source must contain 'habit_pending' in the jobs dict."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        assert '"habit_pending"' in src, (
            "core/autonomous.py jobs dict must include the 'habit_pending' key (D-15)"
        )

    def test_gather_habit_adherence_defined_in_autonomous(self):
        """core/autonomous.py must define _gather_habit_adherence."""
        import core.autonomous as auto
        assert hasattr(auto, "_gather_habit_adherence"), (
            "_gather_habit_adherence not found in core.autonomous"
        )


class TestRecoveryDeviationSignal:
    """Recovery-deviation snapshot key: gather sentinel, triage/compose parity,
    and the Layer-0 gate waking only when flags fired."""

    _RECOVERY = {
        "flags": ["hrv_low"], "hrv_overnight": 52.0, "hrv_baseline_7d": 61.0,
        "hrv_deviation_pct": -14.8, "days_of_data": 7,
    }

    def _situation(self, recovery):
        return {
            "calendar": [],
            "ticktick_overdue": [],
            "unread_email_count": 0,
            "due_followups": [],
            "hours_since_contact": 2.0,
            "recent_journal_digest": "",
            "self_state": {},
            "today_outreach_log": [],
            "now_context": {},
            "meals_since_last_tick": [],
            "training_status": {},
            "acwr": {"ratio": None},
            "habit_pending": [],
            "recovery": recovery,
        }

    def test_is_empty_signals_false_when_recovery_flags(self):
        import core.autonomous as auto
        assert auto._is_empty_signals(self._situation(self._RECOVERY)) is False

    def test_is_empty_signals_true_when_recovery_empty(self):
        import core.autonomous as auto
        assert auto._is_empty_signals(self._situation({})) is True

    def test_triage_prompt_includes_recovery(self):
        import core.autonomous as auto
        prompt = auto._build_triage_prompt(self._situation(self._RECOVERY), "")
        assert '"recovery"' in prompt
        assert "hrv_low" in prompt

    def test_compose_layer2_includes_recovery(self):
        import core.autonomous as auto

        fake_orchestrator = MagicMock()
        fake_orchestrator.render_smart_system.side_effect = lambda t: t
        captured = {}

        def _capture(messages, smart_sys, worker_sys):
            captured["content"] = messages[0]["content"]
            return "ok"

        fake_orchestrator._run_smart_loop.side_effect = _capture
        with patch.object(auto, "_get_orchestrator", return_value=fake_orchestrator):
            auto._compose_layer2(self._situation(self._RECOVERY), "draft", "reason")
        assert '"recovery"' in captured.get("content", "")
        assert "hrv_low" in captured.get("content", "")

    def test_gather_recovery_sentinel_on_failure(self):
        import core.autonomous as auto
        with patch(
            "core.recovery_metrics.get_recovery_deviation",
            side_effect=RuntimeError("pg down"),
        ):
            assert auto._gather_recovery() == {}

    def test_gather_recovery_empty_dict_when_no_deviation(self):
        import core.autonomous as auto
        with patch(
            "core.recovery_metrics.get_recovery_deviation", return_value=None,
        ):
            assert auto._gather_recovery() == {}


# ---------------------------------------------------------------------------
# Training evidence — today's completed-training ground truth in the snapshot
# (evidence-first workout follow-ups; context, never a trigger)
# ---------------------------------------------------------------------------


class TestTrainingEvidence:
    """_gather_training_evidence + snapshot parity across triage and both
    Layer-2 composes, so no proactive path can ask about a workout without
    seeing whether it actually happened."""

    _EVIDENCE = {
        "training_log_today": [
            {"slot": "AM", "type": "run", "planned": True, "completed": True,
             "skipped_reason": None, "source": "garmin"},
        ],
        "strength_today": [],
        "runs_today": [
            {"type": "running", "distance_m": 8000, "duration_sec": 2400,
             "avg_pace_sec_per_km": 300.0},
        ],
    }

    def test_gather_compacts_store_docs(self, fixed_now, monkeypatch):
        """Full store docs (per-set / per-lap detail) are reduced to the
        compact prompt-safe shape — heavy fields must never leak."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        tls = MagicMock()
        tls.get_by_date.return_value = [{
            "doc_id": "2026-07-10_AM", "date": "2026-07-10", "slot": "AM",
            "type": "run", "planned": True, "completed": True,
            "skipped_reason": None, "rpe": 6, "feel": "good",
            "source": "garmin", "garmin_activity_id": "123",
        }]
        sss = MagicMock()
        sss.get_range.return_value = [{
            "workout_id": "w1", "title": "Upper Body", "date": "2026-07-10",
            "start_time": "2026-07-10T18:00:00+03:00", "duration_min": 62,
            "exercises": [{"name": "Bench", "sets": [{"kg": 80, "reps": 5}] * 4}],
            "total_volume_kg": 5400.0,
        }]
        rds = MagicMock()
        rds.get_range.return_value = [{
            "activity_id": "a1", "date": "2026-07-10", "type": "running",
            "distance_m": 8000, "duration_sec": 2400,
            "avg_pace_sec_per_km": 300.0,
            "splits": [{"lap": 1}] * 8, "hr_zones": [1, 2, 3],
        }]
        with patch("memory.firestore_db.TrainingLogStore", return_value=tls), \
             patch("memory.firestore_db.StrengthSessionStore", return_value=sss), \
             patch("memory.firestore_db.RunDetailStore", return_value=rds):
            out = autonomous._gather_training_evidence(fixed_now, "test-project", "(default)")

        assert out["training_log_today"] == [{
            "slot": "AM", "type": "run", "planned": True, "completed": True,
            "skipped_reason": None, "source": "garmin",
        }]
        assert out["strength_today"] == [{
            "title": "Upper Body", "start_time": "2026-07-10T18:00:00+03:00",
            "duration_min": 62, "exercise_count": 1, "total_volume_kg": 5400.0,
        }]
        assert out["runs_today"] == [{
            "type": "running", "distance_m": 8000, "duration_sec": 2400,
            "avg_pace_sec_per_km": 300.0,
        }]
        # Heavy per-set / per-lap fields must not survive compaction.
        blob = json.dumps(out)
        for heavy in ("exercises", "splits", "hr_zones", "sets"):
            assert heavy not in blob, f"heavy field {heavy} leaked into evidence"

    def test_gather_failure_returns_empty_dict(self, fixed_now):
        """Sentinel pattern — a store blowing up must never break the tick."""
        with patch("memory.firestore_db.TrainingLogStore",
                   side_effect=RuntimeError("firestore down")):
            out = autonomous._gather_training_evidence(fixed_now, "p", "(default)")
        assert out == {}

    def test_training_evidence_alone_keeps_signals_empty(self):
        """Context, not a trigger — evidence must never wake tick-brain
        (parity with training_status/acwr)."""
        situation = {
            "ticktick_overdue": [],
            "due_followups": [],
            "calendar": [],
            "meals_since_last_tick": [],
            "training_evidence": self._EVIDENCE,
            "now_context": {},
        }
        assert autonomous._is_empty_signals(situation) is True

    def test_triage_prompt_includes_training_evidence(self):
        situation = {
            "calendar": [], "ticktick_overdue": [], "unread_email_count": 0,
            "due_followups": [], "hours_since_contact": 2.0,
            "recent_journal_digest": "", "self_state": {},
            "today_outreach_log": [], "now_context": {},
            "training_evidence": self._EVIDENCE,
        }
        prompt = autonomous._build_triage_prompt(situation, "")
        assert "training_evidence" in prompt
        assert "runs_today" in prompt

    def _capture_compose(self, fn, *args):
        """Run a compose helper with a fake orchestrator; return the synthetic
        user-message content passed to _run_smart_loop."""
        fake_orchestrator = MagicMock()
        fake_orchestrator.render_smart_system.side_effect = lambda t: t
        captured = {}

        def _capture(messages, smart_sys, worker_sys):
            captured["content"] = messages[0]["content"]
            return "ok"

        fake_orchestrator._run_smart_loop.side_effect = _capture
        with patch.object(autonomous, "_get_orchestrator",
                          return_value=fake_orchestrator):
            fn(*args)
        return captured.get("content", "")

    def test_compose_layer2_snapshot_includes_training_evidence(self, fixed_now):
        sit = _live_situation(fixed_now, training_evidence=self._EVIDENCE)
        content = self._capture_compose(
            autonomous._compose_layer2, sit, "draft", "reason",
        )
        assert '"training_evidence"' in content
        assert "runs_today" in content
        # The compose layer must also carry the clock (was triage-only).
        assert "Time context:" in content
        assert (sit["now_context"]["now_local"] or "") in content

    def test_compose_followup_layer2_includes_training_evidence(self, fixed_now):
        """The smoking gun — the follow-up compose snapshot must carry the
        evidence, otherwise the brain asks about workouts that never happened."""
        fu = {"id": "fu1", "due_at": "2026-07-10T10:00:00+00:00",
              "note": "ask how the run went", "defer_count": 0}
        sit = _live_situation(fixed_now, training_evidence=self._EVIDENCE)
        content = self._capture_compose(
            autonomous._compose_followup_layer2, fu, sit,
        )
        assert '"training_evidence"' in content
        assert "runs_today" in content
        # The follow-up compose must also carry the clock (was triage-only).
        assert "Time context:" in content
        assert (sit["now_context"]["now_local"] or "") in content

    def test_format_now_block_shared_by_triage_and_composes(self, fixed_now):
        """One helper, three call sites — the triage prompt must render the
        exact same time block the composes get (no drift)."""
        sit = _live_situation(fixed_now)
        block = autonomous._format_now_block(sit)
        assert f"now: {sit['now_context']['now_local']}" in block
        assert autonomous._build_triage_prompt(sit, "").count(block) == 1


# ---------------------------------------------------------------------------
# Follow-up cancel action — evidence-first escape hatch
# ---------------------------------------------------------------------------


class TestFollowupCancel:
    """Layer 2 may drop a moot follow-up (e.g. a workout that demonstrably
    didn't happen) instead of sending a false check-in or deferring forever."""

    def test_parse_followup_action_cancel(self):
        text = 'not needed, no run logged\n```json {"action": "cancel"}```'
        action, polished = autonomous._parse_followup_action(text)
        assert action == "cancel"
        assert polished == "not needed, no run logged"

    def test_parse_followup_action_unknown_defaults_to_send(self):
        text = 'body\n```json {"action": "explode"}```'
        action, _ = autonomous._parse_followup_action(text)
        assert action == "send"

    def test_cancel_calls_store_cancel_and_does_not_send(self, mock_bot, fixed_now):
        fu = {
            "id": "fu-cancel",
            "due_at": (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(),
            "note": "ask how the run went",
            "defer_count": 0,
        }
        sit = _live_situation(fixed_now, due_followups=[fu])
        fs_instance = MagicMock()
        ols_instance = MagicMock()

        with patch.object(autonomous, "_compose_followup_layer2",
                          return_value='```json {"action": "cancel"}```'), \
             patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
             patch("memory.firestore_db.FollowupStore", return_value=fs_instance), \
             patch("memory.firestore_db.OutreachLogStore", return_value=ols_instance):
            outcome = asyncio.run(
                autonomous._compose_followup(mock_bot, fu, sit, fixed_now)
            )

        assert outcome == "cancelled"
        fs_instance.cancel.assert_called_once_with("fu-cancel")
        send.assert_not_called()
        fs_instance.mark_done.assert_not_called()
        fs_instance.defer.assert_not_called()
        # D-10 symmetry — nothing sent, nothing logged.
        ols_instance.append.assert_not_called()

    def test_cancel_not_overridden_by_force_fire(self, mock_bot, fixed_now):
        """Force-fire (D-14) exists to stop eternal DEFERRAL — a reasoned
        cancel at defer_count >= 3 must still cancel, not send."""
        fu = {
            "id": "fu-cancel-3",
            "due_at": (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(),
            "note": "ask how the run went",
            "defer_count": 3,
        }
        sit = _live_situation(fixed_now, due_followups=[fu])
        fs_instance = MagicMock()

        with patch.object(autonomous, "_compose_followup_layer2",
                          return_value='```json {"action": "cancel"}```'), \
             patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
             patch("memory.firestore_db.FollowupStore", return_value=fs_instance):
            outcome = asyncio.run(
                autonomous._compose_followup(mock_bot, fu, sit, fixed_now)
            )

        assert outcome == "cancelled"
        fs_instance.cancel.assert_called_once_with("fu-cancel-3")
        send.assert_not_called()

    def test_cancel_store_failure_returns_failed(self, mock_bot, fixed_now):
        """Firestore error during cancel → 'failed' (mirrors the defer branch)."""
        fu = {
            "id": "fu-cancel-err",
            "due_at": (fixed_now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(),
            "note": "n",
            "defer_count": 0,
        }
        sit = _live_situation(fixed_now, due_followups=[fu])
        fs_instance = MagicMock()
        fs_instance.cancel.side_effect = RuntimeError("firestore down")

        with patch.object(autonomous, "_compose_followup_layer2",
                          return_value='```json {"action": "cancel"}```'), \
             patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
             patch("memory.firestore_db.FollowupStore", return_value=fs_instance):
            outcome = asyncio.run(
                autonomous._compose_followup(mock_bot, fu, sit, fixed_now)
            )

        assert outcome == "failed"
        send.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 31 Plan 04 (DIR-03) — standing directives reach the autonomous tick:
# context-only gather (never a trigger) + Step-0 triage veto + both composes.
# ---------------------------------------------------------------------------


class TestStandingDirectivesGather:
    """_gather_standing_directives: sentinel-on-failure, context-only in the
    empty gate, present in gather_situation's assembled dict."""

    _DIRECTIVES = [
        {
            "id": "d1",
            "text": "stop nagging about training while I'm in France",
            "origin": "user_chat",
            "expires_at": None,
            "condition_text": "back from France",
        },
    ]

    def _situation(self, standing_directives):
        return {
            "calendar": [],
            "ticktick_overdue": [],
            "unread_email_count": 0,
            "due_followups": [],
            "hours_since_contact": None,
            "recent_journal_digest": "",
            "self_state": {},
            "today_outreach_log": [],
            "now_context": {},
            "meals_since_last_tick": [],
            "training_status": {},
            "acwr": {"ratio": None},
            "habit_pending": [],
            "recovery": {},
            "standing_directives": standing_directives,
        }

    def test_gather_returns_active_directives(self):
        sds_instance = MagicMock()
        sds_instance.list_active.return_value = self._DIRECTIVES
        with patch("memory.firestore_db.StandingDirectiveStore", return_value=sds_instance):
            result = autonomous._gather_standing_directives("proj", "db")
        assert result == self._DIRECTIVES

    def test_gather_returns_empty_list_on_store_failure(self):
        """The gather must never raise — sentinel [] on any Firestore error."""
        with patch(
            "memory.firestore_db.StandingDirectiveStore",
            side_effect=RuntimeError("firestore down"),
        ):
            result = autonomous._gather_standing_directives("proj", "db")
        assert result == []

    def test_gather_job_key_appears_in_assembled_situation(self, fixed_now):
        """The 'standing_directives' key must be present in gather_situation's output."""
        with patch("core.tools._get_calendar_tool") as get_cal, \
             patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
             patch("core.tools._get_gmail_tool") as get_gm, \
             patch("memory.firestore_db.FollowupStore") as fs_cls, \
             patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
             patch("memory.firestore_db.JournalStore"), \
             patch("memory.firestore_db.SelfStateStore"), \
             patch("memory.firestore_db.OutreachLogStore"), \
             patch("memory.firestore_db.StandingDirectiveStore") as sds_cls:
            get_cal.return_value.list_events.return_value = []
            get_gm.return_value.list_unread.return_value = []
            fs_cls.return_value.list_due.return_value = []
            conv_cls.return_value.get_last_user_timestamp.return_value = None
            sds_cls.return_value.list_active.return_value = self._DIRECTIVES

            out = autonomous.gather_situation(fixed_now)

        assert "standing_directives" in out
        assert out["standing_directives"] == self._DIRECTIVES

    def test_is_empty_signals_true_with_only_active_directives(self):
        """Pitfall 4 / T-31-04 — an otherwise-empty situation with active
        directives but no other signal must still be empty=True. Directives
        are context, never a Layer-0 trigger — they must NOT wake the free
        tier on their own."""
        situation = self._situation(self._DIRECTIVES)
        assert autonomous._is_empty_signals(situation) is True, (
            "_is_empty_signals must stay True when standing_directives is the "
            "only non-empty signal (context-only, Pitfall 4)"
        )

    def test_is_empty_signals_true_with_no_directives(self):
        situation = self._situation([])
        assert autonomous._is_empty_signals(situation) is True


class TestStandingDirectivesTriageAndCompose:
    """Step-0 STANDING ORDERS veto reaches the triage prompt; parity keys
    reach both Layer-2 composes (Plan 04, DIR-03)."""

    _DIRECTIVES = [
        {
            "id": "d1",
            "text": "stop nagging about training while I'm in France",
            "origin": "user_chat",
            "expires_at": None,
            "condition_text": "back from France",
        },
    ]

    def _situation(self, standing_directives):
        return _live_situation(
            datetime(2026, 5, 21, 10, 20, tzinfo=_TZ),
            standing_directives=standing_directives,
        )

    def test_triage_prompt_includes_directive_text_when_active(self):
        prompt = autonomous._build_triage_prompt(self._situation(self._DIRECTIVES), "")
        assert "stop nagging about training while I'm in France" in prompt
        assert "Active standing directives:" in prompt

    def test_triage_prompt_omits_directive_block_when_none_active(self):
        prompt = autonomous._build_triage_prompt(self._situation([]), "")
        assert "(none active)" in prompt
        assert "stop nagging" not in prompt

    def test_compose_layer2_includes_standing_directives_key(self):
        fake_orchestrator = MagicMock()
        fake_orchestrator.render_smart_system.side_effect = lambda t: t
        captured = {}

        def _capture(messages, smart_sys, worker_sys):
            captured["content"] = messages[0]["content"]
            return "ok"

        fake_orchestrator._run_smart_loop.side_effect = _capture
        with patch.object(autonomous, "_get_orchestrator", return_value=fake_orchestrator):
            autonomous._compose_layer2(self._situation(self._DIRECTIVES), "draft", "reason")

        assert '"standing_directives"' in captured.get("content", "")
        assert "stop nagging about training while I'm in France" in captured.get("content", "")

    def test_compose_followup_layer2_includes_standing_directives_key(self):
        fake_orchestrator = MagicMock()
        fake_orchestrator.render_smart_system.side_effect = lambda t: t
        captured = {}

        def _capture(messages, smart_sys, worker_sys):
            captured["content"] = messages[0]["content"]
            return "ok"

        fake_orchestrator._run_smart_loop.side_effect = _capture
        followup = {"id": "fu1", "due_at": "2026-05-21T07:20:00Z", "note": "check in", "defer_count": 0}
        with patch.object(autonomous, "_get_orchestrator", return_value=fake_orchestrator):
            autonomous._compose_followup_layer2(followup, self._situation(self._DIRECTIVES))

        assert '"standing_directives"' in captured.get("content", "")
        assert "stop nagging about training while I'm in France" in captured.get("content", "")


# ---------------------------------------------------------------------------
# Phase 32 Plan 07 (MEM-04/MEM-05) — conversation_tail + training_reality
# gathers, context-only invariant, and triage/compose renders.
# ---------------------------------------------------------------------------


class TestConversationTailGather:
    """_gather_conversation_tail: sentinel-on-failure, widest window fetched
    once (48h/<=40 msgs), context-only in the empty gate."""

    _TAIL = [
        {"role": "user", "content": "how's the training block looking", "ts": "2026-05-21T06:00:00+00:00"},
        {"role": "assistant", "content": "on track, easy run this morning", "ts": "2026-05-21T06:01:00+00:00"},
    ]

    def test_gather_conversation_tail_returns_recent_window(self, fixed_now, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
        store = MagicMock()
        store.get_recent_window.return_value = self._TAIL
        with patch(
            "memory.firestore_conversation.FirestoreConversationStore",
            return_value=store,
        ):
            result = autonomous._gather_conversation_tail(fixed_now, "proj", "db")
        store.get_recent_window.assert_called_once_with(
            123456789, hours=48, max_messages=40,
        )
        assert result == self._TAIL

    def test_gather_conversation_tail_returns_empty_list_on_store_failure(self, fixed_now, monkeypatch):
        """The gather must never raise — sentinel [] on any Firestore error."""
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
        with patch(
            "memory.firestore_conversation.FirestoreConversationStore",
            side_effect=RuntimeError("firestore down"),
        ):
            result = autonomous._gather_conversation_tail(fixed_now, "proj", "db")
        assert result == []

    def test_gather_conversation_tail_env_unset_returns_empty_without_querying(self, fixed_now, monkeypatch):
        monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
        with patch(
            "memory.firestore_conversation.FirestoreConversationStore",
        ) as store_cls:
            result = autonomous._gather_conversation_tail(fixed_now, "proj", "db")
        assert result == []
        store_cls.return_value.get_recent_window.assert_not_called()

    def test_is_empty_signals_true_with_only_conversation_tail(self):
        """MEM-05 (T-32-14) — a non-trivial conversation_tail alone must not
        wake the free tier."""
        situation = {
            "calendar": [], "ticktick_overdue": [], "due_followups": [],
            "meals_since_last_tick": [], "habit_pending": [], "recovery": {},
            "now_context": {},
            "conversation_tail": self._TAIL,
        }
        assert autonomous._is_empty_signals(situation) is True


class TestTrainingRealityGather:
    """_gather_training_reality: sentinel-on-failure, reconciled per-date
    dict via build_training_reality, context-only in the empty gate."""

    def test_gather_training_reality_produces_reconciled_dict(self, fixed_now, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        planned = {"weekday": "Thursday", "am": {"modality": "run"}, "pm": {}}
        tls = MagicMock()
        tls.get_by_date.return_value = [{
            "slot": "am", "type": "run", "planned": True, "completed": True,
            "skipped_reason": None, "source": "garmin",
        }]
        sss = MagicMock()
        sss.get_range.return_value = []
        rds = MagicMock()
        rds.get_range.return_value = [{
            "type": "running", "distance_m": 8000, "duration_sec": 2400,
            "avg_pace_sec_per_km": 300.0,
        }]
        cal = MagicMock()
        cal.list_events.return_value = []

        with patch("core.training_checkin.planned_sessions_for", return_value=planned), \
             patch("memory.firestore_db.TrainingLogStore", return_value=tls), \
             patch("memory.firestore_db.StrengthSessionStore", return_value=sss), \
             patch("memory.firestore_db.RunDetailStore", return_value=rds), \
             patch("core.tools._get_calendar_tool", return_value=cal):
            out = autonomous._gather_training_reality(fixed_now, "test-project", "(default)")

        today_iso = fixed_now.astimezone(_TZ).date().isoformat()
        assert set(out.keys()) == {
            (fixed_now.astimezone(_TZ).date() + timedelta(days=off - 3)).isoformat()
            for off in range(5)
        }
        assert out[today_iso]["slots"].get("am") == "done"
        assert out[today_iso]["planned"] == planned

    def test_gather_training_reality_returns_empty_dict_on_failure(self, fixed_now):
        """Sentinel pattern — a store blowing up must never break the tick."""
        with patch(
            "core.training_checkin.planned_sessions_for",
            side_effect=RuntimeError("firestore down"),
        ):
            out = autonomous._gather_training_reality(fixed_now, "proj", "(default)")
        assert out == {}

    def test_gather_training_reality_no_second_calendar_call_for_non_today_dates(self, fixed_now, monkeypatch):
        """Reuses _gather_calendar's TODAY events only — no per-date calendar
        API calls for the other 4 reconciliation-window dates."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        cal = MagicMock()
        cal.list_events.return_value = [{
            "id": "evt1", "summary": "Easy Run",
            "start": fixed_now.replace(hour=7).isoformat(),
            "end": fixed_now.replace(hour=8).isoformat(),
        }]
        with patch("core.training_checkin.planned_sessions_for", return_value=None), \
             patch("memory.firestore_db.TrainingLogStore", **{"return_value.get_by_date.return_value": []}), \
             patch("memory.firestore_db.StrengthSessionStore", **{"return_value.get_range.return_value": []}), \
             patch("memory.firestore_db.RunDetailStore", **{"return_value.get_range.return_value": []}), \
             patch("core.tools._get_calendar_tool", return_value=cal):
            out = autonomous._gather_training_reality(fixed_now, "test-project", "(default)")
        # Exactly one calendar fetch (for today), reused verbatim.
        assert cal.list_events.call_count == 1
        today_iso = fixed_now.astimezone(_TZ).date().isoformat()
        assert out[today_iso]["calendar"] == cal.list_events.return_value

    def test_is_empty_signals_true_with_only_training_reality(self):
        """MEM-05 (T-32-14) — a non-trivial training_reality alone must not
        wake the free tier."""
        situation = {
            "calendar": [], "ticktick_overdue": [], "due_followups": [],
            "meals_since_last_tick": [], "habit_pending": [], "recovery": {},
            "now_context": {},
            "training_reality": {
                "2026-05-21": {"slots": {"am": "done"}},
            },
        }
        assert autonomous._is_empty_signals(situation) is True


class TestGatherSituationIncludesPhase32Keys:
    """gather_situation's assembled dict must carry both new Phase 32 keys."""

    def test_conversation_tail_and_training_reality_keys_present(self, fixed_now, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
        with patch("core.tools._get_calendar_tool") as get_cal, \
             patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
             patch("core.tools._get_gmail_tool") as get_gm, \
             patch("memory.firestore_db.FollowupStore") as fs_cls, \
             patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
             patch("memory.firestore_db.JournalStore"), \
             patch("memory.firestore_db.SelfStateStore"), \
             patch("memory.firestore_db.OutreachLogStore"), \
             patch("core.training_checkin.planned_sessions_for", return_value=None), \
             patch("memory.firestore_db.TrainingLogStore", **{"return_value.get_by_date.return_value": []}), \
             patch("memory.firestore_db.StrengthSessionStore", **{"return_value.get_range.return_value": []}), \
             patch("memory.firestore_db.RunDetailStore", **{"return_value.get_range.return_value": []}):
            get_cal.return_value.list_events.return_value = []
            get_gm.return_value.list_unread.return_value = []
            fs_cls.return_value.list_due.return_value = []
            conv_cls.return_value.get_last_user_timestamp.return_value = None
            conv_cls.return_value.get_recent_window.return_value = TestConversationTailGather._TAIL

            out = autonomous.gather_situation(fixed_now)

        assert "conversation_tail" in out
        assert out["conversation_tail"] == TestConversationTailGather._TAIL
        assert "training_reality" in out
        assert isinstance(out["training_reality"], dict)
        assert len(out["training_reality"]) == 5


class TestConversationTailAndTrainingRealityRenders:
    """Task 3 (MEM-04/MEM-05): triage-tight vs paid-compose-wide renders for
    conversation_tail and training_reality."""

    def _tail(self, n, chars_each, now):
        tail = []
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"msg{i} " * 100  # deliberately long, needs truncation
            content = content[:chars_each]
            ts = (now - timedelta(minutes=(n - i) * 30)).astimezone(timezone.utc).isoformat()
            tail.append({"role": role, "content": content, "ts": ts})
        return tail

    def _training_reality(self, today_iso, tomorrow_iso, yesterday_iso):
        return {
            yesterday_iso: {
                "planned": {}, "calendar": [],
                "evidence": {
                    "strength_today": [{"title": "Upper Body", "total_volume_kg": 3120}],
                    "runs_today": [],
                },
                "slots": {"am": "done"},
            },
            today_iso: {
                "planned": {}, "calendar": [],
                "evidence": {"strength_today": [], "runs_today": [
                    {"type": "run", "distance_m": 8000, "avg_pace_sec_per_km": 300},
                ]},
                "slots": {"am": "done", "pm": "planned"},
            },
            tomorrow_iso: {
                "planned": {}, "calendar": [],
                "evidence": {},
                "slots": {"am": "planned"},
            },
        }

    def test_triage_render_trims_conversation_tail_to_caps(self, fixed_now):
        """Triage-tight render: <=15 msgs, <=240 chars each, only last 24h."""
        # 20 raw messages (over the 15-msg cap), each far over 240 chars raw,
        # plus one message older than 24h that must be dropped.
        tail = self._tail(20, 400, fixed_now)
        stale = {
            "role": "user", "content": "ancient message",
            "ts": (fixed_now - timedelta(hours=30)).astimezone(timezone.utc).isoformat(),
        }
        sit = _live_situation(fixed_now, conversation_tail=[stale] + tail)
        prompt = autonomous._build_triage_prompt(sit, "")

        assert "Recent conversation with Amit" in prompt
        assert "ancient message" not in prompt, "messages older than 24h must be trimmed"
        # No raw untruncated 400-char filler line should appear verbatim.
        rendered_block = prompt.split("Recent conversation with Amit")[1].split("Training reality")[0]
        for line in rendered_block.splitlines():
            content_only = line.split(": ", 1)[-1]
            assert len(content_only) <= 240, f"triage tail line exceeds 240 chars: {len(content_only)}"
        # At most 15 rendered message lines (role: content).
        message_lines = [
            ln for ln in rendered_block.splitlines() if ln.startswith(("user:", "assistant:"))
        ]
        assert len(message_lines) <= 15

    def test_triage_render_training_reality_today_tomorrow_only_no_evidence_detail(self, fixed_now):
        """Triage-tight render: today+tomorrow only, terminal status strings,
        NO evidence detail (Research Open Question 2)."""
        today_iso = fixed_now.astimezone(_TZ).date().isoformat()
        tomorrow_iso = (fixed_now.astimezone(_TZ).date() + timedelta(days=1)).isoformat()
        yesterday_iso = (fixed_now.astimezone(_TZ).date() - timedelta(days=1)).isoformat()
        reality = self._training_reality(today_iso, tomorrow_iso, yesterday_iso)
        sit = _live_situation(fixed_now, training_reality=reality)

        prompt = autonomous._build_triage_prompt(sit, "")

        assert "Training reality (today + tomorrow" in prompt
        assert today_iso in prompt
        assert tomorrow_iso in prompt
        # Yesterday must NOT appear in the tight render (today+tomorrow only).
        tr_block = prompt.split("Training reality")[1]
        assert yesterday_iso not in tr_block
        # Terminal status strings only — no evidence detail (session titles/volumes/pace).
        assert "Upper Body" not in tr_block
        assert "3120" not in tr_block
        assert "8000" not in tr_block
        # Status strings ARE present.
        assert "done" in tr_block
        assert "planned" in tr_block

    def test_triage_render_training_reality_empty_when_no_data(self, fixed_now):
        sit = _live_situation(fixed_now, training_reality={})
        prompt = autonomous._build_triage_prompt(sit, "")
        assert "(no training reality data)" in prompt

    def _capture_compose(self, fn, *args):
        fake_orchestrator = MagicMock()
        fake_orchestrator.render_smart_system.side_effect = lambda t: t
        captured = {}

        def _capture(messages, smart_sys, worker_sys):
            captured["content"] = messages[0]["content"]
            return "ok"

        fake_orchestrator._run_smart_loop.side_effect = _capture
        with patch.object(autonomous, "_get_orchestrator", return_value=fake_orchestrator):
            fn(*args)
        return captured.get("content", "")

    def test_compose_layer2_renders_wide_training_reality_with_evidence_detail(self, fixed_now):
        """Paid compose render: full today-3d..tomorrow window WITH evidence
        detail (session titles/volumes/pace) — the opposite discipline from
        triage."""
        today_iso = fixed_now.astimezone(_TZ).date().isoformat()
        tomorrow_iso = (fixed_now.astimezone(_TZ).date() + timedelta(days=1)).isoformat()
        yesterday_iso = (fixed_now.astimezone(_TZ).date() - timedelta(days=1)).isoformat()
        reality = self._training_reality(today_iso, tomorrow_iso, yesterday_iso)
        sit = _live_situation(fixed_now, training_reality=reality)

        content = self._capture_compose(autonomous._compose_layer2, sit, "draft", "reason")

        assert "Training reality (today-3d..tomorrow" in content
        # Wide render includes the earlier date (yesterday) too.
        assert yesterday_iso in content
        # Evidence detail is present (unlike the triage-tight render).
        assert "Upper Body" in content
        assert "3120" in content

    def test_compose_layer2_renders_wide_conversation_tail(self, fixed_now):
        """Paid compose render: 48h/<=40 msgs, no 240-char truncation."""
        tail = self._tail(3, 400, fixed_now)  # each entry truncated to 400 (< no-cap concern)
        sit = _live_situation(fixed_now, conversation_tail=tail)
        content = self._capture_compose(autonomous._compose_layer2, sit, "draft", "reason")
        assert "Recent conversation with Amit (last 48h, up to 40 messages)" in content
        # None of the wide-render lines are hard-truncated at 240 chars — the
        # fixture messages are 400 chars so this asserts no premature cut.
        wide_block = content.split("Recent conversation with Amit")[1].split("Training reality")[0]
        message_lines = [
            ln for ln in wide_block.splitlines() if ln.startswith(("user:", "assistant:"))
        ]
        assert any(len(ln.split(": ", 1)[-1]) > 240 for ln in message_lines), (
            "wide compose render must not truncate at the triage 240-char cap"
        )

    def test_compose_followup_layer2_renders_wide_training_reality(self, fixed_now):
        today_iso = fixed_now.astimezone(_TZ).date().isoformat()
        tomorrow_iso = (fixed_now.astimezone(_TZ).date() + timedelta(days=1)).isoformat()
        yesterday_iso = (fixed_now.astimezone(_TZ).date() - timedelta(days=1)).isoformat()
        reality = self._training_reality(today_iso, tomorrow_iso, yesterday_iso)
        sit = _live_situation(fixed_now, training_reality=reality)
        followup = {"id": "fu1", "due_at": "2026-05-21T07:20:00Z", "note": "check in", "defer_count": 0}

        content = self._capture_compose(autonomous._compose_followup_layer2, followup, sit)

        assert "Training reality (today-3d..tomorrow" in content
        assert yesterday_iso in content
        assert "Upper Body" in content


# ---------------------------------------------------------------------------
# Phase 32 Plan 08 (MEM-07) — derive_current_location + _gather_location
# (context-only) + the nightly/morning weather repointing + location_ask
# wiring (Task 2's call-site changes live in core/nightly_review.py and
# core/morning_briefing.py; this file only exercises the shared derivation
# heuristic and the prompt-doc grep, per the plan's <files> list).
# ---------------------------------------------------------------------------


class TestDeriveCurrentLocationHeuristic:
    """derive_current_location: pure Pattern 7 heuristic (D-06) — conservative
    under-detect, home-silent default, never guesses on conflict or an
    unclear trip-end."""

    def test_derive_current_location_no_signal_returns_home_silently(self):
        result = autonomous.derive_current_location([], [])
        assert result == {"location": "Tel Aviv"}

    def test_derive_current_location_calendar_signal_overrides_home(self):
        events = [{"summary": "Client meeting", "location": "Paris, France"}]
        result = autonomous.derive_current_location(events, [])
        assert result == {"location": "Paris, France"}

    def test_derive_current_location_tel_aviv_calendar_location_stays_home(self):
        """A calendar event location that names Tel Aviv itself is NOT a
        travel signal — must not be mistaken for an override."""
        events = [{"summary": "Standup", "location": "Tel Aviv HQ"}]
        result = autonomous.derive_current_location(events, [])
        assert result == {"location": "Tel Aviv"}

    def test_derive_current_location_directive_alone_is_ambiguous(self):
        """No calendar corroboration — unclear trip-end, must ask not guess."""
        directives = [{
            "id": "d1",
            "text": "stop nagging about training while I'm in France",
            "condition_text": "back from France",
        }]
        result = autonomous.derive_current_location([], directives)
        assert result == {"ambiguous": True, "candidate": "France"}

    def test_derive_current_location_calendar_and_directive_agree_resolves(self):
        events = [{"summary": "Dinner", "location": "Paris"}]
        directives = [{"id": "d1", "text": "while I'm in Paris, keep it brief"}]
        result = autonomous.derive_current_location(events, directives)
        assert result == {"location": "Paris"}

    def test_derive_current_location_calendar_and_directive_conflict_is_ambiguous(self):
        events = [{"summary": "Meeting", "location": "London"}]
        directives = [{"id": "d1", "text": "while I'm in Paris, keep it brief"}]
        result = autonomous.derive_current_location(events, directives)
        assert result == {"ambiguous": True, "candidate": "London"}

    def test_derive_current_location_never_raises_on_malformed_input(self):
        assert autonomous.derive_current_location(None, None) == {"location": "Tel Aviv"}
        assert autonomous.derive_current_location(
            [{"summary": "no location field"}], [{"not": "a directive text field"}]
        ) == {"location": "Tel Aviv"}

    def test_derive_current_location_directive_place_name_capped_at_three_words(self):
        """Conservative over-capture guard — a longer sentence fragment after
        the place name doesn't get treated as part of the literal city."""
        directives = [{"id": "d1", "text": "while I'm in New York for a work trip"}]
        result = autonomous.derive_current_location([], directives)
        assert result["ambiguous"] is True
        # The stop-word split on " for " must cut the capture before "for".
        assert result["candidate"] == "New York"


class TestGatherCurrentLocationContextOnly:
    """_gather_location wraps the pure heuristic over already-gathered
    situation values (no new API call), sentinel-on-failure, context-only in
    the Layer-0 empty gate (T-32-17)."""

    def test_gather_current_location_derives_from_situation(self):
        situation = {
            "calendar": [{"summary": "Client visit", "location": "Paris"}],
            "standing_directives": [],
        }
        assert autonomous._gather_location(situation) == {"location": "Paris"}

    def test_gather_current_location_home_default_when_situation_empty(self):
        assert autonomous._gather_location({}) == {"location": "Tel Aviv"}

    def test_gather_current_location_never_raises_returns_home_sentinel(self, monkeypatch):
        def _boom(*a, **kw):
            raise RuntimeError("heuristic exploded")
        monkeypatch.setattr(autonomous, "derive_current_location", _boom)
        result = autonomous._gather_location({"calendar": [], "standing_directives": []})
        assert result == {"location": "Tel Aviv"}

    def test_is_empty_signals_true_with_only_current_location(self):
        """MEM-05/MEM-07 (T-32-17) — a resolved (non-home) current_location
        alone must not wake the free tier; deriving it is context-only."""
        situation = {
            "calendar": [], "ticktick_overdue": [], "due_followups": [],
            "meals_since_last_tick": [], "habit_pending": [], "recovery": {},
            "now_context": {},
            "location": {"location": "Paris"},
        }
        assert autonomous._is_empty_signals(situation) is True

    def test_is_empty_signals_true_with_only_ambiguous_current_location(self):
        """Even an AMBIGUOUS derivation must not trigger the free tier — the
        ask itself only fires through the nightly compose payload."""
        situation = {
            "calendar": [], "ticktick_overdue": [], "due_followups": [],
            "meals_since_last_tick": [], "habit_pending": [], "recovery": {},
            "now_context": {},
            "location": {"ambiguous": True, "candidate": "Paris"},
        }
        assert autonomous._is_empty_signals(situation) is True

    def test_gather_situation_includes_current_location_key(self, fixed_now, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
        with patch("core.tools._get_calendar_tool") as get_cal, \
             patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
             patch("core.tools._get_gmail_tool") as get_gm, \
             patch("memory.firestore_db.FollowupStore") as fs_cls, \
             patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
             patch("memory.firestore_db.JournalStore"), \
             patch("memory.firestore_db.SelfStateStore"), \
             patch("memory.firestore_db.OutreachLogStore"), \
             patch("memory.firestore_db.StandingDirectiveStore") as sds_cls, \
             patch("core.training_checkin.planned_sessions_for", return_value=None), \
             patch("memory.firestore_db.TrainingLogStore", **{"return_value.get_by_date.return_value": []}), \
             patch("memory.firestore_db.StrengthSessionStore", **{"return_value.get_range.return_value": []}), \
             patch("memory.firestore_db.RunDetailStore", **{"return_value.get_range.return_value": []}):
            get_cal.return_value.list_events.return_value = []
            get_gm.return_value.list_unread.return_value = []
            fs_cls.return_value.list_due.return_value = []
            conv_cls.return_value.get_last_user_timestamp.return_value = None
            sds_cls.return_value.list_active.return_value = []

            out = autonomous.gather_situation(fixed_now)

        assert "location" in out
        assert out["location"] == {"location": "Tel Aviv"}

    def test_gather_situation_current_location_reflects_calendar_travel_signal(self, fixed_now, monkeypatch):
        """End-to-end through the real pool: a today calendar event with a
        travel location resolves into gather_situation's assembled dict."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
        with patch("core.tools._get_calendar_tool") as get_cal, \
             patch("memory.firestore_db.TaskStore", **{"return_value.get_overdue.return_value": []}), \
             patch("core.tools._get_gmail_tool") as get_gm, \
             patch("memory.firestore_db.FollowupStore") as fs_cls, \
             patch("memory.firestore_conversation.FirestoreConversationStore") as conv_cls, \
             patch("memory.firestore_db.JournalStore"), \
             patch("memory.firestore_db.SelfStateStore"), \
             patch("memory.firestore_db.OutreachLogStore"), \
             patch("memory.firestore_db.StandingDirectiveStore") as sds_cls, \
             patch("core.training_checkin.planned_sessions_for", return_value=None), \
             patch("memory.firestore_db.TrainingLogStore", **{"return_value.get_by_date.return_value": []}), \
             patch("memory.firestore_db.StrengthSessionStore", **{"return_value.get_range.return_value": []}), \
             patch("memory.firestore_db.RunDetailStore", **{"return_value.get_range.return_value": []}):
            get_cal.return_value.list_events.return_value = [
                {"summary": "Conference", "location": "Berlin"}
            ]
            get_gm.return_value.list_unread.return_value = []
            fs_cls.return_value.list_due.return_value = []
            conv_cls.return_value.get_last_user_timestamp.return_value = None
            sds_cls.return_value.list_active.return_value = []

            out = autonomous.gather_situation(fixed_now)

        assert out["location"] == {"location": "Berlin"}
        # CONTEXT only — a resolved travel location alone must not flip empty.
        assert out["empty"] is True
