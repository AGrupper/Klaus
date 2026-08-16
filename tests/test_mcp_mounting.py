"""Feature-flag mounting and legacy-runtime isolation for subscription v7."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from tests.test_web_server import _stub_web_server_imports


def _fake_runtime_module():
    from interfaces.mcp.oauth import InMemoryOAuthStore, OAuthAuthorizationService

    service = OAuthAuthorizationService(
        InMemoryOAuthStore(),
        "https://klaus.example.com",
        "amit.grupper@gmail.com",
    )

    async def interactive_probe(_request):
        return JSONResponse({"transport": "interactive"}, status_code=202)

    async def routine_probe(_request):
        return JSONResponse({"transport": "routine"}, status_code=202)

    bundle = MagicMock()
    bundle.interactive.streamable_http_app.return_value = Starlette(
        routes=[Route("/", interactive_probe, methods=["POST"])]
    )
    bundle.routine.streamable_http_app.return_value = Starlette(
        routes=[Route("/", routine_probe, methods=["POST"])]
    )
    runtime = MagicMock()
    runtime.create_production_oauth_service.return_value = service
    runtime.create_production_mcp_bundle.return_value = bundle
    return runtime, bundle


def test_live_and_routine_mcp_mount_independently():
    stubs = _stub_web_server_imports()
    runtime, bundle = _fake_runtime_module()
    stubs["interfaces.mcp.runtime"] = runtime
    env = {
        "KLAUS_MCP_ENABLED": "true",
        "KLAUS_CLAUDE_LIVE_ENABLED": "true",
        "KLAUS_CLAUDE_ROUTINES_ENABLED": "false",
        "KLAUS_LEGACY_RUNTIME_ENABLED": "false",
    }
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws

        # Assert what the connector actually experiences rather than how the
        # routes happen to be registered. Enumerating ``app.routes`` broke
        # twice on FastAPI internals: newer versions wrap ``include_router``
        # results in a router object, so the OAuth metadata route is nested
        # rather than top-level and a structural check either crashes or
        # silently misses it. A request cannot be fooled either way.
        with TestClient(ws.app) as client:
            interactive = client.post("/mcp/interactive")
            routine = client.post("/mcp/routine")
            metadata = client.get("/.well-known/oauth-authorization-server")

    assert interactive.status_code == 202
    # NOT a specific status: what matters is that the request never reached a
    # routine MCP app. The exact rejection code depends on whether frontend/dist
    # happens to be built — with the SPA mounted, StaticFiles catches every
    # unmatched request and answers POST with 405; without it, Starlette answers
    # 404. CI builds the frontend *after* pytest, so pinning 404 passed there and
    # failed on any developer machine that had run `npm run build`.
    assert routine.status_code != 202
    assert metadata.status_code == 200
    bundle.interactive.streamable_http_app.assert_called_once()
    bundle.routine.streamable_http_app.assert_not_called()


def test_cloud_service_can_start_without_telegram_when_legacy_runtime_is_off():
    stubs = _stub_web_server_imports()
    env = {
        "KLAUS_MCP_ENABLED": "false",
        "KLAUS_LEGACY_RUNTIME_ENABLED": "false",
    }
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws

        with TestClient(ws.app) as client:
            response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_advertised_mcp_urls_accept_post_without_trailing_slash():
    """The public connector URLs must not fall through to the Hub SPA."""
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
        runtime, _bundle = _fake_runtime_module()
        stubs["interfaces.mcp.runtime"] = runtime
        env = {
            "KLAUS_MCP_ENABLED": "true",
            "KLAUS_CLAUDE_LIVE_ENABLED": "true",
            "KLAUS_CLAUDE_ROUTINES_ENABLED": "true",
            "KLAUS_LEGACY_RUNTIME_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws

            with TestClient(ws.app) as client:
                interactive = client.post("/mcp/interactive", json={})
                routine = client.post("/mcp/routine", json={})

        assert interactive.status_code == 202
        assert interactive.json() == {"transport": "interactive"}
        assert routine.status_code == 202
        assert routine.json() == {"transport": "routine"}
    finally:
        if made_index and os.path.exists(index_html):
            os.remove(index_html)
        if made_dir and os.path.isdir(dist_dir):
            try:
                os.rmdir(dist_dir)
            except OSError:
                pass
