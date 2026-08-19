"""Routine reminders as scheduled notifications (2026-08-19 rework).

The defect these replace: reminders used to ride the deterministic-alert cron,
so a routine anchored at 21:37 fired at 21:40 or not at all. They are now one
Cloud Task per routine per day at an exact schedule_time.

Two guards keep a time change from producing two notifications, and both are
covered here: the one-doc-per-routine store (nowhere to record a second task)
and the handler's anchor_time re-check (a task that outlives a failed cancel
stays silent).
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


TZ = ZoneInfo("Asia/Jerusalem")
TODAY = date(2026, 8, 19)
DAILY = [{"effective_from": "2026-01-01", "days": "daily"}]

ROUTINE = {
    "id": "r1",
    "name": "Nightly routine",
    "emoji": "🌙",
    "anchor_time": "21:37",
    "remind": True,
}
MEMBERS = [
    {"id": "h1", "routine_id": "r1", "schedule_history": DAILY},
    {"id": "h2", "routine_id": "r1", "schedule_history": DAILY},
    {"id": "other", "routine_id": "r2", "schedule_history": DAILY},
]

_ENV = {
    "GCP_PROJECT_ID": "klaus-agent",
    "FIRESTORE_DATABASE": "klaus-firestore",
    "CLOUD_TASKS_QUEUE": "klaus-updates",
    "CLOUD_TASKS_LOCATION": "me-central1",
    "CLOUD_RUN_URL": "https://klaus-agent.example.run.app",
    "CLOUD_SCHEDULER_SA_EMAIL": "klaus-heartbeat@klaus-agent.iam.gserviceaccount.com",
}


class FakeTasksClient:
    """Records create/delete instead of talking to Cloud Tasks."""

    def __init__(self, *, delete_raises: bool = False):
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self._delete_raises = delete_raises
        self._n = 0

    def create_task(self, parent: str, task: dict):
        self._n += 1
        # Server-assigned, as the real client does — `name` is reserved on
        # MagicMock, so this needs a plain object.
        name = f"{parent}/tasks/generated-{self._n}"
        self.created.append({"parent": parent, "task": task, "name": name})
        return SimpleNamespace(name=name)

    def delete_task(self, name: str):
        if self._delete_raises:
            raise RuntimeError("cloud tasks unavailable")
        self.deleted.append(name)


class FakeScheduleStore:
    """The one-doc-per-routine store, in memory."""

    def __init__(self, seed: dict | None = None):
        self.docs: dict[str, dict] = dict(seed or {})

    def get(self, routine_id):
        return self.docs.get(routine_id)

    def list_all(self):
        return list(self.docs.values())

    def upsert(self, routine_id, fields):
        self.docs[routine_id] = {**fields, "routine_id": routine_id}
        return self.docs[routine_id]

    def clear(self, routine_id):
        self.docs.pop(routine_id, None)


def _schedule(routine, *, now, store=None, client=None, target_date=None):
    """Run schedule_reminder against fakes; return (result, store, client)."""
    from core.routines import reminders

    store = store if store is not None else FakeScheduleStore()
    client = client if client is not None else FakeTasksClient()
    with patch.dict("os.environ", _ENV), \
         patch.object(reminders, "_store", return_value=store), \
         patch("google.cloud.tasks_v2.CloudTasksClient", return_value=client):
        result = reminders.schedule_reminder(routine, target_date, now=now)
    return result, store, client


# --------------------------------------------------------------------------- #
# Scheduling                                                                   #
# --------------------------------------------------------------------------- #

def test_an_armed_routine_is_scheduled_for_the_exact_minute():
    """21:37 means 21:37 — the failure that started this rework."""
    now = datetime(2026, 8, 19, 21, 35, tzinfo=TZ)
    result, store, client = _schedule(ROUTINE, now=now)

    assert len(client.created) == 1
    fire_at = client.created[0]["task"]["schedule_time"].ToDatetime(tzinfo=TZ)
    assert fire_at == datetime(2026, 8, 19, 21, 37, tzinfo=TZ)

    assert result["scheduled_for"] == "2026-08-19T21:37:00+03:00"
    assert result["anchor_time"] == "21:37"
    # The name Cloud Tasks assigned — the only handle we can cancel by.
    assert store.docs["r1"]["task_name"] == client.created[0]["name"]

    body = client.created[0]["task"]["http_request"]["body"].decode()
    assert '"anchor_time": "21:37"' in body
    assert client.created[0]["task"]["http_request"]["url"].endswith(
        "/internal/routine-reminder"
    )


def test_changing_the_time_cancels_before_it_creates():
    """The whole point: one notification after an edit, at the new time."""
    now = datetime(2026, 8, 19, 20, 0, tzinfo=TZ)
    _, store, client = _schedule(ROUTINE, now=now)
    first = client.created[0]["name"]

    _schedule({**ROUTINE, "anchor_time": "21:40"}, now=now, store=store, client=client)

    assert client.deleted == [first]            # the old task is gone
    assert len(client.created) == 2             # exactly one replaced it
    assert store.docs["r1"]["task_name"] == client.created[1]["name"]
    assert store.docs["r1"]["anchor_time"] == "21:40"
    assert len(store.docs) == 1                 # never two live schedules


def test_disarming_and_untiming_cancel_without_rescheduling():
    now = datetime(2026, 8, 19, 20, 0, tzinfo=TZ)

    for change in ({"remind": False}, {"anchor_time": None}):
        _, store, client = _schedule(ROUTINE, now=now)
        created_before = len(client.created)

        result, store, client = _schedule(
            {**ROUTINE, **change}, now=now, store=store, client=client
        )

        assert result is None
        assert len(client.created) == created_before   # nothing new queued
        assert store.docs == {}                        # and nothing recorded


def test_a_time_already_past_is_not_scheduled_for_today():
    """Moved from 21:37 to 07:00 at lunchtime: cancel today, leave tomorrow to
    the daily re-arm rather than firing immediately."""
    now = datetime(2026, 8, 19, 12, 0, tzinfo=TZ)
    _, store, client = _schedule(ROUTINE, now=now)

    result, store, client = _schedule(
        {**ROUTINE, "anchor_time": "07:00"}, now=now, store=store, client=client
    )

    assert result is None
    assert len(client.created) == 1     # only the original
    assert store.docs == {}


def test_a_task_that_cannot_be_recorded_is_rolled_back():
    """Otherwise we would leave a notification queued that nothing can cancel —
    exactly the state that produces a second notification after an edit."""
    from core.routines import reminders

    store = FakeScheduleStore()
    store.upsert = MagicMock(side_effect=RuntimeError("firestore down"))
    client = FakeTasksClient()

    result, _, _ = _schedule(
        ROUTINE, now=datetime(2026, 8, 19, 20, 0, tzinfo=TZ), store=store, client=client
    )

    assert result is None
    assert client.deleted == [client.created[0]["name"]]


def test_a_failed_cancel_still_lets_the_new_time_be_scheduled():
    """Cloud Tasks being unreachable must not block the edit; the handler's
    anchor_time check is what keeps the surviving task silent."""
    now = datetime(2026, 8, 19, 20, 0, tzinfo=TZ)
    store = FakeScheduleStore({"r1": {"task_name": "old/task", "anchor_time": "21:37"}})
    client = FakeTasksClient(delete_raises=True)

    result, store, client = _schedule(
        {**ROUTINE, "anchor_time": "21:40"}, now=now, store=store, client=client
    )

    assert result is not None
    assert store.docs["r1"]["anchor_time"] == "21:40"


def test_daily_rearm_covers_armed_routines_only():
    from core.routines import reminders

    routines = [
        ROUTINE,
        {"id": "r2", "name": "Morning", "anchor_time": "07:00", "remind": False},
        {"id": "r3", "name": "Untimed", "anchor_time": None, "remind": True},
    ]
    store = FakeScheduleStore()
    client = FakeTasksClient()
    routine_store = MagicMock()
    routine_store.list_all.return_value = routines

    with patch.dict("os.environ", _ENV), \
         patch.object(reminders, "_store", return_value=store), \
         patch("memory.firestore_db.RoutineStore", return_value=routine_store), \
         patch("google.cloud.tasks_v2.CloudTasksClient", return_value=client):
        result = reminders.schedule_all(now=datetime(2026, 8, 19, 0, 10, tzinfo=TZ))

    # r3 is armed but untimed: counted as armed, impossible to schedule.
    assert result == {"armed": 2, "scheduled": 1, "target_date": "2026-08-19"}
    assert list(store.docs) == ["r1"]


# --------------------------------------------------------------------------- #
# Delivery                                                                     #
# --------------------------------------------------------------------------- #

def _deliver(
    *,
    routine=ROUTINE,
    habits=MEMBERS,
    completions=None,
    topics=None,
    anchor_time="21:37",
    target_date="2026-08-19",
    now=datetime(2026, 8, 19, 21, 37, tzinfo=TZ),
    push=None,
):
    from core.routines.reminders import deliver_reminder

    routine_store = MagicMock()
    routine_store.get.return_value = routine
    habit_store = MagicMock()
    habit_store.list_active.return_value = habits
    habit_store.get_completions_for_date.return_value = completions or {}
    outreach = MagicMock()
    outreach.topics_today.return_value = topics or []
    sent: list[tuple] = []

    with patch.dict("os.environ", _ENV), \
         patch("memory.firestore_db.RoutineStore", return_value=routine_store), \
         patch("memory.firestore_db.HabitStore", return_value=habit_store), \
         patch("memory.firestore_db.OutreachLogStore", return_value=outreach):
        result = deliver_reminder(
            "r1", target_date, anchor_time, now=now,
            push_sender=push or (lambda *args: sent.append(args) or {"sent": 1}),
        )
    return result, sent, outreach


def test_delivery_pushes_an_unfinished_routine():
    result, sent, outreach = _deliver(completions={"h1": {}})

    assert result == {"sent": True, "topic_key": "routine-reminder:r1:2026-08-19"}
    text, message_class, destination, title, external_url, tag = sent[0]
    assert text == "🌙 Nightly routine, Sir — 1 of 2 still open."
    assert (message_class, destination, external_url) == ("habit_nudge", "/routines", None)
    assert tag == "routine-reminder:r1:2026-08-19"
    assert outreach.append.call_args[0][1]["origin"] == "scheduled_reminder"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"routine": None}, "routine_gone"),
        ({"routine": {**ROUTINE, "remind": False}}, "disarmed"),
        # The guard that makes a failed cancel harmless.
        ({"anchor_time": "21:30"}, "time_changed"),
        ({"target_date": "2026-08-18"}, "stale_date"),
        ({"topics": ["routine-reminder:r1:2026-08-19"]}, "already_sent"),
        ({"completions": {"h1": {}, "h2": {}}}, "nothing_open"),
        ({"habits": []}, "nothing_open"),
    ],
)
def test_delivery_stays_silent_and_says_why(kwargs, reason):
    result, sent, outreach = _deliver(**kwargs)

    assert result == {"sent": False, "reason": reason}
    assert sent == []
    outreach.append.assert_not_called()


def test_delivery_does_not_log_outreach_when_no_device_took_the_push():
    """Nothing was delivered, so nothing may claim it in the bell."""
    result, _sent, outreach = _deliver(
        completions={"h1": {}}, push=lambda *args: {"sent": 0, "failed": 1}
    )

    assert result == {"sent": False, "reason": "no_subscription"}
    outreach.append.assert_not_called()


def test_a_deliberate_silence_answers_200_so_cloud_tasks_stops():
    """A retry would only re-derive the same silence."""
    import os
    import sys
    from unittest.mock import patch as _patch
    from fastapi.testclient import TestClient

    from tests.test_paper_hub_api import _stub_web_server_imports

    stubs = _stub_web_server_imports()
    with _patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws

        with _patch.dict(os.environ, {**_ENV, "CRON_DEV_BYPASS": "true"}), \
             _patch(
                 "core.routines.reminders.deliver_reminder",
                 return_value={"sent": False, "reason": "nothing_open"},
             ):
            client = TestClient(ws.app, raise_server_exceptions=False)
            response = client.post(
                "/internal/routine-reminder",
                json={"routine_id": "r1", "target_date": "2026-08-19",
                      "anchor_time": "21:37"},
            )

    assert response.status_code == 200
    assert response.json() == {"sent": False, "reason": "nothing_open"}
