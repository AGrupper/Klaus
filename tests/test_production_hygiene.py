"""Desired-production and infrastructure hygiene contract tests."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.secret_retention import build_retention_plan
from scripts.audit_production_drift import (
    _fetch_runtime_inventory,
    _normalize_bucket_storage_class,
    audit_snapshot,
    load_manifest,
)
from scripts.audit_quarantine import evaluate_quarantine


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "ops" / "desired-production.json"
ARTIFACT_POLICY_PATH = ROOT / "ops" / "policies" / "artifact-cleanup.json"
FIRESTORE_POLICY_PATH = ROOT / "ops" / "policies" / "firestore-hygiene.json"
ARCHIVE_POLICY_PATH = ROOT / "ops" / "policies" / "chat-archive.json"
QUARANTINE_POLICY_PATH = ROOT / "ops" / "policies" / "quarantine.json"


def _clean_snapshot(manifest: dict) -> dict:
    """Build a synthetic live snapshot that exactly matches the contract."""
    runtime_member = (
        "serviceAccount:" + manifest["service"]["runtime_service_account"]
    )
    secret_iam = {
        name: {
            "bindings": [
                {
                    "role": "roles/secretmanager.secretAccessor",
                    "members": [runtime_member],
                }
            ]
        }
        for name in manifest["secrets"]["runtime_access"]
    }
    secret_iam["klaus-google-oauth-token"]["bindings"].extend(
        {
            "role": role,
            "members": [runtime_member],
        }
        for role in manifest["iam"]["oauth_secret_additional_roles"]
    )
    return {
        "service": {
            "name": manifest["service"]["name"],
            "region": manifest["service"]["region"],
            "runtime_service_account": manifest["service"]["runtime_service_account"],
            "environment": dict(manifest["service"]["required_environment"]),
            "secret_bindings": dict(manifest["service"]["secret_bindings"]),
        },
        "schedulers": [
            {
                "name": job["name"],
                "state": "ENABLED",
                "schedule": job["schedule"],
                "time_zone": job["time_zone"],
                "uri": manifest["service"]["public_url"] + job["path"],
            }
            for job in manifest["schedulers"]["required"]
        ],
        "secrets": [
            {
                "name": name,
                "enabled_versions": 2,
                "api_key_uid": (
                    manifest["embedding"]["api_key_uid"]
                    if name == manifest["embedding"]["secret"]
                    else None
                ),
            }
            for name in manifest["secrets"]["runtime_access"]
        ],
        "project_iam": {
            "bindings": [
                {
                    "role": "roles/datastore.user",
                    "members": [runtime_member],
                },
                {
                    "role": "roles/logging.logWriter",
                    "members": [runtime_member],
                },
            ]
        },
        "secret_iam": secret_iam,
        "firestore": {
            "database": manifest["firestore"]["database"],
            "deletion_protection": "DELETE_PROTECTION_ENABLED",
            "ttl_fields": list(manifest["firestore"]["ttl_fields"]),
        },
        "archive": dict(manifest["archive"]),
        "artifact_cleanup_policy_names": list(
            manifest["artifact_registry"]["cleanup_policy_names"]
        ),
        "observed_routes": list(manifest["routes"]["retained"])
        + list(manifest["routes"]["tombstones"]),
        "tombstones": list(manifest["routes"]["tombstones"]),
        "connectors": list(manifest["connectors"]),
        "embedding": {
            "project": manifest["embedding"]["project"],
            "project_number": "269181672466",
            "billing_enabled": True,
            "model": manifest["embedding"]["model"],
            "daily_request_limit": manifest["embedding"]["daily_request_limit"],
            "api_keys": [
                {
                    "uid": manifest["embedding"]["api_key_uid"],
                    "services": ["generativelanguage.googleapis.com"],
                }
            ],
            "budget": {
                "amount_ils": manifest["embedding"]["monthly_budget_ils"],
                "projects": ["projects/269181672466"],
                "thresholds_percent": manifest["embedding"][
                    "budget_alert_thresholds_percent"
                ],
            },
        },
    }


def test_manifest_pins_claude_first_production_boundary():
    """The manifest names every retained category and every retired boundary."""
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest["schema_version"] == 1
    assert manifest["service"] == {
        **manifest["service"],
        "name": "klaus-agent",
        "project": "klaus-agent",
        "region": "me-west1",
        "runtime_service_account": "klaus-runtime@klaus-agent.iam.gserviceaccount.com",
    }
    assert manifest["schedulers"]["required"][0] == {
        **manifest["schedulers"]["required"][0],
        "name": "klaus-deterministic-alerts",
        "category": "deterministic_alerts",
        "schedule": "*/10 7-21 * * *",
        "time_zone": "Asia/Jerusalem",
        "path": "/cron/deterministic-alerts",
    }
    assert {
        job["category"] for job in manifest["schedulers"]["required"]
    } == {
        "deterministic_alerts",
        "health",
        "claude_review_backstop",
        "things_sync",
        "garmin_sync",
        "hevy_sync",
        "biometric_sync",
    }
    assert "klaus-autonomous-tick" in manifest["schedulers"]["forbidden"]
    assert "klaus-reflect" in manifest["schedulers"]["forbidden"]
    assert "klaus-anthropic-key" in manifest["secrets"]["forbidden"]
    assert "klaus-telegram-token" in manifest["secrets"]["forbidden"]
    assert manifest["embedding"] == {
        "project": "klaus-embeddings-838733",
        "model": "gemini-embedding-2",
        "secret": "klaus-gemini-embedding-key",
        "api_key_uid": "01ec21d8-6962-4c99-9baf-d9da003ad965",
        "daily_request_limit": 200,
        "monthly_budget_ils": 15,
        "budget_alert_thresholds_percent": [50, 90, 100],
    }
    assert manifest["service"]["secret_bindings"]["GEMINI_EMBEDDING_API_KEY"] == (
        "klaus-gemini-embedding-key"
    )
    assert manifest["firestore"]["deletion_protection"] is True
    assert manifest["iam"]["forbidden_project_roles"] == [
        "roles/secretmanager.secretAccessor"
    ]
    assert manifest["iam"]["oauth_secret_additional_roles"] == []
    assert manifest["iam"]["oauth_secret_forbidden_roles"] == [
        "roles/secretmanager.secretVersionAdder",
        "roles/secretmanager.secretVersionManager",
    ]


def test_matching_snapshot_has_no_drift():
    """The audit is silent when every live resource matches desired state."""
    manifest = load_manifest(MANIFEST_PATH)

    assert audit_snapshot(manifest, _clean_snapshot(manifest)) == []


def test_runtime_cannot_write_or_manage_calendar_token_versions():
    """A runtime OAuth version-writer grant is production drift."""
    manifest = load_manifest(MANIFEST_PATH)
    snapshot = _clean_snapshot(manifest)
    runtime_member = (
        "serviceAccount:" + manifest["service"]["runtime_service_account"]
    )
    snapshot["secret_iam"]["klaus-google-oauth-token"]["bindings"].append(
        {
            "role": "roles/secretmanager.secretVersionAdder",
            "members": [runtime_member],
        }
    )

    findings = audit_snapshot(manifest, snapshot)

    assert any("forbidden OAuth secret role" in finding for finding in findings)


def test_live_runtime_inventory_is_fetched_instead_of_copied_from_manifest(monkeypatch):
    """Production route/connector drift must come from the deployed revision."""
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"observed_routes":["GET /health"],"connectors":["calendar"],"tombstones":["POST /telegram-webhook"],"embedding":{"model":"gemini-embedding-2","daily_request_limit":200}}'

    monkeypatch.setattr(
        "scripts.audit_production_drift.urllib.request.urlopen",
        lambda request, timeout: Response(),
    )

    assert _fetch_runtime_inventory("https://klaus.example") == {
        "observed_routes": ["GET /health"],
        "connectors": ["calendar"],
        "tombstones": ["POST /telegram-webhook"],
        "runtime_embedding": {
            "model": "gemini-embedding-2",
            "daily_request_limit": 200,
        },
        "inventory_error": None,
    }


def test_inventory_failure_is_reported_as_drift():
    manifest = load_manifest(MANIFEST_PATH)
    snapshot = _clean_snapshot(manifest)
    snapshot["inventory_error"] = "runtime inventory unavailable: HTTPError"

    assert "runtime inventory unavailable" in "\n".join(
        audit_snapshot(manifest, snapshot)
    )


def test_bucket_storage_class_normalizes_gcloud_snake_case():
    """Live bucket audit reads the field emitted by current gcloud storage."""
    assert _normalize_bucket_storage_class({"default_storage_class": "ARCHIVE"}) == (
        "ARCHIVE"
    )
    assert _normalize_bucket_storage_class({"storageClass": "STANDARD"}) == "STANDARD"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda snapshot, manifest: snapshot["schedulers"].pop(),
            "missing scheduler",
        ),
        (
            lambda snapshot, manifest: snapshot["schedulers"].append(
                {
                    "name": "klaus-autonomous-tick",
                    "state": "ENABLED",
                    "schedule": "*/20 7-21 * * *",
                    "time_zone": "Asia/Jerusalem",
                    "uri": manifest["service"]["public_url"]
                    + "/cron/autonomous-tick",
                }
            ),
            "forbidden scheduler enabled",
        ),
        (
            lambda snapshot, manifest: snapshot["project_iam"]["bindings"].append(
                {
                    "role": "roles/secretmanager.secretAccessor",
                    "members": [
                        "serviceAccount:"
                        + manifest["service"]["runtime_service_account"]
                    ],
                }
            ),
            "project-wide secret access",
        ),
        (
            lambda snapshot, manifest: snapshot["secret_iam"].pop(
                manifest["secrets"]["runtime_access"][0]
            ),
            "missing per-secret access",
        ),
        (
            lambda snapshot, manifest: snapshot["firestore"].update(
                deletion_protection="DELETE_PROTECTION_DISABLED"
            ),
            "Firestore deletion protection",
        ),
        (
            lambda snapshot, manifest: snapshot["secrets"].append(
                {"name": "klaus-groq-key", "enabled_versions": 1}
            ),
            "forbidden secret remains usable",
        ),
        (
            lambda snapshot, manifest: snapshot["service"]["secret_bindings"].update(
                ANTHROPIC_API_KEY="klaus-anthropic-key"
            ),
            "forbidden environment variable present",
        ),
        (
            lambda snapshot, manifest: snapshot["secrets"][0].update(
                enabled_versions=0
            ),
            "retained secret has no enabled version",
        ),
        (
            lambda snapshot, manifest: snapshot["secrets"][
                [item["name"] for item in snapshot["secrets"]].index(
                    manifest["embedding"]["secret"]
                )
            ].update(api_key_uid="wrong-key"),
            "embedding secret API key identity drift",
        ),
        (
            lambda snapshot, manifest: snapshot.update(tombstones=[]),
            "expected 410 tombstone missing",
        ),
        (
            lambda snapshot, manifest: snapshot["embedding"]["budget"].update(
                amount_ils=999
            ),
            "embedding monthly budget drift",
        ),
    ],
)
def test_audit_reports_security_and_cost_drift(mutate, expected):
    """Material security or retired-runtime drift produces a clear finding."""
    manifest = load_manifest(MANIFEST_PATH)
    snapshot = _clean_snapshot(manifest)
    mutate(snapshot, manifest)

    findings = audit_snapshot(manifest, snapshot)

    assert any(expected in finding for finding in findings), findings


def test_oauth_retention_plan_is_two_phase_and_keeps_latest_plus_rollback():
    """Only previously-disabled old versions may be destroyed in this run."""
    versions = [
        {"version": "5", "state": "ENABLED", "created_at": "2026-08-12T00:00:00Z"},
        {"version": "4", "state": "ENABLED", "created_at": "2026-08-11T00:00:00Z"},
        {"version": "3", "state": "ENABLED", "created_at": "2026-08-01T00:00:00Z"},
        {"version": "2", "state": "DISABLED", "created_at": "2026-07-01T00:00:00Z"},
        {"version": "1", "state": "DESTROYED", "created_at": "2026-06-01T00:00:00Z"},
    ]

    plan = build_retention_plan(
        versions,
        now=datetime(2026, 8, 13, tzinfo=timezone.utc),
        keep_count=2,
        destroy_grace_days=7,
    )

    assert plan == {
        "keep": ["5", "4"],
        "disable": ["3"],
        "destroy": ["2"],
    }
    assert "3" not in plan["destroy"]


def test_checked_in_hygiene_policies_are_fail_safe():
    """Policies protect live data and require observation before deletion."""
    artifact = json.loads(ARTIFACT_POLICY_PATH.read_text())
    firestore = json.loads(FIRESTORE_POLICY_PATH.read_text())
    archive = json.loads(ARCHIVE_POLICY_PATH.read_text())
    quarantine = json.loads(QUARANTINE_POLICY_PATH.read_text())

    by_name = {policy["name"]: policy for policy in artifact}
    assert by_name["keep-production"]["condition"]["tagPrefixes"] == [
        "production",
        "deployed-",
    ]
    assert by_name["keep-ten-most-recent"]["mostRecentVersions"]["keepCount"] == 10
    assert by_name["delete-images-older-than-30-days"]["condition"]["olderThan"] == "2592000s"
    assert firestore["deletion_protection"] is True
    assert {item["collection_group"] for item in firestore["ttl_fields"]} >= {
        "oauth_authorization_codes",
        "oauth_access_tokens",
        "oauth_refresh_tokens",
        "action_idempotency",
        "pending_approvals",
    }
    assert archive["storage_class"] == "ARCHIVE"
    assert archive["runtime_access"] == "none"
    assert quarantine["minimum_observation_days"] == 7
    assert quarantine["required_access_count"] == 0


def test_quarantine_gate_requires_seven_days_and_zero_access():
    """Retired infrastructure cannot be deleted before a clean observation gate."""
    policy = json.loads(QUARANTINE_POLICY_PATH.read_text())
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clean = {
        "observation_started_at": "2026-08-13T11:59:59Z",
        "access_count": 0,
        "generative_usage_count": 0,
        "resources_still_disabled": True,
        "claude_routines_successful": ["morning", "nightly", "weekly"],
    }

    assert evaluate_quarantine(policy, clean, now=now) == []

    too_early = {**clean, "observation_started_at": "2026-08-14T12:00:00Z"}
    accessed = {**clean, "access_count": 1}
    enabled = {**clean, "resources_still_disabled": False}

    assert any("observation window" in item for item in evaluate_quarantine(policy, too_early, now=now))
    assert any("access count" in item for item in evaluate_quarantine(policy, accessed, now=now))
    assert any("disabled" in item for item in evaluate_quarantine(policy, enabled, now=now))


def test_deploy_still_uses_workload_identity_federation():
    """Infrastructure hygiene must not regress keyless GitHub deployment."""
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()

    assert "id-token: write" in workflow
    assert "google-github-actions/auth@v2" in workflow
    assert "workload_identity_provider:" in workflow
    assert "GOOGLE_APPLICATION_CREDENTIALS=" not in workflow
    assert (
        "GEMINI_EMBEDDING_API_KEY=klaus-gemini-embedding-key:latest" in workflow
    )
    assert "GEMINI_EMBEDDING_API_KEY=klaus-gemini-key:latest" not in workflow
    assert "--set-env-vars" in workflow
    assert "--set-secrets" in workflow
    assert "--clear-env-vars" not in workflow
    assert "--clear-secrets" not in workflow
    assert "--update-secrets" not in workflow
    assert "CLAUDE_PROJECT_URL=${{ vars.CLAUDE_PROJECT_URL }}" in workflow
    for binding in (
        "NOTION_API_TOKEN=klaus-notion-api-token:latest",
        "GARMIN_EMAIL=klaus-garmin-email:latest",
        "GARMIN_PASSWORD=klaus-garmin-password:latest",
        "PG_CONNECTION_STRING=klaus-postgres-connection-string:latest",
    ):
        assert binding in workflow


def test_operator_scripts_are_directly_executable_from_repository_root():
    """Runbook commands must not depend on an implicit PYTHONPATH."""
    for script in (
        "manage_secret_versions.py",
        "audit_production_drift.py",
        "audit_quarantine.py",
    ):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
