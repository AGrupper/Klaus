"""Tests for memory/firestore_db.py::CoachingTopicStore — Phase 24 COACH-05.

RED tests — written before implementation. All should FAIL until CoachingTopicStore
is added to memory/firestore_db.py.

Tests cover:
  - has_topic returns False when the per-day doc does not exist
  - after add_topic(date, "protein-miss"), has_topic(date, "protein-miss") returns True
  - topics_today(date) contains "protein-miss" after add_topic
  - add_topic stores topics as a plain list[str] via ArrayUnion (NOT list[dict])
  - adding the same key twice does NOT duplicate it (ArrayUnion semantics)
  - has_topic and topics_today return False / [] on Firestore read error (fail-open)
  - add_topic re-raises on write error (caller-decides discipline)

Mocks google.cloud.firestore at sys.modules level so tests run without the lib
installed — mirrors tests/test_training_log_store.py pattern.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, call

import pytest


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Mirrors tests/test_training_log_store.py — evict and re-import
    memory.firestore_db with our SERVER_TIMESTAMP sentinel bound.
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
    # ArrayUnion returns a distinguishable object to assert on its argument
    firestore_mock.ArrayUnion = MagicMock(side_effect=lambda items: ("ArrayUnion", items))

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


# Bound per-test by the autouse fixture below.
CoachingTopicStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global CoachingTopicStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    CoachingTopicStore = importlib.import_module("memory.firestore_db").CoachingTopicStore


def _store() -> "CoachingTopicStore":
    """Build a CoachingTopicStore with a fully-mocked Firestore client."""
    s = CoachingTopicStore.__new__(CoachingTopicStore)  # bypass __init__
    s._client = MagicMock()
    s._col = MagicMock()
    return s


# ------------------------------------------------------------------ #
# _COLLECTION constant                                                #
# ------------------------------------------------------------------ #

def test_collection_name():
    """CoachingTopicStore._COLLECTION must be 'coaching_topics' (lowercase)."""
    assert CoachingTopicStore._COLLECTION == "coaching_topics"


# ------------------------------------------------------------------ #
# has_topic — no-doc case                                             #
# ------------------------------------------------------------------ #

def test_has_topic_returns_false_when_doc_does_not_exist():
    """has_topic returns False when the per-day doc does not exist."""
    s = _store()
    snap = MagicMock()
    snap.exists = False
    s._col.document.return_value.get.return_value = snap

    result = s.has_topic("2026-06-06", "protein-miss")

    assert result is False
    s._col.document.assert_called_once_with("2026-06-06")


# ------------------------------------------------------------------ #
# add_topic + has_topic + topics_today round-trip                     #
# ------------------------------------------------------------------ #

def test_has_topic_returns_true_after_add_topic():
    """After add_topic(date, key), has_topic(date, key) returns True."""
    s = _store()

    # Simulate the document now containing the topic
    snap_after = MagicMock()
    snap_after.exists = True
    snap_after.to_dict.return_value = {"date": "2026-06-06", "topics": ["protein-miss"]}
    s._col.document.return_value.get.return_value = snap_after

    # add_topic call (mocked write — no real Firestore)
    s.add_topic("2026-06-06", "protein-miss")

    result = s.has_topic("2026-06-06", "protein-miss")
    assert result is True


def test_topics_today_contains_added_topic():
    """topics_today returns a list containing the added topic key."""
    s = _store()

    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"date": "2026-06-06", "topics": ["protein-miss"]}
    s._col.document.return_value.get.return_value = snap

    result = s.topics_today("2026-06-06")

    assert "protein-miss" in result
    assert isinstance(result, list)


# ------------------------------------------------------------------ #
# ArrayUnion — plain string, NOT dict                                 #
# ------------------------------------------------------------------ #

def test_add_topic_uses_array_union_with_plain_string():
    """add_topic uses firestore.ArrayUnion([topic_key]) where topic_key is a string.

    Pitfall 3: ArrayUnion argument must be a list containing a plain string,
    NOT a list containing a dict (dicts with SERVER_TIMESTAMP break deep-equality
    dedup inside ArrayUnion).
    """
    s = _store()

    s.add_topic("2026-06-06", "protein-miss")

    args, kwargs = s._col.document.return_value.set.call_args
    payload = args[0]

    # The "topics" value must be the result of firestore.ArrayUnion([str])
    topics_val = payload["topics"]
    # Our mock returns ("ArrayUnion", items) so we can inspect the items
    assert isinstance(topics_val, tuple) and topics_val[0] == "ArrayUnion", (
        "topics value must be the result of firestore.ArrayUnion(...)"
    )
    items = topics_val[1]
    assert len(items) == 1, "ArrayUnion must receive exactly one item"
    assert isinstance(items[0], str), "ArrayUnion item must be a plain string, not a dict"
    assert items[0] == "protein-miss"


def test_add_topic_does_not_embed_server_timestamp_in_array():
    """Pitfall 3: SERVER_TIMESTAMP must NOT appear inside the topics ArrayUnion."""
    s = _store()

    s.add_topic("2026-06-06", "protein-miss")

    args, kwargs = s._col.document.return_value.set.call_args
    payload = args[0]

    topics_val = payload["topics"]
    # Unpack our mock's ("ArrayUnion", items) tuple
    items = topics_val[1]
    for item in items:
        assert item is not _FS.SERVER_TIMESTAMP, (
            "SERVER_TIMESTAMP must not appear inside the topics ArrayUnion element"
        )
        assert not isinstance(item, dict), (
            "ArrayUnion items must be plain strings, not dicts"
        )


def test_add_topic_uses_merge_true():
    """add_topic calls .set(..., merge=True) for atomic upsert."""
    s = _store()

    s.add_topic("2026-06-06", "protein-miss")

    args, kwargs = s._col.document.return_value.set.call_args
    assert kwargs.get("merge") is True


def test_add_topic_doc_level_updated_at_is_server_timestamp():
    """The doc-level updated_at in add_topic payload must be SERVER_TIMESTAMP."""
    s = _store()

    s.add_topic("2026-06-06", "protein-miss")

    args, kwargs = s._col.document.return_value.set.call_args
    payload = args[0]
    assert payload["updated_at"] is _FS.SERVER_TIMESTAMP


# ------------------------------------------------------------------ #
# Fail-open reads — never raise                                       #
# ------------------------------------------------------------------ #

def test_has_topic_returns_false_on_firestore_error():
    """has_topic returns False on Firestore read error — never raises."""
    s = _store()
    s._col.document.return_value.get.side_effect = RuntimeError("Firestore down")

    result = s.has_topic("2026-06-06", "protein-miss")

    assert result is False  # fail-open


def test_topics_today_returns_empty_list_on_firestore_error():
    """topics_today returns [] on Firestore read error — never raises."""
    s = _store()
    s._col.document.return_value.get.side_effect = RuntimeError("Firestore down")

    result = s.topics_today("2026-06-06")

    assert result == []  # fail-open


def test_topics_today_returns_empty_list_when_doc_does_not_exist():
    """topics_today returns [] when the per-day doc does not exist."""
    s = _store()
    snap = MagicMock()
    snap.exists = False
    s._col.document.return_value.get.return_value = snap

    result = s.topics_today("2026-06-06")

    assert result == []


# ------------------------------------------------------------------ #
# add_topic re-raises on write error                                  #
# ------------------------------------------------------------------ #

def test_add_topic_reraises_on_write_error():
    """add_topic re-raises on write failure (caller-decides discipline)."""
    s = _store()
    s._col.document.return_value.set.side_effect = RuntimeError("Firestore write failed")

    with pytest.raises(RuntimeError, match="Firestore write failed"):
        s.add_topic("2026-06-06", "protein-miss")
