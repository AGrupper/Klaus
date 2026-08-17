"""Subscription-funded routine trigger and deterministic fallback state machine."""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone

import pytest


class FakeRunStore:
    def __init__(self):
        self.records = {}
        self.review_store = None

    def get(self, correlation_id):
        record = self.records.get(correlation_id)
        return dict(record) if record else None

    def start(
        self, *, routine, target_date, trigger, correlation_id,
        callback_timeout_seconds=600, delivery_mode="live",
    ):
        now = datetime.now(timezone.utc)
        record = {
            "correlation_id": correlation_id,
            "routine": routine,
            "target_date": target_date,
            "trigger": trigger,
            "status": "queued",
            "callback_deadline_at": (now + timedelta(seconds=callback_timeout_seconds)).isoformat(),
            "delivery_mode": delivery_mode,
        }
        self.records[correlation_id] = record
        return dict(record)

    def transition(self, correlation_id, status, **fields):
        self.records[correlation_id].update(status=status, **fields)
        return dict(self.records[correlation_id])

    def transition_claude_publication(self, correlation_id, *, review_id):
        current = self.records[correlation_id]
        status = (
            "late_upgraded"
            if current["status"] == "published_fallback"
            else "published_claude"
        )
        current.update(status=status, review_id=review_id)
        return dict(current)

    def publish_review_atomic(self, correlation_id, *, publisher, **review_fields):
        current = self.records[correlation_id]
        if publisher == "fallback":
            if current["status"] not in {"queued", "running"}:
                return {
                    "committed": False,
                    "initial_publication": False,
                    "run": dict(current),
                    "review": None,
                }
            status = "published_fallback"
            initial_publication = True
        elif current["status"] in {"queued", "running"}:
            status = "published_claude"
            initial_publication = True
        elif current["status"] == "published_fallback":
            status = "late_upgraded"
            initial_publication = False
        else:
            raise ValueError("invalid routine transition")
        current.update(
            status=status,
            review_id=f"{current['routine']}:{current['target_date']}",
        )
        review = self.review_store.publish(
            routine=current["routine"],
            target_date=current["target_date"],
            correlation_id=correlation_id,
            status=status,
            **review_fields,
        )
        return {
            "committed": True,
            "initial_publication": initial_publication,
            "run": dict(current),
            "review": review,
        }

    def patch(self, correlation_id, **fields):
        self.records[correlation_id].update(**fields)
        return dict(self.records[correlation_id])


class FakeReviewStore:
    def __init__(self):
        self.published = []
        self.canonical = {}

    def publish(self, **record):
        record = {
            **record,
            "review_id": f"{record['routine']}:{record['target_date']}",
            "review_text": record["text"],
        }
        self.published.append(record)
        self.canonical[record["review_id"]] = record
        return record


def test_trigger_persists_pending_before_remote_fire_and_schedules_timeout():
    from core.routines.subscription import SubscriptionRoutineCoordinator

    events = []
    runs = FakeRunStore()

    def remote_fire(payload):
        events.append(("remote", runs.get(payload["correlation_id"])["status"]))
        return {
            "accepted": True,
            "claude_code_session_id": "session_01ABC",
            "claude_code_session_url": (
                "https://claude.ai/epitaxy/session_01ABC?trigger=trig_private"
            ),
        }

    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=FakeReviewStore(),
        remote_fire=remote_fire,
        enqueue_fallback=lambda correlation_id, delay: events.append(
            ("fallback", correlation_id, delay)
        ) or True,
        snapshot_builder=lambda: {},
        push_sender=lambda _text, _kind, _destination, _title, **_kw: {},
        public_url="https://klaus.example.com",
    )
    result = coordinator.start("morning", "2026-08-08", "wake")

    assert result["accepted"] is True
    assert events[0][0] == "fallback"
    assert events[1] == ("remote", "queued")
    stored = runs.get(result["correlation_id"])
    assert stored["status"] == "running"
    assert stored["claude_session_url"] == "https://claude.ai/epitaxy/session_01ABC"
    assert result["model"] == "sonnet"


def test_trigger_drops_hostile_session_url_but_keeps_run_running():
    from core.routines.subscription import SubscriptionRoutineCoordinator

    runs = FakeRunStore()
    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=FakeReviewStore(),
        remote_fire=lambda _payload: {
            "accepted": True,
            "claude_code_session_url": "https://evil.example/session_01ABC",
        },
        enqueue_fallback=lambda _cid, _delay: True,
        snapshot_builder=lambda: {},
        push_sender=lambda _text, _kind, _destination, _title, **_kw: {},
        public_url="https://klaus.example.com",
    )

    result = coordinator.start("morning", "2026-08-08", "wake")

    stored = runs.get(result["correlation_id"])
    assert stored["status"] == "running"
    assert "claude_session_url" not in stored


