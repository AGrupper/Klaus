"""Tests for the Phase 18 Firestore stores in memory/firestore_db.py.

Covers:
  - FollowupStore  (AUTO-04, D-12/D-13/D-14/D-15)
  - OutreachLogStore  (AUTO-03, D-07/D-09/D-10)
  - TickLogStore  (NOTE 1, D-21)

Mock strategy
-------------
Firestore is mocked at the sys.modules level using the same
`_install_firestore_mock()` pattern established in test_llm_usage_store.py
and test_reflection.py — google.cloud.firestore is replaced with a MagicMock
before any module under test is imported, so no real GCP connection or
installed google-cloud-firestore package is required.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore and related stubs into sys.modules."""
    # Preserve real google namespace packages if they happen to be installed,
    # otherwise create lightweight ModuleType placeholders.
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

        if "google.cloud" not in sys.modules or isinstance(sys.modules["google.cloud"], MagicMock):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()

    # firestore.Increment must return a distinguishable sentinel so tests can
    # assert "field uses Increment, not a raw value".
    class _Increment:
        def __init__(self, value):
            self.value = value

        def __repr__(self):
            return f"Increment({self.value!r})"

    # firestore.ArrayUnion must also be a distinguishable sentinel — the
    # OutreachLogStore.append assertion needs to confirm the entry list is
    # wrapped in ArrayUnion, not passed as a plain list.
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

    # google.api_core.exceptions — only GoogleAPICallError is consumed.
    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    # google.cloud.firestore_v1.base_query — only FieldFilter is consumed.
    class _FieldFilter:
        """Distinguishable FieldFilter sentinel — captures (field, op, value)."""

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

    # google.oauth2 — used inside _make_firestore_client when FIRESTORE_CREDENTIALS set
    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    # dotenv — load_dotenv is called at module level in _smoke_test, never in tests
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db so it picks up the mocks
    for key in list(sys.modules.keys()):
        if "memory.firestore_db" in key or key == "memory.firestore_db":
            del sys.modules[key]


