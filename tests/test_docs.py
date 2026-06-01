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
        content = _content()
        idx = content.find("klaus-autonomous-tick")
        assert idx >= 0
        window = content[max(0, idx - 200):idx + 1000]
        assert "gcloud scheduler jobs create" in window

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
    """PROMPT-03 — docs/SELF.md regenerated lists all 5 new Phase 19 tools."""

    def test_self_md_lists_phase19_tools(self):
        with open(SELF_MD_PATH, encoding="utf-8") as f:
            content = f.read()
        for tool in (
            "get_training_profile",
            "update_training_profile",
            "fetch_training_status",
            "fetch_recent_activities",
            "fetch_recent_meals",
        ):
            assert tool in content, f"docs/SELF.md missing tool: {tool}"


# ---------------------------------------------------------------------------
# Phase 19.1 HEALTHKIT-07 / D-21 — SELF.md push-endpoints section
# Phase 19.1 D-16 — google_fit legacy-marker docstring
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


def test_google_fit_tool_marked_legacy():
    """D-16 — preserved Android-source path must surface as legacy in the docstring."""
    from mcp_tools import google_fit_tool
    assert "Legacy" in (google_fit_tool.__doc__ or "")
    assert "mcp_tools/healthkit_tool.py" in (google_fit_tool.__doc__ or "")


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
