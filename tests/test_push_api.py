"""Tests for /api/push/* and /api/settings routes in interfaces/web_server.py.

Phase 29 — PUSH-01, PUSH-03 (TDD — Task 1 subscribe/vapid, Task 2 settings)

Covers:
  - test_push_and_settings_routes_require_session: no session → 401 on all 4 routes
  - TestSubscribeEndpoint: non-https endpoint → 400; missing keys → 400; valid → 200 + upsert
  - TestPushEnabledAtStamp: first successful subscribe stamps push_enabled_at (D-14);
    a later subscribe with push_enabled_at already set does not re-stamp
  - test_vapid_public_key_returns_env_key: GET returns {"key": VAPID_PUBLIC_KEY}
  - TestSettingsEndpoint: GET returns HubSettingsStore.get() jsonsafe; PATCH toggles
    telegram_mirror_enabled; PATCH with a non-bool value → 400

Mock strategy (mirrors tests/test_habits_api.py / tests/test_hub_chat.py):
  - Firestore mocked at sys.modules level before any memory.firestore_db import.
  - Heavy web_server deps (telegram, core.main, interfaces._router) stubbed via
    patch.dict(sys.modules, stubs) around each test.
  - require_hub_session dependency overridden for authenticated tests;
    CRON_DEV_BYPASS=false + no override for the 401 auth-gate test.
  - PushSubscriptionStore / HubSettingsStore patched via
    patch("memory.firestore_db.<Store>", return_value=mock_instance).
"""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# (verbatim from test_habits_api.py / test_task_store.py)
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore and related stubs into sys.modules."""
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        if "google" not in sys.modules or isinstance(sys.modules["google"], MagicMock):
            google_mod = ModuleType("google")
            google_mod.__path__ = []
            sys.modules["google"] = google_mod
        else:
            google_mod = sys.modules["google"]

        if "google.cloud" not in sys.modules or isinstance(
            sys.modules["google.cloud"], MagicMock
        ):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()

    class _Increment:
        def __init__(self, value):
            self.value = value

        def __repr__(self):
            return f"Increment({self.value!r})"

    firestore_mock.Increment = _Increment
    firestore_mock.SERVER_TIMESTAMP = object()

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    bq = sys.modules.get("google.cloud.firestore_v1.base_query", MagicMock())
    sys.modules["google.cloud.firestore_v1.base_query"] = bq
    if "google.cloud.firestore_v1" in sys.modules:
        sys.modules["google.cloud.firestore_v1"].base_query = bq
    else:
        fv1 = MagicMock()
        fv1.base_query = bq
        sys.modules["google.cloud.firestore_v1"] = fv1

    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db so it picks up the mocks
    for key in list(sys.modules.keys()):
        if "memory.firestore_db" in key or key == "memory.firestore_db":
            del sys.modules[key]


_install_firestore_mock()


# ---------------------------------------------------------------------------
# Test environment
# ---------------------------------------------------------------------------

_ENV: dict[str, str] = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    # CRON_DEV_BYPASS=false forces real hub-session auth on every /api/* request.
    # Tests that want auth bypassed use app.dependency_overrides instead.
    "CRON_DEV_BYPASS": "false",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
    "VAPID_PUBLIC_KEY": "fake-vapid-public-key-b64url",
}

_VALID_SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "fake-p256dh-key", "auth": "fake-auth-secret"},
}


def _stub_web_server_imports() -> dict:
    """Return sys.modules stubs for heavy web_server dependencies.

    Clears the cached web_server module so the next import picks up the stubs,
    mirroring test_hub_chat.py / test_habits_api.py.
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


# ---------------------------------------------------------------------------
# Auth gate: no session → 401 (T-29-10)
# ---------------------------------------------------------------------------

