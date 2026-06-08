"""Tests for prompts/autonomous_triage.md and prompts/autonomous.md.

These are key-phrase assertions on the two new system prompts authored for
the Phase 18 autonomous engine (Plan 18-03).

The integration test asserting that placeholders are RESOLVED at runtime
(i.e. the smart_system string passed to _run_smart_loop has no unsubstituted
{self_md} / {self_state} / {journal_digest} / {today_date}) belongs in
tests/test_autonomous.py — added in Plan 18-06. This file only asserts that
the placeholders are PRESENT in autonomous.md (WARNING 6 fix).
"""
from __future__ import annotations

import os
import re

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIAGE_PATH = os.path.join(REPO_ROOT, "prompts", "autonomous_triage.md")
AUTONOMOUS_PATH = os.path.join(REPO_ROOT, "prompts", "autonomous.md")
SMART_AGENT_PATH = os.path.join(REPO_ROOT, "prompts", "smart_agent.md")
MEAL_AUDIT_PATH = os.path.join(REPO_ROOT, "prompts", "meal_audit.md")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# TestAutonomousPrompts — key-phrase assertions on both prompt files
# ---------------------------------------------------------------------------


class TestAutonomousPrompts:
    """Phase 18 Plan 03 — key-phrase assertions on the two new prompts."""

    # ---- prompts/autonomous_triage.md ----

    def test_autonomous_triage_file_exists(self):
        assert os.path.isfile(TRIAGE_PATH), (
            f"Expected file at {TRIAGE_PATH}"
        )

    def test_autonomous_triage_contains_json_schema(self):
        content = _read(TRIAGE_PATH)
        for key in ("should_act", "reason", "draft", "topic_key"):
            assert key in content, (
                f"autonomous_triage.md missing JSON schema key {key!r}"
            )

    def test_autonomous_triage_contains_latitude_framing(self):
        content = _read(TRIAGE_PATH).lower()
        assert "no cadence cap" in content, (
            "autonomous_triage.md must contain 'no cadence cap' (D-02)"
        )
        assert "hours_since_contact" in content, (
            "autonomous_triage.md must reference hours_since_contact (D-05)"
        )

    def test_autonomous_triage_contains_topic_key_examples(self):
        content = _read(TRIAGE_PATH)
        for slug_prefix in (
            "overdue:",
            "silence:",
            "gap:",
            "followup:",
            "pattern:",
        ):
            assert slug_prefix in content, (
                f"autonomous_triage.md missing topic_key example prefix {slug_prefix!r}"
            )

    def test_autonomous_triage_contains_informative_suppression(self):
        """D-06 — outreach log is informative, not blocking."""
        content = _read(TRIAGE_PATH).lower()
        # Find 'block' occurrences and verify 'not' appears within a short
        # window before/after at least one of them (informative-not-blocking
        # phrasing). Allow up to 30 chars of separation in either direction.
        matched = False
        for m in re.finditer(r"\bblock\w*\b", content):
            start = max(0, m.start() - 30)
            end = min(len(content), m.end() + 30)
            window = content[start:end]
            if "not" in window:
                matched = True
                break
        assert matched, (
            "autonomous_triage.md must phrase suppression as 'not a block' / "
            "'informative-not-blocking' (D-06)"
        )

    # ---- prompts/autonomous.md ----

    def test_autonomous_md_file_exists(self):
        assert os.path.isfile(AUTONOMOUS_PATH), (
            f"Expected file at {AUTONOMOUS_PATH}"
        )

    def test_autonomous_md_no_second_veto(self):
        """D-17 — judgment happens once at the triage layer."""
        content = _read(AUTONOMOUS_PATH).lower()
        assert (
            "do not get to refuse" in content
            or "no second veto" in content
        ), (
            "autonomous.md must encode D-17 (no second veto) — expected "
            "either 'do not get to refuse' or 'no second veto' substring"
        )

    def test_autonomous_md_followup_action_schema(self):
        """D-13 — follow-up structured output {action: send|defer}."""
        content = _read(AUTONOMOUS_PATH)
        assert '"action": "send"' in content, (
            'autonomous.md must contain the structured-output spec '
            '{"action": "send"} (D-13)'
        )
        assert '"action": "defer"' in content, (
            'autonomous.md must contain the structured-output spec '
            '{"action": "defer"} (D-13)'
        )

    def test_autonomous_md_force_fire(self):
        """D-14 — force-send when defer_count >= 3."""
        content = _read(AUTONOMOUS_PATH)
        assert "defer_count >= 3" in content, (
            "autonomous.md must reference 'defer_count >= 3' force-fire "
            "threshold (D-14)"
        )
        assert "MUST send" in content, (
            "autonomous.md must contain 'MUST send' force-fire instruction "
            "(D-14)"
        )

    def test_autonomous_md_contains_self_md_placeholder(self):
        """WARNING 6 fix — autonomous.md must declare placeholders for the
        Plan 06 render_smart_system substitution step.

        Replaces the old `no_self_md_duplication` test, which gave false
        confidence because BLOCKER 5 proved the injection wasn't wired.
        """
        content = _read(AUTONOMOUS_PATH)
        for placeholder in (
            "{self_md}",
            "{self_state}",
            "{journal_digest}",
            "{today_date}",
        ):
            assert placeholder in content, (
                f"autonomous.md must contain placeholder {placeholder!r} "
                "(WARNING 6 — expected by AgentOrchestrator.render_smart_system "
                "in Plan 18-06)"
            )

    def test_autonomous_md_does_not_inline_smart_agent_identity(self):
        """Defensive guard — autonomous.md must rely on the {self_md} /
        smart_system injection, NOT copy-paste smart_agent.md's identity
        block inline. The distinctive identity sentence below would only
        appear if someone literally inlined it.
        """
        content = _read(AUTONOMOUS_PATH)
        identity_phrase = (
            "hyper-competent personal AI assistant whose personality "
            "blends JARVIS from Iron Man with C-3PO from Star Wars"
        )
        assert identity_phrase not in content, (
            "autonomous.md must not inline smart_agent.md's identity block — "
            "rely on {self_md} injection instead (Phase 18 D-16 / WARNING 6)"
        )


