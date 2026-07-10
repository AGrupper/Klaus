"""Tests for the POST /cron/healthkit-reconcile route in interfaces/web_server.py.

Nightly full-previous-day nutrition reconcile: the 02:00 iOS automation pushes
the last-26h HealthKit window and the server treats it as authoritative for
one calendar date (default = yesterday Asia/Jerusalem).

Mirrors tests/test_strength_sync_endpoint.py + the TestCronHealthkitSync
pattern in tests/test_web_server.py: stub heavy web_server imports, exercise
the shared-secret bearer gate, and confirm reconcile_payload is dispatched
with the right target_date.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_BASE_ENV = {
    "CRON_DEV_BYPASS": "false",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
    "HEALTHKIT_WEBHOOK_TOKEN": "test-token-32-chars-of-entropy-min",
}

_HDRS = {"Authorization": f"Bearer {_BASE_ENV['HEALTHKIT_WEBHOOK_TOKEN']}"}

_RESULT = {
    "date": "2026-07-08", "received": 2, "kept_for_date": 2,
    "upserted": 2, "deleted": 1, "upserted_other_days": 0, "errored": 0,
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


@pytest.fixture(scope="module")
def _ws_module():
    """Module-scoped web_server import with stubs — same rationale as
    tests/test_web_server.py::_ws_module (repeated re-import is fragile)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        yield ws


def _post(ws, path: str, *, json_body=None, headers=None, env_extra=None,
          reconcile=None, raise_exc: bool = False):
    """POST helper: env + MealStore/reconcile_payload patches around a TestClient."""
    from fastapi.testclient import TestClient  # noqa: PLC0415
    env = dict(_BASE_ENV)
    env.update(env_extra or {})
    mock_store_cls = MagicMock(name="MealStore-class", return_value=MagicMock())
    reconcile = reconcile if reconcile is not None else MagicMock(return_value=dict(_RESULT))
    with patch.dict(os.environ, env), \
            patch("memory.firestore_db.MealStore", mock_store_cls), \
            patch("mcp_tools.healthkit_tool.reconcile_payload", reconcile):
        client = TestClient(ws.app, raise_server_exceptions=raise_exc)
        resp = client.post(path, json=json_body if json_body is not None else {"samples": []},
                           headers=headers or {})
    return resp, reconcile, mock_store_cls


def test_missing_auth_returns_401(_ws_module):
    resp, reconcile, _ = _post(_ws_module, "/cron/healthkit-reconcile")
    assert resp.status_code == 401, resp.text
    assert "Missing or malformed Authorization" in resp.text
    reconcile.assert_not_called()


def test_bad_token_returns_403(_ws_module):
    resp, reconcile, _ = _post(
        _ws_module, "/cron/healthkit-reconcile",
        headers={"Authorization": "Bearer wrong-token-different-value-xyz"},
    )
    assert resp.status_code == 403, resp.text
    assert "Invalid token" in resp.text
    reconcile.assert_not_called()


def test_malformed_payload_returns_422(_ws_module):
    """A real (unpatched) reconcile_payload raising ValidationError → 422."""
    import mcp_tools.healthkit_tool as _hk  # noqa: PLC0415
    resp, _, _ = _post(
        _ws_module, "/cron/healthkit-reconcile",
        json_body={"NOT_samples": "garbage"},
        headers=_HDRS,
        reconcile=_hk.reconcile_payload,  # the real one — raises ValidationError
    )
    assert resp.status_code == 422, resp.text


def test_bad_date_param_returns_422(_ws_module):
    resp, reconcile, _ = _post(
        _ws_module, "/cron/healthkit-reconcile?date=last-tuesday",
        headers=_HDRS,
    )
    assert resp.status_code == 422, resp.text
    reconcile.assert_not_called()


def test_happy_path_with_explicit_date(_ws_module):
    """?date=YYYY-MM-DD is passed through as the authoritative target date and
    the reconcile result comes back as the response body."""
    resp, reconcile, store_cls = _post(
        _ws_module, "/cron/healthkit-reconcile?date=2026-07-08",
        headers=_HDRS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == _RESULT
    reconcile.assert_called_once()
    assert reconcile.call_args.kwargs["target_date"] == "2026-07-08"
    # The store handed to reconcile_payload is a constructed MealStore.
    args, kwargs = reconcile.call_args
    assert args[1] is store_cls.return_value


def test_default_date_is_yesterday_jerusalem(_ws_module):
    """No ?date param → target_date = yesterday in Asia/Jerusalem."""
    expected = (
        datetime.now(ZoneInfo("Asia/Jerusalem")).date() - timedelta(days=1)
    ).isoformat()
    resp, reconcile, _ = _post(
        _ws_module, "/cron/healthkit-reconcile", headers=_HDRS,
    )
    assert resp.status_code == 200, resp.text
    assert reconcile.call_args.kwargs["target_date"] == expected


def test_logs_cron_run_ok_true_on_success(_ws_module):
    ws = _ws_module
    calls: list[tuple] = []
    with patch.object(ws, "_log_cron_run", side_effect=lambda job, ok: calls.append((job, ok))):
        resp, _, _ = _post(ws, "/cron/healthkit-reconcile?date=2026-07-08", headers=_HDRS)
    assert resp.status_code == 200
    assert ("healthkit-reconcile", True) in calls


def test_logs_cron_run_ok_false_on_failure(_ws_module):
    ws = _ws_module
    calls: list[tuple] = []
    boom = MagicMock(side_effect=RuntimeError("boom"))
    with patch.object(ws, "_log_cron_run", side_effect=lambda job, ok: calls.append((job, ok))):
        resp, _, _ = _post(
            ws, "/cron/healthkit-reconcile?date=2026-07-08",
            headers=_HDRS, reconcile=boom,
        )
    assert resp.status_code == 500
    assert ("healthkit-reconcile", False) in calls
