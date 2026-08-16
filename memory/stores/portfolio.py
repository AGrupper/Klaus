"""Portfolio holdings and weekly ILS valuations.

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


class PortfolioHoldingStore:
    """Current portfolio holdings with native-currency provenance."""

    _COLLECTION = "portfolio_holdings"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    @staticmethod
    def _holding_id(exchange: str, ticker: str) -> str:
        """Return a stable Firestore-safe identifier for an exchange/ticker pair."""
        import re

        raw = f"{exchange}-{ticker}".lower()
        return re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")

    def upsert(self, holding: dict) -> dict:
        """Create or update a holding without discarding historical optional fields."""
        from datetime import datetime, timezone

        ticker = str(holding.get("ticker") or "").strip().upper()
        exchange = str(holding.get("exchange") or "").strip().upper()
        if not ticker or not exchange:
            raise ValueError("ticker and exchange are required")
        if holding.get("quantity") is None and holding.get("position_value") is None:
            raise ValueError("quantity or position_value is required")

        identifier = str(holding.get("id") or self._holding_id(exchange, ticker))
        record = {
            **holding,
            "id": identifier,
            "ticker": ticker,
            "exchange": exchange,
            "native_currency": str(holding.get("native_currency") or "").upper(),
            "source_urls": [str(url) for url in holding.get("source_urls") or []],
            "observed_at": holding.get("observed_at") or datetime.now(timezone.utc).isoformat(),
            "status": holding.get("status") or "active",
        }
        self._col.document(identifier).set(
            {**record, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return dict(record)

    def get(self, holding_id: str) -> dict | None:
        """Return one holding or ``None``; never raise on read failure."""
        try:
            snap = self._col.document(holding_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("PortfolioHoldingStore.get(%r) failed", holding_id, exc_info=True)
            return None

    def list_active(self) -> list[dict]:
        """Return active holdings; never raise on Firestore failure."""
        try:
            return [
                _jsonsafe_doc(snap.to_dict() or {})
                for snap in _where(self._col, "status", "==", "active").stream()
            ]
        except Exception:
            logger.warning("PortfolioHoldingStore.list_active() failed", exc_info=True)
            return []


class PortfolioSnapshotStore:
    """Weekly portfolio valuations in ILS with quote and FX provenance."""

    _COLLECTION = "portfolio_snapshots"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def write_weekly(self, snapshot: dict) -> dict:
        """Idempotently write a weekly snapshot keyed by its ISO week date."""
        from datetime import datetime, timezone

        week = str(snapshot.get("week") or "")
        if not week:
            raise ValueError("week is required")
        if snapshot.get("total_ils") is None:
            raise ValueError("total_ils is required")
        record = {
            **snapshot,
            "week": week,
            "holdings": list(snapshot.get("holdings") or []),
            "source_urls": [str(url) for url in snapshot.get("source_urls") or []],
            "observed_at": snapshot.get("observed_at") or datetime.now(timezone.utc).isoformat(),
        }
        self._col.document(week).set(
            {**record, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return dict(record)

    def get(self, week: str) -> dict | None:
        """Return a weekly snapshot or ``None``; never raise on read failure."""
        try:
            snap = self._col.document(week).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("PortfolioSnapshotStore.get(%r) failed", week, exc_info=True)
            return None

    def list_recent(self, limit: int = 12) -> list[dict]:
        """Return newest weekly valuations, bounded and json-safe."""
        try:
            query = self._col.order_by("week", direction=_DESCENDING).limit(
                max(1, min(int(limit), 52))
            )
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("PortfolioSnapshotStore.list_recent() failed", exc_info=True)
            return []
