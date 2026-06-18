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

    # ---- Nutrition: fetch_recent_meals is brain-direct (rebuilt) ----

    def test_fetch_recent_meals_brain_direct(self):
        """fetch_recent_meals is brain-direct so totals are server-computed, not
        summed by the worker LLM (the source of the wrong/drifting numbers)."""
        # IN smart-direct (brain tier)
        assert "fetch_recent_meals" in tools.SMART_AGENT_DIRECT_TOOLS
        # IN tool schemas
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "fetch_recent_meals" in names
        # NOT in worker schemas — no worker summarization hop
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "fetch_recent_meals" not in worker_names
        # Exposed to the brain via get_smart_schemas
        smart_names = {s["name"] for s in tools.get_smart_schemas()}
        assert "fetch_recent_meals" in smart_names
        # IN handlers dispatch
        assert "fetch_recent_meals" in tools._HANDLERS

    def test_fetch_recent_meals_schema_default_hours(self):
        """fetch_recent_meals schema: hours is integer + no required args."""
        schema = next(
            s for s in tools.TOOL_SCHEMAS if s["name"] == "fetch_recent_meals"
        )
        assert schema["input_schema"]["properties"]["hours"]["type"] == "integer"
        assert schema["input_schema"]["required"] == []

    def test_fetch_recent_meals_totals_are_server_computed(self, monkeypatch):
        """Totals come from get_day_aggregate (Python arithmetic), not LLM
        summing — so the same question returns the SAME total every time. This is
        the regression guard for the wrong/drifting-numbers bug this tool fixes.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import memory.firestore_db as firestore_db

        tz = ZoneInfo("Asia/Jerusalem")
        today = datetime.now(tz).date().isoformat()
        meals = [
            {"timestamp": f"{today}T08:00:00+03:00", "calories": 500,
             "protein_g": 40, "carbs_g": 60, "fat_g": 10, "fiber_g": 5, "meal_type": 1},
            {"timestamp": f"{today}T13:00:00+03:00", "calories": 700,
             "protein_g": 50, "carbs_g": 80, "fat_g": 20, "fiber_g": 8, "meal_type": 2},
        ]
        real_meal_store = firestore_db.MealStore

        class FakeMealStore:
            def __init__(self, *a, **k):
                pass

            def get_day(self, date_str):
                return list(meals) if date_str == today else []

            def get_day_aggregate(self, date_str):
                # Reuse the REAL server-side arithmetic — the whole point is that
                # Python computes the totals, never the model.
                return real_meal_store.get_day_aggregate(self, date_str)

        monkeypatch.setattr(firestore_db, "MealStore", FakeMealStore)

        # A wide window keeps both meals in-window regardless of wall-clock time.
        out1 = tools._handle_fetch_recent_meals(hours=1000)
        out2 = tools._handle_fetch_recent_meals(hours=1000)
        assert out1 == out2, "identical input must yield byte-identical totals"

        data = json.loads(out1)
        expected_totals = FakeMealStore().get_day_aggregate(today)["totals"]
        assert data["totals_by_day"][today] == expected_totals
        # window_totals = Python sum across the window (40+50 protein, 500+700 kcal)
        assert data["window_totals"]["protein_g"] == 90
        assert data["window_totals"]["calories"] == 1200
        # the per-meal list is still present for recency/timing reasoning
        assert len(data["meals"]) == 2

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


class TestMemorySingletonsConstruct:
    """Regression: long-term memory singletons must be constructible.

    Guards against the d5cd895 regression, where a Five-Fingers prune deleted
    the `MemoryStore`/`MemoryTool` imports from core/tools.py. Because
    `from __future__ import annotations` defers the module-level type hints to
    strings, the module still imported cleanly — but the first conversational
    recall/remember raised `NameError: name 'MemoryTool' is not defined` at
    instantiation time, breaking long-term memory in production for days.

    These build no network clients (Pinecone + Gemini are lazy in MemoryStore),
    so a bare PINECONE_API_KEY is all that's needed.
    """

    def test_get_memory_store_constructs_without_nameerror(self, monkeypatch):
        from memory.pinecone_db import MemoryStore

        monkeypatch.setenv("PINECONE_API_KEY", "test-key")
        monkeypatch.setattr(tools, "_memory_store", None)

        store = tools._get_memory_store()
        assert isinstance(store, MemoryStore)

    def test_get_memory_tool_constructs_without_nameerror(self, monkeypatch):
        from mcp_tools.memory import MemoryTool

        monkeypatch.setenv("PINECONE_API_KEY", "test-key")
        monkeypatch.setattr(tools, "_memory_store", None)
        monkeypatch.setattr(tools, "_memory_tool", None)

        tool = tools._get_memory_tool()
        assert isinstance(tool, MemoryTool)


# ============================================================
# Phase 21 Plan 02 — update_plan alias + JSON-safe get handler
# ============================================================


class TestPhase21UpdatePlanAlias:
    """PLAN-03: update_plan alias and JSON-safe get_training_profile.

    Covers three behaviours:
      1. _HANDLERS["update_plan"] dispatches to the same merge-write as
         update_training_profile — store.update() is called with the patch.
      2. A patch containing a new structured key (dated_goals) passes through
         unchanged (no allow-list rejection).
      3. _handle_get_training_profile returns parseable JSON even when
         store.load() returns a dict whose updated_at is a datetime
         (DatetimeWithNanoseconds-like) — json.loads succeeds and the value
         is a str, not a raw datetime.

    Mock strategy: patch UserProfileStore at the import site used by the
    handler (memory.firestore_db.UserProfileStore) and set required env vars
    via monkeypatch so the handler can construct the store.
    """

    def test_update_plan_in_handlers(self):
        """update_plan must be present in _HANDLERS dispatch table."""
        assert "update_plan" in tools._HANDLERS

    def test_update_plan_in_smart_agent_direct_tools(self):
        """update_plan must be a brain-direct tool (in SMART_AGENT_DIRECT_TOOLS)."""
        assert "update_plan" in tools.SMART_AGENT_DIRECT_TOOLS

    def test_update_plan_schema_registered(self):
        """update_plan must have a schema entry in TOOL_SCHEMAS."""
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "update_plan" in names

    def test_update_plan_schema_requires_patch(self):
        """update_plan schema must require 'patch' argument."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "update_plan")
        assert "patch" in schema["input_schema"]["required"]

    def test_update_plan_calls_store_update(self, monkeypatch):
        """_HANDLERS['update_plan'] calls UserProfileStore.update with the patch."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        mock_store = MagicMock()
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch("memory.firestore_db.UserProfileStore", mock_store_cls):
            result = tools._HANDLERS["update_plan"](
                {"patch": {"dated_goals": [{"target_date": "2026-10-01", "goal_label": "bench", "metric": "100kg"}]}}
            )

        assert mock_store.update.called
        call_args = mock_store.update.call_args[0][0]
        assert "dated_goals" in call_args
        parsed = json.loads(result)
        assert parsed.get("ok") is True

    def test_update_plan_new_structured_key_passes_through(self, monkeypatch):
        """Patch with a new structured key (dated_goals list) passes through unchanged."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        mock_store = MagicMock()
        mock_store_cls = MagicMock(return_value=mock_store)

        patch_payload = {
            "dated_goals": [
                {"target_date": "2026-10-01", "goal_label": "bench", "metric": "100kg"}
            ]
        }

        with patch("memory.firestore_db.UserProfileStore", mock_store_cls):
            tools._HANDLERS["update_plan"]({"patch": patch_payload})

        called_patch = mock_store.update.call_args[0][0]
        assert called_patch == patch_payload

    def test_update_plan_and_update_training_profile_identical_writes(self, monkeypatch):
        """update_plan and update_training_profile must call store.update with the same patch."""
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        patch_payload = {"weekly_split": {"Monday": {"AM": "run", "PM": "rest"}}}

        calls_utp: list = []
        calls_up: list = []

        mock_store_utp = MagicMock()
        mock_store_utp.update.side_effect = lambda p: calls_utp.append(p)

        mock_store_up = MagicMock()
        mock_store_up.update.side_effect = lambda p: calls_up.append(p)

        with patch("memory.firestore_db.UserProfileStore", MagicMock(return_value=mock_store_utp)):
            tools._HANDLERS["update_training_profile"]({"patch": patch_payload})

        with patch("memory.firestore_db.UserProfileStore", MagicMock(return_value=mock_store_up)):
            tools._HANDLERS["update_plan"]({"patch": patch_payload})

        assert calls_utp == calls_up

    def test_get_training_profile_json_safe_with_datetime(self, monkeypatch):
        """_handle_get_training_profile returns parseable JSON when updated_at is a datetime."""
        from datetime import datetime, timezone

        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        # Simulate a DatetimeWithNanoseconds-like value (a datetime with isoformat)
        fake_updated_at = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)
        profile_doc = {
            "athletic_goals": ["run a marathon"],
            "dated_goals": [],
            "updated_at": fake_updated_at,
        }

        mock_store = MagicMock()
        mock_store.load.return_value = profile_doc
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch("memory.firestore_db.UserProfileStore", mock_store_cls):
            result = tools._handle_get_training_profile()

        # Must not raise; must be valid JSON
        parsed = json.loads(result)
        # updated_at must be a string (ISO-converted), not a raw datetime
        assert isinstance(parsed["updated_at"], str)
        assert "2026" in parsed["updated_at"]

    def test_update_training_profile_schema_has_new_keys(self):
        """update_training_profile description must advertise the 6 new structured keys."""
        schema = next(
            s for s in tools.TOOL_SCHEMAS if s["name"] == "update_training_profile"
        )
        desc = schema["description"] + schema["input_schema"]["properties"]["patch"]["description"]
        for key in (
            "dated_goals",
            "weekly_split",
            "nutrition_targets",
            "supplement_schedule",
            "fueling_timeline",
            "plan_start_date",
        ):
            assert key in desc, f"Key '{key}' missing from update_training_profile schema description"