def test_push_and_settings_routes_require_session():
    """POST /api/push/subscribe, GET /api/push/vapid-public-key, GET+PATCH
    /api/settings without a session cookie must return 401 (T-29-10).

    No dependency override is set so the real require_hub_session runs.
    CRON_DEV_BYPASS=false ensures the bypass is inactive.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, _ENV):
            client = TestClient(ws.app, raise_server_exceptions=False)

            resp = client.post(
                "/api/push/subscribe",
                json={"subscription": _VALID_SUBSCRIPTION, "user_agent": "test-ua"},
            )
            assert resp.status_code == 401, (
                f"POST /api/push/subscribe must return 401 without session, got {resp.status_code}"
            )

            resp = client.get("/api/push/vapid-public-key")
            assert resp.status_code == 401, (
                f"GET /api/push/vapid-public-key must return 401 without session, got {resp.status_code}"
            )

            resp = client.get("/api/settings")
            assert resp.status_code == 401, (
                f"GET /api/settings must return 401 without session, got {resp.status_code}"
            )

            resp = client.patch("/api/settings", json={"telegram_mirror_enabled": False})
            assert resp.status_code == 401, (
                f"PATCH /api/settings must return 401 without session, got {resp.status_code}"
            )


# ---------------------------------------------------------------------------
# TestSubscribeEndpoint — validation + upsert (T-29-11)
# ---------------------------------------------------------------------------

class TestSubscribeEndpoint:
    """POST /api/push/subscribe behavior (PUSH-01, T-29-11)."""

    def _call_subscribe(self, body: dict, mock_push_store: MagicMock | None = None,
                         mock_settings_store: MagicMock | None = None):
        """Helper: POST /api/push/subscribe with the given body, auth bypassed."""
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            if mock_push_store is None:
                mock_push_store = MagicMock()
                mock_push_store.upsert.return_value = None
            if mock_settings_store is None:
                mock_settings_store = MagicMock()
                mock_settings_store.get.return_value = {
                    "telegram_mirror_enabled": True,
                    "push_enabled_at": None,
                }
                mock_settings_store.set.return_value = None

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.PushSubscriptionStore", return_value=mock_push_store), \
                         patch("memory.firestore_db.HubSettingsStore", return_value=mock_settings_store):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        resp = client.post("/api/push/subscribe", json=body)
                        return resp, mock_push_store, mock_settings_store
                finally:
                    ws.app.dependency_overrides.clear()

    def test_rejects_non_https_endpoint(self):
        body = {
            "subscription": {
                "endpoint": "http://not-secure.example.com/push",
                "keys": {"p256dh": "k", "auth": "a"},
            },
            "user_agent": "test-ua",
        }
        resp, mock_push_store, _ = self._call_subscribe(body)
        assert resp.status_code == 400, f"non-https endpoint must 400, got {resp.status_code}: {resp.text}"
        mock_push_store.upsert.assert_not_called()

    def test_rejects_missing_keys(self):
        body = {
            "subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/xyz", "keys": {}},
            "user_agent": "test-ua",
        }
        resp, mock_push_store, _ = self._call_subscribe(body)
        assert resp.status_code == 400, f"missing keys must 400, got {resp.status_code}: {resp.text}"
        mock_push_store.upsert.assert_not_called()

    def test_valid_subscribe_calls_upsert(self):
        body = {"subscription": _VALID_SUBSCRIPTION, "user_agent": "test-ua"}
        resp, mock_push_store, _ = self._call_subscribe(body)
        assert resp.status_code == 200, f"valid subscribe must 200, got {resp.status_code}: {resp.text}"
        assert resp.json() == {"ok": True}
        mock_push_store.upsert.assert_called_once_with(_VALID_SUBSCRIPTION, "test-ua")


# ---------------------------------------------------------------------------
# TestPushEnabledAtStamp — D-14 heartbeat anchor
# ---------------------------------------------------------------------------

class TestPushEnabledAtStamp:
    """First successful subscribe stamps push_enabled_at; later ones don't (D-14)."""

    def _call_subscribe(self, mock_settings_store: MagicMock):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            mock_push_store = MagicMock()
            mock_push_store.upsert.return_value = None

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.PushSubscriptionStore", return_value=mock_push_store), \
                         patch("memory.firestore_db.HubSettingsStore", return_value=mock_settings_store):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        resp = client.post(
                            "/api/push/subscribe",
                            json={"subscription": _VALID_SUBSCRIPTION, "user_agent": "test-ua"},
                        )
                        return resp
                finally:
                    ws.app.dependency_overrides.clear()

    def test_first_subscribe_stamps_push_enabled_at(self):
        mock_settings_store = MagicMock()
        mock_settings_store.get.return_value = {
            "telegram_mirror_enabled": True,
            "push_enabled_at": None,
        }
        resp = self._call_subscribe(mock_settings_store)
        assert resp.status_code == 200, resp.text
        mock_settings_store.set.assert_called_once()
        (call_arg,), _ = mock_settings_store.set.call_args
        assert "push_enabled_at" in call_arg

    def test_second_subscribe_does_not_restamp(self):
        mock_settings_store = MagicMock()
        mock_settings_store.get.return_value = {
            "telegram_mirror_enabled": True,
            "push_enabled_at": "2026-07-01T00:00:00+00:00",
        }
        resp = self._call_subscribe(mock_settings_store)
        assert resp.status_code == 200, resp.text
        mock_settings_store.set.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/push/vapid-public-key
# ---------------------------------------------------------------------------

def test_vapid_public_key_returns_env_key():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = (
                lambda: "amit.grupper@gmail.com"
            )
            try:
                client = TestClient(ws.app, raise_server_exceptions=False)
                resp = client.get("/api/push/vapid-public-key")
            finally:
                ws.app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"key": _ENV["VAPID_PUBLIC_KEY"]}


# ---------------------------------------------------------------------------
# TestSettingsEndpoint — GET/PATCH /api/settings (PUSH-03, T-29-12)
# ---------------------------------------------------------------------------

class TestSettingsEndpoint:
    """GET/PATCH /api/settings behavior (mirror flag, D-09)."""

    def _call(self, method: str, mock_settings_store: MagicMock, **kwargs):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.HubSettingsStore", return_value=mock_settings_store):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        fn = getattr(client, method)
                        return fn("/api/settings", **kwargs)
                finally:
                    ws.app.dependency_overrides.clear()

    def test_get_settings_returns_store_get(self):
        mock_settings_store = MagicMock()
        mock_settings_store.get.return_value = {
            "telegram_mirror_enabled": True,
            "push_enabled_at": None,
        }
        resp = self._call("get", mock_settings_store)
        assert resp.status_code == 200, resp.text
        assert resp.json()["telegram_mirror_enabled"] is True

    def test_patch_settings_toggles_mirror(self):
        mock_settings_store = MagicMock()
        mock_settings_store.get.return_value = {
            "telegram_mirror_enabled": False,
            "push_enabled_at": None,
        }
        mock_settings_store.set.return_value = None
        resp = self._call(
            "patch", mock_settings_store, json={"telegram_mirror_enabled": False},
        )
        assert resp.status_code == 200, resp.text
        mock_settings_store.set.assert_called_once_with({"telegram_mirror_enabled": False})
        assert resp.json()["telegram_mirror_enabled"] is False

    def test_patch_settings_rejects_non_bool(self):
        mock_settings_store = MagicMock()
        mock_settings_store.get.return_value = {"telegram_mirror_enabled": True}
        resp = self._call(
            "patch", mock_settings_store, json={"telegram_mirror_enabled": "not-a-bool"},
        )
        assert resp.status_code == 400, f"non-bool must 400, got {resp.status_code}: {resp.text}"
        mock_settings_store.set.assert_not_called()
