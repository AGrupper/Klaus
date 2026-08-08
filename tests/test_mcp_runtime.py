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


def test_resolve_single_user_id_prefers_explicit_setting(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.setenv("KLAUS_USER_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111,222")
    assert _resolve_single_user_id() == 123456789


def test_resolve_single_user_id_uses_first_valid_legacy_value(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "invalid, 123456789, 999")
    assert _resolve_single_user_id() == 123456789


@pytest.mark.parametrize("environment", ["development", "test"])
@pytest.mark.parametrize("legacy_value", ["", "not-a-number", "0", "-1"])
def test_resolve_single_user_id_rejects_invalid_legacy_setting_outside_production(
    monkeypatch, environment, legacy_value
):
    """Configured legacy identities must not silently create namespace zero."""
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", legacy_value)
    monkeypatch.setenv("ENVIRONMENT", environment)

    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
        _resolve_single_user_id()


@pytest.mark.parametrize("value", ["", "not-a-number", "0", "-1"])
def test_resolve_single_user_id_rejects_invalid_explicit_setting(monkeypatch, value):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.setenv("KLAUS_USER_ID", value)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
    with pytest.raises(RuntimeError, match="KLAUS_USER_ID"):
        _resolve_single_user_id()


def test_resolve_single_user_id_fails_closed_in_production(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="canonical Klaus user ID"):
        _resolve_single_user_id()


def test_resolve_single_user_id_retains_local_default(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert _resolve_single_user_id() == 0


def test_dispatch_for_single_user_sets_identity_before_dispatch(monkeypatch):
    import core.tools
    from interfaces.mcp_runtime import dispatch_for_single_user

    observed = []
    monkeypatch.setenv("KLAUS_USER_ID", "123456789")
    monkeypatch.setattr(
        core.tools,
        "set_current_user_id",
        lambda user_id: observed.append(("identity", user_id)),
    )
    monkeypatch.setattr(
        core.tools,
        "dispatch",
        lambda tool_name, arguments: observed.append(
            ("dispatch", tool_name, arguments)
        )
        or "result",
    )

    assert dispatch_for_single_user("recall", {"query": "history"}) == "result"
    assert observed == [
        ("identity", 123456789),
        ("dispatch", "recall", {"query": "history"}),
    ]


def test_production_bundle_uses_identity_aware_dispatcher(monkeypatch):
    import interfaces.mcp_runtime as runtime
    import memory.firestore_db

    captured = {}
    monkeypatch.setattr(
        memory.firestore_db,
        "ActionIdempotencyStore",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        runtime,
        "create_mcp_bundle",
        lambda oauth_service, **kwargs: captured.update(kwargs) or "bundle",
    )

    assert runtime.create_production_mcp_bundle(object()) == "bundle"
    assert captured["dispatcher"] is runtime.dispatch_for_single_user
