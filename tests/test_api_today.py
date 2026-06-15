"""Wave 0 test stubs for the read-only /api/today aggregator (plan 26-04).

WHY this module exists: Phase 26 (v5.0 Klaus Hub) adds GET /api/today — a
read-only aggregator that composes the Today timeline from existing tools and
Firestore stores behind the require_hub_session auth dependency (26-03). These
tests define the behavioral contract that plan 26-04 must satisfy. All test
functions are skip-marked until plan 26-04 implements the production code; at
that point 26-04 removes the skip markers and flips the stubs to real
assertions.

Pattern: mirrors tests/test_web_server.py (_stub_web_server_imports pattern,
CRON_DEV_BYPASS / TestClient) for routes that import the full web_server module.

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
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
}


# ------------------------------------------------------------------ #
# Wave 0 test stubs — skip-marked until plan 26-04 implements        #
# ------------------------------------------------------------------ #

@pytest.mark.skip(reason="implemented in Wave 1 plan 26-04")
def test_today_returns_expected_keys():
    """GET /api/today returns the documented timeline shape.

    Covers TIME-01..05: the aggregator response must contain the expected
    top-level keys (e.g. date, now, items[], coach_note) so the frontend
    TimelineDay (26-07) can render without defensive key-guards.
    """
    raise NotImplementedError("implement in plan 26-04")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-04")
def test_no_datetimewithnanoseconds_leak():
    """No Firestore DatetimeWithNanoseconds leaks into the JSON response.

    Covers the firestore-timestamp JSON invariant: every timestamp read from a
    Firestore store must be ISO-converted server-side. json.dumps over the
    /api/today payload must not raise on a DatetimeWithNanoseconds value.
    """
    raise NotImplementedError("implement in plan 26-04")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-04")
def test_meal_slot_time_not_eating_time():
    """Meal items expose the canonical slot time, never an inferred eating time.

    Covers the Lifesum slot-time invariant (CLAUDE.md): HealthKit/Lifesum meal
    timestamps are canonical slot times (08:00/12:00/20:00) — /api/today must
    surface the slot time and never infer an actual eating time from them.
    """
    raise NotImplementedError("implement in plan 26-04")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-04")
def test_unauthenticated_returns_401():
    """GET /api/today without a valid hub session → 401.

    Covers HUB-01: /api/today depends on require_hub_session (26-03); a request
    with no/invalid hub_session cookie must return HTTPException(status_code=401).
    """
    raise NotImplementedError("implement in plan 26-04")
