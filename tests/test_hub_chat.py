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

def test_post_chat_does_not_append_directly():
    """POST /api/chat routes the user turn to the shared conversation via the worker.

    CHAT-01: the user turn lands in the shared FirestoreConversationStore — but the
    worker's handle_message is the SINGLE writer (it appends BOTH the user turn and
    the assistant reply, core/main.py). The route must NOT append directly: doing so
    double-wrote the user turn, and appending before a failed enqueue stranded a
    message with no agent turn (CR-03). The route's only effect is the enqueue.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=True) as mock_enqueue:
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "hello klaus"})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    assert resp.json() == {"ok": True}
    # The route must not write to the store — the worker's handle_message owns it.
    fake_store_cls.return_value.append.assert_not_called()
    mock_enqueue.assert_called_once_with("hello klaus", 123456)


def test_post_chat_failed_enqueue_persists_nothing():
    """On enqueue failure the route returns 503 and persists nothing (CR-03).

    No stranded user turn → no permanent 'Klaus is thinking…' and no double-send
    on retry.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=False):
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "hello klaus"})

    assert resp.status_code == 503, f"{resp.status_code}: {resp.text}"
    fake_store_cls.return_value.append.assert_not_called()


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
            # The hub poll reads the FULL continuous history (CR-02), not the
            # active-session window get() returns.
            fake_store_cls.return_value.get_full.return_value = [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello, Amit"},
            ]
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages")

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    body = resp.json()
    messages = body["messages"]
    assert messages == [
        {"seq": 0, "role": "user", "content": "hi"},
        {"seq": 1, "role": "assistant", "content": "hello, Amit"},
    ]
    assert body["has_more"] is False


# ------------------------------------------------------------------ #
# UAT gap-closure: GET /api/chat/messages windowing (limit/before)   #
# ------------------------------------------------------------------ #

def _make_stub_messages(n: int) -> list[dict]:
    """n synthetic messages alternating user/assistant, oldest first."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(n)
    ]


def test_get_messages_default_limit_returns_newest_50_with_has_more():
    """With no `before` cursor, the default limit=50 returns only the newest
    50 of a longer stored window and reports has_more=True (the whole point
    of server-side windowing — stop shipping full history on every poll).
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get_full.return_value = _make_stub_messages(80)
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages")

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    body = resp.json()
    messages = body["messages"]
    assert len(messages) == 50
    # Newest 50 of 80 → seqs 30..79
    assert messages[0]["seq"] == 30
    assert messages[-1]["seq"] == 79
    assert body["has_more"] is True


def test_get_messages_before_cursor_returns_older_page():
    """`before=<seq>&limit=<n>` returns the n messages immediately older than
    the cursor (the "scroll up → load earlier messages" page).
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get_full.return_value = _make_stub_messages(80)
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages", params={"before": 30, "limit": 20})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    body = resp.json()
    messages = body["messages"]
    assert len(messages) == 20
    assert messages[0]["seq"] == 10
    assert messages[-1]["seq"] == 29
    assert body["has_more"] is True


def test_get_messages_before_cursor_reaches_start_of_history():
    """When fewer than `limit` older messages remain, has_more is False —
    the client knows it's reached the true start of the conversation.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get_full.return_value = _make_stub_messages(80)
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages", params={"before": 10, "limit": 50})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    body = resp.json()
    messages = body["messages"]
    assert len(messages) == 10
    assert messages[0]["seq"] == 0
    assert messages[-1]["seq"] == 9
    assert body["has_more"] is False


def test_get_messages_chat_visible_and_windowing_params_compose():
    """`chat_visible=1` still marks visibility even when limit/before are
    also supplied — the two query params are independent (D-02 regression
    guard for the windowing gap-closure).
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get_full.return_value = _make_stub_messages(5)
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch("core.scheduled_message.mark_chat_visible") as mock_mark_visible:
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages", params={"chat_visible": 1, "limit": 10})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    mock_mark_visible.assert_called_once()


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


# ------------------------------------------------------------------ #
# Hub attachments — upload route + attachment-carrying send/worker   #
# ------------------------------------------------------------------ #

_FAKE_JPEG = b"\xff\xd8\xff\xe0fakejpeg"


def test_upload_route_saves_and_returns_metadata():
    """POST /api/chat/upload streams raw bytes to GCS via save_attachment and
    echoes the transport metadata the client will send back on /api/chat."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        meta = {"id": "a" * 32, "kind": "image", "mime": "image/jpeg",
                "name": "photo.jpg", "size": len(_FAKE_JPEG)}
        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch("core.hub_attachments.save_attachment", return_value=meta) as mock_save:
                client = TestClient(ws.app)
                resp = client.post(
                    "/api/chat/upload?filename=photo.jpg",
                    content=_FAKE_JPEG,
                    headers={"Content-Type": "image/jpeg"},
                )

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    assert resp.json() == meta
    mock_save.assert_called_once_with(_FAKE_JPEG, "image/jpeg", "photo.jpg")


