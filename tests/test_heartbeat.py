# tests/test_heartbeat.py
from __future__ import annotations
import os
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
os.environ.setdefault("GCP_PROJECT_ID", "klaus-agent")


def test_signal_fields():
    from core.heartbeat import Signal, SEVERITY_CRITICAL
    s = Signal(
        fingerprint="cron:morning-briefing:stale",
        severity=SEVERITY_CRITICAL,
        area="cron",
        title="morning-briefing did not run",
        detail="last run 30h ago",
        remediation="Check Cloud Scheduler job klaus-morning-briefing.",
    )
    assert s.fingerprint == "cron:morning-briefing:stale"
    assert s.severity == "critical"
