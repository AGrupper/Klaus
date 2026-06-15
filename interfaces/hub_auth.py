"""Hub authentication for Klaus — Google Sign-In → signed session cookie.

This module implements the authentication boundary for the Klaus Hub (v5.0):

  1. `verify_google_id_token`  — one-time server-side GIS ID-token verification.
  2. `create_session_cookie`   — issue an itsdangerous HMAC-SHA256-signed cookie.
  3. `verify_session_cookie`   — validate a cookie on every /api/* request.
  4. `get_session_version`     — read the revocation counter from UserProfileStore.
  5. `require_hub_session`     — FastAPI Depends() used on every /api/* route.

Security controls implemented here (RESEARCH.md STRIDE register):
  T-26-03-01 — verify_oauth2_token validates GIS signature + exp + audience.
  T-26-03-02 — allowlist check in BOTH verify_google_id_token AND verify_session_cookie.
  T-26-03-03 — httpOnly=True on the cookie; cookie value never logged in full.
  T-26-03-04 — samesite="strict" primary CSRF control (same-origin architecture).
  T-26-03-05 — session_version counter; /api/auth/revoke-all bumps it (D-02).
  T-26-03-06 — itsdangerous TimestampSigner HMAC-SHA256; tamper → BadSignature.
  T-26-03-07 — refuse-all-on-unset-env for HUB_SESSION_SECRET (Shared Pattern 7).
  T-26-03-08 — require_hub_session is a NEW dependency on /api/* only; existing
               OIDC on /cron/* and /internal/* is untouched (HUB-04).

Analog: _verify_healthkit_request in interfaces/web_server.py (same refuse-all-on-unset-env,
hmac.compare_digest, redacted logging, CRON_DEV_BYPASS bypass shape).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Module-level constants (read at import time)                        #
# ------------------------------------------------------------------ #

_ALLOWED_EMAIL = os.environ.get("HUB_ALLOWED_EMAIL", "amit.grupper@gmail.com")
_SESSION_MAX_AGE_DAYS = 365  # "effectively permanent" per D-01
_COOKIE_NAME = "hub_session"


def _get_signer() -> TimestampSigner:
    """Return a TimestampSigner backed by HUB_SESSION_SECRET.

    WHY lazy function (not module constant): module-level `os.environ[...]`
    would raise KeyError on import when the env var is absent, breaking
    /healthz cold-start. The lazy call lets /healthz succeed; any actual
    auth operation raises 500 "Server misconfigured" instead (Shared Pattern 7).

    WHY digest_method=hashlib.sha256: ASVS V6 prefers SHA-256 over the
    itsdangerous default (SHA-1). Explicitly set to future-proof.
    """
    secret = os.environ.get("HUB_SESSION_SECRET", "")
    if not secret:
        # WHY refuse-all: an empty secret would sign cookies with an empty key,
        # making every string a valid signed value — completely fail-open.
        # Surfaces as 500 so the operator can detect the misconfiguration.
        logger.error("HUB_SESSION_SECRET env unset — refusing all hub auth")
        raise HTTPException(
            status_code=500,
            detail={"error": "Server misconfigured"},
        )
    return TimestampSigner(secret, digest_method=hashlib.sha256)


# ------------------------------------------------------------------ #
# Cookie sign / verify                                               #
# ------------------------------------------------------------------ #

def create_session_cookie(email: str, session_version: int) -> str:
    """Sign 'email:session_version' with a timestamp.

    Returns a URL-safe string suitable for a Set-Cookie header value.
    The payload is `email:session_version` — splitting on the last `:` via
    rsplit(":", 1) in verify_session_cookie handles emails with `+` or dots.

    Raises:
        HTTPException 500: HUB_SESSION_SECRET is unset.
    """
    signer = _get_signer()
    payload = f"{email}:{session_version}"
    return signer.sign(payload).decode("utf-8")


def verify_session_cookie(cookie_value: str, current_version: int) -> str:
    """Verify and return the email from a signed session cookie.

    Args:
        cookie_value:    The raw cookie string from the request.
        current_version: The current session_version from UserProfileStore
                         (used to detect D-02 sign-out-everywhere revocations).

    Returns:
        The verified email address (always `_ALLOWED_EMAIL` for valid cookies).

    Raises:
        HTTPException 401: Cookie absent, malformed, expired, or version mismatch.
        HTTPException 403: Email present but not in the allowlist.
        HTTPException 500: HUB_SESSION_SECRET is unset.

    Security: this function is called on EVERY /api/* request, so it must not
    log the raw cookie value. Any log lines use a redacted prefix only.
    """
    signer = _get_signer()
    try:
        payload_bytes = signer.unsign(
            cookie_value,
            max_age=int(_SESSION_MAX_AGE_DAYS * 86400),
        )
        payload = payload_bytes.decode("utf-8")
        email, stored_version_str = payload.rsplit(":", 1)
    except (SignatureExpired, BadSignature, ValueError):
        # Redacted log — never write the raw cookie to logs.
        redacted = (
            cookie_value[:4] + "..." + cookie_value[-4:]
            if len(cookie_value) >= 8
            else "***"
        )
        logger.warning(
            "hub session verification failed (cookie_prefix=%s)", redacted
        )
        raise HTTPException(
            status_code=401,
            detail={"error": "Session expired or invalid"},
        )

    # D-02: sign-out-everywhere — a bumped session_version invalidates every
    # previously-issued cookie even if the HMAC signature is still valid.
    try:
        stored_version = int(stored_version_str)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"error": "Session expired or invalid"},
        )

    if stored_version != current_version:
        raise HTTPException(
            status_code=401,
            detail={"error": "Session revoked"},
        )

    # T-26-03-02: allowlist check on EVERY request (not only at sign-in).
    # WHY hmac.compare_digest: prevents timing-side-channel leaks even for
    # an allowlist of one email.
    if not hmac.compare_digest(email.encode(), _ALLOWED_EMAIL.encode()):
        logger.warning(
            "hub session: forbidden email (email is redacted from logs)"
        )
        raise HTTPException(
            status_code=403,
            detail={"error": "Forbidden"},
        )

    return email


# ------------------------------------------------------------------ #
# Session version (D-02 revocation counter)                          #
# ------------------------------------------------------------------ #

def get_session_version() -> int:
    """Read the current session_version from UserProfileStore.

    Returns 0 if the field is absent or the store is unreachable — matches the
    _SCAFFOLD default so a freshly-bootstrapped profile does not break auth.

    WHY synchronous: this function is called from require_hub_session which runs
    inside asyncio; the caller must wrap this in run_in_executor when called from
    an async context (same pattern as /cron/* routes). For the FastAPI dependency
    the call is lightweight and the event loop is not the bottleneck on auth.
    """
    try:
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if not project_id:
            return 0
        from memory.firestore_db import UserProfileStore  # lazy import
        store = UserProfileStore(project_id=project_id, database=database)
        profile = store.load()
        return int(profile.get("session_version", 0))
    except Exception:
        logger.warning("get_session_version() failed — defaulting to 0", exc_info=True)
        return 0


# ------------------------------------------------------------------ #
# Google ID token verification (sign-in only)                        #
# ------------------------------------------------------------------ #

def verify_google_id_token(token: str) -> str:
    """Verify a Google Identity Services ID token and return the verified email.

    Called ONCE at sign-in (/api/auth/google). Subsequent requests use
    require_hub_session (cookie-based) — GIS verification does not happen
    on every request.

    Source: https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

    Args:
        token: The GIS ID token from the frontend credential callback.

    Returns:
        The verified email address.

    Raises:
        HTTPException 401: Token invalid, expired, or email not verified by Google.
        HTTPException 403: Token valid but email is not the allowlisted address.
        HTTPException 500: GOOGLE_OAUTH_CLIENT_ID or HUB_SESSION_SECRET is unset.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    if not client_id:
        logger.error("GOOGLE_OAUTH_CLIENT_ID env unset — refusing GIS verification")
        raise HTTPException(
            status_code=500,
            detail={"error": "Server misconfigured"},
        )

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        idinfo = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            client_id,
        )
    except Exception as exc:
        logger.warning("GIS ID token verification failed: %s", exc)
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid or expired Google ID token"},
        )

    if not idinfo.get("email_verified"):
        raise HTTPException(
            status_code=401,
            detail={"error": "Google account email is not verified"},
        )

    email = idinfo.get("email", "")

    # T-26-03-02: allowlist check at sign-in time.
    if not hmac.compare_digest(email.encode(), _ALLOWED_EMAIL.encode()):
        logger.warning(
            "GIS sign-in rejected: email is not the allowlisted account "
            "(email redacted from logs)"
        )
        raise HTTPException(
            status_code=403,
            detail={"error": "Not authorized"},
        )

    return email


# ------------------------------------------------------------------ #
# FastAPI dependency                                                  #
# ------------------------------------------------------------------ #

async def require_hub_session(request: Request) -> str:
    """FastAPI Depends() for every /api/* route — verifies the session cookie.

    Usage:
        @app.get("/api/some-route")
        async def handler(_email: str = Depends(require_hub_session)) -> ...:
            ...

    Returns:
        The verified email address (always _ALLOWED_EMAIL for valid sessions).

    Raises:
        HTTPException 401: Cookie absent or invalid.
        HTTPException 403: Cookie valid but email not allowlisted.
        HTTPException 500: HUB_SESSION_SECRET unset.
    """
    # Shared Pattern 8: CRON_DEV_BYPASS — skip auth in local dev.
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        logger.info("CRON_DEV_BYPASS=true — bypassing hub session check")
        return _ALLOWED_EMAIL

    cookie_value = request.cookies.get(_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(
            status_code=401,
            detail={"error": "Not authenticated"},
        )

    current_version = get_session_version()
    return verify_session_cookie(cookie_value, current_version)
