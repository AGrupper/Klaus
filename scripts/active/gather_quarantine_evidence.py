#!/usr/bin/env python3
"""Gather seven-day quarantine deletion evidence from live, read-only sources.

`audit_quarantine.py` validates an evidence file but cannot check whether its
numbers are true. Hand-writing "access_count: 0" attests from memory that
nothing touched the retired resources for a week — which is exactly the claim
that should not be taken on trust before permanently deleting infrastructure.

This command measures it instead: Cloud Logging for access and generative
provider usage, live GCP state for whether each quarantined resource is still
inert, and Firestore for whether Claude actually completed the three routines.

Every call is read-only (`gcloud ... describe|list`, `logging read`, Firestore
reads). Nothing is deleted, paused, or modified.

The single most important property: **a measurement that did not happen never
reads as a clean one.** A failed query records -1, which closes the gate, and
names itself in `measurement_errors`. Silence is never mistaken for zero.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
# The runbook invokes this by path from the repository root, so the project
# packages are not importable unless we put the root on sys.path ourselves.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_POLICY = ROOT / "ops" / "policies" / "quarantine.json"

# Cloud Scheduler and Secret Manager states that mean "cannot run / cannot be
# read". ABSENT is our own marker for a resource that no longer exists, which
# satisfies the gate because there is nothing left to delete.
_INERT_SCHEDULER_STATES = {"PAUSED", "DISABLED", "ABSENT"}
_INERT_SECRET_STATES = {"DISABLED", "DESTROYED", "ABSENT"}

# Only these mean Claude itself produced the review. `published_fallback` means
# the deterministic backstop published because Claude did not, so it is not
# evidence that the Claude routine works.
_CLAUDE_SUCCESS_STATUSES = {"published_claude", "late_upgraded"}


def resources_are_disabled(
    policy: dict[str, Any],
    observed: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return (all_inert, offenders) for every quarantined resource.

    A resource missing from ``observed`` is treated as an offender, not as
    safe. Not having looked is not the same as having looked and found nothing.
    """
    offenders: list[str] = []
    resources = policy["resources"]

    scheduler_states = observed.get("scheduler_jobs", {})
    for name in resources.get("scheduler_jobs", []):
        state = str(scheduler_states.get(name, "")).upper()
        if not state:
            offenders.append(f"scheduler {name} state was not observed")
        elif state not in _INERT_SCHEDULER_STATES:
            offenders.append(f"scheduler {name} is {state}")

    secret_states = observed.get("secrets", {})
    for name in resources.get("secrets", []):
        state = str(secret_states.get(name, "")).upper()
        if not state:
            offenders.append(f"secret {name} state was not observed")
        elif state not in _INERT_SECRET_STATES:
            offenders.append(f"secret {name} is {state}")

    account_states = observed.get("service_accounts", {})
    for name in resources.get("service_accounts", []):
        if name not in account_states:
            offenders.append(f"service account {name} state was not observed")
        elif account_states[name] is not True:
            offenders.append(f"service account {name} is still enabled")

    return (not offenders), offenders


def claude_completed_routines(
    runs: Iterable[dict[str, Any]],
    *,
    since: str,
) -> list[str]:
    """Return the routines Claude itself published on or after ``since``."""
    completed = {
        str(run.get("routine"))
        for run in runs
        if str(run.get("status")) in _CLAUDE_SUCCESS_STATUSES
        and str(run.get("target_date") or "") >= since
    }
    return sorted(completed & {"morning", "nightly", "weekly"})


def build_evidence(
    *,
    observation_started_at: str,
    access_count: int | None,
    generative_usage_count: int | None,
    resources_disabled: bool,
    offenders: list[str],
    routines: list[str],
    measurement_errors: list[str],
) -> dict[str, Any]:
    """Assemble the evidence file `audit_quarantine.py` consumes.

    ``None`` for either count means the measurement failed. It is written as
    -1 so the audit's ``!= 0`` check closes the gate, rather than being omitted
    (which would also fail, but silently and for the wrong reason).
    """
    return {
        "observation_started_at": observation_started_at,
        "access_count": -1 if access_count is None else int(access_count),
        "generative_usage_count": (
            -1 if generative_usage_count is None else int(generative_usage_count)
        ),
        "resources_still_disabled": bool(resources_disabled),
        "claude_routines_successful": list(routines),
        "offenders": list(offenders),
        "measurement_errors": list(measurement_errors),
    }


