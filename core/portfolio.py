"""Deterministic portfolio valuation helpers used by the weekly Claude routine."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _last_holding(last_valid: dict | None, holding_id: str) -> dict | None:
    for holding in (last_valid or {}).get("holdings") or []:
        if str(holding.get("id") or "") == holding_id:
            return holding
    return None


def build_portfolio_snapshot(
    *,
    week: str,
    holdings: list[dict],
    quotes: dict[str, dict],
    fx_rates: dict[str, Any],
    last_valid: dict | None,
    observed_at: str,
) -> dict:
    """Value holdings in ILS while disclosing estimates and stale fallbacks."""
    valued: list[dict] = []
    warnings: list[str] = []
    source_urls: list[str] = []

    for raw in holdings:
        holding = dict(raw)
        holding_id = str(
            holding.get("id")
            or f"{holding.get('exchange', '')}-{holding.get('ticker', '')}".lower()
        )
        currency = str(holding.get("native_currency") or "").upper()
        quote = dict(quotes.get(holding_id) or quotes.get(str(holding.get("ticker") or "")) or {})
        quote_urls = [str(url) for url in quote.get("source_urls") or []]
        if quote.get("source_url"):
            quote_urls.append(str(quote["source_url"]))
        source_urls.extend(quote_urls)

        quantity = _number(holding.get("quantity"))
        price = _number(quote.get("price"))
        position_value = _number(holding.get("position_value"))
        conflicting = bool(quote.get("conflicting"))
        if conflicting:
            warnings.append(f"{holding_id}: conflicting quote sources; no quote selected silently")

        value_native = None
        if not conflicting and quantity is not None and price is not None:
            value_native = quantity * price
        elif not conflicting and position_value is not None:
            value_native = position_value

        fx_key = f"{currency}_ILS"
        fx = 1.0 if currency == "ILS" else _number(fx_rates.get(fx_key))
        value_ils = value_native * fx if value_native is not None and fx is not None else None
        valuation_status = "current"
        if value_ils is None:
            previous = _last_holding(last_valid, holding_id)
            previous_ils = _number((previous or {}).get("value_ils"))
            if previous_ils is None:
                warnings.append(f"{holding_id}: quote or FX unavailable and no last valid valuation exists")
                valuation_status = "unavailable"
            else:
                value_ils = previous_ils
                valuation_status = "last_valid_fallback"
                warnings.append(f"{holding_id}: using last valid ILS valuation")

        baseline_native = None
        for field in (
            "estimated_baseline_native",
            "estimated_cost_basis_native",
            "estimated_cost_basis",
        ):
            baseline_native = _number(holding.get(field))
            if baseline_native is not None:
                break
        baseline_is_estimated = baseline_native is not None
        if baseline_native is None and value_native is not None:
            return_percent = _number(holding.get("brokerage_return_percent"))
            if return_percent is None:
                return_percent = _number(holding.get("brokerage_return"))
            if return_percent is not None and return_percent > -100:
                baseline_native = value_native / (1 + return_percent / 100)
                baseline_is_estimated = True
        baseline_ils = (
            baseline_native * fx
            if baseline_native is not None and fx is not None
            else None
        )
        valued.append(
            {
                **holding,
                "id": holding_id,
                "quote_price": price,
                "value_native": value_native,
                "value_ils": value_ils,
                "fx_rate_to_ils": fx,
                "estimated_baseline_ils": baseline_ils,
                "baseline_is_estimated": baseline_is_estimated,
                "valuation_status": valuation_status,
                "source_urls": quote_urls,
                "observed_at": quote.get("observed_at") or observed_at,
            }
        )

    available_values = [
        float(item["value_ils"])
        for item in valued
        if item.get("value_ils") is not None
    ]
    total_ils = sum(available_values)
    previous_total = _number((last_valid or {}).get("total_ils"))
    return {
        "week": week,
        "total_ils": total_ils,
        "weekly_pnl_ils": total_ils - previous_total if previous_total is not None else None,
        "holdings": valued,
        "fx_rates": dict(fx_rates),
        "source_urls": list(dict.fromkeys(source_urls)),
        "observed_at": observed_at,
        "warnings": warnings,
        "fallback_from_week": (
            (last_valid or {}).get("week")
            if any(item["valuation_status"] == "last_valid_fallback" for item in valued)
            else None
        ),
    }
