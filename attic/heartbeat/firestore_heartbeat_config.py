"""Parked 2026-05-10. Extracted from memory/firestore_db.py. Import this file when reviving the heartbeat feature."""
from __future__ import annotations

import logging
import os

from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)


_HEARTBEAT_CONFIG_DEFAULTS: dict = {
    "enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "timezone": "Asia/Jerusalem",
    "cadence_minutes": 30,
}


class HeartbeatConfigStore:
    """Read/write heartbeat scheduler config stored in Firestore.

    Config doc lives at collection='config', document='heartbeat'.
    If the document is absent, defaults are returned without writing them,
    so the collection is only created on the first explicit set() call.
    """

    _COLLECTION = "config"
    _DOCUMENT = "heartbeat"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name. Defaults to "(default)".
        """
        credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
        if credentials_path:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/datastore"],
            )
            self._client = firestore.Client(
                project=project_id, credentials=credentials, database=database,
            )
        else:
            self._client = firestore.Client(project=project_id, database=database)

        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)

    def get(self) -> dict:
        """Return the heartbeat config, falling back to defaults for missing fields.

        Returns:
            Dict with keys: enabled, quiet_start, quiet_end, timezone, cadence_minutes.
        """
        try:
            snap = self._doc_ref.get()
            stored = snap.to_dict() or {} if snap.exists else {}
        except GoogleAPICallError:
            logger.warning("HeartbeatConfigStore.get() failed — using defaults")
            stored = {}

        return {**_HEARTBEAT_CONFIG_DEFAULTS, **stored}

    def set(self, patch: dict) -> None:
        """Merge `patch` into the stored config document (creates it if absent).

        Args:
            patch: Partial config dict. Only provided keys are updated.

        Raises:
            GoogleAPICallError: If the Firestore write fails.
        """
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except GoogleAPICallError:
            logger.error("HeartbeatConfigStore.set() failed")
            raise
