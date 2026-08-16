"""Hub sign-in, sign-out and session identity.

Sign-in verifies a Google ID token and mints Klaus's own signed session cookie;
the Google credential is never stored. Revoke-all bumps a server-side session
version so every existing cookie stops validating at once — the recovery path
for a lost device.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/auth/google")
async def api_auth_google(request: Request) -> JSONResponse:
    """Exchange a Google Identity Services ID token for a session cookie.

    Accepts JSON body: {"credential": "<GIS ID token>"}

    The GIS token is verified server-side via verify_oauth2_token (audience =
    GOOGLE_OAUTH_CLIENT_ID). On success, issues an itsdangerous HMAC-SHA256-signed
    httpOnly session cookie valid for 365 days (D-01 effectively permanent).

    Raises:
        HTTPException 401: Invalid or expired GIS token, or email not verified.
        HTTPException 403: Token valid but email is not the allowlisted account.
        HTTPException 500: GOOGLE_OAUTH_CLIENT_ID or HUB_SESSION_SECRET unset.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    body = await request.json()
    credential = body.get("credential", "")
    if not credential:
        raise HTTPException(
            status_code=400,
            detail={"error": "Missing 'credential' in request body"},
        )

    email = _hub_auth.verify_google_id_token(credential)
    loop = asyncio.get_running_loop()
    session_version = await loop.run_in_executor(None, _hub_auth.get_session_version)
    cookie_value = _hub_auth.create_session_cookie(email, session_version)

    # The Set-Cookie MUST go on the response object we actually return. Setting it
    # on a separate injected `response: Response` and then returning a new
    # JSONResponse silently drops the header — FastAPI does not merge the two — so
    # the browser never stores the cookie and every subsequent /api/* call 401s.
    json_response = JSONResponse(content={"ok": True, "email": email})
    json_response.set_cookie(
        _hub_auth._COOKIE_NAME,
        cookie_value,
        max_age=365 * 86400,
        httponly=True,
        secure=True,
        # OAuth begins as a cross-site top-level GET from Claude. Lax permits
        # that safe navigation but still withholds the cookie on cross-site
        # POST mutations; OAuth state + PKCE bind the authorization response.
        samesite="lax",
        path="/",
    )
    return json_response


@router.post("/api/auth/logout")
async def api_auth_logout() -> JSONResponse:
    """Clear the session cookie (single-device sign-out, D-02).

    Does not bump session_version — only removes the cookie on this device.
    For sign-out-everywhere use /api/auth/revoke-all.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    # delete_cookie must be on the returned response (see api_auth_google).
    json_response = JSONResponse(content={"ok": True})
    json_response.delete_cookie(_hub_auth._COOKIE_NAME, path="/")
    return json_response


@router.post("/api/auth/revoke-all")
async def api_auth_revoke_all(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Bump session_version to invalidate every previously-issued cookie (D-02).

    Also clears the cookie on the current device. After this call every existing
    session cookie (on every device) will fail the version check and return 401.

    Requires an active session cookie via Depends(require_hub_session).
    Declared as a dependency rather than called in the body so the gate is
    visible to route introspection — an in-body call is equally secure but
    invisible to the test that proves no /api route is left unguarded.
    Intended for "lost phone" scenarios.

    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 500: HUB_SESSION_SECRET or Firestore unavailable.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    loop = asyncio.get_running_loop()

    def _bump_version() -> None:
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if not project_id:
            raise ValueError("GCP_PROJECT_ID unset")
        from memory.firestore_db import UserProfileStore
        store = UserProfileStore(project_id=project_id, database=database)
        profile = store.load()
        new_version = int(profile.get("session_version", 0)) + 1
        store.update({"session_version": new_version})

    await loop.run_in_executor(None, _bump_version)
    # delete_cookie must be on the returned response (see api_auth_google).
    json_response = JSONResponse(content={"ok": True})
    json_response.delete_cookie(_hub_auth._COOKIE_NAME, path="/")
    return json_response


@router.get("/api/auth/me")
async def api_auth_me(request: Request) -> JSONResponse:
    """Return the signed-in email — used by the frontend to check session validity.

    Returns {"email": "..."} with HTTP 200 if the session cookie is valid.
    Returns HTTP 401 if no valid cookie is present.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    email: str = await _hub_auth.require_hub_session(request)
    return JSONResponse(content={"email": email})
