"""Unit tests for MemoryStore.recall recency-weighted re-ranking (no live API).

Pure cosine ranking surfaced a 2-year-old fact over yesterday's when the
wording matched. recall now over-fetches and blends in a bounded exponential
age decay (memory/pinecone_db.py::_blend_recency). These tests pin:
  - fresher memories outrank slightly-more-similar stale ones
  - vectors without a ``ts`` (pre-Phase-17) are never penalized
  - the user_id / kind filters and over-fetch still reach Pinecone
  - at most k results come back, sorted by blended score
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from memory.pinecone_db import (
    _RECENCY_WEIGHT,
    MemoryStore,
    _blend_recency,
)


def _iso_days_ago(days: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()


def _match(score: float, content: str, ts: str | None) -> MagicMock:
    m = MagicMock()
    m.score = score
    m.metadata = {"kind": "fact", "content": content, "ts": ts}
    return m


def _store_with_matches(matches: list) -> tuple[MemoryStore, MagicMock]:
    store = MemoryStore(api_key="fake", index_name="fake-index")
    store._embed = MagicMock(return_value=[0.1] * 768)
    index = MagicMock(name="pinecone-index")
    index.query.return_value = MagicMock(matches=matches)
    store._index = index
    return store, index


class TestBlendRecency:
    def test_fresh_memory_keeps_full_score(self):
        assert _blend_recency(0.9, _iso_days_ago(0)) == pytest.approx(0.9, abs=1e-4)

    def test_old_memory_loses_at_most_recency_weight(self):
        blended = _blend_recency(0.9, _iso_days_ago(365 * 10))
        floor = 0.9 * (1.0 - _RECENCY_WEIGHT)
        assert blended >= floor - 1e-9
        assert blended < 0.9

    def test_missing_ts_is_not_penalized(self):
        assert _blend_recency(0.9, None) == 0.9

    def test_unparseable_ts_is_not_penalized(self):
        assert _blend_recency(0.9, "not-a-date") == 0.9


class TestRecallReRanking:
    def test_fresh_memory_outranks_slightly_more_similar_stale_one(self):
        """0.88 cosine from yesterday beats 0.90 cosine from a year ago."""
        store, _ = _store_with_matches([
            _match(0.90, "old plan", _iso_days_ago(365)),
            _match(0.88, "current plan", _iso_days_ago(1)),
        ])
        out = store.recall(user_id=1, query="training plan", k=2)
        assert [r["content"] for r in out] == ["current plan", "old plan"]

    def test_no_ts_vector_keeps_raw_cosine_rank(self):
        """A pre-Phase-17 vector with no ts is not penalized below fresh ones."""
        store, _ = _store_with_matches([
            _match(0.90, "curated fact", None),
            _match(0.85, "fresh fact", _iso_days_ago(0)),
        ])
        out = store.recall(user_id=1, query="anything", k=2)
        assert out[0]["content"] == "curated fact"

    def test_returns_at_most_k(self):
        store, _ = _store_with_matches([
            _match(0.9 - i * 0.01, f"m{i}", _iso_days_ago(i)) for i in range(15)
        ])
        out = store.recall(user_id=1, query="q", k=3)
        assert len(out) == 3
        assert out[0]["score"] >= out[1]["score"] >= out[2]["score"]

    def test_overfetches_and_passes_filters(self):
        store, index = _store_with_matches([])
        store.recall(user_id=42, query="q", k=5, kinds=["fact"])

        kwargs = index.query.call_args.kwargs
        assert kwargs["top_k"] >= 20
        assert kwargs["filter"]["user_id"] == {"$eq": "42"}
        assert kwargs["filter"]["kind"] == {"$in": ["fact"]}
        assert kwargs["include_metadata"] is True

    def test_result_shape_unchanged(self):
        ts = _iso_days_ago(2)
        store, _ = _store_with_matches([_match(0.8, "hello", ts)])
        out = store.recall(user_id=1, query="q")
        assert set(out[0].keys()) == {"kind", "content", "score", "ts"}
        assert out[0]["ts"] == ts
        assert isinstance(out[0]["score"], float)


class TestRecallAmbientScoreThreshold:
    """Phase 32 (Plan 06, MEM-01): recall_ambient applies a blended-score floor
    (AMBIENT_MIN_SCORE) on the auto-inject path; recall() stays unthresholded
    (D-03: deliberate tool calls can still see a marginal match).

    Test names carry the ``score_threshold`` keyword so
    ``pytest -k score_threshold`` selects this whole class."""

    def test_score_threshold_below_floor_excluded_from_ambient(self):
        """(a) a candidate with blended score below min_score is excluded."""
        store, _ = _store_with_matches([
            _match(0.3, "weak match", _iso_days_ago(0)),
        ])
        out = store.recall_ambient(user_id=1, query="q", k=5)
        assert out == []

    def test_score_threshold_at_or_above_floor_included_in_ambient(self):
        """(b) a candidate at/above the floor is included."""
        store, _ = _store_with_matches([
            _match(0.6, "strong match", _iso_days_ago(0)),
        ])
        out = store.recall_ambient(user_id=1, query="q", k=5)
        assert [r["content"] for r in out] == ["strong match"]

    def test_score_threshold_floor_is_inclusive_at_exact_boundary(self):
        """A blended score exactly at AMBIENT_MIN_SCORE is included (>=, not >)."""
        from memory.pinecone_db import AMBIENT_MIN_SCORE
        store, _ = _store_with_matches([
            _match(AMBIENT_MIN_SCORE, "boundary match", None),
        ])
        out = store.recall_ambient(user_id=1, query="q", k=5)
        assert [r["content"] for r in out] == ["boundary match"]

    def test_score_threshold_mixed_batch_only_qualifying_candidates_returned(self):
        store, _ = _store_with_matches([
            _match(0.9, "strong", _iso_days_ago(0)),
            _match(0.2, "weak", _iso_days_ago(0)),
            _match(0.55, "borderline-ok", _iso_days_ago(0)),
        ])
        out = store.recall_ambient(user_id=1, query="q", k=5)
        assert {r["content"] for r in out} == {"strong", "borderline-ok"}

    def test_score_threshold_recall_stays_unthresholded_for_marginal_match(self):
        """(c) the unthresholded recall() still returns a marginal match."""
        store, _ = _store_with_matches([
            _match(0.3, "marginal match", _iso_days_ago(0)),
        ])
        out = store.recall(user_id=1, query="q", k=5)
        assert [r["content"] for r in out] == ["marginal match"]

    def test_score_threshold_ambient_preserves_user_id_scoping(self):
        """(d) user_id scoping preserved on the ambient path."""
        store, index = _store_with_matches([])
        store.recall_ambient(user_id=42, query="q", k=5)

        kwargs = index.query.call_args.kwargs
        assert kwargs["filter"]["user_id"] == {"$eq": "42"}
        assert kwargs["include_metadata"] is True

    def test_score_threshold_ambient_respects_custom_min_score_param(self):
        store, _ = _store_with_matches([
            _match(0.4, "just below custom floor", None),
        ])
        out = store.recall_ambient(user_id=1, query="q", k=5, min_score=0.45)
        assert out == []
        out2 = store.recall_ambient(user_id=1, query="q", k=5, min_score=0.35)
        assert [r["content"] for r in out2] == ["just below custom floor"]
