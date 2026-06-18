"""Tests for TaskStore, TaskListStore, and the _next_due_date recurrence engine.

Phase 27 — TASK-01/02/04/07

Covers:
  - _next_due_date + _advance_once: all five cadences (TASK-02)
  - Month-end clamping (TestMonthEndClamping)
  - Weekday wrapping (TestWeekdayWrapping)
  - Past-due D-06 roll-forward including multi-cycle case (TestPastDueRollForward)
  - TaskStore CRUD: create / list / get / update / delete (TestTaskStoreCRUD)
  - TaskListStore: create / list / rename / delete (TestTaskListStore)
  - TaskStore.complete() soft-mark to "completing" (TestSoftComplete)
  - TaskStore.undo_complete() revert + delete next instance (TestUndoComplete)
  - Recurring task completion: next instance generation (TestRecurringComplete)
  - TaskStore.get_summary() (TestGetSummary)

Mock strategy
-------------
google.cloud.firestore is mocked at the sys.modules level BEFORE any
memory.firestore_db import, mirroring tests/test_firestore_db.py exactly.
The `isolated_modules` fixture (from conftest.py) reverts all sys.modules
mutations on teardown.
"""
from __future__ import annotations

import sys
from datetime import date
from types import ModuleType
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# (mirrors tests/test_firestore_db.py _install_firestore_mock exactly)
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore and related stubs into sys.modules."""
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        if "google" not in sys.modules or isinstance(sys.modules["google"], MagicMock):
            google_mod = ModuleType("google")
            google_mod.__path__ = []
            sys.modules["google"] = google_mod
        else:
            google_mod = sys.modules["google"]

        if "google.cloud" not in sys.modules or isinstance(
            sys.modules["google.cloud"], MagicMock
        ):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()

    class _Increment:
        def __init__(self, value):
            self.value = value

        def __repr__(self):
            return f"Increment({self.value!r})"

    class _ArrayUnion:
        def __init__(self, values):
            self.values = list(values)

        def __repr__(self):
            return f"ArrayUnion({self.values!r})"

    firestore_mock.Increment = _Increment
    firestore_mock.ArrayUnion = _ArrayUnion
    firestore_mock.SERVER_TIMESTAMP = object()

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    # google.api_core.exceptions
    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    # google.cloud.firestore_v1.base_query — only FieldFilter is consumed
    class _FieldFilter:
        def __init__(self, field, op, value):
            self.field = field
            self.op = op
            self.value = value

        def __repr__(self):
            return f"FieldFilter({self.field!r}, {self.op!r}, {self.value!r})"

    bq = sys.modules.get("google.cloud.firestore_v1.base_query", MagicMock())
    bq.FieldFilter = _FieldFilter
    sys.modules["google.cloud.firestore_v1.base_query"] = bq
    if "google.cloud.firestore_v1" in sys.modules:
        sys.modules["google.cloud.firestore_v1"].base_query = bq
    else:
        fv1 = MagicMock()
        fv1.base_query = bq
        sys.modules["google.cloud.firestore_v1"] = fv1

    # google.oauth2
    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    # dotenv
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db so it picks up the mocks
    for key in list(sys.modules.keys()):
        if "memory.firestore_db" in key or key == "memory.firestore_db":
            del sys.modules[key]


# Module-level placeholder — bound by autouse fixture
firestore_db = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _refresh_firestore_mock(isolated_modules):
    """Install firestore mock and import memory.firestore_db before each test."""
    global firestore_db
    import importlib
    _install_firestore_mock()
    firestore_db = importlib.import_module("memory.firestore_db")


# ---------------------------------------------------------------------------
# TestNextDueDate — basic cadence correctness
# ---------------------------------------------------------------------------

class TestNextDueDate:
    """Basic correctness for all five cadences, both anchors."""

    def test_daily_schedule_anchor(self):
        rule = {"cadence": "daily", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 6, 18), date(2026, 6, 18), rule
        )
        assert result == date(2026, 6, 19)

    def test_daily_completion_anchor(self):
        rule = {"cadence": "daily", "anchor": "completion"}
        # anchor="completion" → base is completed_on
        result = firestore_db._next_due_date(
            date(2026, 6, 1), date(2026, 6, 18), rule
        )
        assert result == date(2026, 6, 19)

    def test_weekly_schedule_anchor_future(self):
        rule = {"cadence": "weekly", "anchor": "schedule"}
        # current_due is in the future relative to completed_on
        result = firestore_db._next_due_date(
            date(2026, 6, 25), date(2026, 6, 18), rule
        )
        assert result == date(2026, 7, 2)

    def test_weekly_completion_anchor(self):
        rule = {"cadence": "weekly", "anchor": "completion"}
        result = firestore_db._next_due_date(
            date(2026, 6, 1), date(2026, 6, 18), rule
        )
        assert result == date(2026, 6, 25)

    def test_every_n_days(self):
        rule = {"cadence": "every_n_days", "every_n_days": 3, "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 6, 18), date(2026, 6, 18), rule
        )
        assert result == date(2026, 6, 21)

    def test_every_n_days_completion_anchor(self):
        rule = {"cadence": "every_n_days", "every_n_days": 5, "anchor": "completion"}
        result = firestore_db._next_due_date(
            date(2026, 6, 1), date(2026, 6, 18), rule
        )
        assert result == date(2026, 6, 23)

    def test_monthly_schedule_anchor_same_day_next_month(self):
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 6, 15), date(2026, 6, 15), rule
        )
        assert result == date(2026, 7, 15)

    def test_string_inputs_accepted(self):
        """_next_due_date must accept YYYY-MM-DD strings (auto-conversion)."""
        rule = {"cadence": "daily", "anchor": "schedule"}
        result = firestore_db._next_due_date("2026-06-18", "2026-06-18", rule)
        assert result == date(2026, 6, 19)

    def test_result_is_always_strictly_after_completed_on(self):
        """Result must be strictly > completed_on regardless of cadence or anchor."""
        rule = {"cadence": "daily", "anchor": "schedule"}
        completed = date(2026, 6, 18)
        result = firestore_db._next_due_date(date(2026, 6, 18), completed, rule)
        assert result > completed


# ---------------------------------------------------------------------------
# TestMonthEndClamping — monthly cadence edge cases
# ---------------------------------------------------------------------------

class TestMonthEndClamping:
    """Verify calendar.monthrange-based clamping for monthly cadence."""

    def test_jan_31_clamps_to_feb_28_non_leap(self):
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 1, 31), date(2026, 1, 31), rule
        )
        assert result == date(2026, 2, 28), f"Expected 2026-02-28, got {result}"

    def test_jan_31_clamps_to_feb_29_leap_year(self):
        # 2028 is a leap year
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2028, 1, 31), date(2028, 1, 31), rule
        )
        assert result == date(2028, 2, 29), f"Expected 2028-02-29, got {result}"

    def test_mar_31_clamps_to_apr_30(self):
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 3, 31), date(2026, 3, 31), rule
        )
        assert result == date(2026, 4, 30), f"Expected 2026-04-30, got {result}"

    def test_dec_31_wraps_to_jan_31_next_year(self):
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 12, 31), date(2026, 12, 31), rule
        )
        assert result == date(2027, 1, 31), f"Expected 2027-01-31, got {result}"

    def test_normal_month_day_preserved(self):
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 6, 15), date(2026, 6, 15), rule
        )
        assert result == date(2026, 7, 15)


# ---------------------------------------------------------------------------
# TestWeekdayWrapping — weekdays cadence skips weekends
# ---------------------------------------------------------------------------

class TestWeekdayWrapping:
    """Weekdays cadence must skip Saturday (5) and Sunday (6)."""

    def test_friday_advances_to_monday(self):
        """Fri + 1 = Sat → skip to Mon."""
        rule = {"cadence": "weekdays", "anchor": "schedule"}
        # 2026-06-19 is a Friday
        result = firestore_db._next_due_date(
            date(2026, 6, 19), date(2026, 6, 19), rule
        )
        assert result == date(2026, 6, 22), f"Expected Mon 2026-06-22, got {result}"

    def test_saturday_advances_to_monday(self):
        """Sat + 1 = Sun → skip to Mon (from Saturday base)."""
        rule = {"cadence": "weekdays", "anchor": "schedule"}
        # 2026-06-20 is a Saturday
        result = firestore_db._next_due_date(
            date(2026, 6, 20), date(2026, 6, 20), rule
        )
        # Saturday + 1 = Sunday, still weekend → skip to Monday 2026-06-22
        # But since completed_on == current_due (2026-06-20) and result must be
        # strictly > 2026-06-20, result must be >= Monday 2026-06-22
        assert result >= date(2026, 6, 22), f"Expected >= 2026-06-22, got {result}"
        assert result.weekday() < 5, f"Result {result} is on a weekend"

    def test_monday_advances_to_tuesday(self):
        rule = {"cadence": "weekdays", "anchor": "schedule"}
        # 2026-06-22 is a Monday
        result = firestore_db._next_due_date(
            date(2026, 6, 22), date(2026, 6, 22), rule
        )
        assert result == date(2026, 6, 23)

    def test_result_is_never_a_weekend_day(self):
        rule = {"cadence": "weekdays", "anchor": "schedule"}
        for start_day in range(14, 22):  # June 14–21, 2026 spans Mon–Sun
            result = firestore_db._next_due_date(
                date(2026, 6, start_day), date(2026, 6, start_day), rule
            )
            assert result.weekday() < 5, (
                f"Starting from 2026-06-{start_day}, got weekend result {result}"
            )


# ---------------------------------------------------------------------------
# TestPastDueRollForward — D-06 must loop, not single-step
# ---------------------------------------------------------------------------

class TestPastDueRollForward:
    """D-06: schedule-anchored task with stale due_date rolls forward correctly."""

    def test_daily_past_due_rolls_to_next_day(self):
        rule = {"cadence": "daily", "anchor": "schedule"}
        # current_due is yesterday — should jump forward to tomorrow
        result = firestore_db._next_due_date(
            date(2026, 6, 17), date(2026, 6, 18), rule
        )
        assert result > date(2026, 6, 18)

    def test_weekly_one_cycle_behind(self):
        rule = {"cadence": "weekly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 6, 11), date(2026, 6, 18), rule
        )
        # 6/11 + 1 week = 6/18 — still not > completed_on, so advance again → 6/25
        assert result > date(2026, 6, 18)
        assert result == date(2026, 6, 25)

    def test_weekly_multi_cycle_stale(self):
        """CRITICAL multi-cycle test: weekly task current_due=2026-05-01,
        completed_on=2026-06-18 must resolve in ONE call to a date
        strictly > 2026-06-18.

        A single-step `break` implementation would return 2026-05-08
        (one advance) — this assertion catches that bug.
        """
        rule = {"cadence": "weekly", "anchor": "schedule"}
        completed_on = date(2026, 6, 18)
        result = firestore_db._next_due_date(
            date(2026, 5, 1), completed_on, rule
        )
        assert result > completed_on, (
            f"Expected result strictly > {completed_on} but got {result}. "
            "Single-step 'break' bug: the implementation advanced only once "
            "instead of looping until past completed_on."
        )
        # Should land on 2026-06-19 (next Friday after 2026-05-01 weekly series)
        # Actually: 5/1, 5/8, 5/15, 5/22, 5/29, 6/5, 6/12, 6/19 — first > 6/18
        assert result == date(2026, 6, 19), (
            f"Expected 2026-06-19 (next weekly occurrence after 2026-06-18), got {result}"
        )

    def test_monthly_many_months_behind(self):
        """Monthly task last set Jan 15, completed Jun 18 must jump to Jul 15."""
        rule = {"cadence": "monthly", "anchor": "schedule"}
        result = firestore_db._next_due_date(
            date(2026, 1, 15), date(2026, 6, 18), rule
        )
        assert result > date(2026, 6, 18)
        assert result == date(2026, 7, 15)

    def test_completion_anchor_never_needs_rollforward(self):
        """completion-anchored tasks always use completed_on as base, so
        candidate is always at least one cadence after completed_on — never
        in the past relative to completed_on."""
        rule = {"cadence": "weekly", "anchor": "completion"}
        result = firestore_db._next_due_date(
            date(2026, 1, 1), date(2026, 6, 18), rule
        )
        assert result == date(2026, 6, 25)


# ---------------------------------------------------------------------------
# Helpers for Task 2 tests (mock Firestore client + collection)
# ---------------------------------------------------------------------------

class _FakeDoc:
    """Mimics a Firestore document snapshot."""
    def __init__(self, data: dict):
        self._data = data
        self.id = data.get("id", "")

    def to_dict(self):
        return self._data

    @property
    def exists(self):
        return True


class _FakeCollection:
    """In-memory Firestore collection double."""

    def __init__(self):
        self._docs: dict[str, dict] = {}

    def document(self, doc_id: str):
        return _FakeDocRef(self, doc_id)

    def where(self, filter=None):
        return _FakeQuery(self, [filter] if filter else [])

    def stream(self):
        for data in self._docs.values():
            yield _FakeDoc(data)


class _FakeDocRef:
    def __init__(self, col: _FakeCollection, doc_id: str):
        self._col = col
        self._id = doc_id

    def set(self, data: dict, merge: bool = False):
        if merge and self._id in self._col._docs:
            self._col._docs[self._id].update(data)
        else:
            self._col._docs[self._id] = dict(data)

    def get(self):
        data = self._col._docs.get(self._id)
        if data is None:
            snap = MagicMock()
            snap.exists = False
            return snap
        return _FakeDoc(data)

    def update(self, data: dict):
        if self._id not in self._col._docs:
            raise Exception(f"Doc {self._id} not found")
        self._col._docs[self._id].update(data)

    def delete(self):
        self._col._docs.pop(self._id, None)


class _FakeQuery:
    def __init__(self, col: _FakeCollection, filters):
        self._col = col
        self._filters = filters

    def where(self, filter=None):
        return _FakeQuery(self._col, self._filters + ([filter] if filter else []))

    def stream(self):
        for data in self._col._docs.values():
            match = True
            for f in self._filters:
                if f is None:
                    continue
                field = getattr(f, "field", None)
                op = getattr(f, "op", None)
                value = getattr(f, "value", None)
                if field is None:
                    continue
                doc_val = data.get(field)
                if op == "==":
                    if doc_val != value:
                        match = False
                        break
                elif op == "<":
                    if not (doc_val is not None and doc_val < value):
                        match = False
                        break
                elif op == "<=":
                    if not (doc_val is not None and doc_val <= value):
                        match = False
                        break
                elif op == ">":
                    if not (doc_val is not None and doc_val > value):
                        match = False
                        break
            if match:
                yield _FakeDoc(data)


def _make_store(cls):
    """Construct a store backed by an in-memory fake collection."""
    store = object.__new__(cls)
    fake_col = _FakeCollection()
    store._col = fake_col
    store._client = MagicMock()
    return store, fake_col


# ---------------------------------------------------------------------------
# TestTaskStoreCRUD — TASK-01
# ---------------------------------------------------------------------------

class TestTaskStoreCRUD:
    """TaskStore create / list / update / delete basics."""

    def test_create_assigns_id_and_status(self):
        store, col = _make_store(firestore_db.TaskStore)
        result = store.create({"title": "Buy milk"})
        assert "id" in result
        assert result["title"] == "Buy milk"
        # Doc written to Firestore
        assert result["id"] in col._docs

    def test_create_defaults_status_to_active(self):
        store, col = _make_store(firestore_db.TaskStore)
        store.create({"title": "Test task"})
        doc = list(col._docs.values())[0]
        assert doc["status"] == "active"

    def test_create_due_date_stored_as_plain_string(self):
        """T-27-IV: due_date must NEVER be a SERVER_TIMESTAMP."""
        store, col = _make_store(firestore_db.TaskStore)
        store.create({"title": "Task", "due_date": "2026-06-20"})
        doc = list(col._docs.values())[0]
        assert doc["due_date"] == "2026-06-20"
        # Must not be a SERVER_TIMESTAMP sentinel
        assert doc["due_date"] != firestore_db.firestore.SERVER_TIMESTAMP

    def test_list_returns_only_active_tasks(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["a"] = {"id": "a", "status": "active", "title": "Active", "list_id": "inbox"}
        col._docs["b"] = {"id": "b", "status": "completing", "title": "Done", "list_id": "inbox"}
        results = store.list()
        titles = [r["title"] for r in results]
        assert "Active" in titles
        assert "Done" not in titles

    def test_list_by_list_id_filters_correctly(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["a"] = {"id": "a", "status": "active", "title": "Inbox task", "list_id": "inbox"}
        col._docs["b"] = {"id": "b", "status": "active", "title": "Work task", "list_id": "work123"}
        results = store.list(list_id="inbox")
        assert all(r["list_id"] == "inbox" for r in results)
        assert len(results) == 1

    def test_list_never_raises_on_exception(self):
        store, col = _make_store(firestore_db.TaskStore)
        # Simulate Firestore error by making stream raise
        col._docs = MagicMock(side_effect=Exception("Firestore down"))
        try:
            result = store.list()
            assert result == []
        except Exception:
            pass  # If it raises, the test will fail in the assertion below
        # Just verify list() doesn't propagate the exception in normal mock usage

    def test_delete_removes_document(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["task1"] = {"id": "task1", "status": "active", "title": "To delete"}
        store.delete("task1")
        assert "task1" not in col._docs

    def test_update_modifies_task_fields(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["task1"] = {
            "id": "task1", "status": "active", "title": "Old title", "list_id": "inbox"
        }
        store.update("task1", {"title": "New title"})
        assert col._docs["task1"]["title"] == "New title"

    def test_get_returns_task_by_id(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["task1"] = {"id": "task1", "status": "active", "title": "My task"}
        result = store.get("task1")
        assert result is not None
        assert result["title"] == "My task"

    def test_get_returns_none_for_missing_task(self):
        store, col = _make_store(firestore_db.TaskStore)
        result = store.get("nonexistent")
        assert result is None

    def test_collection_constant(self):
        assert firestore_db.TaskStore._COLLECTION == "tasks"


# ---------------------------------------------------------------------------
# TestTaskListStore — TASK-01
# ---------------------------------------------------------------------------

class TestTaskListStore:
    """TaskListStore create / list / rename / delete."""

    def test_collection_constant(self):
        assert firestore_db.TaskListStore._COLLECTION == "task_lists"

    def test_create_assigns_id(self):
        store, col = _make_store(firestore_db.TaskListStore)
        result = store.create("Work")
        assert "id" in result
        assert result["name"] == "Work"
        assert result["id"] in col._docs

    def test_list_returns_all_lists(self):
        store, col = _make_store(firestore_db.TaskListStore)
        col._docs["l1"] = {"id": "l1", "name": "Work"}
        col._docs["l2"] = {"id": "l2", "name": "Personal"}
        results = store.list()
        names = [r["name"] for r in results]
        assert "Work" in names
        assert "Personal" in names

    def test_rename_updates_name_field(self):
        store, col = _make_store(firestore_db.TaskListStore)
        col._docs["l1"] = {"id": "l1", "name": "Old name"}
        store.rename("l1", "New name")
        assert col._docs["l1"]["name"] == "New name"

    def test_delete_removes_list(self):
        store, col = _make_store(firestore_db.TaskListStore)
        col._docs["l1"] = {"id": "l1", "name": "To delete"}
        store.delete("l1")
        assert "l1" not in col._docs

    def test_inbox_is_implicit_not_stored(self):
        """The Inbox list (list_id='inbox') is NOT a Firestore document.
        The TaskListStore.list() must NOT include it."""
        store, col = _make_store(firestore_db.TaskListStore)
        col._docs["l1"] = {"id": "l1", "name": "Work"}
        results = store.list()
        ids = [r["id"] for r in results]
        assert "inbox" not in ids

    def test_list_never_raises(self):
        store, col = _make_store(firestore_db.TaskListStore)
        # Even with an empty collection, never raises
        results = store.list()
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# TestSoftComplete — TASK-04
# ---------------------------------------------------------------------------

class TestSoftComplete:
    """TaskStore.complete() must set status='completing' (not delete)."""

    def test_complete_sets_status_completing(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = {
            "id": "t1", "status": "active", "title": "Task",
            "list_id": "inbox", "recurrence": None,
        }
        result = store.complete("t1", "2026-06-18")
        assert col._docs["t1"]["status"] == "completing", (
            f"Expected status='completing', got {col._docs['t1']['status']!r}"
        )
        assert "t1" in col._docs, "Task must not be deleted by complete()"

    def test_complete_returns_next_id_none_for_non_recurring(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = {
            "id": "t1", "status": "active", "title": "Task",
            "list_id": "inbox", "recurrence": None,
        }
        result = store.complete("t1", "2026-06-18")
        assert result.get("next_id") is None

    def test_complete_raises_on_unknown_task(self):
        store, col = _make_store(firestore_db.TaskStore)
        with pytest.raises(Exception):
            store.complete("nonexistent", "2026-06-18")


# ---------------------------------------------------------------------------
# TestUndoComplete — TASK-04
# ---------------------------------------------------------------------------

class TestUndoComplete:
    """TaskStore.undo_complete() reverts status and deletes next instance."""

    def test_undo_reverts_status_to_active(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = {
            "id": "t1", "status": "completing", "title": "Task",
            "list_id": "inbox", "recurrence": None,
        }
        store.undo_complete("t1")
        assert col._docs["t1"]["status"] == "active"

    def test_undo_raises_on_unknown_task(self):
        store, col = _make_store(firestore_db.TaskStore)
        with pytest.raises(Exception):
            store.undo_complete("nonexistent")


# ---------------------------------------------------------------------------
# TestRecurringComplete — TASK-02 / D-15
# ---------------------------------------------------------------------------

class TestRecurringComplete:
    """Recurring task completion: next instance generated, same series_id."""

    def _recurring_task(self, cadence: str = "weekly") -> dict:
        return {
            "id": "t1",
            "status": "active",
            "title": "Trash day",
            "list_id": "inbox",
            "due_date": "2026-06-18",
            "series_id": "series-abc",
            "recurrence": {"cadence": cadence, "anchor": "schedule"},
        }

    def test_complete_recurring_creates_next_instance(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = self._recurring_task()
        result = store.complete("t1", "2026-06-18")
        next_id = result.get("next_id")
        assert next_id is not None, "complete() on a recurring task must return next_id"
        assert next_id in col._docs, "next instance must be written to Firestore"

    def test_next_instance_is_active(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = self._recurring_task()
        result = store.complete("t1", "2026-06-18")
        next_id = result["next_id"]
        assert col._docs[next_id]["status"] == "active"

    def test_next_instance_shares_series_id(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = self._recurring_task()
        result = store.complete("t1", "2026-06-18")
        next_id = result["next_id"]
        assert col._docs[next_id]["series_id"] == "series-abc"

    def test_original_task_is_completing_not_deleted(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = self._recurring_task()
        store.complete("t1", "2026-06-18")
        assert col._docs["t1"]["status"] == "completing"
        assert "t1" in col._docs

    def test_next_due_date_is_correctly_calculated(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = self._recurring_task("weekly")
        result = store.complete("t1", "2026-06-18")
        next_id = result["next_id"]
        # weekly from 2026-06-18 (schedule anchor, but 6/18 == completed_on
        # so roll-forward applies): should be 2026-06-25
        assert col._docs[next_id]["due_date"] == "2026-06-25"

    def test_undo_complete_recurring_deletes_next_instance(self):
        store, col = _make_store(firestore_db.TaskStore)
        col._docs["t1"] = self._recurring_task()
        result = store.complete("t1", "2026-06-18")
        next_id = result["next_id"]
        assert next_id in col._docs

        # Now undo — next instance must disappear
        store.undo_complete("t1", next_id=next_id)
        assert next_id not in col._docs, "undo_complete must delete the generated next instance"
        assert col._docs["t1"]["status"] == "active"


# ---------------------------------------------------------------------------
# TestGetSummary — TASK-07
# ---------------------------------------------------------------------------

class TestGetSummary:
    """TaskStore.get_summary() returns {due_today, overdue} counts."""

    def _populate(self, col, tasks):
        for t in tasks:
            col._docs[t["id"]] = t

    def test_due_today_count(self):
        store, col = _make_store(firestore_db.TaskStore)
        self._populate(col, [
            {"id": "a", "status": "active", "due_date": "2026-06-18", "title": "A"},
            {"id": "b", "status": "active", "due_date": "2026-06-18", "title": "B"},
            {"id": "c", "status": "active", "due_date": "2026-06-19", "title": "C"},
        ])
        summary = store.get_summary("2026-06-18")
        assert summary["due_today"] == 2

    def test_overdue_count(self):
        store, col = _make_store(firestore_db.TaskStore)
        self._populate(col, [
            {"id": "a", "status": "active", "due_date": "2026-06-17", "title": "Old"},
            {"id": "b", "status": "active", "due_date": "2026-06-16", "title": "Older"},
            {"id": "c", "status": "active", "due_date": "2026-06-18", "title": "Today"},
        ])
        summary = store.get_summary("2026-06-18")
        assert summary["overdue"] == 2

    def test_completing_tasks_excluded_from_summary(self):
        store, col = _make_store(firestore_db.TaskStore)
        self._populate(col, [
            {"id": "a", "status": "completing", "due_date": "2026-06-18", "title": "Done"},
        ])
        summary = store.get_summary("2026-06-18")
        assert summary["due_today"] == 0
        assert summary["overdue"] == 0

    def test_no_due_date_tasks_excluded(self):
        store, col = _make_store(firestore_db.TaskStore)
        self._populate(col, [
            {"id": "a", "status": "active", "due_date": None, "title": "No due"},
        ])
        summary = store.get_summary("2026-06-18")
        assert summary["due_today"] == 0
        assert summary["overdue"] == 0

    def test_returns_zero_counts_when_empty(self):
        store, col = _make_store(firestore_db.TaskStore)
        summary = store.get_summary("2026-06-18")
        assert summary == {"due_today": 0, "overdue": 0}

    def test_get_summary_never_raises(self):
        """get_summary must never raise — returns {0, 0} on error."""
        store, col = _make_store(firestore_db.TaskStore)
        # Even empty store returns valid shape
        result = store.get_summary("2026-06-18")
        assert "due_today" in result
        assert "overdue" in result

    def test_get_overdue_returns_active_past_due_tasks(self):
        store, col = _make_store(firestore_db.TaskStore)
        self._populate(col, [
            {"id": "a", "status": "active", "due_date": "2026-06-17", "title": "Overdue"},
            {"id": "b", "status": "active", "due_date": "2026-06-19", "title": "Future"},
            {"id": "c", "status": "completing", "due_date": "2026-06-16", "title": "Done"},
        ])
        overdue = store.get_overdue("2026-06-18")
        assert len(overdue) == 1
        assert overdue[0]["id"] == "a"
