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


_install_firestore_mock()


# Import after mocks are installed. We import the module object (not symbols)
# so that the autouse fixture below can refresh the binding when other test
# files in the suite re-mock google.cloud.firestore.
import memory.firestore_db as firestore_db  # noqa: E402


@pytest.fixture(autouse=True)
def _refresh_firestore_mock():
    """Re-install the firestore mock and re-import memory.firestore_db before
    each test in case a sibling test file mutated sys.modules. Matches the
    pattern in test_llm_usage_store.py but uses import_module rather than
    importlib.reload — because _install_firestore_mock() deletes
    memory.firestore_db from sys.modules to force a clean re-bind to the new
    mock sentinels, reload() can't be used (it requires the module to still
    be in sys.modules)."""
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
