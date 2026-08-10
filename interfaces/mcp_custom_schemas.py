"""Dependency-free JSON Schema catalog for Klaus-specific MCP handlers."""
from __future__ import annotations

from typing import Any


_EMPTY_OBJECT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}

_QUOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "price": {"type": "number"},
        "source_url": {"type": "string", "format": "uri"},
        "source_urls": {
            "type": "array",
            "items": {"type": "string", "format": "uri"},
        },
        "observed_at": {"type": "string", "format": "date-time"},
        "conflicting": {"type": "boolean"},
    },
}


CUSTOM_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_life_snapshot": _EMPTY_OBJECT,
    "query_health_database": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sql_query": {"type": "string", "minLength": 1},
            "max_rows": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": ["sql_query"],
    },
    "list_portfolio_holdings": _EMPTY_OBJECT,
    "get_routine_status": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "correlation_id": {"type": "string", "minLength": 1},
        },
        "required": ["correlation_id"],
    },
    "upsert_portfolio_holding": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "ticker": {"type": "string", "minLength": 1},
            "exchange": {"type": "string", "minLength": 1},
            "native_currency": {"type": "string", "minLength": 1},
            "quantity": {"type": "number"},
            "position_value": {"type": "number"},
            "estimated_baseline_native": {"type": "number"},
            "estimated_cost_basis_native": {"type": "number"},
            "estimated_cost_basis": {"type": "number"},
            "brokerage_return_percent": {"type": "number"},
            "brokerage_return": {"type": "number"},
            "source_urls": {
                "type": "array",
                "items": {"type": "string", "format": "uri"},
            },
            "observed_at": {"type": "string", "format": "date-time"},
            "status": {"type": "string", "enum": ["active", "inactive"]},
        },
        "required": ["ticker", "exchange"],
        "anyOf": [
            {"required": ["quantity"]},
            {"required": ["position_value"]},
        ],
    },
    "prepare_high_risk_action": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action_type": {
                "type": "string",
                "enum": [
                    "payment",
                    "credentials_security",
                    "permanent_bulk_deletion",
                    "medical_commitment",
                    "first_time_outreach",
                ],
            },
            "payload": {"type": "object"},
            "expires_in_seconds": {"type": "integer", "minimum": 60, "maximum": 3600},
            "action_id": {"type": "string", "minLength": 1},
        },
        "required": ["action_type", "payload"],
    },
    "confirm_prepared_action": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action_id": {"type": "string", "minLength": 1},
            "payload_hash": {"type": "string", "minLength": 1},
        },
        "required": ["action_id", "payload_hash"],
    },
    "list_pending_approvals": _EMPTY_OBJECT,
    "publish_review": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "correlation_id": {"type": "string", "minLength": 1},
            "routine": {"type": "string", "enum": ["morning", "nightly", "weekly"]},
            "target_date": {"type": "string", "format": "date"},
            "text": {"type": "string", "minLength": 1},
            "structured": {"type": "object"},
            "action_ids": {"type": "array", "items": {"type": "string"}},
            "partial_actions": {"type": "array", "items": {"type": "object"}},
        },
        "required": [
            "correlation_id",
            "routine",
            "target_date",
            "text",
            "structured",
            "action_ids",
            "partial_actions",
        ],
    },
    "publish_portfolio_snapshot": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "week": {"type": "string", "format": "date"},
            "quotes": {
                "type": "object",
                "additionalProperties": _QUOTE_SCHEMA,
            },
            "fx_rates": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
            "observed_at": {"type": "string", "format": "date-time"},
        },
        "required": ["week"],
    },
}


def custom_tool_schema(name: str) -> dict[str, Any] | None:
    """Return the published inner-arguments schema for one custom MCP tool."""
    return CUSTOM_TOOL_SCHEMAS.get(name)
