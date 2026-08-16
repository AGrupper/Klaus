"""Modular route handlers for the Klaus service.

Each module owns one surface — the Hub's tasks, the Hub's habits, the cron jobs,
the quarantine tombstones — and exposes an ``APIRouter`` named ``router``.
``interfaces/web_server.py`` composes them into the application.

One rule keeps this working: **never import ``interfaces.web_server`` at module
level.** The web server imports these modules, so a top-level import back into
it is a cycle. Where a handler genuinely needs something from the composition
root, import it inside the function — the same lazy-import pattern used
throughout this codebase for stores and tools.

**Enumerating routes:** use :func:`iter_routes`, never a bare loop over
``app.routes``. In FastAPI 0.141 ``include_router`` stores its routes behind a
private ``_IncludedRouter`` object rather than flattening them, so a plain walk
silently misses every route that arrived through a router. Klaus reads that list
for real work — ``_runtime_inventory`` builds ``/health/inventory`` from it, and
``test_runtime_subtraction`` asserts the exact ``(method, path) -> endpoint`` map
of the 410 tombstones — and enumerating ``app.routes`` has already broken twice
on FastAPI internals in this repository. Keeping the traversal in one function
means the next version bump has one place to fix.
"""
from __future__ import annotations

from typing import Iterator


def iter_routes(container) -> Iterator:
    """Yield every route reachable from an app or router, descending into includes.

    Args:
        container: A ``FastAPI`` app, an ``APIRouter``, or anything else with a
            ``routes`` attribute.

    Yields:
        Route objects — ``APIRoute``, ``Route`` and ``Mount`` alike. Callers
        filter by ``getattr(route, "methods", None)`` as they always have.
    """
    for route in getattr(container, "routes", []):
        # An included router hides its real routes here. Descend rather than
        # yielding the wrapper, which has neither a path nor an endpoint.
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from iter_routes(included)
        else:
            yield route
