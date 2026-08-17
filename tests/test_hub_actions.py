"""Human rendering of action-log entries for the bell (core/hub/actions.py).

Fixtures mirror the real shapes observed in production on 2026-08-17: most
tools store their raw MCP argument payload as a JSON string in `detail`, the
legacy calendar paths store a hand-built sentence, and a couple store nothing
but an opaque id.
"""
from __future__ import annotations

import json

import pytest

from core.hub.actions import dedupe_actions, humanize_action


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


# --- dedupe_actions: one bell row per physical write ------------------------
#
# The pairs below are copied from action_log/2026-08-10 and 2026-08-09, where
# the retired Klaus calendar tool and the MCP gateway each audited the same
# event create a fraction of a second apart.

def _legacy_create(summary, start, at, entry_id):
    return {"id": entry_id, "action": "calendar_create", "occasion": "chat",
            "detail": f"{summary}, {start}", "at": at}


def _mcp_create(summary, start, at, entry_id):
    return {"id": entry_id, "action": "create_calendar_event", "occasion": "interactive",
            "detail": json.dumps({"summary": summary, "start_iso": start,
                                  "end_iso": start, "is_workout": True}, sort_keys=True),
            "at": at}


def test_retired_and_mcp_rows_for_one_event_collapse_to_one():
    entries = [
        _legacy_create("Easy Run + Strides", "2026-08-11T08:00:00+03:00",
                       "2026-08-10T21:27:39.551524+03:00", "60121270c32f403b9399e6914bbfc0cb"),
        _mcp_create("Easy Run + Strides", "2026-08-11T08:00:00+03:00",
                    "2026-08-10T21:27:39.812352+03:00", "easy-run-strides-2026-08-11-0800"),
    ]
    kept = dedupe_actions(entries)
    assert len(kept) == 1
    # The MCP row survives: it names the event without trailing a raw ISO stamp.
    assert humanize_action(kept[0]) == "Added a calendar event — Easy Run + Strides"


def test_two_different_events_seconds_apart_both_survive():
    """The 2026-08-09 race pair: 7s apart, four rows, two real events."""
    entries = [
        _legacy_create("Run With Moshe 5K", "2026-10-09T00:00:00+03:00",
                       "2026-08-09T15:52:04.381051+03:00", "b04fa7a97b2e430ea542048b50ec48da"),
        _mcp_create("Run With Moshe 5K", "2026-10-09T00:00:00+03:00",
                    "2026-08-09T15:52:04.542929+03:00", "race-run-with-moshe-5k-2026-10-09"),
        _legacy_create("Night Run TLV 15K", "2026-10-28T00:00:00+03:00",
                       "2026-08-09T15:52:11.236505+03:00", "7382246ea1e54a6aa62eafdef79ba9e3"),
        _mcp_create("Night Run TLV 15K", "2026-10-28T00:00:00+03:00",
                    "2026-08-09T15:52:11.364178+03:00", "race-night-run-tlv-15k-2026-10-28"),
    ]
    kept = dedupe_actions(entries)
    assert [humanize_action(entry) for entry in kept] == [
        "Added a calendar event — Run With Moshe 5K",
        "Added a calendar event — Night Run TLV 15K",
    ]


def test_replayed_audit_under_the_same_id_collapses():
    """The idempotency gateway re-audits on replay so a crash can't lose it."""
    entries = [
        {"id": "task-organize-email-inbox-2026-08-14-r2", "action": "task_create",
         "detail": '{"title": "Organize entire email inbox"}',
         "at": "2026-08-14T14:59:07.425550+03:00"},
        {"id": "task-organize-email-inbox-2026-08-14-r2", "action": "task_create",
         "detail": '{"title": "Organize entire email inbox"}',
         "at": "2026-08-14T14:59:41.882110+03:00"},
    ]
    assert len(dedupe_actions(entries)) == 1


def test_the_same_event_recreated_days_later_shows_twice():
    entries = [
        _mcp_create("Upper Body Day", "2026-08-08T13:00:00+03:00",
                    "2026-08-08T12:39:11.218107+03:00", "upper-body-2026-08-08"),
        _mcp_create("Upper Body Day", "2026-08-08T13:00:00+03:00",
                    "2026-08-15T09:02:00.000000+03:00", "upper-body-2026-08-08-redo"),
    ]
    assert len(dedupe_actions(entries)) == 2


def test_a_lone_retired_row_still_renders():
    """08-06 and 08-08 have calendar_create with no MCP twin — keep them."""
    entry = _legacy_create("Easy Run", "2026-08-06T19:30:00+03:00",
                           "2026-08-06T11:34:50.599634+03:00", "9f1e3abc50e843bfaedeb519c5dae63e")
    kept = dedupe_actions([entry])
    assert len(kept) == 1
    assert humanize_action(kept[0]) == (
        "Added a calendar event — Easy Run, 2026-08-06T19:30:00+03:00"
    )


def test_unreadable_timestamps_keep_both_rows():
    """Ambiguity resolves toward showing too much, never toward losing a record."""
    entries = [
        _legacy_create("Easy Run", "2026-08-11T08:00:00+03:00", "", "a"),
        _mcp_create("Easy Run", "2026-08-11T08:00:00+03:00", "not-a-timestamp", "b"),
    ]
    assert len(dedupe_actions(entries)) == 2


def test_non_calendar_actions_are_never_paired():
    entries = [
        {"id": "x1", "action": "remember", "detail": '{"content": "same note"}',
         "at": "2026-08-14T19:04:52.613143+03:00"},
        {"id": "x2", "action": "remember", "detail": '{"content": "same note"}',
         "at": "2026-08-14T19:04:53.100000+03:00"},
    ]
    assert len(dedupe_actions(entries)) == 2


def test_dedupe_of_nothing_is_nothing():
    assert dedupe_actions([]) == []
