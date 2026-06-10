# tests/test_nightly_review.py
"""Tests for the nightly review (WS2): wind-down date mapping, idempotency,
send-after-build, light fallback, and the /trigger/nightly + /cron/nightly-backstop
route auth."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_TZ = ZoneInfo("Asia/Jerusalem")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")


# ---------------------------------------------------------------------------
# nightly_target_date — wind-down maps to the day it started on
# ---------------------------------------------------------------------------

def test_nightly_target_date_evening_stays_same_day():
    from core.nightly_review import nightly_target_date
    assert nightly_target_date(datetime(2026, 6, 10, 23, 0, tzinfo=_TZ)) == "2026-06-10"


def test_nightly_target_date_after_midnight_maps_to_prev_day():
    """A 01:00 backstop (or a 00:30 trigger) belongs to the previous evening."""
    from core.nightly_review import nightly_target_date
    assert nightly_target_date(datetime(2026, 6, 11, 1, 0, tzinfo=_TZ)) == "2026-06-10"


# ---------------------------------------------------------------------------
# Light plain-text fallback
# ---------------------------------------------------------------------------

def test_plain_text_fallback_is_light_and_includes_tomorrow():
    from core.nightly_review import _plain_text_fallback
    journal = {"summary": "Solid day — hit the lift and ate well."}
    tomorrow = {"calendar": [{"start": "2026-06-11T09:00:00+03:00", "summary": "Threshold run"}]}
    txt = _plain_text_fallback(journal, tomorrow)
    assert "Tomorrow:" in txt
    assert "Threshold run" in txt
    assert "sir" not in txt.lower()


def test_plain_text_fallback_empty_tomorrow():
    from core.nightly_review import _plain_text_fallback
    txt = _plain_text_fallback(None, {"calendar": []})
    assert "Nothing on the calendar." in txt


# ---------------------------------------------------------------------------
# run_nightly — idempotency + send/mark-after-build
# ---------------------------------------------------------------------------

def test_run_nightly_idempotent_skips_when_already_sent():
    import core.nightly_review as nr
    send_mock = AsyncMock()
    with patch.object(nr, "was_sent", return_value=True), \
         patch("core.scheduled_message.send_and_inject", new=send_mock):
        result = asyncio.run(nr.run_nightly(MagicMock(), "2026-06-10", trigger="backstop"))
    assert result is False
    send_mock.assert_not_awaited()


def test_run_nightly_sends_injects_and_marks_state():
    import core.nightly_review as nr
    send_mock = AsyncMock()
    set_calls: dict = {}
    with patch.object(nr, "was_sent", return_value=False), \
         patch.object(nr, "_build_nightly",
                      return_value={"text": "night text", "structured": {"tomorrow_date": "2026-06-11"}}), \
         patch.object(nr, "_set_state", side_effect=lambda d, f: set_calls.update({d: f})), \
         patch("core.scheduled_message.send_and_inject", new=send_mock):
        result = asyncio.run(nr.run_nightly(MagicMock(), "2026-06-10", trigger="focus"))

    assert result is True
    send_mock.assert_awaited_once()
    # injected into conversation history
    assert send_mock.await_args.kwargs.get("inject_into_conversation") is True
    # state marked sent AFTER send, with the tomorrow snapshot for the morning delta
    assert set_calls["2026-06-10"]["status"] == "sent"
    assert set_calls["2026-06-10"]["trigger"] == "focus"
    assert set_calls["2026-06-10"]["structured"]["tomorrow_date"] == "2026-06-11"


# ---------------------------------------------------------------------------
# Route auth — /trigger/nightly + /cron/nightly-backstop
# ---------------------------------------------------------------------------

def _build_test_client(env_patch: dict):
    """Import web_server with the heavy deps stubbed and return a TestClient + module.

    Mirrors tests/test_reflection.py::test_cron_reflect_route stubbing so the route
    layer is exercised without booting the real orchestrator.
    """
    telegram_stub = MagicMock(name="telegram")
    stubs = {
        "telegram": sys.modules.get("telegram", telegram_stub),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if "interfaces.web_server" in key:
            del sys.modules[key]
    return stubs, env_patch


def test_trigger_nightly_rejects_missing_token():
    """No bypass + no Authorization header → 401."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "NIGHTLY_TRIGGER_TOKEN": "s3cret-token",
        "CRON_DEV_BYPASS": "false",
    })
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            client = TestClient(ws.app)
            resp = client.post("/trigger/nightly")
    assert resp.status_code == 401


def test_trigger_nightly_rejects_bad_token():
    """Wrong bearer → 403."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "NIGHTLY_TRIGGER_TOKEN": "s3cret-token",
        "CRON_DEV_BYPASS": "false",
    })
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            client = TestClient(ws.app)
            resp = client.post("/trigger/nightly", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403


def test_trigger_nightly_dev_bypass_acks_and_runs_in_background():
    """CRON_DEV_BYPASS=true skips auth; route returns 202 immediately and the nightly
    runs in a background task (Starlette TestClient executes background tasks in-cycle)."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "CRON_DEV_BYPASS": "true",
    })
    run_mock = AsyncMock(return_value=True)
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            with patch("core.nightly_review.run_nightly", run_mock):
                ws._log_cron_run = lambda *a, **k: None  # type: ignore[attr-defined]
                ws._application = MagicMock()  # TestClient w/o `with` skips lifespan
                client = TestClient(ws.app)
                resp = client.post("/trigger/nightly")
    # Phone gets an instant ack, not the slow compose result.
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True}
    # The background task still ran the nightly with the focus trigger.
    run_mock.assert_awaited_once()
    assert run_mock.await_args.kwargs.get("trigger") == "focus"


def test_nightly_backstop_rejects_unauthenticated():
    """/cron/nightly-backstop uses OIDC verification → 401 without a bearer."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "CRON_DEV_BYPASS": "false",
        "CLOUD_RUN_URL": "https://example.run.app",
        "CLOUD_SCHEDULER_SA_EMAIL": "sched@example.iam.gserviceaccount.com",
    })
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            client = TestClient(ws.app)
            resp = client.post("/cron/nightly-backstop")
    assert resp.status_code == 401


def test_nightly_backstop_dev_bypass_runs_nightly():
    """CRON_DEV_BYPASS=true → backstop invokes run_nightly with trigger='backstop'."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "CRON_DEV_BYPASS": "true",
    })
    run_mock = AsyncMock(return_value=False)
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            with patch("core.nightly_review.run_nightly", run_mock):
                ws._log_cron_run = lambda *a, **k: None  # type: ignore[attr-defined]
                ws._application = MagicMock()  # TestClient w/o `with` skips lifespan
                client = TestClient(ws.app)
                resp = client.post("/cron/nightly-backstop")
    assert resp.status_code == 200
    assert resp.json() == {"sent": False}
    run_mock.assert_awaited_once()
    assert run_mock.await_args.kwargs.get("trigger") == "backstop"
