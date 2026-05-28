"""Tests for core/tools.py — follow-up tool handlers (Phase 18, Plan 02).

Covers AUTO-05: the 3 self-scheduled follow-up tools:
  - schedule_followup (D-12 — accepts ISO 8601 and natural-language)
  - list_followups
  - cancel_followup (D-15 — idempotent)

Test scope
----------
- _handle_schedule_followup, _handle_list_followups, _handle_cancel_followup
- Registration sites (SMART_AGENT_DIRECT_TOOLS, WORKER_TOOL_SCHEMAS, TOOL_SCHEMAS, _HANDLERS)
- WARNING 7 regression: ImportError on dateutil must surface as structured error
- NOTE 4 verification: SMART_AGENT_DIRECT_TOOLS appended at the end (not alphabetical)

Mock strategy
-------------
FollowupStore is patched in-place via `core.tools.FollowupStore` so handlers
never reach Firestore. Each handler imports FollowupStore locally; we patch
the symbol at the import site (`memory.firestore_db.FollowupStore`) so the
handler's local `from memory.firestore_db import FollowupStore` picks up the
patched class.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import core.tools — this transitively imports many tool backends.  We
# only need _handle_* and the registries, so we just import the module.
# ---------------------------------------------------------------------------

import core.tools as tools


# ---------------------------------------------------------------------------
# Shared fixture: a fake FollowupStore class that records every interaction.
# ---------------------------------------------------------------------------

class _FakeFollowupStore:
    """Test double for FollowupStore — records every call without I/O.

    Created instances are tracked on the class via `instances`.  Each
    instance has `added`, `cancelled`, and `list_pending_return` so tests
    can assert and configure behaviour.
    """

    instances: list["_FakeFollowupStore"] = []

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self.project_id = project_id
        self.database = database
        self.added: list[dict] = []
        self.cancelled: list[str] = []
        self.list_pending_return: list[dict] = []
        # Configurable behaviours
        self.add_return: dict | None = None
        self.cancel_return: bool = True
        _FakeFollowupStore.instances.append(self)

    def add(self, due_at: str, note: str, origin: str = "user_chat") -> dict:
        record = {"due_at": due_at, "note": note, "origin": origin}
        self.added.append(record)
        if self.add_return is not None:
            return self.add_return
        return {"id": "fake-id-123", "due_at": due_at}

    def list_pending(self) -> list[dict]:
        return list(self.list_pending_return)

    def cancel(self, fid: str) -> bool:
        self.cancelled.append(fid)
        return self.cancel_return


@pytest.fixture
def fake_store(monkeypatch):
    """Patch FollowupStore in memory.firestore_db and ensure GCP_PROJECT_ID is set."""
    _FakeFollowupStore.instances = []

    # Ensure required env var is present
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

    # Make sure memory.firestore_db is importable in tests; the handler does
    # `from memory.firestore_db import FollowupStore`, so we patch that symbol.
    import memory.firestore_db as firestore_db
    monkeypatch.setattr(firestore_db, "FollowupStore", _FakeFollowupStore)
    yield _FakeFollowupStore


# ===========================================================================
# TestFollowupTools — handler behaviour
# ===========================================================================

class TestFollowupTools:
    """Tests for the 3 follow-up tool handlers in core/tools.py."""

    # ----- _handle_schedule_followup ----- #

    def test_schedule_followup_iso_8601(self, fake_store):
        """Test 1 — ISO 8601 input persists via FollowupStore.add with origin='klaus_self'."""
        result_str = tools._handle_schedule_followup(
            when="2026-05-21T15:00:00+00:00",
            note="check on maya",
        )
        result = json.loads(result_str)
        assert result.get("id") == "fake-id-123"
        assert result.get("due_at") == "2026-05-21T15:00:00+00:00"
        # FollowupStore.add was called with origin='klaus_self'
        assert len(fake_store.instances) == 1
        added = fake_store.instances[0].added
        assert len(added) == 1
        assert added[0]["origin"] == "klaus_self"
        assert added[0]["note"] == "check on maya"

    def test_schedule_followup_natural_language(self, fake_store):
        """Test 2 — natural-language `when` parses via dateutil; result is ISO-8601 UTC."""
        result_str = tools._handle_schedule_followup(
            when="2026-05-22 15:00",   # naive datetime in past — but parseable
            note="test nl",
        )
        result = json.loads(result_str)
        # Must NOT be an error; due_at must be ISO-8601 with +00:00
        assert "error" not in result, f"Unexpected error: {result}"
        assert result["due_at"].endswith("+00:00"), f"Expected UTC ISO, got {result['due_at']!r}"
        # FollowupStore.add called
        assert len(fake_store.instances[0].added) == 1

    def test_schedule_followup_invalid_when_returns_error(self, fake_store):
        """Test 3 — unparseable `when` returns structured error, does NOT call FollowupStore.add."""
        result_str = tools._handle_schedule_followup(
            when="absolutely not a date",
            note="x",
        )
        result = json.loads(result_str)
        assert "error" in result, f"Expected error key, got {result}"
        assert "could_not_parse_when" in result["error"]
        # FollowupStore.add was NOT called
        if fake_store.instances:
            assert fake_store.instances[0].added == []

    def test_schedule_followup_naive_datetime_assigned_utc(self, fake_store):
        """Test 4 — naive datetime (no tzinfo) becomes UTC ISO-8601 with +00:00."""
        result_str = tools._handle_schedule_followup(
            when="2026-05-21 15:00",
            note="naive test",
        )
        result = json.loads(result_str)
        assert "error" not in result
        # due_at is forwarded to FollowupStore.add — verify what was actually stored
        stored = fake_store.instances[0].added[0]
        assert stored["due_at"].endswith("+00:00"), (
            f"Naive datetime not converted to UTC: {stored['due_at']!r}"
        )

    # ----- _handle_list_followups ----- #

    def test_list_followups_strips_internal_fields(self, fake_store):
        """Test 5 — list_followups returns id/due_at/note/defer_count only."""
        fake_store.instances = []  # ensure clean
        # Pre-populate list_pending_return on the next-built instance via subclass trick:
        # We swap in a fresh fake-store with the return value baked in.
        class _CustomStore(_FakeFollowupStore):
            def __init__(self, project_id: str, database: str = "(default)") -> None:
                super().__init__(project_id, database)
                self.list_pending_return = [
                    {
                        "id": "abc",
                        "due_at": "2026-05-21T15:00:00+00:00",
                        "note": "n1",
                        "defer_count": 2,
                        # Internal fields that must NOT appear in output
                        "created_at": "2026-05-20T00:00:00+00:00",
                        "status": "pending",
                        "origin": "user_chat",
                    },
                ]

        import memory.firestore_db as firestore_db
        with patch.object(firestore_db, "FollowupStore", _CustomStore):
            result_str = tools._handle_list_followups()

        result = json.loads(result_str)
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) == 1
        entry = result[0]
        # Allowed keys
        assert set(entry.keys()) == {"id", "due_at", "note", "defer_count"}, (
            f"Unexpected key set: {set(entry.keys())}"
        )
        assert entry["id"] == "abc"
        assert entry["defer_count"] == 2
        # Internal fields stripped
        for forbidden in ("created_at", "status", "origin"):
            assert forbidden not in entry, f"{forbidden} leaked into list_followups output"

    def test_list_followups_empty(self, fake_store):
        """Test 6 — empty list_pending returns '[]'."""
        # Default FollowupStore returns [] from list_pending
        result_str = tools._handle_list_followups()
        assert result_str == "[]", f"Expected '[]' for empty pending list, got {result_str!r}"

    # ----- _handle_cancel_followup ----- #

    def test_cancel_followup_idempotent_returns_ok_true(self, fake_store):
        """Test 7 — cancel returns {ok: True} when FollowupStore.cancel returns True; idempotent."""
        # First call: FollowupStore.cancel returns True (default)
        result_str = tools._handle_cancel_followup(id="abc")
        result = json.loads(result_str)
        assert result == {"ok": True}, f"Expected {{ok: True}}, got {result}"

        # Second call on same id (FollowupStore.cancel is idempotent — returns True again)
        result_str = tools._handle_cancel_followup(id="abc")
        result = json.loads(result_str)
        assert result == {"ok": True}, f"Expected {{ok: True}} on repeat, got {result}"

    def test_cancel_followup_nonexistent_returns_ok_false(self, fake_store):
        """Test 8 — cancel returns {ok: False} when FollowupStore.cancel returns False (id not found)."""
        class _StoreReturnsFalse(_FakeFollowupStore):
            def cancel(self, fid: str) -> bool:
                return False

        import memory.firestore_db as firestore_db
        with patch.object(firestore_db, "FollowupStore", _StoreReturnsFalse):
            result_str = tools._handle_cancel_followup(id="nonexistent")

        result = json.loads(result_str)
        assert result == {"ok": False}, f"Expected {{ok: False}}, got {result}"

    # ----- Registration tests ----- #

    def test_all_three_tools_in_smart_agent_direct_tools(self):
        """Test 9 — schedule_followup, list_followups, cancel_followup are in SMART_AGENT_DIRECT_TOOLS."""
        for name in ("schedule_followup", "list_followups", "cancel_followup"):
            assert name in tools.SMART_AGENT_DIRECT_TOOLS, (
                f"{name!r} missing from SMART_AGENT_DIRECT_TOOLS"
            )

    def test_all_three_tools_excluded_from_worker_schemas(self):
        """Test 10 — none of the 3 tools appear in WORKER_TOOL_SCHEMAS."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        for name in ("schedule_followup", "list_followups", "cancel_followup"):
            assert name not in worker_names, (
                f"{name!r} must NOT appear in WORKER_TOOL_SCHEMAS — Klaus brain-only"
            )

    def test_all_three_tools_in_handlers_dispatch(self):
        """Test 11 — all 3 tools are in _HANDLERS."""
        for name in ("schedule_followup", "list_followups", "cancel_followup"):
            assert name in tools._HANDLERS, f"{name!r} missing from _HANDLERS"

    def test_all_three_tools_have_correct_schemas(self):
        """Test 12 — schemas exist in TOOL_SCHEMAS with correct `required` arrays."""
        schemas_by_name = {s["name"]: s for s in tools.TOOL_SCHEMAS}

        # schedule_followup — requires when + note
        assert "schedule_followup" in schemas_by_name
        sched = schemas_by_name["schedule_followup"]
        assert set(sched["input_schema"]["required"]) == {"when", "note"}, (
            f"schedule_followup required mismatch: {sched['input_schema']['required']}"
        )
        assert "when" in sched["input_schema"]["properties"]
        assert "note" in sched["input_schema"]["properties"]

        # list_followups — no required params
        assert "list_followups" in schemas_by_name
        lst = schemas_by_name["list_followups"]
        assert lst["input_schema"]["required"] == []

        # cancel_followup — requires id
        assert "cancel_followup" in schemas_by_name
        canc = schemas_by_name["cancel_followup"]
        assert set(canc["input_schema"]["required"]) == {"id"}
        assert "id" in canc["input_schema"]["properties"]

    # ----- WARNING 7 regression ----- #

    def test_schedule_followup_handles_dateutil_import_error(self, fake_store, monkeypatch):
        """Test 13 — WARNING 7: ImportError on dateutil produces structured error, NOT a 500.

        Simulates the failure mode where Plan 01's requirements.txt change did
        not deploy (Cloud Run on stale image): the handler's
        `from dateutil import parser` raises ImportError. The handler must
        catch this and return {'error': 'could_not_parse_when: ...'} rather
        than propagating the exception up to the chat layer.
        """
        # Force `from dateutil import parser` to raise ImportError by
        # setting sys.modules["dateutil"] = None — Python raises
        # ModuleNotFoundError on any subsequent `import dateutil` or
        # `from dateutil import ...` until the slot is restored.
        original_dateutil = sys.modules.pop("dateutil", None)
        original_parser = sys.modules.pop("dateutil.parser", None)
        sys.modules["dateutil"] = None  # type: ignore[assignment]
        try:
            result_str = tools._handle_schedule_followup(
                when="tomorrow 3pm",
                note="dateutil missing test",
            )
        finally:
            # Restore dateutil so other tests can import it.
            del sys.modules["dateutil"]
            if original_dateutil is not None:
                sys.modules["dateutil"] = original_dateutil
            if original_parser is not None:
                sys.modules["dateutil.parser"] = original_parser

        result = json.loads(result_str)
        assert "error" in result, f"Expected structured error, got {result}"
        assert "could_not_parse_when" in result["error"], (
            f"Expected 'could_not_parse_when' prefix, got {result['error']!r}"
        )
        # FollowupStore.add must NOT have been called
        if fake_store.instances:
            assert fake_store.instances[0].added == []


