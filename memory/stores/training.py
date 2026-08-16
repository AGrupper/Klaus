"""Planned and completed training: the session log, mesocycle blocks, and
benchmark results.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _DESCENDING,
    _cache_get,
    _cache_invalidate_prefix,
    _cache_put,
    _jsonsafe_doc,
    _jsonsafe_value,
    _where,
)


class TrainingLogStore:
    """Per-session training log stored in Firestore (Phase 20 — LOG-01/LOG-02).

    Collection: training_log
    Document ID: {YYYY-MM-DD}_{slot}

    Idempotency:
        Garmin silent sync may write before the user replies; merge=True on the
        doc_id key prevents duplicate rows (Pitfall 4 / LOG-01).

    RPE normalisation (Pitfall 7):
        Garmin stores perceived_exertion in steps of 10 (10..100 for 1..10 scale).
        log_session normalises values > 10 that are multiples of 10 to the 1..10
        scale by integer division.  Values already in 1..10 are left unchanged.

    Read discipline (LOG-02):
        get_recent / get_by_date / get_range — never raise on Firestore errors;
        return [] so callers (weekly review, morning briefing) can degrade
        gracefully.

    Write discipline (LOG-01):
        log_session re-raises on Firestore write failures so callers know the
        sync failed (matches UserProfileStore.update / MealStore.upsert convention).
    """

    _COLLECTION = "training_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def log_session(
        self,
        date: str,                              # YYYY-MM-DD
        slot: str,                              # calendar event id or YYYYMMDDHHmm
        session_type: str | None = None,
        planned: bool = False,
        completed: bool = False,
        skipped_reason: str | None = None,      # rest_recovery | sick_injured | too_busy | other
        rpe: int | None = None,                 # 1–10 (normalised here from Garmin raw)
        feel: int | None = None,                # Garmin feel value, verbatim
        notes: str | None = None,
        quality: str | None = None,             # "strong" | "neutral" | "grind" | None (D-13 Phase 24)
        source: str = "telegram",               # garmin | telegram | manual_chat
        garmin_activity_id: str | None = None,
        calendar_event_id: str | None = None,
        plan_status: str | None = None,          # planned | moved | deleted
    ) -> None:
        """Write one training session to training_log/{date}_{slot}.

        Idempotent via merge=True — safe to call multiple times for the same
        (date, slot) pair (e.g. Garmin silent sync then user Telegram reply).

        Pitfall 7: normalises Garmin raw RPE (steps-of-10, 10..100) to 1..10.
        Values already in 1..10 are left unchanged.

        quality: "strong" | "neutral" | "grind" | None — D-13 derived field.
            Derived from Garmin Feel + RPE + notes by derive_session_quality in
            core/training_checkin.py. Existing entries without quality remain
            valid (merge=True handles backward compatibility).

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        doc_id = f"{date}_{slot}"
        # Pitfall 7: normalise Garmin raw RPE (steps-of-10, 10..100) to 1..10
        if rpe is not None and rpe > 10 and rpe % 10 == 0:
            rpe = rpe // 10
        payload = {
            "date": date,
            "slot": slot,
            "type": session_type,
            "planned": planned,
            "completed": completed,
            "skipped_reason": skipped_reason,
            "rpe": rpe,
            "feel": feel,
            "notes": notes,
            "quality": quality,
            "source": source,
            "garmin_activity_id": garmin_activity_id,
            "calendar_event_id": calendar_event_id,
            "plan_status": plan_status,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(doc_id).set(payload, merge=True)   # merge=True — idempotent
        except Exception:
            logger.error("TrainingLogStore.log_session(%r) failed", doc_id, exc_info=True)
            raise

    def get_recent(self, days: int) -> list[dict]:
        """Return sessions with date >= today-{days}, sorted date desc, with doc_id.

        Never raises — returns [] on any Firestore error (LOG-02).

        Args:
            days: Number of calendar days to look back (inclusive).

        Returns:
            List of session dicts, each with a ``doc_id`` field, sorted by date
            descending.  Empty list on any Firestore error.
        """
        try:
            from datetime import date as _date, timedelta
            cutoff = (_date.today() - timedelta(days=days)).isoformat()
            # Server-side filter + order — only the window's docs are read,
            # not the lifetime collection.
            query = _where(self._col, "date", ">=", cutoff).order_by(
                "date", direction=_DESCENDING
            )
            results = []
            for snap in query.stream():
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                results.append(d)
            return results
        except Exception:
            logger.warning("TrainingLogStore.get_recent failed", exc_info=True)
            return []

    def get_by_date(self, date_str: str) -> list[dict]:
        """Return all sessions for one calendar date.

        Every doc carries a ``date`` field equal to the YYYY-MM-DD prefix of
        its doc_id, so an equality query replaces the old doc-ID prefix scan.

        Never raises — returns [] on any Firestore error (LOG-02).

        Args:
            date_str: YYYY-MM-DD date.

        Returns:
            List of matching session dicts (each with doc_id).  Empty on error.
        """
        try:
            query = _where(self._col, "date", "==", date_str)
            return [
                {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
                for snap in query.stream()
            ]
        except Exception:
            logger.warning("TrainingLogStore.get_by_date(%r) failed", date_str, exc_info=True)
            return []

    def get_by_slot(self, slot: str) -> dict | None:
        """Return the newest row for a calendar/event slot; never raises."""
        try:
            query = _where(self._col, "slot", "==", slot)
            rows = [
                {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
                for snap in query.stream()
            ]
            rows.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
            return rows[0] if rows else None
        except Exception:
            logger.warning("TrainingLogStore.get_by_slot(%r) failed", slot, exc_info=True)
            return None

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return all sessions in [start_date, end_date] (inclusive), sorted date desc.

        Never raises — returns [] on any Firestore error (LOG-02).

        Args:
            start_date: YYYY-MM-DD start of range (inclusive).
            end_date:   YYYY-MM-DD end of range (inclusive).

        Returns:
            List of session dicts with doc_id, sorted date desc.  Empty on error.
        """
        try:
            query = _where(
                _where(self._col, "date", ">=", start_date), "date", "<=", end_date
            ).order_by("date", direction=_DESCENDING)
            results = []
            for snap in query.stream():
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                results.append(d)
            return results
        except Exception:
            logger.warning(
                "TrainingLogStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []


def get_week_num(plan_start_date: str, today: str) -> int | None:
    """Return the 1-based week number for ``today`` relative to ``plan_start_date``.

    Returns None when ``today`` is before ``plan_start_date`` (pre-cycle).

    Formula (D-03): ``(today - start).days // 7 + 1``
    Week 1 = days 0..6 inclusive; week 2 = days 7..13; etc.

    Args:
        plan_start_date: ISO date string "YYYY-MM-DD" (e.g. "2026-06-21").
        today:           ISO date string "YYYY-MM-DD" representing today.

    Returns:
        1-based week number, or None if today < plan_start_date.
    """
    from datetime import date as _date
    start = _date.fromisoformat(plan_start_date)
    today_dt = _date.fromisoformat(today)
    if today_dt < start:
        return None
    return (today_dt - start).days // 7 + 1


# 5-facet closed set for benchmark validation (D-06 / T-23-01)
_BENCHMARK_FACETS: frozenset[str] = frozenset({
    "bench_press_1rm",
    "squat_1rm",
    "push_ups",
    "pull_ups",
    "threshold_pace",
})


class BlockStore:
    """Training block tracking stored in Firestore (Phase 23 — BLOCK-01).

    Collection: training_blocks
    Document ID: {YYYY-MM-DD}_{label_slug} (e.g. "2026-06-21_aerobic_base")

    Schema fields:
        block_id:             str  — same as doc id: "{YYYY-MM-DD}_{label_slug}"
        label:                str  — "Aerobic Base", "Capacity Build", etc.
        start_date:           str  — YYYY-MM-DD (stored as string, not timestamp)
        end_date:             str  — YYYY-MM-DD (stored as string, not timestamp)
        focus_facets:         list — ["bench_press_1rm", "squat_1rm", ...]
        weekly_split_override:dict|None — None for auto-seeded blocks
        status:               str  — "active"|"complete"|"abandoned"|"pending"
                                     BOOKKEEPING ONLY — get_current does NOT filter on status
        notes:                str  — ""
        benchmark_due:        bool — False until deload week triggers it
        created_at:           SERVER_TIMESTAMP
        updated_at:           SERVER_TIMESTAMP

    get_current() resolution semantics (D-01 — the critical contract):
        Resolves by DATE RANGE (start_date <= today <= end_date) across all seeded
        blocks. Does NOT filter on status=active. This means Block 1 → Block 2
        transitions are automatic as time advances, even if start_block() is never
        called. The `status` field is bookkeeping for the current_block_id FK —
        not a precondition of get_current's correctness.

    Read discipline: get_current / get_all never raise (return None/[] on error).
    Write discipline: upsert / set_benchmark_due / start_block / end_block re-raise.
    """

    _COLLECTION = "training_blocks"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def get_current(self, today: str | None = None) -> dict | None:
        """Return the block whose date range contains today — or None if none matches.

        Resolution is DATE-RANGE based (D-01): start_date <= today <= end_date.
        Does NOT filter on status field — status is bookkeeping only.
        If multiple blocks overlap (should not happen with contiguous seed), returns
        the one with the earliest start_date.

        Args:
            today: ISO date string "YYYY-MM-DD". Defaults to current date when None.

        Returns:
            Block dict with doc_id attached, or None (pre/post-cycle or on error).
            Never raises.
        """
        try:
            if today is None:
                from datetime import date as _date
                today = _date.today().isoformat()
            snaps = list(self._col.stream())
            matches = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                start = d.get("start_date", "")
                end = d.get("end_date", "")
                if start and end and start <= today <= end:
                    matches.append(d)
            if not matches:
                return None
            # If multiple (shouldn't happen with contiguous seed), return earliest start
            matches.sort(key=lambda b: b.get("start_date", ""))
            return matches[0]
        except Exception:
            logger.warning("BlockStore.get_current() failed", exc_info=True)
            return None

    def get_all(self) -> list[dict]:
        """Return all training block docs, unordered, with doc_id.

        Never raises — returns [] on any Firestore error.
        """
        try:
            snaps = list(self._col.stream())
            results = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                results.append(d)
            return results
        except Exception:
            logger.warning("BlockStore.get_all() failed", exc_info=True)
            return []

    def upsert(self, block: dict) -> None:
        """Write or merge a block doc. Re-raises on Firestore failure.

        Uses merge=True so partial updates (e.g. set_benchmark_due) are safe.
        Stamps created_at and updated_at with SERVER_TIMESTAMP.

        Args:
            block: Block dict. Must include 'block_id' key (used as doc id).

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        doc_id = block["block_id"]
        payload = {
            **block,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            ref = self._col.document(doc_id)
            # WR-02: only stamp created_at on the FIRST write. A --force re-seed
            # uses merge=True, so unconditionally writing created_at would clobber
            # the original creation timestamp on every re-run.
            existing = ref.get()
            if not getattr(existing, "exists", False):
                payload["created_at"] = firestore.SERVER_TIMESTAMP
            ref.set(payload, merge=True)
        except Exception:
            logger.error("BlockStore.upsert(%r) failed", doc_id, exc_info=True)
            raise

    def set_benchmark_due(self, block_id: str, due: bool) -> None:
        """Set or clear the benchmark_due flag on an existing block.

        Uses merge=True — touches only benchmark_due and updated_at.

        Args:
            block_id: Block doc ID.
            due:      True to mark benchmark due; False to clear.

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        try:
            self._col.document(block_id).set(
                {"benchmark_due": due, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("BlockStore.set_benchmark_due(%r, %r) failed", block_id, due, exc_info=True)
            raise

    def start_block(self, block_id: str) -> None:
        """Set status='active' on a block (bookkeeping — not a precondition of get_current).

        Also updates the updated_at timestamp via merge.

        Args:
            block_id: Block doc ID.

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        try:
            self._col.document(block_id).set(
                {"status": "active", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("BlockStore.start_block(%r) failed", block_id, exc_info=True)
            raise

    def end_block(self, block_id: str) -> None:
        """Set status='complete' on a block (bookkeeping — not a precondition of get_current).

        Also updates the updated_at timestamp via merge.

        Args:
            block_id: Block doc ID.

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        try:
            self._col.document(block_id).set(
                {"status": "complete", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("BlockStore.end_block(%r) failed", block_id, exc_info=True)
            raise


class BenchmarkStore:
    """Per-facet benchmark results stored in Firestore (Phase 23 — BLOCK-03).

    Collection: benchmarks
    Document ID: {YYYY-MM-DD}_{facet} (e.g. "2026-07-18_bench_press_1rm")

    Schema fields:
        date:       str   — YYYY-MM-DD
        facet:      str   — one of the 5-facet closed set (D-06)
        value:      float — numeric result
        unit:       str   — "kg" | "reps" | "sec_per_km"
        block_id:   str   — FK → training_blocks doc id
        notes:      str   — optional note (e.g. "Epley estimate from 85kg×5")
        updated_at: SERVER_TIMESTAMP

    Idempotency: doc_id = "{date}_{facet}" — logging the same facet on the same date
    merges (merge=True), so retries are safe.

    Input validation (T-23-01): log_benchmark raises ValueError for any facet outside
    the 5-facet closed set (_BENCHMARK_FACETS) — prevents arbitrary doc creation from
    LLM-supplied facet strings.

    Read discipline: get_facet_history / get_block_benchmarks never raise (return []).
    Write discipline: log_benchmark re-raises on Firestore failure.
    """

    _COLLECTION = "benchmarks"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def log_benchmark(
        self,
        date: str,
        facet: str,
        value: float,
        unit: str,
        block_id: str,
        notes: str = "",
    ) -> None:
        """Write one benchmark result to benchmarks/{date}_{facet}.

        Idempotent via merge=True — safe to call multiple times for the same
        (date, facet) pair (updates the value, e.g. on correction).

        Args:
            date:     YYYY-MM-DD date of the benchmark session.
            facet:    One of the 5 valid facets (T-23-01 validation).
            value:    Numeric result.
            unit:     "kg" | "reps" | "sec_per_km"
            block_id: FK to the training_blocks collection.
            notes:    Optional context note.

        Raises:
            ValueError:  If facet is not in the 5-facet closed set (T-23-01).
            Exception:   Re-raises any Firestore write failure.
        """
        if facet not in _BENCHMARK_FACETS:
            raise ValueError(
                f"Unknown facet {facet!r}. Valid facets: {sorted(_BENCHMARK_FACETS)}"
            )
        # IN-02: validate the date format before it becomes part of the doc id.
        # A malformed LLM-supplied date would otherwise produce an opaque SDK
        # error rather than a clean, catchable ValueError.
        from datetime import date as _date
        try:
            _date.fromisoformat(date)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date {date!r}; expected ISO YYYY-MM-DD")
        doc_id = f"{date}_{facet}"
        payload = {
            "date": date,
            "facet": facet,
            "value": value,
            "unit": unit,
            "block_id": block_id,
            "notes": notes,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(doc_id).set(payload, merge=True)
        except Exception:
            logger.error("BenchmarkStore.log_benchmark(%r) failed", doc_id, exc_info=True)
            raise

    def get_facet_history(self, facet: str, n: int = 10) -> list[dict]:
        """Return the last n benchmark entries for a specific facet, sorted date-desc.

        Streams all benchmark docs, filters by facet in Python, sorts, and caps.

        Args:
            facet: Facet to filter by (e.g. "bench_press_1rm").
            n:     Maximum number of records to return (default 10).

        Returns:
            List of benchmark dicts, each with doc_id, sorted date desc.
            Empty list on any error — never raises.
        """
        try:
            snaps = list(self._col.stream())
            results = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                if d.get("facet") == facet:
                    results.append(d)
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results[:n]
        except Exception:
            logger.warning("BenchmarkStore.get_facet_history(%r) failed", facet, exc_info=True)
            return []

    def get_block_benchmarks(self, block_id: str) -> list[dict]:
        """Return all benchmarks for a given block, sorted date-desc.

        Uses a server-side FieldFilter on block_id.

        Args:
            block_id: FK to the training_blocks collection.

        Returns:
            List of benchmark dicts with doc_id, sorted date desc.
            Empty list on any error — never raises.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            snaps = list(
                self._col.where(filter=FieldFilter("block_id", "==", block_id)).stream()
            )
            results = [
                {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
                for snap in snaps
            ]
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results
        except Exception:
            logger.warning(
                "BenchmarkStore.get_block_benchmarks(%r) failed", block_id, exc_info=True
            )
            return []

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return benchmarks across ALL 5 facets with date in [start_date, end_date].

        Sorted newest-first (client-side, matching this class's existing
        get_facet_history/get_block_benchmarks style — FieldFilter + Python sort,
        NOT the module-level `_where` helper used by RunDetailStore/StrengthSessionStore).

        Args:
            start_date: ISO YYYY-MM-DD, inclusive lower bound.
            end_date:   ISO YYYY-MM-DD, inclusive upper bound.

        Returns:
            List of benchmark dicts (via _jsonsafe_doc), sorted date desc.
            Empty list on any error — never raises.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            snaps = list(
                self._col
                .where(filter=FieldFilter("date", ">=", start_date))
                .where(filter=FieldFilter("date", "<=", end_date))
                .stream()
            )
            results = [_jsonsafe_doc(snap.to_dict() or {}) for snap in snaps]
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results
        except Exception:
            logger.warning(
                "BenchmarkStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []
