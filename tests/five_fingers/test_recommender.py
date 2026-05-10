"""Tests for mcp_tools/five_fingers/recommender.py.

All tests are pure-logic; no external imports or I/O.
"""
from __future__ import annotations

import pytest

from mcp_tools.five_fingers.recommender import (
    PracticeRecord,
    Suggestion,
    Teammate,
    recommend,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_teammate(doc_id: str, name: str | None = None) -> Teammate:
    return Teammate(doc_id=doc_id, name=name or doc_id)


def make_record(
    practice_date: str,
    attendance: dict[str, str],
    pinged: list[str] | None = None,
) -> PracticeRecord:
    return PracticeRecord(
        practice_date=practice_date,
        attendance=attendance,
        pinged_pre_practice=pinged or [],
    )


# ---------------------------------------------------------------------------
# Test 1: missed last practice → missed_last_week
# ---------------------------------------------------------------------------

def test_missed_last_week():
    alice = make_teammate("alice")
    records = [
        make_record("2026-05-07", {"alice": "missed"}),
    ]
    result = recommend([alice], records, today="2026-05-10")
    assert len(result) == 1
    assert result[0].teammate == alice
    assert result[0].reason == "missed_last_week"


# ---------------------------------------------------------------------------
# Test 2: missed 2-of-last-4 but NOT the most recent → shaky_attendance
# ---------------------------------------------------------------------------

def test_shaky_attendance():
    bob = make_teammate("bob")
    # Most recent: came; then missed, missed, came
    records = [
        make_record("2026-05-07", {"bob": "came"}),
        make_record("2026-04-30", {"bob": "missed"}),
        make_record("2026-04-23", {"bob": "missed"}),
        make_record("2026-04-16", {"bob": "came"}),
    ]
    result = recommend([bob], records, today="2026-05-10")
    assert len(result) == 1
    assert result[0].teammate == bob
    assert result[0].reason == "shaky_attendance"


# ---------------------------------------------------------------------------
# Test 3: not pinged in 21 days → social_checkin
# ---------------------------------------------------------------------------

def test_social_checkin():
    carol = make_teammate("carol")
    # Single record, outside the 21-day window — carol was never pinged
    records = [
        make_record("2026-04-01", {"carol": "came"}, pinged=["someone_else"]),
    ]
    result = recommend([carol], records, today="2026-05-10")
    assert len(result) == 1
    assert result[0].teammate == carol
    assert result[0].reason == "social_checkin"


# ---------------------------------------------------------------------------
# Test 4: always-shows exclusion blocks rules 1 and 2
# ---------------------------------------------------------------------------

def test_always_shows_excluded_from_rules_1_and_2():
    # dave: 6 "came" in [:6] → always-shows (100% rate, ≥4 records).
    # ed: single "missed" at index 0 → would fire rule 1; not always-shows.
    # We give ed only 1 record so always-shows doesn't apply (< 4 records with data).
    # Verify: only ed appears for rule 1; dave is skipped by the exclusion check.
    dave = make_teammate("dave")
    ed = make_teammate("ed")
    records = [
        make_record("2026-05-07", {"dave": "came", "ed": "missed"}),
        make_record("2026-04-30", {"dave": "came"}),
        make_record("2026-04-23", {"dave": "came"}),
        make_record("2026-04-16", {"dave": "came"}),
        make_record("2026-04-09", {"dave": "came"}),
        make_record("2026-04-02", {"dave": "came"}),
    ]

    # Pass dave first so rule-1 loop encounters him before ed; without
    # the exclusion dave would appear first.  With it, only ed appears.
    result = recommend([dave, ed], records, today="2026-05-10")

    doc_ids_with_rule = {s.teammate.doc_id: s.reason for s in result}
    assert "ed" in doc_ids_with_rule
    assert doc_ids_with_rule["ed"] == "missed_last_week"
    # dave must NOT appear for rules 1 or 2 — he may appear for social_checkin.
    assert doc_ids_with_rule.get("dave") != "missed_last_week"
    assert doc_ids_with_rule.get("dave") != "shaky_attendance"


# ---------------------------------------------------------------------------
# Test 5: always-shows exclusion does NOT prevent social_checkin
# ---------------------------------------------------------------------------

def test_always_shows_still_gets_social_checkin():
    eve = make_teammate("eve")
    # 6 came → always-shows for rules 1/2
    records = [
        make_record("2026-05-07", {"eve": "came"}, pinged=[]),
        make_record("2026-04-30", {"eve": "came"}, pinged=[]),
        make_record("2026-04-23", {"eve": "came"}, pinged=[]),
        make_record("2026-04-16", {"eve": "came"}, pinged=[]),
        make_record("2026-04-09", {"eve": "came"}, pinged=[]),
        make_record("2026-04-02", {"eve": "came"}, pinged=[]),
    ]
    # eve has never been pinged within the last 21 days
    result = recommend([eve], records, today="2026-05-10")
    reasons = [s.reason for s in result]
    assert "social_checkin" in reasons


# ---------------------------------------------------------------------------
# Test 6: no duplicates — rule-1 match prevents rule-2 match
# ---------------------------------------------------------------------------

def test_no_duplicates_rule1_prevents_rule2():
    frank = make_teammate("frank")
    # Most-recent missed (triggers rule 1) AND missed 2-of-4 (would trigger rule 2)
    records = [
        make_record("2026-05-07", {"frank": "missed"}),
        make_record("2026-04-30", {"frank": "missed"}),
        make_record("2026-04-23", {"frank": "came"}),
        make_record("2026-04-16", {"frank": "came"}),
    ]
    result = recommend([frank], records, today="2026-05-10")
    doc_ids = [s.teammate.doc_id for s in result]
    assert doc_ids.count("frank") == 1
    assert result[0].reason == "missed_last_week"


# ---------------------------------------------------------------------------
# Test 7: cap at 3 suggestions
# ---------------------------------------------------------------------------

def test_cap_at_three():
    teammates = [make_teammate(f"t{i}") for i in range(5)]
    # All 5 missed last practice
    records = [
        make_record("2026-05-07", {f"t{i}": "missed" for i in range(5)}),
    ]
    result = recommend(teammates, records, today="2026-05-10")
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Test 8: empty roster → empty list
# ---------------------------------------------------------------------------

def test_empty_roster():
    result = recommend([], [], today="2026-05-10")
    assert result == []


# ---------------------------------------------------------------------------
# Test 9: no prior practices → only social_checkin can fire
# ---------------------------------------------------------------------------

def test_no_prior_practices_social_checkin_only():
    grace = make_teammate("grace")
    result = recommend([grace], [], today="2026-05-10")
    assert len(result) == 1
    assert result[0].reason == "social_checkin"


# ---------------------------------------------------------------------------
# Test 10: only "unknown" attendance → shaky rule does NOT fire
# ---------------------------------------------------------------------------

def test_unknown_attendance_does_not_trigger_shaky():
    henry = make_teammate("henry")
    # 4 records all "unknown" — should not count as misses
    records = [
        make_record("2026-05-07", {"henry": "unknown"}),
        make_record("2026-04-30", {"henry": "unknown"}),
        make_record("2026-04-23", {"henry": "unknown"}),
        make_record("2026-04-16", {"henry": "unknown"}),
    ]
    result = recommend([henry], records, today="2026-05-10")
    for suggestion in result:
        assert suggestion.reason != "shaky_attendance"
        assert suggestion.reason != "missed_last_week"
