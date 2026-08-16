"""Repository/ZIP drift guards for Klaus's uploaded Claude skill suite."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = (
    "klaus-live-agent",
    "klaus-morning-review",
    "klaus-nightly-review",
    "klaus-weekly-review",
)
ROUTINE_NAMES = (
    "klaus-morning-review",
    "klaus-nightly-review",
    "klaus-weekly-review",
)

sys.path.insert(0, str(ROOT / "scripts" / "active"))


def _skill_text(name: str) -> str:
    """Return the SKILL.md text as uploaded, with shared includes expanded.

    Safety rules live once under claude/skills/_shared/ and are expanded inline
    at package time, so assertions must run against the rendered result. Reading
    the raw source would let a rule that ships correctly look like a regression —
    and worse, would stop noticing if the expansion broke.
    """
    from package_claude_skills import render_skill

    return render_skill(name)


def test_skill_sources_and_mcp_capability_version_match():
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION

    for name in SKILL_NAMES:
        skill_dir = ROOT / "claude" / "skills" / name
        assert (skill_dir / "SKILL.md").is_file()
        assert (skill_dir / "VERSION").read_text().strip() == EXPECTED_SKILL_VERSION


def test_uploadable_zips_exactly_match_canonical_sources():
    version = (ROOT / "claude" / "skills" / SKILL_NAMES[0] / "VERSION").read_text().strip()
    for name in SKILL_NAMES:
        source = ROOT / "claude" / "skills" / name
        artifact = ROOT / "claude" / "dist" / f"{name}-{version}.zip"
        assert artifact.is_file(), f"missing upload artifact: {artifact}"
        with zipfile.ZipFile(artifact) as archive:
            skill_path = f"{name}/SKILL.md"
            version_path = f"{name}/VERSION"
            assert sorted(archive.namelist()) == [skill_path, version_path]
            # The shipped SKILL.md is the rendered one — shared includes expanded
            # inline — so Claude receives a self-contained file with no reference
            # it might decline to load.
            assert archive.read(skill_path).decode("utf-8") == _skill_text(name)
            assert archive.read(version_path) == (source / "VERSION").read_bytes()
            assert b"<!-- INCLUDE:" not in archive.read(skill_path), (
                f"{name} shipped an unexpanded include marker"
            )


def test_packager_check_mode_detects_no_drift():
    result = subprocess.run(
        [sys.executable, "scripts/active/package_claude_skills.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_skill_eval_suite_covers_each_skill_with_three_pressure_cases():
    evaluations = json.loads((ROOT / "claude" / "evals" / "skill-evals.json").read_text())
    counts = Counter(case["skill"] for case in evaluations)
    assert set(counts) == set(SKILL_NAMES)
    assert all(counts[name] >= 3 for name in SKILL_NAMES)
    assert all(len(case.get("expected_behavior", [])) >= 2 for case in evaluations)


def test_skills_encode_non_negotiable_authority_and_safety_rules():
    combined = "\n".join(
        _skill_text(name).lower()
        for name in SKILL_NAMES
    )
    required_phrases = (
        "klaus backend",
        "authoritative",
        "idempotency_key",
        "untrusted data",
        "approximately 20%",
        "recommendation-only",
        "publish_review",
        "source urls",
    )
    for phrase in required_phrases:
        assert phrase in combined


def test_routine_skills_forbid_write_based_schema_discovery():
    for name in ROUTINE_NAMES:
        text = _skill_text(name).lower()
        assert "never call a write tool to discover its schema" in text
        assert "final and one-shot" in text
        assert "correlation_id" in text
        assert "partial_actions" in text

    nightly = _skill_text("klaus-nightly-review").lower()
    for field in ("summary", "mood", "current_focus", "recent_context", "highlights"):
        assert field in nightly


def test_routine_skills_render_exact_published_text_after_success():
    for name in ROUTINE_NAMES:
        text = _skill_text(name).lower()
        normalized = " ".join(text.split())
        assert "exact published review text" in text
        assert "final assistant response" in text
        assert "consist solely of the exact published review text" in normalized
        assert "do not add a preamble, status line, acknowledgement, or postscript" in normalized
        assert "you may append" not in text
        assert "do not replace it with an acknowledgement" in text
        assert "do not call `publish_review` again" in text
        assert "if `publish_review` fails" in text


def test_routine_skills_forbid_live_side_effects_in_shadow_mode():
    for name in ROUTINE_NAMES:
        text = _skill_text(name).lower()
        normalized = " ".join(text.split())
        assert "when `delivery_mode` is `shadow`" in normalized
        assert "do not call any mutating tool except the single `publish_review`" in normalized
        assert "do not create, edit, complete, reschedule, or delete tasks" in normalized
        assert "record proposed actions only in `partial_actions`" in normalized


def test_skill_version_is_consistent_everywhere():
    """One version string, asserted in all four places it is written down."""
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION

    assert EXPECTED_SKILL_VERSION == "7.4.0"
    assert f'"skill_version": "{EXPECTED_SKILL_VERSION}"' in (
        ROOT / "core" / "subscription_routines.py"
    ).read_text()
    for name in SKILL_NAMES:
        assert (
            ROOT / "claude" / "skills" / name / "VERSION"
        ).read_text().strip() == EXPECTED_SKILL_VERSION
        # Each skill states its own version in prose so Claude can warn Amit when
        # the uploaded copy is stale.
        assert EXPECTED_SKILL_VERSION in _skill_text(name)


def test_live_agent_captures_and_files_tasks_in_the_moment():
    """Spec 3.1. Deferring capture to the nightly review was explicitly rejected.

    Amit's blocker is deciding where a to-do goes, not writing it down, so Klaus
    must file it himself rather than asking.
    """
    text = _skill_text("klaus-live-agent")
    assert "## Tasks" in text
    assert "list_id" in text, "must tell Klaus to file, not just create"
    assert "in that turn" in text
    lowered = text.lower()
    assert "do not ask" in lowered or "never ask" in lowered
    assert "invent" in lowered, "must forbid inventing dates"


def test_nightly_review_plans_tomorrow_and_writes_the_plan():
    """Spec 3.2. The plan is written when sent — no pending-plan state."""
    text = _skill_text("klaus-nightly-review")
    assert "## Plan tomorrow" in text
    lowered = text.lower()
    assert "footprints" in lowered, "planning must check the plan against real durations"
    assert "created_at" in text, "tidying needs the staleness field"
    assert "do not wait" in lowered or "without waiting" in lowered


def test_skills_read_facts_from_the_profile_instead_of_restating_them():
    """The regression this consolidation exists to prevent.

    Durable facts about Amit belong in docs/USER.md, which reaches Claude every
    turn in the snapshot's `profile` block. A fact copied into one skill is a
    fact the other three do not have — that is how the nightly review ended up
    knowing his real gym footprint while the morning review, which also plans his
    day, did not.
    """
    for name in SKILL_NAMES:
        text = _skill_text(name)
        assert "profile" in text.lower(), f"{name} never mentions the profile block"

    # Specific values that previously lived in exactly one skill each. If one
    # reappears here, it has been copied back out of USER.md.
    for name in SKILL_NAMES:
        lowered = _skill_text(name).lower()
        assert "3h15" not in lowered, f"{name} restates the gym footprint"
        assert "median age" not in lowered, f"{name} restates the task-age measurement"


def test_shared_safety_rules_are_defined_once():
    """Untrusted-source handling drifted into three wordings before it was shared."""
    shared = ROOT / "claude" / "skills" / "_shared"
    assert (shared / "safety.md").is_file()
    assert (shared / "routine-contract.md").is_file()

    for name in SKILL_NAMES:
        source = (ROOT / "claude" / "skills" / name / "SKILL.md").read_text()
        assert "<!-- INCLUDE: safety -->" in source, f"{name} must share the safety rules"
        # The prose itself must exist only in the shared file.
        assert "never instructions" not in source, f"{name} inlines its own untrusted-source rule"

    for name in ROUTINE_NAMES:
        source = (ROOT / "claude" / "skills" / name / "SKILL.md").read_text()
        assert "<!-- INCLUDE: routine-contract -->" in source
        assert "final and one-shot" not in source, f"{name} inlines its own publication contract"


def test_nightly_review_still_honours_shadow_mode():
    """Shadow mode forbids every mutating call; planning must not bypass it."""
    text = _skill_text("klaus-nightly-review")
    assert "## Shadow mode" in text
    plan_section = text.split("## Plan tomorrow", 1)[1].split("\n## ", 1)[0]
    assert "shadow" in plan_section.lower(), "the planning section must defer to it"


def test_evals_cover_the_task_partnership_behaviours():
    """The three failure modes most likely to reappear as 'helpful' defaults."""
    cases = json.loads((ROOT / "claude" / "evals" / "skill-evals.json").read_text())
    blob = json.dumps(cases).lower()
    assert "inbox" in blob, "filing rather than defaulting to the Inbox"
    assert "invent" in blob or "fabricat" in blob, "not inventing dates"
    assert "overdue" in blob, "not nagging about overdue items"

    by_query = {case["query"]: case for case in cases}

    shadow_query = (
        "Run tonight's review in shadow mode. Amit has eleven stale to-dos "
        "that need refiling."
    )
    assert shadow_query in by_query, "must exercise shadow mode with a query that actually sets it"
    shadow_case = by_query[shadow_query]
    assert shadow_case["skill"] == "klaus-nightly-review"
    assert any("partial_actions" in b for b in shadow_case["expected_behavior"])
    assert any("no mutating tool" in b.lower() for b in shadow_case["expected_behavior"])


def test_skills_consult_reconciled_training_reality_before_asking():
    """WB-04 — the reasoning surfaces must read the reconciled window.

    Without this each skill re-derives planned-vs-actual from raw sources, which
    is how Klaus ended up asking about a session Amit had already done.
    """
    for name in ("klaus-live-agent", "klaus-nightly-review", "klaus-weekly-review"):
        normalized = " ".join(_skill_text(name).split())
        assert "get_training_reality" in normalized, name
