"""Regression coverage for the post-cutover runtime subtraction."""
from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import subprocess
import textwrap
import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_cleanup_guard_rejects_forbidden_runtime_markers(tmp_path: Path) -> None:
    """The deploy guard must reject SDK imports and retired configuration."""
    from scripts.check_claude_first_runtime import find_violations

    source = tmp_path / "unsafe.py"
    source.write_text(
        "import openai\n"
        "secret_name = 'TELEGRAM_BOT_TOKEN'\n"
        "legacy_module = 'core.morning_briefing'\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text("TELEGRAM_BOT_TOKEN=bad\n", encoding="utf-8")

    violations = find_violations(tmp_path)

    assert any("openai" in violation for violation in violations)
    assert any("TELEGRAM_BOT_TOKEN" in violation for violation in violations)
    assert any("core.morning_briefing" in violation for violation in violations)


@pytest.mark.parametrize(
    "content,marker",
    (
        ("GEMINI_API_KEY='bad'\n", "GEMINI_API_KEY"),
        ("import groq\n", "groq"),
        ("import core.chat_ingest\n", "core.chat_ingest"),
        (
            "SMART_AGENT_MODEL='bad'\nSMART_AGENT_DIRECT_TOOLS=set()\n",
            "SMART_AGENT_",
        ),
    ),
)
def test_cleanup_guard_rejects_bypass_cases(
    tmp_path: Path, content: str, marker: str,
) -> None:
    from scripts.check_claude_first_runtime import find_violations

    (tmp_path / "unsafe.py").write_text(content, encoding="utf-8")
    assert any(marker in violation for violation in find_violations(tmp_path))


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
    monkeypatch.setenv("KLAUS_MCP_ENABLED", "true")
    monkeypatch.setenv("KLAUS_CLAUDE_LIVE_ENABLED", "true")
    monkeypatch.setenv("KLAUS_CLAUDE_ROUTINES_ENABLED", "true")

    sys.modules.pop("interfaces.web_server", None)
    web_server = importlib.import_module("interfaces.web_server")

    assert web_server.app is not None


def test_clean_process_imports_web_server_without_local_dotenv_or_provider_keys(
    tmp_path: Path,
) -> None:
    """A fresh deploy-like interpreter must boot with no retired credentials."""
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "KLAUS_SKIP_DOTENV": "true",
        "KLAUS_USER_ID": "123456",
        "KLAUS_MCP_ENABLED": "false",
    }
    completed = subprocess.run(
        [sys.executable, "-c", "import interfaces.web_server; print('boot-ok')"],
        cwd=tmp_path,
        env=clean_env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "boot-ok"


def test_retired_web_routes_are_minimal_registered_tombstones() -> None:
    """Retired HTTP contracts stay registered without keeping dead runtimes."""
    from interfaces.web_server import app

    retired_routes = {
        ("POST", "/telegram-webhook"),
        ("POST", "/internal/process-update"),
        ("POST", "/internal/process-occasion"),
        ("POST", "/internal/process-hub-message"),
        ("POST", "/cron/proactive-alerts"),
        ("POST", "/cron/reflect"),
        ("POST", "/cron/autonomous-tick"),
        ("POST", "/cron/ingest-chats"),
        ("POST", "/cron/ingest-chat-exports"),
        ("POST", "/api/chat"),
        ("POST", "/api/chat/upload"),
        ("GET", "/api/chat/messages"),
        ("POST", "/api/chat/regenerate"),
        ("POST", "/api/chat/stop"),
    }
    registered = {
        (method, route.path): route.endpoint
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    for key in retired_routes:
        endpoint = registered[key]
        tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
        function = next(
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        assert len(function.body) <= 2, key
        assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(function)), key


def test_retired_web_and_frontend_implementations_are_physically_absent() -> None:
    """Source subtraction removes dead chat/transport bodies, not just reachability."""
    web_source = (ROOT / "interfaces" / "web_server.py").read_text(encoding="utf-8")
    tools_source = (ROOT / "core" / "tools.py").read_text(encoding="utf-8")

    for forbidden in (
        "core.hub_attachments",
        "core.scheduled_message",
        "core.chat_ingest",
        "core.chat_export_ingest",
        "core.proactive_alerts",
        "core.nightly_review",
        "core.morning_briefing",
        "core.weekly_training_review",
        "AgentOrchestrator",
        "enqueue_hub_message",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_WEBHOOK_SECRET",
    ):
        assert forbidden not in web_source

    assert "toggle_telegram_mirror" not in tools_source
    assert "telegram_mirror_enabled" not in tools_source
    assert "run_morning_briefing" not in tools_source

    firestore_source = (ROOT / "memory" / "firestore_db.py").read_text(encoding="utf-8")
    assert "class HubStreamStore" not in firestore_source
    memory_source = (ROOT / "memory" / "pinecone_db.py").read_text(encoding="utf-8")
    memory_tool_source = (ROOT / "mcp_tools" / "memory.py").read_text(encoding="utf-8")
    assert "def upsert_chat_chunks" not in memory_source
    assert "def search_chat_history" not in memory_tool_source

    retired_paths = (
        ROOT / "core" / "hub_attachments.py",
        ROOT / "core" / "chat_ingest.py",
        ROOT / "core" / "chat_export_ingest.py",
        ROOT / "mcp_tools" / "self_inspect.py",
        ROOT / "mcp_tools" / "readwise_tool.py",
        ROOT / "scripts" / "run_chat_export_backfill.sh",
        ROOT / "scripts" / "smoke_test_chat_export.py",
        ROOT / "scripts" / "smoke_test_chat_ingest.py",
        ROOT / "scripts" / "upload_chat_export.sh",
        ROOT / "scripts" / "upload_claude_logs.sh",
        ROOT / "scripts" / "upload_claude_logs.ps1",
        ROOT / "scripts" / "export_tick_logs.py",
        ROOT / "evals" / "tick_brain",
        ROOT / "tests" / "test_hub_stream_store.py",
        ROOT / "tests" / "test_chat_export_ingest.py",
        ROOT / "tests" / "test_self_inspect.py",
        ROOT / "tests" / "test_llm_usage_store.py",
        ROOT / "tests" / "test_export_tick_logs.py",
        ROOT / "tests" / "test_evals.py",
        ROOT / "tests" / "test_conversational_review_rollout.py",
        ROOT / "tests" / "memory" / "test_pinecone_upsert.py",
        ROOT / "frontend" / "src" / "api" / "chat.ts",
        ROOT / "frontend" / "src" / "components" / "chat",
        ROOT / "frontend" / "src" / "components" / "layout" / "DockChat.tsx",
        ROOT / "frontend" / "src" / "components" / "shared" / "UnreadBadge.tsx",
        ROOT / "frontend" / "src" / "hooks" / "useAppBadge.ts",
        ROOT / "frontend" / "src" / "hooks" / "useChat.ts",
        ROOT / "frontend" / "src" / "hooks" / "useUnread.ts",
    )
    assert [str(path.relative_to(ROOT)) for path in retired_paths if path.exists()] == []

    retired_store_classes = {
        "HeartbeatConfigStore",
        "IncidentStore",
        "LLMUsageStore",
        "PendingPromptStore",
        "CostTripwireLogStore",
        "GroqTokenLedgerStore",
        "TickSignatureStore",
        "OccasionInFlightStore",
        "CoachingTopicStore",
        "TickLogStore",
    }
    assert not any(
        f"class {name}" in firestore_source for name in retired_store_classes
    )


def test_nightly_target_date_is_a_retained_deterministic_helper() -> None:
    """Both nightly trigger entrypoints must use a helper independent of old code."""
    from interfaces.web_server import nightly_target_date_now

    assert len(nightly_target_date_now()) == 10


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
