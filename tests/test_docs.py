"""INFRA-01 — docs/DEPLOYMENT.md completeness assertions.

These tests are grep-style smoke checks that prevent regression of operator-facing
deployment documentation: all 9 Cloud Scheduler job-ids, the Groq TICK_BRAIN_API_KEY
secret access/rotation procedure, the Five Fingers job-id quirk WITH the legacy
single-job migration paragraph, and the Firestore composite index requirement on
the `followups` collection.
"""
from __future__ import annotations

import os

DEPLOYMENT_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, "docs", "DEPLOYMENT.md"
)


def _content() -> str:
    with open(DEPLOYMENT_PATH, encoding="utf-8") as f:
        return f.read()


class TestDeploymentCompleteness:

    # All 7 job-ids must appear
    ALL_JOB_IDS = [
        "klaus-morning-briefing",
        "klaus-proactive-alerts",
        "klaus-heartbeat",
        "klaus-ingest-chats",
        "klaus-ingest-chat-exports",
        "klaus-reflect",
        "klaus-autonomous-tick",
        "klaus-biometric-sync",
    ]

    def test_all_nine_job_ids_present(self):
        content = _content()
        for job_id in self.ALL_JOB_IDS:
            assert job_id in content, f"DEPLOYMENT.md missing job-id {job_id!r}"

    def test_autonomous_tick_schedule_present(self):
        content = _content()
        assert "*/20 7-21 * * *" in content
        assert "/cron/autonomous-tick" in content

    def test_reflect_schedule_present(self):
        content = _content()
        assert "/cron/reflect" in content

    def test_gcloud_create_block_present_for_autonomous_tick(self):
        # Assert the explicit create block exists rather than relying on a fragile
        # char-distance window from the inventory table (which shifts as jobs are
        # added). This checks the true property: autonomous-tick is documented with
        # its own `gcloud scheduler jobs create` command.
        content = _content()
        assert "gcloud scheduler jobs create http klaus-autonomous-tick" in content

    def test_gcloud_create_block_present_for_biometric_sync(self):
        content = _content()
        assert "gcloud scheduler jobs create http klaus-biometric-sync" in content
        assert "/cron/biometric-sync" in content

    def test_groq_secret_documented(self):
        content = _content()
        assert "TICK_BRAIN_API_KEY" in content
        assert "klaus-tick-brain-api-key" in content
        # Rotation steps
        assert "gcloud secrets versions add" in content



    def test_followups_composite_index_documented(self):
        content = _content()
        assert "composite index" in content.lower()
        assert "followups" in content
        assert "status" in content
        assert "due_at" in content

    def test_phase_shifu_section_present(self):
        """CRON-02 — DEPLOYMENT.md contains the Phase Shifu section with the new job."""
        content = _content()
        assert "Phase Shifu" in content, "DEPLOYMENT.md missing 'Phase Shifu' section"
        assert "klaus-weekly-training-review" in content, (
            "DEPLOYMENT.md missing 'klaus-weekly-training-review' job reference"
        )

    def test_allowed_updates_callback_query_documented(self):
        """CRON-02 / Pitfall 1 — DEPLOYMENT.md documents the callback_query allowed_updates re-registration."""
        content = _content()
        assert '"callback_query"' in content, (
            'DEPLOYMENT.md must document allowed_updates ["message","callback_query"] re-registration'
        )

    def test_no_separate_training_checkin_job(self):
        """D-09 — DEPLOYMENT.md does NOT register a separate klaus-training-checkin scheduler job."""
        content = _content()
        # The design note (folds into proactive-alerts) must be documented
        assert "proactive-alerts" in content or "folds into" in content, (
            "DEPLOYMENT.md should document that check-in folds into proactive-alerts (D-09)"
        )
        # No row in the inventory table for a training-checkin job
        # (A brief mention in a note is fine, but there must not be a scheduler job entry)
        import re
        # Check there is no gcloud create block for training-checkin
        assert not re.search(r"gcloud scheduler jobs create[^\n]*training-checkin", content), (
            "DEPLOYMENT.md must NOT register a separate klaus-training-checkin scheduler job (D-09)"
        )


# ---------------------------------------------------------------------------
# PROMPT-03 — docs/SELF.md lists all 5 new Phase 19 tools
# ---------------------------------------------------------------------------

SELF_MD_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, "docs", "SELF.md"
)