# ---------------------------------------------------------------------------
# Phase 22 Plan 02 — read_coaching_guide brain-direct tool (COACH-01)
# ---------------------------------------------------------------------------

class TestPhase22CoachingGuideTool:
    """COACH-01 — verify read_coaching_guide registration at all 4 sites."""

    def test_read_coaching_guide_in_smart_agent_direct_tools(self):
        """Site 1: read_coaching_guide is in SMART_AGENT_DIRECT_TOOLS."""
        assert "read_coaching_guide" in tools.SMART_AGENT_DIRECT_TOOLS

    def test_read_coaching_guide_in_tool_schemas(self):
        """Site 2: read_coaching_guide schema exists in TOOL_SCHEMAS."""
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "read_coaching_guide" in names

    def test_read_coaching_guide_not_in_worker_schemas(self):
        """Brain-direct — worker MUST NOT see this tool (T-22-05 mitigation)."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "read_coaching_guide" not in worker_names

    def test_read_coaching_guide_in_handlers_dispatch(self):
        """Site 4: read_coaching_guide is in _HANDLERS dispatch table."""
        assert "read_coaching_guide" in tools._HANDLERS

    def test_read_coaching_guide_schema_requires_topic(self):
        """Schema must require exactly ['topic'] — no other required args."""
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "read_coaching_guide")
        assert schema["input_schema"]["required"] == ["topic"]
        assert "topic" in schema["input_schema"]["properties"]

    def test_handle_read_coaching_guide_known_topic(self, tmp_path, monkeypatch):
        """Handler returns JSON with 'content' key for a known slug (T-22-04 mitigation)."""
        guide = tmp_path / "docs" / "COACHING_GUIDE.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            "<!-- SECTION: threshold-runs -->\n## Threshold Runs\nRun at LT2 pace.\n"
            "<!-- SECTION: supplements -->\n## Supplements\nCreatine 3-5g/day.\n"
        )
        import core.tools as tools_module
        import pathlib

        _original_resolve = pathlib.Path.resolve

        def _fake_resolve(self_path):
            resolved = _original_resolve(self_path)
            if str(resolved).endswith("docs/COACHING_GUIDE.md"):
                return (tmp_path / "docs" / "COACHING_GUIDE.md").resolve()
            return resolved

        monkeypatch.setattr(pathlib.Path, "resolve", _fake_resolve)

        result = tools_module._handle_read_coaching_guide("threshold-runs")
        parsed = json.loads(result)
        assert "content" in parsed, f"Expected 'content' key, got: {parsed}"
        assert "LT2" in parsed["content"]
        assert "error" not in parsed

    def test_handle_read_coaching_guide_unknown_topic(self, tmp_path, monkeypatch):
        """Handler returns JSON with 'error' key for unknown topic — never raises (T-22-04)."""
        guide = tmp_path / "docs" / "COACHING_GUIDE.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            "<!-- SECTION: threshold-runs -->\n## Threshold Runs\nRun at LT2 pace.\n"
        )
        import core.tools as tools_module
        import pathlib

        _original_resolve = pathlib.Path.resolve

        def _fake_resolve(self_path):
            resolved = _original_resolve(self_path)
            if str(resolved).endswith("docs/COACHING_GUIDE.md"):
                return (tmp_path / "docs" / "COACHING_GUIDE.md").resolve()
            return resolved

        monkeypatch.setattr(pathlib.Path, "resolve", _fake_resolve)

        result = tools_module._handle_read_coaching_guide("nonexistent-topic-xyz")
        parsed = json.loads(result)
        assert "error" in parsed, f"Expected 'error' key, got: {parsed}"
        assert "content" not in parsed


# ---------------------------------------------------------------------------
# Phase 24 Plan 03 — WR-02: hardened read_coaching_guide fuzzy match (COACH-03)
# ---------------------------------------------------------------------------

class TestPhase24CoachingGuideFuzzyHardening:
    """WR-02 — verify unambiguous-only fuzzy match in _handle_read_coaching_guide.

    These tests patch pathlib.Path.read_text to inject an in-memory guide string
    with multiple SECTION anchors so no real file dependency is required and the
    fuzzy fallback can be exercised deterministically with controlled anchors.
    """

    # Guide with two sections sharing the word 'zymbal' — both anchors contain 'zymbal'
    # so any query with 'zymbal' is ambiguous. 'creatine' appears in only one anchor.
    MULTI_SECTION_GUIDE = (
        "<!-- SECTION: zymbal-alpha -->\n"
        "## Zymbal Alpha\nAlpha protocol. Creatine 3-5g/day.\n"
        "<!-- SECTION: zymbal-beta -->\n"
        "## Zymbal Beta\nBeta protocol. High volume.\n"
        "<!-- SECTION: unique-creatine-section -->\n"
        "## Creatine Supplementation\nCreatine 3-5g/day. Take with carbs.\n"
    )

    def _patch_read_text(self, monkeypatch, content: str):
        """Patch Path.read_text so COACHING_GUIDE.md returns the provided content."""
        import core.tools as tools_module
        import pathlib

        _original_read_text = pathlib.Path.read_text

        def _fake_read_text(self_path, *args, **kwargs):
            if self_path.name == "COACHING_GUIDE.md":
                return content
            return _original_read_text(self_path, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "read_text", _fake_read_text)
        return tools_module

    def test_ambiguous_word_returns_not_found(self, monkeypatch):
        """WR-02: a word that matches multiple section anchors returns not-found JSON.

        'zymbal' appears in both 'zymbal-alpha' and 'zymbal-beta' anchors. A query
        whose only ≥4-char word is 'zymbal' must return not-found, NOT 'zymbal-alpha'.
        """
        tools_module = self._patch_read_text(monkeypatch, self.MULTI_SECTION_GUIDE)
        # Slug with no exact match; only fuzzy word is 'zymbal' which hits 2 anchors
        result = tools_module._handle_read_coaching_guide("zymbal-query")
        parsed = json.loads(result)
        assert "error" in parsed, (
            f"Expected not-found error for ambiguous word 'zymbal', got: {parsed}"
        )
        assert "content" not in parsed, "Ambiguous fuzzy match MUST NOT return content"

    def test_short_word_skip_returns_not_found(self, monkeypatch):
        """WR-02: short words (< 4 chars) are skipped and do not trigger fuzzy match."""
        # Guide has one section; slug has only short words so fuzzy should not match
        guide_content = (
            "<!-- SECTION: threshold-runs -->\n"
            "## Threshold Runs\nRun at LT2 pace.\n"
        )
        tools_module = self._patch_read_text(monkeypatch, guide_content)
        # Query 'go-run-now': 'run' is 3 chars → skipped; 'now' is 3 chars → skipped
        # 'go' is 2 chars → skipped; no 4+-char word → not-found
        result = tools_module._handle_read_coaching_guide("go-run-now")
        parsed = json.loads(result)
        assert "error" in parsed, (
            f"Expected not-found (all words < 4 chars skipped), got: {parsed}"
        )
        assert "content" not in parsed

    def test_unambiguous_word_returns_correct_section(self, monkeypatch):
        """WR-02: an unambiguous ≥4-char word that matches exactly one section returns it."""
        tools_module = self._patch_read_text(monkeypatch, self.MULTI_SECTION_GUIDE)
        # 'unique-creatine-section' slug: 'unique' (6 chars) → appears only in that one anchor
        # No exact match for slug 'creatine-info'; 'creatine' → only in 'unique-creatine-section'
        result = tools_module._handle_read_coaching_guide("creatine-info")
        parsed = json.loads(result)
        assert "content" in parsed, (
            f"Expected content for unambiguous match 'creatine', got: {parsed}"
        )
        assert "error" not in parsed
        assert "Creatine" in parsed["content"], (
            f"Expected 'Creatine' in section content, got: {parsed['content']}"
        )


# --------------------------------------------------------------------------- #
# fetch_recent_meals — slot-time semantics note (2026-06-12 incident)          #
# --------------------------------------------------------------------------- #


# ---------------------------------------------------------------------------
# TestNativeTaskTools — Phase 27 Wave 0 scaffold (implemented in 27-03)
# ---------------------------------------------------------------------------


class TestNativeTaskTools:
    """Wave 0 scaffold for native task tool registration in core/tools.py.

    All tests are skip-marked — implemented in plan 27-03.
    Covers TASK-05: native task schemas registered; add_task schema removed.
    """

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_task_create_schema_registered_in_tool_schemas(self):
        """TOOL_SCHEMAS must contain a schema named 'task_create'."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_task_list_schema_registered_in_tool_schemas(self):
        """TOOL_SCHEMAS must contain a schema named 'task_list'."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_task_complete_schema_registered_in_tool_schemas(self):
        """TOOL_SCHEMAS must contain a schema named 'task_complete'."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_task_reschedule_schema_registered_in_tool_schemas(self):
        """TOOL_SCHEMAS must contain a schema named 'task_reschedule'."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_task_edit_schema_registered_in_tool_schemas(self):
        """TOOL_SCHEMAS must contain a schema named 'task_edit'."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_task_delete_schema_registered_in_tool_schemas(self):
        """TOOL_SCHEMAS must contain a schema named 'task_delete'."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_add_task_schema_removed_from_tool_schemas(self):
        """TOOL_SCHEMAS must NOT contain 'add_task' after the TickTick tool swap."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_all_six_native_task_handlers_registered_in_handlers(self):
        """_HANDLERS must have keys: task_create, task_list, task_complete,
        task_reschedule, task_edit, task_delete."""

    @pytest.mark.skip(reason="implemented in 27-03")
    def test_add_task_handler_removed_from_handlers(self):
        """_HANDLERS must NOT contain 'add_task' after the tool swap."""


