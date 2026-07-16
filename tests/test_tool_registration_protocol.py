"""Registration tests for the supplement/habit protocol tools in core/tools.py.

Confirms get_supplement_protocol + update_supplement_protocol are:
  - present in TOOL_SCHEMAS with valid input_schema
  - dispatchable via _HANDLERS
  - brain-direct (in SMART_AGENT_DIRECT_TOOLS, excluded from WORKER_TOOL_SCHEMAS)
And that the handlers degrade gracefully (return {"error": ...}) when
Firestore is unreachable rather than raising — mirrors
tests/test_tool_registration_strength.py.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import core.tools as t

_PROTOCOL_TOOLS = {"get_supplement_protocol", "update_supplement_protocol"}


def test_schemas_present_and_wellformed():
    names = {s["name"] for s in t.TOOL_SCHEMAS}
    assert _PROTOCOL_TOOLS <= names
    for s in t.TOOL_SCHEMAS:
        if s["name"] in _PROTOCOL_TOOLS:
            assert s["input_schema"]["type"] == "object"
            assert "properties" in s["input_schema"]


def test_update_schema_requires_full_items_list():
    """update is a FULL-list replace — items must be the sole required param."""
    schema = next(s for s in t.TOOL_SCHEMAS if s["name"] == "update_supplement_protocol")
    assert schema["input_schema"]["required"] == ["items"]
    assert schema["input_schema"]["properties"]["items"]["type"] == "array"


def test_handlers_registered():
    assert _PROTOCOL_TOOLS <= set(t._HANDLERS)


def test_brain_direct_and_worker_excluded():
    assert _PROTOCOL_TOOLS <= t.SMART_AGENT_DIRECT_TOOLS
    worker_names = {s["name"] for s in t.WORKER_TOOL_SCHEMAS}
    assert not (_PROTOCOL_TOOLS & worker_names)


def test_get_handler_fail_open():
    """Store construction failing → JSON error dict, never raises.

    The failure is injected via _get_protocol_store (not by unsetting env)
    so the test is deterministic regardless of which sibling test files
    have mocked google.cloud.firestore in sys.modules."""
    with patch.object(t, "_get_protocol_store", side_effect=RuntimeError("no firestore")):
        out = t._HANDLERS["get_supplement_protocol"]({})
    parsed = json.loads(out)
    assert isinstance(parsed, dict)
    assert "error" in parsed


def test_update_handler_fail_open():
    """A failing replace() → JSON error dict, never raises."""
    mock_store = MagicMock()
    mock_store.replace.side_effect = RuntimeError("boom")
    with patch.object(t, "_get_protocol_store", return_value=mock_store):
        out = t._HANDLERS["update_supplement_protocol"](
            {"items": [{"name": "Creatine", "kind": "supplement", "anchor": "post_lunch"}]}
        )
    parsed = json.loads(out)
    assert isinstance(parsed, dict)
    assert "error" in parsed


def test_get_handler_returns_items(monkeypatch):
    doc = {"items": [{"name": "Creatine", "kind": "supplement",
                      "anchor": "post_lunch", "active": True}]}
    mock_store = MagicMock()
    mock_store.get.return_value = dict(doc)
    with patch.object(t, "_get_protocol_store", return_value=mock_store):
        out = t._HANDLERS["get_supplement_protocol"]({})
    parsed = json.loads(out)
    assert parsed["items"] == doc["items"]


def test_update_handler_replaces_full_list(monkeypatch):
    items = [{"name": "Magnesium", "kind": "supplement", "anchor": "night",
              "notes": "", "active": True}]
    mock_store = MagicMock()
    with patch.object(t, "_get_protocol_store", return_value=mock_store):
        out = t._HANDLERS["update_supplement_protocol"]({"items": items})
    mock_store.replace.assert_called_once_with(items)
    parsed = json.loads(out)
    assert parsed.get("ok") is True
    assert parsed.get("count") == 1
