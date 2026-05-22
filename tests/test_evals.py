"""Fixture schema validation for tick-brain eval harness (AUTO-08).

Plan 18-04 ships 5 hand-written seed fixtures at evals/tick_brain/fixtures/.
These tests validate the contract every fixture must conform to so the eval
harness (scripts/eval_tick_brain.py, Plan 08) and the retroactive-labeling
workflow (evals/tick_brain/README.md) stay stable.

WARNING 8 regression guard: test_followup_only_fixture_expects_silence pins
fixture 0003-due-followup.json's ground_truth.should_speak to False. Per D-13,
the dedicated _compose_followup path handles due follow-ups; tick-brain stays
silent on those snapshots. Do not "fix" this to True without reading
evals/tick_brain/README.md "What should_speak Means".
"""
from __future__ import annotations

import glob
import json
import os
import re

import pytest

_FIXTURE_GLOB = "evals/tick_brain/fixtures/*.json"
_VALID_TRIGGER_TYPES = {"overdue", "gap", "silence", "followup", "quiet"}
_REQUIRED_TOP_KEYS = {"id", "captured_at", "situation_snapshot", "trigger_type", "ground_truth"}
_REQUIRED_SNAPSHOT_KEYS = {
    "calendar",
    "ticktick_overdue",
    "unread_email_count",
    "due_followups",
    "hours_since_contact",
    "recent_journal_digest",
    "self_state",
    "today_outreach_log",
    "now_context",
}


def _all_fixture_paths() -> list[str]:
    return sorted(glob.glob(_FIXTURE_GLOB))


class TestFixtureSchema:
    """Validates every fixture under evals/tick_brain/fixtures/."""

    def test_at_least_five_fixtures(self):
        assert len(_all_fixture_paths()) >= 5, "AUTO-08 requires >=5 seed fixtures"

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_each_fixture_is_valid_json(self, path):
        with open(path) as f:
            json.loads(f.read())

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_each_fixture_has_required_keys(self, path):
        data = json.loads(open(path).read())
        missing = _REQUIRED_TOP_KEYS - data.keys()
        assert not missing, f"{path}: missing keys {missing}"

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_each_situation_snapshot_has_required_keys(self, path):
        data = json.loads(open(path).read())
        snap = data["situation_snapshot"]
        missing = _REQUIRED_SNAPSHOT_KEYS - snap.keys()
        assert not missing, f"{path}: situation_snapshot missing keys {missing}"

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_each_trigger_type_is_valid_enum(self, path):
        data = json.loads(open(path).read())
        assert data["trigger_type"] in _VALID_TRIGGER_TYPES, (
            f"{path}: trigger_type={data['trigger_type']!r} not in {_VALID_TRIGGER_TYPES}"
        )

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_each_ground_truth_has_should_speak_bool(self, path):
        data = json.loads(open(path).read())
        assert isinstance(data["ground_truth"]["should_speak"], bool), (
            f"{path}: ground_truth.should_speak must be bool"
        )

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_topic_key_pattern_required_when_should_speak(self, path):
        data = json.loads(open(path).read())
        gt = data["ground_truth"]
        if gt["should_speak"]:
            assert "topic_key_pattern" in gt, (
                f"{path}: should_speak=true requires topic_key_pattern"
            )
            re.compile(gt["topic_key_pattern"])  # raises if invalid regex

    @pytest.mark.parametrize("path", _all_fixture_paths())
    def test_id_matches_filename_stem(self, path):
        data = json.loads(open(path).read())
        stem = os.path.splitext(os.path.basename(path))[0]
        assert data["id"] == stem, (
            f"{path}: id={data['id']!r} != filename stem {stem!r}"
        )

    def test_followup_only_fixture_expects_silence(self):
        """WARNING 8 regression guard — per D-13 the followup path bypasses tick-brain,
        so a followup-only snapshot's expected tick-brain behavior is silence."""
        path = "evals/tick_brain/fixtures/0003-due-followup.json"
        data = json.loads(open(path).read())
        assert data["ground_truth"]["should_speak"] is False, (
            "WARNING 8 regression: 0003-due-followup.json should_speak must be false "
            "(see evals/tick_brain/README.md 'What should_speak Means')"
        )
