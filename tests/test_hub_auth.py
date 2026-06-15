"""Tests for interfaces/hub_auth.py — session cookie + GIS verify + allowlist.

WHY this module exists: Phase 26 (v5.0 Klaus Hub) adds Google Sign-In session auth
(HUB-01) implemented in interfaces/hub_auth.py. These tests define the behavioral
contract satisfied by plan 26-03 (Wave 1).

Pattern: mirrors tests/test_task_dispatch.py (_ENV dict, fake_tasks_v2 fixture) and
tests/test_web_server.py (_stub_web_server_imports pattern, CRON_DEV_BYPASS).

Seeded by plan 26-02 Task 3; implemented by plan 26-03 Task 3.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


# ------------------------------------------------------------------ #
# Shared test environment                                            #
# ------------------------------------------------------------------ #

_ENV = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    # Required for hub_auth to load without Firestore errors
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
}


def _fresh_hub_auth(monkeypatch):
    """Import hub_auth with test env vars set, bypassing any cached import."""
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)
    # Disable the dev bypass so real auth paths are exercised in all tests that
    # call this helper — test_no_cookie_401 overrides this individually.
    monkeypatch.setenv("CRON_DEV_BYPASS", "false")
    # Force reimport so env vars take effect on module-level reads
    for mod in list(sys.modules.keys()):
        if mod == "interfaces.hub_auth" or mod.startswith("interfaces.hub_auth."):
            del sys.modules[mod]
    import interfaces.hub_auth as hub_auth
    return hub_auth


# ------------------------------------------------------------------ #
# Tests                                                              #
# ------------------------------------------------------------------ #

def test_valid_gis_token_issues_cookie(monkeypatch):
    """A valid GIS ID token from Amit's account → signed session cookie issued.

    Covers HUB-01: `create_session_cookie` + `verify_session_cookie` round-trip:
    - sign a payload with session_version=0
    - unsign and assert email + version recovered correctly
    """
    hub_auth = _fresh_hub_auth(monkeypatch)

    email = "amit.grupper@gmail.com"
    session_version = 0

    cookie = hub_auth.create_session_cookie(email, session_version)

    # Cookie is a non-empty string
    assert isinstance(cookie, str)
    assert len(cookie) > 0

    # Round-trip: verify_session_cookie should return the original email
    result_email = hub_auth.verify_session_cookie(cookie, session_version)
    assert result_email == email


def test_allowlist_rejects_other_email(monkeypatch):
    """A valid GIS token from a non-Amit email → 403.

    Covers HUB-01 allowlist: `verify_session_cookie` with an email that does not
    match HUB_ALLOWED_EMAIL must raise HTTPException(status_code=403).
    """
    hub_auth = _fresh_hub_auth(monkeypatch)

    # Sign a cookie with a non-allowlisted email
    other_email = "other@example.com"
    cookie = hub_auth.create_session_cookie(other_email, 0)

    with pytest.raises(HTTPException) as exc_info:
        hub_auth.verify_session_cookie(cookie, 0)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "Forbidden"}


def test_no_cookie_401(monkeypatch):
    """A request with no `hub_session` cookie → `require_hub_session` raises 401.

    Covers HUB-01: the FastAPI dependency `require_hub_session` must raise
    HTTPException(status_code=401) when the cookie is absent and CRON_DEV_BYPASS
    is not set.
    """
    # Set env vars BEFORE any import so hub_auth reads the correct values
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CRON_DEV_BYPASS", "false")

    # Force fresh import with correct env vars
    for mod in list(sys.modules.keys()):
        if mod == "interfaces.hub_auth" or mod.startswith("interfaces.hub_auth."):
            del sys.modules[mod]
    import interfaces.hub_auth as hub_auth

    # Build a minimal mock request with no cookies
    mock_request = MagicMock()
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(hub_auth.require_hub_session(mock_request))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == {"error": "Not authenticated"}


def test_revoked_session(monkeypatch):
    """After session_version is bumped, an old cookie is rejected.

    Covers D-02 sign-out-everywhere: a cookie signed with session_version=0
    must be rejected when the current session_version is 1 (after revoke-all).
    """
    hub_auth = _fresh_hub_auth(monkeypatch)

    email = "amit.grupper@gmail.com"

    # Issue a cookie with the OLD session_version (0)
    old_cookie = hub_auth.create_session_cookie(email, session_version=0)

    # Verify against the NEW session_version (1) — should fail
    with pytest.raises(HTTPException) as exc_info:
        hub_auth.verify_session_cookie(old_cookie, current_version=1)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == {"error": "Session revoked"}
