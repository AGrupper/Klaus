"""Tests for memory/firestore_db.py::PushSubscriptionStore (Phase 29 — PUSH-01).

Covers:
  - upsert writes doc keyed by sha256(endpoint)[:32], merge=True, idempotent
  - upsert re-raises on Firestore write failure
  - list_all returns _jsonsafe_doc dicts, [] on read failure (never raises)
  - delete targets the sha256-hashed doc, re-raises on failure
  - record_success / record_failure merge-write the right fields

Mocks google.cloud.firestore at sys.modules level — mirrors
tests/test_run_detail_store.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from tests.fakes import FailingCollection, FakeCollection


def _install_firestore_mock() -> MagicMock:
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        google_mod = sys.modules.get("google") or ModuleType("google")
        google_mod.__path__ = []
        sys.modules["google"] = google_mod
        google_cloud_mod = sys.modules.get("google.cloud") or ModuleType("google.cloud")
        google_cloud_mod.__path__ = []
        sys.modules["google.cloud"] = google_cloud_mod
        setattr(google_mod, "cloud", google_cloud_mod)

    firestore_mock = MagicMock()
    firestore_mock.SERVER_TIMESTAMP = object()
    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    api_core = sys.modules.get("google.api_core", MagicMock())
    api_core.exceptions = exc_mod
    sys.modules["google.api_core"] = api_core

    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    from tests.fakes import install_fake_base_query
    install_fake_base_query()

    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]
    return firestore_mock


PushSubscriptionStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]

_ENDPOINT = "https://web.push.apple.com/abc123"
_DOC_ID = hashlib.sha256(_ENDPOINT.encode()).hexdigest()[:32]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global PushSubscriptionStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    PushSubscriptionStore = importlib.import_module("memory.firestore_db").PushSubscriptionStore


def _store():
    s = PushSubscriptionStore.__new__(PushSubscriptionStore)
    s._client = MagicMock()
    s._col = MagicMock()
    return s


def _snap(doc_id: str, data: dict) -> MagicMock:
    snap = MagicMock()
    snap.id = doc_id
    snap.exists = True
    snap.to_dict.return_value = data
    return snap


# ------------------------------------------------------------------ #
# upsert                                                              #
# ------------------------------------------------------------------ #

def test_upsert_keys_doc_on_sha256_endpoint_and_merges():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.upsert({"endpoint": _ENDPOINT, "keys": {"p256dh": "p", "auth": "a"}}, user_agent="Safari/1.0")
    s._col.document.assert_called_once_with(_DOC_ID)
    args, kwargs = doc.set.call_args
    assert kwargs.get("merge") is True
    assert args[0]["endpoint"] == _ENDPOINT
    assert args[0]["keys"] == {"p256dh": "p", "auth": "a"}
    assert args[0]["user_agent"] == "Safari/1.0"
    assert args[0]["created_at"] is _FS.SERVER_TIMESTAMP
    assert args[0]["last_validated_at"] is _FS.SERVER_TIMESTAMP


def test_upsert_is_idempotent_same_doc_id():
    """Two upserts of the same endpoint hit the same doc id (multi-call dedup)."""
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.upsert({"endpoint": _ENDPOINT, "keys": {}})
    s.upsert({"endpoint": _ENDPOINT, "keys": {}})
    assert s._col.document.call_args_list[0].args == (_DOC_ID,)
    assert s._col.document.call_args_list[1].args == (_DOC_ID,)


def test_upsert_reraises_on_write_failure():
    s = _store()
    doc = MagicMock()
    doc.set.side_effect = RuntimeError("firestore down")
    s._col.document.return_value = doc
    with pytest.raises(RuntimeError):
        s.upsert({"endpoint": _ENDPOINT, "keys": {}})


# ------------------------------------------------------------------ #
# list_all                                                            #
# ------------------------------------------------------------------ #

def test_list_all_returns_jsonsafe_docs():
    s = _store()
    s._col = FakeCollection([
        _snap(_DOC_ID, {
            "endpoint": _ENDPOINT,
            "created_at": datetime(2026, 7, 1, 12, 0, 0),
        }),
    ])
    out = s.list_all()
    assert len(out) == 1
    assert out[0]["endpoint"] == _ENDPOINT
    assert isinstance(out[0]["created_at"], str)  # json-safe
    json.dumps(out)  # must not raise


def test_list_all_returns_empty_on_read_failure():
    s = _store()
    s._col = FailingCollection(RuntimeError("firestore down"))
    assert s.list_all() == []


# ------------------------------------------------------------------ #
# delete                                                              #
# ------------------------------------------------------------------ #

def test_delete_targets_sha256_doc():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.delete(_ENDPOINT)
    s._col.document.assert_called_once_with(_DOC_ID)
    doc.delete.assert_called_once()


def test_delete_reraises_on_failure():
    s = _store()
    doc = MagicMock()
    doc.delete.side_effect = RuntimeError("firestore down")
    s._col.document.return_value = doc
    with pytest.raises(RuntimeError):
        s.delete(_ENDPOINT)


# ------------------------------------------------------------------ #
# record_success / record_failure                                     #
# ------------------------------------------------------------------ #

def test_record_success_merge_writes_success_fields():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.record_success(_ENDPOINT)
    s._col.document.assert_called_once_with(_DOC_ID)
    args, kwargs = doc.set.call_args
    assert kwargs.get("merge") is True
    assert args[0]["failure_count"] == 0
    assert "last_success_at" in args[0]


def test_record_failure_merge_writes_error_and_increments_count():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.record_failure(_ENDPOINT, "410 Gone")
    s._col.document.assert_called_once_with(_DOC_ID)
    args, kwargs = doc.set.call_args
    assert kwargs.get("merge") is True
    assert args[0]["last_error"] == "410 Gone"
    assert "failure_count" in args[0]
