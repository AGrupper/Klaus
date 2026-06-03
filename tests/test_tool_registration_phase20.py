"""Tests for Phase 20 tool registration in core/tools.py — LOG-03/LOG-04.

RED tests — written before implementation. All should FAIL until log_training
and get_training_history are registered at all 5 sites in core/tools.py.

Tests cover (mirroring TestPhase19ToolRegistration pattern):
  - "log_training" is in SMART_AGENT_DIRECT_TOOLS frozenset (brain-direct)
  - "log_training" schema is in TOOL_SCHEMAS and is NOT in WORKER_TOOL_SCHEMAS (excluded)
  - "log_training" is a key in _HANDLERS
  - "get_training_history" schema is in TOOL_SCHEMAS, IS in WORKER_TOOL_SCHEMAS, NOT in SMART_AGENT_DIRECT_TOOLS
  - "get_training_history" is a key in _HANDLERS
  - Schema shapes are correct (name + description + input_schema with type object)
  - log_training schema requires "date"; get_training_history has no required fields
  - Handler functions _handle_log_training and _handle_get_training_history exist
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _install_tools_mocks() -> None:
    """Install all heavy-dependency stubs so core.tools can be imported in tests.

    Strategy: stub core.auth_google entirely (it imports google_auth_oauthlib and
    other OAuth libs not installed in the test env) + stub googleapiclient +
    stub all mcp_tools modules used by core.tools lazy singletons.
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
# stubs or import core.tools at module/collection time — that leaks fake
# core.auth_google / googleapiclient / google.* modules into sys.modules for the
# whole session and breaks sibling test files.
tools = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _tools(isolated_modules):
    global tools
    import importlib
    _install_tools_mocks()  # also evicts core.tools + memory.firestore_db
    tools = importlib.import_module("core.tools")


class TestPhase20ToolRegistration:
    """LOG-03 + LOG-04 — verify log_training + get_training_history at all 5 sites.

    Brain-direct (in SMART_AGENT_DIRECT_TOOLS, excluded from WORKER_TOOL_SCHEMAS):
      - log_training

    Worker-delegated (in WORKER_TOOL_SCHEMAS, NOT in SMART_AGENT_DIRECT_TOOLS):
      - get_training_history
    """

    def test_log_training_in_smart_agent_direct_tools(self):
        """LOG-03: log_training is in SMART_AGENT_DIRECT_TOOLS (brain-direct)."""
        assert "log_training" in tools.SMART_AGENT_DIRECT_TOOLS

    def test_log_training_in_tool_schemas(self):
        """log_training schema is present in TOOL_SCHEMAS."""
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "log_training" in names

    def test_log_training_excluded_from_worker_tool_schemas(self):
        """log_training is NOT in WORKER_TOOL_SCHEMAS (brain-direct only, not worker)."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "log_training" not in worker_names

    def test_log_training_in_handlers(self):
        """log_training is dispatched via _HANDLERS."""
        assert "log_training" in tools._HANDLERS

    def test_get_training_history_not_in_smart_agent_direct(self):
        """LOG-04: get_training_history is worker-delegated — NOT in SMART_AGENT_DIRECT_TOOLS."""
        assert "get_training_history" not in tools.SMART_AGENT_DIRECT_TOOLS

    def test_get_training_history_in_tool_schemas(self):
        """get_training_history schema is present in TOOL_SCHEMAS."""
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "get_training_history" in names

    def test_get_training_history_in_worker_tool_schemas(self):
        """get_training_history IS in WORKER_TOOL_SCHEMAS (worker-delegated)."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "get_training_history" in worker_names

    def test_get_training_history_in_handlers(self):
        """get_training_history is dispatched via _HANDLERS."""
        assert "get_training_history" in tools._HANDLERS

    def test_log_training_schema_shape(self):
        """log_training schema has name + description + input_schema (type object)."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "log_training")
        assert set(schema.keys()) >= {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"

    def test_log_training_schema_requires_date(self):
        """log_training schema requires 'date' (the only required field)."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "log_training")
        required = schema["input_schema"].get("required", [])
        assert "date" in required

    def test_get_training_history_schema_shape(self):
        """get_training_history schema has name + description + input_schema (type object)."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "get_training_history")
        assert set(schema.keys()) >= {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"

    def test_get_training_history_schema_no_required(self):
        """get_training_history has no required fields (days defaults to 7)."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "get_training_history")
        required = schema["input_schema"].get("required", [])
        assert required == []

    def test_handler_functions_defined(self):
        """_handle_log_training and _handle_get_training_history functions exist."""
        assert hasattr(tools, "_handle_log_training")
        assert hasattr(tools, "_handle_get_training_history")
        assert callable(tools._handle_log_training)
        assert callable(tools._handle_get_training_history)

    def test_log_training_derives_unique_manual_slot(self, monkeypatch):
        """CR-02 regression: with no explicit slot, the handler derives a unique
        timestamped manual_HHMMSS slot — never the literal 'manual' (which would
        collide on {date}_manual and overwrite a prior same-day chat log)."""
        from unittest.mock import patch as _patch
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        captured = {}

        class _FakeTLS:
            def __init__(self, **kwargs):
                pass

            def log_session(self, **kwargs):
                captured.update(kwargs)

        with _patch("memory.firestore_db.TrainingLogStore", _FakeTLS):
            tools._handle_log_training(date="2026-06-01", session_type="run", rpe=6)

        slot = captured.get("slot")
        assert slot is not None and slot != "manual", captured
        assert slot.startswith("manual_") and len(slot) == len("manual_HHMMSS"), slot
