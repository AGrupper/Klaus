"""Security-focused tests for production MCP handler wiring."""
from __future__ import annotations

import pytest

from tests.test_review_delivery import (
    assert_public_routine_run,
    expected_public_routine_run,
    hostile_routine_run,
)


def test_redaction_and_prepared_action_guard_find_nested_secret_aliases():
    from interfaces.mcp_runtime import _redact, _reject_embedded_secrets

    payload = {
        "request": {
            "headers": [
                {"access_token": "raw-token"},
                {"client-secret": "raw-secret"},
            ]
        }
    }

    assert _redact(payload) == {
        "request": {
            "headers": [
                {"access_token": "[REDACTED]"},
                {"client-secret": "[REDACTED]"},
            ]
        }
    }
    with pytest.raises(ValueError, match="raw secrets"):
        _reject_embedded_secrets(payload)


def test_resolve_single_user_id_prefers_explicit_setting(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.setenv("KLAUS_USER_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111,222")
    assert _resolve_single_user_id() == 123456789


def test_resolve_single_user_id_uses_first_valid_legacy_value(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "invalid, 123456789, 999")
    assert _resolve_single_user_id() == 123456789


@pytest.mark.parametrize("environment", ["development", "test"])
@pytest.mark.parametrize("legacy_value", ["", "not-a-number", "0", "-1"])
def test_resolve_single_user_id_rejects_invalid_legacy_setting_outside_production(
    monkeypatch, environment, legacy_value
):
    """Configured legacy identities must not silently create namespace zero."""
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", legacy_value)
    monkeypatch.setenv("ENVIRONMENT", environment)

    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
        _resolve_single_user_id()


@pytest.mark.parametrize("value", ["", "not-a-number", "0", "-1"])
def test_resolve_single_user_id_rejects_invalid_explicit_setting(monkeypatch, value):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.setenv("KLAUS_USER_ID", value)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
    with pytest.raises(RuntimeError, match="KLAUS_USER_ID"):
        _resolve_single_user_id()


def test_resolve_single_user_id_fails_closed_in_production(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="canonical Klaus user ID"):
        _resolve_single_user_id()


def test_resolve_single_user_id_retains_local_default(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert _resolve_single_user_id() == 0


def test_dispatch_for_single_user_sets_identity_before_dispatch(monkeypatch):
    import core.tools
    from interfaces.mcp_runtime import dispatch_for_single_user

    observed = []
    monkeypatch.setenv("KLAUS_USER_ID", "123456789")
    monkeypatch.setattr(
        core.tools,
        "set_current_user_id",
        lambda user_id: observed.append(("identity", user_id)),
    )
    monkeypatch.setattr(
        core.tools,
        "dispatch",
        lambda tool_name, arguments: observed.append(
            ("dispatch", tool_name, arguments)
        )
        or "result",
    )

    assert dispatch_for_single_user("recall", {"query": "history"}) == "result"
    assert observed == [
        ("identity", 123456789),
        ("dispatch", "recall", {"query": "history"}),
    ]


def test_production_bundle_uses_identity_aware_dispatcher(monkeypatch):
    import interfaces.mcp_runtime as runtime
    import memory.firestore_db

    captured = {}
    monkeypatch.setattr(
        memory.firestore_db,
        "ActionIdempotencyStore",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        runtime,
        "create_mcp_bundle",
        lambda oauth_service, **kwargs: captured.update(kwargs) or "bundle",
    )

    assert runtime.create_production_mcp_bundle(object()) == "bundle"
    assert captured["dispatcher"] is runtime.dispatch_for_single_user


def test_normalise_publish_review_accepts_claude_review_alias():
    """Claude's observed ``review`` payload must not publish as empty content."""
    from interfaces.mcp_runtime import _normalise_publish_review

    review = {
        "summary": "Quiet morning. Recovery is adequate; preserve tonight's plan.",
        "calendar": {"events": []},
        "recovery": {"sleep_hours": 8.1, "hrv": 104},
    }

    text, structured = _normalise_publish_review({"review": review})

    assert text == review["summary"]
    assert structured == review


def test_normalise_publish_review_rejects_empty_publication():
    """A successful callback cannot discard the review and publish emptiness."""
    from interfaces.mcp_runtime import _normalise_publish_review

    with pytest.raises(ValueError, match="review content is required"):
        _normalise_publish_review({})


def test_get_routine_status_returns_only_the_public_run_contract(monkeypatch):
    """Internal provider diagnostics must not cross the MCP status boundary."""
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    stored = hostile_routine_run()

    class RoutineRuns:
        @staticmethod
        def get(_correlation_id):
            return stored

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())

    result = build_custom_handlers()["get_routine_status"](
        {"correlation_id": stored["correlation_id"]}
    )

    assert_public_routine_run(result["run"], expected_public_routine_run(stored))


INCIDENT_PAYLOAD = {
    "correlation_id": "a485e1a9914893c100eb2dce1d25b53e",
    "routine": "nightly",
    "target_date": "2026-08-09",
    "text": "test text eighteen",
    "structured": {
        "reflection": {"summary": "test reflection", "mood": "steady"},
        "self_state": {"proposed_mood": "steady"},
        "quiet_night": True,
    },
    "action_ids": [],
    "partial_actions": [],
}


def complete_nightly_payload():
    return {
        "correlation_id": "complete-nightly-correlation",
        "routine": "nightly",
        "target_date": "2026-08-09",
        "text": "Nightly review: good recovery.",
        "structured": {
            "reflection": {
                "summary": "Good recovery.",
                "mood": "steady",
                "current_focus": "Recovery",
                "recent_context": "A quiet Sunday.",
                "highlights": ["Good recovery"],
            },
            "self_state": {
                "mood": "steady",
                "current_focus": "Recovery",
                "recent_context": "A quiet Sunday.",
            },
        },
        "action_ids": [],
        "partial_actions": [],
    }


def test_validate_publish_review_rejects_incident_placeholder_shape():
    """Nightly publications require the full reflection and self-state contract."""
    from interfaces.mcp_runtime import _validate_publish_review

    with pytest.raises(ValueError, match="current_focus"):
        _validate_publish_review(INCIDENT_PAYLOAD)


def test_validate_publish_review_accepts_complete_nightly_shape():
    """A complete nightly payload preserves normalized publication fields."""
    from interfaces.mcp_runtime import _validate_publish_review

    text, structured, action_ids, partial_actions = _validate_publish_review(
        complete_nightly_payload()
    )

    assert text.startswith("Nightly review")
    assert structured["reflection"]["highlights"] == ["Good recovery"]
    assert action_ids == []
    assert partial_actions == []


def test_invalid_nightly_publish_has_zero_side_effects(monkeypatch):
    """A malformed callback must fail before it can publish or mutate routine state."""
    import core.push_sender
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    transitions = []
    writes = []
    pushes = []
    reads = []

    class RoutineRuns:
        def get(self, correlation_id):
            reads.append(correlation_id)
            return {
                "routine": "nightly",
                "target_date": "2026-08-09",
                "delivery_mode": "live",
            }

        def transition_claude_publication(self, *args, **kwargs):
            transitions.append((args, kwargs))
            return {"status": "published"}

        def patch(self, *args, **kwargs):
            writes.append(("routine_patch", args, kwargs))

    class Journal:
        def set(self, *args, **kwargs):
            writes.append(("journal", args, kwargs))

    class SelfState:
        def set(self, *args, **kwargs):
            writes.append(("self_state", args, kwargs))

    class Reviews:
        def publish(self, *args, **kwargs):
            writes.append(("review", args, kwargs))

    class Feedback:
        def record(self, *args, **kwargs):
            writes.append(("feedback", args, kwargs))

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())
    monkeypatch.setattr(memory.firestore_db, "JournalStore", lambda *_args: Journal())
    monkeypatch.setattr(memory.firestore_db, "SelfStateStore", lambda *_args: SelfState())
    monkeypatch.setattr(memory.firestore_db, "RoutineReviewStore", lambda *_args: Reviews())
    monkeypatch.setattr(
        memory.firestore_db,
        "BehavioralFeedbackStore",
        lambda *_args: Feedback(),
    )
    monkeypatch.setattr(
        core.push_sender,
        "send_push_to_all",
        lambda *args: pushes.append(args),
    )

    with pytest.raises(ValueError, match="current_focus"):
        build_custom_handlers()["publish_review"](INCIDENT_PAYLOAD)

    assert reads == []
    assert transitions == []
    assert writes == []
    assert pushes == []


