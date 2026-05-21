"""Persistent Google OAuth 2.0 manager for Gmail + Calendar.

Implements the Phase-1 auth boilerplate (per `docs/TECHNICAL_PLAN.md` §3.1
and §4). Holds a refresh token so the agent can call Google APIs indefinitely
without user re-consent — this works because the OAuth consent screen is
configured as **Internal**, which exempts refresh tokens from the standard
7-day expiry.

Token storage is pluggable via the `TokenStorage` protocol:
  - `FileTokenStorage`          — stores token.json on disk (local dev).
  - `SecretManagerTokenStorage` — stores token JSON in GCP Secret Manager
                                   (Cloud Run, where the filesystem is ephemeral).

Use `build_auth_manager_from_env()` to get the correct storage backend
based on the `GOOGLE_TOKEN_STORAGE` env var.

Run this file directly to perform the one-time browser consent and verify
that credentials work end-to-end:

    python -m core.auth_google
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

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
# IMPORTANT: editing this list invalidates the cached token — delete it to re-auth.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


# ------------------------------------------------------------------ #
# Token storage protocol and backends                                #
# ------------------------------------------------------------------ #

@runtime_checkable
class TokenStorage(Protocol):
    """Protocol for pluggable OAuth token persistence backends.

    Both methods deal in raw JSON strings (as produced by
    `Credentials.to_json()`) so each backend is purely responsible for
    I/O — no credential parsing happens here.
    """

    def load(self) -> str | None:
        """Return the stored token JSON string, or None if not found."""
        ...

    def save(self, token_json: str) -> None:
        """Persist the token JSON string."""
        ...


class FileTokenStorage:
    """Stores the OAuth token as a plain file on the local filesystem.

    Suitable for local development. Not suitable for Cloud Run, where the
    container filesystem is ephemeral and does not survive restarts.
    """

    def __init__(self, path: str) -> None:
        """
        Args:
            path: Absolute or relative path to the token JSON file.
                  Directories are created on first save if they don't exist.
        """
        self.path = path

    def load(self) -> str | None:
        """Read and return the token file contents, or None if the file doesn't exist."""
        if not os.path.exists(self.path):
            return None
        with open(self.path, "r", encoding="utf-8") as fh:
            return fh.read()

    def save(self, token_json: str) -> None:
        """Write token JSON to disk, creating parent directories if needed."""
        token_dir = os.path.dirname(self.path)
        if token_dir:
            # WHY: a custom GOOGLE_TOKEN_PATH may point to a directory that
            # doesn't exist yet; makedirs is idempotent so safe to always call.
            os.makedirs(token_dir, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(token_json)


class SecretManagerTokenStorage:
    """Stores the OAuth token as a GCP Secret Manager secret version.

    Designed for Cloud Run, where the local filesystem does not survive
    container restarts. The secret itself must be pre-created in GCP;
    this class only manages versions (add / read latest).

    IAM requirement:
        The runtime service account needs the `secretmanager.secretVersionAdder`
        role on the secret to call `add_secret_version`.

    WHY immutable versions:
        Secret Manager versions are immutable — you can never overwrite a
        version's payload. Each token refresh therefore creates a new version.
        `load` always reads `latest`, which automatically resolves to the
        most recently added version.
    """

    def __init__(self, project_id: str, secret_name: str) -> None:
        """
        Args:
            project_id: GCP project ID (e.g. "my-project-123").
            secret_name: Name of the pre-created secret resource (e.g.
                         "google-oauth-token").
        """
        self.project_id = project_id
        self.secret_name = secret_name

    def load(self) -> str | None:
        """Read the latest secret version and return the decoded payload.

        Returns None if the secret exists but has no versions yet (first run
        before any token has been saved).
        """
        from google.cloud import secretmanager
        from google.api_core.exceptions import NotFound

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.project_id}/secrets/{self.secret_name}/versions/latest"
        try:
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("utf-8")
        except NotFound:
            # WHY: on the very first deployment there are no versions yet.
            # Treat this as "no cached token" so the consent flow can run.
            logger.info(
                "Secret '%s' has no versions yet; will run consent flow.",
                self.secret_name,
            )
            return None

    def save(self, token_json: str) -> None:
        """Add a new secret version containing the token JSON.

        WHY a new version instead of overwrite:
            Secret Manager versions are immutable by design. Each refresh
            cycle adds a new version; `load` always resolves `latest` to
            the newest one. Old versions are kept but never used.
        """
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{self.project_id}/secrets/{self.secret_name}"
        client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": token_json.encode("utf-8")},
            }
        )
        logger.debug("Saved new token version to secret '%s'.", self.secret_name)


# ------------------------------------------------------------------ #
# Auth manager                                                       #
# ------------------------------------------------------------------ #