def test_upload_route_rejects_bad_mime_with_400():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch("core.hub_attachments.save_attachment",
                       side_effect=ValueError("Unsupported attachment type")):
                client = TestClient(ws.app)
                resp = client.post(
                    "/api/chat/upload?filename=evil.exe",
                    content=b"MZ\x90\x00",
                    headers={"Content-Type": "application/x-msdownload"},
                )

    assert resp.status_code == 400


def test_upload_route_rejects_oversize_with_413():
    """Oversize bodies are rejected by length check before any GCS work."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from core.hub_attachments import MAX_ATTACHMENT_BYTES  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch("core.hub_attachments.save_attachment") as mock_save:
                client = TestClient(ws.app)
                resp = client.post(
                    "/api/chat/upload?filename=huge.jpg",
                    content=b"\xff\xd8\xff" + b"0" * (MAX_ATTACHMENT_BYTES + 1),
                    headers={"Content-Type": "image/jpeg"},
                )

    assert resp.status_code == 413
    mock_save.assert_not_called()


def test_post_chat_forwards_attachments_to_enqueue():
    """POST /api/chat with an attachments list passes it through to the Cloud
    Tasks payload (metadata only — bytes stay in GCS)."""
    stubs = _stub_web_server_imports()
    atts = [{"id": "b" * 32, "kind": "image", "mime": "image/jpeg",
             "name": "photo.jpg", "size": 123}]
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=True) as mock_enqueue:
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "look", "attachments": atts})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    mock_enqueue.assert_called_once_with("look", 123456, atts)


def test_post_chat_allows_empty_content_with_attachments():
    """Image-only sends are valid: empty content is fine when attachments exist."""
    stubs = _stub_web_server_imports()
    atts = [{"id": "c" * 32, "kind": "pdf", "mime": "application/pdf",
             "name": "doc.pdf", "size": 5}]
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=True):
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "", "attachments": atts})

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"


@pytest.mark.parametrize("bad_atts", [
    [{"id": "../../etc/passwd", "kind": "image"}],          # malformed id
    [{"id": "d" * 32, "kind": "script"}],                    # unknown kind
    [{"id": "e" * 32, "kind": "image"}] * 5,                 # too many (max 4)
    "not-a-list",                                            # wrong type
])
def test_post_chat_rejects_invalid_attachments(bad_atts):
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "enqueue_hub_message", return_value=True) as mock_enqueue:
                client = TestClient(ws.app)
                resp = client.post("/api/chat", json={"content": "x", "attachments": bad_atts})

    assert resp.status_code == 400, f"{resp.status_code}: {resp.text}"
    mock_enqueue.assert_not_called()


def test_internal_worker_downloads_attachments_and_forwards():
    """The Cloud Tasks worker re-downloads attachment bytes from GCS and hands
    InboundAttachment objects to handle_message for the single turn."""
    stubs = _stub_web_server_imports()
    # The worker lazily imports InboundAttachment from the (stubbed) core.main —
    # expose the real dataclass on the stub so the objects it builds are real.
    from core.main import InboundAttachment as _RealInboundAttachment
    stubs["core.main"].InboundAttachment = _RealInboundAttachment
    atts = [{"id": "f" * 32, "kind": "image", "mime": "image/jpeg",
             "name": "photo.jpg", "size": len(_FAKE_JPEG)}]
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        fake_orch = MagicMock()
        fake_orch.handle_message.return_value = "I see it."
        with patch.dict(os.environ, _ENV):
            with patch.object(ws, "_orchestrator", fake_orch), \
                 patch.object(ws, "_get_hub_stream_store", return_value=MagicMock()), \
                 patch("core.hub_attachments.load_attachment",
                       return_value=(_FAKE_JPEG, "image/jpeg", "photo.jpg")) as mock_load, \
                 patch("core.scheduled_message.send_and_inject", new=MagicMock()):
                client = TestClient(ws.app)
                resp = client.post(
                    "/internal/process-hub-message",
                    json={"content": "what's this?", "user_id": 123456,
                          "attachments": atts},
                )

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    mock_load.assert_called_once_with("f" * 32)
    args, kwargs = fake_orch.handle_message.call_args
    assert args[0] == "what's this?"
    assert args[1] == 123456
    passed = kwargs.get("attachments") or (args[2] if len(args) > 2 else None)
    assert passed is not None and len(passed) == 1
    att = passed[0]
    assert att.data == _FAKE_JPEG
    assert att.mime_type == "image/jpeg"
    assert att.kind == "image"


def test_internal_worker_drops_missing_attachment_but_runs_turn():
    """A lifecycle-expired GCS object must not fail the whole turn — the
    attachment is dropped and the text still reaches the agent."""
    stubs = _stub_web_server_imports()
    atts = [{"id": "a1" * 16, "kind": "image", "mime": "image/jpeg",
             "name": "gone.jpg", "size": 10}]
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        fake_orch = MagicMock()
        fake_orch.handle_message.return_value = "ok"
        with patch.dict(os.environ, _ENV):
            with patch.object(ws, "_orchestrator", fake_orch), \
                 patch.object(ws, "_get_hub_stream_store", return_value=MagicMock()), \
                 patch("core.hub_attachments.load_attachment",
                       side_effect=FileNotFoundError("gone")) as mock_load, \
                 patch("core.scheduled_message.send_and_inject", new=MagicMock()):
                client = TestClient(ws.app)
                resp = client.post(
                    "/internal/process-hub-message",
                    json={"content": "hi", "user_id": 123456, "attachments": atts},
                )

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    # The download was attempted (the worker consumed the attachments field)…
    mock_load.assert_called_once_with("a1" * 16)
    # …but the failed attachment was dropped and the text turn still ran.
    args, kwargs = fake_orch.handle_message.call_args
    passed = kwargs.get("attachments") or (args[2] if len(args) > 2 else None)
    assert not passed  # dropped — empty list or None


# ------------------------------------------------------------------ #
# Hub streaming — draft plumbing, stop route, draft in the poll      #
# ------------------------------------------------------------------ #

def test_internal_worker_streams_draft_lifecycle():
    """The worker opens a draft turn, hands a stream sink to handle_message,
    and closes the draft when the turn completes."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        fake_orch = MagicMock()
        fake_orch.handle_message.return_value = "final reply"
        fake_stream_store = MagicMock()
        with patch.dict(os.environ, _ENV):
            with patch.object(ws, "_orchestrator", fake_orch), \
                 patch.object(ws, "_get_hub_stream_store", return_value=fake_stream_store), \
                 patch("core.scheduled_message.send_and_inject", new=MagicMock()):
                client = TestClient(ws.app)
                resp = client.post(
                    "/internal/process-hub-message",
                    json={"content": "hi", "user_id": 123456},
                )

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    fake_stream_store.start_turn.assert_called_once()
    turn_user, turn_id = fake_stream_store.start_turn.call_args.args
    assert turn_user == 123456
    # handle_message received a sink bound to the same turn.
    sink = fake_orch.handle_message.call_args.kwargs.get("stream_sink")
    assert sink is not None
    # And the draft was closed as done afterwards.
    fake_stream_store.finish_turn.assert_called_once()
    assert fake_stream_store.finish_turn.call_args.args == (123456, turn_id)


