"""Lightweight infrastructure health checks for the Claude-first runtime.

The heartbeat is intentionally observational: it reads retained scheduler
ledgers, MCP/Routine configuration, Web Push health, and deployment identity.
It never constructs a model client, sends Telegram, or performs autonomous
outreach.  ``core.deterministic_alerts`` is the sole scheduler-owned notifier.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_FYI = "fyi"


@dataclass(frozen=True)
class Signal:
    """A concrete infrastructure condition suitable for deterministic alerts."""

    fingerprint: str
    severity: str
    area: str
    title: str
    detail: str
    remediation: str


# Only retained, scheduler-driven surfaces are monitored.  Triggered routines
# are represented by their routine-run state rather than old occasion crons.
_CRON_MAX_STALENESS_HOURS = {
    "deterministic-alerts": 1,
    "heartbeat": 2,
    "nightly-backstop": 26,
    "morning-backstop": 26,
    "weekly-training-review": 170,
    "things-sync": 26,
    "healthkit-sync": 48,
    "strength-sync": 26,
    "run-sync": 26,
    "biometric-sync": 26,
}
_CRON_FAILURE_STREAK_THRESHOLD = 3
_PUSH_FAILURE_STREAK_THRESHOLD = 3
_PUSH_STALE_HOURS = 48


def _read_cron_ledger() -> dict[str, dict[str, Any]]:
    """Return the retained scheduler ledger without mutating it."""
    from memory.firestore_db import _make_firestore_client

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    client = _make_firestore_client(project_id, database)
    return {
        snapshot.id: snapshot.to_dict() or {}
        for snapshot in client.collection("heartbeat_runs").stream()
    }


def _as_utc(value: Any) -> datetime | None:
    """Normalize a stored timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def check_cron_health(now: datetime | None = None) -> list[Signal]:
    """Report missing, stale, or repeatedly failing retained schedulers."""
    try:
        ledger = _read_cron_ledger()
    except Exception:
        logger.warning("heartbeat: scheduler ledger read failed", exc_info=True)
        return [Signal(
            "cron:ledger:unavailable", SEVERITY_CRITICAL, "scheduler",
            "Scheduler health ledger is unavailable",
            "Klaus could not read heartbeat_runs.",
            "Check Firestore availability and service credentials.",
        )]

    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    signals: list[Signal] = []
    for job_id, max_hours in _CRON_MAX_STALENESS_HOURS.items():
        record = ledger.get(job_id)
        if record is None:
            signals.append(Signal(
                f"cron:{job_id}:missing", SEVERITY_CRITICAL, "scheduler",
                f"{job_id} has never recorded a run",
                "No heartbeat_runs ledger entry exists.",
                f"Confirm the Cloud Scheduler job for {job_id} is enabled.",
            ))
            continue
        last_run = _as_utc(record.get("last_run_at"))
        if last_run is None:
            signals.append(Signal(
                f"cron:{job_id}:invalid-timestamp", SEVERITY_CRITICAL, "scheduler",
                f"{job_id} has no valid last-run timestamp",
                f"Stored value: {record.get('last_run_at')!r}.",
                "Inspect the scheduler ledger writer.",
            ))
            continue
        age = observed_at - last_run
        if age > timedelta(hours=max_hours):
            signals.append(Signal(
                f"cron:{job_id}:stale", SEVERITY_CRITICAL, "scheduler",
                f"{job_id} has not run in {age.total_seconds() / 3600:.0f}h",
                f"Last run {last_run.isoformat()}; expected within {max_hours}h.",
                f"Check the Cloud Scheduler job and Cloud Run logs for {job_id}.",
            ))
        if int(record.get("consecutive_failures") or 0) >= _CRON_FAILURE_STREAK_THRESHOLD:
            signals.append(Signal(
                f"cron:{job_id}:failing", SEVERITY_CRITICAL, "scheduler",
                f"{job_id} failed {record['consecutive_failures']} times in a row",
                f"last_ok={record.get('last_ok')!r}.",
                f"Inspect Cloud Run logs for {job_id}.",
            ))
    return signals


