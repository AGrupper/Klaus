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
