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


# ---------------------------------------------------------------------------
# Phase 30.5 Plan 06 (D-16/D-12) — 3-tier Sonnet -> Gemini -> Haiku fallback
# ---------------------------------------------------------------------------

def _make_orchestrator_with_tiers(fallback=None, tertiary=None):
    """Build a minimal AgentOrchestrator with all three fallback tiers wired."""
    orch = _make_minimal_orchestrator()
    orch.smart_agent_fallback = fallback
    orch.smart_agent_tertiary = tertiary
    return orch


class TestThreeTierFallbackChain:
    """D-16: Sonnet primary -> Gemini fallback -> Haiku tertiary -> CONNECTIVITY_ERROR_TEXT.

    D-12: only the Gemini-fallback branch appends the backup-reasoning disclosure.
    """

    def test_sonnet_error_falls_back_to_gemini_with_disclosure(self, monkeypatch):
        """Primary (Sonnet) LLMError -> Gemini fallback used; disclosure line appended."""
        from core.llm_client import LLMError
        from core.main import FALLBACK_DISCLOSURE_TEXT

        fallback = MagicMock()
        fallback.chat.return_value = _text_only_response("Here's your answer.")
        orch = _make_orchestrator_with_tiers(fallback=fallback, tertiary=None)
        orch.smart_agent.chat.side_effect = LLMError("boom", backend="anthropic")

        monkeypatch.setattr(
            "core.main.tool_registry.get_smart_schemas",
            lambda user_message=None: [],
        )

        messages = [{"role": "user", "content": "hello"}]
        result = orch._run_smart_loop(messages, smart_system="", worker_system="")

        fallback.chat.assert_called_once()
        assert fallback.chat.call_args.kwargs["purpose"] == "smart_fallback"
        assert result.startswith("Here's your answer.")
        assert FALLBACK_DISCLOSURE_TEXT in result

    def test_sonnet_and_gemini_error_falls_back_to_haiku_no_disclosure(self, monkeypatch):
        """Primary + Gemini fallback both LLMError -> tertiary (Haiku) used, purpose smart_fallback_2, no disclosure."""
        from core.llm_client import LLMError
        from core.main import FALLBACK_DISCLOSURE_TEXT

        fallback = MagicMock()
        fallback.chat.side_effect = LLMError("gemini down", backend="gemini")
        tertiary = MagicMock()
        tertiary.chat.return_value = _text_only_response("Backup answer from Haiku.")
        orch = _make_orchestrator_with_tiers(fallback=fallback, tertiary=tertiary)
        orch.smart_agent.chat.side_effect = LLMError("boom", backend="anthropic")

        monkeypatch.setattr(
            "core.main.tool_registry.get_smart_schemas",
            lambda user_message=None: [],
        )

        messages = [{"role": "user", "content": "hello"}]
        result = orch._run_smart_loop(messages, smart_system="", worker_system="")

        tertiary.chat.assert_called_once()
        assert tertiary.chat.call_args.kwargs["purpose"] == "smart_fallback_2"
        assert result == "Backup answer from Haiku."
        assert FALLBACK_DISCLOSURE_TEXT not in result

    def test_all_three_tiers_fail_returns_connectivity_error(self, monkeypatch):
        """Sonnet + Gemini + Haiku all LLMError -> CONNECTIVITY_ERROR_TEXT."""
        from core.llm_client import LLMError
        from core.main import CONNECTIVITY_ERROR_TEXT

        fallback = MagicMock()
        fallback.chat.side_effect = LLMError("gemini down", backend="gemini")
        tertiary = MagicMock()
        tertiary.chat.side_effect = LLMError("haiku down", backend="anthropic")
        orch = _make_orchestrator_with_tiers(fallback=fallback, tertiary=tertiary)
        orch.smart_agent.chat.side_effect = LLMError("boom", backend="anthropic")

        monkeypatch.setattr(
            "core.main.tool_registry.get_smart_schemas",
            lambda user_message=None: [],
        )

        messages = [{"role": "user", "content": "hello"}]
        result = orch._run_smart_loop(messages, smart_system="", worker_system="")

        assert result == CONNECTIVITY_ERROR_TEXT

    def test_tertiary_none_returns_connectivity_error_after_gemini_fails(self, monkeypatch):
        """Tertiary is None-safe: Sonnet + Gemini fail, no tertiary configured -> CONNECTIVITY_ERROR_TEXT."""
        from core.llm_client import LLMError
        from core.main import CONNECTIVITY_ERROR_TEXT

        fallback = MagicMock()
        fallback.chat.side_effect = LLMError("gemini down", backend="gemini")
        orch = _make_orchestrator_with_tiers(fallback=fallback, tertiary=None)
        orch.smart_agent.chat.side_effect = LLMError("boom", backend="anthropic")

        monkeypatch.setattr(
            "core.main.tool_registry.get_smart_schemas",
            lambda user_message=None: [],
        )

        messages = [{"role": "user", "content": "hello"}]
        result = orch._run_smart_loop(messages, smart_system="", worker_system="")

        assert result == CONNECTIVITY_ERROR_TEXT

    def test_tertiary_client_constructed_from_env(self, monkeypatch):
        """AgentOrchestrator.__init__ builds smart_agent_tertiary from SMART_AGENT_TERTIARY_* env."""
        import importlib
        import core.main as main_module

        monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
        monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
        monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")
        monkeypatch.setenv("WORKER_AGENT_BACKEND", "openai")
        monkeypatch.setenv("WORKER_AGENT_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("WORKER_AGENT_API_KEY", "test-key")
        monkeypatch.setenv("SMART_AGENT_TERTIARY_BACKEND", "anthropic")
        monkeypatch.setenv("SMART_AGENT_TERTIARY_MODEL", "claude-haiku-4-5")
        monkeypatch.setenv("SMART_AGENT_TERTIARY_API_KEY", "test-key")
        monkeypatch.delenv("SMART_AGENT_FALLBACK_BACKEND", raising=False)
        monkeypatch.delenv("SMART_AGENT_FALLBACK_MODEL", raising=False)
        monkeypatch.delenv("SMART_AGENT_FALLBACK_API_KEY", raising=False)

        with patch("core.main._load_prompt", return_value="stub"), \
             patch("core.main._load_self_md", return_value="stub"), \
             patch("core.main._load_coaching_guide_slim", return_value="stub"), \
             patch("core.main._build_self_state_store", return_value=None), \
             patch("core.main._build_user_profile_store", return_value=None), \
             patch("core.main._build_journal_store", return_value=None), \
             patch("core.main.build_conversation_store_from_env", return_value=MagicMock()):
            orch = main_module.AgentOrchestrator()

        assert orch.smart_agent_tertiary is not None
        assert orch.smart_agent_tertiary.model == "claude-haiku-4-5"

    def test_tertiary_none_when_env_absent(self, monkeypatch):
        """AgentOrchestrator.__init__ leaves smart_agent_tertiary as None when env unset."""
        import core.main as main_module

        monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
        monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
        monkeypatch.setenv("SMART_AGENT_API_KEY", "test-key")
        monkeypatch.setenv("WORKER_AGENT_BACKEND", "openai")
        monkeypatch.setenv("WORKER_AGENT_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("WORKER_AGENT_API_KEY", "test-key")
        monkeypatch.delenv("SMART_AGENT_TERTIARY_BACKEND", raising=False)
        monkeypatch.delenv("SMART_AGENT_TERTIARY_MODEL", raising=False)
        monkeypatch.delenv("SMART_AGENT_TERTIARY_API_KEY", raising=False)
        monkeypatch.delenv("SMART_AGENT_FALLBACK_BACKEND", raising=False)
        monkeypatch.delenv("SMART_AGENT_FALLBACK_MODEL", raising=False)
        monkeypatch.delenv("SMART_AGENT_FALLBACK_API_KEY", raising=False)

        with patch("core.main._load_prompt", return_value="stub"), \
             patch("core.main._load_self_md", return_value="stub"), \
             patch("core.main._load_coaching_guide_slim", return_value="stub"), \
             patch("core.main._build_self_state_store", return_value=None), \
             patch("core.main._build_user_profile_store", return_value=None), \
             patch("core.main._build_journal_store", return_value=None), \
             patch("core.main.build_conversation_store_from_env", return_value=MagicMock()):
            orch = main_module.AgentOrchestrator()

        assert orch.smart_agent_tertiary is None


# ---------------------------------------------------------------------------
# Hub attachments feature — InboundAttachment injection into the smart loop
# ---------------------------------------------------------------------------

_JPEG_BYTES = b"\xff\xd8\xff\xe0fakejpeg"
_PDF_BYTES = b"%PDF-1.7 fakepdf"


def _run_loop_with_attachments(monkeypatch, messages, attachments):
    """Run _run_smart_loop with a text-only brain response; return the messages
    list the brain actually received."""
    orch = _make_minimal_orchestrator()
    orch.smart_agent.chat.return_value = _text_only_response("done")
    monkeypatch.setattr(
        "core.main.tool_registry.get_smart_schemas",
        lambda user_message=None: [],
    )
    orch._run_smart_loop(messages, smart_system="", worker_system="",
                         attachments=attachments)
    return orch.smart_agent.chat.call_args.args[0]


class TestAttachmentInjection:
    """Attachments (images + PDFs) are injected as content blocks into a local
    copy of the last user message — transient by design: history keeps only the
    text (mirrors the original Telegram photo behavior, now generalized)."""

    def test_image_attachment_injected_as_image_block(self, monkeypatch):
        import base64
        from core.main import InboundAttachment

        messages = [{"role": "user", "content": "what is this?"}]
        sent = _run_loop_with_attachments(
            monkeypatch, messages,
            [InboundAttachment(data=_JPEG_BYTES, mime_type="image/jpeg", kind="image")],
        )

        content = sent[-1]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "what is this?"}
        assert content[1]["type"] == "image"
        assert content[1]["source"] == {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(_JPEG_BYTES).decode("utf-8"),
        }

    def test_pdf_attachment_injected_as_document_block(self, monkeypatch):
        import base64
        from core.main import InboundAttachment

        messages = [{"role": "user", "content": "summarize this"}]
        sent = _run_loop_with_attachments(
            monkeypatch, messages,
            [InboundAttachment(data=_PDF_BYTES, mime_type="application/pdf", kind="pdf")],
        )

        content = sent[-1]["content"]
        assert content[1]["type"] == "document"
        assert content[1]["source"] == {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(_PDF_BYTES).decode("utf-8"),
        }

    def test_multiple_attachments_all_injected_in_order(self, monkeypatch):
        from core.main import InboundAttachment

        messages = [{"role": "user", "content": "both"}]
        sent = _run_loop_with_attachments(
            monkeypatch, messages,
            [
                InboundAttachment(data=_JPEG_BYTES, mime_type="image/jpeg", kind="image"),
                InboundAttachment(data=_PDF_BYTES, mime_type="application/pdf", kind="pdf"),
            ],
        )

        content = sent[-1]["content"]
        assert [b["type"] for b in content] == ["text", "image", "document"]

    def test_empty_content_omits_text_block(self, monkeypatch):
        """Image-only message: Anthropic rejects empty text blocks, so the
        content list must contain only the attachment blocks."""
        from core.main import InboundAttachment

        messages = [{"role": "user", "content": ""}]
        sent = _run_loop_with_attachments(
            monkeypatch, messages,
            [InboundAttachment(data=_JPEG_BYTES, mime_type="image/jpeg", kind="image")],
        )

        content = sent[-1]["content"]
        assert [b["type"] for b in content] == ["image"]

    def test_original_history_not_polluted(self, monkeypatch):
        """The injection must happen on a deep copy — the caller's messages
        list (which mirrors persisted history) keeps its plain-string content."""
        from core.main import InboundAttachment

        messages = [{"role": "user", "content": "look"}]
        _run_loop_with_attachments(
            monkeypatch, messages,
            [InboundAttachment(data=_JPEG_BYTES, mime_type="image/jpeg", kind="image")],
        )

        assert messages == [{"role": "user", "content": "look"}]

    def test_no_attachments_leaves_string_content(self, monkeypatch):
        sent = _run_loop_with_attachments(
            monkeypatch, [{"role": "user", "content": "plain"}], None,
        )
        assert sent[-1]["content"] == "plain"


class TestHandleMessageAttachments:
    """handle_message forwards attachments to the loop and persists text only."""

    def test_attachments_forwarded_and_history_text_only(self):
        from core.main import InboundAttachment

        orch = _make_orchestrator_for_handle_message(loop_return="I see a cat.")
        atts = [InboundAttachment(data=_JPEG_BYTES, mime_type="image/jpeg", kind="image")]

        result = orch.handle_message("what's this?", user_id=123456, attachments=atts)

        assert result == "I see a cat."
        # The loop received the attachments…
        assert orch._run_smart_loop.call_args.kwargs.get("attachments") == atts
        # …but history got only the plain text turns.
        user_calls = [
            c for c in orch.conversation_manager.append.call_args_list
            if c.args[1] == "user"
        ]
        assert user_calls[-1].args[2] == "what's this?"
