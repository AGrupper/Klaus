"""Compact provider-neutral Klaus context shared by Hub and Claude MCP."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo


async def _normalized_hub_today() -> dict[str, Any]:
    """Build the exact normalized state used by ``GET /api/today``."""
    # Lazy import avoids a module cycle while web_server is mounting MCP.
    from interfaces import web_server as hub
    from memory.firestore_db import _jsonsafe_doc

    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    calendar, garmin, weather, meals, training, nutrition = await asyncio.gather(
        loop.run_in_executor(None, hub._today_calendar, today_iso),
        loop.run_in_executor(None, hub._today_garmin),
        loop.run_in_executor(None, hub._today_weather),
        loop.run_in_executor(None, hub._today_meals, today_iso),
        loop.run_in_executor(None, hub._today_training, today_iso),
        loop.run_in_executor(None, hub._today_nutrition_totals, today_iso),
    )
    calendar = await loop.run_in_executor(None, hub._today_departure_windows, calendar)
    coach_note = await loop.run_in_executor(None, hub._today_coach_note, today_iso)
    return _jsonsafe_doc(
        {
            "today": today_iso,
            "calendar": calendar,
            "garmin": garmin,
            "weather": weather,
            "meals": meals,
            "training": training,
            "coach_note": coach_note,
            "nutrition_totals": nutrition,
        }
    )


def _default_directives_loader() -> list[dict]:
    from memory.firestore_db import StandingDirectiveStore

    return StandingDirectiveStore(
        os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
        os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
    ).list_active()


def _default_reviews_loader(target_date: str) -> dict[str, Any]:
    from memory.firestore_db import RoutineReviewStore

    store = RoutineReviewStore(
        os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
        os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
    )
    return {routine: store.get(routine, target_date) for routine in ("morning", "nightly", "weekly")}


def _parse_dispatch_result(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": raw}
    return raw


async def _call(loader: Callable[..., Any], *args) -> Any:
    if inspect.iscoroutinefunction(loader):
        return await loader(*args)
    return await asyncio.to_thread(loader, *args)


def _default_profile_loader() -> dict[str, Any]:
    from core.user_profile import profile_block

    return profile_block()


async def build_life_snapshot(
    *,
    today_loader: Callable[[], dict | Awaitable[dict]] | None = None,
    dispatcher: Callable[[str, dict], Any] | None = None,
    directives_loader: Callable[[], list[dict]] | None = None,
    reviews_loader: Callable[[str], dict[str, Any]] | None = None,
    profile_loader: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return compact state first; Claude can lazily retrieve detail afterward."""
    if dispatcher is None:
        from core.tools import dispatch

        dispatcher = dispatch
    today_loader = today_loader or _normalized_hub_today
    directives_loader = directives_loader or _default_directives_loader
    reviews_loader = reviews_loader or _default_reviews_loader
    profile_loader = profile_loader or _default_profile_loader

    today = await _call(today_loader)
    today_iso = str(today.get("today") or datetime.now(ZoneInfo("Asia/Jerusalem")).date())

    tasks_raw, habits_raw, self_raw, directives, reviews = await asyncio.gather(
        asyncio.to_thread(dispatcher, "task_list", {}),
        asyncio.to_thread(dispatcher, "get_habit_adherence", {}),
        asyncio.to_thread(dispatcher, "get_self_status", {}),
        _call(directives_loader),
        _call(reviews_loader, today_iso),
    )
    tasks = _parse_dispatch_result(tasks_raw)
    habits = _parse_dispatch_result(habits_raw)
    self_state = _parse_dispatch_result(self_raw)
    return {
        "schema_version": "klaus.life-snapshot.v2",
        "generated_at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(),
        # Who Amit is. Included on every snapshot so no skill has to restate a
        # fact about him, and so all four skills know the same things. Sourced
        # from docs/USER.md — see core/user_profile.
        "profile": profile_loader(),
        "today": today,
        "tasks": list(tasks if isinstance(tasks, list) else [])[:100],
        "habits_pending": list(habits if isinstance(habits, list) else [])[:50],
        "directives": list(directives or [])[:30],
        "self_state": self_state if isinstance(self_state, dict) else {},
        "reviews": reviews or {},
        "memory": {
            "authoritative_store": "pinecone",
            "conversation_context": "claude_project",
        },
    }
