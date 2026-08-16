"""Logged meals and their daily aggregates, ingested from HealthKit.

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


def _is_newer(candidate, incumbent) -> bool:
    """True if ``candidate`` is a strictly newer updated_at than ``incumbent``.

    Tolerates ``None`` (treated as oldest) and any comparable timestamp type
    (Firestore ``DatetimeWithNanoseconds`` or ``datetime``). On an
    incomparable pair (e.g. tz-aware vs naive) it returns False so the
    first-seen doc is kept — a stable, deterministic tie-break. Used by
    :meth:`MealStore.get_day` to pick the latest of a duplicate set.
    """
    if candidate is None:
        return False
    if incumbent is None:
        return True
    try:
        return candidate > incumbent
    except TypeError:
        return False


class MealStore:
    """Per-date nutrition log persistence (Phase 19 — NUTR-02).

    Firestore path: ``meals/{YYYY-MM-DD}/timestamps/{source_id}``.

    The date-partitioned layout matches JournalStore's discipline (one
    document per calendar day) but uses a sub-collection of meal entries
    rather than a single doc — Lifesum can log many meals per day and
    each must round-trip through Fit + this store independently.

    Idempotency:
        ``source_id`` is the per-sample stable id the meal normalizer emits
        (currently ``healthkit:{uuid}`` from ``mcp_tools/healthkit_tool``).
        Re-syncs land on the same doc with ``merge=True``, so Lifesum
        sync-timing variance cannot produce duplicate rows (Pitfall 2 mitigation).

    Pitfall 4:
        ``get_day_aggregate`` returns ``{}`` (an EMPTY DICT) when no meals
        are logged for the date — NOT ``{"meal_count": 0}``. The Plan 19-04
        morning briefing uses truthiness on the return value to decide
        between silent-omit and rendering the nutrition section; a
        non-empty placeholder would break silent-omit.
    """

    _COLLECTION = "meals"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, source_id: str, meal: dict) -> None:
        """Idempotent on source_id. Re-raises on Firestore failure (caller decides).

        The meal dict's ``timestamp`` field (ISO-8601) drives the date-bucket
        document — slicing the first 10 chars yields ``YYYY-MM-DD``. The
        full meal payload is written with ``merge=True`` plus a server-side
        ``updated_at`` stamp; ``source_id`` is also written into the payload
        for easier downstream querying.

        Args:
            source_id: the per-sample stable id from the meal normalizer
                       (e.g. ``healthkit:{uuid}``).
            meal:      Normalized meal dict (see mcp_tools/healthkit_tool).

        Raises:
            Exception: re-raises any Firestore write failure after logging.
        """
        try:
            date_str = meal["timestamp"][:10]
            (
                self._col.document(date_str)
                .collection("timestamps")
                .document(source_id)
                .set(
                    {
                        **meal,
                        "source_id": source_id,
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
            )
        except Exception:
            logger.error("MealStore.upsert(%r) failed", source_id, exc_info=True)
            raise

    def get_day(self, date_str: str) -> list[dict]:
        """Return all meals for a date, sorted by timestamp ascending.

        Never raises — returns ``[]`` on any Firestore error so callers
        (e.g. the morning briefing) can degrade gracefully.

        Args:
            date_str: ``YYYY-MM-DD`` (Asia/Jerusalem calendar date).

        Returns:
            List of meal dicts, ordered by ``timestamp`` ascending. ``[]``
            when the date has no entries OR Firestore is unreachable.
        """
        try:
            snaps = self._col.document(date_str).collection("timestamps").stream()
            # De-duplicate re-synced meals (2026-06-09 fix). The iOS Shortcut
            # re-sends the day on every Lifesum close; before the source_id fix
            # a meal-time whose calorie total changed between syncs produced
            # several docs (e.g. lunch stored as both 1177 and 1180 kcal),
            # inflating daily totals. Collapse docs that share the same
            # (timestamp, source) — the duplicate signature — keeping the
            # most-recently-written one (max updated_at). This corrects totals
            # for days that accumulated duplicates BEFORE the source_id fix,
            # with no mutation of stored data. Google-Fit meals have unique
            # nanosecond timestamps, so they never collapse.
            best: dict[tuple, dict] = {}
            for s in snaps:
                d = s.to_dict() or {}
                # updated_at is the Firestore server-write stamp
                # (DatetimeWithNanoseconds). Use it to pick the latest of a
                # duplicate set, then strip it: it is not json-serializable and
                # would break downstream json.dumps (fetch_recent_meals tool +
                # autonomous triage snapshot); it is write-metadata, not meal data.
                updated_at = d.pop("updated_at", None)
                key = (d.get("timestamp", ""), d.get("source"))
                prev = best.get(key)
                if prev is None or _is_newer(updated_at, prev[0]):
                    best[key] = (updated_at, d)
            meals = [d for _, d in best.values()]
            return sorted(meals, key=lambda d: d.get("timestamp", ""))
        except Exception:
            logger.warning("MealStore.get_day(%r) failed", date_str, exc_info=True)
            return []

    def get_day_aggregate(self, date_str: str) -> dict:
        """Return totals + per-meal-type breakdown + biggest_gap_minutes.

        Used by the Plan 19-04 morning briefing (NUTR-07 silent-omit gate)
        and the autonomous-tick gather (NUTR-04 nudge logic).

        Returns ``{}`` (empty dict) when no meals are logged on ``date_str``
        — Pitfall 4 contract. Callers MUST use truthiness checks
        (``if agg: ...``) rather than key lookups, or silent-omit breaks.

        Args:
            date_str: ``YYYY-MM-DD`` (Asia/Jerusalem calendar date).

        Returns:
            ``{}`` when no meals; else::

                {
                    "meal_count":           int,
                    "totals":               {"calories": int, "protein_g": int, ...},
                    "by_type":              {1: count_of_meal_type_1, ...},
                    "biggest_gap_minutes":  float (rounded to 1 dp),
                    "meals":                ordered list (asc by timestamp),
                }
        """
        import collections
        from datetime import datetime as _dt

        meals = self.get_day(date_str)
        if not meals:
            # Pitfall 4 — silent-omit gate. DO NOT change to {"meal_count": 0}.
            return {}

        totals = {
            "calories":  sum(m.get("calories")  or 0 for m in meals),
            "protein_g": sum(m.get("protein_g") or 0 for m in meals),
            "carbs_g":   sum(m.get("carbs_g")   or 0 for m in meals),
            "fat_g":     sum(m.get("fat_g")     or 0 for m in meals),
            "fiber_g":   sum(m.get("fiber_g")   or 0 for m in meals),  # Phase 19.2
        }
        by_type: dict = collections.defaultdict(list)
        for m in meals:
            by_type[m.get("meal_type", 1)].append(m)

        biggest_gap_minutes = 0.0
        for i in range(1, len(meals)):
            try:
                t_prev = _dt.fromisoformat(meals[i - 1]["timestamp"])
                t_curr = _dt.fromisoformat(meals[i]["timestamp"])
                gap = (t_curr - t_prev).total_seconds() / 60.0
                if gap > biggest_gap_minutes:
                    biggest_gap_minutes = gap
            except (KeyError, ValueError, TypeError):
                # Malformed timestamp on one entry → skip that pair.
                continue

        return {
            "meal_count":          len(meals),
            "totals":              totals,
            "by_type":             {k: len(v) for k, v in by_type.items()},
            "biggest_gap_minutes": round(biggest_gap_minutes, 1),
            "meals":               meals,  # ordered — prompt may render breakdown
        }