class TestFetchRecentMealsSlotTimeNote:
    """Lifesum stamps HealthKit samples with canonical meal-slot times
    (breakfast=08:00, lunch=12:00, dinner=20:00) — NOT the actual eating
    time. The tool result must say so, otherwise the brain reasons about
    digestion windows from times the user never ate at."""

    def test_result_includes_timestamp_semantics_note(self):
        import json as _json
        from unittest.mock import MagicMock, patch as _patch

        fake_store = MagicMock(name="MealStore")
        fake_store.get_day.return_value = [{
            "timestamp": "2026-06-12T08:00:00+03:00",
            "source": "healthkit",
            "calories": 885.0,
            "meal_type": 1,
        }]
        fake_store.get_day_aggregate.return_value = {
            "totals": {"calories": 885.0, "protein_g": 46.0,
                       "carbs_g": 87.0, "fat_g": 41.0, "fiber_g": 3.3},
        }
        with _patch("memory.firestore_db.MealStore", return_value=fake_store):
            result = _json.loads(tools._handle_fetch_recent_meals(hours=6))

        note = result.get("timestamp_note", "")
        assert "slot" in note.lower(), (
            "fetch_recent_meals must warn that healthkit timestamps are "
            f"Lifesum slot times, got: {result.keys()}"
        )
        assert "not" in note.lower() and "actual" in note.lower()
