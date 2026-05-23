# tests/test_web_server.py
"""Tests for interfaces/web_server.py cron routes.

Currently covers:
  - TestCronAutonomousTick: the Phase 18 /cron/autonomous-tick route
    (AUTO-06) — OIDC gate + _application guard + run_autonomous_tick
    invocation + _log_cron_run ledger writes on success and failure.

Pattern: mirror tests/test_reflection.py::test_cron_reflect_route — stub
the heavy top-level web_server imports (telegram, core.main, core.auth_google,
interfaces._router) via patch.dict(sys.modules) so the import side-effects
do not require real Google/Telegram credentials. The stubs are scoped to the
patch.dict block so they don't leak into adjacent test files.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Module-level env defaults so any deferred import does not error.
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
os.environ.setdefault("GCP_PROJECT_ID", "klaus-agent")


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #

_BASE_ENV = {
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
    "PINECONE_API_KEY": "fake",
    "PINECONE_INDEX": "fake-index",
}


def _stub_web_server_imports() -> dict:
    """Return a sys.modules-stubs dict that lets interfaces.web_server import
    without real telegram / google-auth / core.main dependencies.

    Caller is expected to wrap import in `with patch.dict(sys.modules, stubs)`.
    Also flushes the cached web_server so the next import picks up the stubs.
    """
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    # Force fresh re-import of web_server so the stubs are seen.
    for key in list(sys.modules.keys()):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs


# --------------------------------------------------------------------------- #
# TestCronAutonomousTick — Phase 18 AUTO-06                                    #
# --------------------------------------------------------------------------- #


class TestCronAutonomousTick:
    """Behavioral tests for the POST /cron/autonomous-tick endpoint."""

    def test_returns_200_with_dev_bypass_and_app_present(self, monkeypatch):
        """Dev bypass + initialised _application + run_autonomous_tick succeeds → 200."""
        stubs = _stub_web_server_imports()

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            with patch.dict(os.environ, _BASE_ENV):
                # _application must be non-None so the guard is satisfied
                fake_app = MagicMock(name="Application")
                fake_app.bot = MagicMock(name="bot")
                ws._application = fake_app  # type: ignore[attr-defined]

                # Patch core.autonomous.run_autonomous_tick so no real LLM call.
                async_mock = AsyncMock(return_value={"sent": False})
                # The route does `import core.autonomous as _auto` then awaits
                # `_auto.run_autonomous_tick(...)`. Patching the module attribute
                # ensures the route's resolved reference uses our mock.
                with patch("core.autonomous.run_autonomous_tick", async_mock):
                    client = TestClient(ws.app, raise_server_exceptions=True)
                    resp = client.post("/cron/autonomous-tick")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json() == {"ok": True}
        async_mock.assert_awaited_once()
        # First positional arg must be _application.bot
        args, _kwargs = async_mock.await_args
        assert args[0] is fake_app.bot, "run_autonomous_tick must receive _application.bot"

    def test_returns_401_without_bearer(self, monkeypatch):
        """No bypass + no Authorization header → 401 from _verify_cron_request."""
        stubs = _stub_web_server_imports()

        env = dict(_BASE_ENV)
        env["CRON_DEV_BYPASS"] = "false"

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            # Remove OIDC env so it would fail even if bypass was somehow honored.
            monkeypatch.delenv("CLOUD_RUN_URL", raising=False)
            monkeypatch.delenv("CLOUD_SCHEDULER_SA_EMAIL", raising=False)
            with patch.dict(os.environ, env):
                client = TestClient(ws.app)
                resp = client.post("/cron/autonomous-tick")

        assert resp.status_code == 401

    def test_returns_500_when_application_is_none(self, monkeypatch):
        """Dev bypass + _application is None → 500 from the singleton guard."""
        stubs = _stub_web_server_imports()

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            with patch.dict(os.environ, _BASE_ENV):
                ws._application = None  # type: ignore[attr-defined]
                client = TestClient(ws.app, raise_server_exceptions=False)
                resp = client.post("/cron/autonomous-tick")

        assert resp.status_code == 500
        # Detail body shape mirrors cron_proactive_alerts / cron_morning_briefing_tick.
        body = resp.json()
        assert "detail" in body
        # detail is either {"error": "..."} dict or a string — either is fine
        # so long as 500 fired from the guard, not from an uncaught exception.

    def test_logs_cron_run_ok_true_on_success(self, monkeypatch):
        """On a clean success path, _log_cron_run('autonomous-tick', ok=True) is called."""
        stubs = _stub_web_server_imports()
        calls: list[dict] = []

        def _fake_log(job_id: str, ok: bool, **kwargs) -> None:
            calls.append({"job_id": job_id, "ok": ok, "kwargs": kwargs})

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            with patch.dict(os.environ, _BASE_ENV):
                fake_app = MagicMock(name="Application")
                fake_app.bot = MagicMock(name="bot")
                ws._application = fake_app  # type: ignore[attr-defined]
                ws._log_cron_run = _fake_log  # type: ignore[attr-defined]

                async_mock = AsyncMock(return_value={"sent": True})
                with patch("core.autonomous.run_autonomous_tick", async_mock):
                    client = TestClient(ws.app, raise_server_exceptions=True)
                    resp = client.post("/cron/autonomous-tick")

        assert resp.status_code == 200
        relevant = [c for c in calls if c["job_id"] == "autonomous-tick"]
        assert relevant, f"_log_cron_run('autonomous-tick', ...) must be called; got {calls}"
        assert relevant[-1]["ok"] is True, (
            f"Expected ok=True on success, got {relevant}"
        )

    def test_logs_cron_run_ok_false_on_exception(self, monkeypatch):
        """If run_autonomous_tick raises, _log_cron_run is called with ok=False AND the exception propagates."""
        stubs = _stub_web_server_imports()
        calls: list[dict] = []

        def _fake_log(job_id: str, ok: bool, **kwargs) -> None:
            calls.append({"job_id": job_id, "ok": ok, "kwargs": kwargs})

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            with patch.dict(os.environ, _BASE_ENV):
                fake_app = MagicMock(name="Application")
                fake_app.bot = MagicMock(name="bot")
                ws._application = fake_app  # type: ignore[attr-defined]
                ws._log_cron_run = _fake_log  # type: ignore[attr-defined]

                async_mock = AsyncMock(side_effect=RuntimeError("upstream blew up"))
                # raise_server_exceptions=False so the test client returns 500
                # instead of re-raising; we still want to verify the log call.
                with patch("core.autonomous.run_autonomous_tick", async_mock):
                    client = TestClient(ws.app, raise_server_exceptions=False)
                    resp = client.post("/cron/autonomous-tick")

        assert resp.status_code == 500, (
            f"Unhandled exception in the route must surface as 500; got {resp.status_code}"
        )
        relevant = [c for c in calls if c["job_id"] == "autonomous-tick"]
        assert relevant, f"_log_cron_run('autonomous-tick', ...) must be called; got {calls}"
        assert relevant[-1]["ok"] is False, (
            f"Expected ok=False on exception, got {relevant}"
        )