def check_mcp_routine_health() -> list[Signal]:
    """Report missing Claude connector and Routine capability prerequisites."""
    enabled = lambda name: os.environ.get(name, "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    signals: list[Signal] = []
    if not enabled("KLAUS_MCP_ENABLED"):
        signals.append(Signal(
            "mcp:interactive:disabled", SEVERITY_CRITICAL, "mcp",
            "Claude MCP connector is disabled",
            "KLAUS_MCP_ENABLED is not enabled.",
            "Enable the scoped Claude MCP connector.",
        ))
    if not enabled("KLAUS_CLAUDE_ROUTINES_ENABLED"):
        signals.append(Signal(
            "routine:disabled", SEVERITY_CRITICAL, "routine",
            "Claude Routines are disabled",
            "KLAUS_CLAUDE_ROUTINES_ENABLED is not enabled.",
            "Enable the configured Claude Remote Routine connector.",
        ))
    for routine in ("MORNING", "NIGHTLY", "WEEKLY"):
        if not os.environ.get(f"CLAUDE_ROUTINE_TRIGGER_URL_{routine}"):
            signals.append(Signal(
                f"routine:{routine.lower()}:trigger-missing", SEVERITY_CRITICAL, "routine",
                f"{routine.title()} Claude Routine trigger is missing",
                f"CLAUDE_ROUTINE_TRIGGER_URL_{routine} is unset.",
                "Configure the supported Claude Routine trigger URL.",
            ))
    return signals


def _check_push_health() -> list[Signal]:
    """Report Web Push failures without sending a notification itself."""
    from memory.firestore_db import HubSettingsStore, PushSubscriptionStore

    project = os.environ.get("GCP_PROJECT_ID", "")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    try:
        subscriptions = PushSubscriptionStore(project, database).list_all()
        settings = HubSettingsStore(project, database).get()
    except Exception:
        logger.warning("heartbeat: Web Push health read failed", exc_info=True)
        return [Signal(
            "push:health:unavailable", SEVERITY_WARNING, "push",
            "Web Push health could not be checked",
            "The push subscription store was unavailable.",
            "Check Firestore and Web Push configuration.",
        )]

    enabled_at = _as_utc(settings.get("push_enabled_at"))
    if enabled_at is None:
        return []
    signals: list[Signal] = []
    if not subscriptions:
        signals.append(Signal(
            "push:subscriptions:missing", SEVERITY_CRITICAL, "push",
            "Web Push is enabled but has no subscriptions",
            "No browser has an active Web Push subscription.",
            "Open the Hub and enable notifications again.",
        ))
        return signals
    latest_success: datetime | None = None
    for subscription in subscriptions:
        failures = int(subscription.get("failure_count") or 0)
        if failures >= _PUSH_FAILURE_STREAK_THRESHOLD:
            signals.append(Signal(
                f"push:delivery:failing:{failures}", SEVERITY_CRITICAL, "push",
                "A Web Push subscription is repeatedly failing",
                f"failure_count={failures}.",
                "Re-register the affected browser subscription.",
            ))
        success_at = _as_utc(subscription.get("last_success_at"))
        if success_at and (latest_success is None or success_at > latest_success):
            latest_success = success_at
    if latest_success and datetime.now(timezone.utc) - latest_success > timedelta(hours=_PUSH_STALE_HOURS):
        signals.append(Signal(
            "push:delivery:stale", SEVERITY_WARNING, "push",
            "Web Push has no recent successful delivery",
            f"Last success was {latest_success.isoformat()}.",
            "Confirm notifications are permitted in the Hub browser.",
        ))
    return signals


def deployment_identity() -> dict[str, str | None]:
    """Return the deployment identity exposed by Cloud Run without API polling."""
    return {
        "service": os.environ.get("K_SERVICE"),
        "revision": os.environ.get("K_REVISION"),
        "configuration": os.environ.get("K_CONFIGURATION"),
        "version": os.environ.get("KLAUS_DEPLOY_VERSION"),
    }


def check_deployment_identity() -> list[Signal]:
    """Surface a missing Cloud Run revision identity as an operator warning."""
    identity = deployment_identity()
    if identity["revision"]:
        return []
    return [Signal(
        "deployment:revision:missing", SEVERITY_WARNING, "deployment",
        "Cloud Run revision identity is not available",
        "K_REVISION is unset in this runtime.",
        "Verify the service is running under Cloud Run with standard metadata.",
    )]


def collect_deterministic_signals(now: datetime | None = None) -> list[Signal]:
    """Collect retained infrastructure health without delivery or model usage."""
    signals: list[Signal] = []
    for checker in (lambda: check_cron_health(now), check_mcp_routine_health, _check_push_health, check_deployment_identity):
        try:
            signals.extend(checker())
        except Exception:
            logger.warning("heartbeat: checker failed", exc_info=True)
    return signals
