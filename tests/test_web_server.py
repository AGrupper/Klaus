"""Retained HTTP route tests for ``interfaces.web_server``."""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("GCP_PROJECT_ID", "klaus-agent")


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #

_BASE_ENV = {
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "PINECONE_API_KEY": "fake",
    "PINECONE_INDEX": "fake-index",
}


@pytest.fixture(autouse=True)
def _no_real_cron_ledger_writes():
    """Route tests must never reach the configured Firestore project."""
    with patch("memory.firestore_db.record_cron_run"):
        yield


def _stub_web_server_imports() -> dict:
    """Clear the cached HTTP boundary so each test gets fresh routes.

    The route modules under ``interfaces.routes`` go too. Their APIRouters build
    their ``Depends(require_hub_session)`` at import time, so a cached router
    would hand a freshly re-imported ``web_server`` route objects still bound to
    the previous ``hub_auth.require_hub_session`` object — and
    ``dependency_overrides`` keys on object identity, so the override would
    silently fail to apply.
    """
    for key in list(sys.modules.keys()):
        if (
            key == "interfaces.web_server"
            or key.startswith("interfaces.web_server.")
            or key == "interfaces.routes"
            or key.startswith("interfaces.routes.")
        ):
            del sys.modules[key]
    return {}


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


def test_internal_routine_fallback_jsonresponse_serializes_atomic_run(
    monkeypatch,
    _ws_module,
):
    """The real fallback HTTP route must JSON-encode a fresh atomic result."""
    import memory.firestore_db
    from fastapi.testclient import TestClient
    from tests.routine_firestore_fakes import (
        VersionedFirestoreClient,
        transactional_with_retry,
    )

    ws = _ws_module
    client = VersionedFirestoreClient(
        server_timestamp=memory.firestore_db.firestore.SERVER_TIMESTAMP
    )
    monkeypatch.setattr(memory.firestore_db, "_make_firestore_client", lambda *_args: client)
    monkeypatch.setattr(
        memory.firestore_db.firestore,
        "transactional",
        transactional_with_retry,
    )
    runs = memory.firestore_db.RoutineRunStore("test-project")
    runs.start(
        routine="morning",
        target_date="2026-08-11",
        trigger="wake",
        correlation_id="fallback-json-safe",
    )

    class AtomicFallbackCoordinator:
        @staticmethod
        async def publish_timeout_fallback(correlation_id):
            return runs.publish_review_atomic(
                correlation_id,
                publisher="fallback",
                text="Serializable deterministic fallback.",
                structured={"fallback": True},
                action_ids=[],
                partial_actions=[],
            )

    monkeypatch.setattr(
        "core.subscription_routines.build_subscription_routine_coordinator",
        lambda: AtomicFallbackCoordinator(),
    )
    with patch.dict(os.environ, _BASE_ENV):
        response = TestClient(ws.app, raise_server_exceptions=True).post(
            "/internal/routine-fallback",
            json={"correlation_id": "fallback-json-safe"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "published_fallback"
    assert isinstance(payload["run"]["updated_at"], str)
    assert payload["review"]["review_text"] == "Serializable deterministic fallback."


@pytest.fixture(scope="module")
def _ws_module():
    """Module-scoped import of interfaces.web_server with stubs applied.

    WHY: re-importing web_server in each test triggers a CPython 3.14 segfault
    when repeated more than ~5
    times in one process — the dotenv module's NamedTuple machinery
    interacts badly with the GC during repeated module-deletion. Cache
    the import at module scope and rely on per-test environment patches.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from interfaces.routes import sync as sync_routes
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

        with patch("interfaces.routes.sync._log_cron_run", _fake_log):
            with patch.dict(os.environ, env), patch(
                "memory.firestore_db.MealStore", mock_store_cls
            ):
                client = TestClient(ws.app)
                resp = client.post(
                    "/cron/healthkit-sync",
                    json=fixture,
                    headers={"Authorization": f"Bearer {_VALID_HEALTHKIT_TOKEN}"},
                )

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

        with patch("interfaces.routes.sync._log_cron_run", _fake_log):
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

    def test_handler_runs_without_conversation_runtime(self, monkeypatch, _ws_module):
        """The retained handler is an upsert-only data boundary."""
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
            resp = client.post("/cron/healthkit-sync", json={"samples": []})

        assert resp.status_code == 200, (
            f"Retained data handler failed without a conversation runtime: {resp.status_code}: {resp.text}"
        )


# --------------------------------------------------------------------------- #
# TestSPAMountRegression — Phase 26 HUB-04 / threat T-26-01-01                 #
# The SPAStaticFiles catch-all is mounted at "/" as the absolute last route.  #
# It must NOT shadow existing API/cron routes like /health.                    #
# --------------------------------------------------------------------------- #


class TestSPAMountRegression:
    """Prove the SPA catch-all mount does not shadow real routes (HUB-04)."""

    def test_health_still_works(self, monkeypatch):
        """With the SPA mount ACTIVE, GET /health still returns 200.

        The ``app.mount("/", SPAStaticFiles(...))`` only activates when
        ``frontend/dist`` exists, so create a minimal ``index.html`` first —
        this makes the test exercise the real catch-all and stay portable to
        CI, where ``frontend/dist`` is gitignored and absent.
        """
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dist_dir = os.path.join(repo_root, "frontend", "dist")
        index_html = os.path.join(dist_dir, "index.html")
        made_dir = not os.path.isdir(dist_dir)
        os.makedirs(dist_dir, exist_ok=True)
        made_index = not os.path.exists(index_html)
        if made_index:
            with open(index_html, "w", encoding="utf-8") as fh:
                fh.write("<!doctype html><title>Klaus</title>")

        try:
            stubs = _stub_web_server_imports()
            with patch.dict(sys.modules, stubs):
                import interfaces.web_server as ws  # noqa: PLC0415
                from interfaces.routes import sync as sync_routes
                from fastapi.testclient import TestClient  # noqa: PLC0415

                # The SPA catch-all must be registered — otherwise this test
                # would silently pass without exercising shadow-protection.
                assert any(
                    getattr(route, "name", None) == "spa" for route in ws.app.routes
                ), "SPA mount not registered; test would not prove shadow-protection"

                with patch.dict(os.environ, _BASE_ENV):
                    client = TestClient(ws.app)
                    resp = client.get("/health")

            assert resp.status_code == 200, (
                f"/health shadowed by SPA mount: {resp.status_code}: {resp.text}"
            )
            assert resp.json() == {"status": "ok"}
        finally:
            if made_index and os.path.exists(index_html):
                os.remove(index_html)
            if made_dir and os.path.isdir(dist_dir):
                try:
                    os.rmdir(dist_dir)
                except OSError:
                    pass

    def test_health_inventory_reports_registered_routes_and_connectors(self):
        """The drift endpoint reflects the running app rather than a manifest copy."""
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from interfaces.routes import sync as sync_routes
            from fastapi.testclient import TestClient  # noqa: PLC0415

            registered_tools = {
                "list_calendar_events",
                "create_calendar_event",
                "task_list",
                "task_create",
                "fetch_garmin_today",
                "get_strength_progress",
                "fetch_weather",
                "recall",
                "remember",
                "query_health_database",
                "get_routine_status",
                "get_push_health",
            }
            manager = lambda tools: type(
                "ToolManager", (), {"_tools": {name: object() for name in tools}}
            )()
            server = lambda tools: type(
                "Server", (), {"_tool_manager": manager(tools)}
            )()
            ws._mcp_bundle = type(
                "Bundle",
                (),
                {
                    "interactive": server(registered_tools),
                    "routine": server(registered_tools),
                },
            )()
            response = TestClient(ws.app).get("/health/inventory")

        assert response.status_code == 200
        payload = response.json()
        assert "GET /health/inventory" in payload["observed_routes"]
        assert "POST /telegram-webhook" in payload["observed_routes"]
        assert "POST /telegram-webhook" in payload["tombstones"]
        assert "calendar" in payload["connectors"]
        assert "postgresql" in payload["connectors"]

    def test_root_serves_spa_index_and_falls_back_for_client_routes(self):
        """GET / (and unknown client-side routes) must serve index.html, not 500.

        Regression for the production 500 "cannot unpack non-iterable coroutine
        object": SPAStaticFiles.lookup_path was declared `async`, but Starlette's
        StaticFiles.lookup_path is synchronous (get_response calls it via
        anyio.to_thread.run_sync). The async override returned an un-awaited
        coroutine and 500'd every page load. TestClient defaults to
        raise_server_exceptions=True, so a regression surfaces as a test error.
        """
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dist_dir = os.path.join(repo_root, "frontend", "dist")
        index_html = os.path.join(dist_dir, "index.html")
        made_dir = not os.path.isdir(dist_dir)
        os.makedirs(dist_dir, exist_ok=True)
        made_index = not os.path.exists(index_html)
        if made_index:
            with open(index_html, "w", encoding="utf-8") as fh:
                fh.write("<!doctype html><title>Klaus</title><div id=root></div>")

        try:
            stubs = _stub_web_server_imports()
            with patch.dict(sys.modules, stubs):
                import interfaces.web_server as ws  # noqa: PLC0415
                from interfaces.routes import sync as sync_routes
                from fastapi.testclient import TestClient  # noqa: PLC0415

                assert any(
                    getattr(route, "name", None) == "spa" for route in ws.app.routes
                ), "SPA mount not registered; test would not exercise SPA serving"

                with patch.dict(os.environ, _BASE_ENV):
                    client = TestClient(ws.app)
                    root = client.get("/")
                    # Unknown path with no matching file → React Router fallback.
                    deep = client.get("/today/anything")

            assert root.status_code == 200, (
                f"GET / did not serve the SPA shell: {root.status_code}: {root.text}"
            )
            assert "Klaus" in root.text
            assert deep.status_code == 200, (
                f"client-side route did not fall back to index.html: {deep.status_code}"
            )
            assert "Klaus" in deep.text
        finally:
            if made_index and os.path.exists(index_html):
                os.remove(index_html)
            if made_dir and os.path.isdir(dist_dir):
                try:
                    os.rmdir(dist_dir)
                except OSError:
                    pass


# --------------------------------------------------------------------------- #
# TestAuthGoogleCookie — Phase 26 HUB-01                                       #
# /api/auth/google must actually deliver the Set-Cookie header on the response #
# it returns. Setting the cookie on an injected `response: Response` and then  #
# returning a new JSONResponse silently drops the header — the browser stores  #
# no cookie and every subsequent /api/* call 401s.                            #
# --------------------------------------------------------------------------- #


# ---------------------------------------------------------------------------
# TestTaskRoutes — Phase 27 Plan 02: /api/tasks* + /api/task-lists* CRUD
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared helpers for TestTaskRoutes
# ---------------------------------------------------------------------------

def _make_task_store_mock(
    created: dict | None = None,
    listed: list | None = None,
    gotten: dict | None = None,
    updated: dict | None = None,
    summary: dict | None = None,
    next_id: str | None = None,
) -> MagicMock:
    """Return a MagicMock mimicking TaskStore with sensible defaults."""
    store = MagicMock(name="TaskStore")
    store.create.return_value = created or {
        "id": "task-abc", "title": "Test", "status": "active", "list_id": "inbox"
    }
    store.list.return_value = listed if listed is not None else [
        {"id": "task-abc", "title": "Test", "status": "active"}
    ]
    store.get.return_value = gotten  # None by default — caller sets as needed
    store.update.return_value = updated or {
        "id": "task-abc", "title": "Updated", "status": "active"
    }
    store.complete.return_value = {"next_id": next_id}
    store.undo_complete.return_value = None
    store.delete.return_value = None
    store.get_summary.return_value = summary or {"due_today": 2, "overdue": 1}
    return store


def _make_list_store_mock(
    created: dict | None = None,
    listed: list | None = None,
    renamed: dict | None = None,
) -> MagicMock:
    """Return a MagicMock mimicking TaskListStore with sensible defaults."""
    store = MagicMock(name="TaskListStore")
    store.create_list.return_value = created or {"id": "list-xyz", "name": "Work"}
    store.list_lists.return_value = listed if listed is not None else [
        {"id": "list-xyz", "name": "Work"}
    ]
    store.rename_list.return_value = renamed or {"id": "list-xyz", "name": "Renamed"}
    store.delete_list.return_value = None
    return store


class TestTaskRoutes:
    """Integration tests for /api/tasks* CRUD + summary routes.

    Covers TASK-01 and TASK-07:
      - POST   /api/tasks                  → create a task
      - GET    /api/tasks                  → list active tasks
      - GET    /api/tasks?list_id=X        → filtered list
      - PATCH  /api/tasks/{id}             → update a task
      - POST   /api/tasks/{id}/complete    → soft-mark completing
      - POST   /api/tasks/{id}/undo        → revert to active
      - POST   /api/tasks/{id}/hard-delete → hard-delete (gated on status=completing)
      - GET    /api/tasks/summary          → {due_today, overdue} counts
      - POST   /api/task-lists             → create a task list
      - GET    /api/task-lists             → list all task lists (Inbox prepended)
      - PATCH  /api/task-lists/{id}        → rename a list
      - DELETE /api/task-lists/{id}        → delete a list

    Auth: all routes require a valid session cookie (require_hub_session Depends).
    T-27-AC: unauthenticated requests → 401.
    T-27-IV: invalid input → 422/400.
    T-27-REP: hard-delete on non-completing task → 409.
    """

    def _build_client(self, task_store=None, list_store=None, authed=True):
        """Yield (TestClient, ws_module, hub_auth_module) with patched stores.

        When authed=True, require_hub_session is overridden to return the test
        email without a real cookie check.  When authed=False the dependency is
        left unoverridden so the real cookie-check runs and rejects the request.
        """
        from fastapi.testclient import TestClient  # noqa: PLC0415

        stubs = _stub_web_server_imports()
        task_store = task_store or _make_task_store_mock()
        list_store = list_store or _make_list_store_mock()

        def _patched_task_store(*args, **kwargs):
            return task_store

        def _patched_list_store(*args, **kwargs):
            return list_store

        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from interfaces.routes import sync as sync_routes
            import interfaces.hub_auth as hub_auth  # noqa: PLC0415

            with patch("memory.firestore_db.get_task_store", side_effect=_patched_task_store):
                with patch.dict(os.environ, _BASE_ENV):
                    if authed:
                        ws.app.dependency_overrides[hub_auth.require_hub_session] = (
                            lambda: "amit.grupper@gmail.com"
                        )
                    client = TestClient(ws.app, raise_server_exceptions=True)
                    yield client, ws, hub_auth

    # ------------------------------------------------------------------
    # Task CRUD tests
    # ------------------------------------------------------------------

    def test_post_tasks_returns_200_with_id(self):
        """POST /api/tasks creates a task and returns the stored dict with id."""
        task_store = _make_task_store_mock(
            created={"id": "task-abc", "title": "Buy groceries",
                     "status": "active", "list_id": "inbox"}
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.post("/api/tasks", json={"title": "Buy groceries"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "id" in body
        assert body["title"] == "Buy groceries"

    def test_post_tasks_accepts_v7_planning_fields(self):
        """The task API forwards optional subscription-era planning metadata."""
        task_store = _make_task_store_mock(
            created={"id": "task-v7", "title": "Deep work", "status": "active"}
        )
        payload = {
            "title": "Deep work",
            "estimated_minutes": 90,
            "hard_deadline_at": "2026-08-12T17:00:00+03:00",
            "auto_schedule": True,
            "manual_lock": False,
            "calendar_event_id": "event-123",
        }
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.post("/api/tasks", json=payload)

        assert resp.status_code == 200, resp.text
        stored = task_store.create.call_args.args[0]
        assert stored["estimated_minutes"] == 90
        assert stored["hard_deadline_at"] == "2026-08-12T17:00:00+03:00"
        assert stored["auto_schedule"] is True
        assert stored["manual_lock"] is False
        assert stored["calendar_event_id"] == "event-123"

    def test_post_tasks_rejects_non_positive_estimate(self):
        """Scheduling duration must be a useful positive number of minutes."""
        for client, _ws, _ha in self._build_client():
            resp = client.post(
                "/api/tasks", json={"title": "Impossible", "estimated_minutes": 0}
            )
        assert resp.status_code == 422

    def test_post_tasks_empty_title_rejected(self):
        """POST /api/tasks with title='' → 422 (Pydantic min_length=1 violated)."""
        for client, _ws, _ha in self._build_client():
            resp = client.post("/api/tasks", json={"title": ""})
        assert resp.status_code in (400, 422), (
            f"Expected 400/422, got {resp.status_code}: {resp.text}"
        )

    def test_post_tasks_malformed_due_date_rejected(self):
        """POST /api/tasks with due_date='2026/06/20' → 422 (regex reject)."""
        for client, _ws, _ha in self._build_client():
            resp = client.post(
                "/api/tasks", json={"title": "Task", "due_date": "2026/06/20"}
            )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422, got {resp.status_code}: {resp.text}"
        )

    def test_get_tasks_returns_active_tasks(self):
        """GET /api/tasks returns {tasks: [...]} containing the active task list."""
        task_store = _make_task_store_mock(
            listed=[{"id": "t1", "title": "Alpha", "status": "active"}]
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.get("/api/tasks")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "tasks" in body
        assert isinstance(body["tasks"], list)
        assert len(body["tasks"]) == 1

    def test_get_tasks_by_list_id_filters(self):
        """GET /api/tasks?list_id=inbox calls TaskStore.list(list_id='inbox')."""
        task_store = _make_task_store_mock(
            listed=[{"id": "t1", "title": "Inbox task",
                     "status": "active", "list_id": "inbox"}]
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.get("/api/tasks?list_id=inbox")
        assert resp.status_code == 200, resp.text
        task_store.list.assert_called_once_with(list_id="inbox")

    def test_get_tasks_summary_returns_due_today_and_overdue(self):
        """GET /api/tasks/summary returns {due_today: int, overdue: int}."""
        task_store = _make_task_store_mock(summary={"due_today": 3, "overdue": 2})
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.get("/api/tasks/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "due_today" in body
        assert "overdue" in body
        assert isinstance(body["due_today"], int)
        assert isinstance(body["overdue"], int)

    def test_patch_tasks_updates_title(self):
        """PATCH /api/tasks/{id} with {title: 'New'} returns the updated task."""
        task_store = _make_task_store_mock(
            updated={"id": "task-abc", "title": "New title", "status": "active"}
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.patch("/api/tasks/task-abc", json={"title": "New title"})
        assert resp.status_code == 200, resp.text
        assert resp.json().get("title") == "New title"

    def test_patch_tasks_accepts_v7_planning_fields(self):
        """PATCH keeps the new fields backward-compatible and optional."""
        task_store = _make_task_store_mock(
            updated={"id": "task-abc", "title": "Task", "manual_lock": True}
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.patch(
                "/api/tasks/task-abc",
                json={"estimated_minutes": 30, "manual_lock": True, "auto_schedule": False},
            )

        assert resp.status_code == 200, resp.text
        patch_arg = task_store.update.call_args.args[1]
        assert patch_arg == {
            "estimated_minutes": 30,
            "auto_schedule": False,
            "manual_lock": True,
        }

    def test_post_tasks_complete_returns_next_id(self):
        """POST /api/tasks/{id}/complete → {next_id: str|None}."""
        task_store = _make_task_store_mock(next_id="task-next-123")
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.post("/api/tasks/task-abc/complete")
        assert resp.status_code == 200, resp.text
        assert "next_id" in resp.json()

    def test_post_tasks_undo_reverts_to_active(self):
        """POST /api/tasks/{id}/undo → 200 ok."""
        for client, _ws, _ha in self._build_client():
            resp = client.post("/api/tasks/task-abc/undo")
        assert resp.status_code == 200, resp.text

    def test_post_tasks_hard_delete_on_active_task_returns_409(self):
        """POST /api/tasks/{id}/hard-delete on status='active' → 409 (T-27-REP)."""
        task_store = _make_task_store_mock(
            gotten={"id": "task-abc", "title": "Active task", "status": "active"}
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.post(
                "/api/tasks/task-abc/hard-delete",
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 409, (
            f"Expected 409, got {resp.status_code}: {resp.text}"
        )

    def test_post_tasks_hard_delete_on_completing_task_returns_200(self):
        """POST /api/tasks/{id}/hard-delete on status='completing' → 200."""
        task_store = _make_task_store_mock(
            gotten={"id": "task-abc", "title": "Done task", "status": "completing"}
        )
        for client, _ws, _ha in self._build_client(task_store=task_store):
            resp = client.post("/api/tasks/task-abc/hard-delete")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        task_store.delete.assert_called_once_with("task-abc")

    # ------------------------------------------------------------------
    # Auth gate tests (T-27-AC)
    # ------------------------------------------------------------------

    def test_tasks_routes_require_hub_session_401(self):
        """Unauthenticated GET /api/tasks → 401 (T-27-AC)."""
        from fastapi.testclient import TestClient  # noqa: PLC0415

        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from interfaces.routes import sync as sync_routes
            import interfaces.hub_auth as hub_auth  # noqa: PLC0415

            def _no_session():
                raise HTTPException(status_code=401, detail="Not authenticated")

            with patch.dict(os.environ, _BASE_ENV):
                # Override to reject — simulates missing/invalid session cookie.
                ws.app.dependency_overrides[hub_auth.require_hub_session] = _no_session
                client = TestClient(ws.app, raise_server_exceptions=False)
                resp = client.get("/api/tasks")

        assert resp.status_code == 401, (
            f"Expected 401, got {resp.status_code}: {resp.text}"
        )

    # ------------------------------------------------------------------
    # Task-list CRUD tests
    # ------------------------------------------------------------------

    def test_post_task_lists_creates_a_list(self):
        """POST /api/task-lists creates a user-defined task list."""
        list_store = _make_list_store_mock(
            created={"id": "list-xyz", "name": "Work"}
        )
        for client, _ws, _ha in self._build_client(task_store=list_store):
            resp = client.post("/api/task-lists", json={"name": "Work"})
        assert resp.status_code == 200, resp.text
        assert resp.json().get("name") == "Work"

    def test_get_task_lists_prepends_inbox(self):
        """GET /api/task-lists returns Inbox as first element, then user lists."""
        list_store = _make_list_store_mock(
            listed=[{"id": "list-xyz", "name": "Work"}]
        )
        for client, _ws, _ha in self._build_client(task_store=list_store):
            resp = client.get("/api/task-lists")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "lists" in body
        lists = body["lists"]
        assert lists[0]["id"] == "inbox", f"Expected inbox first, got: {lists}"
        assert lists[0]["name"] == "Inbox"
        assert len(lists) == 2  # Inbox + Work

    def test_patch_task_lists_renames_a_list(self):
        """PATCH /api/task-lists/{id} renames and returns the updated list."""
        list_store = _make_list_store_mock(
            renamed={"id": "list-xyz", "name": "Personal"}
        )
        for client, _ws, _ha in self._build_client(task_store=list_store):
            resp = client.patch("/api/task-lists/list-xyz", json={"name": "Personal"})
        assert resp.status_code == 200, resp.text
        assert resp.json().get("name") == "Personal"

    def test_delete_task_lists_returns_200(self):
        """DELETE /api/task-lists/{id} removes the list and returns ok."""
        list_store = _make_list_store_mock()
        for client, _ws, _ha in self._build_client(task_store=list_store):
            resp = client.delete("/api/task-lists/list-xyz")
        assert resp.status_code == 200, resp.text
        list_store.delete_list.assert_called_once_with("list-xyz")


class TestAuthGoogleCookie:
    """Prove the sign-in endpoint emits the session Set-Cookie header."""

    def test_signin_emits_session_set_cookie(self, monkeypatch):
        stubs = _stub_web_server_imports()
        env = {
            **_BASE_ENV,
            "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!!",
            "GOOGLE_OAUTH_CLIENT_ID": "fake.apps.googleusercontent.com",
            "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
        }
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws  # noqa: PLC0415
            from interfaces.routes import sync as sync_routes
            import interfaces.hub_auth as hub_auth  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            with patch.dict(os.environ, env):
                # Bypass real Google verification + Firestore version read.
                monkeypatch.setattr(
                    hub_auth, "verify_google_id_token",
                    lambda token: "amit.grupper@gmail.com",
                )
                monkeypatch.setattr(hub_auth, "get_session_version", lambda: 0)

                client = TestClient(ws.app)
                resp = client.post("/api/auth/google", json={"credential": "fake"})

        assert resp.status_code == 200, resp.text
        set_cookie = resp.headers.get("set-cookie", "")
        assert "hub_session=" in set_cookie, (
            f"sign-in did not emit the session cookie header: {dict(resp.headers)!r}"
        )
        assert "httponly" in set_cookie.lower()
        # OAuth authorization starts as a cross-site top-level GET from Claude.
        # Lax sends the Hub identity cookie for that safe navigation while still
        # withholding it from cross-site POST writes.
        assert "samesite=lax" in set_cookie.lower()
