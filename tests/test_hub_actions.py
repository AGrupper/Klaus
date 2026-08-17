"""Human rendering of action-log entries for the bell (core/hub/actions.py).

Fixtures mirror the real shapes observed in production on 2026-08-17: most
tools store their raw MCP argument payload as a JSON string in `detail`, the
legacy calendar paths store a hand-built sentence, and a couple store nothing
but an opaque id.
"""
from __future__ import annotations

import pytest

from core.hub.actions import humanize_action


def test_publish_review_is_suppressed():
    """The review is already a first-class bell item — don't list it twice."""
    entry = {
        "action": "publish_review",
        "detail": '{"action_ids": [], "correlation_id": "c2614aaf", "routine": "morning"}',
    }
    assert humanize_action(entry) is None


def test_legacy_hand_built_detail_is_kept_verbatim():
    entry = {"action": "calendar_create", "detail": "LT2 Run, 2026-08-17T07:30:00+03:00"}
    assert humanize_action(entry) == "Added a calendar event — LT2 Run, 2026-08-17T07:30:00+03:00"


def test_json_payload_is_mined_for_a_readable_field():
    entry = {
        "action": "task_create",
        "detail": '{"due_date": "2026-08-15", "due_time": "14:30", "title": "Switch newsletters"}',
    }
    assert humanize_action(entry) == "Filed a to-do — Switch newsletters"


def test_dict_detail_works_as_well_as_a_json_string():
    entry = {"action": "schedule_followup", "detail": {"note": "Check the shoulder"}}
    assert humanize_action(entry) == "Scheduled a follow-up — Check the shoulder"


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"action": "calendar_delete", "detail": "tg061l821accgrfilvjreuc4hs"},
         "Removed a calendar event"),
        ({"action": "forget_memory", "detail": '{"vector_id": "62fe0875-1311-4502-94ab"}'},
         "Forgot a memory"),
        ({"action": "task_edit", "detail": '{"list_id": "EzzQi1", "task_id": "NQzGJg7"}'},
         "Edited a to-do"),
        ({"action": "publish_portfolio_snapshot", "detail": '{"fx_rates": {"USD_ILS": 3.0}}'},
         "Recorded the weekly portfolio snapshot"),
    ],
)
def test_opaque_details_fall_back_to_the_bare_phrase(entry, expected):
    """Ids and machine payloads are dropped, never quoted at the user."""
    assert humanize_action(entry) == expected


def test_long_values_are_truncated_not_dumped():
    long_text = "Amit's weekly training split updated " + "x" * 300
    result = humanize_action({"action": "set_standing_directive", "detail": {"text": long_text}})
    assert result is not None
    assert result.startswith("Set a standing directive — ")
    assert len(result) < 140
    assert result.endswith("…")


def test_unknown_action_still_reads_as_a_sentence():
    assert humanize_action({"action": "some_new_tool", "detail": "{}"}) == "Some new tool"


def test_missing_action_never_raises():
    assert humanize_action({}) == "Did something"
    assert humanize_action({"action": "remember", "detail": None}) == "Remembered something"


def test_multiline_content_is_flattened_to_one_line():
    entry = {"action": "remember", "detail": {"content": "IBI SMART\n  portfolio\ttool"}}
    assert humanize_action(entry) == "Remembered something — IBI SMART portfolio tool"
