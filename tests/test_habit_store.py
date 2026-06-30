"""Tests for HabitStore + compute_streak_and_grid in memory/firestore_db.py.

Phase 28 — HABIT-01/03/04 (TDD RED gate — Task 1)

Covers:
  - TestHabitStoreCRUD: create / list_active / update / soft_delete / restore
  - TestHabitCompletion: log_completion toggle + get_completions_for_date (_jsonsafe_doc)
  - TestStreakComputation: pure reset / non-scheduled neutral / pending neutral / backfill
  - TestDST: spring-forward 2026-03-27 + fall-back 2026-10-25 (HABIT-03 mandate)
  - TestGridDerivation: four-state mapping / rolling-year length / effective-dated schedule (D-19)

Mock strategy
-------------
google.cloud.firestore is mocked at the sys.modules level BEFORE any
memory.firestore_db import, mirroring tests/test_task_store.py exactly.
The `isolated_modules` fixture (from conftest.py) reverts all sys.modules
mutations on teardown.
"""
from __future__ import annotations

import sys
from datetime import date
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# (verbatim copy from tests/test_task_store.py lines 39-131)
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
# In-memory Firestore fakes — habits collection + completions subcollection
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


class _FakeMissingDoc:
    """Mimics a missing Firestore document snapshot."""

    def to_dict(self):
        return None

    @property
    def exists(self):
        return False


class _FakeCollection:
    """In-memory Firestore collection double (habits/{habit_id})."""

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
            return _FakeMissingDoc()
        return _FakeDoc(data)

    def update(self, data: dict):
        if self._id not in self._col._docs:
            raise Exception(f"Doc {self._id!r} not found")
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


# ---------------------------------------------------------------------------
# Nested fake for habit_completions/{date}/records/{habit_id}
# ---------------------------------------------------------------------------

class _FakeCompletionsStore:
    """Simulates habit_completions/{date}/records/{habit_id} nested path."""

    def __init__(self):
        # _data[date_str][habit_id] = doc_data
        self._data: dict[str, dict[str, dict]] = {}

    def document(self, date_str: str):
        return _FakeDateRef(self, date_str)

    def stream(self):
        """Stream date-level document stubs (for hard-delete iteration)."""
        for date_str in self._data:
            stub = MagicMock()
            stub.id = date_str
            yield stub


class _FakeDateRef:
    def __init__(self, store: _FakeCompletionsStore, date_str: str):
        self._store = store
        self._date_str = date_str

    def collection(self, subcol_name: str):
        # subcol_name is "records"
        return _FakeRecordsCol(self._store, self._date_str)


class _FakeRecordsCol:
    def __init__(self, store: _FakeCompletionsStore, date_str: str):
        self._store = store
        self._date_str = date_str

    def document(self, habit_id: str):
        return _FakeRecordRef(self._store, self._date_str, habit_id)

    def stream(self):
        date_data = self._store._data.get(self._date_str, {})
        for hid, data in date_data.items():
            doc = _FakeDoc(data)
            doc.id = hid  # Override: doc ID is the habit_id key, not data["id"]
            yield doc


class _FakeRecordRef:
    def __init__(self, store: _FakeCompletionsStore, date_str: str, habit_id: str):
        self._store = store
        self._date_str = date_str
        self._habit_id = habit_id

    @property
    def exists(self):
        return self._habit_id in self._store._data.get(self._date_str, {})

    def set(self, data: dict, merge: bool = False):
        if self._date_str not in self._store._data:
            self._store._data[self._date_str] = {}
        if merge and self._habit_id in self._store._data.get(self._date_str, {}):
            self._store._data[self._date_str][self._habit_id].update(data)
        else:
            self._store._data[self._date_str][self._habit_id] = dict(data)

    def get(self):
        data = self._store._data.get(self._date_str, {}).get(self._habit_id)
        if data is None:
            return _FakeMissingDoc()
        return _FakeDoc(data)

    def delete(self):
        if self._date_str in self._store._data:
            self._store._data[self._date_str].pop(self._habit_id, None)


