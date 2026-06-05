"""Tests for scripts/seed_training_blocks.py — Phase 23 BLOCK-01.

RED tests — written before implementation. All should FAIL until
scripts/seed_training_blocks.py is created.

Tests cover:
  - build_blocks_list() returns exactly 4 blocks with locked labels/dates
  - Block 4 has benchmark_due=False (race, never benchmarked)
  - The 4 blocks' date ranges are contiguous and non-overlapping from 2026-06-21 to 2026-10-10
  - seed_if_absent with existing blocks and force=False returns False (no overwrite)

Imports the seed script by inserting the scripts/ directory onto sys.path,
then importing build_blocks_list and seed_if_absent directly.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Same pattern as test_training_log_store.py.
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
    sys.modules["dotenv"] = dotenv_mod

    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


# Bound per-test by the autouse fixture below.
build_blocks_list = None  # type: ignore[assignment]
seed_if_absent = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global build_blocks_list, seed_if_absent, _FS
    import importlib
    _FS = _install_firestore_mock()

    # Also evict the seed script module if previously imported
    if "seed_training_blocks" in sys.modules:
        del sys.modules["seed_training_blocks"]
    if "scripts.seed_training_blocks" in sys.modules:
        del sys.modules["scripts.seed_training_blocks"]

    # Add scripts directory to path for import
    scripts_dir = str(Path(__file__).parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    mod = importlib.import_module("seed_training_blocks")
    build_blocks_list = mod.build_blocks_list
    seed_if_absent = mod.seed_if_absent


# Locked labels and dates from 23-01-PLAN.md closed_sets block
_EXPECTED_LABELS = [
    "Aerobic Base",
    "Capacity Build",
    "Deep Waters → Peak Engine",
    "Race Specificity → Taper → Race Week",
]
_EXPECTED_STARTS = ["2026-06-21", "2026-07-19", "2026-08-16", "2026-09-13"]
_EXPECTED_ENDS = ["2026-07-18", "2026-08-15", "2026-09-12", "2026-10-10"]
_EXPECTED_FACETS = ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"]


# ------------------------------------------------------------------ #
# build_blocks_list                                                   #
# ------------------------------------------------------------------ #

def test_build_blocks_list_returns_four():
    """build_blocks_list() returns exactly 4 block dicts."""
    blocks = build_blocks_list()
    assert len(blocks) == 4


def test_build_blocks_list_labels_match():
    """build_blocks_list() labels match the locked blueprint labels exactly."""
    blocks = build_blocks_list()
    labels = [b["label"] for b in blocks]
    assert labels == _EXPECTED_LABELS


def test_build_blocks_list_dates_match():
    """build_blocks_list() start_date and end_date match the locked blueprint dates."""
    blocks = build_blocks_list()
    for i, block in enumerate(blocks):
        assert block["start_date"] == _EXPECTED_STARTS[i], (
            f"Block {i+1} start_date: expected {_EXPECTED_STARTS[i]} got {block['start_date']}"
        )
        assert block["end_date"] == _EXPECTED_ENDS[i], (
            f"Block {i+1} end_date: expected {_EXPECTED_ENDS[i]} got {block['end_date']}"
        )


def test_build_blocks_list_facets():
    """All 4 blocks have the 5-facet focus_facets list."""
    blocks = build_blocks_list()
    for block in blocks:
        assert block["focus_facets"] == _EXPECTED_FACETS, (
            f"Block {block['label']} has wrong facets: {block['focus_facets']}"
        )


def test_block_4_benchmark_due_false():
    """Block 4 (Race week) has benchmark_due=False — never gets a benchmark (D-02)."""
    blocks = build_blocks_list()
    block4 = blocks[3]
    assert block4["benchmark_due"] is False, (
        f"Block 4 benchmark_due should be False, got {block4['benchmark_due']}"
    )
    # Verify it's the race block
    assert "Race" in block4["label"]


def test_blocks_all_benchmark_due_false():
    """All 4 auto-seeded blocks have benchmark_due=False at seed time."""
    blocks = build_blocks_list()
    for block in blocks:
        assert block["benchmark_due"] is False, (
            f"Block '{block['label']}' should have benchmark_due=False at seed time"
        )


def test_blocks_cover_contiguous_date_range():
    """The 4 blocks' date ranges are contiguous and non-overlapping from 2026-06-21 to 2026-10-10.

    Contiguous means each block's start_date is exactly the day after the previous block's end_date.
    This is required so that date-range get_current always resolves exactly one block in-cycle.
    """
    blocks = build_blocks_list()

    # Overall cycle starts at 2026-06-21 and ends at 2026-10-10
    assert blocks[0]["start_date"] == "2026-06-21"
    assert blocks[-1]["end_date"] == "2026-10-10"

    for i in range(len(blocks) - 1):
        end_of_current = date.fromisoformat(blocks[i]["end_date"])
        start_of_next = date.fromisoformat(blocks[i + 1]["start_date"])
        gap_days = (start_of_next - end_of_current).days
        assert gap_days == 1, (
            f"Gap between block {i+1} end ({blocks[i]['end_date']}) "
            f"and block {i+2} start ({blocks[i+1]['start_date']}) "
            f"is {gap_days} days — expected exactly 1 (contiguous, no overlap)"
        )


def test_blocks_block1_status_active():
    """Block 1 seed status is 'active' (its date range includes the anchor day)."""
    blocks = build_blocks_list()
    assert blocks[0]["status"] == "active"


def test_blocks_remaining_status_pending():
    """Blocks 2-4 seed status is 'pending' (bookkeeping; get_current uses date range)."""
    blocks = build_blocks_list()
    for block in blocks[1:]:
        assert block["status"] == "pending", (
            f"Block '{block['label']}' expected status 'pending', got {block['status']!r}"
        )


# ------------------------------------------------------------------ #
# seed_if_absent — idempotency gate                                   #
# ------------------------------------------------------------------ #

def test_seed_idempotent():
    """seed_if_absent with existing blocks and force=False returns False (no overwrite)."""
    # BlockStore is imported inside seed_if_absent, so patch it at the source module.
    with patch("memory.firestore_db.BlockStore") as MockBlockStore, \
         patch("memory.firestore_db.UserProfileStore"):
        # Simulate BlockStore.get_all() returning existing blocks (non-empty)
        instance = MockBlockStore.return_value
        instance.get_all.return_value = [{"block_id": "existing"}]

        result = seed_if_absent(
            project_id="test-project",
            database="(default)",
            force=False,
        )

    assert result is False, (
        "seed_if_absent should return False when blocks already exist and force=False"
    )


def test_seed_force_overwrites():
    """seed_if_absent with force=True upserts blocks even when they already exist."""
    # BlockStore is imported inside seed_if_absent, so patch it at the source module.
    with patch("memory.firestore_db.BlockStore") as MockBlockStore, \
         patch("memory.firestore_db.UserProfileStore") as MockUserProfileStore:
        instance = MockBlockStore.return_value
        instance.get_all.return_value = [{"block_id": "existing"}]  # non-empty
        profile_instance = MockUserProfileStore.return_value  # noqa: F841

        result = seed_if_absent(
            project_id="test-project",
            database="(default)",
            force=True,
        )

    assert result is True
    # Should have called upsert 4 times (one per block)
    assert instance.upsert.call_count == 4
