"""Every Hub API route must be behind the session gate.

The existing auth test covers one route. That is enough to prove the gate
works and not enough to prove it is applied: a new `/api/*` route added
without the dependency ships unguarded, and nothing fails. The Hub is Amit's
whole life dashboard on a public URL, so "we remembered on this one" is not
the property worth testing — "it is impossible to forget" is.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from tests.test_web_server import _stub_web_server_imports, _BASE_ENV


# Routes that are public by design. Each needs a reason, because adding to this
# list is how the gate gets quietly disabled.
PUBLIC_API_ROUTES = {
    "/api/auth/google",           # sign-in itself: no session exists yet
    "/api/auth/logout",           # clearing a cookie must work without a valid one
    "/api/auth/me",               # the frontend's "am I signed in?" probe
    "/api/push/vapid-public-key",  # public key by definition
    # Retired chat surfaces. These are 410 Gone tombstones that answer every
    # caller identically and touch no data, so a session would gate nothing.
    "/api/chat",
    "/api/chat/messages",
    "/api/chat/regenerate",
    "/api/chat/stop",
    "/api/chat/upload",
}


def _api_routes(app):
    """Return (path, route) for every API route, however FastAPI nests them.

    Traversal is shared with production code (``interfaces.routes.iter_routes``),
    which is the point: newer FastAPI hides ``include_router`` results behind a
    wrapper exposing ``original_router`` rather than ``routes``, so a walker that
    guesses the attribute name finds nothing and this guard passes vacuously.
    Assuming a flat list is what broke the MCP mount test twice.
    """
    from interfaces.routes import iter_routes

    return [
        (route.path, route)
        for route in iter_routes(app)
        if getattr(route, "path", None) and getattr(route, "dependant", None) is not None
    ]


def _depends_on(route, target) -> bool:
    """True when ``target`` appears anywhere in the route's dependency tree."""
    seen = []

    def visit(dependant):
        for dependency in getattr(dependant, "dependencies", []):
            seen.append(getattr(dependency, "call", None))
            visit(dependency)

    visit(route.dependant)
    return target in seen


def test_every_hub_api_route_requires_a_session():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs), patch.dict(os.environ, _BASE_ENV):
        import interfaces.web_server as ws
        import interfaces.hub_auth as hub_auth

        unguarded = sorted(
            {
                path
                for path, route in _api_routes(ws.app)
                if path.startswith("/api/")
                and path not in PUBLIC_API_ROUTES
                and not _depends_on(route, hub_auth.require_hub_session)
            }
        )

    assert unguarded == [], (
        "these /api routes are reachable without a Hub session: "
        f"{unguarded}. Add the require_hub_session dependency, or add the "
        "route to PUBLIC_API_ROUTES with a reason if it is public by design."
    )


def test_the_route_walker_actually_finds_the_hub_api():
    """Guard the guard: a walker that finds nothing would pass vacuously."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs), patch.dict(os.environ, _BASE_ENV):
        import interfaces.web_server as ws

        api_paths = {p for p, _ in _api_routes(ws.app) if p.startswith("/api/")}

    assert "/api/today" in api_paths
    assert "/api/tasks" in api_paths
    assert len(api_paths) >= 20, f"only found {len(api_paths)} API routes"


def test_api_responses_are_marked_no_store():
    """Every /api response carries Cache-Control: no-store.

    The Hub is a live dashboard — /api/today reads Garmin, Google Calendar and
    the weather per request — but no route set a cache header, leaving freshness
    to browser and intermediary heuristics. Applied as middleware so a new route
    cannot forget it, which is what this asserts.
    """
    from fastapi.testclient import TestClient

    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs), patch.dict(os.environ, _BASE_ENV):
        import interfaces.web_server as ws

        client = TestClient(ws.app, raise_server_exceptions=False)
        # An unauthenticated call is enough: middleware runs on the way out
        # regardless of the status code.
        api_response = client.get("/api/today")
        assert api_response.headers.get("Cache-Control") == "no-store"

        # Hashed SPA assets must stay cacheable — the header is scoped to /api.
        root_response = client.get("/")
        assert root_response.headers.get("Cache-Control") != "no-store"


def test_session_version_is_cached_and_dropped_on_revoke():
    """The revocation counter is read once per TTL, not once per request.

    get_session_version() is a blocking Firestore read inside the dependency that
    guards EVERY /api route — roughly eight reads per Hub page load. Caching it is
    only safe if revoke-all still takes effect immediately, so both halves are
    asserted here.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs), patch.dict(os.environ, _BASE_ENV):
        import interfaces.hub_auth as hub_auth

        store = MagicMock()
        store.load.return_value = {"session_version": 3}
        hub_auth.invalidate_session_version_cache()

        with patch("memory.firestore_db.UserProfileStore", return_value=store):
            assert hub_auth.get_session_version() == 3
            assert hub_auth.get_session_version() == 3
            assert hub_auth.get_session_version() == 3
            assert store.load.call_count == 1

            # Revoking must not wait for the TTL to expire.
            store.load.return_value = {"session_version": 4}
            hub_auth.invalidate_session_version_cache()
            assert hub_auth.get_session_version() == 4
            assert store.load.call_count == 2

        hub_auth.invalidate_session_version_cache()