# ---------------------------------------------------------------------------
# TestPhase19Prompts — PROMPT-02 + NUTR-06 + NUTR-08
# ---------------------------------------------------------------------------


def test_smart_agent_has_training_section():
    """PROMPT-02 — smart_agent.md contains the new section + 5 tool names."""
    content = _read(SMART_AGENT_PATH)
    assert "{training_profile}" in content
    assert "TRAINING & ATHLETIC COACHING" in content
    # The 5 new tools must be mentioned by name
    for tool in (
        "fetch_training_status",
        "fetch_recent_activities",
        "fetch_recent_meals",
        "get_training_profile",
        "update_training_profile",
    ):
        assert tool in content, f"tool name missing from smart_agent.md: {tool}"


def test_triage_mentions_meal_triggers():
    """NUTR-06 — autonomous_triage.md has Meals as triggers section + meal_audit cross-link."""
    content = _read(TRIAGE_PATH)
    assert "Meals as triggers" in content
    assert "meals_since_last_tick" in content
    # Cross-reference to meal_audit.md per NUTR-08
    assert "meal_audit" in content


def test_meal_audit_exists():
    """NUTR-08 — prompts/meal_audit.md exists."""
    assert os.path.isfile(MEAL_AUDIT_PATH), (
        f"Expected prompts/meal_audit.md at {MEAL_AUDIT_PATH}"
    )


def test_meal_audit_referenced():
    """NUTR-08 wiring — meal_audit.md is mentioned by autonomous_triage.md."""
    triage = _read(TRIAGE_PATH)
    assert "meal_audit" in triage


# ---------------------------------------------------------------------------
# Phase 25 Plan 03 — weekly_training_review.md fence lift (PROG-02-L)
# ---------------------------------------------------------------------------

WEEKLY_REVIEW_PATH = os.path.join(REPO_ROOT, "prompts", "weekly_training_review.md")


def test_no_phase25_fence():
    """PROG-02-L: the weekly_training_review.md prompt no longer contains the
    Phase-24 'PHASE 25 FENCE' / 'ABSOLUTELY FORBIDDEN' prohibition and still
    contains the 'Week' framing (Week N of 16 preserved — Pitfall 5)."""
    content = _read(WEEKLY_REVIEW_PATH)
    assert "PHASE 25 FENCE" not in content, (
        "prompts/weekly_training_review.md still contains 'PHASE 25 FENCE' — "
        "fence lift (Task 3) not yet applied"
    )
    assert "ABSOLUTELY FORBIDDEN" not in content, (
        "prompts/weekly_training_review.md still contains 'ABSOLUTELY FORBIDDEN' — "
        "fence lift (Task 3) not yet applied"
    )
    assert "Week" in content, (
        "prompts/weekly_training_review.md lost 'Week' framing — "
        "'Week N of 16' block-relative language must be preserved (Pitfall 5)"
    )