class GoogleAuthManager:
    """Manages a single Google OAuth credential covering Gmail + Calendar.

    Delegates all token persistence to an injected `TokenStorage` backend,
    which makes the manager storage-agnostic and independently testable.

    Lifecycle:
        1. First call to `get_credentials()` runs the browser consent flow
           and persists the token via the storage backend.
        2. Subsequent calls load the token via the storage backend and
           silently refresh the access token when needed — no browser,
           no user interaction.
    """

    SCOPES: list[str] = [GMAIL_SCOPE, CALENDAR_SCOPE]

    def __init__(self, credentials_path: str, token_storage: TokenStorage) -> None:
        """
        Args:
            credentials_path: Path to the OAuth client secrets JSON
                downloaded from Google Cloud Console (Desktop app type).
            token_storage: A `TokenStorage` implementation that handles
                reading and writing the token. Use `FileTokenStorage` for
                local dev or `SecretManagerTokenStorage` for Cloud Run.
        """
        self.credentials_path = credentials_path
        self._token_storage = token_storage
        # Lazy: don't authenticate at construction — caller decides when.
        self._creds: Credentials | None = None

    def get_credentials(self) -> Credentials:
        """Return valid `Credentials`, performing auth or refresh as needed.

        Resolution order:
            1. In-memory cache (subsequent calls in the same process).
            2. Token from storage backend → load + maybe refresh.
            3. No token in storage → run the interactive consent flow.

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

        # 2. Try to reuse a cached token from the storage backend.
        creds = self._load_cached_token()

        # 3. If cached token expired but is refreshable, refresh silently.
        if creds is not None and not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    # WHY: this is the hot path on every long-running invocation.
                    # If refresh succeeds we save the new access_token back to
                    # storage so the next process start is also seamless.
                    creds.refresh(Request())
                    self._persist_token(creds)
                except RefreshError as exc:
                    # WHY: a RefreshError means the refresh token itself is no
                    # longer accepted (revoked, expired, scopes changed, or
                    # consent screen flipped from Internal → External). There's
                    # nothing programmatic we can do — re-prompting silently
                    # would be confusing. Surface it loudly so the operator
                    # knows to delete/clear the token and re-consent.
                    logger.error(
                        "Refresh token rejected by Google: %s. "
                        "Clear the stored token and re-run to re-consent.",
                        exc,
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
        """Load token from the storage backend; return None if absent or corrupt."""
        payload = self._token_storage.load()
        if payload is None:
            return None
        try:
            # WHY: from_authorized_user_info accepts a dict parsed from the
            # JSON string. This is storage-backend-agnostic — it works whether
            # the payload came from a file, Secret Manager, or any other source.
            return Credentials.from_authorized_user_info(
                json.loads(payload), self.SCOPES
            )
        except (ValueError, GoogleAuthError) as exc:
            # WHY: a corrupt token should not crash the whole agent —
            # treat it as "no token" so the consent flow can run.
            logger.warning(
                "Cached token from storage is unreadable (%s); discarding.", exc
            )
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
        """Persist the credentials via the storage backend."""
        self._token_storage.save(creds.to_json())


# ------------------------------------------------------------------ #
# Factory function                                                   #
# ------------------------------------------------------------------ #

def build_auth_manager_from_env() -> GoogleAuthManager:
    """Construct a `GoogleAuthManager` backed by the storage configured in env vars.

    Reads `GOOGLE_TOKEN_STORAGE` (default: ``"file"``) to select the backend:

    ``"file"``
        `FileTokenStorage` using the path from `GOOGLE_TOKEN_PATH`
        (default: ``"./config/token.json"``). Suitable for local dev.

    ``"secret_manager"``
        `SecretManagerTokenStorage` using `GCP_PROJECT_ID` and
        `GOOGLE_TOKEN_SECRET_NAME` env vars. Suitable for Cloud Run.

    Returns:
        A fully-configured `GoogleAuthManager` instance.

    Raises:
        KeyError: If `GOOGLE_TOKEN_STORAGE` is ``"secret_manager"`` but
            `GCP_PROJECT_ID` or `GOOGLE_TOKEN_SECRET_NAME` are not set.
        ValueError: If `GOOGLE_TOKEN_STORAGE` is set to an unrecognised value.
    """
    storage_backend = os.getenv("GOOGLE_TOKEN_STORAGE", "file")

    if storage_backend == "file":
        token_path = os.getenv("GOOGLE_TOKEN_PATH", "./config/token.json")
        storage: TokenStorage = FileTokenStorage(path=token_path)
    elif storage_backend == "secret_manager":
        # WHY: require these vars to be present rather than silently
        # defaulting — a misconfigured Cloud Run deployment should fail
        # loudly at startup, not at the first API call.
        project_id = os.environ["GCP_PROJECT_ID"]
        secret_name = os.environ["GOOGLE_TOKEN_SECRET_NAME"]
        storage = SecretManagerTokenStorage(
            project_id=project_id, secret_name=secret_name
        )
    else:
        raise ValueError(
            f"Unknown GOOGLE_TOKEN_STORAGE value: '{storage_backend}'. "
            f"Expected 'file' or 'secret_manager'."
        )

    credentials_path = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", "./config/credentials.json"
    )
    return GoogleAuthManager(
        credentials_path=credentials_path, token_storage=storage
    )


# ---------------------------------------------------------------------- #
# CLI entry point — Phase 1 smoke test.                                  #
# ---------------------------------------------------------------------- #

def _smoke_test() -> int:
    """Authenticate and print the active Gmail address. Exit code 0 on success."""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    manager = build_auth_manager_from_env()

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

    storage_backend = os.getenv("GOOGLE_TOKEN_STORAGE", "file")
    print(f"Authenticated as: {profile.get('emailAddress', '<unknown>')}")
    print(f"Total messages in mailbox: {profile.get('messagesTotal', '?')}")
    print(f"Token storage backend: {storage_backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
