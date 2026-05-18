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
                self.assertEqual(primary_call["model"], "qwen3-32b")
                self.assertEqual(primary_call["base_url"], "https://api.groq.com/openai/v1")


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


if __name__ == "__main__":
    unittest.main()
