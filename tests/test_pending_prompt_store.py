"""Tests for memory/firestore_db.py::PendingPromptStore — Phase 20 V3 session mgmt.

RED tests — written before implementation. All should FAIL until PendingPromptStore
is added to memory/firestore_db.py.

Tests cover:
  - set(session_key, payload) writes doc with merge=True + stamps session_key
  - set() never raises on Firestore error (soft degradation)
  - get(session_key) returns dict when expires_at is in the future
  - get(session_key) returns None when expires_at is in the past (soft TTL)
  - get(session_key) returns None when doc does not exist
  - get() returns None on Firestore exception (never raises)
  - delete(session_key) calls document(session_key).delete()
  - get_open_note_session(user_id) returns awaiting_notes session for that user
  - get_open_note_session returns None when no open session found
  - _pending_expiry() returns (created_at_iso, expires_at_iso) tuple 20h apart

Mocks google.cloud.firestore at sys.modules level — mirrors tests/test_meal_store.py.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from types import ModuleType
from unittest.mock import MagicMock


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Mirrors tests/test_meal_store.py — evict and re-import memory.firestore_db
    with our SERVER_TIMESTAMP sentinel bound.
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
    firestore_mock.SERVER_TIMESTAMP = object()  # distinguishable sentinel

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    # google.api_core.exceptions stub
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

    # Force re-import so `from google.cloud import firestore` rebinds to OUR mock.
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


_FS = _install_firestore_mock()

from memory.firestore_db import PendingPromptStore, _pending_expiry  # noqa: E402


def _store() -> PendingPromptStore:
    """Build a PendingPromptStore with a fully-mocked Firestore client."""
    s = PendingPromptStore.__new__(PendingPromptStore)
    s._client = MagicMock()
    s._col = MagicMock()
    return s


def _future_expires_at() -> str:
    """ISO UTC timestamp 20 hours from now."""
    return (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()


def _past_expires_at() -> str:
    """ISO UTC timestamp 1 hour in the past."""
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


# ------------------------------------------------------------------ #
# set                                                                 #
# ------------------------------------------------------------------ #

def test_set_writes_doc_at_session_key():
    """set() writes to document(session_key) with merge=True."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.set("2026-06-01_evt_abc", {"user_id": 123, "state": "awaiting_rpe"})

    s._col.document.assert_called_once_with("2026-06-01_evt_abc")
    assert doc_mock.set.called
    args, kwargs = doc_mock.set.call_args
    assert kwargs.get("merge") is True


def test_set_stamps_session_key_into_payload():
    """set() injects session_key into the stored payload."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.set("2026-06-01_evt_abc", {"user_id": 123, "state": "awaiting_rpe"})

    args, kwargs = doc_mock.set.call_args
    written = args[0]
    assert written["session_key"] == "2026-06-01_evt_abc"


def test_set_never_raises_on_firestore_error():
    """set() swallows Firestore exceptions — degraded to no follow-up, not a crash."""
    s = _store()
    s._col.document.return_value.set.side_effect = RuntimeError("firestore down")

    # Must not raise
    s.set("key", {"state": "awaiting_rpe"})


# ------------------------------------------------------------------ #
# get — expiry, missing doc, exception                               #
# ------------------------------------------------------------------ #

def test_get_returns_dict_for_valid_non_expired_session():
    """get() returns the dict when expires_at is in the future."""
    s = _store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "session_key": "key1",
        "user_id": 123,
        "state": "awaiting_rpe",
        "expires_at": _future_expires_at(),
    }
    s._col.document.return_value.get.return_value = snap

    result = s.get("key1")

    assert result is not None
    assert result["session_key"] == "key1"
    assert result["state"] == "awaiting_rpe"


def test_get_returns_none_for_expired_session():
    """get() returns None when expires_at is in the past (soft TTL guard)."""
    s = _store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "session_key": "key1",
        "user_id": 123,
        "state": "awaiting_rpe",
        "expires_at": _past_expires_at(),
    }
    s._col.document.return_value.get.return_value = snap

    result = s.get("key1")

    assert result is None


def test_get_returns_none_when_doc_does_not_exist():
    """get() returns None when the document does not exist in Firestore."""
    s = _store()
    snap = MagicMock()
    snap.exists = False
    s._col.document.return_value.get.return_value = snap

    result = s.get("nonexistent_key")

    assert result is None


def test_get_returns_none_on_firestore_exception():
    """get() returns None on Firestore error — never raises."""
    s = _store()
    s._col.document.return_value.get.side_effect = RuntimeError("down")

    result = s.get("key1")

    assert result is None


# ------------------------------------------------------------------ #
# delete                                                              #
# ------------------------------------------------------------------ #

def test_delete_calls_document_delete():
    """delete(session_key) calls document(session_key).delete()."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.delete("2026-06-01_evt_abc")

    s._col.document.assert_called_once_with("2026-06-01_evt_abc")
    doc_mock.delete.assert_called_once()


