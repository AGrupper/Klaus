"""TickTick OAuth 2.0 token management.

Mirrors the TokenStorage protocol pattern from core/auth_google.py.
Tokens are stored as {"access_token": str, "refresh_token": str}.

Token storage is pluggable via TICKTICK_TOKEN_STORAGE:
  "file"           — config/ticktick_tokens.json (local dev).
  "secret_manager" — two Secret Manager secrets: TICKTICK_ACCESS_TOKEN and
                     TICKTICK_REFRESH_TOKEN (Cloud Run).

Run the one-time OAuth bootstrap to obtain tokens:
    python scripts/ticktick_oauth_bootstrap.py
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Protocol, runtime_checkable

import requests

logger = logging.getLogger(__name__)

_TICKTICK_TOKEN_URL = "https://ticktick.com/oauth/token"

# In-process cache: {"access_token": str, "refresh_token": str}
# Populated on first get_valid_access_token() call; updated on refresh.
_token_cache: dict | None = None


# ------------------------------------------------------------------ #
# Storage protocol + backends                                        #
# ------------------------------------------------------------------ #

@runtime_checkable
class TickTickTokenStore(Protocol):
    def load(self) -> dict | None:
        """Return {"access_token": ..., "refresh_token": ...} or None."""
        ...

    def save(self, tokens: dict) -> None:
        """Persist the token dict."""
        ...


class FileTickTickTokenStore:
    """Stores tokens as JSON on disk. Suitable for local dev."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> dict | None:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            logger.warning("ticktick_auth: token file %s is unreadable; treating as absent", self.path)
            return None

    def save(self, tokens: dict) -> None:
        import pathlib
        pathlib.Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(tokens, fh)
        logger.debug("ticktick_auth: tokens saved to %s", self.path)


class SecretManagerTickTickTokenStore:
    """Stores access_token and refresh_token in separate GCP Secret Manager secrets.

    IAM requirement:
        The runtime service account needs secretmanager.secretVersionAdder
        on both secrets to write refreshed tokens.
    """

    def __init__(self, project_id: str,
                 access_token_secret: str = "TICKTICK_ACCESS_TOKEN",
                 refresh_token_secret: str = "TICKTICK_REFRESH_TOKEN") -> None:
        self.project_id = project_id
        self.access_token_secret = access_token_secret
        self.refresh_token_secret = refresh_token_secret

    def _read_secret(self, secret_name: str) -> str | None:
        from google.cloud import secretmanager
        from google.api_core.exceptions import NotFound
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
        try:
            resp = client.access_secret_version(request={"name": name})
            return resp.payload.data.decode("utf-8").strip()
        except NotFound:
            logger.info("ticktick_auth: secret '%s' has no versions yet.", secret_name)
            return None

    def _write_secret(self, secret_name: str, value: str) -> None:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{self.project_id}/secrets/{secret_name}"
        client.add_secret_version(
            request={"parent": parent, "payload": {"data": value.encode("utf-8")}}
        )
        logger.debug("ticktick_auth: added new version of secret '%s'.", secret_name)

    def load(self) -> dict | None:
        access = self._read_secret(self.access_token_secret)
        if not access:
            return None
        refresh = self._read_secret(self.refresh_token_secret) or ""
        # Treat placeholder "none" the same as empty — written when no refresh token
        # was returned by the initial OAuth flow.
        if refresh == "none":
            refresh = ""
        return {"access_token": access, "refresh_token": refresh}

    def save(self, tokens: dict) -> None:
        if "access_token" in tokens:
            self._write_secret(self.access_token_secret, tokens["access_token"])
        if "refresh_token" in tokens:
            self._write_secret(self.refresh_token_secret, tokens["refresh_token"])


