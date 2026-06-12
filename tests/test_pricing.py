"""Tests for core/pricing.py — MODEL_PRICING and compute_cost()."""
from core.pricing import compute_cost, MODEL_PRICING


def test_model_pricing_has_four_entries():
    assert len(MODEL_PRICING) == 6


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
    # qwen3-32b is a free/open-weight model — absent from MODEL_PRICING → 0.0.
    # Both the namespaced Groq id (production since 2026-06-11) and the legacy
    # bare name must stay free.
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
