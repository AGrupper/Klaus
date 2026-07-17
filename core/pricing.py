"""LLM cost computation.

MODEL_PRICING maps model ID → {input, output} USD per 1M tokens.
Free/open-weight models (Groq, self-hosted) are intentionally absent — they return 0.0.
Unknown models also return 0.0 and log once; they never raise.

claude-sonnet-5 uses dated intro pricing ($2/$10 through 2026-08-31, then $3/$15
standard) — see _SONNET_5_INTRO_CUTOFF below. [CITED:
platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5]
"""
from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)

# claude-sonnet-5 intro pricing ($2/$10 per 1M in/out) applies through this date
# (inclusive); standard pricing ($3/$15) applies after. Re-verify against
# platform.claude.com if this module is touched after the cutover date.
_SONNET_5_INTRO_CUTOFF = datetime.date(2026, 8, 31)
_SONNET_5_INTRO_PRICE = {"input": 2.00, "output": 10.00}
_SONNET_5_STANDARD_PRICE = {"input": 3.00, "output": 15.00}


def _sonnet_5_pricing(today: datetime.date | None = None) -> dict[str, float]:
    """Return the currently-active claude-sonnet-5 input/output rate.

    Intro pricing ($2/$10) is active through _SONNET_5_INTRO_CUTOFF (inclusive);
    standard pricing ($3/$15) applies the day after.
    """
    today = today or datetime.date.today()
    if today <= _SONNET_5_INTRO_CUTOFF:
        return _SONNET_5_INTRO_PRICE
    return _SONNET_5_STANDARD_PRICE


# USD per 1 million tokens.
# Prices sourced from provider pricing pages as of 2026-05 (claude-sonnet-5
# confirmed 2026-07-17 — see _sonnet_5_pricing for the dated intro mechanism).
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Current roster
    "gemini-3.5-flash":          {"input": 0.40,  "output": 1.50},
    "deepseek-v4-flash":         {"input": 0.11,  "output": 0.22},
    "claude-haiku-4-5":          {"input": 0.80,  "output": 4.00},
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    # claude-sonnet-5: dated intro-vs-standard pricing. This row holds the
    # CURRENT rate for entry-count/grep purposes; compute_cost() always
    # resolves the live rate via _sonnet_5_pricing() (dated intro through
    # 2026-08-31, then standard) rather than reading this row directly.
    "claude-sonnet-5":           _sonnet_5_pricing(),
    # Legacy models (kept for in-flight log accuracy)
    "gemini-3-flash-preview":    {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash":          {"input": 0.075, "output": 0.30},
    # Free models (Groq / open-weight) intentionally absent → 0.0 by design.
    # Unknown models → 0.0 + log once.
}

_SONNET_5_MODEL_ID = "claude-sonnet-5"

_logged_unknown: set[str] = set()


def _pricing_for(model: str) -> dict[str, float] | None:
    """Resolve the active input/output rate dict for a model, or None if unpriced."""
    if model == _SONNET_5_MODEL_ID:
        return _sonnet_5_pricing()
    return MODEL_PRICING.get(model)


def compute_cost(model: str, in_tokens: int, out_tokens: int,
                  cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    """Return the USD cost for one LLM call.

    Args:
        model:     Provider-specific model ID.
        in_tokens: Input (prompt) token count for this call.
        out_tokens: Output (completion) token count for this call.
        cache_read_tokens:  Anthropic prompt-cache read tokens (0.1x input rate).
        cache_write_tokens: Anthropic prompt-cache write tokens, 1h TTL (2.0x input rate).

    Returns:
        Computed cost in USD. Returns 0.0 for free or unpriced models — never raises.
    """
    pricing = _pricing_for(model)
    if pricing is None:
        if model not in _logged_unknown:
            _logged_unknown.add(model)
            logger.info("compute_cost: no pricing for model '%s' — returning 0.0", model)
        return 0.0
    cost = (in_tokens / 1_000_000) * pricing["input"] \
         + (out_tokens / 1_000_000) * pricing["output"] \
         + (cache_read_tokens / 1_000_000) * pricing["input"] * 0.1 \
         + (cache_write_tokens / 1_000_000) * pricing["input"] * 2.0  # 1h TTL multiplier
    return cost
