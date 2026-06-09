"""Tests for core/tools.py::_handle_get_run_detail (brain-direct tool handler).

Covers single-run lookup, recent-window 'summary' projection (drops per-lap
arrays), and fail-open error envelope. The RunDetailStore is patched at the
firestore module boundary the handler imports from.
"""
from __future__ import annotations

import json

import pytest

import core.tools as tools
import memory.firestore_db as fdb


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")


def _patch_store(monkeypatch, fake_or_factory):
    # Patch the exact module object the handler's `from memory.firestore_db
    # import RunDetailStore` resolves, so cross-file sys.modules swaps in other
    # tests can't make us hit real Firestore.
    monkeypatch.setattr(fdb, "RunDetailStore", fake_or_factory)


def test_get_run_detail_single_run(monkeypatch):
    fake = type("S", (), {"get_run": staticmethod(lambda aid: {"activity_id": aid, "date": "2026-06-08"})})()
    _patch_store(monkeypatch, lambda **k: fake)
    out = json.loads(tools._handle_get_run_detail(activity_id="5"))
    assert out["run"]["activity_id"] == "5"


def test_get_run_detail_recent_summary_drops_splits(monkeypatch):
    runs = [{
        "date": "2026-06-08", "type": "running", "distance_m": 5000,
        "avg_pace_sec_per_km": 300.0, "has_dynamics": True,
        "derived": {"split_shape": "even"},
        "splits": [{"index": 1, "pace_sec_per_km": 300.0}],   # must be dropped
        "summary": {"hr_bpm": {"avg": 160}},                  # must be dropped
    }]
    fake = type("S", (), {"get_recent": staticmethod(lambda days: runs)})()
    _patch_store(monkeypatch, lambda **k: fake)
    out = json.loads(tools._handle_get_run_detail(days=14, detail="summary"))
    row = out["runs"][0]
    assert "splits" not in row and "summary" not in row
    assert row["derived"]["split_shape"] == "even"
    assert row["avg_pace_sec_per_km"] == 300.0


def test_get_run_detail_full_keeps_splits(monkeypatch):
    runs = [{"date": "2026-06-08", "splits": [{"index": 1}], "summary": {}}]
    fake = type("S", (), {"get_recent": staticmethod(lambda days: runs)})()
    _patch_store(monkeypatch, lambda **k: fake)
    out = json.loads(tools._handle_get_run_detail(days=7, detail="full"))
    assert out["runs"][0]["splits"] == [{"index": 1}]


def test_get_run_detail_error_returns_dict(monkeypatch):
    def boom(**k):
        raise RuntimeError("store down")
    _patch_store(monkeypatch, boom)
    out = json.loads(tools._handle_get_run_detail())
    assert "error" in out
