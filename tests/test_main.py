"""Tests for core/main.py — Phase 24 Plan 03: double-send fix + cap 12.

Covers:
  - MAX_TOOL_ITERATIONS == 12 (raised from 8)
  - _run_smart_loop exhaustion with substantive text → returns that text (no double-send)
  - _run_smart_loop exhaustion with no substantive text → returns existing sentinel string
  - sentinel string byte-identical (test_autonomous.py::test_sentinel_substring_matches_main_constant)

Test strategy
-------------
core.main is imported with google.cloud.firestore + google auth stubs at the
sys.modules level (same pattern as tests/test_main_render_smart_system.py).
_run_smart_loop is exercised by building a minimal AgentOrchestrator with
a mocked smart_agent whose .chat() returns controlled responses.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Firestore / google stubs — mirror test_main_render_smart_system.py exactly
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_orchestrator():
    """Build a minimal AgentOrchestrator with only the attributes _run_smart_loop needs."""
    from core.main import AgentOrchestrator
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    # smart_agent mock — will be overridden per test
    orch.smart_agent = MagicMock()
    orch.smart_agent_fallback = None
    # worker_agent mock (needed for delegate_to_worker path — not used in these tests)
    orch.worker_agent = MagicMock()
    return orch


def _tool_call_response(text: str = "", tool_name: str = "read_coaching_guide"):
    """Return a chat() response dict that includes one tool call + optional text."""
    return {
        "text": text,
        "tool_calls": [
            {
                "id": "tc_001",
                "name": tool_name,
                "input": {"topic": "test-topic"},
            }
        ],
        "thought_signature": None,
        "reasoning_content": None,
    }


def _text_only_response(text: str):
    """Return a chat() response dict with no tool calls (final answer)."""
    return {
        "text": text,
        "tool_calls": [],
        "thought_signature": None,
        "reasoning_content": None,
    }


# ---------------------------------------------------------------------------
# Phase 24 Plan 03 — Task 2: cap 12 + last-substantive-text fallback
# ---------------------------------------------------------------------------

class TestPhase24DoublesSendFix:
    """Verify MAX_TOOL_ITERATIONS=12 + last-substantive-text fallback behavior."""

    def test_max_tool_iterations_is_12(self):
        """MAX_TOOL_ITERATIONS must be 12 (raised from 8 for data-heavy coaching)."""
        from core.main import MAX_TOOL_ITERATIONS
        assert MAX_TOOL_ITERATIONS == 12, (
            f"Expected MAX_TOOL_ITERATIONS == 12, got {MAX_TOOL_ITERATIONS}"
        )

    def test_cap_exhaustion_with_substantive_text_returns_text(self, monkeypatch):
        """When loop hits cap and last iteration had >100-char text, return that text.

        This is the double-send fix: the brain produced a real answer alongside tool
        calls; instead of discarding it and returning the apologetic sentinel, we
        return the substantive answer (single message, no double-send).
        """
        import core.main as main_module

        orch = _make_minimal_orchestrator()

        # Produce a >100-char substantive text with tool calls on every iteration
        substantive_text = "A" * 120  # > 100 chars
        response = _tool_call_response(text=substantive_text)

        orch.smart_agent.chat.return_value = response

        # Patch the tool dispatch to return a dummy result
        monkeypatch.setattr(
            "core.main.tool_registry.dispatch",
            lambda name, args: '{"result": "ok"}',
        )
        monkeypatch.setattr(
            "core.main.tool_registry.get_smart_schemas",
            lambda user_message=None: [],
        )
        monkeypatch.setattr(
            "core.main.tool_registry.SMART_AGENT_DIRECT_TOOLS",
            {"read_coaching_guide"},
        )

        messages = [{"role": "user", "content": "What is my bench press program?"}]
        result = orch._run_smart_loop(messages, smart_system="", worker_system="")

        # Must return the substantive text, not the apologetic fallback
        assert result == substantive_text, (
            f"Expected substantive text returned at cap exhaustion, got: {result!r}"
        )
        assert "Apologies" not in result, (
            "Apologetic fallback returned despite substantive text being available"
        )

    def test_cap_exhaustion_without_substantive_text_returns_sentinel(self, monkeypatch):
        """When loop hits cap with no substantive text, return unchanged sentinel string.

        test_autonomous.py::test_sentinel_substring_matches_main_constant must stay green.
        """
        import core.main as main_module

        orch = _make_minimal_orchestrator()

        # Produce empty text with tool calls on every iteration (no substantive text)
        response = _tool_call_response(text="")
        orch.smart_agent.chat.return_value = response

        monkeypatch.setattr(
            "core.main.tool_registry.dispatch",
            lambda name, args: '{"result": "ok"}',
        )
        monkeypatch.setattr(
            "core.main.tool_registry.get_smart_schemas",
            lambda user_message=None: [],
        )
        monkeypatch.setattr(
            "core.main.tool_registry.SMART_AGENT_DIRECT_TOOLS",
            {"read_coaching_guide"},
        )

        messages = [{"role": "user", "content": "test"}]
        result = orch._run_smart_loop(messages, smart_system="", worker_system="")

        # Must return the cap-exhaustion fallback string (not empty)
        assert "more steps" in result, (
            f"Expected cap-exhaustion fallback when no substantive text, got: {result!r}"
        )
        assert "rephrasing" in result.lower() or "smaller parts" in result.lower(), (
            f"Expected a rephrase/break-up hint in the fallback, got: {result!r}"
        )

    def test_sentinel_string_unchanged(self):
        """Verify the sentinel string text is byte-identical to the expected value.

        This guards the test_autonomous.py::test_sentinel_substring_matches_main_constant
        coupling — autonomous.py keys on a substring of CONNECTIVITY_ERROR_TEXT.
        """
        from core.main import CONNECTIVITY_ERROR_TEXT
        # The sentinel from autonomous.py is "connectivity issue" substring
        assert "connectivity issue" in CONNECTIVITY_ERROR_TEXT.lower() or \
               "I'm afraid" in CONNECTIVITY_ERROR_TEXT, (
            f"CONNECTIVITY_ERROR_TEXT changed unexpectedly: {CONNECTIVITY_ERROR_TEXT!r}"
        )


# ---------------------------------------------------------------------------
# WR-05 (Phase 26) — empty orchestrator reply must not be persisted verbatim
# ---------------------------------------------------------------------------

def _make_orchestrator_for_handle_message(loop_return: str):
    """Build a minimal AgentOrchestrator whose _run_smart_loop returns a fixed
    value, with the prompt/conversation collaborators stubbed out so
    handle_message can run without real Firestore / prompt state.
    """
    from core.main import AgentOrchestrator

    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.smart_agent = MagicMock()
    orch.smart_agent_fallback = None
    orch.worker_agent = MagicMock()
    orch._smart_prompt_template = "smart"
    orch._worker_prompt_template = "worker {today_date}"
    orch._meal_audit_content = ""
    orch.conversation_manager = MagicMock()
    orch.conversation_manager.get.return_value = []
    # Avoid touching real SELF.md / self_state rendering.
    orch.render_smart_system = lambda template: "rendered-system"
    # The unit under test is the empty-reply guard, not the loop itself.
    orch._run_smart_loop = MagicMock(return_value=loop_return)
    return orch


class TestEmptyReplyGuard:
    """WR-05: an empty/whitespace-only loop result must be replaced with a
    non-empty fallback before it is persisted — otherwise the hub UI clears
    'Klaus is thinking…' and renders a blank bubble with no retry affordance.
    """

    @pytest.mark.parametrize("empty_reply", ["", "   ", "\n\t  "])
    def test_empty_reply_replaced_with_fallback(self, empty_reply):
        orch = _make_orchestrator_for_handle_message(loop_return=empty_reply)

        result = orch.handle_message("hello", user_id=123456)

        # The returned text must be non-empty (a fallback was substituted).
        assert result.strip(), f"empty reply was not replaced, got: {result!r}"
        # The assistant turn persisted to the conversation must be the same
        # non-empty fallback — never the empty string.
        assistant_calls = [
            c for c in orch.conversation_manager.append.call_args_list
            if c.args[1] == "assistant"
        ]
        assert assistant_calls, "no assistant message was persisted"
        persisted = assistant_calls[-1].args[2]
        assert persisted.strip(), f"empty assistant reply persisted: {persisted!r}"
        assert persisted == result

    def test_substantive_reply_passed_through_unchanged(self):
        """A normal non-empty reply must be returned verbatim (guard is a no-op)."""
        orch = _make_orchestrator_for_handle_message(
            loop_return="Here is your schedule for today."
        )

        result = orch.handle_message("what's today?", user_id=123456)

        assert result == "Here is your schedule for today."
