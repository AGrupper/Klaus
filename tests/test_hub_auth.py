"""Wave 0 test stubs for interfaces/hub_auth.py — session cookie + GIS verify + allowlist.

WHY this module exists: Phase 26 (v5.0 Klaus Hub) adds Google Sign-In session auth
(HUB-01) implemented in interfaces/hub_auth.py. These tests define the behavioral
contract that plan 26-03 must satisfy. All test functions are skip-marked until
plan 26-03 implements the production code; at that point 26-03 removes the skip
markers and flips the stubs to real assertions.

Pattern: mirrors tests/test_task_dispatch.py (_ENV dict, fake_tasks_v2 fixture) and
tests/test_web_server.py (_stub_web_server_imports pattern, CRON_DEV_BYPASS).

Seeded by plan 26-02 Task 3 per RESEARCH.md § Validation Architecture.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------ #
# Shared test environment                                            #
# ------------------------------------------------------------------ #

_ENV = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    "CRON_DEV_BYPASS": "true",
    # Required for hub_auth to load without errors
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
}


# ------------------------------------------------------------------ #
# Wave 0 test stubs — skip-marked until plan 26-03 implements        #
# ------------------------------------------------------------------ #

@pytest.mark.skip(reason="implemented in Wave 1 plan 26-03")
def test_valid_gis_token_issues_cookie():
    """A valid GIS ID token from Amit's account → signed session cookie issued.

    Covers HUB-01: `create_session_cookie` + `verify_session_cookie` round-trip:
    - sign a payload with session_version=0
    - unsign and assert email + version recovered correctly
    - assert cookie attributes: httpOnly=True, Secure=True, SameSite='strict'
    """
    raise NotImplementedError("implement in plan 26-03")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-03")
def test_allowlist_rejects_other_email():
    """A valid GIS token from a non-Amit email → 403.

    Covers HUB-01 allowlist: `verify_session_cookie` with an email that does not
    match HUB_ALLOWED_EMAIL must raise HTTPException(status_code=403).
    """
    raise NotImplementedError("implement in plan 26-03")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-03")
def test_no_cookie_401():
    """A request with no `hub_session` cookie → `require_hub_session` raises 401.

    Covers HUB-01: the FastAPI dependency `require_hub_session` must raise
    HTTPException(status_code=401) when the cookie is absent.
    """
    raise NotImplementedError("implement in plan 26-03")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-03")
def test_revoked_session():
    """After session_version is bumped, an old cookie is rejected.

    Covers D-02 sign-out-everywhere: a cookie signed with session_version=0
    must be rejected when the current session_version is 1 (after revoke-all).
    """
    raise NotImplementedError("implement in plan 26-03")
