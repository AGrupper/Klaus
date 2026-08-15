"""Persistent Google OAuth 2.0 manager for Calendar.

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

import httplib2
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# WHY explicit + configurable: googleapiclient's own build_http() already sets
# a 60s httplib2 socket timeout when nothing else is specified, but that
# default is buried in the library and not something Klaus's operator can see
# or tune. Every outbound client Klaus owns gets an explicit, bounded,
# env-driven timeout
# rather than relying on an SDK default. 30s keeps a single stalled Calendar/
# Calendar read well under the Cloud Run request deadline instead of eating up
# to 60s of it (observed recurring in production 2026-08-01..03 as
# `TimeoutError: The read operation timed out` from httplib2/ssl during
# calendar gather).
_GOOGLE_API_TIMEOUT_ENV = "GOOGLE_API_TIMEOUT_SECONDS"
_GOOGLE_API_TIMEOUT_DEFAULT = "30"


# Calendar is the only retained Google OAuth capability. Any cached token that
# carries a different grant is intentionally discarded so Google re-consent is
# required instead of silently preserving broader historical access.
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


def required_google_scopes() -> list[str]:
    """Return the fixed least-privilege scope set for the retained runtime."""
    return [CALENDAR_SCOPE]


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
        The runtime service account needs only `secretmanager.secretAccessor`.
        Version-adder and version-manager permissions belong to the operator
        identity used for explicit reauthorization, never to Cloud Run.

    WHY immutable versions:
        Secret Manager versions are immutable — you can never overwrite a
        version's payload. An explicit reauthorization therefore creates a new
        version, and `load` resolves `latest` to that operator-approved grant.
        Ordinary one-hour access-token renewals stay in process memory and do
        not call `save`. After an explicit write, Klaus keeps the newest working
        version plus one rollback version. Older enabled versions are disabled;
        versions already disabled by an earlier write are destroyed.
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
            Secret Manager versions are immutable by design. This method is
            reserved for a new consent grant, not ordinary access-token
            renewal. `load` resolves `latest` to the newest approved grant.
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
        try:
            self._prune_versions(client, parent)
        except Exception:
            # WHY: a refreshed access token is already durably persisted. IAM
            # drift in retention must be visible, but it must not make the
            # Calendar call fail or tempt the caller to re-run token refresh.
            logger.warning(
                "OAuth token retention cleanup failed for secret '%s'; "
                "the newly saved token remains usable.",
                self.secret_name,
                exc_info=True,
            )

    @staticmethod
    def _prune_versions(client: Any, parent: str) -> None:
        """Keep latest+rollback using separate disable and destroy phases."""
        from core.secret_retention import apply_plan, plan_for_client

        # Destruction is limited to versions observed as DISABLED before this
        # explicit write. A version disabled below therefore survives until a
        # later operator cleanup, while the two newest usable grants remain.
        plan = plan_for_client(
            client,
            parent,
            keep_count=2,
            destroy_grace_days=0,
        )
        apply_plan(client, parent, plan)


# ------------------------------------------------------------------ #
# Auth manager                                                       #
# ------------------------------------------------------------------ #

class GoogleAuthManager:
    """Manages a single Calendar OAuth credential.

    Delegates all token persistence to an injected `TokenStorage` backend,
    which makes the manager storage-agnostic and independently testable.

    Lifecycle:
        1. First call to `get_credentials()` runs the browser consent flow
           and persists the token via the storage backend.
        2. Subsequent calls load the static refresh credential and silently
           renew short-lived access tokens in memory — no browser, no user
           interaction, and no storage rotation.
    """

    SCOPES: list[str] = [CALENDAR_SCOPE]

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
        self.scopes = required_google_scopes()
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
                    # WHY in-memory only: the stored refresh credential is the
                    # durable authorization. Google access tokens are temporary,
                    # and persisting each renewal to immutable Secret Manager
                    # creates a billable secret version every hour. A future
                    # process can load the same refresh credential and obtain
                    # its own access token without rotating storage.
                    creds.refresh(Request())
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

    def calendar_service(self) -> Any:
        """Return an authenticated Calendar v3 service resource."""
        return build("calendar", "v3", http=self._authorized_http(),
                     cache_discovery=False)

    def _authorized_http(self) -> AuthorizedHttp:
        """Build an authenticated http client with an explicit socket timeout.

        WHY `http=` instead of `credentials=`: `build()` builds an equivalent
        `AuthorizedHttp(credentials, http=httplib2.Http())` internally when
        given `credentials=`, but that inner `httplib2.Http()` only gets a
        timeout via googleapiclient's own (undocumented-to-us) default. Doing
        it ourselves makes the timeout explicit, env-configurable, and
        consistent with `LLM_TIMEOUT_SECONDS` (CLAUDE.md invariant).
        """
        timeout = float(
            os.getenv(_GOOGLE_API_TIMEOUT_ENV, _GOOGLE_API_TIMEOUT_DEFAULT)
        )
        return AuthorizedHttp(
            self.get_credentials(), http=httplib2.Http(timeout=timeout)
        )

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
            credential_info = json.loads(payload)
            scopes = set(credential_info.get("scopes") or [])
            if scopes != set(self.scopes):
                logger.info("Cached Google token has retired scopes; re-consent is required.")
                return None
            return Credentials.from_authorized_user_info(credential_info, self.scopes)
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
            self.credentials_path, self.scopes
        )
        # port=0 → OS picks a free port. Avoids conflicts on shared dev machines.
        return flow.run_local_server(port=0)

    def _persist_token(self, creds: Credentials) -> None:
        """Persist a newly consented credential via the storage backend."""
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
    """Authenticate and list a bounded Calendar window. Exit code 0 on success."""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    manager = build_auth_manager_from_env()

    try:
        from datetime import datetime, timedelta, timezone
        calendar = manager.calendar_service()
        start = datetime.now(timezone.utc)
        result = calendar.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=(start + timedelta(days=1)).isoformat(),
            maxResults=1,
            singleEvents=True,
        ).execute()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except (GoogleAuthError, HttpError) as exc:
        logger.error("Google API rejected the request: %s", exc)
        return 3

    storage_backend = os.getenv("GOOGLE_TOKEN_STORAGE", "file")
    print(f"Calendar access verified; returned {len(result.get('items', []))} event(s).")
    print(f"Token storage backend: {storage_backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
