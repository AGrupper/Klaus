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
            assert archive.read(skill_path) == (source / "SKILL.md").read_bytes()
            assert archive.read(version_path) == (source / "VERSION").read_bytes()


def test_packager_check_mode_detects_no_drift():
    result = subprocess.run(
        [sys.executable, "scripts/package_claude_skills.py", "--check"],
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
        (ROOT / "claude" / "skills" / name / "SKILL.md").read_text().lower()
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
    routine_names = (
        "klaus-morning-review", "klaus-nightly-review", "klaus-weekly-review",
    )
    for name in routine_names:
        text = (ROOT / "claude" / "skills" / name / "SKILL.md").read_text().lower()
        assert "never call a write tool to discover its schema" in text
        assert "final and one-shot" in text
        assert "correlation_id" in text
        assert "partial_actions" in text

    nightly = (
        ROOT / "claude" / "skills" / "klaus-nightly-review" / "SKILL.md"
    ).read_text().lower()
    for field in ("summary", "mood", "current_focus", "recent_context", "highlights"):
        assert field in nightly


def test_routine_skills_render_exact_published_text_after_success():
    for name in (
        "klaus-morning-review",
        "klaus-nightly-review",
        "klaus-weekly-review",
    ):
        text = (ROOT / "claude" / "skills" / name / "SKILL.md").read_text().lower()
        assert "exact published review text" in text
        assert "final assistant response" in text
        assert "do not replace it with an acknowledgement" in text
        assert "do not call `publish_review` again" in text
        assert "if `publish_review` fails" in text


def test_skill_version_is_7_1_0_everywhere():
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION

    assert EXPECTED_SKILL_VERSION == "7.1.0"
    assert '"skill_version": "7.1.0"' in (
        ROOT / "core" / "subscription_routines.py"
    ).read_text()
    assert "Expected Claude skill version: `7.1.0`" in (
        ROOT / "core" / "self_manifest.py"
    ).read_text()
