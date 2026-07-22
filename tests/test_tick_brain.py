"""Tests for core/tick_brain.py — TickBrain judgment layer.

Tests cover:
- _parse_response static method: JSON success, no-JSON, missing key, with draft
- think() behavior: purpose="tick" passed, fallback on LLMError, safe mode on double failure
- Constructor: env var defaults, ValueError on missing API key
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch


class TestParseResponse(unittest.TestCase):
    """Unit tests for TickBrain._parse_response (no network, no env vars needed)."""

    def _get_parse_response(self):
        """Import _parse_response lazily so the test file imports cleanly."""
        from core.tick_brain import TickBrain
        return TickBrain._parse_response

    def test_valid_json_no_act(self):
        parse = self._get_parse_response()
        result = parse('{"should_act": false, "reason": "all good"}')
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "all good")
        self.assertNotIn("draft", result)

    def test_valid_json_with_act_and_draft(self):
        parse = self._get_parse_response()
        result = parse('{"should_act": true, "reason": "alert", "draft": "Check tasks"}')
        self.assertTrue(result["should_act"])
        self.assertEqual(result["draft"], "Check tasks")

    def test_non_json_returns_parse_failure(self):
        parse = self._get_parse_response()
        result = parse("not json at all")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "parse_failure")

    def test_json_missing_should_act_returns_parse_failure(self):
        parse = self._get_parse_response()
        result = parse('{"missing_key": true}')
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "parse_failure")

    def test_markdown_fenced_json_stripped(self):
        parse = self._get_parse_response()
        fenced = '```json\n{"should_act": false, "reason": "ok"}\n```'
        result = parse(fenced)
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "ok")

    def test_empty_string_returns_parse_failure(self):
        parse = self._get_parse_response()
        result = parse("")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "parse_failure")

    def test_draft_omitted_when_should_act_false(self):
        parse = self._get_parse_response()
        result = parse('{"should_act": false, "reason": "quiet", "draft": ""}')
        # Empty draft string should not be included
        self.assertNotIn("draft", result)

    def test_think_block_stripped_before_json(self):
        """Qwen3 prepends <think>…</think> reasoning before the JSON payload —
        the parse must strip it (2026-06-11: this broke every live Groq call)."""
        parse = self._get_parse_response()
        raw = ('<think>\nThe user has an overdue task. I should flag it.\n</think>\n\n'
               '{"should_act": true, "reason": "overdue", "topic_key": "overdue:x"}')
        result = parse(raw)
        self.assertTrue(result["should_act"])
        self.assertEqual(result["reason"], "overdue")

    def test_think_block_with_fenced_json_stripped(self):
        parse = self._get_parse_response()
        raw = ('<think>reasoning here</think>\n'
               '```json\n{"should_act": false, "reason": "ok"}\n```')
        result = parse(raw)
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "ok")

    def test_unterminated_think_block_returns_parse_failure(self):
        """max_tokens truncation mid-reasoning leaves an unclosed <think> and no
        JSON — must land in safe mode, not raise."""
        parse = self._get_parse_response()
        result = parse('<think>\nstill reasoning when the output got cut')
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "parse_failure")


class TestTickBrainConstructor(unittest.TestCase):
    """Tests for TickBrain.__init__ — env var handling."""

    def test_raises_if_api_key_missing(self):
        """ValueError if TICK_BRAIN_API_KEY not set."""
        env = {k: v for k, v in os.environ.items() if "TICK_BRAIN" not in k}
        with patch.dict(os.environ, env, clear=True):
            from core.tick_brain import TickBrain
            with self.assertRaises(ValueError):
                TickBrain()

    def test_defaults_applied_when_env_vars_absent(self):
        """Backend, model, base_url all fall back to defaults when not in env."""
        env = {"TICK_BRAIN_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            from core.llm_client import LLMClient
            with patch.object(LLMClient, "__init__", return_value=None) as mock_init:
                # Patch _impl to avoid real network calls
                with patch.object(LLMClient, "_impl", create=True, new=MagicMock()):
                    from core.tick_brain import TickBrain
                    brain = TickBrain.__new__(TickBrain)
                    # Call __init__ directly via reimport
        # Test via env reading — simpler approach
        captured = {}

        class FakeLLMClient:
            def __init__(self, backend, model, api_key, base_url=None):
                captured.update({"backend": backend, "model": model, "base_url": base_url})

        with patch.dict(os.environ, {"TICK_BRAIN_API_KEY": "gsk_test"}, clear=True):
            import importlib
            import core.tick_brain as tb_module
            with patch("core.tick_brain.LLMClient" if hasattr(tb_module, "LLMClient") else "core.llm_client.LLMClient", FakeLLMClient, create=True):
                # Reload to pick up env
                pass

        # Direct check via monkey-patch at import level
        from core import tick_brain as tb
        orig = tb.LLMClient if hasattr(tb, "LLMClient") else None

        _calls = []

        class CaptureLLMClient:
            def __init__(self, backend, model, api_key, base_url=None):
                _calls.append({"backend": backend, "model": model, "base_url": base_url})

        with patch.dict(os.environ, {"TICK_BRAIN_API_KEY": "gsk_test"}, clear=True):
            # Patch inside tick_brain module
            import core.tick_brain as tb2
            with patch.object(tb2, "LLMClient", CaptureLLMClient):
                brain = tb2.TickBrain()
                primary_call = _calls[0]
                self.assertEqual(primary_call["backend"], "openai")
                self.assertEqual(primary_call["model"], "openai/gpt-oss-120b")
                self.assertEqual(primary_call["base_url"], "https://api.groq.com/openai/v1")
                self.assertEqual(brain._max_tokens, 2048)

    def test_max_tokens_env_override(self):
        """TICK_BRAIN_MAX_TOKENS env var overrides the 2048 default; a
        non-numeric value falls back to the default instead of raising."""
        class StubLLMClient:
            def __init__(self, backend, model, api_key, base_url=None):
                pass

        import core.tick_brain as tb
        env = {"TICK_BRAIN_API_KEY": "gsk_test", "TICK_BRAIN_MAX_TOKENS": "1500"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(tb, "LLMClient", StubLLMClient):
                self.assertEqual(tb.TickBrain()._max_tokens, 1500)

        env["TICK_BRAIN_MAX_TOKENS"] = "not-a-number"
        with patch.dict(os.environ, env, clear=True):
            with patch.object(tb, "LLMClient", StubLLMClient):
                self.assertEqual(tb.TickBrain()._max_tokens, 2048)

    # ---- BRAIN-03: fallback decoupled onto TICK_BRAIN_FALLBACK_* ----

    def test_fallback_constructed_from_tick_brain_fallback_env(self):
        """Fallback client must be built from TICK_BRAIN_FALLBACK_* env vars,
        never SMART_AGENT_* — asserts _fallback_model == 'gemini-3.5-flash'."""
        _calls = []

        class CaptureLLMClient:
            def __init__(self, backend, model, api_key, base_url=None):
                _calls.append({"backend": backend, "model": model,
                                "api_key": api_key, "base_url": base_url})

        import core.tick_brain as tb
        env = {
            "TICK_BRAIN_API_KEY": "gsk_test",
            "TICK_BRAIN_FALLBACK_BACKEND": "gemini",
            "TICK_BRAIN_FALLBACK_MODEL": "gemini-3.5-flash",
            "TICK_BRAIN_FALLBACK_API_KEY": "gemini_test_key",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(tb, "LLMClient", CaptureLLMClient):
                brain = tb.TickBrain()
                self.assertEqual(brain._fallback_model, "gemini-3.5-flash")
                fallback_call = _calls[1]
                self.assertEqual(fallback_call["backend"], "gemini")
                self.assertEqual(fallback_call["model"], "gemini-3.5-flash")
                self.assertEqual(fallback_call["api_key"], "gemini_test_key")

    def test_fallback_defaults_to_gemini_when_backend_model_unset(self):
        """Backend/model default to gemini/gemini-3.5-flash on a fresh deploy
        (vars unset) as long as TICK_BRAIN_FALLBACK_API_KEY is present."""
        _calls = []

        class CaptureLLMClient:
            def __init__(self, backend, model, api_key, base_url=None):
                _calls.append({"backend": backend, "model": model})

        import core.tick_brain as tb
        env = {
            "TICK_BRAIN_API_KEY": "gsk_test",
            "TICK_BRAIN_FALLBACK_API_KEY": "gemini_test_key",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(tb, "LLMClient", CaptureLLMClient):
                brain = tb.TickBrain()
                self.assertEqual(brain._fallback_model, "gemini-3.5-flash")
                self.assertEqual(_calls[1]["backend"], "gemini")
                self.assertEqual(_calls[1]["model"], "gemini-3.5-flash")

    def test_fallback_none_when_fallback_api_key_absent(self):
        """No TICK_BRAIN_FALLBACK_API_KEY -> fallback client stays None even
        though backend/model default (optional-client shape preserved)."""
        class StubLLMClient:
            def __init__(self, backend, model, api_key, base_url=None):
                pass

        import core.tick_brain as tb
        env = {"TICK_BRAIN_API_KEY": "gsk_test"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(tb, "LLMClient", StubLLMClient):
                brain = tb.TickBrain()
                self.assertIsNone(brain._fallback_client)
                self.assertIsNone(brain._fallback_model)

    def test_module_never_reads_smart_agent_env(self):
        """core/tick_brain.py must not read any SMART_AGENT_* var (BRAIN-03)."""
        import inspect
        import core.tick_brain as tb
        source = inspect.getsource(tb)
        self.assertNotIn("SMART_AGENT", source)

    def test_forced_groq_failure_routes_to_decoupled_fallback(self):
        """RESEARCH.md Code Examples shape: a forced Groq (primary) failure
        must route to the decoupled TICK_BRAIN_FALLBACK_* client and report
        gemini-3.5-flash — NEVER claude-sonnet-5, even when SMART_AGENT_MODEL
        has already been flipped to claude-sonnet-5 (post-flip state, D-13)."""
        from core.llm_client import LLMError
        import core.tick_brain as tb

        env = {
            "TICK_BRAIN_API_KEY": "gsk_test",
            "TICK_BRAIN_FALLBACK_BACKEND": "gemini",
            "TICK_BRAIN_FALLBACK_MODEL": "gemini-3.5-flash",
            "TICK_BRAIN_FALLBACK_API_KEY": "test-key",
            "SMART_AGENT_MODEL": "claude-sonnet-5",  # post-flip state
        }
        with patch.dict(os.environ, env, clear=True):
            brain = tb.TickBrain()
            with patch.object(brain._client, "chat",
                               side_effect=LLMError("boom", backend="openai")):
                with patch.object(brain._fallback_client, "chat") as mock_fb:
                    mock_fb.return_value = {
                        "text": '{"should_act": false, "reason": "test"}',
                        "tool_calls": [], "stop_reason": "end_turn",
                        "usage": {"in_tokens": 1, "out_tokens": 1},
                    }
                    brain.think("test prompt")
                    self.assertEqual(brain._fallback_model, "gemini-3.5-flash")
                    self.assertNotEqual(brain._fallback_model, "claude-sonnet-5")
                    mock_fb.assert_called_once()


class TestTickBrainThink(unittest.TestCase):
    """Tests for TickBrain.think() — uses mocked LLMClient."""

    def _make_brain(self, primary_response=None, primary_raises=None,
                    fallback_response=None, fallback_raises=None,
                    has_fallback=True):
        """Build a TickBrain with mocked _client and _fallback_client."""
        from core.tick_brain import TickBrain

        brain = object.__new__(TickBrain)

        primary = MagicMock()
        if primary_raises:
            primary.chat.side_effect = primary_raises
        else:
            primary.chat.return_value = primary_response or {
                "text": '{"should_act": false, "reason": "ok"}',
                "tool_calls": [],
                "stop_reason": "end_turn",
                "usage": {"in_tokens": 10, "out_tokens": 5},
            }
        brain._client = primary

        if has_fallback:
            fallback = MagicMock()
            if fallback_raises:
                fallback.chat.side_effect = fallback_raises
            else:
                fallback.chat.return_value = fallback_response or {
                    "text": '{"should_act": false, "reason": "fallback_ok"}',
                    "tool_calls": [],
                    "stop_reason": "end_turn",
                    "usage": {"in_tokens": 10, "out_tokens": 5},
                }
            brain._fallback_client = fallback
            brain._fallback_model = "gemini-3-flash"
        else:
            brain._fallback_client = None
            brain._fallback_model = None

        brain._model = "qwen3-32b"
        brain._max_tokens = 2048
        brain._temperature = 0.6
        return brain

    def test_think_returns_should_act_false_on_good_response(self):
        brain = self._make_brain()
        result = brain.think("Signal: all healthy")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "ok")

    def test_think_passes_purpose_tick_to_primary(self):
        """purpose='tick' must be passed to primary LLMClient.chat()."""
        brain = self._make_brain()
        brain.think("test prompt")
        call_kwargs = brain._client.chat.call_args
        # purpose is a keyword argument
        self.assertEqual(call_kwargs.kwargs.get("purpose"), "tick")

    def test_think_passes_purpose_tick_fallback_to_fallback(self):
        """purpose='tick_fallback' must be passed to fallback LLMClient.chat()."""
        from core.llm_client import LLMError
        brain = self._make_brain(
            primary_raises=LLMError("rate limit", backend="openai", status_code=429)
        )
        brain.think("test prompt")
        call_kwargs = brain._fallback_client.chat.call_args
        self.assertEqual(call_kwargs.kwargs.get("purpose"), "tick_fallback")

    def test_think_passes_tick_budget_to_primary(self):
        """Primary (Groq) gets the reduced tick budget — Groq's free tier
        counts input + max_tokens against the 6000-TPM per-request limit,
        so the global 4096 default 413s and silently re-routes to fallback."""
        brain = self._make_brain()
        brain.think("test prompt")
        kwargs = brain._client.chat.call_args.kwargs
        self.assertEqual(kwargs.get("max_tokens"), 2048)

    def test_think_fallback_keeps_default_budget(self):
        """Fallback (Gemini) has no per-request token cap — it must NOT
        inherit the Groq budget; omitting max_tokens keeps MAX_TOKENS."""
        from core.llm_client import LLMError
        brain = self._make_brain(
            primary_raises=LLMError("rate limit", backend="openai", status_code=429)
        )
        brain.think("test prompt")
        kwargs = brain._fallback_client.chat.call_args.kwargs
        self.assertNotIn("max_tokens", kwargs)

    def test_think_falls_back_on_llm_error(self):
        """On LLMError from primary, fallback client is tried."""
        from core.llm_client import LLMError
        fallback_resp = {
            "text": '{"should_act": true, "reason": "via fallback", "draft": "Alert!"}',
            "tool_calls": [], "stop_reason": "end_turn",
            "usage": {"in_tokens": 10, "out_tokens": 5},
        }
        brain = self._make_brain(
            primary_raises=LLMError("groq error", backend="openai"),
            fallback_response=fallback_resp,
        )
        result = brain.think("alert scenario")
        self.assertTrue(result["should_act"])
        self.assertEqual(result["reason"], "via fallback")
        self.assertEqual(result["draft"], "Alert!")

    def test_think_safe_mode_when_both_fail(self):
        """When both primary and fallback raise LLMError → safe mode."""
        from core.llm_client import LLMError
        brain = self._make_brain(
            primary_raises=LLMError("groq down", backend="openai"),
            fallback_raises=LLMError("gemini down", backend="gemini"),
        )
        result = brain.think("test")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "llm_error")

    def test_think_safe_mode_no_fallback_configured(self):
        """When primary fails and no fallback configured → safe mode."""
        from core.llm_client import LLMError
        brain = self._make_brain(
            primary_raises=LLMError("groq down", backend="openai"),
            has_fallback=False,
        )
        result = brain.think("test")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "llm_error")

    def test_think_returns_parse_failure_on_non_json(self):
        """Non-JSON LLM output → safe mode parse_failure."""
        brain = self._make_brain(primary_response={
            "text": "Sure! I think you should act.",
            "tool_calls": [], "stop_reason": "end_turn",
            "usage": {"in_tokens": 10, "out_tokens": 5},
        })
        result = brain.think("test")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "parse_failure")

    def test_think_includes_draft_when_present(self):
        """think() returns draft key when LLM includes it and should_act=true."""
        brain = self._make_brain(primary_response={
            "text": '{"should_act": true, "reason": "tasks overdue", "draft": "2 tasks overdue!"}',
            "tool_calls": [], "stop_reason": "end_turn",
            "usage": {"in_tokens": 10, "out_tokens": 5},
        })
        result = brain.think("2 tasks overdue")
        self.assertTrue(result["should_act"])
        self.assertEqual(result["draft"], "2 tasks overdue!")


class TestSystemOverrideAndTopicKey(unittest.TestCase):
    """Plan 18-05 — system_override kwarg + topic_key passthrough + layered purpose strings.

    Covers AUTO-01 (Layer 1 accepts autonomous_triage.md as system prompt) and
    AUTO-07 (topic_key field flows through parser for outreach_log dedup).

    WARNING 1 regression guard: fallback purpose must remain 'tick_fallback' when
    no system_override is set, so Phase 14 INFRA-02 fallback-rate visibility is
    preserved. With override set, fallback becomes 'tick_autonomous_fallback'.
    """

    def _make_brain(self, primary_response=None, primary_raises=None,
                    fallback_response=None, fallback_raises=None,
                    has_fallback=True):
        """Build a TickBrain with mocked _client and _fallback_client (same shape as TestTickBrainThink)."""
        from core.tick_brain import TickBrain

        brain = object.__new__(TickBrain)

        primary = MagicMock()
        if primary_raises:
            primary.chat.side_effect = primary_raises
        else:
            primary.chat.return_value = primary_response or {
                "text": '{"should_act": false, "reason": "ok"}',
                "tool_calls": [],
                "stop_reason": "end_turn",
                "usage": {"in_tokens": 10, "out_tokens": 5},
            }
        brain._client = primary

        if has_fallback:
            fallback = MagicMock()
            if fallback_raises:
                fallback.chat.side_effect = fallback_raises
            else:
                fallback.chat.return_value = fallback_response or {
                    "text": '{"should_act": false, "reason": "fallback_ok"}',
                    "tool_calls": [],
                    "stop_reason": "end_turn",
                    "usage": {"in_tokens": 10, "out_tokens": 5},
                }
            brain._fallback_client = fallback
            brain._fallback_model = "gemini-3-flash"
        else:
            brain._fallback_client = None
            brain._fallback_model = None

        brain._model = "qwen3-32b"
        brain._max_tokens = 2048
        brain._temperature = 0.6
        return brain

    # ---- think() signature: system_override kwarg ----

    def test_think_default_uses_tick_system_prompt_and_purpose_tick(self):
        """Test 1: no system_override → system=_TICK_SYSTEM_PROMPT, purpose='tick' (backward-compat)."""
        from core.tick_brain import _TICK_SYSTEM_PROMPT
        brain = self._make_brain()
        brain.think("test")
        kwargs = brain._client.chat.call_args.kwargs
        self.assertEqual(kwargs["system"], _TICK_SYSTEM_PROMPT)
        self.assertEqual(kwargs["purpose"], "tick")

    def test_think_with_override_uses_custom_system_and_purpose_autonomous(self):
        """Test 2: system_override set → system=<override>, purpose='tick_autonomous'."""
        brain = self._make_brain()
        brain.think("test", system_override="custom system prompt")
        kwargs = brain._client.chat.call_args.kwargs
        self.assertEqual(kwargs["system"], "custom system prompt")
        self.assertEqual(kwargs["purpose"], "tick_autonomous")

    def test_fallback_purpose_preserves_tick_fallback_when_no_override(self):
        """Test 3 + 6 (WARNING 1 regression guard): fallback purpose must remain 'tick_fallback'
        when no system_override is set, so INFRA-02 fallback-rate visibility is preserved.
        """
        from core.llm_client import LLMError
        from core.tick_brain import _TICK_SYSTEM_PROMPT
        brain = self._make_brain(
            primary_raises=LLMError("boom", backend="openai"),
        )
        brain.think("test")  # no system_override
        kwargs = brain._fallback_client.chat.call_args.kwargs
        self.assertEqual(
            kwargs["purpose"], "tick_fallback",
            f"WARNING 1 regression: fallback purpose changed to {kwargs['purpose']!r}"
        )
        # Active system carries through (should be the default).
        self.assertEqual(kwargs["system"], _TICK_SYSTEM_PROMPT)

    def test_fallback_purpose_is_autonomous_when_override_set(self):
        """Test 4: fallback purpose 'tick_autonomous_fallback' when system_override is set."""
        from core.llm_client import LLMError
        brain = self._make_brain(
            primary_raises=LLMError("boom", backend="openai"),
        )
        brain.think("test", system_override="custom")
        kwargs = brain._fallback_client.chat.call_args.kwargs
        self.assertEqual(kwargs["purpose"], "tick_autonomous_fallback")

    def test_fallback_receives_same_system_as_primary(self):
        """Test 5: active_system value carries through to fallback when primary fails."""
        from core.llm_client import LLMError
        brain = self._make_brain(
            primary_raises=LLMError("boom", backend="openai"),
        )
        brain.think("test", system_override="autonomous triage prompt body")
        kwargs = brain._fallback_client.chat.call_args.kwargs
        self.assertEqual(kwargs["system"], "autonomous triage prompt body")

    # ---- _parse_response: topic_key passthrough ----

    def test_topic_key_passthrough_when_present(self):
        """Test 7: topic_key flows through when LLM JSON contains it."""
        from core.tick_brain import TickBrain
        result = TickBrain._parse_response(
            '{"should_act": true, "reason": "x", "draft": "y", "topic_key": "overdue:maya"}'
        )
        self.assertEqual(result["topic_key"], "overdue:maya")
        self.assertEqual(result["draft"], "y")
        self.assertTrue(result["should_act"])

    def test_topic_key_absent_when_missing_from_json(self):
        """Test 8: missing topic_key → result dict has no topic_key key."""
        from core.tick_brain import TickBrain
        result = TickBrain._parse_response('{"should_act": true, "reason": "x"}')
        self.assertNotIn("topic_key", result)

    def test_topic_key_absent_when_empty_string(self):
        """Test 9: empty-string topic_key treated as missing (falsy guard)."""
        from core.tick_brain import TickBrain
        result = TickBrain._parse_response(
            '{"should_act": true, "reason": "x", "topic_key": ""}'
        )
        self.assertNotIn("topic_key", result)

    def test_topic_key_absent_from_parse_failure_safe_mode(self):
        """Test 10: safe-mode return (parse failure) unchanged — no topic_key key."""
        from core.tick_brain import TickBrain
        result = TickBrain._parse_response("not json")
        self.assertFalse(result["should_act"])
        self.assertEqual(result["reason"], "parse_failure")
        self.assertNotIn("topic_key", result)

    def test_topic_key_coerces_non_string_to_string(self):
        """Test 11: non-string topic_key coerced via str() (defensive parsing)."""
        from core.tick_brain import TickBrain
        result = TickBrain._parse_response(
            '{"should_act": true, "reason": "x", "topic_key": 123}'
        )
        self.assertEqual(result["topic_key"], "123")


class TestGroqTokenLedgerStore(unittest.TestCase):
    """GroqTokenLedgerStore — date-keyed Groq daily-token counter (MEM-06,
    Plan 32-05 Task 1). Modeled on CostTripwireLogStore (memory/firestore_db.py);
    same _make_firestore_client-patching approach as
    tests/test_firestore_db.py::TestCostTripwireLogStore."""

    @staticmethod
    def _make_mock_client_with_collection():
        client = MagicMock()
        col = MagicMock()
        client.collection.return_value = col
        return client, col

    @staticmethod
    def _stub_missing_doc(col, doc_id):
        doc_ref = MagicMock()
        snap = MagicMock()
        snap.exists = False
        doc_ref.get.return_value = snap
        col.document.return_value = doc_ref
        return doc_ref

    @staticmethod
    def _stub_existing_doc(col, doc_id, data):
        doc_ref = MagicMock()
        snap = MagicMock()
        snap.exists = True
        snap.id = doc_id
        snap.to_dict.return_value = dict(data)
        doc_ref.get.return_value = snap
        col.document.return_value = doc_ref
        return doc_ref

    def test_ledger_increment_bumps_total_and_purpose_bucket(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            store.increment("tick", 100, 50)

        doc_ref.set.assert_called_once()
        args, kwargs = doc_ref.set.call_args
        payload = args[0]
        self.assertEqual(payload["total_tokens"].value, 150)
        self.assertEqual(payload["tick_tokens"].value, 150)
        self.assertTrue(kwargs.get("merge"))

    def test_ledger_increment_accepts_tick_autonomous_purpose(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            store.increment("tick_autonomous", 30, 20)

        doc_ref.set.assert_called_once()
        args, _ = doc_ref.set.call_args
        payload = args[0]
        self.assertEqual(payload["total_tokens"].value, 50)
        self.assertEqual(payload["tick_autonomous_tokens"].value, 50)

    def test_ledger_increment_ignores_tick_fallback_purpose(self):
        """T-32-10: a *_fallback purpose (bills Gemini) must never write to the ledger."""
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            store.increment("tick_fallback", 100, 50)
            store.increment("tick_autonomous_fallback", 100, 50)

        doc_ref.set.assert_not_called()

    def test_ledger_today_returns_empty_dict_when_missing(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        self._stub_missing_doc(col, "2026-07-22")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            self.assertEqual(store.today(), {})

    def test_ledger_today_never_raises_on_read_error(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        doc_ref.get.side_effect = RuntimeError("simulated failure")
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            self.assertEqual(store.today(), {})

    def test_ledger_today_returns_doc_dict_when_present(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        self._stub_existing_doc(
            col, "2026-07-22", {"date": "2026-07-22", "total_tokens": 160000}
        )

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            result = store.today()
        self.assertEqual(result["total_tokens"], 160000)

    def test_ledger_already_alerted_false_before_mark_alerted(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        self._stub_existing_doc(col, "2026-07-22", {"date": "2026-07-22", "total_tokens": 160000})

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            self.assertFalse(store.already_alerted("2026-07-22"))

    def test_ledger_already_alerted_false_when_doc_missing(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        self._stub_missing_doc(col, "2026-07-22")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            self.assertFalse(store.already_alerted("2026-07-22"))

    def test_ledger_already_alerted_true_after_mark_alerted(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            store.mark_alerted("2026-07-22", {"total_tokens": 165000})

        doc_ref.set.assert_called_once()
        args, kwargs = doc_ref.set.call_args
        payload = args[0]
        self.assertEqual(payload["date"], "2026-07-22")
        self.assertIn("alerted_at", payload)
        self.assertTrue(kwargs.get("merge"))

        # Simulate the doc now existing with alerted_at set for a follow-up read.
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {"alerted_at": "sentinel"}
        doc_ref.get.return_value = snap
        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            self.assertTrue(store.already_alerted("2026-07-22"))

    def test_ledger_already_alerted_returns_false_on_read_error(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        doc_ref.get.side_effect = RuntimeError("simulated failure")
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            self.assertFalse(store.already_alerted("2026-07-22"))

    def test_ledger_mark_alerted_reraises_on_write_failure(self):
        from memory import firestore_db
        client, col = self._make_mock_client_with_collection()
        doc_ref = MagicMock()
        doc_ref.set.side_effect = RuntimeError("simulated write failure")
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.GroqTokenLedgerStore("test-project")
            with self.assertRaises(RuntimeError):
                store.mark_alerted("2026-07-22", {"total_tokens": 165000})

    def test_ledger_collection_name_is_lowercase(self):
        from memory import firestore_db
        self.assertEqual(firestore_db.GroqTokenLedgerStore._COLLECTION, "groq_token_ledger")


if __name__ == "__main__":
    unittest.main()
