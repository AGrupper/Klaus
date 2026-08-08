"""Deterministic portfolio valuation and fallback behavior."""
from __future__ import annotations


def test_portfolio_values_quotes_converts_to_ils_and_estimates_baseline():
    from core.portfolio import build_portfolio_snapshot

    result = build_portfolio_snapshot(
        week="2026-08-09",
        holdings=[
            {
                "id": "nyse-voo",
                "ticker": "VOO",
                "exchange": "NYSE",
                "quantity": 2,
                "native_currency": "USD",
                "brokerage_return_percent": 10,
            }
        ],
        quotes={"nyse-voo": {"price": 500, "source_url": "https://quote.test/voo"}},
        fx_rates={"USD_ILS": 3.7},
        last_valid=None,
        observed_at="2026-08-08T12:00:00Z",
    )

    holding = result["holdings"][0]
    assert holding["value_native"] == 1000
    assert holding["value_ils"] == 3700
    assert round(holding["estimated_baseline_ils"], 2) == 3363.64
    assert holding["baseline_is_estimated"] is True
    assert result["total_ils"] == 3700


def test_portfolio_accepts_onboarding_field_names_for_cost_basis_and_return():
    from core.portfolio import build_portfolio_snapshot

    explicit = build_portfolio_snapshot(
        week="2026-08-09",
        holdings=[{
            "id": "nasdaq-msft",
            "ticker": "MSFT",
            "exchange": "NASDAQ",
            "quantity": 2,
            "native_currency": "USD",
            "estimated_cost_basis": 700,
        }],
        quotes={"nasdaq-msft": {"price": 400}},
        fx_rates={"USD_ILS": 3.5},
        last_valid=None,
        observed_at="2026-08-08T12:00:00Z",
    )
    derived = build_portfolio_snapshot(
        week="2026-08-09",
        holdings=[{
            "id": "nasdaq-msft",
            "ticker": "MSFT",
            "exchange": "NASDAQ",
            "quantity": 2,
            "native_currency": "USD",
            "brokerage_return": 10,
        }],
        quotes={"nasdaq-msft": {"price": 400}},
        fx_rates={"USD_ILS": 3.5},
        last_valid=None,
        observed_at="2026-08-08T12:00:00Z",
    )

    assert explicit["holdings"][0]["estimated_baseline_ils"] == 2450
    assert round(derived["holdings"][0]["estimated_baseline_ils"], 2) == 2545.45


def test_missing_or_conflicting_quote_is_disclosed_and_uses_last_valid_value():
    from core.portfolio import build_portfolio_snapshot

    result = build_portfolio_snapshot(
        week="2026-08-09",
        holdings=[
            {"id": "tase-abc", "ticker": "ABC", "exchange": "TASE", "quantity": 4, "native_currency": "ILS"}
        ],
        quotes={"tase-abc": {"conflicting": True, "source_urls": ["https://a", "https://b"]}},
        fx_rates={},
        last_valid={"week": "2026-08-02", "total_ils": 1200, "holdings": [{"id": "tase-abc", "value_ils": 1200}]},
        observed_at="2026-08-08T12:00:00Z",
    )

    holding = result["holdings"][0]
    assert holding["value_ils"] == 1200
    assert holding["valuation_status"] == "last_valid_fallback"
    assert any("conflicting" in warning for warning in result["warnings"])
    assert result["weekly_pnl_ils"] == 0
