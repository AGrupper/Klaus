"""Tests for LLMUsageStore in memory/firestore_db.py.

Uses sys.modules mocking to patch google.cloud.firestore so no real GCP
connection or installed package is needed.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch
import importlib


def _install_firestore_mock():
    """Install mock google.cloud.firestore into sys.modules."""
    # 1. Try to import existing real google modules to preserve their PEP 420 namespace paths
    try:
        import google
        import google.cloud
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        # Fallback if they do not exist
        if "google" not in sys.modules or isinstance(sys.modules["google"], MagicMock):
            google_mod = ModuleType("google")
            google_mod.__path__ = []
            sys.modules["google"] = google_mod
        else:
            google_mod = sys.modules["google"]

        if "google.cloud" not in sys.modules or isinstance(sys.modules["google.cloud"], MagicMock):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()

    # firestore.Increment must return a distinguishable sentinel
    class _Increment:
        def __init__(self, value):
            self.value = value
        def __repr__(self):
            return f"Increment({self.value!r})"

    firestore_mock.Increment = _Increment
    firestore_mock.SERVER_TIMESTAMP = object()
    firestore_mock.ArrayUnion = MagicMock()

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    # Also stub google.api_core.exceptions if needed
    try:
        import google.api_core.exceptions
    except ImportError:
        pass
    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod

    # google.cloud.firestore_v1.base_query
    try:
        import google.cloud.firestore_v1.base_query
    except ImportError:
        pass
    bq = sys.modules.get("google.cloud.firestore_v1.base_query", MagicMock())
    bq.FieldFilter = MagicMock()
    sys.modules["google.cloud.firestore_v1.base_query"] = bq
    if "google.cloud.firestore_v1" in sys.modules:
        sys.modules["google.cloud.firestore_v1"].base_query = bq

    # google.oauth2 (used in _make_firestore_client when FIRESTORE_CREDENTIALS set)
    try:
        import google.oauth2
        import google.oauth2.service_account
    except ImportError:
        pass
    if "google.oauth2" not in sys.modules:
        sys.modules["google.oauth2"] = MagicMock()
    if "google.oauth2.service_account" not in sys.modules:
        sys.modules["google.oauth2.service_account"] = MagicMock()

    # dotenv
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db so it picks up the mocks
    for key in list(sys.modules.keys()):
        if "memory.firestore_db" in key or key == "memory.firestore_db":
            del sys.modules[key]


_install_firestore_mock()

# Now import the module (with mocks in place)
from memory.firestore_db import (  # noqa: E402
    LLMUsageStore,
    _make_firestore_client,
    _HEARTBEAT_CONFIG_DEFAULTS,
)

import pytest

@pytest.fixture(autouse=True)
def setup_firestore_mock():
    _install_firestore_mock()
    import sys
    import importlib
    import memory.firestore_db
    importlib.reload(memory.firestore_db)
    global LLMUsageStore, _make_firestore_client, _HEARTBEAT_CONFIG_DEFAULTS
    LLMUsageStore = memory.firestore_db.LLMUsageStore
    _make_firestore_client = memory.firestore_db._make_firestore_client
    _HEARTBEAT_CONFIG_DEFAULTS = memory.firestore_db._HEARTBEAT_CONFIG_DEFAULTS


def _make_mock_client():
    """Return a MagicMock that behaves like a firestore.Client."""
    client = MagicMock()
    doc_ref = MagicMock()
    client.collection.return_value.document.return_value = doc_ref
    return client, doc_ref


# ── basic structural tests ────────────────────────────────────────────────────

def test_llm_usage_store_import():
    assert LLMUsageStore is not None


def test_llm_usage_store_has_record_method():
    assert hasattr(LLMUsageStore, "record")


def test_llm_usage_store_has_summary_method():
    assert hasattr(LLMUsageStore, "summary")


def test_llm_usage_store_collection_name():
    assert LLMUsageStore._COLLECTION == "llm_usage"


# ── record() behaviour tests ──────────────────────────────────────────────────

def test_record_calls_firestore_set_with_merge():
    """record() must call doc_ref.set(..., merge=True) with expected keys."""
    mock_client, mock_doc_ref = _make_mock_client()

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        store.record("gemini-3-flash-preview", "smart", 1000, 500, 0.000225)

    mock_doc_ref.set.assert_called_once()
    args, kwargs = mock_doc_ref.set.call_args
    payload = args[0]
    assert kwargs.get("merge") is True

    for key in ("total_in_tokens", "total_out_tokens", "total_cost_usd",
                "call_count", "smart_calls", "date"):
        assert key in payload, f"Missing key: {key}"


def test_record_uses_firestore_increment():
    """Numeric fields must use firestore.Increment, not raw values."""
    mock_client, mock_doc_ref = _make_mock_client()

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        store.record("gemini-3-flash-preview", "worker", 100, 50, 0.01)

    args, _ = mock_doc_ref.set.call_args
    payload = args[0]

    for field in ("total_in_tokens", "total_out_tokens", "total_cost_usd",
                  "call_count", "worker_calls"):
        val = payload[field]
        assert "Increment" in type(val).__name__, (
            f"Field '{field}' should be firestore.Increment, got {type(val).__name__}"
        )


def test_record_purpose_key():
    """Purpose 'brain' → 'brain_calls' key in the payload."""
    mock_client, mock_doc_ref = _make_mock_client()

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        store.record("gemini-3-flash-preview", "brain", 100, 50, 0.0)

    args, _ = mock_doc_ref.set.call_args
    payload = args[0]
    assert "brain_calls" in payload


def test_record_never_raises():
    """record() must swallow all exceptions and never raise."""
    mock_client = MagicMock()
    mock_client.collection.side_effect = RuntimeError("simulated Firestore failure")

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        result = store.record("gemini-3-flash-preview", "smart", 100, 50, 0.01)
        assert result is None  # returns None (no explicit return value)


# ── summary() behaviour tests ─────────────────────────────────────────────────

def test_summary_today_doc_absent_returns_empty_dict():
    """summary('today') returns {} when Firestore doc doesn't exist."""
    mock_client = MagicMock()
    snap = MagicMock()
    snap.exists = False
    mock_client.collection.return_value.document.return_value.get.return_value = snap

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        result = store.summary("today")

    assert isinstance(result, dict)
    assert result == {}


def test_summary_today_returns_doc_data():
    """summary('today') returns doc data when the Firestore doc exists."""
    mock_client = MagicMock()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"call_count": 5, "total_cost_usd": 0.01}
    mock_client.collection.return_value.document.return_value.get.return_value = snap

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        result = store.summary("today")

    assert result["call_count"] == 5
    assert result["total_cost_usd"] == 0.01


def test_summary_never_raises():
    """summary() must return {} on any exception, never raise."""
    mock_client = MagicMock()
    mock_client.collection.side_effect = RuntimeError("simulated failure")

    with patch("memory.firestore_db._make_firestore_client", return_value=mock_client):
        store = LLMUsageStore("test-project")
        result = store.summary("today")

    assert result == {}
