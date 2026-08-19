"""Deterministic waking-hours alerts for the subscription-first runtime.

This module intentionally contains no LLM client. It only emits explicit,
time-bound reminders, calendar/travel conflicts, and critical infrastructure
failures. Untimed tasks, habits, nutrition, and coaching never create pushes.

The one habit-shaped exception is the routine reminder: a Hub routine Amit has
armed himself (``remind: true``) at a wall-clock time he chose
(``anchor_time``). That is an explicit, time-bound reminder he set — not Klaus
inferring urgency from an untimed habit, which stays forbidden.

There are no quiet hours (removed 2026-08-19 at Amit's request). Every rule
here is already explicit and time-bound — it fires because something he set
came due, never because Klaus decided the moment was interesting — so an
outreach window was suppressing wanted alerts rather than unwanted ones.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo


_TZ = ZoneInfo("Asia/Jerusalem")
_HARD_DEADLINE_WINDOW = timedelta(hours=2)
# How long after its anchor_time a routine reminder may still be delivered.
# A catch-up window rather than an exact match, so a slow or skipped cron
# tick still reminds him; the outreach log keeps it to one push per day.
_REMINDER_WINDOW = timedelta(hours=1)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_TZ)


def _anchor_datetime(value: Any, local_now: datetime) -> datetime | None:
    """Return today's ``local_now``-dated datetime for an "HH:MM" string."""
    try:
        hour, minute = (int(part) for part in str(value or "").split(":"))
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def reminder_window_open(routine: dict, local_now: datetime) -> bool:
    """True when ``routine`` is armed and ``local_now`` sits in its window.

    Cheap and store-free by design: :func:`run_rule_evaluator` calls this to
    decide whether loading habits and completions is worth a Firestore read at
    all, which on a quiet 03:00 tick it never is.
    """
    if not routine.get("remind") or not routine.get("id"):
        return False
    anchor = _anchor_datetime(routine.get("anchor_time"), local_now)
    if anchor is None:
        return False
    end_of_day = local_now.replace(hour=23, minute=59, second=59, microsecond=999999)
    return anchor <= local_now < min(anchor + _REMINDER_WINDOW, end_of_day)


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


def evaluate_routine_reminders(
    routines: list[dict],
    habits: list[dict],
    completions_today: dict,
    *,
    now: datetime,
) -> list[dict]:
    """Return reminders for armed routines that still have work left today.

    Silent when the routine is finished, when nothing of it is scheduled today,
    when it is unarmed or untimed, and outside its window — a reminder for a
    routine already checked off is noise, not a nudge.
    """
    local_now = now.astimezone(_TZ)
    today = local_now.date()
    alerts: list[dict] = []

    for routine in routines:
        if not reminder_window_open(routine, local_now):
            continue
        routine_id = str(routine.get("id") or "")
        members = [
            habit for habit in habits if habit.get("routine_id") == routine_id
        ]
        scheduled, completed = routine_pending_today(members, completions_today, today)
        if scheduled == 0 or completed >= scheduled:
            continue
        label = f"{str(routine.get('emoji') or '').strip()} {routine.get('name') or 'Routine'}".strip()
        alerts.append(
            {
                "kind": "routine_reminder",
                "topic_key": f"routine-reminder:{routine_id}:{today.isoformat()}",
                "text": (
                    f"{label}, Sir — {scheduled - completed} of {scheduled} still open."
                ),
                "message_class": "habit_nudge",
                "destination": "/routines",
            }
        )
    return alerts