def _make_habit_store():
    """Construct a HabitStore backed by in-memory fake collections."""
    store = object.__new__(firestore_db.HabitStore)
    fake_col = _FakeCollection()            # habits/{habit_id}
    fake_completions = _FakeCompletionsStore()  # habit_completions/{date}/records/{id}

    def _client_collection(name):
        if name == "habits":
            return fake_col
        elif name == "habit_completions":
            return fake_completions
        return MagicMock()

    client_mock = MagicMock()
    client_mock.collection.side_effect = _client_collection
    # collection_group used by get_history/delete — return a MagicMock that streams []
    cg_mock = MagicMock()
    cg_mock.where.return_value = cg_mock
    cg_mock.stream.return_value = iter([])
    client_mock.collection_group.return_value = cg_mock

    store._col = fake_col
    store._client = client_mock
    return store, fake_col, fake_completions


# ---------------------------------------------------------------------------
# TestHabitStoreCRUD — HABIT-01
# ---------------------------------------------------------------------------

class TestHabitStoreCRUD:
    """HabitStore create / list_active / update / soft_delete / restore."""

    def test_create_returns_doc_without_updated_at(self):
        store, col, _ = _make_habit_store()
        result = store.create({"name": "Morning run", "type": "habit", "slot": "Morning", "days": "daily"})
        assert "id" in result
        assert result["name"] == "Morning run"
        assert "updated_at" not in result, "create() must strip updated_at from the returned dict"
        assert result["id"] in col._docs

    def test_create_defaults_status_to_active(self):
        store, col, _ = _make_habit_store()
        store.create({"name": "Creatine", "type": "supplement"})
        doc = list(col._docs.values())[0]
        assert doc["status"] == "active"

    def test_create_seeds_schedule_history(self):
        """H-28-IV: schedule_history seeded from days on create; days is never stored top-level."""
        store, col, _ = _make_habit_store()
        result = store.create({"name": "Omega-3", "type": "supplement", "days": [0, 1, 2, 3, 4]})
        assert "schedule_history" in result
        assert len(result["schedule_history"]) >= 1
        assert result["schedule_history"][0]["days"] == [0, 1, 2, 3, 4]

    def test_create_created_at_is_plain_string(self):
        """H-28-IV: created_at must be a plain ISO string, never SERVER_TIMESTAMP."""
        store, col, _ = _make_habit_store()
        result = store.create({"name": "Test", "type": "habit"})
        assert isinstance(result["created_at"], str)
        assert result["created_at"] != firestore_db.firestore.SERVER_TIMESTAMP

    def test_list_active_filters_status(self):
        store, col, _ = _make_habit_store()
        col._docs["a"] = {
            "id": "a", "name": "Run", "type": "habit", "status": "active",
            "schedule_history": [{"effective_from": "2026-01-01", "days": "daily"}],
        }
        col._docs["b"] = {
            "id": "b", "name": "Old", "type": "habit", "status": "completing",
            "schedule_history": [{"effective_from": "2026-01-01", "days": "daily"}],
        }
        results = store.list_active()
        names = [r["name"] for r in results]
        assert "Run" in names
        assert "Old" not in names

    def test_list_active_never_raises(self):
        store, col, _ = _make_habit_store()
        # Even empty collection returns []
        results = store.list_active()
        assert isinstance(results, list)

    def test_update_patches_fields(self):
        store, col, _ = _make_habit_store()
        col._docs["h1"] = {
            "id": "h1", "name": "Old name", "type": "habit", "status": "active",
            "schedule_history": [{"effective_from": "2026-01-01", "days": "daily"}],
        }
        result = store.update("h1", {"name": "New name"})
        assert result is not None
        assert col._docs["h1"]["name"] == "New name"

    def test_update_schedule_days_appends_schedule_history(self):
        """D-19: changing days appends a new schedule_history revision (never mutates prior)."""
        store, col, _ = _make_habit_store()
        col._docs["h1"] = {
            "id": "h1", "name": "Run", "type": "habit", "status": "active",
            "schedule_history": [{"effective_from": "2026-01-01", "days": "daily"}],
        }
        store.update("h1", {"days": [0, 2, 4]})  # Mon/Wed/Fri from today
        updated_history = col._docs["h1"]["schedule_history"]
        assert len(updated_history) == 2, "A second revision must be appended"
        assert updated_history[0]["days"] == "daily", "First revision must be unchanged (D-19)"
        assert updated_history[1]["days"] == [0, 2, 4], "New revision must have updated days"

    def test_soft_delete_sets_completing(self):
        store, col, _ = _make_habit_store()
        col._docs["h1"] = {"id": "h1", "name": "Run", "type": "habit", "status": "active"}
        store.soft_delete("h1")
        assert col._docs["h1"]["status"] == "completing"

    def test_restore_sets_active(self):
        store, col, _ = _make_habit_store()
        col._docs["h1"] = {"id": "h1", "name": "Run", "type": "habit", "status": "completing"}
        store.restore("h1")
        assert col._docs["h1"]["status"] == "active"

    def test_get_returns_none_for_missing_habit(self):
        store, col, _ = _make_habit_store()
        result = store.get("nonexistent")
        assert result is None

    def test_get_returns_habit_by_id(self):
        store, col, _ = _make_habit_store()
        col._docs["h1"] = {"id": "h1", "name": "Run", "type": "habit", "status": "active"}
        result = store.get("h1")
        assert result is not None
        assert result["name"] == "Run"

    def test_collection_constants(self):
        assert firestore_db.HabitStore._COLLECTION == "habits"
        assert firestore_db.HabitStore._COMPLETIONS == "habit_completions"


