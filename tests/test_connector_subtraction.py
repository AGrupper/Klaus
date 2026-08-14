"""Regression coverage for retired connector and dependency subtraction."""
from __future__ import annotations

from pathlib import Path


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


def test_notion_module_exposes_no_retired_chat_import_helpers() -> None:
    """Notion keeps its MCP operations without the removed chat-import pipeline."""
    from mcp_tools import notion_tool

    for name in (
        "build_chat_log_properties",
        "build_ai_chat_properties",
        "update_page_properties",
        "upsert_database_row",
    ):
        assert not hasattr(notion_tool, name)

    for name in (
        "search",
        "get_page",
        "query_database",
        "create_page",
        "append_blocks",
    ):
        assert callable(getattr(notion_tool, name))


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