# ------------------------------------------------------------------ #
# get_open_note_session                                               #
# ------------------------------------------------------------------ #

def test_get_open_note_session_returns_matching_session():
    """get_open_note_session returns an awaiting_notes session for the given user_id."""
    s = _store()
    user_id = 42
    expires_str = _future_expires_at()

    # One matching snap, one non-matching
    matching_snap = MagicMock()
    matching_snap.to_dict.return_value = {
        "session_key": "key_match",
        "user_id": user_id,
        "state": "awaiting_notes",
        "expires_at": expires_str,
    }
    other_snap = MagicMock()
    other_snap.to_dict.return_value = {
        "session_key": "key_other",
        "user_id": 999,
        "state": "awaiting_notes",
        "expires_at": expires_str,
    }
    s._col.stream.return_value = [matching_snap, other_snap]

    result = s.get_open_note_session(user_id)

    assert result is not None
    assert result["session_key"] == "key_match"


def test_get_open_note_session_returns_none_when_no_open_session():
    """get_open_note_session returns None when no awaiting_notes session for user."""
    s = _store()
    # No docs in collection
    s._col.stream.return_value = []

    result = s.get_open_note_session(42)

    assert result is None


def test_get_open_note_session_skips_expired_sessions():
    """get_open_note_session ignores sessions with expired expires_at."""
    s = _store()
    user_id = 42
    expired_snap = MagicMock()
    expired_snap.to_dict.return_value = {
        "session_key": "key_expired",
        "user_id": user_id,
        "state": "awaiting_notes",
        "expires_at": _past_expires_at(),
    }
    s._col.stream.return_value = [expired_snap]

    result = s.get_open_note_session(user_id)

    assert result is None


def test_get_open_note_session_returns_none_on_exception():
    """get_open_note_session returns None on Firestore error — never raises."""
    s = _store()
    s._col.stream.side_effect = RuntimeError("down")

    result = s.get_open_note_session(42)

    assert result is None


# ------------------------------------------------------------------ #
# State value coverage                                                #
# ------------------------------------------------------------------ #

def test_state_values_present_in_module():
    """State string literals are documented in the module for reference."""
    # The four valid state values used by PendingPromptStore are documented
    # as constants or comments in the module — verified by checking the class docstring
    # or a module-level list. This test just verifies the class exists with the right name.
    assert PendingPromptStore._COLLECTION == "pending_prompts"


# ------------------------------------------------------------------ #
# _pending_expiry helper                                              #
# ------------------------------------------------------------------ #

def test_pending_expiry_returns_tuple_of_two_isos():
    """_pending_expiry() returns (created_at_iso, expires_at_iso)."""
    result = _pending_expiry()
    assert isinstance(result, tuple)
    assert len(result) == 2
    created_str, expires_str = result
    # Both must be parseable ISO strings
    created = datetime.fromisoformat(created_str)
    expires = datetime.fromisoformat(expires_str)
    assert expires > created


def test_pending_expiry_default_is_20h():
    """_pending_expiry() default TTL is 20 hours."""
    created_str, expires_str = _pending_expiry()
    created = datetime.fromisoformat(created_str)
    expires = datetime.fromisoformat(expires_str)
    delta = expires - created
    # Allow 1s clock drift
    assert abs(delta.total_seconds() - 20 * 3600) < 2


def test_pending_expiry_custom_hours():
    """_pending_expiry(hours=48) returns 48h gap."""
    created_str, expires_str = _pending_expiry(hours=48)
    created = datetime.fromisoformat(created_str)
    expires = datetime.fromisoformat(expires_str)
    delta = expires - created
    assert abs(delta.total_seconds() - 48 * 3600) < 2
