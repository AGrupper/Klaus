"""RED-phase tests for UserProfileStore v4.0 scaffold (Phase 21 Plan 01).

These tests assert the NEW v4.0 _SCAFFOLD shape. They MUST FAIL against the
current v1 scaffold and pass after the _SCAFFOLD expansion in Task 1.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — same approach as test_user_profile_store.py
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> MagicMock:
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


UserProfileStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]

V4_REQUIRED_KEYS = {
    "dated_goals",
    "weekly_split",
    "nutrition_targets",
    "supplement_schedule",
    "fueling_timeline",
    "plan_start_date",
}


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global UserProfileStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    UserProfileStore = importlib.import_module("memory.firestore_db").UserProfileStore


# ---------------------------------------------------------------------------
# Task 1 RED tests — assert v4.0 _SCAFFOLD shape
# ---------------------------------------------------------------------------

def test_scaffold_schema_version_is_2():
    """v4.0 scaffold must have schema_version == 2."""
    assert UserProfileStore._SCAFFOLD["schema_version"] == 2


def test_scaffold_contains_all_six_v4_keys():
    """v4.0 scaffold must contain all six structured keys."""
    scaffold = UserProfileStore._SCAFFOLD
    missing = V4_REQUIRED_KEYS - scaffold.keys()
    assert not missing, f"Missing v4.0 keys in _SCAFFOLD: {missing}"


def test_scaffold_dated_goals_is_empty_list():
    """dated_goals default must be an empty list."""
    assert UserProfileStore._SCAFFOLD["dated_goals"] == []


def test_scaffold_weekly_split_is_empty_dict():
    """weekly_split default must be empty dict (template shape, not attendance flags)."""
    ws = UserProfileStore._SCAFFOLD["weekly_split"]
    assert isinstance(ws, dict), "weekly_split must be a dict"
    assert ws == {}, "weekly_split default must be empty (template shape)"


def test_scaffold_weekly_split_contains_no_attendance_booleans():
    """weekly_split must never contain attendance/done/completed boolean keys.

    This guards the PLAN-02 rigidity-drift invariant — per-session attendance
    booleans must be structurally impossible in the scaffold default.
    """
    ws = UserProfileStore._SCAFFOLD.get("weekly_split", {})
    # Flatten all keys across all day values
    attendance_keys = {"attendance", "done", "completed", "attended", "checked"}
    for day, day_val in ws.items():
        if isinstance(day_val, dict):
            for slot_val in day_val.values():
                if isinstance(slot_val, dict):
                    forbidden = attendance_keys & slot_val.keys()
                    assert not forbidden, (
                        f"weekly_split[{day}] contains forbidden attendance key(s): {forbidden}"
                    )


def test_scaffold_nutrition_targets_is_empty_dict():
    """nutrition_targets default must be an empty dict."""
    assert UserProfileStore._SCAFFOLD["nutrition_targets"] == {}


def test_scaffold_supplement_schedule_is_empty_list():
    """supplement_schedule default must be an empty list."""
    assert UserProfileStore._SCAFFOLD["supplement_schedule"] == []


def test_scaffold_fueling_timeline_is_empty_list():
    """fueling_timeline default must be an empty list."""
    assert UserProfileStore._SCAFFOLD["fueling_timeline"] == []


def test_scaffold_plan_start_date_is_string():
    """plan_start_date default must be a string (empty str is acceptable)."""
    val = UserProfileStore._SCAFFOLD["plan_start_date"]
    assert isinstance(val, str), "plan_start_date must be a str"


def test_scaffold_retains_athletic_goals():
    """athletic_goals must be retained — read by core/weekly_training_review.py:188."""
    assert "athletic_goals" in UserProfileStore._SCAFFOLD, (
        "athletic_goals must stay in _SCAFFOLD — removing it breaks the Sunday cron "
        "(weekly_training_review.py line 188 does data['athletic_goals'])"
    )