# ---------------------------------------------------------------------------
# TestHabitCompletion — HABIT-01/02 check-off toggle
# ---------------------------------------------------------------------------

class TestHabitCompletion:
    """log_completion toggle + get_completions_for_date."""

    def test_log_completion_done_writes_subcollection(self):
        store, col, comps = _make_habit_store()
        store.log_completion("2026-06-28", "h1", done=True, dose_taken="5g")
        assert "h1" in comps._data.get("2026-06-28", {}), "completion record must be written"
        record = comps._data["2026-06-28"]["h1"]
        assert record["done"] is True
        assert record["dose_taken"] == "5g"
        assert record["habit_id"] == "h1"
        assert record["date"] == "2026-06-28"

    def test_log_completion_logged_at_is_plain_string(self):
        """H-28-IV: logged_at must be a plain ISO string, never SERVER_TIMESTAMP."""
        store, col, comps = _make_habit_store()
        store.log_completion("2026-06-28", "h1", done=True)
        record = comps._data["2026-06-28"]["h1"]
        assert isinstance(record["logged_at"], str), "logged_at must be a plain ISO string"
        assert record["logged_at"] != firestore_db.firestore.SERVER_TIMESTAMP

    def test_log_completion_undone_deletes_record(self):
        """D-07: done=False deletes the completion record (un-check toggle)."""
        store, col, comps = _make_habit_store()
        # Pre-populate a completion record
        comps._data["2026-06-28"] = {"h1": {"habit_id": "h1", "date": "2026-06-28", "done": True}}
        store.log_completion("2026-06-28", "h1", done=False)
        assert "h1" not in comps._data.get("2026-06-28", {}), "un-check must delete the record"

    def test_log_completion_undone_noop_if_no_record(self):
        """done=False on a non-existent record must not raise (idempotent)."""
        store, col, comps = _make_habit_store()
        store.log_completion("2026-06-28", "h1", done=False)  # should not raise

    def test_get_completions_for_date_returns_dict(self):
        store, col, comps = _make_habit_store()
        comps._data["2026-06-28"] = {
            "h1": {"habit_id": "h1", "date": "2026-06-28", "done": True, "dose_taken": None},
            "h2": {"habit_id": "h2", "date": "2026-06-28", "done": True, "dose_taken": "10ml"},
        }
        result = store.get_completions_for_date("2026-06-28")
        assert "h1" in result
        assert "h2" in result
        assert result["h1"]["done"] is True

    def test_get_completions_for_date_applies_jsonsafe(self):
        """Pitfall 1: DatetimeWithNanoseconds in updated_at must not leak into the dict.

        Firestore SERVER_TIMESTAMP reads back as DatetimeWithNanoseconds which has
        .isoformat() but is not json-serializable.  _jsonsafe_doc converts it to a
        plain string.  This test simulates that with a MagicMock that has .isoformat().
        """
        import json
        store, col, comps = _make_habit_store()
        # Simulate DatetimeWithNanoseconds: has isoformat() but is not JSON-serializable
        dt_sentinel = MagicMock()
        dt_sentinel.isoformat.return_value = "2026-06-28T10:00:00+00:00"
        # Verify that this sentinel itself is NOT json-serializable (precondition)
        try:
            json.dumps({"x": dt_sentinel})
            pytest.skip("MagicMock is accidentally JSON-safe in this env — test invalid")
        except TypeError:
            pass  # expected: MagicMock is not json-serializable
        comps._data["2026-06-28"] = {
            "h1": {
                "habit_id": "h1",
                "date": "2026-06-28",
                "done": True,
                "dose_taken": None,
                "updated_at": dt_sentinel,
            }
        }
        result = store.get_completions_for_date("2026-06-28")
        # Must round-trip through json.dumps without raising
        try:
            json.dumps(result)
        except TypeError as exc:
            pytest.fail(f"get_completions_for_date result not JSON-safe: {exc}")

    def test_get_completions_for_date_never_raises(self):
        store, col, comps = _make_habit_store()
        # Empty date → empty dict
        result = store.get_completions_for_date("2026-06-28")
        assert result == {}


