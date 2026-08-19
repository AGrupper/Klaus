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
}


def _web_server():
    """Import a fresh copy of the retained HTTP boundary."""
    sys.modules.pop("interfaces.web_server", None)
    import interfaces.web_server as web_server
    return web_server


def test_deterministic_alerts_is_the_canonical_scheduler_endpoint(monkeypatch):
    """A scheduler tick evaluates explicit rules without booting legacy runtime."""
    web_server = _web_server()
    evaluator = AsyncMock(return_value={"evaluated": 2, "sent": 1, "reminders_sent": 0})
    deterministic = MagicMock(run_rule_evaluator=evaluator)
    web_server._application = None

    with patch.dict(os.environ, _ENV), patch.dict(
        sys.modules, {"core.routines.alerts": deterministic}
    ), patch("interfaces.routes.cron._log_cron_run") as log_cron_run:
        response = TestClient(web_server.app).post("/cron/deterministic-alerts")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "evaluated": 2, "sent": 1, "reminders_sent": 0}
    evaluator.assert_awaited_once()
    log_cron_run.assert_called_once_with("deterministic-alerts", ok=True)


def test_deterministic_endpoint_does_not_depend_on_model_or_telegram_runtime():
    """Adding an old runtime import to the scheduler boundary must fail this guard."""
    import ast
    import inspect
    import interfaces.web_server as web_server

    source = inspect.getsource(
        __import__("interfaces.routes.cron", fromlist=["cron_deterministic_alerts"]).cron_deterministic_alerts
    )
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


_FORBIDDEN_DETERMINISTIC_MODULES = (
    "core.autonomous",
    "core.llm_client",
    "core.pricing",
    "core.scheduled_message",
    "core.tick_brain",
    "telegram",
)
_FORBIDDEN_DETERMINISTIC_CALLS = {
    "AgentOrchestrator",
    "LLMClient",
    "LLMUsageStore",
    "compute_cost",
    "run_autonomous_tick",
    "send_and_inject",
}


def _life_snapshot_dispatch_nodes(tools):
    """Resolve Life Snapshot's string tool keys through the live handler table."""
    import inspect

    nodes = []
    for tool_name in ("task_list", "get_habit_adherence", "get_self_status"):
        # The registry maps a name to exactly one handler function. Before the
        # package split this was a lambda over module globals, so the closure had
        # to be inspected to find the handler behind it; the mapping is direct now.
        registered = tools.registered_tools()[tool_name]
        referenced = [registered] if inspect.isfunction(registered) else []
        assert len(referenced) == 1, (
            f"{tool_name} must map to exactly one retained handler", referenced
        )
        nodes.append((f"core.tools registry[{tool_name!r}]", referenced[0]))
    return tuple(nodes)


def _deterministic_execution_nodes():
    """Return the concrete default call closure of deterministic alerts.

    This is intentionally an explicit retained-function allowlist rather than a
    whole-module scan: ``interfaces.web_server`` and ``core.tools`` still carry
    unreachable legacy bodies pending Task 2. These nodes are the only
    functions the evaluator reaches through its default loaders.
    """
    import core.routines.alerts as deterministic
    import core.routines.heartbeat as heartbeat
    import core.life_snapshot as life_snapshot
    import core.push_sender as push_sender
    import core.tools as tools
    import interfaces.web_server as hub

    return (
        ("core.routines.alerts", deterministic.run_rule_evaluator),
        ("core.routines.heartbeat", heartbeat.collect_deterministic_signals),
        ("core.routines.heartbeat", heartbeat._read_cron_ledger),
        ("core.routines.heartbeat", heartbeat._as_utc),
        ("core.routines.heartbeat", heartbeat.check_cron_health),
        ("core.routines.heartbeat", heartbeat.check_mcp_routine_health),
        ("core.routines.heartbeat", heartbeat._check_push_health),
        ("core.routines.heartbeat", heartbeat.check_deployment_identity),
        ("core.life_snapshot", life_snapshot.build_life_snapshot),
        ("core.life_snapshot", life_snapshot._normalized_hub_today),
        ("core.life_snapshot", life_snapshot._default_directives_loader),
        ("core.life_snapshot", life_snapshot._default_reviews_loader),
        ("core.push_sender", push_sender.send_push_to_all),
        ("core.push_sender", push_sender._get_vapid_private_key),
        ("core.push_sender", push_sender._get_subscription_store),
        ("core.push_sender", push_sender._safe_destination),
        ("core.tools", tools.dispatch),
        *_life_snapshot_dispatch_nodes(tools),
        ("core.tools", tools._get_task_store),
        ("core.tools", tools._get_habit_store),
        ("core.tools", tools._task_today_iso),
        ("interfaces.web_server", hub._today_calendar),
        ("interfaces.web_server", hub._today_garmin),
        ("interfaces.web_server", hub._today_weather),
        ("interfaces.web_server", hub._today_meals),
        ("interfaces.web_server", hub._today_training),
        ("interfaces.web_server", hub._today_coach_note),
        ("interfaces.web_server", hub._sanitize_coach_note),
        ("interfaces.web_server", hub._today_departure_windows),
        ("interfaces.web_server", hub._today_nutrition_totals),
    )