@pytest.mark.parametrize(
    ("stored_url", "expected_url"),
    [
        (
            "https://www.claude.ai/epitaxy/session_01ABC?trigger=private",
            "https://claude.ai/epitaxy/session_01ABC",
        ),
        ("https://evil.example/code/session_01ABC", None),
    ],
)
def test_publish_review_passes_only_safe_session_url_to_review_store(
    monkeypatch, stored_url, expected_url
):
    """Callback delivery forwards a normalized session link, never provider data."""
    import core.push_sender
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    published = []

    class RoutineRuns:
        def get(self, _correlation_id):
            return {
                "routine": "morning",
                "target_date": "2026-08-08",
                "delivery_mode": "live",
                "claude_session_url": stored_url,
                "remote_trigger_result": {
                    "claude_code_session_url": "https://evil.example/never-forward"
                },
            }

        @staticmethod
        def publish_review_atomic(correlation_id, **kwargs):
            published.append(kwargs)
            return {
                "committed": True,
                "initial_publication": True,
                "run": {"status": "published_claude"},
                "review": {**kwargs, "review_text": kwargs["text"]},
            }

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())
    monkeypatch.setattr(core.push_sender, "send_push_to_all", lambda *_args: {"sent": 1})

    result = build_custom_handlers()["publish_review"](
        {
            "correlation_id": "routine-1",
            "routine": "morning",
            "target_date": "2026-08-08",
            "text": "Morning review.",
            "structured": {},
            "action_ids": [],
            "partial_actions": [],
        }
    )

    assert result["delivery"] == {"sent": 1}
    if expected_url is None:
        assert "claude_session_url" not in published[0]
    else:
        assert published[0]["claude_session_url"] == expected_url


