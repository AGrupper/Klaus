"""Tests for Phase 23 tool registration in core/tools.py — BLOCK-01/BLOCK-03.

RED tests — written before implementation. All should FAIL until the 6 new
block/benchmark tools are registered at all sites in core/tools.py.

The 6 new brain-direct tools (update_plan EXCLUDED — already exists since Phase 21):
  get_plan, get_block_status, log_benchmark, get_benchmark_history,
  start_block, end_block

Tests cover (mirroring TestPhase20ToolRegistration pattern):
  - each new tool is in SMART_AGENT_DIRECT_TOOLS (brain-direct)
  - none of the new tools appear in WORKER_TOOL_SCHEMAS (V4 access control, T-23-05)
  - each new tool is a key in _HANDLERS
  - update_plan appears exactly once in SMART_AGENT_DIRECT_TOOLS and once in
    _HANDLERS (Pitfall 2 — must not be re-added)
  - each new tool has a TOOL_SCHEMAS entry with name + description + input_schema
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


NEW_TOOLS = [
    "get_plan",
    "get_block_status",
    "log_benchmark",
    "get_benchmark_history",
    "start_block",
    "end_block",
]


def _install_tools_mocks() -> None:
    """Install all heavy-dependency stubs so core.tools can be imported in tests.

    Mirrors test_tool_registration_phase20._install_tools_mocks.
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


class TestPhase23ToolRegistration:
    """BLOCK-01 + BLOCK-03 — verify the 6 new block/benchmark tools at all sites.

    All 6 are brain-direct (in SMART_AGENT_DIRECT_TOOLS, excluded from
    WORKER_TOOL_SCHEMAS). update_plan is NOT re-added (Pitfall 2).
    """

    def test_six_new_tools_in_direct(self):
        """Each of the 6 new tools is in SMART_AGENT_DIRECT_TOOLS (brain-direct)."""
        for name in NEW_TOOLS:
            assert name in tools.SMART_AGENT_DIRECT_TOOLS, name

    def test_six_new_tools_excluded_from_worker(self):
        """None of the 6 new tools appear in WORKER_TOOL_SCHEMAS (T-23-05)."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        for name in NEW_TOOLS:
            assert name not in worker_names, name

    def test_six_new_tools_in_handlers(self):
        """Each of the 6 new tools is a key in _HANDLERS."""
        for name in NEW_TOOLS:
            assert name in tools._HANDLERS, name

    def test_six_new_tools_have_schemas(self):
        """Each new tool has a TOOL_SCHEMAS entry with name + description + input_schema."""
        schemas = {s["name"]: s for s in tools.TOOL_SCHEMAS}
        for name in NEW_TOOLS:
            assert name in schemas, name
            schema = schemas[name]
            assert set(schema.keys()) >= {"name", "description", "input_schema"}, name
            assert schema["input_schema"]["type"] == "object", name

    def test_update_plan_not_duplicated(self):
        """update_plan must appear exactly once in SMART_AGENT_DIRECT_TOOLS and _HANDLERS
        (Pitfall 2 — it already exists from Phase 21 and must not be re-added)."""
        # frozenset / dict keys are inherently unique; assert it exists exactly once
        # in the schema list too (the real duplicate-key risk is the schema list).
        schema_names = [s["name"] for s in tools.TOOL_SCHEMAS]
        assert schema_names.count("update_plan") == 1
        assert "update_plan" in tools.SMART_AGENT_DIRECT_TOOLS
        assert "update_plan" in tools._HANDLERS

    def test_log_benchmark_schema_required_fields(self):
        """log_benchmark requires date, facet, value, unit, block_id (notes optional)."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "log_benchmark")
        required = set(schema["input_schema"].get("required", []))
        assert {"date", "facet", "value", "unit", "block_id"} <= required
        assert "notes" not in required

    def test_get_benchmark_history_requires_facet(self):
        """get_benchmark_history requires facet (n optional)."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "get_benchmark_history")
        required = set(schema["input_schema"].get("required", []))
        assert "facet" in required
        assert "n" not in required

    def test_zero_arg_tools_have_no_required(self):
        """get_plan and get_block_status take no arguments."""
        for name in ("get_plan", "get_block_status"):
            schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == name)
            assert schema["input_schema"].get("required", []) == [], name

    def test_handler_functions_defined(self):
        """The 6 _handle_* functions exist and are callable."""
        for name in NEW_TOOLS:
            fn = getattr(tools, f"_handle_{name}", None)
            assert callable(fn), name
