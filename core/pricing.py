"""LLM cost computation.

MODEL_PRICING maps model ID → {input, output} USD per 1M tokens.
Free/open-weight models (Groq, self-hosted) are intentionally absent — they return 0.0.
Unknown models also return 0.0 and log once; they never raise.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# USD per 1 million tokens.
# Prices sourced from provider pricing pages as of 2026-05.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Current roster
    "gemini-3.5-flash":          {"input": 0.40,  "output": 1.50},
    "deepseek-v4-flash":         {"input": 0.11,  "output": 0.22},
    "claude-haiku-4-5":          {"input": 0.80,  "output": 4.00},
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    # Legacy models (kept for in-flight log accuracy)
    "gemini-3-flash-preview":    {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash":          {"input": 0.075, "output": 0.30},
    # Free models (Groq / open-weight) intentionally absent → 0.0 by design.
    # Unknown models → 0.0 + log once.
}

_logged_unknown: set[str] = set()


def compute_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """Return the USD cost for one LLM call.

    Args:
        model:     Provider-specific model ID.
        in_tokens: Input (prompt) token count for this call.
        out_tokens: Output (completion) token count for this call.

    Returns:
        Computed cost in USD. Returns 0.0 for free or unpriced models — never raises.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        if model not in _logged_unknown:
            _logged_unknown.add(model)
            logger.info("compute_cost: no pricing for model '%s' — returning 0.0", model)
        return 0.0
    cost = (in_tokens / 1_000_000) * pricing["input"] + \
           (out_tokens / 1_000_000) * pricing["output"]
    return cost
