"""Registration tests for the Hevy strength coaching tools in core/tools.py.

Confirms get_strength_progress + get_training_context are:
  - present in TOOL_SCHEMAS with valid input_schema
  - dispatchable via _HANDLERS
  - brain-direct (in SMART_AGENT_DIRECT_TOOLS, excluded from WORKER_TOOL_SCHEMAS)
And that the handlers degrade gracefully (return {"error": ...} / a dict) when
Firestore is unreachable rather than raising.
"""
from __future__ import annotations

import json

import core.tools as t

_STRENGTH_TOOLS = {"get_strength_progress", "get_training_context"}


def test_schemas_present_and_wellformed():
    names = {s["name"] for s in t.TOOL_SCHEMAS}
    assert _STRENGTH_TOOLS <= names
    for s in t.TOOL_SCHEMAS:
        if s["name"] in _STRENGTH_TOOLS:
            assert s["input_schema"]["type"] == "object"
            assert "properties" in s["input_schema"]


def test_handlers_registered():
    assert _STRENGTH_TOOLS <= set(t._HANDLERS)


def test_brain_direct_and_worker_excluded():
    assert _STRENGTH_TOOLS <= t.SMART_AGENT_DIRECT_TOOLS
    worker_names = {s["name"] for s in t.WORKER_TOOL_SCHEMAS}
    assert not (_STRENGTH_TOOLS & worker_names)


def test_get_strength_progress_handler_fail_open(monkeypatch):
    # No GCP env / no Firestore → handler returns a JSON error string, never raises.
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    out = t._HANDLERS["get_strength_progress"]({})
    parsed = json.loads(out)
    assert isinstance(parsed, dict)
    assert "error" in parsed


def test_get_training_context_handler_returns_dict(monkeypatch):
    # Every block is fail-open; with no backends the call still returns a JSON
    # object carrying the window and (None-valued) domain keys.
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    out = t._HANDLERS["get_training_context"]({"days": 7})
    parsed = json.loads(out)
    assert parsed["window_days"] == 7
    assert "strength_sessions" in parsed
