"""Tests for core/pricing.py — MODEL_PRICING and compute_cost()."""
from core.pricing import compute_cost, MODEL_PRICING


def test_model_pricing_has_four_entries():
    assert len(MODEL_PRICING) == 7


def test_gemini_3_flash_preview_known_price():
    # 1M in + 1M out
    assert compute_cost("gemini-3-flash-preview", 1_000_000, 1_000_000) == 0.075 + 0.30


def test_gemini_25_flash_known_price():
    # Same rates as gemini-3-flash-preview
    assert compute_cost("gemini-2.5-flash", 1_000_000, 1_000_000) == 0.075 + 0.30


def test_haiku_known_price():
    assert compute_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == 0.80 + 4.00


def test_haiku_versioned_alias():
    assert compute_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000) == 0.80 + 4.00


def test_free_model_zero():
    # Tick-brain models ride Groq's free tier — absent from MODEL_PRICING → 0.0.
    # gpt-oss-120b is production since 2026-07-16 (qwen3-32b decommissioned by
    # Groq 2026-07-17); the legacy ids must stay free for historical LLMUsage rows.
    assert compute_cost("openai/gpt-oss-120b", 1000, 500) == 0.0
    assert compute_cost("qwen/qwen3-32b", 1000, 500) == 0.0
    assert compute_cost("qwen3-32b", 1000, 500) == 0.0


def test_unknown_model_zero_no_raise():
    result = compute_cost("unknown-xyz-model", 100, 50)
    assert result == 0.0


def test_fractional_tokens():
    # 1000 in, 500 out for gemini-3-flash-preview
    expected = (1000 / 1_000_000) * 0.075 + (500 / 1_000_000) * 0.30
    assert abs(compute_cost("gemini-3-flash-preview", 1000, 500) - expected) < 1e-12


def test_unknown_model_logs_only_once(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="core.pricing"):
        compute_cost("unique-unknown-model-abc", 100, 50)
        compute_cost("unique-unknown-model-abc", 100, 50)
    # Should have logged exactly once
    records = [r for r in caplog.records if "unique-unknown-model-abc" in r.getMessage()]
    assert len(records) == 1


# --------------------------------------------------------------------------- #
# claude-sonnet-5 — dated intro pricing + cache multipliers (BRAIN-02/05)      #
# Intro pricing $2/$10 applies through 2026-08-31; standard $3/$15 after.      #
# Today (test run date) is within the intro window per STATE.md/RESEARCH.md.  #
# --------------------------------------------------------------------------- #


def test_sonnet_5_base_price_intro_window():
    # Intro pricing active through 2026-08-31: $2/$10 per 1M tokens.
    assert compute_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 2.00 + 10.00


def test_sonnet_5_cache_read_price():
    # Cache reads price at 0.1x the input rate.
    expected = (1_000_000 / 1_000_000) * 2.00 * 0.1
    assert compute_cost(
        "claude-sonnet-5", 0, 0, cache_read_tokens=1_000_000
    ) == expected


def test_sonnet_5_cache_write_price():
    # 1h-TTL cache writes price at 2.0x the input rate.
    expected = (1_000_000 / 1_000_000) * 2.00 * 2.0
    assert compute_cost(
        "claude-sonnet-5", 0, 0, cache_write_tokens=1_000_000
    ) == expected


def test_sonnet_5_combined_base_plus_cache():
    in_tok, out_tok, cache_read, cache_write = 1_000_000, 1_000_000, 500_000, 200_000
    expected = (
        (in_tok / 1_000_000) * 2.00
        + (out_tok / 1_000_000) * 10.00
        + (cache_read / 1_000_000) * 2.00 * 0.1
        + (cache_write / 1_000_000) * 2.00 * 2.0
    )
    result = compute_cost(
        "claude-sonnet-5", in_tok, out_tok,
        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
    )
    assert abs(result - expected) < 1e-9


def test_cache_kwargs_default_zero_no_behavior_change():
    # Existing callers that don't pass cache kwargs must be unaffected.
    assert compute_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == 0.80 + 4.00
