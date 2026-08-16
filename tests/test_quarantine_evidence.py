"""Tests for machine-gathered quarantine deletion evidence.

The seven-day gate decides whether retired infrastructure is permanently
deleted. Until now the evidence was hand-typed and the audit simply believed
it, so "access_count: 0" was an assertion rather than a measurement. These
tests pin the properties that make the gathered version trustworthy — above
all, that a measurement which did not happen can never read as a clean one.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.active.audit_quarantine import evaluate_quarantine
from scripts.active.gather_quarantine_evidence import (
    build_evidence,
    claude_completed_routines,
    resources_are_disabled,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "ops" / "policies" / "quarantine.json").read_text())
STARTED = "2026-08-13T00:00:00Z"
NOW = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)


def _all_quarantined_disabled() -> dict:
    """Observed state in which every quarantined resource is safely inert."""
    return {
        "scheduler_jobs": {name: "PAUSED" for name in POLICY["resources"]["scheduler_jobs"]},
        "secrets": {name: "DISABLED" for name in POLICY["resources"]["secrets"]},
        "service_accounts": {name: True for name in POLICY["resources"]["service_accounts"]},
    }


def test_all_quarantined_resources_disabled_reports_clean():
    disabled, offenders = resources_are_disabled(POLICY, _all_quarantined_disabled())

    assert disabled is True
    assert offenders == []


def test_an_enabled_scheduler_job_is_named_as_an_offender():
    observed = _all_quarantined_disabled()
    observed["scheduler_jobs"]["klaus-autonomous-tick"] = "ENABLED"

    disabled, offenders = resources_are_disabled(POLICY, observed)

    assert disabled is False
    assert "klaus-autonomous-tick" in " ".join(offenders)


def test_an_enabled_secret_is_named_as_an_offender():
    observed = _all_quarantined_disabled()
    observed["secrets"]["klaus-anthropic-key"] = "ENABLED"

    disabled, offenders = resources_are_disabled(POLICY, observed)

    assert disabled is False
    assert "klaus-anthropic-key" in " ".join(offenders)


def test_a_resource_that_could_not_be_observed_is_not_assumed_disabled():
    """Absent state means unknown. Unknown must never read as safe."""
    observed = _all_quarantined_disabled()
    del observed["secrets"]["klaus-telegram-token"]

    disabled, offenders = resources_are_disabled(POLICY, observed)

    assert disabled is False
    assert "klaus-telegram-token" in " ".join(offenders)


def test_a_deleted_resource_counts_as_disabled():
    """Already-removed resources satisfy the gate — there is nothing to delete."""
    observed = _all_quarantined_disabled()
    observed["secrets"]["klaus-groq-key"] = "ABSENT"

    disabled, offenders = resources_are_disabled(POLICY, observed)

    assert disabled is True
    assert offenders == []


def test_only_claude_published_runs_count_as_a_completed_routine():
    """A fallback publication means the deterministic backstop ran, not Claude."""
    runs = [
        {"routine": "morning", "status": "published_claude", "target_date": "2026-08-14"},
        {"routine": "nightly", "status": "published_fallback", "target_date": "2026-08-14"},
        {"routine": "weekly", "status": "late_upgraded", "target_date": "2026-08-16"},
    ]

    completed = claude_completed_routines(runs, since="2026-08-13")

    assert completed == ["morning", "weekly"]


def test_runs_before_the_observation_window_do_not_count():
    runs = [
        {"routine": "morning", "status": "published_claude", "target_date": "2026-08-01"},
    ]

    assert claude_completed_routines(runs, since="2026-08-13") == []


def test_gathered_clean_evidence_satisfies_the_gate():
    evidence = build_evidence(
        observation_started_at=STARTED,
        access_count=0,
        generative_usage_count=0,
        resources_disabled=True,
        offenders=[],
        routines=["morning", "nightly", "weekly"],
        measurement_errors=[],
    )

    assert evaluate_quarantine(POLICY, evidence, now=NOW) == []


def test_an_unmeasured_access_count_closes_the_gate():
    """The whole point: a query that did not run must not read as zero."""
    evidence = build_evidence(
        observation_started_at=STARTED,
        access_count=None,
        generative_usage_count=0,
        resources_disabled=True,
        offenders=[],
        routines=["morning", "nightly", "weekly"],
        measurement_errors=["access log query failed"],
    )

    findings = evaluate_quarantine(POLICY, evidence, now=NOW)

    assert findings != []
    assert evidence["access_count"] == -1
    assert evidence["measurement_errors"] == ["access log query failed"]


def test_an_unmeasured_generative_usage_count_closes_the_gate():
    evidence = build_evidence(
        observation_started_at=STARTED,
        access_count=0,
        generative_usage_count=None,
        resources_disabled=True,
        offenders=[],
        routines=["morning", "nightly", "weekly"],
        measurement_errors=["provider usage query failed"],
    )

    assert evaluate_quarantine(POLICY, evidence, now=NOW) != []
    assert evidence["generative_usage_count"] == -1


def test_offenders_are_recorded_in_the_evidence_for_the_operator():
    evidence = build_evidence(
        observation_started_at=STARTED,
        access_count=0,
        generative_usage_count=0,
        resources_disabled=False,
        offenders=["scheduler klaus-reflect is ENABLED"],
        routines=["morning", "nightly", "weekly"],
        measurement_errors=[],
    )

    assert evidence["resources_still_disabled"] is False
    assert evidence["offenders"] == ["scheduler klaus-reflect is ENABLED"]
    assert evaluate_quarantine(POLICY, evidence, now=NOW) != []


def test_access_query_counts_use_not_the_act_of_retiring():
    """Disabling a secret is quarantining it, not accessing it.

    The first real run counted 14 "accesses" that were all Amit's own
    DisableSecretVersion and DestroySecretVersion calls on 2026-08-13 — the
    retirement itself. Counting those would keep the gate shut forever.
    """
    from scripts.active.gather_quarantine_evidence import secret_access_query

    query = secret_access_query(POLICY)

    assert "AccessSecretVersion" in query
    assert "DisableSecretVersion" not in query
    assert "DestroySecretVersion" not in query
    assert "klaus-anthropic-key" in query


def test_scheduler_query_targets_job_execution():
    """A paused job that never fires must produce no execution entries."""
    from scripts.active.gather_quarantine_evidence import scheduler_run_query

    query = scheduler_run_query(POLICY)

    assert "cloud_scheduler_job" in query
    assert "klaus-autonomous-tick" in query


def test_service_account_query_targets_authenticated_use():
    from scripts.active.gather_quarantine_evidence import service_account_use_query

    query = service_account_use_query(POLICY)

    assert "principalEmail" in query
    assert "klaus-log-uploader@klaus-agent.iam.gserviceaccount.com" in query


def test_gatherer_runs_from_the_repository_root():
    """The operator runs this by path; it must not need a PYTHONPATH."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "active" / "gather_quarantine_evidence.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
