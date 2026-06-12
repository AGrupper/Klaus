"""Offline tests for scripts/export_tick_logs.py pure helpers.

No Firestore, no network — only the digest/fixture computation paths.
The script calls load_dotenv at import time (harmless) but the Firestore
stores are only imported inside the export subcommand, which these tests
never invoke.
"""
from __future__ import annotations

import json

import pytest

from scripts.export_tick_logs import (
    _build_fixture,
    _compact_signals,
    _digest_rows,
    _infer_trigger,
    _iter_dates,
    _layer1_verdict,
    _next_fixture_number,
    _render_day_table,
    _validate_fixture,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _snapshot(**overrides) -> dict:
    snap = {
        "calendar": [],
        "ticktick_overdue": [],
        "unread_email_count": 0,
        "due_followups": [],
        "hours_since_contact": 1.0,
        "recent_journal_digest": "",
        "self_state": {"current_focus": "", "mood": ""},
        "today_outreach_log": [],
        "now_context": {
            "now_iso": "2026-06-03T14:20:00+03:00",
            "now_local": "14:20 Asia/Jerusalem",
            "tick_index": 22, "tick_total": 43,
            "last_tick_at": "2026-06-03T14:00:00+03:00",
        },
        "meals_since_last_tick": [],
        "training_status": {},
        "acwr": {"acute": None, "chronic": None, "ratio": None},
    }
    snap.update(overrides)
    return snap


def _tick(time="14:20", snapshot=None, decision=None) -> dict:
    return {
        "time": time,
        "captured_at": "2026-06-03T11:20:00+00:00",
        "situation_snapshot": snapshot or _snapshot(),
        "decision_trail": decision or {"skipped": False, "sent": False, "trail": []},
    }


def _acted_decision(topic_key="overdue:maya", sent=True) -> dict:
    trail = [{"layer1": {"should_act": True, "reason": "task is overdue",
                         "draft": "Maya reply is overdue.", "topic_key": topic_key}}]
    if sent:
        trail.append({"shipped": topic_key})
    return {"skipped": False, "sent": sent, "trail": trail}


def _quiet_decision(reason="nothing salient") -> dict:
    return {"skipped": False, "sent": False,
            "trail": [{"layer1": {"should_act": False, "reason": reason}},
                      "layer1_no_act"]}


# ---------------------------------------------------------------------------
# _iter_dates / _layer1_verdict / _compact_signals
# ---------------------------------------------------------------------------

def test_iter_dates_inclusive():
    assert _iter_dates("2026-05-30", "2026-06-02") == [
        "2026-05-30", "2026-05-31", "2026-06-01", "2026-06-02",
    ]


def test_layer1_verdict_found_and_missing():
    assert _layer1_verdict(_acted_decision())["should_act"] is True
    assert _layer1_verdict({"trail": ["layer0_empty_signals"]}) is None


def test_compact_signals_renders_counts_and_unknown_hsc():
    snap = _snapshot(ticktick_overdue=[{"id": "a"}, {"id": "b"}],
                     hours_since_contact=None,
                     today_outreach_log=["overdue:maya"])
    s = _compact_signals(snap)
    assert "ov=2" in s and "hsc=?" in s and "outlog=1" in s


# ---------------------------------------------------------------------------
# _infer_trigger
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("overrides,expected", [
    ({"due_followups": [{"id": "fu1"}]}, "followup"),
    ({"ticktick_overdue": [{"id": "t1"}]}, "overdue"),
    ({"hours_since_contact": 9.0}, "silence"),
    ({}, "quiet"),
    # followup wins over overdue (matches WARNING-8 prominence)
    ({"due_followups": [{"id": "f"}], "ticktick_overdue": [{"id": "t"}]}, "followup"),
])
def test_infer_trigger(overrides, expected):
    assert _infer_trigger(_snapshot(**overrides)) == expected


# ---------------------------------------------------------------------------
# _next_fixture_number
# ---------------------------------------------------------------------------

def test_next_fixture_number(tmp_path):
    assert _next_fixture_number(tmp_path) == 1
    (tmp_path / "0001-a.json").write_text("{}")
    (tmp_path / "0005-b.json").write_text("{}")
    (tmp_path / "notes.md").write_text("")
    assert _next_fixture_number(tmp_path) == 6


# ---------------------------------------------------------------------------
# _build_fixture
# ---------------------------------------------------------------------------

def test_build_fixture_backfills_phase19_keys():
    """Pre-Phase-19 ticks lack meals/training/acwr — minting must add the
    production-default empties so the schema tests pass."""
    snap = _snapshot()
    for key in ("meals_since_last_tick", "training_status", "acwr"):
        del snap[key]
    fixture = _build_fixture(_tick(snapshot=snap), 6, "old-tick", True,
                             "^overdue:.*", "overdue", None)
    assert fixture["situation_snapshot"]["meals_since_last_tick"] == []
    assert fixture["situation_snapshot"]["training_status"] == {}
    assert fixture["situation_snapshot"]["acwr"] == {
        "acute": None, "chronic": None, "ratio": None,
    }


def test_build_fixture_id_captured_at_and_ground_truth():
    fixture = _build_fixture(_tick(), 12, "my-slug", True, "^gap:.*", "gap", "why")
    assert fixture["id"] == "0012-my-slug"
    # captured_at comes from now_context.now_iso, not the UTC write stamp
    assert fixture["captured_at"] == "2026-06-03T14:20:00+03:00"
    assert fixture["ground_truth"] == {
        "should_speak": True, "topic_key_pattern": "^gap:.*", "_note": "why",
    }
    assert _validate_fixture(fixture, "0012-my-slug") == []


def test_build_fixture_false_label_omits_pattern():
    fixture = _build_fixture(_tick(), 7, "quiet-noon", False, None, "quiet", None)
    assert fixture["ground_truth"] == {"should_speak": False}
    assert _validate_fixture(fixture, "0007-quiet-noon") == []


# ---------------------------------------------------------------------------
# _validate_fixture
# ---------------------------------------------------------------------------

def test_validate_fixture_catches_errors():
    fixture = _build_fixture(_tick(), 6, "s", True, "^overdue:.*", "overdue", None)

    broken = json.loads(json.dumps(fixture))
    del broken["situation_snapshot"]["acwr"]
    assert any("acwr" in e for e in _validate_fixture(broken, "0006-s"))

    broken = json.loads(json.dumps(fixture))
    broken["ground_truth"]["topic_key_pattern"] = "[unclosed"
    assert any("compile" in e for e in _validate_fixture(broken, "0006-s"))

    broken = json.loads(json.dumps(fixture))
    broken["trigger_type"] = "banana"
    assert any("trigger_type" in e for e in _validate_fixture(broken, "0006-s"))

    assert any("stem" in e for e in _validate_fixture(fixture, "0099-other"))

    broken = json.loads(json.dumps(fixture))
    del broken["ground_truth"]["topic_key_pattern"]
    assert any("topic_key_pattern" in e for e in _validate_fixture(broken, "0006-s"))


# ---------------------------------------------------------------------------
# _digest_rows — flags
# ---------------------------------------------------------------------------

def test_digest_rows_sent_and_verdict_rendering():
    rows = _digest_rows([
        _tick("07:00", decision={"skipped": "empty", "sent": False,
                                 "trail": ["layer0_empty_signals"]}),
        _tick("07:20", snapshot=_snapshot(ticktick_overdue=[{"id": "t1"}],
                                          hours_since_contact=4.5),
              decision=_acted_decision()),
    ])
    assert rows[0]["verdict"] == "skipped:empty"
    assert rows[0]["sent"] == "-"
    assert rows[1]["verdict"].startswith("ACT overdue:maya")
    assert rows[1]["sent"] == "yes overdue:maya"
    assert rows[1]["flag"] == ""  # real signal, sent — not suspicious


def test_digest_flags_marginal_send_as_fp():
    """Sent with no overdue/followup/meals and recent contact => FP? hint."""
    rows = _digest_rows([
        _tick(snapshot=_snapshot(hours_since_contact=1.2),
              decision=_acted_decision(topic_key="pattern:nudge")),
    ])
    assert rows[0]["flag"] == "FP?"


def test_digest_flags_repeatish_send_as_fp():
    """Sent topic whose prefix was already raised today => FP? hint."""
    rows = _digest_rows([
        _tick(snapshot=_snapshot(ticktick_overdue=[{"id": "t1"}],
                                 today_outreach_log=["overdue:maya"]),
              decision=_acted_decision(topic_key="overdue:maya-again")),
    ])
    assert rows[0]["flag"] == "FP?"


def test_digest_flags_persistent_overdue_silence_as_fn():
    """Same overdue ids unresolved for 3+ consecutive non-sent rows => FN?."""
    snap = lambda: _snapshot(ticktick_overdue=[{"id": "t1"}])  # noqa: E731
    ticks = [_tick(f"0{i}:00", snapshot=snap(), decision=_quiet_decision())
             for i in range(7, 11)]
    flags = [r["flag"] for r in _digest_rows(ticks)]
    assert flags[:2] == ["", ""]
    assert flags[2] == "FN?" and flags[3] == "FN?"


def test_digest_fn_streak_resets_on_send_or_id_change():
    snap_a = _snapshot(ticktick_overdue=[{"id": "a"}])
    snap_b = _snapshot(ticktick_overdue=[{"id": "b"}])
    ticks = [
        _tick("07:00", snapshot=snap_a, decision=_quiet_decision()),
        _tick("07:20", snapshot=snap_a, decision=_quiet_decision()),
        _tick("07:40", snapshot=snap_b, decision=_quiet_decision()),  # ids changed
        _tick("08:00", snapshot=snap_b, decision=_quiet_decision()),
    ]
    assert all(r["flag"] == "" for r in _digest_rows(ticks))


def test_digest_flags_long_silence_as_fn():
    rows = _digest_rows([
        _tick(snapshot=_snapshot(hours_since_contact=9.5),
              decision=_quiet_decision()),
    ])
    assert rows[0]["flag"] == "FN?"


# ---------------------------------------------------------------------------
# _render_day_table
# ---------------------------------------------------------------------------

def test_render_day_table_smoke():
    md = _render_day_table(
        "2026-06-03",
        [
            _tick("07:00", decision={"skipped": "empty", "sent": False,
                                     "trail": ["layer0_empty_signals"]}),
            _tick("14:20", snapshot=_snapshot(ticktick_overdue=[{"id": "t1"}]),
                  decision=_acted_decision()),
        ],
        outreach_entries=[{"topic_key": "overdue:maya", "time": "14:21"}],
    )
    assert md.startswith("## 2026-06-03  (2 ticks, 1 empty-skip, 1 L1-act, 1 sent: overdue:maya)")
    assert "| 14:20 |" in md
    assert "| Time | Signals | L1 verdict | Sent | Flag |" in md
