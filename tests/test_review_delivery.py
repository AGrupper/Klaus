import pytest

from core.review_delivery import (
    normalise_claude_session_url,
    routine_review_path,
    routine_review_title,
)


_PUBLIC_RUN_FIELDS = frozenset({
    "correlation_id",
    "routine",
    "target_date",
    "status",
    "provider",
    "delivery_mode",
    "created_at",
    "updated_at",
    "callback_deadline_at",
    "published_at",
    "review_id",
    "fallback_scheduled",
    "claude_session_url",
})


def hostile_routine_run(**overrides) -> dict:
    """Return one internal run containing diagnostics that must stay internal."""
    run = {
        "correlation_id": "run-public-1",
        "routine": "morning",
        "target_date": "2026-08-10",
        "status": "running",
        "provider": "claude_subscription",
        "delivery_mode": "live",
        "created_at": "2026-08-10T07:00:00+00:00",
        "updated_at": "2026-08-10T07:01:00+00:00",
        "callback_deadline_at": "2026-08-10T07:10:00+00:00",
        "published_at": None,
        "review_id": None,
        "fallback_scheduled": True,
        "claude_session_url": (
            "https://www.claude.ai/code/session_01Public?token=url-query-secret"
        ),
        "trigger": "trigger-secret",
        "remote_trigger_result": {
            "claude_code_session_url": (
                "https://provider-user:provider-pass@claude.ai/code/session_01Raw"
            ),
            "provider_secret": "remote-provider-secret",
        },
        "remote_trigger_error": "remote-error-secret",
        "error": "fallback-error-secret",
        "shadow_review": {"metadata_secret": "shadow-metadata-secret"},
        "credential": "top-level-credential-secret",
        "arbitrary_provider_field": "arbitrary-provider-secret",
    }
    run.update(overrides)
    return run


def expected_public_routine_run(run: dict) -> dict:
    """Hand-built public run contract for hostile boundary fixtures."""
    result = {key: run[key] for key in _PUBLIC_RUN_FIELDS if key in run}
    result["claude_session_url"] = "https://claude.ai/code/session_01Public"
    return result


def assert_public_routine_run(run: dict, expected: dict) -> None:
    """Assert the response remains an exact whitelist despite hostile storage."""
    assert run == expected
    rendered = repr(run)
    for marker in (
        "trigger-secret",
        "url-query-secret",
        "provider-user",
        "provider-pass",
        "remote-provider-secret",
        "remote-error-secret",
        "fallback-error-secret",
        "shadow-metadata-secret",
        "top-level-credential-secret",
        "arbitrary-provider-secret",
    ):
        assert marker not in rendered


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://claude.ai/code/session_01ABC-def?trigger=trig_private",
            "https://claude.ai/code/session_01ABC-def",
        ),
        (
            "https://www.claude.ai/epitaxy/session_01XYZ_9?trigger=trig_private",
            "https://claude.ai/epitaxy/session_01XYZ_9",
        ),
    ],
)
def test_normalise_claude_session_url_accepts_known_session_forms(raw, expected):
    assert normalise_claude_session_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://claude.ai/code/session_01ABC",
        "https://evil.example/code/session_01ABC",
        "https://claude.ai.evil.example/code/session_01ABC",
        "https://user:pass@claude.ai/code/session_01ABC",
        "https://claude.ai/chat/ordinary-chat",
        "//claude.ai/code/session_01ABC",
        "https://claude.ai/code/session_01ABC/extra",
        "https://claude.ai/code/session_01ABC\nhttps://evil.example",
        None,
        42,
    ],
)
def test_normalise_claude_session_url_rejects_unsafe_values(raw):
    assert normalise_claude_session_url(raw) is None


def test_routine_review_path_is_deterministic_and_strict():
    assert routine_review_path("nightly", "2026-08-10") == (
        "/klaus/reviews/nightly/2026-08-10"
    )
    with pytest.raises(ValueError, match="unsupported routine"):
        routine_review_path("adhoc", "2026-08-10")
    with pytest.raises(ValueError, match="ISO date"):
        routine_review_path("morning", "2026-02-30")


def test_routine_review_title_is_user_visible_and_strict():
    assert routine_review_title("morning") == "Klaus Morning Review"
    assert routine_review_title("nightly") == "Klaus Nightly Review"
    assert routine_review_title("weekly") == "Klaus Weekly Review"
    with pytest.raises(ValueError, match="unsupported routine"):
        routine_review_title("adhoc")
