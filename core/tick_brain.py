"""Tick-brain: a free Groq/Qwen3-32B reasoning client for the heartbeat and autonomous engine.

The tick-brain performs quick judgment passes over raw health signals or situation
snapshots. It uses the Groq free tier (OpenAI-compatible) and falls back to the
main Gemini brain on LLMError or rate-limit.

Env vars:
    TICK_BRAIN_BACKEND   — "openai" (default; Groq is OpenAI-compatible)
    TICK_BRAIN_MODEL     — e.g. "qwen3-32b" (default)
    TICK_BRAIN_API_KEY   — Groq API key (required; stored in GCP Secret Manager)
    TICK_BRAIN_BASE_URL  — Groq base URL (default: https://api.groq.com/openai/v1)

Fallback uses:
    SMART_AGENT_BACKEND / SMART_AGENT_MODEL / SMART_AGENT_API_KEY
"""
from __future__ import annotations

import json
import logging
import os

from core.llm_client import LLMClient, LLMError

logger = logging.getLogger(__name__)

_DEFAULT_BACKEND  = "openai"
_DEFAULT_MODEL    = "qwen3-32b"
_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

_TICK_SYSTEM_PROMPT = """\
You are Klaus's judgment layer. You receive raw health signals or situation data.
Your job: decide whether the situation warrants action and, if so, draft a short message.

Always respond with valid JSON and nothing else:
{
  "should_act": true | false,
  "reason": "<one-sentence explanation>",
  "draft": "<optional short message draft, omit if should_act is false>"
}

Rules:
- Prefer silence. Only return should_act=true when something genuinely needs attention.
- If uncertain, return should_act=false.
- Keep draft under 200 characters if included.
"""


class TickBrain:
    """Groq/Qwen3-32B judgment client with Gemini fallback.

    Usage:
        brain = TickBrain()
        result = brain.think("Signal: 2 cron jobs stale for 3h. Daily digest day.")
        if result["should_act"]:
            message = result.get("draft", "Attention needed.")
    """

    def __init__(self) -> None:
        """Initialise primary (Groq) and fallback (Gemini brain) clients.

        Reads all config from environment variables. Never raises on missing
        fallback vars — fallback client is set to None if vars are absent.

        Raises:
            ValueError: If TICK_BRAIN_API_KEY is not set.
        """
        api_key = os.getenv("TICK_BRAIN_API_KEY")
        if not api_key:
            raise ValueError(
                "TICK_BRAIN_API_KEY is required. "
                "Set it in .env (dev) or GCP Secret Manager (Cloud Run)."
            )

        backend  = os.getenv("TICK_BRAIN_BACKEND",  _DEFAULT_BACKEND)
        model    = os.getenv("TICK_BRAIN_MODEL",    _DEFAULT_MODEL)
        base_url = os.getenv("TICK_BRAIN_BASE_URL", _DEFAULT_BASE_URL)

        self._client = LLMClient(
            backend=backend,
            model=model,
            api_key=api_key,
            base_url=base_url if backend == "openai" else None,
        )
        self._model = model

        # Fallback: main brain (Gemini). Optional — skipped if vars absent.
        fallback_backend = os.getenv("SMART_AGENT_BACKEND")
        fallback_model   = os.getenv("SMART_AGENT_MODEL")
        fallback_key     = os.getenv("SMART_AGENT_API_KEY")
        if fallback_backend and fallback_model and fallback_key:
            self._fallback_client: LLMClient | None = LLMClient(
                backend=fallback_backend,
                model=fallback_model,
                api_key=fallback_key,
            )
            self._fallback_model = fallback_model
        else:
            self._fallback_client = None
            self._fallback_model  = None

    def think(self, prompt: str,
              tools: list[dict] | None = None,
              system_override: str | None = None) -> dict:
        """Run a judgment pass over the given prompt.

        Args:
            prompt: A plain-text description of the situation to evaluate.
            tools:  Optional tool schemas (passed through to LLMClient; usually None for tick).
            system_override: When set, replaces _TICK_SYSTEM_PROMPT for this call
                (e.g., autonomous tick passes prompts/autonomous_triage.md).
                Also flips purpose from 'tick' to 'tick_autonomous' for cost
                metering granularity (Phase 18 D-04).

        Purpose-string layering (WARNING 1 — preserves Phase 14 INFRA-02 visibility):
            override=None  -> primary 'tick',            fallback 'tick_fallback'
            override=...   -> primary 'tick_autonomous', fallback 'tick_autonomous_fallback'

        Returns:
            A dict with:
                should_act (bool):  Whether the situation warrants action.
                reason     (str):   One-sentence explanation.
                draft      (str):   Optional message draft (only when should_act=True).
                topic_key  (str):   Optional outreach category slug (autonomous path; D-07).

            On any failure, returns safe mode: {should_act: False, reason: <failure_type>}.
        """
        messages = [{"role": "user", "content": prompt}]
        active_system = system_override if system_override is not None else _TICK_SYSTEM_PROMPT
        # WARNING 1 fix — layered purpose strings keep 'tick_fallback' visible
        # in LLMUsageStore for Phase 14 INFRA-02 heartbeat-fallback-rate metrics.
        primary_purpose = "tick_autonomous" if system_override is not None else "tick"
        fallback_purpose = primary_purpose + "_fallback"

        # Try primary (Groq).
        response = None
        try:
            response = self._client.chat(
                messages,
                system=active_system,
                tools=tools,
                purpose=primary_purpose,
            )
        except LLMError as exc:
            logger.warning(
                "tick-brain: primary LLMError (%s) — trying fallback", exc, exc_info=False
            )
        except Exception as exc:
            logger.warning("tick-brain: unexpected primary error: %s", exc, exc_info=True)

        # Try fallback (Gemini brain) if primary failed.
        if response is None:
            if self._fallback_client is None:
                logger.warning("tick-brain: no fallback configured — safe mode")
                return {"should_act": False, "reason": "llm_error"}
            try:
                logger.info("tick-brain: retrying with fallback (%s)", self._fallback_model)
                response = self._fallback_client.chat(
                    messages,
                    system=active_system,
                    tools=tools,
                    purpose=fallback_purpose,
                )
            except LLMError as exc:
                logger.error("tick-brain: fallback also failed: %s", exc)
                return {"should_act": False, "reason": "llm_error"}
            except Exception as exc:
                logger.error("tick-brain: fallback unexpected error: %s", exc, exc_info=True)
                return {"should_act": False, "reason": "llm_error"}

        # Parse the JSON response.
        return self._parse_response(response.get("text") or "")

    @staticmethod
    def _parse_response(text: str) -> dict:
        """Parse the LLM's JSON response. Returns safe mode on any parse failure."""
        text = text.strip()
        # Strip markdown code fences if present (some models wrap JSON in ```json ... ```)
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("tick-brain: JSON parse failure; safe mode. Raw: %.200s", text)
            return {"should_act": False, "reason": "parse_failure"}

        if not isinstance(data, dict) or "should_act" not in data:
            logger.warning("tick-brain: missing 'should_act' key; safe mode")
            return {"should_act": False, "reason": "parse_failure"}

        result = {
            "should_act": bool(data.get("should_act", False)),
            "reason":     str(data.get("reason", "")),
        }
        if "draft" in data and data["draft"]:
            result["draft"] = str(data["draft"])
        # D-07 — pass through topic_key for autonomous tick repeat-suppression.
        # Falsy values (empty string, None) treated as missing; downstream
        # (core/autonomous.py) synthesises a fallback slug when absent.
        if "topic_key" in data and data["topic_key"]:
            result["topic_key"] = str(data["topic_key"])
        return result