def build_token_store_from_env() -> TickTickTokenStore:
    """Construct the token store configured in env vars.

    TICKTICK_TOKEN_STORAGE values:
        "file"           → FileTickTickTokenStore at TICKTICK_TOKEN_PATH
                           (default: "./config/ticktick_tokens.json").
        "secret_manager" → SecretManagerTickTickTokenStore using GCP_PROJECT_ID
                           and optional TICKTICK_ACCESS_TOKEN_SECRET /
                           TICKTICK_REFRESH_TOKEN_SECRET names.
    """
    backend = os.getenv("TICKTICK_TOKEN_STORAGE", "file")
    if backend == "file":
        path = os.getenv("TICKTICK_TOKEN_PATH", "./config/ticktick_tokens.json")
        return FileTickTickTokenStore(path=path)
    elif backend == "secret_manager":
        project_id = os.environ["GCP_PROJECT_ID"]
        return SecretManagerTickTickTokenStore(
            project_id=project_id,
            access_token_secret=os.getenv("TICKTICK_ACCESS_TOKEN_SECRET", "TICKTICK_ACCESS_TOKEN"),
            refresh_token_secret=os.getenv("TICKTICK_REFRESH_TOKEN_SECRET", "TICKTICK_REFRESH_TOKEN"),
        )
    else:
        raise ValueError(
            f"Unknown TICKTICK_TOKEN_STORAGE value: {backend!r}. "
            "Expected 'file' or 'secret_manager'."
        )


# ------------------------------------------------------------------ #
# Token access + refresh                                             #
# ------------------------------------------------------------------ #

def _make_auth_header() -> str:
    client_id = os.environ["TICKTICK_CLIENT_ID"]
    client_secret = os.environ["TICKTICK_CLIENT_SECRET"]
    return "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()


def _do_refresh(refresh_token: str) -> dict:
    """Call TickTick's token endpoint and return fresh {"access_token", "refresh_token"}."""
    resp = requests.post(
        _TICKTICK_TOKEN_URL,
        headers={"Authorization": _make_auth_header()},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"Unexpected token response: {data}")
    return {
        "access_token": data["access_token"],
        # TickTick may or may not rotate the refresh token; preserve old one if absent.
        "refresh_token": data.get("refresh_token", refresh_token),
    }


def get_valid_access_token() -> str:
    """Return a valid TickTick access token, refreshing if needed.

    Flow:
      1. Return in-process cached token (avoids repeated storage reads).
      2. Load from storage backend if cache is empty.
      3. Refresh via TickTick OAuth if no usable token found.
      4. Persist refreshed tokens to storage.

    Raises:
        RuntimeError: If no tokens are available and refresh cannot proceed.
        requests.HTTPError: If the refresh request fails.
    """
    global _token_cache

    if _token_cache and _token_cache.get("access_token"):
        return _token_cache["access_token"]

    store = build_token_store_from_env()
    tokens = store.load()

    if not tokens:
        raise RuntimeError(
            "No TickTick tokens found. Run scripts/ticktick_oauth_bootstrap.py "
            "to obtain an initial token pair."
        )

    _token_cache = tokens
    return _token_cache["access_token"]


def refresh_and_persist() -> str:
    """Force a token refresh, persist the new tokens, and return the new access token.

    Call this when an API request returns 401 to silently recover.

    Raises:
        RuntimeError: If no refresh token is available.
        requests.HTTPError: If the refresh request fails.
    """
    global _token_cache

    store = build_token_store_from_env()
    tokens = _token_cache or store.load()
    if not tokens or not tokens.get("refresh_token"):
        raise RuntimeError(
            "No refresh token available. Re-run scripts/ticktick_oauth_bootstrap.py."
        )

    logger.info("ticktick_auth: access token expired; refreshing.")
    new_tokens = _do_refresh(tokens["refresh_token"])
    _token_cache = new_tokens

    try:
        store.save(new_tokens)
    except Exception:
        # WHY: failing to persist should not break the current request; the next
        # container restart will pick up a stale token and refresh again.
        logger.warning("ticktick_auth: failed to persist refreshed tokens", exc_info=True)

    return new_tokens["access_token"]
