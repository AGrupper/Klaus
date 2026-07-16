"""Tests for memory/firestore_db.py::ProtocolStore — supplement & habit protocol.

Single-doc store at protocol/supplements:

    {"items": [{"name", "kind", "anchor", "notes", "active"}, ...],
     "updated_at": SERVER_TIMESTAMP}

- get(): {} when unset or on error (silent-omit contract, like
  get_day_aggregate); updated_at ISO-converted so json.dumps never chokes.
- replace(items): full-doc overwrite (JournalStore-style, no merge) so a
  shrunken list leaves no stale items behind.
- active_items(): convenience filter the gather sites share.

Mocks google.cloud.firestore at sys.modules level — mirrors tests/test_meal_store.py.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Same rationale as tests/test_meal_store.py — the module must re-import
    with OUR SERVER_TIMESTAMP sentinel bound.
    """
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
    firestore_mock.SERVER_TIMESTAMP = object()

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


ProtocolStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global ProtocolStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    ProtocolStore = importlib.import_module("memory.firestore_db").ProtocolStore


def _store():
    s = ProtocolStore.__new__(ProtocolStore)  # bypass __init__ → no real client
    s._client = MagicMock()
    s._doc_ref = MagicMock()
    return s


_ITEMS = [
    {"name": "Creatine", "kind": "supplement", "anchor": "post_lunch",
     "notes": "5g with food", "active": True},
    {"name": "Morning sunlight", "kind": "habit", "anchor": "morning",
     "notes": "10 min outside", "active": True},
]


def test_get_returns_empty_when_unset():
    """Silent-omit contract: no doc → {} (empty dict, truthiness-gated)."""
    s = _store()
    snap = MagicMock()
    snap.exists = False
    s._doc_ref.get.return_value = snap
    assert s.get() == {}


def test_get_returns_empty_on_error():
    s = _store()
    s._doc_ref.get.side_effect = RuntimeError("boom")
    assert s.get() == {}


def test_get_round_trip_is_json_safe():
    """get() ISO-converts updated_at (the SERVER_TIMESTAMP JSON pitfall) —
    the result must survive json.dumps end-to-end."""
    import json as _json

    class _FakeTs:  # stand-in for Firestore DatetimeWithNanoseconds
        def isoformat(self):
            return "2026-07-10T02:00:00+03:00"

    s = _store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"items": list(_ITEMS), "updated_at": _FakeTs()}
    s._doc_ref.get.return_value = snap
    doc = s.get()
    assert doc["items"] == _ITEMS
    assert doc["updated_at"] == "2026-07-10T02:00:00+03:00"
    _json.dumps(doc)


def test_replace_overwrites_full_doc_without_merge():
    """replace() is a full-doc overwrite (JournalStore-style) — a shrunken
    items list must leave no stale entries, so NO merge=True."""
    s = _store()
    s.replace(_ITEMS)
    args, kwargs = s._doc_ref.set.call_args
    written = args[0]
    assert written["items"] == _ITEMS
    assert written["updated_at"] is _FS.SERVER_TIMESTAMP
    assert kwargs.get("merge") is not True


def test_replace_raises_on_failure():
    s = _store()
    s._doc_ref.set.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        s.replace(_ITEMS)


def test_active_items_filters_inactive_and_defaults_to_active():
    """active_items(): active=False dropped; a missing active key counts as
    active; unset store → []."""
    s = _store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"items": [
        {"name": "Creatine", "active": True},
        {"name": "Old thing", "active": False},
        {"name": "Implicitly active"},
    ]}
    s._doc_ref.get.return_value = snap
    names = [i["name"] for i in s.active_items()]
    assert names == ["Creatine", "Implicitly active"]

    empty = _store()
    snap2 = MagicMock()
    snap2.exists = False
    empty._doc_ref.get.return_value = snap2
    assert empty.active_items() == []
