"""Tests for Phase 25 tool registration in core/tools.py — PROG-02.

RED tests — written before implementation. All should FAIL until
get_goal_projection is registered at all four sites in core/tools.py.

New brain-direct tool: get_goal_projection

Tests cover:
  - get_goal_projection is in SMART_AGENT_DIRECT_TOOLS (brain-direct)
  - get_goal_projection is NOT in WORKER_TOOL_SCHEMAS (T-25-08)
  - get_goal_projection is a key in _HANDLERS
  - get_goal_projection has a TOOL_SCHEMAS entry with the required shape
  - _handle_get_goal_projection is callable
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


NEW_TOOLS = ["get_goal_projection"]


def _install_tools_mocks() -> None:
    """Install all heavy-dependency stubs so core.tools can be imported in tests.

    Mirrors test_tool_registration_phase23._install_tools_mocks.
    Also stubs core.projection and core.pace_history so the new handler
    imports do not fail at collection time.
    """
    # stub core.auth_google entirely — it imports google_auth_oauthlib etc.
    auth_google_stub = MagicMock()
    auth_google_stub.GoogleAuthManager = MagicMock
    auth_google_stub.build_auth_manager_from_env = MagicMock(return_value=MagicMock())
    sys.modules["core.auth_google"] = auth_google_stub

    # ---- googleapiclient ----
    if "googleapiclient" not in sys.modules:
        api = ModuleType("googleapiclient")
        api.__path__ = []
        sys.modules["googleapiclient"] = api
    errors = MagicMock()
    errors.HttpError = type("HttpError", (Exception,), {})
    sys.modules["googleapiclient.errors"] = errors
    sys.modules["googleapiclient.discovery"] = MagicMock()

    # google.cloud.firestore (may already exist from firestore test stubs)
    google_mod = sys.modules.get("google")
    if google_mod is None or isinstance(google_mod, MagicMock):
        google_mod = ModuleType("google")
        google_mod.__path__ = []
        sys.modules["google"] = google_mod

    google_cloud = sys.modules.get("google.cloud")
    if google_cloud is None or isinstance(google_cloud, MagicMock):
        google_cloud = ModuleType("google.cloud")
        google_cloud.__path__ = []
        sys.modules["google.cloud"] = google_cloud
        setattr(google_mod, "cloud", google_cloud)

    if "google.cloud.firestore" not in sys.modules:
        fs_mock = MagicMock()
        fs_mock.SERVER_TIMESTAMP = object()
        sys.modules["google.cloud.firestore"] = fs_mock
        setattr(google_cloud, "firestore", fs_mock)

    # google.api_core
    if "google.api_core" not in sys.modules:
        api_core = ModuleType("google.api_core")
        api_core.__path__ = []
        sys.modules["google.api_core"] = api_core
        setattr(google_mod, "api_core", api_core)
    exc_mod = MagicMock()
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod

    # google.cloud.firestore_v1
    for m in ["google.cloud.firestore_v1", "google.cloud.firestore_v1.base_query"]:
        sys.modules.setdefault(m, MagicMock())

    # dotenv
    if "dotenv" not in sys.modules:
        dotenv_mod = MagicMock()
        dotenv_mod.load_dotenv = MagicMock()
        sys.modules["dotenv"] = dotenv_mod

    # pinecone
    for m in ["pinecone", "pinecone.grpc"]:
        sys.modules.setdefault(m, MagicMock())

    # mcp_tools imports used by core.tools lazy singletons
    for m in [
        "mcp_tools.gmail_tool",
        "mcp_tools.calendar_tool",
        "mcp_tools.weather_tool",
        "mcp_tools.readwise_tool",
        "mcp_tools.garmin_tool",
        "mcp_tools.notion_tool",
        "mcp_tools.memory",
        "mcp_tools.self_inspect",
        "mcp_tools.healthkit_tool",
    ]:
        sys.modules.setdefault(m, MagicMock())

    # Phase 25 — stub the new helper modules so handler imports don't fail
    for m in ["core.projection", "core.pace_history"]:
        sys.modules.setdefault(m, MagicMock())

    # Force re-import of core.tools so our stubs take effect
    for m in ["core.tools", "memory.firestore_db"]:
        if m in sys.modules:
            del sys.modules[m]


import pytest

# Bound per-test by the autouse fixture below. We deliberately do NOT install the
# stubs or import core.tools at module/collection time.
tools = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _tools(isolated_modules):
    global tools
    import importlib
    _install_tools_mocks()  # also evicts core.tools + memory.firestore_db
    tools = importlib.import_module("core.tools")


class TestPhase25ToolRegistration:
    """PROG-02 — verify get_goal_projection registered at all four sites.

    Brain-direct: in SMART_AGENT_DIRECT_TOOLS, excluded from WORKER_TOOL_SCHEMAS,
    present in _HANDLERS and TOOL_SCHEMAS, handler callable.
    """

    def test_tool_in_direct(self):
        """get_goal_projection is in SMART_AGENT_DIRECT_TOOLS (brain-direct)."""
        assert "get_goal_projection" in tools.SMART_AGENT_DIRECT_TOOLS

    def test_tool_excluded_from_worker(self):
        """get_goal_projection is NOT in WORKER_TOOL_SCHEMAS (T-25-08)."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "get_goal_projection" not in worker_names

    def test_tool_in_handlers(self):
        """get_goal_projection is a key in _HANDLERS."""
        assert "get_goal_projection" in tools._HANDLERS

    def test_tool_has_schema(self):
        """get_goal_projection has a TOOL_SCHEMAS entry with the required shape."""
        schemas = {s["name"]: s for s in tools.TOOL_SCHEMAS}
        assert "get_goal_projection" in schemas
        schema = schemas["get_goal_projection"]
        assert set(schema.keys()) >= {"name", "description", "input_schema"}
        assert "facet" in schema["input_schema"]["properties"]
        assert schema["input_schema"].get("required") == ["facet"]

    def test_handler_callable(self):
        """_handle_get_goal_projection is callable."""
        assert callable(getattr(tools, "_handle_get_goal_projection", None))