# ---------------------------------------------------------------------------
# TestStreakComputation — pure compute_streak_and_grid function (no Firestore)
# ---------------------------------------------------------------------------

class TestStreakComputation:
    """compute_streak_and_grid: streak rules D-10/D-11/D-12."""

    def test_pure_reset_on_missed_day(self):
        """D-10: any confirmed missed scheduled day resets streak to 0."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        # today=2026-06-30; yesterday=2026-06-29 (pending);
        # 2026-06-28 = confirmed miss (2 days before today, no completion)
        # 2026-06-25 through 2026-06-27 have completions before the gap
        completions = {
            "2026-06-25": {"done": True},
            "2026-06-26": {"done": True},
            "2026-06-27": {"done": True},
            # gap: 2026-06-28 missing → confirmed miss (before yesterday)
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 6, 30)
        )
        assert result["streak"] == 0, "Confirmed miss must reset streak to 0"
        # Verify the missed day has state "missed"
        missed_cell = next(c for c in result["grid"] if c["date"] == "2026-06-28")
        assert missed_cell["state"] == "missed"

    def test_nonscheduled_days_neutral(self):
        """Non-scheduled days are neutral: don't break streak, don't count."""
        # Mon/Wed/Fri schedule (days=[0,2,4])
        schedule = [{"effective_from": "2026-01-01", "days": [0, 2, 4]}]
        # 2026-06-19=Fri, 2026-06-22=Mon, 2026-06-24=Wed, all done
        # Non-scheduled: Sat/Sun/Tue/Thu
        # today = 2026-06-24 (Wednesday, done)
        completions = {
            "2026-06-19": {"done": True},  # Fri
            "2026-06-22": {"done": True},  # Mon
            "2026-06-24": {"done": True},  # Wed = today
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 6, 24)
        )
        # Non-scheduled days (Sat/Sun/Tue/Thu) should be "not-scheduled"
        thu_cell = next(c for c in result["grid"] if c["date"] == "2026-06-19")
        # 2026-06-21 is Saturday — not scheduled
        sat_cell = next(c for c in result["grid"] if c["date"] == "2026-06-21")
        assert sat_cell["state"] == "not-scheduled"
        # Streak should be >= 3 (Mon, Wed count + Fri was before yesterday → done)
        assert result["streak"] >= 3, (
            f"Non-scheduled days must not break streak; got streak={result['streak']}"
        )

    def test_pending_does_not_break_streak(self):
        """Pitfall 6: today and yesterday 'pending' must NOT break the streak."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        # today = 2026-06-28, not checked off yet → pending
        # yesterday = 2026-06-27, not checked off → pending (in backfill window)
        # 2026-06-25, 2026-06-26 = done
        completions = {
            "2026-06-25": {"done": True},
            "2026-06-26": {"done": True},
            # today and yesterday missing → pending, not missed
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 6, 28)
        )
        assert result["streak"] >= 2, (
            f"Pending today/yesterday must not break streak; got streak={result['streak']}"
        )
        # Confirm today and yesterday are "pending"
        today_cell = next(c for c in result["grid"] if c["date"] == "2026-06-28")
        yesterday_cell = next(c for c in result["grid"] if c["date"] == "2026-06-27")
        assert today_cell["state"] == "pending"
        assert yesterday_cell["state"] == "pending"

    def test_yesterday_backfill_repairs_streak(self):
        """D-11: adding yesterday's completion increments the streak by 1."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        # today = 2026-06-28
        # Shared base: 2026-06-25 and 2026-06-26 done; 2026-06-24 missed (confirmed)
        base_completions = {
            "2026-06-25": {"done": True},
            "2026-06-26": {"done": True},
        }
        result_no_backfill = firestore_db.compute_streak_and_grid(
            "h1", schedule, base_completions, today=date(2026, 6, 28)
        )
        # With yesterday (2026-06-27) backfilled
        with_backfill = {**base_completions, "2026-06-27": {"done": True}}
        result_with_backfill = firestore_db.compute_streak_and_grid(
            "h1", schedule, with_backfill, today=date(2026, 6, 28)
        )
        assert result_with_backfill["streak"] == result_no_backfill["streak"] + 1, (
            "Backfilling yesterday must extend streak by exactly 1"
        )
        # Yesterday cell is "done" in backfill scenario
        yesterday_cell = next(
            c for c in result_with_backfill["grid"] if c["date"] == "2026-06-27"
        )
        assert yesterday_cell["state"] == "done"

    def test_fresh_habit_no_completions_streak_zero(self):
        """A brand new habit with no completions has streak 0."""
        schedule = [{"effective_from": "2026-06-28", "days": "daily"}]
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, {}, today=date(2026, 6, 28)
        )
        assert result["streak"] == 0

    def test_consecutive_completions_build_streak(self):
        """N consecutive done days = streak N (simplified, no gaps)."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        completions = {
            "2026-06-25": {"done": True},
            "2026-06-26": {"done": True},
            "2026-06-27": {"done": True},
            "2026-06-28": {"done": True},  # today
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 6, 28)
        )
        assert result["streak"] == 4