# ---------------------------------------------------------------------------
# Phase 19 Plan 02 — training profile + Garmin tool registration
# ---------------------------------------------------------------------------

class TestPhase19ToolRegistration:
    """PROFILE-04 + GARMIN-04 — verify 4 new tools at all registration sites.

    Brain-direct (in SMART_AGENT_DIRECT_TOOLS, excluded from WORKER_TOOL_SCHEMAS):
      - get_training_profile
      - update_training_profile

    Worker-delegated (in WORKER_TOOL_SCHEMAS, NOT in SMART_AGENT_DIRECT_TOOLS):
      - fetch_training_status
      - fetch_recent_activities
    """

    def test_phase19_profile_tools_registered(self):
        """Brain-direct tools appear at all 4 expected sites."""
        # Site 1: SMART_AGENT_DIRECT_TOOLS membership
        assert "get_training_profile" in tools.SMART_AGENT_DIRECT_TOOLS
        assert "update_training_profile" in tools.SMART_AGENT_DIRECT_TOOLS
        # Site 2: TOOL_SCHEMAS entry exists (by name)
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "get_training_profile" in names
        assert "update_training_profile" in names
        # Site 3: WORKER_TOOL_SCHEMAS EXCLUSION (brain-direct → NOT seen by worker)
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "get_training_profile" not in worker_names
        assert "update_training_profile" not in worker_names
        # Site 4: _HANDLERS dispatch
        assert "get_training_profile" in tools._HANDLERS
        assert "update_training_profile" in tools._HANDLERS

    def test_phase19_fetch_tools_worker_delegated(self):
        """fetch_* tools are worker-delegated (NOT in SMART_AGENT_DIRECT_TOOLS)."""
        # NOT in smart-direct
        assert "fetch_training_status" not in tools.SMART_AGENT_DIRECT_TOOLS
        assert "fetch_recent_activities" not in tools.SMART_AGENT_DIRECT_TOOLS
        # IN tool schemas
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "fetch_training_status" in names
        assert "fetch_recent_activities" in names
        # IN worker schemas (delegated through worker)
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "fetch_training_status" in worker_names
        assert "fetch_recent_activities" in worker_names
        # IN handlers dispatch
        assert "fetch_training_status" in tools._HANDLERS
        assert "fetch_recent_activities" in tools._HANDLERS

    def test_phase19_tool_schema_shape(self):
        """Each new schema has name + description + input_schema (object type)."""
        targets = {
            "get_training_profile", "update_training_profile",
            "fetch_training_status", "fetch_recent_activities",
        }
        seen = set()
        for s in tools.TOOL_SCHEMAS:
            if s["name"] not in targets:
                continue
            seen.add(s["name"])
            assert set(s.keys()) >= {"name", "description", "input_schema"}, (
                f"{s['name']!r} schema missing required top-level keys"
            )
            assert s["input_schema"]["type"] == "object"
        assert seen == targets, f"Missing schemas: {targets - seen}"

    def test_phase19_update_profile_schema_requires_patch(self):
        """update_training_profile must REQUIRE the patch argument."""
        schema = next(
            s for s in tools.TOOL_SCHEMAS if s["name"] == "update_training_profile"
        )
        assert schema["input_schema"]["required"] == ["patch"]

    # ---- Phase 19 Plan 03 — fetch_recent_meals (worker-delegated) ----

    def test_fetch_recent_meals_worker_delegated(self):
        """NUTR-03: fetch_recent_meals is worker-delegated at all 4 sites."""
        # NOT in smart-direct (worker tier)
        assert "fetch_recent_meals" not in tools.SMART_AGENT_DIRECT_TOOLS
        # IN tool schemas
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "fetch_recent_meals" in names
        # IN worker schemas (delegated through worker)
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "fetch_recent_meals" in worker_names
        # IN handlers dispatch
        assert "fetch_recent_meals" in tools._HANDLERS

    def test_fetch_recent_meals_schema_default_hours(self):
        """fetch_recent_meals schema: hours is integer + no required args."""
        schema = next(
            s for s in tools.TOOL_SCHEMAS if s["name"] == "fetch_recent_meals"
        )
        assert schema["input_schema"]["properties"]["hours"]["type"] == "integer"
        assert schema["input_schema"]["required"] == []

    def test_get_acwr_worker_delegated(self):
        """Phase 19 SC-1 closeout: get_acwr is worker-delegated at all 4 sites."""
        assert "get_acwr" not in tools.SMART_AGENT_DIRECT_TOOLS
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "get_acwr" in names
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "get_acwr" in worker_names
        assert "get_acwr" in tools._HANDLERS

    def test_get_acwr_schema_no_args(self):
        """get_acwr schema: zero properties, zero required."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "get_acwr")
        assert schema["input_schema"]["properties"] == {}
        assert schema["input_schema"]["required"] == []

    def test_get_acwr_handler_returns_json_with_ratio_key(self, monkeypatch):
        """Handler dispatches to compute_acwr_from_db and returns JSON string."""
        from mcp_tools import garmin_tool

        sentinel = {"acute": 12.3, "chronic": 9.5, "ratio": 1.29}
        monkeypatch.setattr(garmin_tool, "compute_acwr_from_db", lambda: sentinel)
        result = tools._HANDLERS["get_acwr"]({})
        assert json.loads(result) == sentinel
