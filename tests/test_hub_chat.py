"""Wave 0 test stubs for the hub chat backend (plan 26-05).

WHY this module exists: Phase 26 (v5.0 Klaus Hub) adds a dedicated Cloud Tasks
full-CPU path so hub chat messages run the agent turn exactly like Telegram,
sharing one continuous Firestore conversation (one Klaus). These tests define the
behavioral contract that plan 26-05 must satisfy. All test functions are
skip-marked until plan 26-05 implements the production code; at that point 26-05
removes the skip markers and flips the stubs to real assertions.

Pattern: mirrors tests/test_task_dispatch.py (fake_tasks_v2 fixture — a mocked
Cloud Tasks v2 client) and tests/test_web_server.py (_stub_web_server_imports,
CRON_DEV_BYPASS OIDC gating).

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
    "CLOUD_TASKS_QUEUE": "klaus-updates",
    "CLOUD_TASKS_LOCATION": "me-central1",
}


@pytest.fixture
def fake_tasks_v2():
    """Mocked Cloud Tasks v2 client — mirrors tests/test_task_dispatch.py.

    Plan 26-05 fills this in to assert the hub message is enqueued onto the
    full-CPU /internal/process-hub-message path (never run inline in the
    request handler — Cloud Run throttles CPU once no request is in flight).
    """
    return MagicMock()


# ------------------------------------------------------------------ #
# Wave 0 test stubs — skip-marked until plan 26-05 implements        #
# ------------------------------------------------------------------ #

@pytest.mark.skip(reason="implemented in Wave 1 plan 26-05")
def test_post_chat_appends_to_firestore():
    """POST /api/chat appends the user message to the shared Firestore conversation.

    Covers CHAT-01: the hub keys FirestoreConversationStore on telegram_user_id
    (26-02 bridge field) so hub + Telegram share one continuous conversation.
    """
    raise NotImplementedError("implement in plan 26-05")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-05")
def test_post_chat_enqueues_hub_message():
    """POST /api/chat enqueues a Cloud Tasks job for the full-CPU agent turn.

    Covers CHAT-02 + the full-CPU invariant: the agent turn must run inside a
    tracked Cloud Tasks request, never in a Starlette BackgroundTask.
    """
    raise NotImplementedError("implement in plan 26-05")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-05")
def test_get_messages_returns_window():
    """GET /api/messages returns the recent conversation window for polling.

    Covers CHAT-03: the frontend useChat hook (26-08) polls this for new
    assistant turns; the response is the trailing window of the shared thread.
    """
    raise NotImplementedError("implement in plan 26-05")


@pytest.mark.skip(reason="implemented in Wave 1 plan 26-05")
def test_internal_process_hub_message_oidc_gated():
    """/internal/process-hub-message rejects non-OIDC callers.

    Covers CHAT-04: the internal full-CPU worker route must be OIDC-protected
    exactly like /internal/process-update (CRON_DEV_BYPASS only in dev).
    """
    raise NotImplementedError("implement in plan 26-05")