# ---------------------------------------------------------------------------
# TestDST — Israel spring-forward/fall-back (HABIT-03 mandatory fixtures)
# ---------------------------------------------------------------------------

class TestDST:
    """DST-boundary streak fixtures — HABIT-03 mandate."""

    def test_streak_survives_spring_forward_dst(self):
        """Streak does not break across Israel's March DST transition (2026-03-27)."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        completions = {
            "2026-03-26": {"done": True},
            "2026-03-27": {"done": True},  # Spring-forward day (ILST → IDT)
            "2026-03-28": {"done": True},
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 3, 28)
        )
        assert result["streak"] >= 3, (
            f"Streak must survive spring-forward DST; got {result['streak']}"
        )

    def test_streak_survives_fall_back_dst(self):
        """Streak does not break across Israel's October DST transition (2026-10-25)."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        completions = {
            "2026-10-24": {"done": True},
            "2026-10-25": {"done": True},  # Fall-back day (IDT → ILST)
            "2026-10-26": {"done": True},
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 10, 26)
        )
        assert result["streak"] >= 3, (
            f"Streak must survive fall-back DST; got {result['streak']}"
        )


# ---------------------------------------------------------------------------
# TestGridDerivation — four-state grid + effective-dated schedule (HABIT-04)
# ---------------------------------------------------------------------------

