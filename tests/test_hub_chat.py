"""Tests for the hub chat backend (plan 26-05).

The hub chat path runs the agent turn exactly like Telegram — POST /api/chat
appends the user message to the shared FirestoreConversationStore (keyed on
telegram_user_id, CHAT-01) and enqueues a Cloud Tasks job to the full-CPU
/internal/process-hub-message worker (CHAT-02 / D-09), which is OIDC-gated
(CHAT-04). GET /api/chat/messages returns the polling window (CHAT-03).

Pattern: mirrors tests/test_web_server.py (_stub_web_server_imports + TestClient,
CRON_DEV_BYPASS OIDC gating). Auth (require_hub_session) is bypassed via FastAPI
dependency_overrides; the conversation store + enqueue are mocked at their
import boundaries.

Implemented by plan 26-05 (Wave-0 skip stubs flipped to real assertions).
"""
from __future__ import annotations

import os
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
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _stub_web_server_imports() -> dict:
    """Return a sys.modules-stubs dict that lets interfaces.web_server import
    without real telegram / google-auth / core.main dependencies, and flush the
    cached web_server so the next import picks up the stubs.
    """
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs


# ------------------------------------------------------------------ #
# CHAT-01: POST /api/chat appends to the shared Firestore conversation #
# ------------------------------------------------------------------ #

def test_post_chat_appends_to_firestore():
    """POST /api/chat appends the user message to the shared Firestore conversation."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=True):
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "hello klaus"})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    assert resp.json() == {"ok": True}
    # CHAT-01: append(user_id, "user", content) on the shared conversation store
    fake_store_cls.return_value.append.assert_called_once_with(123456, "user", "hello klaus")


# ------------------------------------------------------------------ #
# CHAT-02: POST /api/chat enqueues the full-CPU agent turn            #
# ------------------------------------------------------------------ #

def test_post_chat_enqueues_hub_message():
    """POST /api/chat enqueues the agent turn via Cloud Tasks (never a BackgroundTask)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch("memory.firestore_conversation.FirestoreConversationStore", MagicMock()), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=True) as mock_enqueue:
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "hello klaus"})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    mock_enqueue.assert_called_once_with("hello klaus", 123456)


def test_post_chat_rejects_empty_content():
    """POST /api/chat with empty content → 400 (input validation, T-26-05-04)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            client = TestClient(ws.app)
            resp = client.post("/api/chat", json={"content": "   "})

    assert resp.status_code == 400


# ------------------------------------------------------------------ #
# CHAT-03: GET /api/chat/messages returns the polling window         #
# ------------------------------------------------------------------ #

def test_get_messages_returns_window():
    """GET /api/chat/messages returns the conversation window with stable seq indices."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get.return_value = [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello, Amit"},
            ]
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages")

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    messages = resp.json()["messages"]
    assert messages == [
        {"seq": 0, "role": "user", "content": "hi"},
        {"seq": 1, "role": "assistant", "content": "hello, Amit"},
    ]


# ------------------------------------------------------------------ #
# CHAT-04: /internal/process-hub-message is OIDC-gated               #
# ------------------------------------------------------------------ #

def test_internal_process_hub_message_oidc_gated(monkeypatch):
    """/internal/process-hub-message rejects callers without a valid OIDC bearer."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        env = dict(_ENV)
        env["CRON_DEV_BYPASS"] = "false"  # force real OIDC verification
        with patch.dict(os.environ, env):
            monkeypatch.delenv("CLOUD_RUN_URL", raising=False)
            monkeypatch.delenv("CLOUD_SCHEDULER_SA_EMAIL", raising=False)
            client = TestClient(ws.app)
            resp = client.post(
                "/internal/process-hub-message",
                json={"content": "hi", "user_id": 123456},
            )

    assert resp.status_code in (401, 403), f"expected 401/403, got {resp.status_code}: {resp.text}"
