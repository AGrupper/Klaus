"""Persistent Google OAuth 2.0 manager for Gmail + Calendar.

Implements the Phase-1 auth boilerplate (per `docs/TECHNICAL_PLAN.md` §3.1
and §4). Holds a refresh token on disk so the agent can call Google APIs
indefinitely without user re-consent — this works because the OAuth
consent screen is configured as **Internal**, which exempts refresh
tokens from the standard 7-day expiry.

Run this file directly to perform the one-time browser consent and verify
that credentials work end-to-end:

    python -m core.auth_google
"""
from __future__ import annotations

import logging
import os
from typing import Any

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


# OAuth scopes the agent needs.
#  - gmail.modify  : read inbox, mark read, send drafts (broad enough for Phase 3 tools).
#  - calendar      : full read/write on the primary calendar.
# IMPORTANT: editing this list invalidates the cached token.json — delete it to re-auth.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


class GoogleAuthManager:
    """Manages a single Google OAuth credential covering Gmail + Calendar.

    Lifecycle:
        1. First call to `get_credentials()` runs the browser consent flow
           and writes `token.json` to disk.
        2. Subsequent calls load `token.json` and silently refresh the
           access token when needed — no browser, no user interaction.
    """

    SCOPES: list[str] = [GMAIL_SCOPE, CALENDAR_SCOPE]

    def __init__(self, credentials_path: str, token_path: str) -> None:
        """
        Args:
            credentials_path: Path to the OAuth client secrets JSON
                downloaded from Google Cloud Console (Desktop app type).
            token_path: Where to persist the refresh token. Created on
                first auth; reused on subsequent runs.
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        # Lazy: don't authenticate at construction — caller decides when.
        self._creds: Credentials | None = None

    def get_credentials(self) -> Credentials:
        """Return valid `Credentials`, performing auth or refresh as needed.

        Resolution order:
            1. In-memory cache (subsequent calls in the same process).
            2. Existing `token.json` on disk → load + maybe refresh.
            3. No token on disk → run the interactive consent flow.

        Raises:
            FileNotFoundError: `credentials.json` is missing — see
                `config/README.md` for setup steps.
            GoogleAuthError: A non-recoverable auth failure (e.g. revoked
                consent, malformed client secrets). Caller should surface
                this to the user, not swallow it.
        """
        # 1. In-memory short-circuit.
        if self._creds is not None and self._creds.valid:
            return self._creds

        # 2. Try to reuse a cached token from disk.
        creds = self._load_cached_token()

        # 3. If cached token expired but is refreshable, refresh silently.
        if creds is not None and not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    # WHY: this is the hot path on every long-running invocation.
                    # If refresh succeeds we save the new access_token back to
                    # disk so the next process start is also seamless.
                    creds.refresh(Request())
                    self._persist_token(creds)
                except RefreshError as exc:
                    # WHY: a RefreshError means the refresh token itself is no
                    # longer accepted (revoked, expired, scopes changed, or
                    # consent screen flipped from Internal → External). There's
                    # nothing programmatic we can do — re-prompting silently
                    # would be confusing. Surface it loudly so the operator
                    # knows to delete token.json and re-consent.
                    logger.error(
                        "Refresh token rejected by Google: %s. "
                        "Delete %s and re-run to re-consent.",
                        exc,
                        self.token_path,
                    )
                    raise
            else:
                # Cached token is invalid AND has no refresh_token — discard.
                creds = None

        # 4. No usable cached token → run the interactive consent flow.
        if creds is None:
            creds = self._run_consent_flow()
            self._persist_token(creds)

        self._creds = creds
        return creds

    # ------------------------------------------------------------------ #
    # Service builders — thin convenience wrappers over googleapiclient. #
    # ------------------------------------------------------------------ #

    def gmail_service(self) -> Any:
        """Return an authenticated Gmail v1 service resource."""
        # cache_discovery=False silences a noisy warning on Cloud Run where
        # the local discovery cache directory isn't writable.
        return build("gmail", "v1", credentials=self.get_credentials(),
                     cache_discovery=False)

    def calendar_service(self) -> Any:
        """Return an authenticated Calendar v3 service resource."""
        return build("calendar", "v3", credentials=self.get_credentials(),
                     cache_discovery=False)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _load_cached_token(self) -> Credentials | None:
        """Load `token.json` from disk if it exists, else return None."""
        if not os.path.exists(self.token_path):
            return None
        try:
            return Credentials.from_authorized_user_file(self.token_path,
                                                         self.SCOPES)
        except (ValueError, GoogleAuthError) as exc:
            # WHY: a corrupt token.json should not crash the whole agent —
            # treat it as "no token" so the consent flow can run.
            logger.warning("Cached token at %s is unreadable (%s); discarding.",
                           self.token_path, exc)
            return None

    def _run_consent_flow(self) -> Credentials:
        """Run the one-time browser-based OAuth consent flow.

        Uses `run_local_server` which spins up a localhost callback server,
        opens the user's default browser, and blocks until consent is granted.
        """
        if not os.path.exists(self.credentials_path):
            # WHY: a clear, actionable error beats a stack trace. Point the
            # operator straight at the README that explains the fix.
            raise FileNotFoundError(
                f"OAuth client secrets not found at {self.credentials_path}. "
                f"See config/README.md for setup steps."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            self.credentials_path, self.SCOPES
        )
        # port=0 → OS picks a free port. Avoids conflicts on shared dev machines.
        return flow.run_local_server(port=0)

    def _persist_token(self, creds: Credentials) -> None:
        """Write `creds` to `token.json` so the next process can reuse it."""
        # Ensure the parent directory exists (config/ is created at scaffold
        # time but a custom GOOGLE_TOKEN_PATH may point elsewhere).
        token_dir = os.path.dirname(self.token_path)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(self.token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())


# ---------------------------------------------------------------------- #
# CLI entry point — Phase 1 smoke test.                                  #
# ---------------------------------------------------------------------- #

def _smoke_test() -> int:
    """Authenticate and print the active Gmail address. Exit code 0 on success."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS",
                                 "./config/credentials.json")
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "./config/token.json")

    manager = GoogleAuthManager(credentials_path=credentials_path,
                                token_path=token_path)

    try:
        gmail = manager.gmail_service()
        # users().getProfile is the cheapest authenticated call we can make —
        # it confirms the token works and returns the active email address.
        profile = gmail.users().getProfile(userId="me").execute()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except HttpError as exc:
        logger.error("Google API rejected the request: %s", exc)
        return 3
    except GoogleAuthError as exc:
        logger.error("Authentication failed: %s", exc)
        return 4

    print(f"Authenticated as: {profile.get('emailAddress', '<unknown>')}")
    print(f"Total messages in mailbox: {profile.get('messagesTotal', '?')}")
    print(f"Token cached at: {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
