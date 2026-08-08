"""Feature-flag mounting and legacy-runtime isolation for subscription v7."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.applications import Starlette

from tests.test_web_server import _stub_web_server_imports


def _fake_runtime_module():
    from interfaces.mcp_oauth import InMemoryOAuthStore, OAuthAuthorizationService

    service = OAuthAuthorizationService(
        InMemoryOAuthStore(),
        "https://klaus.example.com",
        "amit.grupper@gmail.com",
    )
    bundle = MagicMock()
    bundle.interactive.streamable_http_app.return_value = Starlette()
    bundle.routine.streamable_http_app.return_value = Starlette()
    runtime = MagicMock()
    runtime.create_production_oauth_service.return_value = service
    runtime.create_production_mcp_bundle.return_value = bundle
    return runtime, bundle


def test_live_and_routine_mcp_mount_independently():
    stubs = _stub_web_server_imports()
    runtime, bundle = _fake_runtime_module()
    stubs["interfaces.mcp_runtime"] = runtime
    env = {
        "KLAUS_MCP_ENABLED": "true",
        "KLAUS_CLAUDE_LIVE_ENABLED": "true",
        "KLAUS_CLAUDE_ROUTINES_ENABLED": "false",
        "KLAUS_LEGACY_RUNTIME_ENABLED": "false",
    }
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws

        paths = {route.path for route in ws.app.routes}

    assert "/mcp/interactive" in paths
    assert "/mcp/routine" not in paths
    assert "/.well-known/oauth-authorization-server" in paths
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
