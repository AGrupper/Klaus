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


# --------------------------------------------------------------------------- #
# TestCronWeeklyTrainingReview — Phase 20 REVIEW-01 + REVIEW-04                #
# --------------------------------------------------------------------------- #


class TestCronWeeklyTrainingReview:
    """Behavioral tests for the POST /cron/weekly-training-review endpoint.

    Mirrors TestCronAutonomousTick: OIDC gate + _application guard +
    run_weekly_review invocation + _log_cron_run ledger writes on both paths.
    Covers REVIEW-01 + REVIEW-04.
    """

    def test_returns_200_with_dev_bypass_and_app_present(self, monkeypatch):
        """Dev bypass + initialised _application + run_weekly_review succeeds → 200."""
        stubs = _stub_web_server_imports()

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            with patch.dict(os.environ, _BASE_ENV):
                fake_app = MagicMock(name="Application")
                fake_app.bot = MagicMock(name="bot")
                ws._application = fake_app  # type: ignore[attr-defined]

                async_mock = AsyncMock(return_value=None)
                with patch("core.weekly_training_review.run_weekly_review", async_mock):
                    client = TestClient(ws.app, raise_server_exceptions=True)
                    resp = client.post("/cron/weekly-training-review")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json() == {"ok": True}
        async_mock.assert_awaited_once()
        # First positional arg must be _application.bot
        args, _kwargs = async_mock.await_args
        assert args[0] is fake_app.bot, "run_weekly_review must receive _application.bot"

    def test_returns_401_without_bearer(self, monkeypatch):
        """No bypass + no Authorization header → 401 from _verify_cron_request."""
        stubs = _stub_web_server_imports()

        env = dict(_BASE_ENV)
        env["CRON_DEV_BYPASS"] = "false"

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            monkeypatch.delenv("CLOUD_RUN_URL", raising=False)
            monkeypatch.delenv("CLOUD_SCHEDULER_SA_EMAIL", raising=False)
            with patch.dict(os.environ, env):
                client = TestClient(ws.app)
                resp = client.post("/cron/weekly-training-review")

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
                resp = client.post("/cron/weekly-training-review")

        assert resp.status_code == 500
        body = resp.json()
        assert "detail" in body

    def test_logs_cron_run_ok_true_on_success(self, monkeypatch):
        """On a clean success path, _log_cron_run('weekly-training-review', ok=True) is called."""
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

                async_mock = AsyncMock(return_value=None)
                with patch("core.weekly_training_review.run_weekly_review", async_mock):
                    client = TestClient(ws.app, raise_server_exceptions=True)
                    resp = client.post("/cron/weekly-training-review")

        assert resp.status_code == 200
        relevant = [c for c in calls if c["job_id"] == "weekly-training-review"]
        assert relevant, f"_log_cron_run('weekly-training-review', ...) must be called; got {calls}"
        assert relevant[-1]["ok"] is True, (
            f"Expected ok=True on success, got {relevant}"
        )

    def test_logs_cron_run_ok_false_on_exception(self, monkeypatch):
        """If run_weekly_review raises, _log_cron_run called with ok=False AND exception propagates."""
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

                async_mock = AsyncMock(side_effect=RuntimeError("weekly review blew up"))
                with patch("core.weekly_training_review.run_weekly_review", async_mock):
                    client = TestClient(ws.app, raise_server_exceptions=False)
                    resp = client.post("/cron/weekly-training-review")

        assert resp.status_code == 500, (
            f"Unhandled exception in the route must surface as 500; got {resp.status_code}"
        )
        relevant = [c for c in calls if c["job_id"] == "weekly-training-review"]
        assert relevant, f"_log_cron_run('weekly-training-review', ...) must be called; got {calls}"
        assert relevant[-1]["ok"] is False, (
            f"Expected ok=False on exception, got {relevant}"
        )


# --------------------------------------------------------------------------- #
# TestCronHealthkitSync — Phase 19.1 HEALTHKIT-04 / HEALTHKIT-05               #
# --------------------------------------------------------------------------- #


# A 32+ byte token used across the auth tests; matches the entropy floor in
# RESEARCH.md Q5 (`secrets.token_urlsafe(32)`).
_VALID_HEALTHKIT_TOKEN = "test-token-32-chars-of-entropy-min"