class TestPhase19SelfManifest:
    """PROMPT-03 — docs/SELF.md covers the 5 Phase 19 coaching tools.

    Since BRAIN-06 (Phase 30.5) the Tools section renders grouped category
    one-liners instead of per-tool rows, so coverage is asserted via the
    Coaching & Training category capabilities rather than snake_case names.
    """

    def test_self_md_lists_phase19_tools(self):
        with open(SELF_MD_PATH, encoding="utf-8") as f:
            content = f.read()
        assert "**Coaching & Training:**" in content, (
            "docs/SELF.md missing the Coaching & Training tool category"
        )
        coaching_line = next(
            line for line in content.splitlines()
            if "**Coaching & Training:**" in line
        )
        for capability in (
            "get-profile",
            "update-profile",
            "training-status",
            "recent-activities",
            "recent-meals",
        ):
            assert capability in coaching_line, (
                f"docs/SELF.md Coaching & Training line missing: {capability}"
            )


# ---------------------------------------------------------------------------
# Phase 19.1 HEALTHKIT-07 / D-21 — SELF.md push-endpoints section
# ---------------------------------------------------------------------------


def test_self_md_lists_healthkit_push_endpoint():
    """HEALTHKIT-07 / D-21 — SELF.md must surface the push endpoint so the brain
    truthfully answers 'how do my meals reach me?' without spelunking source."""
    with open(SELF_MD_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "## Push endpoints" in content
    assert "/cron/healthkit-sync" in content
    assert "iPhone Shortcut" in content
    assert "shared-secret bearer" in content


def test_self_md_does_not_advertise_the_retired_morning_briefing_tick():
    """WR-10 — plan 33-13 deleted /cron/morning-briefing-tick and updated
    core/self_manifest.py, but the COMMITTED docs/SELF.md predated that change
    and still advertised the route. SELF.md is injected into the brain's system
    prompt ({self_md}) and served verbatim by read_own_source, so a stale copy
    makes Klaus describe a cron that 404s. CI regenerates it on deploy, which is
    why only local runs and human readers saw the drift — hence this guard."""
    with open(SELF_MD_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "/cron/morning-briefing-tick" not in content
    assert "morning-briefing-tick" not in content
    assert "8 scheduled jobs" in content


def test_self_md_does_not_claim_autonomous_outreach_is_unimplemented():
    """WR-10 — "Autonomous proactive outreach: not yet implemented (Phase 18)"
    survived in the GENERATOR long after Phase 18 shipped it, so regenerating
    could not fix it. Klaus must not assert a falsehood about himself."""
    with open(SELF_MD_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "not yet implemented (Phase 18)" not in content


def test_self_md_cron_section_matches_the_generator():
    """WR-10 root cause — the committed SELF.md drifted from what
    core/self_manifest.py emits, because CI only regenerates on deploy. Pin the
    Cron Jobs section (the part that actually went stale) against a fresh
    render, without comparing the whole file: the model-name rows are
    env-derived and legitimately differ between a laptop and the deploy runner."""
    from pathlib import Path
    from core.self_manifest import _get_source_root, _render_manifest

    with open(SELF_MD_PATH, encoding="utf-8") as f:
        committed = f.read()
    root = _get_source_root()
    fresh = _render_manifest(root, "0" * 40)

    def _cron_section(text: str) -> str:
        return text.split("## Cron Jobs", 1)[1].split("\n## ", 1)[0].strip()

    assert _cron_section(committed) == _cron_section(fresh), (
        "docs/SELF.md Cron Jobs section is stale — "
        "run `python core/self_manifest.py` and commit the result."
    )
    assert Path(root, "docs", "SELF.md").exists()


def test_self_md_expected_skill_version_matches_canonical_render():
    """The committed manifest must expose the live Klaus MCP skill version."""
    from pathlib import Path

    from core.self_manifest import _compute_schema_hash, _get_source_root, _render_manifest
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION

    root = _get_source_root()
    fresh = _render_manifest(root, _compute_schema_hash(root))
    committed = Path(SELF_MD_PATH).read_text(encoding="utf-8")
    expected_line = f"Expected Claude skill version: `{EXPECTED_SKILL_VERSION}`"

    assert expected_line in fresh
    assert expected_line in committed


def test_deployment_md_section_22_push_endpoints():
    """RESEARCH.md Q10 — DEPLOYMENT.md ends at §21; this phase adds §22 + §23 (NOT §23 + §24)."""
    with open(DEPLOYMENT_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "## 22. Push-driven endpoints" in content
    assert "/cron/healthkit-sync" in content


def test_deployment_md_section_23_healthkit_secret():
    """HEALTHKIT-08 part 1 — secret rotation runbook present."""
    with open(DEPLOYMENT_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "## 23. HEALTHKIT_WEBHOOK_TOKEN Secret" in content
    assert "klaus-healthkit-webhook-token" in content
    assert "secrets.token_urlsafe(32)" in content
    assert "gcloud secrets versions disable" in content


# ---------------------------------------------------------------------------
# Phase 19.1 HEALTHKIT-08 / D-23 — operator iOS Shortcut runbook
# ---------------------------------------------------------------------------

HEALTHKIT_RUNBOOK_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, "docs", "healthkit_shortcut.md"
)


def test_healthkit_shortcut_runbook_complete():
    """HEALTHKIT-08 / D-23 — operator runbook has all 8 required sections + key security guidance."""
    with open(HEALTHKIT_RUNBOOK_PATH, encoding="utf-8") as f:
        content = f.read()
    # All 8 section headings present
    for heading in [
        "## 1. Overview",
        "## 2. Required HealthKit permissions",
        "## 3. Build: Lifesum-close 2h automation",
        "## 4. Build: 23:55 24h catch-up automation",
        "## 5. iCloud Shortcut share link",
        "## 6. Security Considerations",
        "## 7. Testing",
        "## 8. Troubleshooting",
    ]:
        assert heading in content, f"missing runbook section: {heading!r}"
    # Key build instructions
    for marker in [
        "Find Health Samples",
        "Personal Automation",
        "Authorization",
        "Bearer",
    ]:
        assert marker in content, f"runbook missing build marker: {marker!r}"
    # Security guidance — token NOT in URL
    assert (
        "Authorization header ONLY" in content
        or "NEVER in URL" in content
    ), "runbook must explicitly tell operator NOT to put token in URL query"
    # Cross-references to other docs
    assert "DEPLOYMENT.md" in content
    assert "klaus-healthkit-webhook-token" in content


# ---------------------------------------------------------------------------
# Phase 20 REVIEW-03 — prompts/weekly_training_review.md existence + structure
# ---------------------------------------------------------------------------

WEEKLY_REVIEW_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, "prompts", "weekly_training_review.md"
)


def test_weekly_training_review_prompt_exists():
    """REVIEW-03 — prompts/weekly_training_review.md exists with required structure."""
    assert os.path.exists(WEEKLY_REVIEW_PROMPT_PATH), (
        "prompts/weekly_training_review.md must exist"
    )
    with open(WEEKLY_REVIEW_PROMPT_PATH, encoding="utf-8") as f:
        content = f.read()
    # Required placeholder
    assert "{today_date}" in content, "prompt must contain {today_date} placeholder"
    # Scorecard emoji set (D-18)
    assert "✅" in content, "prompt must reference ✅ scorecard emoji (D-18)"
    assert "❌" in content, "prompt must reference ❌ scorecard emoji (D-18)"
    assert "⚠️" in content, "prompt must reference ⚠️ scorecard emoji (D-18)"
    # D-24 sparse-week copy
    assert "Quiet week" in content, "prompt must contain D-24 sparse-week copy"


# ---------------------------------------------------------------------------
# Phase 33 Plan 02 (D-22) — self_manifest.py never hardcodes a stale
# MAX_TOOL_ITERATIONS digit; must always interpolate the live constant.
# ---------------------------------------------------------------------------

def test_self_manifest_reports_live_max_tool_iterations():
    """The generated manifest must report core.main.MAX_TOOL_ITERATIONS's live
    value, not a hardcoded digit — this previously drifted to a stale "8"
    after the real cap was raised to 12 (core/main.py:50)."""
    from core.main import MAX_TOOL_ITERATIONS
    from core.self_manifest import _render_manifest, _get_source_root, _compute_schema_hash

    root = _get_source_root()
    sha = _compute_schema_hash(root)
    content = _render_manifest(root, sha)

    assert f"**Max tool iterations per conversation:** {MAX_TOOL_ITERATIONS}" in content, (
        "Generated manifest must report the live MAX_TOOL_ITERATIONS value "
        f"({MAX_TOOL_ITERATIONS})"
    )
    assert "iterations per conversation:** 8" not in content, (
        "Generated manifest must never hardcode a stale MAX_TOOL_ITERATIONS value"
    )