def test_publish_review_pushes_claude_nightly_to_its_review_detail(monkeypatch):
    """The initial Claude publication routes its push to the nightly review."""
    import core.push_sender
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    pushes = []

    class RoutineRuns:
        @staticmethod
        def get(_correlation_id):
            return {
                "routine": "nightly",
                "target_date": "2026-08-10",
                "delivery_mode": "live",
            }

        @staticmethod
        def publish_review_atomic(correlation_id, **kwargs):
            return {
                "committed": True,
                "initial_publication": True,
                "run": {"status": "published_claude"},
                "review": {**kwargs, "review_text": kwargs["text"]},
            }

    class Journal:
        @staticmethod
        def set(*_args, **_kwargs):
            return None

    class SelfState:
        @staticmethod
        def set(*_args, **_kwargs):
            return None

    class Feedback:
        @staticmethod
        def record(*_args, **_kwargs):
            return None

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())
    monkeypatch.setattr(memory.firestore_db, "JournalStore", lambda *_args: Journal())
    monkeypatch.setattr(memory.firestore_db, "SelfStateStore", lambda *_args: SelfState())
    monkeypatch.setattr(
        memory.firestore_db, "BehavioralFeedbackStore", lambda *_args: Feedback()
    )
    monkeypatch.setattr(
        core.push_sender,
        "send_push_to_all",
        lambda *args: pushes.append(args) or {"sent": 1},
    )

    payload = complete_nightly_payload()
    payload["target_date"] = "2026-08-10"
    result = build_custom_handlers()["publish_review"](payload)

    assert result["delivery"] == {"sent": 1}
    assert pushes == [
        (
            "Nightly review: good recovery.",
            "briefing",
            "/klaus/reviews/nightly/2026-08-10",
            "Klaus Nightly Review",
        )
    ]


def test_publish_review_late_upgrade_does_not_send_another_push(monkeypatch):
    """A Claude callback after fallback enriches the review without notifying again."""
    import core.push_sender
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    pushes = []

    class RoutineRuns:
        @staticmethod
        def get(_correlation_id):
            return {
                "routine": "morning",
                "target_date": "2026-08-08",
                "delivery_mode": "live",
            }

        @staticmethod
        def publish_review_atomic(correlation_id, **kwargs):
            return {
                "committed": True,
                "initial_publication": False,
                "run": {"status": "late_upgraded"},
                "review": {**kwargs, "review_text": kwargs["text"]},
            }

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())
    monkeypatch.setattr(
        core.push_sender,
        "send_push_to_all",
        lambda *args: pushes.append(args) or {"sent": 1},
    )

    result = build_custom_handlers()["publish_review"](
        {
            "correlation_id": "routine-1",
            "routine": "morning",
            "target_date": "2026-08-08",
            "text": "Morning review.",
            "structured": {},
            "action_ids": [],
            "partial_actions": [],
        }
    )

    assert result["delivery"] == {"late_upgrade": True, "push_sent": False}
    assert pushes == []


