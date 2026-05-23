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

    # All 9 job-ids must appear
    ALL_JOB_IDS = [
        "klaus-five-fingers-morning",
        "klaus-five-fingers-evening",
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

    def test_five_fingers_quirk_documented(self):
        content = _content()
        assert "Five Fingers" in content
        assert "job-id" in content.lower() or "job id" in content.lower()

    def test_five_fingers_migration_paragraph_present(self):
        """Bonus WARNING — operators of older deploys need an explicit migration step."""
        content = _content()
        # The migration block instructs deleting the legacy single five-fingers job.
        assert "gcloud scheduler jobs delete five-fingers" in content, (
            "Bonus WARNING regression: migration paragraph for legacy single "
            "'five-fingers' Cloud Scheduler job missing from DEPLOYMENT.md"
        )
        # Migration must mention either "migration" or "Migration" for context.
        assert ("Migration" in content or "migration" in content), (
            "Migration paragraph should explicitly label itself as a migration step"
        )

    def test_followups_composite_index_documented(self):
        content = _content()
        assert "composite index" in content.lower()
        assert "followups" in content
        assert "status" in content
        assert "due_at" in content
