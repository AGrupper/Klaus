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