def test_same_routine_date_deduplicates_without_second_remote_fire():
    from core.routines.subscription import SubscriptionRoutineCoordinator

    fires = []
    runs = FakeRunStore()
    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=FakeReviewStore(),
        remote_fire=lambda payload: fires.append(payload) or {"accepted": True},
        enqueue_fallback=lambda _cid, _delay: True,
        snapshot_builder=lambda: {},
        push_sender=lambda _text, _kind, _destination, _title, **_kw: {},
        public_url="https://klaus.example.com",
    )
    first = coordinator.start("weekly", "2026-08-09", "cron")
    second = coordinator.start("weekly", "2026-08-09", "cron")

    assert first["correlation_id"] == second["correlation_id"]
    assert second["deduplicated"] is True
    assert len(fires) == 1
    assert first["model"] == "opus"


def test_shadow_run_has_separate_identity_and_tells_claude_not_to_deliver():
    from core.routines.subscription import SubscriptionRoutineCoordinator

    fires = []
    runs = FakeRunStore()
    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=FakeReviewStore(),
        remote_fire=lambda payload: fires.append(payload) or {"accepted": True},
        enqueue_fallback=lambda _cid, _delay: True,
        snapshot_builder=lambda: {},
        push_sender=lambda _text, _kind, _destination, _title, **_kw: {},
        public_url="https://klaus.example.com",
    )
    live = coordinator.start("morning", "2026-08-08", "wake")
    shadow = coordinator.start(
        "morning", "2026-08-08", "operator", delivery_mode="shadow"
    )

    assert live["correlation_id"] != shadow["correlation_id"]
    assert fires[-1]["delivery_mode"] == "shadow"

    runs.patch(
        shadow["correlation_id"],
        callback_deadline_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    fallback = asyncio.run(coordinator.publish_timeout_fallback(shadow["correlation_id"]))
    assert fallback["status"] == "published_fallback"
    assert fallback["delivery"] == {"shadow": True, "push_sent": False}
    assert coordinator._reviews.published == []


def test_timeout_publishes_deterministic_review_without_judgment_writes():
    from core.routines.subscription import SubscriptionRoutineCoordinator

    runs = FakeRunStore()
    reviews = FakeReviewStore()
    runs.review_store = reviews
    pushes = []
    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=reviews,
        remote_fire=lambda _payload: {
            "accepted": True,
            "claude_code_session_url": "https://claude.ai/code/session_01ABC",
        },
        enqueue_fallback=lambda _cid, _delay: True,
        snapshot_builder=lambda: {
            "today": {"today": "2026-08-08", "calendar": {"timed": [{"id": "e1"}]}, "garmin": {}},
            "tasks": [{"id": "t1"}],
            "habits_pending": [],
        },
        push_sender=lambda text, kind, destination, title, **_kw: pushes.append(
            (text, kind, destination, title)
        )
        or {"sent": 1},
        public_url="https://klaus.example.com",
    )
    started = coordinator.start("nightly", "2026-08-08", "backstop")
    runs.patch(
        started["correlation_id"],
        callback_deadline_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    fallback = asyncio.run(coordinator.publish_timeout_fallback(started["correlation_id"]))

    assert fallback["status"] == "published_fallback"
    assert reviews.published[0]["action_ids"] == []
    assert reviews.published[0]["partial_actions"] == []
    assert reviews.published[0]["claude_session_url"] == (
        "https://claude.ai/code/session_01ABC"
    )
    assert "No schedule, task, training, or memory changes were made" in reviews.published[0]["text"]
    assert len(pushes) == 1
    assert pushes[0] == (
        reviews.published[0]["text"],
        "briefing",
        "/klaus/reviews/nightly/2026-08-08",
        "Klaus Nightly Review",
    )


def test_late_callback_after_fallback_does_not_trigger_second_fallback_push():
    from core.routines.subscription import SubscriptionRoutineCoordinator

    runs = FakeRunStore()
    reviews = FakeReviewStore()
    runs.review_store = reviews
    pushes = []
    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=reviews,
        remote_fire=lambda _payload: {"accepted": True},
        enqueue_fallback=lambda _cid, _delay: True,
        snapshot_builder=lambda: {},
        push_sender=lambda text, kind, destination, title, **_kw: pushes.append(
            (text, kind, destination, title)
        )
        or {},
        public_url="https://klaus.example.com",
    )
    started = coordinator.start("morning", "2026-08-08", "wake")
    runs.transition(started["correlation_id"], "published_claude")

    result = asyncio.run(coordinator.publish_timeout_fallback(started["correlation_id"]))
    assert result["deduplicated"] is True
    assert pushes == []


