"""Deterministic waking-hours alerts for the subscription-first runtime.

This module intentionally contains no LLM client. It only emits explicit,
time-bound reminders, calendar/travel conflicts, and critical infrastructure
failures. Untimed tasks, habits, nutrition, and coaching never create pushes.
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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_TZ)


def evaluate_daytime_rules(
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
) -> dict:
    """Evaluate, de-duplicate, deliver, and audit explicit daytime alerts."""
    local_now = (now or datetime.now(_TZ)).astimezone(_TZ)
    if local_now.hour < 7 or local_now.hour > 21:
        return {"evaluated": 0, "sent": 0, "quiet_hours": True}

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    if snapshot_loader is None:
        from core.life_snapshot import build_life_snapshot

        snapshot_loader = build_life_snapshot
    if due_followups_loader is None:
        from memory.firestore_db import FollowupStore

        due_followups_loader = FollowupStore(project, database).list_due
    if infrastructure_loader is None:
        from core.heartbeat import collect_deterministic_signals

        infrastructure_loader = collect_deterministic_signals
    if prior_topics_loader is None or outreach_logger is None:
        from memory.firestore_db import OutreachLogStore

        outreach_store = OutreachLogStore(project, database)
        prior_topics_loader = prior_topics_loader or outreach_store.topics_today
        outreach_logger = outreach_logger or outreach_store.append
    if followup_marker is None:
        from memory.firestore_db import FollowupStore

        followup_marker = FollowupStore(project, database).mark_done
    if push_sender is None:
        from core.push_sender import send_push_to_all

        push_sender = send_push_to_all

    utc_now = local_now.astimezone(timezone.utc).isoformat()
    day = local_now.date().isoformat()
    snapshot, followups, infrastructure, prior_topics = await asyncio.gather(
        _resolve(snapshot_loader),
        _resolve(due_followups_loader, utc_now),
        _resolve(infrastructure_loader),
        _resolve(prior_topics_loader, day),
    )
    alerts = evaluate_daytime_rules(
        snapshot or {}, followups or [], infrastructure or [], now=local_now
    )
    seen = set(prior_topics or [])
    sent = 0
    for alert in alerts:
        if alert["topic_key"] in seen:
            continue
        delivery = await _resolve(
            push_sender, alert["text"], alert.get("message_class") or "alert"
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
    return {"evaluated": len(alerts), "sent": sent, "quiet_hours": False}
