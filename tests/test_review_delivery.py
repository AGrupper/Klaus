import pytest

from core.review_delivery import (
    normalise_claude_session_url,
    routine_review_path,
    routine_review_title,
)


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
