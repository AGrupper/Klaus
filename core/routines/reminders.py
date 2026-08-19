"""Routine reminders: scheduled notifications, not polled ones.

A reminder's moment is known the instant Amit sets it, so it is scheduled —
one Cloud Task per routine per day, enqueued with an exact ``schedule_time``.
Polling for it (which is what shipped first) can only ever fire on the cron's
grid, which is how a routine anchored at 21:37 waited until 21:40.

Two independent guards keep a time change from producing two notifications:

* ``ReminderScheduleStore`` holds **one document per routine id**, so there is
  nowhere to record a second live task — rescheduling cancels what that
  document names before it creates anything;
* the delivery handler re-reads the routine and drops anything whose
  ``anchor_time`` no longer matches, so a task that survives a failed cancel
  is silent rather than duplicated.

Cloud Tasks client construction mirrors core/routines/dispatch.py.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date as _date, datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

_DELIVERY_PATH = "/internal/routine-reminder"


# --------------------------------------------------------------------------- #
# Pure rules                                                                   #
# --------------------------------------------------------------------------- #

def parse_anchor(value: Any, day: _date) -> datetime | None:
    """Return the Asia/Jerusalem moment an "HH:MM" anchor names on ``day``."""
    try:
        hour, minute = (int(part) for part in str(value or "").split(":"))
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_TZ)


def routine_pending_today(
    members: list[dict], completions_today: dict, today: Any
) -> tuple[int, int]:
    """Return ``(scheduled, completed)`` counts for one day.

    The single-day form of ``day_state`` inside
    ``memory.stores.habits.compute_routine_streak`` — that walks 365 days per
    routine to build a streak, which a reminder has no use for.
    """
    from memory.stores.habits import _is_scheduled

    scheduled = [
        habit for habit in members
        if _is_scheduled(today, habit.get("schedule_history") or [])
    ]
    completed = sum(1 for habit in scheduled if habit.get("id") in completions_today)
    return len(scheduled), completed


def reminder_alert(
    routine: dict, habits: list[dict], completions_today: dict, *, today: _date
) -> dict | None:
    """Return the alert for an unfinished routine, or None if it is silent.

    Silent when the routine is finished and when nothing of it is scheduled
    today — a reminder for a routine already checked off is noise, not a nudge.
    The returned shape matches what ``core.routines.alerts`` delivers, so both
    paths share one push/outreach-log tail.
    """
    routine_id = str(routine.get("id") or "")
    members = [habit for habit in habits if habit.get("routine_id") == routine_id]
    scheduled, completed = routine_pending_today(members, completions_today, today)
    if scheduled == 0 or completed >= scheduled:
        return None
    label = f"{str(routine.get('emoji') or '').strip()} {routine.get('name') or 'Routine'}".strip()
    return {
        "kind": "routine_reminder",
        "topic_key": f"routine-reminder:{routine_id}:{today.isoformat()}",
        "text": f"{label}, Sir — {scheduled - completed} of {scheduled} still open.",
        "message_class": "habit_nudge",
        "destination": "/routines",
    }


# --------------------------------------------------------------------------- #
# Cloud Tasks                                                                  #
# --------------------------------------------------------------------------- #

def _task_config() -> tuple[str, str, str] | None:
    """Return ``(parent, service_url, service_account)`` or None if unconfigured."""
    queue = os.environ.get("CLOUD_TASKS_QUEUE", "")
    project = os.environ.get("GCP_PROJECT_ID", "")
    location = os.environ.get("CLOUD_TASKS_LOCATION", "")
    service_url = os.environ.get("CLOUD_RUN_URL", "").rstrip("/")
    service_account = os.environ.get("CLOUD_SCHEDULER_SA_EMAIL", "")
    if not all((queue, project, location, service_url, service_account)):
        logger.warning("routine reminders: Cloud Tasks is not configured")
        return None
    return (
        f"projects/{project}/locations/{location}/queues/{queue}",
        service_url,
        service_account,
    )


def _store():
    """Lazy ReminderScheduleStore (module-cheap-import discipline)."""
    from memory.firestore_db import ReminderScheduleStore

    return ReminderScheduleStore(
        os.environ.get("GCP_PROJECT_ID", ""),
        os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _delete_task(task_name: str) -> None:
    """Best-effort cancel. A task that is already gone is a success, not an error."""
    if not task_name:
        return
    from google.cloud import tasks_v2

    try:
        tasks_v2.CloudTasksClient().delete_task(name=task_name)
    except Exception:
        # NOT_FOUND (already executed or already deleted) is the common case and
        # is fine. Anything else leaves a task queued, which the handler's
        # anchor_time check then neutralises — so log and carry on rather than
        # refusing to schedule the replacement.
        logger.info("routine reminders: could not delete %s", task_name, exc_info=True)


def cancel_reminder(routine_id: str) -> bool:
    """Cancel whatever is scheduled for this routine and forget it.

    Returns True when something was cancelled. Never raises — a routine being
    deleted or disarmed must not fail on a scheduling hiccup.
    """
    try:
        store = _store()
        existing = store.get(routine_id)
        if not existing:
            return False
        _delete_task(str(existing.get("task_name") or ""))
        store.clear(routine_id)
        return True
    except Exception:
        logger.warning(
            "routine reminders: cancel failed for %s", routine_id, exc_info=True
        )
        return False


def schedule_reminder(
    routine: dict, target_date: _date | str | None = None, *, now: datetime | None = None
) -> dict | None:
    """Schedule this routine's notification for ``target_date``.

    Cancels the routine's existing task first, so the store's one-doc-per-
    routine rule holds at every moment. Returns the stored schedule, or None
    when there is nothing to schedule: the routine is unarmed, has no
    ``anchor_time``, or that moment has already passed.

    Never raises. A failure here leaves the routine without a notification for
    one day; ``/cron/schedule-reminders`` re-arms it the next.
    """
    routine_id = str(routine.get("id") or "")
    if not routine_id:
        return None

    local_now = (now or datetime.now(_TZ)).astimezone(_TZ)
    if target_date is None:
        target_date = local_now.date()
    elif isinstance(target_date, str):
        target_date = _date.fromisoformat(target_date)

    # Always cancel first: disarming, clearing the time and moving the time all
    # have to remove the old task, and only the last of them adds a new one.
    cancel_reminder(routine_id)

    if not routine.get("remind"):
        return None
    fire_at = parse_anchor(routine.get("anchor_time"), target_date)
    if fire_at is None or fire_at <= local_now:
        return None

    config = _task_config()
    if config is None:
        return None
    parent, service_url, service_account = config

    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    schedule = timestamp_pb2.Timestamp()
    schedule.FromDatetime(fire_at)
    body = {
        "routine_id": routine_id,
        "target_date": target_date.isoformat(),
        # Baked in so the handler can tell a live task from one left over by a
        # cancel that did not land.
        "anchor_time": str(routine.get("anchor_time")),
    }
    task = {
        "schedule_time": schedule,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{service_url}{_DELIVERY_PATH}",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body).encode(),
            "oidc_token": {
                "service_account_email": service_account,
                "audience": service_url,
            },
        },
    }
    try:
        created = tasks_v2.CloudTasksClient().create_task(parent=parent, task=task)
    except Exception:
        logger.warning(
            "routine reminders: enqueue failed for %s at %s",
            routine_id, fire_at.isoformat(), exc_info=True,
        )
        return None

    try:
        return _store().upsert(routine_id, {
            "anchor_time": body["anchor_time"],
            "target_date": body["target_date"],
            "scheduled_for": fire_at.isoformat(),
            # The name Cloud Tasks assigned — the only handle we can cancel by.
            "task_name": created.name,
        })
    except Exception:
        # The task exists but we failed to record it, so we can no longer
        # cancel it. Delete it now rather than leave an uncancellable
        # notification queued against a time Amit may be about to change.
        logger.error(
            "routine reminders: could not record %s — rolling the task back",
            routine_id, exc_info=True,
        )
        _delete_task(created.name)
        return None


def schedule_all(target_date: _date | str | None = None, *, now: datetime | None = None) -> dict:
    """Arm every routine for ``target_date`` — the daily re-arm.

    Idempotent through :class:`ReminderScheduleStore`, so re-running it costs
    one cancel and one create per armed routine and changes nothing else. This
    is what makes a lost task self-heal, and what arms routines Amit armed
    while the previous day's window had already passed.
    """
    from memory.firestore_db import RoutineStore

    local_now = (now or datetime.now(_TZ)).astimezone(_TZ)
    if target_date is None:
        target_date = local_now.date()
    elif isinstance(target_date, str):
        target_date = _date.fromisoformat(target_date)

    store = RoutineStore(
        os.environ.get("GCP_PROJECT_ID", ""),
        os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    scheduled = 0
    armed = 0
    for routine in store.list_all():
        if not routine.get("remind"):
            continue
        armed += 1
        if schedule_reminder(routine, target_date, now=local_now) is not None:
            scheduled += 1
    return {"armed": armed, "scheduled": scheduled, "target_date": target_date.isoformat()}


# --------------------------------------------------------------------------- #
# Delivery                                                                     #
# --------------------------------------------------------------------------- #

def deliver_reminder(
    routine_id: str,
    target_date: str,
    anchor_time: str,
    *,
    now: datetime | None = None,
    push_sender=None,
) -> dict:
    """Decide whether this task should still notify, and notify if so.

    Every reason to stay silent is a normal outcome, reported as
    ``{"sent": False, "reason": ...}``. The caller turns that into a 200 so
    Cloud Tasks does not retry a deliberate silence.
    """
    local_now = (now or datetime.now(_TZ)).astimezone(_TZ)
    today = local_now.date()

    from memory.firestore_db import (
        HabitStore,
        OutreachLogStore,
        RoutineStore,
    )

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")

    if target_date != today.isoformat():
        return {"sent": False, "reason": "stale_date"}

    routine = RoutineStore(project, database).get(routine_id)
    if routine is None:
        return {"sent": False, "reason": "routine_gone"}
    if not routine.get("remind"):
        return {"sent": False, "reason": "disarmed"}
    # The guard that makes a failed cancel harmless: this task was enqueued for
    # a time the routine no longer keeps, so it is a leftover, not a reminder.
    if str(routine.get("anchor_time") or "") != anchor_time:
        return {"sent": False, "reason": "time_changed"}

    day = today.isoformat()
    outreach = OutreachLogStore(project, database)
    topic_key = f"routine-reminder:{routine_id}:{day}"
    # Cloud Tasks delivers at least once; the outreach log makes that exactly
    # once, the same way it does for the polled alerts.
    if topic_key in set(outreach.topics_today(day) or []):
        return {"sent": False, "reason": "already_sent"}

    habit_store = HabitStore(project, database)
    alert = reminder_alert(
        routine,
        habit_store.list_active(),
        habit_store.get_completions_for_date(day),
        today=today,
    )
    if alert is None:
        return {"sent": False, "reason": "nothing_open"}

    if push_sender is None:
        from core.push_sender import send_push_to_all

        push_sender = send_push_to_all
    delivery = push_sender(
        alert["text"],
        alert["message_class"],
        alert["destination"],
        "Klaus",
        None,
        # Tag = topic_key, the same id /api/notifications reports as push_tag —
        # reading it in the bell clears the lock screen.
        alert["topic_key"],
    )
    if not isinstance(delivery, dict) or int(delivery.get("sent") or 0) < 1:
        return {"sent": False, "reason": "no_subscription"}

    outreach.append(day, {
        "topic_key": alert["topic_key"],
        "time": local_now.strftime("%H:%M"),
        "final": alert["text"],
        "origin": "scheduled_reminder",
        "kind": alert["kind"],
    })
    return {"sent": True, "topic_key": alert["topic_key"]}