def _healthkit_env(*, bypass: bool = False, token: str | None = _VALID_HEALTHKIT_TOKEN) -> dict:
    """Build an env dict for the healthkit tests — bypass off by default
    so the auth helper actually runs."""
    env = dict(_BASE_ENV)
    env["CRON_DEV_BYPASS"] = "true" if bypass else "false"
    if token is None:
        env.pop("HEALTHKIT_WEBHOOK_TOKEN", None)
    else:
        env["HEALTHKIT_WEBHOOK_TOKEN"] = token
    return env


def _load_sample_payload() -> dict:
    """Load the Wave-0 real-device fixture for the happy-path test."""
    import json  # noqa: PLC0415
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "healthkit_payload_sample.json"
    )
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def _ws_module():
    """Module-scoped import of interfaces.web_server with stubs applied.

    WHY: re-importing web_server in each test (the autonomous-tick test
    pattern) triggers a CPython 3.14 segfault when repeated more than ~5
    times in one process — the dotenv module's NamedTuple machinery
    interacts badly with the GC during repeated module-deletion. Cache
    the import at module scope; tests then mutate ws._application /
    ws._log_cron_run as needed and rely on per-test os.environ patches.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        yield ws


class TestCronHealthkitSync:
    """Behavioral tests for the POST /cron/healthkit-sync endpoint (Phase 19.1)."""

    def test_missing_auth_returns_401(self, monkeypatch, _ws_module):
        """No Authorization header → 401 from _verify_healthkit_request."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env()  # bypass=False, token set

        with patch.dict(os.environ, env):
            client = TestClient(ws.app)
            resp = client.post("/cron/healthkit-sync", json={"samples": []})

        assert resp.status_code == 401, (
            f"Missing Authorization header must yield 401; got {resp.status_code}: {resp.text}"
        )
        assert "Missing or malformed Authorization" in resp.text

    def test_bad_token_returns_403(self, monkeypatch, _ws_module):
        """Authorization header with wrong bearer → 403 from _verify_healthkit_request."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env(token="right-token")

        with patch.dict(os.environ, env):
            client = TestClient(ws.app)
            resp = client.post(
                "/cron/healthkit-sync",
                json={"samples": []},
                headers={"Authorization": "Bearer wrong-token-different-value-xyz"},
            )

        assert resp.status_code == 403, (
            f"Bad bearer must yield 403; got {resp.status_code}: {resp.text}"
        )
        assert "Invalid token" in resp.text

    def test_verify_uses_compare_digest(self, monkeypatch, _ws_module):
        """The auth helper MUST call hmac.compare_digest (constant-time compare)
        rather than plain ``==``. Patch the call site and assert it was invoked
        with byte-encoded arguments (per RESEARCH.md Q5)."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env(token="right-token")

        digest_mock = MagicMock(return_value=False)
        with patch.dict(os.environ, env), patch.object(
            ws.hmac, "compare_digest", digest_mock
        ):
            client = TestClient(ws.app)
            resp = client.post(
                "/cron/healthkit-sync",
                json={"samples": []},
                headers={"Authorization": "Bearer right-token"},
            )

        # Mock returned False so we end up in the 403 branch.
        assert resp.status_code == 403, (
            f"Mocked compare_digest=False must funnel into 403; got {resp.status_code}"
        )
        assert digest_mock.called, (
            "hmac.compare_digest must be invoked — `==` would not call the mock"
        )
        # Verify the mock was called with byte arguments (the canonical shape
        # `compare_digest(received.encode(), expected.encode())`).
        for call in digest_mock.call_args_list:
            args, _ = call
            assert all(isinstance(a, (bytes, bytearray)) for a in args), (
                f"compare_digest must be called with byte args; got {args!r}"
            )

    def test_missing_env_var_returns_500(self, monkeypatch, _ws_module):
        """HEALTHKIT_WEBHOOK_TOKEN env unset → 500 (refuse-all, prevents fail-open)."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env(token=None)
        monkeypatch.delenv("HEALTHKIT_WEBHOOK_TOKEN", raising=False)

        with patch.dict(os.environ, env, clear=False):
            # Ensure no leaked HEALTHKIT_WEBHOOK_TOKEN from another test
            # (env's None value just means "don't add" — strip explicitly).
            os.environ.pop("HEALTHKIT_WEBHOOK_TOKEN", None)
            client = TestClient(ws.app, raise_server_exceptions=False)
            resp = client.post(
                "/cron/healthkit-sync",
                json={"samples": []},
                headers={"Authorization": "Bearer anything-at-all-here"},
            )

        assert resp.status_code == 500, (
            f"Unset env var must yield 500 not 403; got {resp.status_code}: {resp.text}"
        )
        assert "Server misconfigured" in resp.text

    def test_malformed_payload_returns_422(self, monkeypatch, _ws_module):
        """Body missing the `samples` key → 422 via Pydantic ValidationError translation."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env()

        with patch.dict(os.environ, env):
            client = TestClient(ws.app)
            resp = client.post(
                "/cron/healthkit-sync",
                json={"NOT_samples": "garbage"},
                headers={"Authorization": f"Bearer {_VALID_HEALTHKIT_TOKEN}"},
            )

        assert resp.status_code == 422, (
            f"Malformed body must yield 422; got {resp.status_code}: {resp.text}"
        )

    def test_happy_path_upserts_each_meal(self, monkeypatch, _ws_module):
        """Valid auth + Path-B fixture payload → 200 with {"upserted": N_meals};
        MealStore.upsert called exactly once per aggregated meal.

        Path B: the fixture is 5 flat HKQuantitySample rows at one start_date
        (one for Energy / Protein / Carbs / Fat / Fiber) → the server
        aggregator groups them into ONE meal → ONE upsert call.
        """
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env()
        fixture = _load_sample_payload()
        # Path B: count meals (distinct start_date + food_item pairs), not
        # raw samples. The Path-B fixture is single-meal so this is 1.
        expected_meals = len({
            (s["start_date"], s.get("food_item")) for s in fixture["samples"]
        })

        mock_store = MagicMock(name="MealStore-instance")
        mock_store.upsert = MagicMock(return_value=None)
        mock_store_cls = MagicMock(name="MealStore-class", return_value=mock_store)

        with patch.dict(os.environ, env), patch(
            "memory.firestore_db.MealStore", mock_store_cls
        ):
            client = TestClient(ws.app)
            resp = client.post(
                "/cron/healthkit-sync",
                json=fixture,
                headers={"Authorization": f"Bearer {_VALID_HEALTHKIT_TOKEN}"},
            )

        assert resp.status_code == 200, (
            f"Happy path must yield 200; got {resp.status_code}: {resp.text}"
        )
        assert resp.json() == {"upserted": expected_meals}, (
            f"Response body must be {{'upserted': {expected_meals}}}; "
            f"got {resp.json()}"
        )
        assert mock_store.upsert.call_count == expected_meals, (
            f"MealStore.upsert must be called once per aggregated meal "
            f"(expected {expected_meals}, got {mock_store.upsert.call_count})"
        )

    def test_idempotent_repush(self, monkeypatch, _ws_module):
        """Same payload POSTed twice → both return 200; upsert called
        2 * N_meals times (idempotency lives in MealStore's merge=True
        semantics, not the handler)."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env()
        fixture = _load_sample_payload()
        # Path B: meals = distinct (start_date, food_item) groups.
        n_meals = len({
            (s["start_date"], s.get("food_item")) for s in fixture["samples"]
        })

        mock_store = MagicMock(name="MealStore-instance")
        mock_store.upsert = MagicMock(return_value=None)
        mock_store_cls = MagicMock(name="MealStore-class", return_value=mock_store)

        with patch.dict(os.environ, env), patch(
            "memory.firestore_db.MealStore", mock_store_cls
        ):
            client = TestClient(ws.app)
            hdrs = {"Authorization": f"Bearer {_VALID_HEALTHKIT_TOKEN}"}
            r1 = client.post("/cron/healthkit-sync", json=fixture, headers=hdrs)
            r2 = client.post("/cron/healthkit-sync", json=fixture, headers=hdrs)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert mock_store.upsert.call_count == 2 * n_meals, (
            f"Two pushes must each call upsert N_meals times "
            f"(expected {2 * n_meals}, got {mock_store.upsert.call_count})"
        )

    def test_logs_cron_run_ok_true_on_success(self, monkeypatch, _ws_module):
        """Clean success path → _log_cron_run('healthkit-sync', ok=True) fires."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env()
        fixture = _load_sample_payload()
        calls: list[dict] = []

        def _fake_log(job_id: str, ok: bool, **kwargs) -> None:
            calls.append({"job_id": job_id, "ok": ok, "kwargs": kwargs})

        mock_store = MagicMock(name="MealStore-instance")
        mock_store.upsert = MagicMock(return_value=None)
        mock_store_cls = MagicMock(name="MealStore-class", return_value=mock_store)

        original_log = ws._log_cron_run
        ws._log_cron_run = _fake_log  # type: ignore[attr-defined]
        try:
            with patch.dict(os.environ, env), patch(
                "memory.firestore_db.MealStore", mock_store_cls
            ):
                client = TestClient(ws.app)
                resp = client.post(
                    "/cron/healthkit-sync",
                    json=fixture,
                    headers={"Authorization": f"Bearer {_VALID_HEALTHKIT_TOKEN}"},
                )
        finally:
            ws._log_cron_run = original_log  # type: ignore[attr-defined]

        assert resp.status_code == 200
        relevant = [c for c in calls if c["job_id"] == "healthkit-sync"]
        assert relevant, (
            f"_log_cron_run('healthkit-sync', ...) must be called; got {calls}"
        )
        assert relevant[-1]["ok"] is True, (
            f"Expected ok=True on success, got {relevant}"
        )

    def test_logs_cron_run_ok_false_on_exception(self, monkeypatch, _ws_module):
        """If ingest_payload raises, _log_cron_run('healthkit-sync', ok=False) fires
        AND the exception propagates as a 500 to the client."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env()
        fixture = _load_sample_payload()
        calls: list[dict] = []

        def _fake_log(job_id: str, ok: bool, **kwargs) -> None:
            calls.append({"job_id": job_id, "ok": ok, "kwargs": kwargs})

        original_log = ws._log_cron_run
        ws._log_cron_run = _fake_log  # type: ignore[attr-defined]
        try:
            # Patch the ingest_payload function on the healthkit_tool module
            # so the handler hits an exception mid-flow.
            import mcp_tools.healthkit_tool as _hk  # noqa: PLC0415
            with patch.dict(os.environ, env), patch.object(
                _hk, "ingest_payload", side_effect=RuntimeError("kaboom")
            ):
                client = TestClient(ws.app, raise_server_exceptions=False)
                resp = client.post(
                    "/cron/healthkit-sync",
                    json=fixture,
                    headers={"Authorization": f"Bearer {_VALID_HEALTHKIT_TOKEN}"},
                )
        finally:
            ws._log_cron_run = original_log  # type: ignore[attr-defined]

        assert resp.status_code == 500, (
            f"RuntimeError in ingest_payload must surface as 500; got {resp.status_code}"
        )
        relevant = [c for c in calls if c["job_id"] == "healthkit-sync"]
        assert relevant, (
            f"_log_cron_run('healthkit-sync', ...) must be called; got {calls}"
        )
        assert relevant[-1]["ok"] is False, (
            f"Expected ok=False on exception, got {relevant}"
        )

    def test_cron_dev_bypass_skips_auth(self, monkeypatch, _ws_module):
        """CRON_DEV_BYPASS=true short-circuits the auth check entirely."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env(bypass=True, token=None)

        mock_store = MagicMock(name="MealStore-instance")
        mock_store.upsert = MagicMock(return_value=None)
        mock_store_cls = MagicMock(name="MealStore-class", return_value=mock_store)

        with patch.dict(os.environ, env), patch(
            "memory.firestore_db.MealStore", mock_store_cls
        ):
            client = TestClient(ws.app)
            # NO Authorization header on purpose
            resp = client.post("/cron/healthkit-sync", json={"samples": []})

        assert resp.status_code == 200, (
            f"CRON_DEV_BYPASS=true must skip auth; got {resp.status_code}: {resp.text}"
        )
        assert resp.json() == {"upserted": 0}

    def test_handler_does_not_touch_application(self, monkeypatch, _ws_module):
        """The handler is upsert-only (D-10) — it must NOT 500 when _application
        is None (no orchestrator / Telegram dependency)."""
        ws = _ws_module
        from fastapi.testclient import TestClient  # noqa: PLC0415
        env = _healthkit_env(bypass=True, token=None)

        mock_store = MagicMock(name="MealStore-instance")
        mock_store.upsert = MagicMock(return_value=None)
        mock_store_cls = MagicMock(name="MealStore-class", return_value=mock_store)

        original_app = ws._application
        ws._application = None  # type: ignore[attr-defined]
        try:
            with patch.dict(os.environ, env), patch(
                "memory.firestore_db.MealStore", mock_store_cls
            ):
                client = TestClient(ws.app)
                resp = client.post("/cron/healthkit-sync", json={"samples": []})
        finally:
            ws._application = original_app  # type: ignore[attr-defined]

        assert resp.status_code == 200, (
            f"Handler must not depend on _application; got {resp.status_code}: {resp.text}"
        )