def test_internal_worker_finishes_turn_even_when_agent_raises():
    """finish_turn must run on the error path too — a stuck 'generating' draft
    would leave the hub showing a phantom typing bubble forever."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        fake_orch = MagicMock()
        fake_orch.handle_message.side_effect = RuntimeError("boom")
        fake_stream_store = MagicMock()
        with patch.dict(os.environ, _ENV):
            with patch.object(ws, "_orchestrator", fake_orch), \
                 patch.object(ws, "_get_hub_stream_store", return_value=fake_stream_store):
                client = TestClient(ws.app)
                try:
                    client.post(
                        "/internal/process-hub-message",
                        json={"content": "hi", "user_id": 123456},
                    )
                except RuntimeError:
                    pass  # TestClient re-raises unhandled app exceptions

    fake_stream_store.finish_turn.assert_called_once()


def test_post_chat_stop_requests_cancel():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        fake_stream_store = MagicMock()
        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            with patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "_get_hub_stream_store", return_value=fake_stream_store):
                client = TestClient(ws.app)
                resp = client.post("/api/chat/stop")

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    fake_stream_store.request_cancel.assert_called_once_with(123456)


def test_get_messages_includes_draft_while_generating():
    """While a turn is in flight (last message role=user) the poll carries the
    live draft so the frontend can render the streaming bubble."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get_full.return_value = [
                {"role": "user", "content": "long question"},
            ]
            fake_stream_store = MagicMock()
            fake_stream_store.get_draft.return_value = {
                "turn_id": "t1", "text": "typing so far", "status": "generating",
            }
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "_get_hub_stream_store", return_value=fake_stream_store):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages")

    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["draft"] == {"text": "typing so far", "status": "generating"}


def test_get_messages_no_draft_when_last_is_assistant():
    """No in-flight turn → no draft field (and no extra Firestore read)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            fake_store_cls = MagicMock(name="FirestoreConversationStore")
            fake_store_cls.return_value.get_full.return_value = [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ]
            fake_stream_store = MagicMock()
            with patch("memory.firestore_conversation.FirestoreConversationStore", fake_store_cls), \
                 patch.object(ws, "_resolve_hub_user_id", return_value=123456), \
                 patch.object(ws, "_get_hub_stream_store", return_value=fake_stream_store):
                client = TestClient(ws.app)
                resp = client.get("/api/chat/messages")

    body = resp.json()
    assert body.get("draft") is None
    fake_stream_store.get_draft.assert_not_called()
