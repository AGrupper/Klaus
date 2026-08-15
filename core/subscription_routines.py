"""Claude subscription routine triggers and deterministic timeout fallback."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from core.review_delivery import (
    normalise_claude_session_url,
    routine_review_path,
    routine_review_title,
)


_MODELS = {"morning": "sonnet", "nightly": "sonnet", "weekly": "opus"}


def routine_correlation_id(
    routine: str, target_date: str, delivery_mode: str = "live",
) -> str:
    """Stable per-routine/date identifier used for trigger and callback dedup."""
    suffix = "" if delivery_mode == "live" else f":{delivery_mode}"
    return hashlib.sha256(
        f"{routine}:{target_date}{suffix}".encode("utf-8")
    ).hexdigest()[:32]


class SubscriptionRoutineCoordinator:
    """Coordinate remote Claude reasoning without any generative-model API key."""

    def __init__(
        self,
        *,
        run_store,
        review_store,
        remote_fire: Callable[[dict], dict],
        enqueue_fallback: Callable[[str, int], bool],
        snapshot_builder: Callable[[], Any],
        push_sender: Callable[[str, str, str, str], dict],
        public_url: str,
        callback_timeout_seconds: int = 600,
    ) -> None:
        self._runs = run_store
        self._reviews = review_store
        self._remote_fire = remote_fire
        self._enqueue_fallback = enqueue_fallback
        self._snapshot_builder = snapshot_builder
        self._push_sender = push_sender
        self._public_url = public_url.rstrip("/")
        self._timeout = callback_timeout_seconds

    def start(
        self,
        routine: str,
        target_date: str,
        trigger: str,
        *,
        delivery_mode: str = "live",
    ) -> dict:
        """Persist pending state, schedule fallback, then fire Remote Routine."""
        if routine not in _MODELS:
            raise ValueError(f"unsupported subscription routine: {routine}")
        if delivery_mode not in {"live", "shadow"}:
            raise ValueError("delivery_mode must be live or shadow")
        correlation_id = routine_correlation_id(routine, target_date, delivery_mode)
        existing = self._runs.get(correlation_id)
        if existing:
            return {
                "accepted": True,
                "deduplicated": True,
                "correlation_id": correlation_id,
                "status": existing.get("status"),
                "model": _MODELS[routine],
            }

        started = self._runs.start(
            routine=routine,
            target_date=target_date,
            trigger=trigger,
            correlation_id=correlation_id,
            callback_timeout_seconds=self._timeout,
            delivery_mode=delivery_mode,
        )
        if started.get("created") is False:
            return {
                "accepted": True,
                "deduplicated": True,
                "correlation_id": correlation_id,
                "status": started.get("status"),
                "model": _MODELS[routine],
            }
        fallback_scheduled = self._enqueue_fallback(correlation_id, self._timeout)
        if not fallback_scheduled:
            self._runs.transition(
                correlation_id,
                "failed",
                error="could not schedule deterministic timeout fallback",
                fallback_scheduled=False,
            )
            return {
                "accepted": False,
                "deduplicated": False,
                "correlation_id": correlation_id,
                "status": "failed",
                "model": _MODELS[routine],
                "error": "fallback dispatch unavailable",
            }

        payload = {
            "correlation_id": correlation_id,
            "routine": routine,
            "target_date": target_date,
            "trigger": trigger,
            "model": _MODELS[routine],
            "mcp_url": f"{self._public_url}/mcp/routine",
            "skill_version": "7.3.1",
            "delivery_mode": delivery_mode,
        }
        try:
            remote_result = self._remote_fire(payload)
            transition_fields = {
                "fallback_scheduled": True,
                "remote_trigger_result": remote_result,
            }
            session_url = normalise_claude_session_url(
                remote_result.get("claude_code_session_url")
                if isinstance(remote_result, dict)
                else None
            )
            if session_url:
                transition_fields["claude_session_url"] = session_url
            self._runs.transition(
                correlation_id,
                "running",
                **transition_fields,
            )
            provider_fired = True
        except Exception as exc:
            # The scheduled deterministic path still guarantees publication.
            self._runs.patch(
                correlation_id,
                fallback_scheduled=True,
                remote_trigger_error=f"{type(exc).__name__}: {exc}"[:1000],
            )
            provider_fired = False

        return {
            "accepted": True,
            "deduplicated": False,
            "correlation_id": correlation_id,
            "status": "running" if provider_fired else "queued",
            "model": _MODELS[routine],
            "provider_fired": provider_fired,
            "fallback_scheduled": True,
        }

    async def publish_timeout_fallback(self, correlation_id: str) -> dict:
        """Publish a no-judgment review if Claude missed its callback deadline."""
        run = self._runs.get(correlation_id)
        if not run:
            raise ValueError("routine run not found")
        if run.get("status") not in {"queued", "running"}:
            return {
                "deduplicated": True,
                "status": run.get("status"),
                "correlation_id": correlation_id,
            }
        deadline = datetime.fromisoformat(
            str(run["callback_deadline_at"]).replace("Z", "+00:00")
        )
        if deadline > datetime.now(timezone.utc):
            return {
                "deduplicated": True,
                "status": run.get("status"),
                "correlation_id": correlation_id,
                "reason": "callback deadline has not elapsed",
            }

        if inspect.iscoroutinefunction(self._snapshot_builder):
            snapshot = await self._snapshot_builder()
        else:
            snapshot = await asyncio.to_thread(self._snapshot_builder)
            if inspect.isawaitable(snapshot):
                snapshot = await snapshot
        text = deterministic_review_text(run["routine"], snapshot)
        if run.get("delivery_mode") == "shadow":
            transitioned = await asyncio.to_thread(
                self._runs.transition,
                correlation_id,
                "published_fallback",
                shadow_review={
                    "text": text,
                    "fallback": True,
                    "judgment_writes": False,
                },
            )
            return {
                **transitioned,
                "review": transitioned.get("shadow_review"),
                "delivery": {"shadow": True, "push_sent": False},
            }
        review_fields = {
            "text": text,
            "structured": {
                "fallback": True,
                "reason": "Claude callback timed out after 10 minutes",
                "snapshot_generated": True,
                "judgment_writes": False,
            },
            "action_ids": [],
            "partial_actions": [],
        }
        session_url = normalise_claude_session_url(run.get("claude_session_url"))
        if session_url:
            review_fields["claude_session_url"] = session_url
        publication = await asyncio.to_thread(
            self._runs.publish_review_atomic,
            correlation_id,
            publisher="fallback",
            **review_fields,
        )
        transitioned = publication["run"]
        if not publication["committed"]:
            return {
                "deduplicated": True,
                "status": transitioned.get("status"),
                "correlation_id": correlation_id,
            }
        review = publication["review"]
        delivery = await asyncio.to_thread(
            self._push_sender,
            review["review_text"],
            "briefing",
            routine_review_path(run["routine"], run["target_date"]),
            routine_review_title(run["routine"]),
        )
        return {**transitioned, "review": review, "delivery": delivery}


def deterministic_review_text(routine: str, snapshot: dict) -> str:
    """Render factual fallback text without recommendations or state changes."""
    today = snapshot.get("today") or {}
    calendar = today.get("calendar") or {}
    timed_count = len(calendar.get("timed") or [])
    task_count = len(snapshot.get("tasks") or [])
    habit_count = len(snapshot.get("habits_pending") or [])
    title = {
        "morning": "Morning status",
        "nightly": "Nightly status",
        "weekly": "Weekly status",
    }.get(routine, "Klaus status")
    return (
        f"{title}, Sir. Claude did not return before the review deadline. "
        f"Klaus currently sees {timed_count} timed calendar item(s), "
        f"{task_count} active task(s), and {habit_count} pending habit(s). "
        "No schedule, task, training, or memory changes were made. "
        "The review will be enriched silently if Claude finishes later."
    )


def fire_remote_claude_routine(payload: dict) -> dict:
    """Call a configured Claude Remote Routine trigger; never a model API."""
    import httpx

    routine = str(payload["routine"]).upper()
    url = os.environ.get(f"CLAUDE_ROUTINE_TRIGGER_URL_{routine}", "")
    if not url:
        raise RuntimeError(f"Claude {routine.lower()} routine trigger URL is not configured")
    token = os.environ.get(f"CLAUDE_ROUTINE_TRIGGER_TOKEN_{routine}") or os.environ.get(
        "CLAUDE_ROUTINE_TRIGGER_TOKEN", ""
    )
    if not token:
        raise RuntimeError(
            f"Claude {routine.lower()} routine trigger token is not configured"
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "anthropic-beta": "experimental-cc-routine-2026-04-01",
        "anthropic-version": "2023-06-01",
    }
    timeout = float(os.environ.get("CLAUDE_ROUTINE_TRIGGER_TIMEOUT_SECONDS", "30"))
    body = {"text": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
    response = httpx.post(url, json=body, headers=headers, timeout=timeout)
    response.raise_for_status()
    if not response.content:
        return {"accepted": True}
    try:
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {"accepted": True}
    except ValueError:
        return {"accepted": True}


def build_subscription_routine_coordinator() -> SubscriptionRoutineCoordinator:
    """Build production dependencies lazily for Cloud Run request handlers."""
    from core.life_snapshot import build_life_snapshot
    from core.push_sender import send_push_to_all
    from core.routine_dispatch import enqueue_routine_fallback
    from memory.firestore_db import RoutineReviewStore, RoutineRunStore

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    public_url = os.environ.get("KLAUS_PUBLIC_URL") or os.environ.get("CLOUD_RUN_URL", "")
    return SubscriptionRoutineCoordinator(
        run_store=RoutineRunStore(project, database),
        review_store=RoutineReviewStore(project, database),
        remote_fire=fire_remote_claude_routine,
        enqueue_fallback=enqueue_routine_fallback,
        snapshot_builder=build_life_snapshot,
        push_sender=send_push_to_all,
        public_url=public_url,
    )
