"""Security-focused tests for production MCP handler wiring."""
from __future__ import annotations

import pytest


def test_redaction_and_prepared_action_guard_find_nested_secret_aliases():
    from interfaces.mcp_runtime import _redact, _reject_embedded_secrets

    payload = {
        "request": {
            "headers": [
                {"access_token": "raw-token"},
                {"client-secret": "raw-secret"},
            ]
        }
    }

    assert _redact(payload) == {
        "request": {
            "headers": [
                {"access_token": "[REDACTED]"},
                {"client-secret": "[REDACTED]"},
            ]
        }
    }
    with pytest.raises(ValueError, match="raw secrets"):
        _reject_embedded_secrets(payload)
