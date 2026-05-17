"""Klaus self-monitoring heartbeat.

Runs one health-check tick: inspects Klaus's own crons, integration tokens,
runtime degradation, and deployment state, then sends tiered Telegram alerts.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/heartbeat  (hourly, 0 * * * *, Asia/Jerusalem)

Local smoke test:
  python -m core.heartbeat --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_FYI = "fyi"


@dataclass
class Signal:
    """A single detected health problem.

    fingerprint: stable dedup key, e.g. "cron:morning-briefing:stale".
    severity:    SEVERITY_CRITICAL | SEVERITY_WARNING | SEVERITY_FYI.
    area:        "cron" | "token" | "degradation" | "deployment" | "code".
    title:       one-line human summary.
    detail:      specific evidence (numbers, timestamps).
    remediation: static fix hint.
    """
    fingerprint: str
    severity: str
    area: str
    title: str
    detail: str
    remediation: str


def _parse_hm(hm_str: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    try:
        h, m = hm_str.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        logger.warning("heartbeat: could not parse time %r", hm_str)
        return 0


def _in_quiet_hours(config: dict, now: datetime) -> bool:
    """Return True if `now` falls within the configured quiet window."""
    tz_name = config.get("timezone", "Asia/Jerusalem")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("heartbeat: unknown timezone %r — defaulting to UTC", tz_name)
        tz = ZoneInfo("UTC")

    local_now = now.astimezone(tz)
    now_hm = local_now.hour * 60 + local_now.minute

    quiet_start = _parse_hm(config.get("quiet_start", "22:00"))
    quiet_end = _parse_hm(config.get("quiet_end", "07:00"))

    if quiet_start <= quiet_end:
        return quiet_start <= now_hm < quiet_end
    else:
        return now_hm >= quiet_start or now_hm < quiet_end


def _tiers_for_now(config: dict, now: datetime) -> set[str]:
    """Return the severity tiers to check this tick.

    Critical always; Warning at the configured digest_hour; FYI additionally
    on the configured weekly_digest_day at digest_hour.
    """
    tz_name = config.get("timezone", "Asia/Jerusalem")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    tiers = {SEVERITY_CRITICAL}
    if local_now.hour == int(config.get("digest_hour", 9)):
        tiers.add(SEVERITY_WARNING)
        if local_now.isoweekday() == int(config.get("weekly_digest_day", 1)):
            tiers.add(SEVERITY_FYI)
    return tiers


_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
}
_CRON_FAILURE_STREAK_THRESHOLD = 3


def _read_cron_ledger() -> dict:
    """Return {job_id: doc_dict} from the Firestore heartbeat_runs collection."""
    from memory.firestore_db import _make_firestore_client
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    client = _make_firestore_client(project_id, database)
    out: dict = {}
    for snap in client.collection("heartbeat_runs").stream():
        out[snap.id] = snap.to_dict() or {}
    return out


def check_cron_health() -> list[Signal]:
    """Critical-tier: each cron ran recently and is not in a failure streak."""
    signals: list[Signal] = []
    try:
        ledger = _read_cron_ledger()
    except Exception:
        logger.warning("heartbeat: cron ledger read failed", exc_info=True)
        return signals

    now = datetime.now(timezone.utc)
    for job_id, max_hours in _CRON_MAX_STALENESS_HOURS.items():
        doc = ledger.get(job_id)
        if doc is None:
            signals.append(Signal(
                fingerprint=f"cron:{job_id}:missing",
                severity=SEVERITY_CRITICAL, area="cron",
                title=f"{job_id} has never recorded a run",
                detail="No heartbeat_runs ledger entry exists.",
                remediation=f"Confirm the Cloud Scheduler job for {job_id} exists and is enabled.",
            ))
            continue
        last = doc.get("last_run_at")
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_h = (now - last).total_seconds() / 3600
            if age_h > max_hours:
                signals.append(Signal(
                    fingerprint=f"cron:{job_id}:stale",
                    severity=SEVERITY_CRITICAL, area="cron",
                    title=f"{job_id} has not run in {age_h:.0f}h",
                    detail=f"Last run {last.isoformat()}; expected within {max_hours}h.",
                    remediation=f"Check the Cloud Scheduler job for {job_id} and Cloud Run logs.",
                ))

    for job_id, doc in ledger.items():
        if doc.get("consecutive_failures", 0) >= _CRON_FAILURE_STREAK_THRESHOLD:
            signals.append(Signal(
                fingerprint=f"cron:{job_id}:failing",
                severity=SEVERITY_CRITICAL, area="cron",
                title=f"{job_id} failed {doc['consecutive_failures']}x in a row",
                detail=f"last_ok={doc.get('last_ok')}.",
                remediation=f"Inspect Cloud Run logs for the {job_id} endpoint.",
            ))
    return signals


def check_tokens() -> list[Signal]:
    """Token/integration health: Google OAuth and TickTick OAuth refresh probes."""
    signals: list[Signal] = []

    try:
        from core.auth_google import build_auth_manager_from_env
        build_auth_manager_from_env().get_credentials()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:google:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="Google OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Re-run the Google OAuth bootstrap; refresh klaus-google-oauth-token.",
        ))

    try:
        from mcp_tools.ticktick_auth import get_valid_access_token
        get_valid_access_token()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:ticktick:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="TickTick OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Run scripts/ticktick_oauth_bootstrap.py to re-issue the token pair.",
        ))

    return signals
