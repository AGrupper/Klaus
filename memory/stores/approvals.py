"""The high-risk action handshake: idempotency records and the
prepare-then-confirm approval queue.

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


class ActionIdempotencyStore:
    """Bind each remote write key to one immutable payload and cached result."""

    _COLLECTION = "action_idempotency"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    @staticmethod
    def _digest(tool_name: str, payload: dict, origin: str) -> str:
        import hashlib
        import json

        canonical = json.dumps(
            {"tool_name": tool_name, "payload": payload, "origin": origin},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _document_id(idempotency_key: str) -> str:
        import hashlib

        return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

    def begin(
        self,
        idempotency_key: str,
        *,
        tool_name: str,
        payload: dict,
        origin: str,
    ) -> dict:
        """Atomically claim a key or return its exact prior execution record."""
        from datetime import datetime, timedelta, timezone

        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if len(idempotency_key) > 256:
            raise ValueError("idempotency_key is too long")
        payload_hash = self._digest(tool_name, payload, origin)
        record = {
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "payload_hash": payload_hash,
            "origin": origin,
            "status": "running",
            "result": None,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expire_at": datetime.now(timezone.utc) + timedelta(days=30),
        }
        doc = self._col.document(self._document_id(idempotency_key))
        try:
            # Firestore create() is atomic and fails if another request won.
            doc.create(record)
            return {**record, "is_new": True}
        except Exception:
            snap = doc.get()
            if not snap.exists:
                raise
            existing = _jsonsafe_doc(snap.to_dict() or {})
            if existing.get("payload_hash") != payload_hash:
                raise ValueError("idempotency_key was already used for a different payload")
            return {**existing, "is_new": False}

    def mark_executed(self, idempotency_key: str, result: dict) -> None:
        """Persist a result before auditing so retries never repeat the write."""
        from datetime import datetime, timezone

        self._col.document(self._document_id(idempotency_key)).set(
            {
                "status": "executed",
                "result": _jsonsafe_doc(result),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )

    def complete(self, idempotency_key: str) -> None:
        """Mark an executed action fully audited and replay-safe."""
        from datetime import datetime, timezone

        self._col.document(self._document_id(idempotency_key)).set(
            {
                "status": "succeeded",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )

    def fail(self, idempotency_key: str, error: str) -> None:
        """Record a pre-execution failure; a new retry must use a new key."""
        from datetime import datetime, timezone

        self._col.document(self._document_id(idempotency_key)).set(
            {
                "status": "failed",
                "error": str(error)[:1000],
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )


class PendingApprovalStore:
    """Store immutable, expiring confirmations for high-risk prepared actions.

    The canonical payload hash binds confirmation to the exact action Amit
    reviewed. A confirmed or rejected record can never be reused.
    """

    _COLLECTION = "pending_approvals"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    @staticmethod
    def payload_hash(payload: dict) -> str:
        """Return the SHA-256 hash of a canonical JSON action payload."""
        import hashlib
        import json

        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def prepare(
        self,
        *,
        action_type: str,
        payload: dict,
        origin: str,
        expires_in_seconds: int = 900,
        action_id: str | None = None,
        risk_category: str | None = None,
    ) -> dict:
        """Create a pending prepared action and return its public record.

        Args:
            action_type: Stable action category such as ``payment``.
            payload: Exact action parameters to bind to the confirmation.
            origin: ``interactive`` or ``routine``.
            expires_in_seconds: Positive approval lifetime, default 15 minutes.
            action_id: Optional caller-supplied idempotency identifier.
            risk_category: Optional policy category for the Hub display.

        Returns:
            The stored approval document without the server timestamp sentinel.
        """
        import uuid
        from datetime import datetime, timedelta, timezone

        if not action_type.strip():
            raise ValueError("action_type is required")
        if expires_in_seconds <= 0:
            raise ValueError("expires_in_seconds must be positive")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        now = datetime.now(timezone.utc)
        identifier = action_id or uuid.uuid4().hex
        expires_at = now + timedelta(seconds=expires_in_seconds)
        record = {
            "action_id": identifier,
            "action_type": action_type,
            "payload": dict(payload),
            "payload_hash": self.payload_hash(payload),
            "origin": origin,
            "risk_category": risk_category or action_type,
            "status": "pending",
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "expire_at": expires_at,
            "confirmation_state": "awaiting_user",
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
                raise RuntimeError("prepared action exists but could not be read") from exc
            return {**existing, "created": False}
        return {**record, "created": True}

    def get(self, action_id: str) -> dict | None:
        """Return an approval record or ``None``; never raise on read failure."""
        try:
            snap = self._col.document(action_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("PendingApprovalStore.get(%r) failed", action_id, exc_info=True)
            return None

    def list_pending(self) -> list[dict]:
        """Return unexpired pending approvals; never raises on read failure."""
        from datetime import datetime, timezone

        try:
            now = datetime.now(timezone.utc)
            results = []
            for snap in _where(self._col, "status", "==", "pending").stream():
                record = _jsonsafe_doc(snap.to_dict() or {})
                try:
                    expiry = datetime.fromisoformat(
                        str(record.get("expires_at") or "").replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if expiry > now:
                    results.append(record)
            return sorted(results, key=lambda item: str(item.get("created_at") or ""))
        except Exception:
            logger.warning("PendingApprovalStore.list_pending() failed", exc_info=True)
            return []

    def confirm(self, action_id: str, payload_hash: str) -> dict:
        """Atomically confirm one pending action with its immutable payload hash."""
        import hmac
        from datetime import datetime, timezone

        doc_ref = self._col.document(action_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def confirm_once(txn):
            snap = doc_ref.get(transaction=txn)
            if not snap.exists:
                raise ValueError("prepared action not found")
            record = snap.to_dict() or {}
            if record.get("status") != "pending":
                raise ValueError("prepared action is not pending")
            expected_hash = str(record.get("payload_hash") or "")
            if not hmac.compare_digest(expected_hash, str(payload_hash)):
                raise ValueError("payload hash does not match prepared action")
            try:
                expires_at = datetime.fromisoformat(
                    str(record["expires_at"]).replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("prepared action has invalid expiry") from exc
            now = datetime.now(timezone.utc)
            if expires_at <= now:
                patch = {
                    "status": "expired",
                    "confirmation_state": "expired",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
                txn.update(doc_ref, patch)
                return _jsonsafe_doc({**record, **patch}), True

            patch = {
                "status": "confirmed",
                "confirmation_state": "confirmed",
                "confirmed_at": now.isoformat(),
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            txn.update(doc_ref, patch)
            return _jsonsafe_doc({**record, **patch}), False

        confirmed, expired = confirm_once(transaction)
        if expired:
            raise ValueError("prepared action has expired")
        return confirmed

    def reject(self, action_id: str) -> dict:
        """Reject a pending action so its payload can never be confirmed later."""
        from datetime import datetime, timezone

        record = self.get(action_id)
        if not record or record.get("status") != "pending":
            raise ValueError("prepared action is not pending")
        patch = {
            "status": "rejected",
            "confirmation_state": "rejected",
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        self._col.document(action_id).set(patch, merge=True)
        return _jsonsafe_doc({**record, **patch})