def test_stale_fallback_retries_without_overwriting_claude_publication(monkeypatch):
    """A stale fallback transaction retries and cannot overwrite Claude."""
    import core.push_sender
    import memory.firestore_db
    from core.routines.subscription import SubscriptionRoutineCoordinator
    from interfaces.mcp.runtime import build_custom_handlers
    from tests.routine_firestore_fakes import (
        VersionedFirestoreClient,
        transactional_with_retry,
    )

    client = VersionedFirestoreClient(
        server_timestamp=memory.firestore_db.firestore.SERVER_TIMESTAMP
    )
    monkeypatch.setattr("memory.stores.base._make_firestore_client", lambda *_args: client)
    monkeypatch.setattr(
        memory.firestore_db.firestore,
        "transactional",
        transactional_with_retry,
    )
    runs = memory.firestore_db.RoutineRunStore("test-project")
    reviews = memory.firestore_db.RoutineReviewStore("test-project")
    pushes = []
    coordinator = SubscriptionRoutineCoordinator(
        run_store=runs,
        review_store=reviews,
        remote_fire=lambda _payload: {"accepted": True},
        enqueue_fallback=lambda _cid, _delay: True,
        snapshot_builder=lambda: {},
        push_sender=lambda text, *_args, **_kw: pushes.append(text) or {"sent": 1},
        public_url="https://klaus.example.com",
    )
    started = coordinator.start("morning", "2026-08-08", "wake")
    correlation_id = started["correlation_id"]
    runs.patch(
        correlation_id,
        callback_deadline_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    client.arm_next_transaction_read_pause()

    outcome = {}

    def publish_fallback():
        outcome["fallback"] = asyncio.run(
            coordinator.publish_timeout_fallback(correlation_id)
        )

    fallback_thread = threading.Thread(target=publish_fallback)
    fallback_thread.start()
    assert client.read_barrier.wait(timeout=2)

    monkeypatch.setattr(
        core.push_sender,
        "send_push_to_all",
        lambda text, *_args, **_kw: pushes.append(text) or {"sent": 1},
    )
    claude = build_custom_handlers()["publish_review"](
        {
            "correlation_id": correlation_id,
            "routine": "morning",
            "target_date": "2026-08-08",
            "text": "Claude's canonical review.",
            "structured": {"source": "claude"},
            "action_ids": [],
            "partial_actions": [],
        }
    )
    client.resume_barrier.set()
    fallback_thread.join(timeout=2)
    assert not fallback_thread.is_alive()

    assert runs.get(correlation_id)["status"] == "published_claude"
    assert reviews.get("morning", "2026-08-08")["review_text"] == (
        "Claude's canonical review."
    )
    assert claude["delivery"] == {"sent": 1}
    assert outcome["fallback"] == {
        "deduplicated": True,
        "status": "published_claude",
        "correlation_id": correlation_id,
    }
    assert client.stale_commits == 1
    assert client.retries == 1
    review_writes = [
        write
        for write in client.write_history
        if write[0] == ("morning_briefings", "2026-08-08")
    ]
    assert len(review_writes) == 1
    assert review_writes[0][1]["provider"] == "claude_subscription"
    assert pushes == ["Claude's canonical review."]


def test_remote_fire_uses_claude_subscription_routine_api_contract(monkeypatch):
    from core.routines.subscription import fire_remote_claude_routine

    monkeypatch.setenv(
        "CLAUDE_ROUTINE_TRIGGER_URL_MORNING",
        "https://api.anthropic.com/v1/claude_code/routines/trig_morning/fire",
    )
    monkeypatch.setenv("CLAUDE_ROUTINE_TRIGGER_TOKEN_MORNING", "morning-token")
    monkeypatch.setenv("CLAUDE_ROUTINE_TRIGGER_TOKEN", "legacy-shared-token")
    captured = {}

    class FakeResponse:
        content = b'{"type":"routine_fire","claude_code_session_id":"session_1"}'

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"type": "routine_fire", "claude_code_session_id": "session_1"}

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    result = fire_remote_claude_routine(
        {
            "routine": "morning",
            "correlation_id": "corr-1",
            "target_date": "2026-08-08",
        }
    )

    assert captured == {
        "url": "https://api.anthropic.com/v1/claude_code/routines/trig_morning/fire",
        "json": {
            "text": '{"correlation_id":"corr-1","routine":"morning","target_date":"2026-08-08"}'
        },
        "headers": {
            "Authorization": "Bearer morning-token",
            "Content-Type": "application/json",
            "anthropic-beta": "experimental-cc-routine-2026-04-01",
            "anthropic-version": "2023-06-01",
        },
        "timeout": 30.0,
    }
    assert result["claude_code_session_id"] == "session_1"


def test_remote_fire_requires_a_routine_trigger_token(monkeypatch):
    from core.routines.subscription import fire_remote_claude_routine

    monkeypatch.setenv(
        "CLAUDE_ROUTINE_TRIGGER_URL_NIGHTLY",
        "https://api.anthropic.com/v1/claude_code/routines/trig_nightly/fire",
    )
    monkeypatch.delenv("CLAUDE_ROUTINE_TRIGGER_TOKEN_NIGHTLY", raising=False)
    monkeypatch.delenv("CLAUDE_ROUTINE_TRIGGER_TOKEN", raising=False)
    monkeypatch.setattr(
        "httpx.post",
        lambda *_args, **_kwargs: pytest.fail("request must not fire without a token"),
    )

    with pytest.raises(RuntimeError, match="nightly routine trigger token is not configured"):
        fire_remote_claude_routine({"routine": "nightly"})
