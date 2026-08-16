"""Routine runs and the reviews they publish. The two are coupled through
publish_review_atomic, which is why they share a module.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging

from google.cloud import firestore

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _DESCENDING,
    _jsonsafe_doc,
)


class RoutineReviewStore:
    """Common review schema layered onto the existing routine collections."""

    _COLLECTIONS = {
        "morning": "morning_briefings",
        "nightly": "nightly_reviews",
        "weekly": "weekly_reviews",
    }
    _STATUSES = frozenset(
        {"published_claude", "published_fallback", "late_upgraded"}
    )

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)

    @classmethod
    def build_record(
        cls,
        *,
        routine: str,
        target_date: str,
        correlation_id: str,
        status: str,
        text: str,
        structured: dict | None = None,
        action_ids: list[str] | None = None,
        partial_actions: list[dict] | None = None,
        claude_session_url: str | None = None,
        published_at: str | None = None,
    ) -> dict:
        """Build and validate the canonical routine-review record."""
        from datetime import datetime, timezone

        from core.routines.delivery import normalise_claude_session_url

        if routine not in cls._COLLECTIONS:
            raise ValueError(f"unsupported routine: {routine}")
        if status not in cls._STATUSES:
            raise ValueError(f"unsupported review status: {status}")
        if not text.strip():
            raise ValueError("review text is required")
        record = {
            "review_id": f"{routine}:{target_date}",
            "correlation_id": correlation_id,
            "routine": routine,
            "target_date": target_date,
            "routine_status": status,
            "provider": (
                "deterministic"
                if status == "published_fallback"
                else "claude_subscription"
            ),
            "review_text": text,
            "structured": dict(structured or {}),
            "action_ids": [str(item) for item in action_ids or []],
            "partial_actions": [_jsonsafe_doc(item) for item in partial_actions or []],
            "published_at": published_at or datetime.now(timezone.utc).isoformat(),
        }
        session_url = normalise_claude_session_url(claude_session_url)
        if session_url:
            record["claude_session_url"] = session_url
        return record

    def publish(
        self,
        *,
        routine: str,
        target_date: str,
        correlation_id: str,
        status: str,
        text: str,
        structured: dict | None = None,
        action_ids: list[str] | None = None,
        partial_actions: list[dict] | None = None,
        claude_session_url: str | None = None,
    ) -> dict:
        """Merge a Claude/fallback publication into its existing date document."""
        record = self.build_record(
            routine=routine,
            target_date=target_date,
            correlation_id=correlation_id,
            status=status,
            text=text,
            structured=structured,
            action_ids=action_ids,
            partial_actions=partial_actions,
            claude_session_url=claude_session_url,
        )
        self._client.collection(self._COLLECTIONS[routine]).document(target_date).set(
            {**record, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return dict(record)

    def get(self, routine: str, target_date: str) -> dict | None:
        """Read one review from its existing collection; never raises."""
        try:
            collection = self._COLLECTIONS[routine]
            snap = self._client.collection(collection).document(target_date).get()
            return _jsonsafe_doc(snap.to_dict() or {}) if snap.exists else None
        except Exception:
            logger.warning(
                "RoutineReviewStore.get(%r, %r) failed",
                routine,
                target_date,
                exc_info=True,
            )
            return None

    def list_recent(self, limit_per_routine: int = 10) -> list[dict]:
        """Return recent v7 reviews across existing routine collections."""
        limit = max(1, min(int(limit_per_routine), 31))
        reviews = []
        for routine, collection in self._COLLECTIONS.items():
            try:
                query = self._client.collection(collection).order_by(
                    "target_date", direction=_DESCENDING
                ).limit(limit)
                for snap in query.stream():
                    record = _jsonsafe_doc(snap.to_dict() or {})
                    if record.get("review_text"):
                        record.setdefault("routine", routine)
                        reviews.append(record)
            except Exception:
                logger.warning(
                    "RoutineReviewStore.list_recent(%s) failed", routine, exc_info=True
                )
        return sorted(
            reviews,
            key=lambda item: str(item.get("published_at") or item.get("target_date") or ""),
            reverse=True,
        )


class RoutineRunStore:
    """Shared morning/nightly/weekly subscription-routine run state."""

    _COLLECTION = "routine_runs"
    _ROUTINES = frozenset({"morning", "nightly", "weekly"})
    _STATUSES = frozenset({
        "queued",
        "running",
        "published_claude",
        "published_fallback",
        "late_upgraded",
        "failed",
    })
    _TRANSITIONS = {
        "queued": frozenset({"running", "published_claude", "published_fallback", "failed"}),
        "running": frozenset({"published_claude", "published_fallback", "failed"}),
        "published_fallback": frozenset({"late_upgraded"}),
        "published_claude": frozenset(),
        "late_upgraded": frozenset(),
        "failed": frozenset(),
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def start(
        self,
        *,
        routine: str,
        target_date: str,
        trigger: str,
        correlation_id: str | None = None,
        callback_timeout_seconds: int = 600,
        delivery_mode: str = "live",
    ) -> dict:
        """Create a queued routine run before the external Claude trigger fires."""
        import uuid
        from datetime import datetime, timedelta, timezone

        if routine not in self._ROUTINES:
            raise ValueError(f"unsupported routine: {routine}")
        if callback_timeout_seconds <= 0:
            raise ValueError("callback_timeout_seconds must be positive")
        if delivery_mode not in {"live", "shadow"}:
            raise ValueError("delivery_mode must be live or shadow")
        now = datetime.now(timezone.utc)
        identifier = correlation_id or uuid.uuid4().hex
        record = {
            "correlation_id": identifier,
            "routine": routine,
            "target_date": target_date,
            "trigger": trigger,
            "status": "queued",
            "provider": "claude_subscription",
            "delivery_mode": delivery_mode,
            "created_at": now.isoformat(),
            "callback_deadline_at": (
                now + timedelta(seconds=callback_timeout_seconds)
            ).isoformat(),
            "published_at": None,
            "review_id": None,
            "error": None,
        }
        doc_ref = self._col.document(identifier)
        try:
            doc_ref.create({**record, "updated_at": firestore.SERVER_TIMESTAMP})
        except Exception as exc:
            from google.api_core.exceptions import AlreadyExists

            if not isinstance(exc, AlreadyExists):
                raise
            existing = self.get(identifier)
            if existing is None:
                raise RuntimeError("routine run exists but could not be read") from exc
            return {**existing, "created": False}
        return {**record, "created": True}

    def get(self, correlation_id: str) -> dict | None:
        """Return a routine run or ``None``; never raise on read failure."""
        try:
            snap = self._col.document(correlation_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("RoutineRunStore.get(%r) failed", correlation_id, exc_info=True)
            return None

    def patch(self, correlation_id: str, **fields) -> dict:
        """Merge non-status trigger metadata into an existing run."""
        from datetime import datetime, timezone

        current = self.get(correlation_id)
        if current is None:
            raise ValueError("routine run not found")
        stored_patch = {**fields, "updated_at": firestore.SERVER_TIMESTAMP}
        returned_patch = {
            **fields,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._col.document(correlation_id).set(stored_patch, merge=True)
        return _jsonsafe_doc({**current, **returned_patch})

    def list_recent(self, limit: int = 20) -> list[dict]:
        """Return newest routine runs for Hub status and usage reporting."""
        try:
            query = self._col.order_by("created_at", direction=_DESCENDING).limit(
                max(1, min(int(limit), 100))
            )
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("RoutineRunStore.list_recent() failed", exc_info=True)
            return []

    def transition(self, correlation_id: str, status: str, **fields) -> dict:
        """Atomically apply a validated state transition and return the record."""
        from datetime import datetime, timezone

        if status not in self._STATUSES:
            raise ValueError(f"unsupported routine status: {status}")
        doc_ref = self._col.document(correlation_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def transition_once(txn):
            snap = doc_ref.get(transaction=txn)
            if not snap.exists:
                raise ValueError("routine run not found")
            current = snap.to_dict() or {}
            current_status = str(current.get("status") or "")
            if status not in self._TRANSITIONS.get(current_status, frozenset()):
                raise ValueError(
                    f"invalid routine transition: {current_status or 'unknown'} -> {status}"
                )
            patch = {
                **fields,
                "status": status,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            if status.startswith("published_") or status == "late_upgraded":
                patch.setdefault("published_at", datetime.now(timezone.utc).isoformat())
            txn.update(doc_ref, patch)
            return _jsonsafe_doc({**current, **patch})

        return transition_once(transaction)

    def transition_claude_publication(
        self, correlation_id: str, *, review_id: str,
    ) -> dict:
        """Atomically win an initial publication or claim a late fallback upgrade."""
        from datetime import datetime, timezone

        doc_ref = self._col.document(correlation_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def transition_once(txn):
            snap = doc_ref.get(transaction=txn)
            if not snap.exists:
                raise ValueError("routine run not found")
            current = snap.to_dict() or {}
            current_status = str(current.get("status") or "")
            if current_status in {"queued", "running"}:
                target_status = "published_claude"
            elif current_status == "published_fallback":
                target_status = "late_upgraded"
            else:
                raise ValueError(
                    f"invalid routine transition: {current_status or 'unknown'} -> claude"
                )
            patch = {
                "status": target_status,
                "review_id": review_id,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            txn.update(doc_ref, patch)
            return _jsonsafe_doc({**current, **patch})

        return transition_once(transaction)

    def publish_review_atomic(
        self,
        correlation_id: str,
        *,
        publisher: str,
        text: str,
        structured: dict | None = None,
        action_ids: list[str] | None = None,
        partial_actions: list[dict] | None = None,
        claude_session_url: str | None = None,
    ) -> dict:
        """Atomically transition a live run and write its canonical review."""
        from datetime import datetime, timezone

        if publisher not in {"claude", "fallback"}:
            raise ValueError(f"unsupported routine publisher: {publisher}")
        run_ref = self._col.document(correlation_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def publish_once(txn):
            snap = run_ref.get(transaction=txn)
            if not snap.exists:
                raise ValueError("routine run not found")
            current = snap.to_dict() or {}
            current_status = str(current.get("status") or "")
            if publisher == "fallback":
                if current_status not in {"queued", "running"}:
                    return {
                        "committed": False,
                        "initial_publication": False,
                        "run": _jsonsafe_doc(current),
                        "review": None,
                    }
                target_status = "published_fallback"
                initial_publication = True
            elif current_status in {"queued", "running"}:
                target_status = "published_claude"
                initial_publication = True
            elif current_status == "published_fallback":
                target_status = "late_upgraded"
                initial_publication = False
            else:
                raise ValueError(
                    f"invalid routine transition: {current_status or 'unknown'} -> claude"
                )

            routine = str(current.get("routine") or "")
            target_date = str(current.get("target_date") or "")
            published_at = datetime.now(timezone.utc).isoformat()
            review = RoutineReviewStore.build_record(
                routine=routine,
                target_date=target_date,
                correlation_id=correlation_id,
                status=target_status,
                text=text,
                structured=structured,
                action_ids=action_ids,
                partial_actions=partial_actions,
                claude_session_url=claude_session_url,
                published_at=published_at,
            )
            stored_run_patch = {
                "status": target_status,
                "review_id": review["review_id"],
                "published_at": published_at,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            returned_run_patch = {
                **stored_run_patch,
                "updated_at": published_at,
            }
            review_ref = self._client.collection(
                RoutineReviewStore._COLLECTIONS[routine]
            ).document(target_date)
            txn.update(run_ref, stored_run_patch)
            txn.set(
                review_ref,
                {**review, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
            return {
                "committed": True,
                "initial_publication": initial_publication,
                "run": _jsonsafe_doc({**current, **returned_run_patch}),
                "review": dict(review),
            }

        return publish_once(transaction)