# Bound per-test by the autouse fixture below. We deliberately do NOT install
# the mock or import memory.firestore_db at module/collection time — doing so
# leaks fake google.* modules into sys.modules for the whole session and breaks
# sibling test files. The fixture installs the mock at test time, guarded by
# isolated_modules so every key is restored on teardown.
firestore_db = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _refresh_firestore_mock(isolated_modules):
    """Install the firestore mock and import memory.firestore_db against it
    before each test. isolated_modules reverts every sys.modules mutation on
    teardown so nothing leaks into later tests."""
    global firestore_db
    import importlib
    _install_firestore_mock()
    firestore_db = importlib.import_module("memory.firestore_db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client_with_collection():
    """Return (client, col) MagicMocks wired so client.collection(...) -> col."""
    client = MagicMock()
    col = MagicMock()
    client.collection.return_value = col
    return client, col


def _stub_existing_doc(col: MagicMock, doc_id: str, data: dict) -> MagicMock:
    """Wire col.document(doc_id) to return a MagicMock doc_ref whose .get()
    returns a snapshot with exists=True and to_dict()->data. Returns doc_ref."""
    doc_ref = MagicMock()
    snap = MagicMock()
    snap.exists = True
    snap.id = doc_id
    snap.to_dict.return_value = dict(data)
    doc_ref.get.return_value = snap
    col.document.return_value = doc_ref
    return doc_ref


def _stub_missing_doc(col: MagicMock, doc_id: str) -> MagicMock:
    """Wire col.document(doc_id) to return a doc_ref whose .get() returns
    a snapshot with exists=False."""
    doc_ref = MagicMock()
    snap = MagicMock()
    snap.exists = False
    doc_ref.get.return_value = snap
    col.document.return_value = doc_ref
    return doc_ref


# =============================================================================
# FollowupStore — AUTO-04, D-12/D-13/D-14/D-15
# =============================================================================

class TestFollowupStore:
    """Unit tests for FollowupStore — scheduled check-backs."""

    def test_add_persists_pending_doc(self):
        """add() must persist status='pending', defer_count=0, origin='user_chat' default."""
        client, col = _make_mock_client_with_collection()
        captured: dict = {}
        doc_ref = MagicMock()

        def _capture_set(payload):
            captured.update(payload)

        doc_ref.set.side_effect = _capture_set
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            result = store.add(due_at="2026-05-21T15:00:00+00:00", note="check on maya")

        # Returned dict shape
        assert "id" in result and isinstance(result["id"], str) and result["id"]
        assert result["due_at"] == "2026-05-21T15:00:00+00:00"

        # Persisted doc shape
        assert captured["status"] == "pending"
        assert captured["defer_count"] == 0
        assert captured["origin"] == "user_chat"
        assert captured["note"] == "check on maya"
        assert captured["due_at"] == "2026-05-21T15:00:00+00:00"
        assert captured["id"] == result["id"]
        assert "created_at" in captured and captured["created_at"]  # ISO string

    def test_add_with_origin_klaus_self(self):
        """add() honors origin='klaus_self' when explicitly passed."""
        client, col = _make_mock_client_with_collection()
        captured: dict = {}
        doc_ref = MagicMock()
        doc_ref.set.side_effect = lambda p: captured.update(p)
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            store.add(
                due_at="2026-05-21T15:00:00+00:00",
                note="self-managed check-back",
                origin="klaus_self",
            )

        assert captured["origin"] == "klaus_self"

    def test_list_due_filters_by_status_and_time(self):
        """list_due(now) returns only docs with status=='pending' AND due_at<=now."""
        client, col = _make_mock_client_with_collection()

        # Build mock snapshots — list_due relies on the .where() chain to do
        # the actual filtering, so we just return whatever the chain yields.
        due_doc = {
            "id": "abc",
            "due_at": "2026-05-21T14:00:00+00:00",
            "status": "pending",
            "note": "tea time",
        }
        snap = MagicMock()
        snap.to_dict.return_value = due_doc

        # Capture what filters were applied so we can assert the FieldFilter
        # values match the contract.
        applied_filters = []

        def _where(*args, **kwargs):
            f = kwargs.get("filter")
            if f is not None:
                applied_filters.append(f)
            return col  # chainable

        col.where.side_effect = _where
        col.stream.return_value = iter([snap])

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            results = store.list_due("2026-05-21T15:00:00+00:00")

        assert results == [due_doc]
        # Two FieldFilter calls expected: one on status, one on due_at.
        assert len(applied_filters) == 2, (
            f"Expected 2 FieldFilter clauses (status, due_at), got {len(applied_filters)}"
        )
        fields = {(f.field, f.op) for f in applied_filters}
        assert ("status", "==") in fields
        assert ("due_at", "<=") in fields
        # status filter value must be 'pending'; due_at value must match the now arg.
        for f in applied_filters:
            if f.field == "status":
                assert f.value == "pending"
            if f.field == "due_at":
                assert f.value == "2026-05-21T15:00:00+00:00"

    def test_list_pending_returns_all_pending(self):
        """list_pending() returns all status=='pending' docs regardless of due_at."""
        client, col = _make_mock_client_with_collection()

        snap = MagicMock()
        snap.to_dict.return_value = {"id": "x", "status": "pending", "due_at": "2999-01-01T00:00:00+00:00"}

        applied_filters = []

        def _where(*args, **kwargs):
            f = kwargs.get("filter")
            if f is not None:
                applied_filters.append(f)
            return col

        col.where.side_effect = _where
        col.stream.return_value = iter([snap])

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            results = store.list_pending()

        assert len(results) == 1
        assert results[0]["status"] == "pending"
        # Only ONE filter (status==pending) — no due_at clause.
        assert len(applied_filters) == 1
        assert applied_filters[0].field == "status"
        assert applied_filters[0].op == "=="
        assert applied_filters[0].value == "pending"

    def test_mark_done_updates_status(self):
        """mark_done(id) must call .update({'status': 'done'})."""
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            store.mark_done("abc")

        col.document.assert_called_with("abc")
        doc_ref.update.assert_called_once_with({"status": "done"})

    def test_cancel_idempotent(self):
        """cancel(id) returns True when doc exists; calling twice still returns True."""
        client, col = _make_mock_client_with_collection()
        doc_ref = _stub_existing_doc(col, "abc", {"id": "abc", "status": "pending"})

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            assert store.cancel("abc") is True
            # Second call — still True (idempotent).
            assert store.cancel("abc") is True

        doc_ref.update.assert_called_with({"status": "cancelled"})

    def test_cancel_nonexistent_returns_false(self):
        """cancel(id) returns False when the doc does not exist."""
        client, col = _make_mock_client_with_collection()
        _stub_missing_doc(col, "ghost")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            assert store.cancel("ghost") is False

    def test_defer_uses_firestore_increment(self):
        """defer(id, new_due_at) updates due_at and increments defer_count via firestore.Increment."""
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            store.defer("abc", "2026-05-22T15:00:00+00:00")

        doc_ref.update.assert_called_once()
        payload = doc_ref.update.call_args.args[0]
        assert payload["due_at"] == "2026-05-22T15:00:00+00:00"
        # defer_count must use firestore.Increment, not a raw value.
        increment_val = payload["defer_count"]
        assert "Increment" in type(increment_val).__name__, (
            f"defer_count should be firestore.Increment, got {type(increment_val).__name__}"
        )
        assert increment_val.value == 1

    def test_list_due_returns_empty_on_firestore_error(self):
        """list_due() must return [] (not raise) when Firestore raises."""
        client, col = _make_mock_client_with_collection()
        col.where.side_effect = RuntimeError("simulated Firestore outage")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            result = store.list_due("2026-05-21T15:00:00+00:00")

        assert result == []

    def test_list_pending_returns_empty_on_firestore_error(self):
        """list_pending() must return [] (not raise) when Firestore raises."""
        client, col = _make_mock_client_with_collection()
        col.where.side_effect = RuntimeError("boom")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            assert store.list_pending() == []

    def test_add_raises_on_firestore_error(self):
        """add() must log and re-raise when Firestore .set() fails."""
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        doc_ref.set.side_effect = RuntimeError("simulated set failure")
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.FollowupStore("test-project")
            with pytest.raises(RuntimeError):
                store.add(due_at="2026-05-21T15:00:00+00:00", note="boom")


# =============================================================================
# OutreachLogStore — AUTO-03, D-07/D-09/D-10/D-21
# =============================================================================

class TestOutreachLogStore:
    """Unit tests for OutreachLogStore — per-day record of autonomous outreach."""

    _DATE = "2026-05-21"
    _ENTRY = {
        "topic_key": "overdue:reply-to-maya",
        "time": "14:20",
        "draft": "Sir, you have an overdue task...",
        "final": "Sir, that reply to Maya is still on your plate.",
        "tick_index": 22,
    }

    def test_append_uses_array_union_atomically(self):
        """append() must wrap the entry in firestore.ArrayUnion and merge=True."""
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            store.append(self._DATE, self._ENTRY)

        # set() called once on the date-keyed doc.
        col.document.assert_called_with(self._DATE)
        doc_ref.set.assert_called_once()
        args, kwargs = doc_ref.set.call_args
        payload = args[0]

        assert kwargs.get("merge") is True, "OutreachLogStore.append must use merge=True"
        assert payload["date"] == self._DATE

        # entries field must be ArrayUnion-wrapped, not a plain list.
        entries_val = payload["entries"]
        assert "ArrayUnion" in type(entries_val).__name__, (
            f"entries should be wrapped in firestore.ArrayUnion, got {type(entries_val).__name__}"
        )
        assert entries_val.values == [self._ENTRY]

        # updated_at uses the SERVER_TIMESTAMP sentinel at the doc level
        # (not inside the entry — that would break ArrayUnion dedup per NOTE 2).
        assert payload["updated_at"] is firestore_db.firestore.SERVER_TIMESTAMP

    def test_get_today_returns_entries_list(self):
        """get_today(date) returns the entries list when the doc exists."""
        client, col = _make_mock_client_with_collection()
        _stub_existing_doc(col, self._DATE, {
            "date": self._DATE,
            "entries": [self._ENTRY, {"topic_key": "silence:afternoon", "time": "16:00"}],
        })

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            result = store.get_today(self._DATE)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == self._ENTRY

    def test_get_today_missing_doc_returns_empty(self):
        """get_today(date) returns [] when no doc for that date."""
        client, col = _make_mock_client_with_collection()
        _stub_missing_doc(col, "1999-01-01")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            assert store.get_today("1999-01-01") == []

    def test_topics_today_returns_topic_keys_in_order(self):
        """topics_today(date) returns the list of topic_keys from entries."""
        client, col = _make_mock_client_with_collection()
        _stub_existing_doc(col, self._DATE, {
            "date": self._DATE,
            "entries": [
                {"topic_key": "overdue:reply-to-maya", "time": "14:20"},
                {"topic_key": "silence:afternoon", "time": "16:00"},
            ],
        })

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            topics = store.topics_today(self._DATE)

        assert topics == ["overdue:reply-to-maya", "silence:afternoon"]

    def test_topics_today_missing_doc_returns_empty(self):
        """topics_today(date) returns [] when no doc for that date."""
        client, col = _make_mock_client_with_collection()
        _stub_missing_doc(col, "1999-01-01")

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            assert store.topics_today("1999-01-01") == []

    def test_get_today_returns_empty_on_firestore_error(self):
        """Firestore .get() error → get_today and topics_today return [] (never raise)."""
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        doc_ref.get.side_effect = RuntimeError("simulated outage")
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            assert store.get_today(self._DATE) == []
            assert store.topics_today(self._DATE) == []

    def test_append_raises_on_firestore_error(self):
        """append() must log and re-raise when Firestore .set() fails."""
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        doc_ref.set.side_effect = RuntimeError("simulated set failure")
        col.document.return_value = doc_ref

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.OutreachLogStore("test-project")
            with pytest.raises(RuntimeError):
                store.append(self._DATE, self._ENTRY)

    def test_append_docstring_warns_about_server_timestamp(self):
        """NOTE 2 regression guard — the warning must stay in the docstring.

        Future devs must not silently drop the warning that putting
        firestore.SERVER_TIMESTAMP inside the entry dict breaks ArrayUnion's
        deep-equality dedup semantics.
        """
        doc = firestore_db.OutreachLogStore.append.__doc__ or ""
        assert "SERVER_TIMESTAMP" in doc, (
            "NOTE 2 regression: OutreachLogStore.append docstring must warn against "
            "passing SERVER_TIMESTAMP inside entry dicts (ArrayUnion equality break)"
        )


# =============================================================================
# TickLogStore — NOTE 1, D-21
# =============================================================================

class TestTickLogStore:
    """Unit tests for TickLogStore — per-tick eval-fixture snapshots."""

    _DATE = "2026-05-21"
    _TICK = "14:20"
    _SITUATION = {
        "calendar": [],
        "ticktick_overdue": ["reply-to-maya"],
        "hours_since_contact": 4.5,
        "empty": False,
    }
    _DECISION = {
        "sent": True,
        "trail": ["gather", "tick_brain", "compose", "send"],
        "topic_key": "overdue:reply-to-maya",
    }

    def test_write_persists_tick_snapshot(self):
        """write(date, tick, situation, decision) must write to tick_logs/{date}/ticks/{HH:MM}."""
        client, col = _make_mock_client_with_collection()

        # Capture the sub-collection chain: col.document(date).collection("ticks").document(tick).set(...)
        date_doc = MagicMock()
        ticks_col = MagicMock()
        tick_doc = MagicMock()
        col.document.return_value = date_doc
        date_doc.collection.return_value = ticks_col
        ticks_col.document.return_value = tick_doc

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.TickLogStore("test-project")
            result = store.write(self._DATE, self._TICK, self._SITUATION, self._DECISION)

        # Best-effort writes return None implicitly.
        assert result is None
        col.document.assert_called_with(self._DATE)
        date_doc.collection.assert_called_with("ticks")
        ticks_col.document.assert_called_with(self._TICK)

        tick_doc.set.assert_called_once()
        payload = tick_doc.set.call_args.args[0]

        # Three required top-level fields.
        assert "captured_at" in payload and payload["captured_at"]  # ISO string
        assert "situation_snapshot" in payload
        assert "decision_trail" in payload
        # Decision trail passes through verbatim.
        assert payload["decision_trail"] == self._DECISION
        # situation_snapshot strips the 'empty' field but keeps the others.
        assert "empty" not in payload["situation_snapshot"]
        assert payload["situation_snapshot"]["calendar"] == []
        assert payload["situation_snapshot"]["ticktick_overdue"] == ["reply-to-maya"]
        assert payload["situation_snapshot"]["hours_since_contact"] == 4.5

    def test_write_swallows_firestore_error(self):
        """TickLogStore.write must NEVER raise — best-effort contract (Plan 06 _write_tick_log)."""
        client, col = _make_mock_client_with_collection()
        # Make the inner .set() raise.
        date_doc = MagicMock()
        ticks_col = MagicMock()
        tick_doc = MagicMock()
        tick_doc.set.side_effect = RuntimeError("simulated tick-log outage")
        col.document.return_value = date_doc
        date_doc.collection.return_value = ticks_col
        ticks_col.document.return_value = tick_doc

        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.TickLogStore("test-project")
            # Must not raise.
            result = store.write(self._DATE, self._TICK, self._SITUATION, self._DECISION)

        assert result is None

    def _store_with_ticks(self, subcollections):
        from tests.fakes import FakeCollection
        client = MagicMock()
        client.collection.return_value = FakeCollection([], subcollections)
        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            return firestore_db.TickLogStore("test-project")

    def test_ticks_for_date_sorted_with_time_ids(self):
        """ticks_for_date returns docs sorted by HH:MM with 'time' attached."""
        from tests.fakes import FakeCollection, make_snap
        snaps = [
            make_snap("14:20", {"captured_at": "b", "situation_snapshot": {}, "decision_trail": {}}),
            make_snap("07:00", {"captured_at": "a", "situation_snapshot": {}, "decision_trail": {}}),
        ]
        store = self._store_with_ticks({self._DATE: {"ticks": FakeCollection(snaps)}})

        ticks = store.ticks_for_date(self._DATE)

        assert [t["time"] for t in ticks] == ["07:00", "14:20"]
        assert ticks[0]["captured_at"] == "a"

    def test_ticks_for_date_missing_date_returns_empty(self):
        """A date with no ticks subcollection yields [] — not an error."""
        store = self._store_with_ticks({})
        assert store.ticks_for_date("2099-01-01") == []

    def test_ticks_for_date_never_raises(self):
        """Firestore errors are swallowed and reported as [] (export must not
        crash on one bad day)."""
        client, col = _make_mock_client_with_collection()
        col.document.side_effect = RuntimeError("simulated outage")
        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.TickLogStore("test-project")
        assert store.ticks_for_date(self._DATE) == []


# ---------------------------------------------------------------------------
# TTL read cache — SelfStateStore.get / JournalStore.get / get_recent
# ---------------------------------------------------------------------------

class TestReadCache:
    """The module-level TTL cache must serve repeat reads, be invalidated by
    writes, expire after the TTL, and stay inert for __new__-built stores."""

    def _journal_store(self, docs: dict[str, dict]):
        client, col = _make_mock_client_with_collection()
        for date_str, data in docs.items():
            _stub_existing_doc(col, date_str, data)
        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.JournalStore("test-project")
        return store, col

    def test_journal_get_served_from_cache(self):
        store, col = self._journal_store({"2026-06-10": {"summary": "day"}})

        first = store.get("2026-06-10")
        second = store.get("2026-06-10")

        assert first == second
        assert col.document.call_count == 1, "second get() must not hit Firestore"

    def test_journal_set_invalidates_cache(self):
        store, col = self._journal_store({"2026-06-10": {"summary": "day"}})

        store.get("2026-06-10")
        store.set("2026-06-10", {"summary": "rewritten"})
        store.get("2026-06-10")

        # document() used for: get, set, get-after-invalidation.
        assert col.document.call_count == 3

    def test_journal_missing_entry_not_cached(self):
        """A miss (no journal yet) must not be cached — tonight's entry can
        appear at any moment via the nightly reflection."""
        client, col = _make_mock_client_with_collection()
        snap = MagicMock()
        snap.exists = False
        col.document.return_value.get.return_value = snap
        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.JournalStore("test-project")

        assert store.get("2026-06-10") is None
        assert store.get("2026-06-10") is None
        assert col.document.call_count == 2

    def test_journal_cache_expires_after_ttl(self, monkeypatch):
        store, col = self._journal_store({"2026-06-10": {"summary": "day"}})
        monkeypatch.setattr(firestore_db, "_READ_CACHE_TTL_SEC", -1)

        store.get("2026-06-10")
        store.get("2026-06-10")

        assert col.document.call_count == 2, "expired entry must re-read"

    def test_new_built_store_bypasses_cache(self):
        """Stores built via __new__ (the store-test pattern) have no
        _cache_key and must never touch the shared cache."""
        store = firestore_db.JournalStore.__new__(firestore_db.JournalStore)
        col = MagicMock()
        snap = MagicMock()
        snap.exists = True
        snap.id = "2026-06-10"
        snap.to_dict.return_value = {"summary": "day"}
        col.document.return_value.get.return_value = snap
        store._col = col

        store.get("2026-06-10")
        store.get("2026-06-10")

        assert col.document.call_count == 2
        assert firestore_db._READ_CACHE == {}

    def test_self_state_get_served_from_cache_and_invalidated_by_set(self):
        client, col = _make_mock_client_with_collection()
        doc_ref = MagicMock()
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {"mood": "sharp"}
        doc_ref.get.return_value = snap
        col.document.return_value = doc_ref
        with patch.object(firestore_db, "_make_firestore_client", return_value=client):
            store = firestore_db.SelfStateStore("test-project")

        assert store.get() == {"mood": "sharp"}
        assert store.get() == {"mood": "sharp"}
        assert doc_ref.get.call_count == 1, "second get() must be a cache hit"

        store.set({"mood": "calm"})
        store.get()
        assert doc_ref.get.call_count == 2, "set() must invalidate the cache"

    def test_cached_value_is_copied_not_shared(self):
        """Mutating a returned dict must not corrupt the cached copy."""
        store, _ = self._journal_store({"2026-06-10": {"summary": "day"}})

        first = store.get("2026-06-10")
        first["summary"] = "mutated by caller"
        second = store.get("2026-06-10")

        assert second["summary"] == "day"
