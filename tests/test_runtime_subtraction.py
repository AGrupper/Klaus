"""Regression coverage for the post-cutover runtime subtraction."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_cleanup_guard_rejects_forbidden_runtime_markers(tmp_path: Path) -> None:
    """The deploy guard must reject SDK imports and retired configuration."""
    from scripts.check_claude_first_runtime import find_violations

    source = tmp_path / "unsafe.py"
    source.write_text("import openai\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TELEGRAM_BOT_TOKEN=bad\n", encoding="utf-8")

    violations = find_violations(tmp_path)

    assert any("openai" in violation for violation in violations)
    assert any("TELEGRAM_BOT_TOKEN" in violation for violation in violations)


def test_cleanup_guard_accepts_the_checked_in_runtime() -> None:
    """Current deployable code has no legacy generative or Telegram residue."""
    from scripts.check_claude_first_runtime import find_violations

    assert find_violations(ROOT) == []


def test_web_server_imports_without_retired_provider_credentials(monkeypatch) -> None:
    """Cold start must not need model or Telegram credentials."""
    forbidden = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "SMART_AGENT_API_KEY",
        "SMART_AGENT_BACKEND",
        "SMART_AGENT_MODEL",
        "SMART_AGENT_FALLBACK_API_KEY",
        "TICK_BRAIN_API_KEY",
        "TICK_BRAIN_BACKEND",
        "TICK_BRAIN_MODEL",
        "WORKER_AGENT_API_KEY",
        "WORKER_AGENT_BACKEND",
        "WORKER_AGENT_MODEL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "TELEGRAM_ALLOWED_USER_IDS",
    )
    for name in forbidden:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KLAUS_USER_ID", "123456")
    monkeypatch.setenv("KLAUS_MCP_ENABLED", "false")

    sys.modules.pop("interfaces.web_server", None)
    web_server = importlib.import_module("interfaces.web_server")

    assert web_server.app is not None


def test_single_user_identity_requires_explicit_provider_neutral_setting(monkeypatch) -> None:
    """MCP namespaces never fall back to the former transport user-id setting."""
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456")
    with pytest.raises(RuntimeError, match="KLAUS_USER_ID"):
        _resolve_single_user_id()

    monkeypatch.setenv("KLAUS_USER_ID", "123456")
    assert _resolve_single_user_id() == 123456


def test_google_oauth_always_requests_calendar_and_rejects_stale_gmail_token() -> None:
    """A broad cached token must re-consent instead of silently retaining Gmail."""
    from unittest.mock import MagicMock, patch

    from core.auth_google import CALENDAR_SCOPE, GoogleAuthManager

    token_storage = MagicMock()
    token_storage.load.return_value = json.dumps({
        "scopes": ["https://www.googleapis.com/auth/gmail.modify", CALENDAR_SCOPE],
    })
    manager = GoogleAuthManager("unused", token_storage)
    stale_credentials = MagicMock()

    assert manager.scopes == [CALENDAR_SCOPE]
    with patch(
        "core.auth_google.Credentials.from_authorized_user_info",
        return_value=stale_credentials,
    ):
        assert manager._load_cached_token() is None
