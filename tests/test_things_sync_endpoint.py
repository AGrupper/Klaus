"""Tests for core/things_ingest.py and the POST /cron/things-sync route.

Mirrors tests/test_strength_sync_endpoint.py: stub heavy web_server imports,
exercise the OIDC gate (dev-bypass + 401 without bearer), and confirm
run_one_batch is dispatched and its result returned.

The ingest module itself is covered for the cron contract that matters — it must
never raise, and it must report failure rather than a false success when Things
Cloud is degraded.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import memory.things_store as store_mod

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


# ------------------------------------------------------------------ #
# Route                                                               #
# ------------------------------------------------------------------ #

def test_things_sync_returns_batch_result_with_dev_bypass():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        batch = {"ok": True, "mode": "delta", "cursor": 343,
                 "entities": 261, "open_todos": 54, "done": True}
        with patch.dict(os.environ, _BASE_ENV):
            with patch("core.things_ingest.run_one_batch", return_value=batch) as rob:
                client = TestClient(ws.app, raise_server_exceptions=True)
                resp = client.post("/cron/things-sync")

    assert resp.status_code == 200, resp.text
    assert resp.json() == batch
    rob.assert_called_once()


def test_things_sync_returns_401_without_bearer(monkeypatch):
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
            resp = client.post("/cron/things-sync")

    assert resp.status_code == 401, resp.text


# ------------------------------------------------------------------ #
# Ingest batch                                                        #
# ------------------------------------------------------------------ #

def test_batch_reports_counts_on_success():
    store_mod.reset_cache()
    fake = MagicMock()
    fake._refresh.return_value = {"a": {}, "b": {}}
    fake.list.return_value = [{"id": "a"}]
    with patch.object(store_mod, "ThingsTaskStore", return_value=fake):
        import core.things_ingest as ingest
        result = ingest.run_one_batch()

    assert result["ok"] is True
    assert result["entities"] == 2
    assert result["open_todos"] == 1
    assert result["done"] is True, "a refresh always drains to the head"


def test_batch_reports_failure_when_things_is_degraded():
    """A stale mirror is a real failure for a sync job, not a silent success."""
    store_mod.reset_cache()
    fake = MagicMock()
    fake._refresh.return_value = {"a": {}}
    with patch.object(store_mod, "ThingsTaskStore", return_value=fake):
        store_mod._cache["stale_reason"] = "Things Cloud unreachable"
        import core.things_ingest as ingest
        result = ingest.run_one_batch()

    assert result["ok"] is False
    assert "unreachable" in result["error"]
    store_mod.reset_cache()


def test_batch_never_raises():
    """The cron contract: report the failure, do not propagate it."""
    store_mod.reset_cache()
    with patch.object(store_mod, "ThingsTaskStore", side_effect=RuntimeError("boom")):
        import core.things_ingest as ingest
        result = ingest.run_one_batch()

    assert result == {"ok": False, "error": "boom", "done": True}


def test_batch_labels_cold_start_as_replay():
    store_mod.reset_cache()
    fake = MagicMock()
    fake._refresh.return_value = {}
    fake.list.return_value = []
    with patch.object(store_mod, "ThingsTaskStore", return_value=fake):
        import core.things_ingest as ingest
        assert ingest.run_one_batch()["mode"] == "replay"


def test_batch_labels_warm_cache_as_delta():
    store_mod.reset_cache()
    store_mod._cache["state"] = {"a": {}}
    fake = MagicMock()
    fake._refresh.return_value = {"a": {}}
    fake.list.return_value = []
    with patch.object(store_mod, "ThingsTaskStore", return_value=fake):
        import core.things_ingest as ingest
        assert ingest.run_one_batch()["mode"] == "delta"
    store_mod.reset_cache()
