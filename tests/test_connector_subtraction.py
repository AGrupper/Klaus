"""Regression coverage for retired connector and dependency subtraction."""
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_guard_rejects_retired_connector_and_dependency_residue(
    tmp_path: Path,
) -> None:
    """Deployment must fail if removed connectors or support packages return."""
    from scripts.check_claude_first_runtime import find_violations

    (tmp_path / "requirements.txt").write_text(
        "google-cloud-monitoring>=2.20\n"
        "google-cloud-run>=0.10\n",
        encoding="utf-8",
    )
    (tmp_path / "connector.py").write_text(
        "from mcp_tools.gmail_tool import GmailManager\n"
        "from mcp_tools.readwise_tool import fetch_readwise_today\n"
        "from mcp_tools.self_inspect import read_source\n"
        "CHAT_LOGS_BUCKET = 'retired'\n",
        encoding="utf-8",
    )

    violations = find_violations(tmp_path)

    for marker in (
        "google-cloud-monitoring",
        "google-cloud-run",
        "mcp_tools.gmail_tool",
        "mcp_tools.readwise_tool",
        "mcp_tools.self_inspect",
        "CHAT_LOGS_BUCKET",
    ):
        assert any(marker in violation for violation in violations), marker


def test_checked_in_dependency_set_excludes_retired_connector_support() -> None:
    """The production image installs only retained connector dependencies."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()

    for package in (
        "anthropic",
        "openai",
        "python-telegram-bot",
        "tiktoken",
        "google-cloud-monitoring",
        "google-cloud-run",
    ):
        assert package not in requirements

    assert "google-genai" in requirements
    assert "embedding client only" in requirements


def test_notion_connector_is_retired_in_favour_of_the_claude_connector() -> None:
    """Notion moved to Claude's own connector; Klaus must not rebuild it.

    Claude's Notion connector reaches strictly more of the workspace than the
    integration token ever did, and nothing in Klaus reads Notion data — it was
    pure pass-through — so the module and its secret are gone rather than
    duplicated.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mcp_tools.notion_tool")

    assert not (ROOT / "mcp_tools" / "notion_tool.py").exists()
    assert not (ROOT / "scripts" / "smoke_test_notion.py").exists()

    from core.tools import TOOL_SCHEMAS, _HANDLERS

    assert not [name for name in _HANDLERS if name.startswith("notion_")]
    assert not [t for t in TOOL_SCHEMAS if t["name"].startswith("notion_")]


def test_google_routes_is_retired_in_favour_of_a_configured_travel_time() -> None:
    """Routes was a billed API, a cache and a cost breaker producing one number.

    The departure-window contract it fed must survive its removal: the Hub
    renders leave_by/get_ready_at, and the deterministic "leave now" push fires
    on leave_by with no LLM anywhere in that path.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mcp_tools.routes_tool")

    assert not (ROOT / "mcp_tools" / "routes_tool.py").exists()

    from memory import firestore_db

    assert not hasattr(firestore_db, "RoutesUsageStore")

    from interfaces import web_server

    assert callable(web_server._today_departure_windows)
    assert not hasattr(web_server, "_today_routes")


def test_retired_connector_secrets_are_not_bound_in_production() -> None:
    """The Notion token is quarantined, not still wired into the service."""
    import json

    desired = json.loads(
        (ROOT / "ops" / "desired-production.json").read_text(encoding="utf-8")
    )
    bindings = desired["service"]["secret_bindings"]
    runtime_secrets = desired["secrets"]["runtime_access"]
    quarantine = json.loads(
        (ROOT / "ops" / "policies" / "quarantine.json").read_text(encoding="utf-8")
    )

    for env_key, secret in (
        ("NOTION_API_TOKEN", "klaus-notion-api-token"),
        ("HOME_ADDRESS", "klaus-home-address"),
    ):
        assert env_key not in bindings, env_key
        assert secret not in runtime_secrets, secret
        assert secret in quarantine["resources"]["secrets"], secret

    assert "notion" not in desired["connectors"]
    assert "google_routes" not in desired["connectors"]


def test_retired_connector_support_artifacts_are_absent() -> None:
    """No model prompt, local transcript reader, or stale task lock ships."""
    retired_paths = (
        ROOT / "core" / "prompt_loader.py",
        ROOT / "prompts" / "chat_summary.md",
        ROOT / "prompts" / "morning_occasion.md",
        ROOT / "prompts" / "nightly_occasion.md",
        ROOT / "prompts" / "weekly_occasion.md",
        ROOT / "scratch_read.py",
        ROOT / "force_reauth.py",
        ROOT / ".claude" / "scheduled_tasks.lock",
    )

    assert [str(path.relative_to(ROOT)) for path in retired_paths if path.exists()] == []
