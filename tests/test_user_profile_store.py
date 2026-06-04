"""Tests for memory/firestore_db.py::UserProfileStore (Phase 19 Plan 02).

Covers PROFILE-01/02/03:
  - load()                returns {} on any error; doc content on success
  - update(patch)         merges with SERVER_TIMESTAMP; re-raises on failure
  - bootstrap_if_empty()  seeds empty scaffold when absent; no-op when present;
                          never raises on Firestore failure (Pitfall 7).

Mock strategy
-------------
Reuses the proven sys.modules google.cloud mock dance from
tests/test_firestore_db.py — installed BEFORE memory.firestore_db is imported.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> MagicMock:
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

    # google.oauth2 — used inside _make_firestore_client when FIRESTORE_CREDENTIALS set
    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    # dotenv
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


# Bound per-test by the autouse fixture below. We deliberately do NOT install
# the mock or import memory.firestore_db at module/collection time — that leaks
# fake google.* modules into sys.modules for the whole session and breaks
# sibling test files.
UserProfileStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global UserProfileStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    UserProfileStore = importlib.import_module("memory.firestore_db").UserProfileStore


# ---------------------------------------------------------------------------
# Helper — build a UserProfileStore with a controllable doc_ref MagicMock
# ---------------------------------------------------------------------------

def _build_store(
    *,
    snap_exists: bool = False,
    snap_data: dict | None = None,
    get_raises: bool = False,
    set_raises: bool = False,
) -> tuple[UserProfileStore, MagicMock]:
    """Return (store, doc_ref_mock) — store's _doc_ref replaced for isolation."""
    # _make_firestore_client is mocked via sys.modules; constructor will use it.
    store = UserProfileStore(project_id="test-project", database="(default)")

    snap = MagicMock()
    snap.exists = snap_exists
    snap.to_dict.return_value = snap_data or {}

    doc_ref = MagicMock()
    if get_raises:
        doc_ref.get.side_effect = RuntimeError("firestore down")
    else:
        doc_ref.get.return_value = snap
    if set_raises:
        doc_ref.set.side_effect = RuntimeError("write failed")

    store._doc_ref = doc_ref
    return store, doc_ref


# ---------------------------------------------------------------------------
# PROFILE-01 — load()
# ---------------------------------------------------------------------------

def test_load_returns_empty_on_error():
    """PROFILE-01: load() must NEVER raise; returns {} on any exception."""
    store, _ = _build_store(get_raises=True)
    assert store.load() == {}


def test_load_returns_empty_when_doc_absent():
    """PROFILE-01: missing doc → {}."""
    store, _ = _build_store(snap_exists=False)
    assert store.load() == {}


def test_load_returns_doc_when_present():
    """PROFILE-01: present doc → its dict."""
    scaffold = {"athletic_goals": ["5k"], "schema_version": 1}
    store, _ = _build_store(snap_exists=True, snap_data=scaffold)
    assert store.load() == scaffold


# ---------------------------------------------------------------------------
# PROFILE-02 — update()
# ---------------------------------------------------------------------------

def test_update_merges_and_stamps():
    """PROFILE-02: merge=True and updated_at = SERVER_TIMESTAMP sentinel."""
    store, doc_ref = _build_store()
    store.update({"athletic_goals": ["5k"]})
    args, kwargs = doc_ref.set.call_args
    written = args[0]
    assert written["athletic_goals"] == ["5k"]
    assert written["updated_at"] is _FS.SERVER_TIMESTAMP  # exact sentinel
    assert kwargs.get("merge") is True


def test_update_reraises_on_error():
    """PROFILE-02: write failure must re-raise after logging."""
    store, _ = _build_store(set_raises=True)
    with pytest.raises(RuntimeError):
        store.update({"x": 1})


# ---------------------------------------------------------------------------
# PROFILE-03 — bootstrap_if_empty()
# ---------------------------------------------------------------------------

def test_bootstrap_creates_when_missing():
    """PROFILE-03: missing doc → write empty scaffold once.

    Phase 21 Plan 01: schema_version bumped to 2; v4.0 structured keys present.
    """
    store, doc_ref = _build_store(snap_exists=False)
    store.bootstrap_if_empty()
    args, _ = doc_ref.set.call_args
    written = args[0]
    # v3.0 legacy fields retained for backward compat
    assert written["athletic_goals"] == []
    assert written["training_constraints"] == []
    assert written["recovery_preferences"] == {}
    # v4.0 schema version
    assert written["schema_version"] == 2
    # Firestore sentinel stamps
    assert written["bootstrapped_at"] is _FS.SERVER_TIMESTAMP
    assert written["updated_at"] is _FS.SERVER_TIMESTAMP


def test_bootstrap_seeds_v4_structured_keys():
    """PROFILE-03 v4.0: bootstrapped doc must contain all six v4.0 structured keys."""
    store, doc_ref = _build_store(snap_exists=False)
    store.bootstrap_if_empty()
    args, _ = doc_ref.set.call_args
    written = args[0]

    v4_keys = {
        "dated_goals",
        "weekly_split",
        "nutrition_targets",
        "supplement_schedule",
        "fueling_timeline",
        "plan_start_date",
    }
    missing = v4_keys - written.keys()
    assert not missing, f"Bootstrapped doc missing v4.0 keys: {missing}"


def test_bootstrap_seeds_weekly_split_as_empty_dict():
    """PROFILE-03 v4.0: weekly_split must be an empty dict — template, not attendance flags.

    Guards the PLAN-02 rigidity-drift invariant: per-session attendance/done/completed
    booleans must be structurally absent from the scaffold default.
    """
    store, doc_ref = _build_store(snap_exists=False)
    store.bootstrap_if_empty()
    args, _ = doc_ref.set.call_args
    written = args[0]

    ws = written.get("weekly_split")
    assert isinstance(ws, dict), "weekly_split must be a dict"
    assert ws == {}, "weekly_split scaffold default must be an empty dict (template shape)"


def test_bootstrap_skips_when_present():
    """PROFILE-03: present doc → no write."""
    store, doc_ref = _build_store(snap_exists=True)
    store.bootstrap_if_empty()
    doc_ref.set.assert_not_called()


def test_bootstrap_never_raises_on_error():
    """PROFILE-03 / Pitfall 7: bootstrap MUST NOT raise — startup must not die."""
    store, _ = _build_store(get_raises=True)
    # If this line raises, the test fails.
    store.bootstrap_if_empty()
