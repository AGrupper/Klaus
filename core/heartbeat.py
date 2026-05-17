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