def test_publish_review_uses_atomic_result_and_pushes_committed_canonical_text(
    monkeypatch,
):
    """Live Claude publication must push only the review committed with its run."""
    import core.push_sender
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    publications = []
    pushes = []

    class RoutineRuns:
        @staticmethod
        def get(_correlation_id):
            return {
                "routine": "morning",
                "target_date": "2026-08-08",
                "delivery_mode": "live",
            }

        @staticmethod
        def transition_claude_publication(*_args, **_kwargs):
            raise AssertionError("live publication must use the atomic store API")

        @staticmethod
        def publish_review_atomic(correlation_id, **kwargs):
            publications.append((correlation_id, kwargs))
            return {
                "committed": True,
                "initial_publication": True,
                "run": {
                    "correlation_id": correlation_id,
                    "routine": "morning",
                    "target_date": "2026-08-08",
                    "delivery_mode": "live",
                    "status": "published_claude",
                    "review_id": "morning:2026-08-08",
                },
                "review": {
                    "review_id": "morning:2026-08-08",
                    "review_text": "Canonical committed Claude review.",
                },
            }

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())
    monkeypatch.setattr(
        memory.firestore_db,
        "RoutineReviewStore",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("live publication must not perform a second review write")
        ),
    )
    monkeypatch.setattr(
        core.push_sender,
        "send_push_to_all",
        lambda *args: pushes.append(args) or {"sent": 1},
    )

    result = build_custom_handlers()["publish_review"](
        {
            "correlation_id": "routine-atomic",
            "routine": "morning",
            "target_date": "2026-08-08",
            "text": "Uncommitted callback text.",
            "structured": {},
            "action_ids": [],
            "partial_actions": [],
        }
    )

    assert publications[0][1]["publisher"] == "claude"
    assert result["review"]["review_text"] == "Canonical committed Claude review."
    assert pushes == [
        (
            "Canonical committed Claude review.",
            "briefing",
            "/klaus/reviews/morning/2026-08-08",
            "Klaus Morning Review",
        )
    ]


@pytest.mark.parametrize(
    ("delivery_mode", "transition_status"),
    [
        ("shadow", "published_claude"),
        ("live", "published_claude"),
        ("live", "late_upgraded"),
    ],
    ids=("shadow", "initial-publication", "late-upgrade"),
)
def test_publish_review_never_returns_internal_run_diagnostics(
    monkeypatch, delivery_mode, transition_status
):
    """All publication results expose an exact public run, never raw diagnostics."""
    import core.push_sender
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers

    stored = hostile_routine_run(delivery_mode=delivery_mode)

    class RoutineRuns:
        @staticmethod
        def get(_correlation_id):
            return stored

        @staticmethod
        def transition_claude_publication(*_args, **_kwargs):
            return {**stored, "status": transition_status, "review_id": "morning:2026-08-10"}

        @staticmethod
        def publish_review_atomic(correlation_id, **kwargs):
            return {
                "committed": True,
                "initial_publication": transition_status == "published_claude",
                "run": {
                    **stored,
                    "status": transition_status,
                    "review_id": "morning:2026-08-10",
                },
                "review": {**kwargs, "review_text": kwargs["text"]},
            }

        @staticmethod
        def patch(_correlation_id, **fields):
            return {
                **stored,
                "status": transition_status,
                "review_id": "morning:2026-08-10",
                **fields,
            }

    class Reviews:
        @staticmethod
        def publish(**kwargs):
            return kwargs

    monkeypatch.setattr(memory.firestore_db, "RoutineRunStore", lambda *_args: RoutineRuns())
    monkeypatch.setattr(memory.firestore_db, "RoutineReviewStore", lambda *_args: Reviews())
    monkeypatch.setattr(core.push_sender, "send_push_to_all", lambda *_args: {"sent": 1})

    result = build_custom_handlers()["publish_review"](
        {
            "correlation_id": stored["correlation_id"],
            "routine": stored["routine"],
            "target_date": stored["target_date"],
            "text": "Morning review.",
            "structured": {},
            "action_ids": [],
            "partial_actions": [],
        }
    )

    expected = expected_public_routine_run(
        {**stored, "status": transition_status, "review_id": "morning:2026-08-10"}
    )
    assert_public_routine_run(result["run"], expected)