class TestGridDerivation:
    """compute_streak_and_grid grid output: four states + D-19 schedule revisions."""

    def test_four_state_mapping(self):
        """Grid must emit all four states: done/missed/not-scheduled/pending."""
        # Mon/Wed/Fri schedule from 2026-01-01
        schedule = [{"effective_from": "2026-01-01", "days": [0, 2, 4]}]
        # today = 2026-06-26 (Friday) — pending (not done)
        # yesterday = 2026-06-25 (Thursday) — not-scheduled
        # 2026-06-24 (Wednesday) — done
        # 2026-06-22 (Monday) — missed (confirmed: before yesterday, no completion)
        completions = {
            "2026-06-24": {"done": True},  # Wednesday = done
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 6, 26)
        )
        grid_by_date = {c["date"]: c["state"] for c in result["grid"]}

        assert grid_by_date["2026-06-26"] == "pending", "Today unchecked = pending"
        assert grid_by_date["2026-06-25"] == "not-scheduled", "Thursday = not-scheduled"
        assert grid_by_date["2026-06-24"] == "done", "Completed Wednesday = done"
        assert grid_by_date["2026-06-22"] == "missed", "Missed Monday (confirmed) = missed"

    def test_rolling_year_length(self):
        """Grid must have exactly window_days entries."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, {}, today=date(2026, 6, 30), window_days=365
        )
        assert len(result["grid"]) == 365

    def test_custom_window_days(self):
        """Custom window_days is respected."""
        schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, {}, today=date(2026, 6, 30), window_days=30
        )
        assert len(result["grid"]) == 30

    def test_effective_dated_schedule_revision(self):
        """D-19 / Pitfall 7: pre-revision dates resolve under the EARLIER revision.

        Scenario: habit was daily until 2026-06-15, then switched to Mon-only.
        Dates before 2026-06-15 must be computed under "daily".
        Dates from 2026-06-15 onward must be computed under [0] (Monday only).

        today = 2026-06-29 (Monday, weekday=0).
        2026-06-14 = Sunday (before revision) → under "daily" → scheduled → done.
        2026-06-21 = Sunday (after revision) → under [0] Mon-only → not-scheduled.
        2026-06-29 = Monday (today, after revision) → under [0] → pending.
        """
        schedule = [
            {"effective_from": "2026-01-01", "days": "daily"},
            {"effective_from": "2026-06-15", "days": [0]},  # Mon only from June 15
        ]
        completions = {
            "2026-06-14": {"done": True},  # Sunday, before revision, should be "done"
        }
        result = firestore_db.compute_streak_and_grid(
            "h1", schedule, completions, today=date(2026, 6, 29)   # Monday
        )
        grid_by_date = {c["date"]: c["state"] for c in result["grid"]}

        # 2026-06-14 = Sunday: under daily revision → scheduled → done (completion present)
        assert grid_by_date["2026-06-14"] == "done", (
            "Pre-revision Sunday must be 'done' under the earlier 'daily' revision (D-19)"
        )
        # 2026-06-21 = Sunday, after revision: under [0] (Mon only) → not-scheduled
        assert grid_by_date["2026-06-21"] == "not-scheduled", (
            "Post-revision Sunday must be 'not-scheduled' under the Mon-only revision"
        )
        # 2026-06-29 = Monday, today, after revision: under [0] → pending (no completion)
        assert grid_by_date["2026-06-29"] == "pending", (
            "Post-revision Monday (today) must be 'pending' under Mon-only revision"
        )