def _gcloud_json(args: list[str]) -> Any:
    """Run a read-only gcloud command and parse its JSON, or raise."""
    result = subprocess.run(
        ["gcloud", *args, "--format=json"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(result.stdout or "[]")


def observe_scheduler_jobs(policy: dict, project: str, location: str) -> dict[str, str]:
    """Return {job_name: STATE} for quarantined jobs; ABSENT when gone."""
    live = {}
    for job in _gcloud_json(
        ["scheduler", "jobs", "list", f"--project={project}", f"--location={location}"]
    ):
        live[str(job.get("name", "")).rsplit("/", 1)[-1]] = str(job.get("state", ""))
    return {
        name: live.get(name, "ABSENT")
        for name in policy["resources"].get("scheduler_jobs", [])
    }


def observe_secrets(policy: dict, project: str) -> dict[str, str]:
    """Return {secret_name: STATE} for quarantined secrets; ABSENT when gone.

    A secret is inert when it exists but has no enabled version, so the state
    reported is derived from its versions rather than the secret itself.
    """
    existing = {
        str(secret.get("name", "")).rsplit("/", 1)[-1]
        for secret in _gcloud_json(["secrets", "list", f"--project={project}"])
    }
    states: dict[str, str] = {}
    for name in policy["resources"].get("secrets", []):
        if name not in existing:
            states[name] = "ABSENT"
            continue
        versions = _gcloud_json(
            ["secrets", "versions", "list", name, f"--project={project}"]
        )
        enabled = [v for v in versions if str(v.get("state", "")).upper() == "ENABLED"]
        states[name] = "ENABLED" if enabled else "DISABLED"
    return states


def observe_service_accounts(policy: dict, project: str) -> dict[str, bool]:
    """Return {email: is_inert} for quarantined service accounts."""
    live = {
        str(account.get("email")): bool(account.get("disabled", False))
        for account in _gcloud_json(["iam", "service-accounts", "list", f"--project={project}"])
    }
    return {
        email: live.get(email, True)  # absent means deleted, which is inert
        for email in policy["resources"].get("service_accounts", [])
    }


def count_log_entries(query: str, project: str, since: str) -> int:
    """Return the number of matching log entries since ``since``; may raise."""
    entries = _gcloud_json(
        [
            "logging",
            "read",
            f'{query} AND timestamp>="{since}"',
            f"--project={project}",
            "--limit=1000",
        ]
    )
    return len(entries)


def secret_access_query(policy: dict) -> str:
    """Log filter for a workload actually reading a quarantined secret.

    Deliberately scoped to ``AccessSecretVersion``. The first real run counted
    fourteen "accesses" that were all the operator's own DisableSecretVersion
    and DestroySecretVersion calls — the act of retiring the secrets. Counting
    the quarantine as a breach of the quarantine would keep the gate shut
    forever, so administrative methods are excluded by construction.
    """
    names = policy["resources"].get("secrets", [])
    clauses = " OR ".join(f'protoPayload.resourceName:"{name}"' for name in names)
    return (
        'protoPayload.methodName='
        '"google.cloud.secretmanager.v1.SecretManagerService.AccessSecretVersion"'
        f" AND ({clauses})"
    )


def scheduler_run_query(policy: dict) -> str:
    """Log filter for a quarantined scheduler job actually firing."""
    names = policy["resources"].get("scheduler_jobs", [])
    clauses = " OR ".join(f'resource.labels.job_id="{name}"' for name in names)
    return f'resource.type="cloud_scheduler_job" AND ({clauses})'


def service_account_use_query(policy: dict) -> str:
    """Log filter for a quarantined service account authenticating."""
    names = policy["resources"].get("service_accounts", [])
    clauses = " OR ".join(
        f'protoPayload.authenticationInfo.principalEmail="{name}"' for name in names
    )
    return f"({clauses})"


_GENERATIVE_USAGE_QUERY = (
    'protoPayload.serviceName:("generativelanguage.googleapis.com" OR '
    '"aiplatform.googleapis.com")'
)


def main() -> int:
    """Measure the gate inputs and write an evidence file. Read-only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--project", default="klaus-agent")
    parser.add_argument("--location", default="me-west1")
    parser.add_argument(
        "--observation-start",
        required=True,
        help="RFC3339 timestamp the quarantine began, e.g. 2026-08-13T00:00:00Z",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    errors: list[str] = []

    observed: dict[str, Any] = {}
    try:
        observed["scheduler_jobs"] = observe_scheduler_jobs(
            policy, args.project, args.location
        )
    except Exception as exc:
        errors.append(f"scheduler state unavailable: {exc}")
    try:
        observed["secrets"] = observe_secrets(policy, args.project)
    except Exception as exc:
        errors.append(f"secret state unavailable: {exc}")
    try:
        observed["service_accounts"] = observe_service_accounts(policy, args.project)
    except Exception as exc:
        errors.append(f"service account state unavailable: {exc}")

    disabled, offenders = resources_are_disabled(policy, observed)

    # Access is the sum of three distinct kinds of use: a workload reading a
    # retired secret, a paused job firing anyway, or a retired service account
    # authenticating. Any single query failing makes the total unknown rather
    # than partial — a partial total that reads as 0 is the failure mode this
    # whole command exists to remove.
    access_count: int | None = 0
    for label, query in (
        ("secret access", secret_access_query(policy)),
        ("scheduler execution", scheduler_run_query(policy)),
        ("service account use", service_account_use_query(policy)),
    ):
        try:
            found = count_log_entries(query, args.project, args.observation_start)
        except Exception as exc:
            access_count = None
            errors.append(f"{label} query failed: {exc}")
            continue
        if access_count is not None:
            access_count += found

    try:
        generative_usage_count = count_log_entries(
            _GENERATIVE_USAGE_QUERY, args.project, args.observation_start
        )
    except Exception as exc:
        generative_usage_count = None
        errors.append(f"generative usage query failed: {exc}")

    routines: list[str] = []
    try:
        from memory.firestore_db import RoutineRunStore

        runs = RoutineRunStore(args.project, "klaus-firestore").list_recent(60)
        routines = claude_completed_routines(runs, since=args.observation_start[:10])
    except Exception as exc:
        errors.append(f"routine run history unavailable: {exc}")

    evidence = build_evidence(
        observation_started_at=args.observation_start,
        access_count=access_count,
        generative_usage_count=generative_usage_count,
        resources_disabled=disabled,
        offenders=offenders,
        routines=routines,
        measurement_errors=errors,
    )
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")

    print(f"Wrote {args.out}")
    if errors:
        print("Measurements that did not complete (the gate stays closed):")
        print("\n".join(f"- {error}" for error in errors))
    if offenders:
        print("Quarantined resources that are not inert:")
        print("\n".join(f"- {offender}" for offender in offenders))
    print(f"Now run: python scripts/active/audit_quarantine.py --evidence {args.out}")
    return 1 if (errors or offenders) else 0


if __name__ == "__main__":
    raise SystemExit(main())
