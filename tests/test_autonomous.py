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


_install_firestore_mock()


# Imported AFTER the firestore mock is installed.
import core.autonomous as autonomous  # noqa: E402


_TZ = ZoneInfo("Asia/Jerusalem")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_orchestrator_singleton():
    """Reset the module singleton between tests (BLOCKER 5a state hygiene)."""
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
    from mcp_tools.ticktick_tool import get_today_tasks       # noqa: F401
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
         patch("mcp_tools.ticktick_tool.get_today_tasks", return_value={"overdue": []}), \
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

    # All 8 keys present + now_context + empty.
    for k in (
        "calendar", "ticktick_overdue", "unread_email_count", "due_followups",
        "hours_since_contact", "recent_journal_digest", "self_state",
        "today_outreach_log", "now_context", "empty",
    ):
        assert k in out, f"key {k} missing"
    # Calendar fallback to []; the rest still gathered.
    assert out["calendar"] == []
    assert out["ticktick_overdue"] == []


def test_gather_situation_now_context_block(fixed_now):
    """D-08 — now_context contains the 5 required keys; tick_total == 43."""
    with patch("core.tools._get_calendar_tool"), \
         patch("mcp_tools.ticktick_tool.get_today_tasks", return_value={"overdue": []}), \
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
         patch("mcp_tools.ticktick_tool.get_today_tasks", return_value={"overdue": []}), \
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