def _assert_deterministic_node_is_quarantined(label, function):
    """Reject forbidden imports and calls using syntax, not source text."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden_imports = {
        imported
        for imported in imports
        if any(imported == forbidden or imported.startswith(f"{forbidden}.")
               for forbidden in _FORBIDDEN_DETERMINISTIC_MODULES)
    }
    calls = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    forbidden_calls = calls & _FORBIDDEN_DETERMINISTIC_CALLS
    assert not forbidden_imports and not forbidden_calls, (
        label,
        {"imports": forbidden_imports, "calls": forbidden_calls},
    )


def test_deterministic_default_execution_closure_is_quarantined():
    """Every default evaluator dependency is syntax-checked for legacy runtime use."""
    for label, function in _deterministic_execution_nodes():
        _assert_deterministic_node_is_quarantined(label, function)


def test_deterministic_closure_guard_rejects_a_synthetic_llm_import():
    """Prove the AST guard fails when a future default dependency imports an LLM."""
    def unsafe_default_loader():
        from core.llm_client import LLMClient
        return LLMClient

    with pytest.raises(AssertionError, match="core.llm_client"):
        _assert_deterministic_node_is_quarantined("synthetic", unsafe_default_loader)


def test_deterministic_closure_guard_rejects_a_synthetic_usage_meter():
    """Model/cost storage is forbidden even when no LLM module is imported."""
    def unsafe_status_loader():
        from memory.firestore_db import LLMUsageStore
        return LLMUsageStore("project").summary("today")

    with pytest.raises(AssertionError, match="LLMUsageStore"):
        _assert_deterministic_node_is_quarantined("synthetic-meter", unsafe_status_loader)


def test_startup_only_initializes_retained_claude_mcp_runtime():
    """A cold start cannot resurrect the Telegram/agent singleton runtime."""
    import inspect

    web_server = _web_server()
    source = inspect.getsource(web_server.lifespan)
    assert "AgentOrchestrator" not in source
    assert "Application" not in source
    assert "telegram" not in source.lower()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/internal/process-hub-message"),
        ("post", "/api/chat"),
        ("post", "/api/chat/upload"),
        ("get", "/api/chat/messages"),
        ("post", "/api/chat/regenerate"),
        ("post", "/api/chat/stop"),
    ],
)
def test_hub_chat_tombstones_return_410_before_production_auth(method, path):
    """Removed chat processors never expose an auth distinction to callers."""
    web_server = _web_server()
    production_env = {**_ENV, "CRON_DEV_BYPASS": "false"}
    with patch.dict(os.environ, production_env):
        response = getattr(TestClient(web_server.app), method)(path)
    assert response.status_code == 410


@pytest.mark.parametrize(
    "path",
    [
        "/cron/autonomous-tick",
        "/cron/proactive-alerts",
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
        from interfaces import flags  # noqa: PLC0415

        assert all(flags._routine_cutover_enabled(name) for name in ("morning", "nightly", "weekly"))


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