def evaluate_explicit_rules(
    snapshot: dict,
    due_followups: list[dict],
    infrastructure_signals: list[Any],
    *,
    now: datetime,
) -> list[dict]:
    """Return explicit alerts; never infer urgency from an untimed item."""
    local_now = now.astimezone(_TZ)
    alerts: list[dict] = []

    for followup in due_followups:
        followup_id = str(followup.get("id") or "")
        note = str(followup.get("note") or "Scheduled follow-up")
        if followup_id:
            alerts.append(
                {
                    "kind": "timed_followup",
                    "topic_key": f"followup:{followup_id}",
                    "text": f"Scheduled follow-up, Sir: {note}",
                    "followup_id": followup_id,
                    "message_class": "alert",
                }
            )

    for task in snapshot.get("tasks") or []:
        if task.get("completed") or task.get("status") in {"completed", "done"}:
            continue
        deadline = _parse_datetime(task.get("hard_deadline_at"))
        if deadline is None:
            continue
        remaining = deadline.astimezone(_TZ) - local_now
        if timedelta(0) <= remaining <= _HARD_DEADLINE_WINDOW:
            task_id = str(task.get("id") or task.get("title") or "deadline")
            minutes = max(0, int(remaining.total_seconds() // 60))
            alerts.append(
                {
                    "kind": "hard_deadline",
                    "topic_key": f"deadline:{task_id}:{deadline.isoformat()}",
                    "text": (
                        f"Hard deadline, Sir: {task.get('title') or 'Task'} is due "
                        f"in {minutes} minute(s)."
                    ),
                    "message_class": "alert",
                }
            )

    events = list((((snapshot.get("today") or {}).get("calendar") or {}).get("timed") or []))
    parsed_events: list[tuple[dict, datetime, datetime]] = []
    for event in events:
        start = _parse_datetime(event.get("start"))
        end = _parse_datetime(event.get("end"))
        if start and end:
            parsed_events.append((event, start, end))
        leave_by = _parse_datetime(event.get("leave_by"))
        if leave_by and start and leave_by <= local_now < start:
            event_id = str(event.get("id") or event.get("title") or "event")
            alerts.append(
                {
                    "kind": "travel_conflict",
                    "topic_key": f"travel:{event_id}:{start.isoformat()}",
                    "text": (
                        f"Travel conflict, Sir: the leave-by time for "
                        f"{event.get('title') or 'your next event'} has passed."
                    ),
                    "message_class": "leave_by",
                }
            )
    parsed_events.sort(key=lambda item: item[1])
    for index, (first, first_start, first_end) in enumerate(parsed_events):
        for second, second_start, _second_end in parsed_events[index + 1 :]:
            if second_start >= first_end:
                break
            first_id = str(first.get("id") or first_start.isoformat())
            second_id = str(second.get("id") or second_start.isoformat())
            alerts.append(
                {
                    "kind": "calendar_conflict",
                    "topic_key": f"calendar-conflict:{first_id}:{second_id}",
                    "text": (
                        f"Calendar conflict, Sir: {first.get('title') or 'one event'} "
                        f"overlaps {second.get('title') or 'another event'}."
                    ),
                    "message_class": "alert",
                }
            )

    for signal in infrastructure_signals:
        if isinstance(signal, dict):
            severity = signal.get("severity")
            fingerprint = signal.get("fingerprint")
            title = signal.get("title")
        else:
            severity = getattr(signal, "severity", None)
            fingerprint = getattr(signal, "fingerprint", None)
            title = getattr(signal, "title", None)
        if severity != "critical" or not fingerprint:
            continue
        alerts.append(
            {
                "kind": "automation_failure",
                "topic_key": f"automation:{fingerprint}",
                "text": f"Automation failure, Sir: {title or fingerprint}",
                "message_class": "alert",
            }
        )
    return alerts


async def _resolve(loader: Callable, *args):
    if inspect.iscoroutinefunction(loader):
        return await loader(*args)
    result = await asyncio.to_thread(loader, *args)
    return await result if inspect.isawaitable(result) else result


async def run_rule_evaluator(
    *,
    now: datetime | None = None,
    snapshot_loader: Callable | None = None,
    due_followups_loader: Callable | None = None,
    infrastructure_loader: Callable | None = None,
    prior_topics_loader: Callable | None = None,
    push_sender: Callable | None = None,
    outreach_logger: Callable | None = None,
    followup_marker: Callable | None = None,
    routines_loader: Callable | None = None,
    habits_loader: Callable | None = None,
    completions_loader: Callable | None = None,
) -> dict:
    """Evaluate, de-duplicate, deliver, and audit explicit alerts.

    Runs at every hour of the day — see the module docstring on why there is
    no outreach window. Two passes share one delivery loop: routine reminders,
    which read only the routines unless one is actually inside its window, and
    everything else, which needs the life snapshot.
    """
    local_now = (now or datetime.now(_TZ)).astimezone(_TZ)

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    habit_store = None
    if habits_loader is None or completions_loader is None:
        from memory.firestore_db import HabitStore

        habit_store = HabitStore(project, database)
    if routines_loader is None:
        from memory.firestore_db import RoutineStore

        routines_loader = RoutineStore(project, database).list_all
    if habits_loader is None:
        habits_loader = habit_store.list_active
    if completions_loader is None:
        completions_loader = habit_store.get_completions_for_date
    if prior_topics_loader is None or outreach_logger is None:
        from memory.firestore_db import OutreachLogStore

        outreach_store = OutreachLogStore(project, database)
        prior_topics_loader = prior_topics_loader or outreach_store.topics_today
        outreach_logger = outreach_logger or outreach_store.append
    if push_sender is None:
        from core.push_sender import send_push_to_all

        push_sender = send_push_to_all

    day = local_now.date().isoformat()
    seen = set(await _resolve(prior_topics_loader, day) or [])

    # Pass 1 — routine reminders. Filtering on the window and on what has
    # already gone out today keeps the habit/completion reads off every tick
    # that has nothing to say.
    routines = await _resolve(routines_loader) or []
    candidates = [
        routine for routine in routines
        if reminder_window_open(routine, local_now)
        and f"routine-reminder:{routine.get('id')}:{day}" not in seen
    ]
    alerts: list[dict] = []
    if candidates:
        habits, completions = await asyncio.gather(
            _resolve(habits_loader),
            _resolve(completions_loader, day),
        )
        alerts += evaluate_routine_reminders(
            candidates, habits or [], completions or {}, now=local_now
        )
    reminder_topics = {alert["topic_key"] for alert in alerts}

    # Pass 2 — everything else. These rules need the life snapshot, which
    # is the expensive load on this path.
    if snapshot_loader is None:
        from core.life_snapshot import build_life_snapshot

        snapshot_loader = build_life_snapshot
    if due_followups_loader is None:
        from memory.firestore_db import FollowupStore

        due_followups_loader = FollowupStore(project, database).list_due
    if infrastructure_loader is None:
        from core.routines.heartbeat import collect_deterministic_signals

        infrastructure_loader = collect_deterministic_signals
    if followup_marker is None:
        from memory.firestore_db import FollowupStore

        followup_marker = FollowupStore(project, database).mark_done

    utc_now = local_now.astimezone(timezone.utc).isoformat()
    snapshot, followups, infrastructure = await asyncio.gather(
        _resolve(snapshot_loader),
        _resolve(due_followups_loader, utc_now),
        _resolve(infrastructure_loader),
    )
    alerts += evaluate_explicit_rules(
        snapshot or {}, followups or [], infrastructure or [], now=local_now
    )

    sent = 0
    reminders_sent = 0
    for alert in alerts:
        if alert["topic_key"] in seen:
            continue
        delivery = await _resolve(
            push_sender,
            alert["text"],
            alert.get("message_class") or "alert",
            alert.get("destination") or "/",
            "Klaus",
            None,
            # Tag = topic_key, the same id /api/notifications reports as
            # push_tag — reading the alert in the bell clears the lock screen.
            alert["topic_key"],
        )
        if not isinstance(delivery, dict) or int(delivery.get("sent") or 0) < 1:
            continue
        await _resolve(
            outreach_logger,
            day,
            {
                "topic_key": alert["topic_key"],
                "time": local_now.strftime("%H:%M"),
                "final": alert["text"],
                "origin": "deterministic_rule",
                "kind": alert["kind"],
            },
        )
        if alert.get("followup_id"):
            await _resolve(followup_marker, alert["followup_id"])
        seen.add(alert["topic_key"])
        sent += 1
        if alert["topic_key"] in reminder_topics:
            reminders_sent += 1
    return {
        "evaluated": len(alerts),
        "sent": sent,
        "reminders_sent": reminders_sent,
    }
