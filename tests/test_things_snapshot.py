# tests/test_things_snapshot.py
from __future__ import annotations
import sys
import types
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import os


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")


def _make_doc(updated_at_offset_minutes: int) -> dict:
    updated_at = datetime.now(timezone.utc) - timedelta(minutes=updated_at_offset_minutes)
    return {
        "updated_at": updated_at,
        "today": [{"uuid": "A", "title": "Task 1", "area": "Work", "project": None, "due_date": None}],
        "overdue": [],
        "due_today": [],
        "version": 1,
    }


def _mock_firestore(doc_data: dict | None):
    snap = MagicMock()
    snap.exists = doc_data is not None
    snap.to_dict.return_value = doc_data
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = snap
    return client


def _patch_firestore_client(mock_client):
    """Patch _make_firestore_client at the memory.firestore_db module level.

    get_today_tasks() does `from memory.firestore_db import _make_firestore_client`
    inside the function body, so we must ensure memory.firestore_db exists in
    sys.modules and its attribute points to our mock before the import fires.
    """
    fake_mod = types.ModuleType("memory.firestore_db")
    fake_mod._make_firestore_client = MagicMock(return_value=mock_client)
    return patch.dict(sys.modules, {"memory.firestore_db": fake_mod})


def test_missing_doc_returns_none_stale():
    with _patch_firestore_client(_mock_firestore(None)):
        # Force reimport so the patched module is picked up
        import importlib
        import mcp_tools.things_snapshot as mod
        importlib.reload(mod)
        result = mod.get_today_tasks()
    assert result.stale_minutes is None
    assert result.doc_exists is False
    assert result.is_missing
    assert result.staleness_warning == "Task data unavailable, sir."


def test_fresh_doc_no_warning():
    with _patch_firestore_client(_mock_firestore(_make_doc(2))):
        import importlib
        import mcp_tools.things_snapshot as mod
        importlib.reload(mod)
        result = mod.get_today_tasks()
    assert result.stale_minutes is not None and result.stale_minutes <= 3
    assert result.staleness_warning is None
    assert len(result.today) == 1


def test_30_min_stale_shows_warning():
    with _patch_firestore_client(_mock_firestore(_make_doc(30))):
        import importlib
        import mcp_tools.things_snapshot as mod
        importlib.reload(mod)
        result = mod.get_today_tasks()
    assert result.staleness_warning is not None
    assert "30 min" in result.staleness_warning


def test_90_min_stale_shows_hour_warning():
    with _patch_firestore_client(_mock_firestore(_make_doc(90))):
        import importlib
        import mcp_tools.things_snapshot as mod
        importlib.reload(mod)
        result = mod.get_today_tasks()
    assert "hour" in result.staleness_warning


def test_25h_stale_returns_unavailable():
    with _patch_firestore_client(_mock_firestore(_make_doc(1500))):
        import importlib
        import mcp_tools.things_snapshot as mod
        importlib.reload(mod)
        result = mod.get_today_tasks()
    assert result.staleness_warning == "Task data unavailable, sir."
