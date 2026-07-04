"""Tests for memory/firestore_db.py::HubSettingsStore (Phase 29 — PUSH-03).

Covers:
  - get() returns defaults (telegram_mirror_enabled=True, push_enabled_at=None)
    when the doc is absent
  - get() never raises — returns defaults on Firestore read failure
  - set(patch) merge-writes patch + updated_at SERVER_TIMESTAMP
  - set(patch) re-raises on Firestore write failure
  - set-then-get round trip reflects the patched value

Mocks google.cloud.firestore at sys.modules level — mirrors
tests/test_run_detail_store.py / tests/test_push_subscription_store.py.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


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


HubSettingsStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global HubSettingsStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    HubSettingsStore = importlib.import_module("memory.firestore_db").HubSettingsStore


def _store():
    s = HubSettingsStore.__new__(HubSettingsStore)
    s._client = MagicMock()
    s._doc_ref = MagicMock()
    return s


def _missing_snap() -> MagicMock:
    snap = MagicMock()
    snap.exists = False
    return snap


def _existing_snap(data: dict) -> MagicMock:
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = data
    return snap


# ------------------------------------------------------------------ #
# get() defaults                                                      #
# ------------------------------------------------------------------ #

def test_get_returns_defaults_when_doc_absent():
    s = _store()
    s._doc_ref.get.return_value = _missing_snap()
    out = s.get()
    assert out["telegram_mirror_enabled"] is True
    assert out["push_enabled_at"] is None


def test_get_returns_defaults_on_read_failure():
    s = _store()
    s._doc_ref.get.side_effect = RuntimeError("firestore down")
    out = s.get()
    assert out["telegram_mirror_enabled"] is True
    assert out["push_enabled_at"] is None


def test_get_merges_stored_over_defaults():
    s = _store()
    s._doc_ref.get.return_value = _existing_snap({"telegram_mirror_enabled": False})
    out = s.get()
    assert out["telegram_mirror_enabled"] is False
    assert out["push_enabled_at"] is None  # default still present


# ------------------------------------------------------------------ #
# set()                                                                #
# ------------------------------------------------------------------ #

def test_set_merge_writes_patch_and_updated_at():
    s = _store()
    s.set({"telegram_mirror_enabled": False})
    args, kwargs = s._doc_ref.set.call_args
    assert kwargs.get("merge") is True
    assert args[0]["telegram_mirror_enabled"] is False
    assert args[0]["updated_at"] is _FS.SERVER_TIMESTAMP


def test_set_reraises_on_write_failure():
    s = _store()
    s._doc_ref.set.side_effect = RuntimeError("firestore down")
    with pytest.raises(RuntimeError):
        s.set({"telegram_mirror_enabled": False})


def test_set_then_get_round_trip():
    """Simulates a real doc_ref: set() stores a dict, get() reads it back."""
    s = _store()
    stored: dict = {}

    def _fake_set(payload, merge=False):
        stored.update(payload)

    s._doc_ref.set.side_effect = _fake_set

    def _fake_get():
        snap = MagicMock()
        snap.exists = bool(stored)
        snap.to_dict.return_value = dict(stored)
        return snap

    s._doc_ref.get.side_effect = _fake_get

    s.set({"telegram_mirror_enabled": False})
    out = s.get()
    assert out["telegram_mirror_enabled"] is False
