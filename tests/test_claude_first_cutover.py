"""Regression tests for the deterministic Claude-first runtime cutover."""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


_ENV = {
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _web_server():
    """Import the HTTP boundary with its legacy SDKs isolated."""
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    sys.modules.pop("interfaces.web_server", None)
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as web_server
    return web_server


def test_deterministic_alerts_is_the_canonical_scheduler_endpoint(monkeypatch):
    """A scheduler tick evaluates explicit rules without booting legacy runtime."""
    web_server = _web_server()
    evaluator = AsyncMock(return_value={"evaluated": 2, "sent": 1, "quiet_hours": False})
    deterministic = MagicMock(run_rule_evaluator=evaluator)
    web_server._log_cron_run = MagicMock()
    web_server._application = None

    with patch.dict(os.environ, _ENV), patch.dict(
        sys.modules, {"core.deterministic_alerts": deterministic}
    ):
        response = TestClient(web_server.app).post("/cron/deterministic-alerts")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "evaluated": 2, "sent": 1, "quiet_hours": False}
    evaluator.assert_awaited_once()
    web_server._log_cron_run.assert_called_once_with("deterministic-alerts", ok=True)


def test_deterministic_endpoint_does_not_depend_on_model_or_telegram_runtime():
    """Adding an old runtime import to the scheduler boundary must fail this guard."""
    import ast
    import inspect
    import interfaces.web_server as web_server

    source = inspect.getsource(web_server.cron_deterministic_alerts)
    names = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden = {"core.autonomous", "core.llm_client", "core.pricing", "core.scheduled_message"}
    assert names.isdisjoint(forbidden)


def test_startup_only_initializes_retained_claude_mcp_runtime():
    """A cold start cannot resurrect the Telegram/agent singleton runtime."""
    import inspect

    web_server = _web_server()
    source = inspect.getsource(web_server.lifespan)
    assert "AgentOrchestrator" not in source
    assert "Application" not in source
    assert "telegram" not in source.lower()


def test_hub_chat_is_a_hard_tombstone_even_if_a_legacy_flag_is_set(monkeypatch):
    """An accidental environment override cannot restore Hub generative chat."""
    web_server = _web_server()
    monkeypatch.setenv("KLAUS_HUB_CHAT_ENABLED", "true")
    with pytest.raises(web_server.HTTPException) as exc_info:
        web_server._require_legacy_hub_chat()
    assert exc_info.value.status_code == 410


@pytest.mark.parametrize(
    "path",
    [
        "/cron/autonomous-tick",
        "/telegram-webhook",
        "/cron/reflect",
        "/cron/ingest-chats",
        "/cron/ingest-chat-exports",
        "/internal/process-update",
        "/internal/process-hub-message",
        "/internal/process-occasion",
    ],
)
def test_removed_runtime_paths_are_gone(path):
    """Removed processors are explicit tombstones rather than silent fallbacks."""
    web_server = _web_server()
    with patch.dict(os.environ, _ENV):
        response = TestClient(web_server.app, raise_server_exceptions=False).post(path)
    assert response.status_code == 410


def test_weekly_cutover_is_enabled_with_the_other_claude_routines(monkeypatch):
    """Weekly must use Remote Claude when the verified routine runtime is on."""
    web_server = _web_server()
    env = {
        **_ENV,
        "KLAUS_MCP_ENABLED": "true",
        "KLAUS_CLAUDE_ROUTINES_ENABLED": "true",
        "KLAUS_CAPABILITY_MCP_VERIFIED": "true",
        "KLAUS_CAPABILITY_SKILL_VERIFIED": "true",
        "KLAUS_CAPABILITY_ROUTINE_VERIFIED": "true",
        "KLAUS_CAPABILITY_PUBLISH_VERIFIED": "true",
        "KLAUS_ROUTINE_MORNING_CUTOVER": "true",
        "KLAUS_ROUTINE_NIGHTLY_CUTOVER": "true",
        "KLAUS_ROUTINE_WEEKLY_CUTOVER": "true",
    }
    with patch.dict(os.environ, env):
        assert all(web_server._routine_cutover_enabled(name) for name in ("morning", "nightly", "weekly"))


def test_task_store_refuses_firestore_as_an_authority(monkeypatch):
    """TASK_BACKEND cannot silently switch task reads and writes away from Things."""
    from memory.things_store import ThingsTaskStore
    from memory.firestore_db import get_task_store

    monkeypatch.setenv("TASK_BACKEND", "firestore")
    assert isinstance(get_task_store("project", "database"), ThingsTaskStore)


def test_things_failure_is_visible_instead_of_serving_the_firestore_mirror():
    """The mirror is a sync/outbox aid, never an outage authority."""
    from mcp_tools.things_tool import ThingsUnavailableError
    from memory.things_store import ThingsTaskStore
    import memory.things_store as things_store

    things_store.reset_cache()
    store = ThingsTaskStore("project", "database")
    with patch.object(things_store.things, "fetch_history_key", side_effect=ThingsUnavailableError("down")):
        with pytest.raises(ThingsUnavailableError, match="down"):
            store.list()
