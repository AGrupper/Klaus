"""Regression tests for the static Google Calendar refresh credential."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.auth_google import CALENDAR_SCOPE, GoogleAuthManager


class RecordingTokenStorage:
    """Expose token-store writes while serving one realistic OAuth credential."""

    def __init__(self) -> None:
        self.saved_payloads: list[str] = []

    def load(self) -> str:
        """Return a long-lived refresh credential with an expired access token."""
        return json.dumps(
            {
                "token": "expired-access-token",
                "refresh_token": "stable-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "calendar-client.apps.googleusercontent.com",
                "client_secret": "client-secret",
                "scopes": [CALENDAR_SCOPE],
                "expiry": "2026-08-01T00:00:00Z",
            }
        )

    def save(self, token_json: str) -> None:
        """Record any attempt to rotate the static stored credential."""
        self.saved_payloads.append(token_json)


def test_expired_access_token_refreshes_in_memory_without_rotating_storage() -> None:
    """Ordinary Calendar access renewal must not create a secret version."""
    storage = RecordingTokenStorage()
    manager = GoogleAuthManager("unused-client-file.json", storage)

    def refresh_without_network(credentials, _request) -> None:
        credentials.token = "fresh-access-token"
        credentials.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    with patch(
        "core.auth_google.Credentials.refresh",
        new=refresh_without_network,
    ):
        credentials = manager.get_credentials()

    assert credentials.token == "fresh-access-token"
    assert credentials.refresh_token == "stable-refresh-token"
    assert storage.saved_payloads == []
