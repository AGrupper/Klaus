"""Tests for the POST /cron/biometric-sync route in interfaces/web_server.py.

Mirrors tests/test_run_sync_endpoint.py: stub heavy web_server imports,
exercise the OIDC gate (dev-bypass + 401 without bearer), and confirm
run_one_batch is dispatched and its result is returned.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

_BASE_ENV = {
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _stub_web_server_imports() -> dict:
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


def test_biometric_sync_returns_batch_result_with_dev_bypass():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        batch = {"ok": True, "mode": "delta", "processed": 2, "remaining": 0, "done": True}
        with patch.dict(os.environ, _BASE_ENV):
            with patch("core.biometric_ingest.run_one_batch", return_value=batch) as rob:
                client = TestClient(ws.app, raise_server_exceptions=True)
                resp = client.post("/cron/biometric-sync")

    assert resp.status_code == 200, resp.text
    assert resp.json() == batch
    rob.assert_called_once()


def test_biometric_sync_returns_401_without_bearer(monkeypatch):
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        env = dict(_BASE_ENV)
        env["CRON_DEV_BYPASS"] = "false"
        with patch.dict(os.environ, env):
            monkeypatch.delenv("CLOUD_RUN_URL", raising=False)
            monkeypatch.delenv("CLOUD_SCHEDULER_SA_EMAIL", raising=False)
            client = TestClient(ws.app)
            resp = client.post("/cron/biometric-sync")

    assert resp.status_code == 401, resp.text
