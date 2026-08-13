#!/usr/bin/env python3
"""Read-only audit of Klaus production against the checked-in desired state.

By default this command reads live GCP metadata with ``gcloud`` and never calls
a mutation command. ``--snapshot`` accepts an exported JSON snapshot for CI or
offline review. A non-zero exit indicates drift.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "ops" / "desired-production.json"


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and minimally validate the desired-production contract."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "service",
        "schedulers",
        "secrets",
        "iam",
        "firestore",
        "artifact_registry",
        "archive",
        "connectors",
        "embedding",
        "routes",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"manifest is missing required sections: {missing}")
    return manifest


def _binding_members(policy: dict[str, Any], role: str) -> set[str]:
    """Return all IAM members for one role from a policy JSON object."""
    return {
        str(member)
        for binding in policy.get("bindings", [])
        if binding.get("role") == role
        for member in binding.get("members", [])
    }


def audit_snapshot(manifest: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Return human-readable drift findings for one normalized snapshot."""
    findings: list[str] = []
    desired_service = manifest["service"]
    live_service = snapshot.get("service", {})
    for field in ("name", "region", "runtime_service_account"):
        if live_service.get(field) != desired_service.get(field):
            findings.append(
                f"service {field} drift: expected {desired_service.get(field)!r}, "
                f"got {live_service.get(field)!r}"
            )

    environment = live_service.get("environment", {})
    for key, expected in desired_service["required_environment"].items():
        actual = environment.get(key)
        if expected == "<required>":
            if not actual:
                findings.append(f"required environment variable missing: {key}")
        elif str(actual).lower() != str(expected).lower():
            findings.append(
                f"environment drift for {key}: expected {expected!r}, got {actual!r}"
            )
    bindings = live_service.get("secret_bindings", {})
    for key in desired_service["forbidden_environment"]:
        if key in environment or key in bindings:
            findings.append(f"forbidden environment variable present: {key}")

    for variable, secret_name in desired_service["secret_bindings"].items():
        if bindings.get(variable) != secret_name:
            findings.append(
                f"secret binding drift for {variable}: expected {secret_name!r}, "
                f"got {bindings.get(variable)!r}"
            )
    for variable in sorted(set(bindings) - set(desired_service["secret_bindings"])):
        findings.append(f"unexpected secret binding present: {variable}")

    live_jobs = {job.get("name"): job for job in snapshot.get("schedulers", [])}
    for expected in manifest["schedulers"]["required"]:
        name = expected["name"]
        actual = live_jobs.get(name)
        if not actual:
            findings.append(f"missing scheduler: {name}")
            continue
        if str(actual.get("state", "")).upper() != "ENABLED":
            findings.append(f"required scheduler is not enabled: {name}")
        expected_values = {
            "schedule": expected["schedule"],
            "time_zone": expected["time_zone"],
            "uri": desired_service["public_url"] + expected["path"],
        }
        for field, wanted in expected_values.items():
            if actual.get(field) != wanted:
                findings.append(
                    f"scheduler {name} {field} drift: expected {wanted!r}, "
                    f"got {actual.get(field)!r}"
                )
    for name in manifest["schedulers"]["forbidden"]:
        job = live_jobs.get(name)
        if job and str(job.get("state", "")).upper() not in {"PAUSED", "DISABLED"}:
            findings.append(f"forbidden scheduler enabled: {name}")

    live_secrets = {item.get("name"): item for item in snapshot.get("secrets", [])}
    for name in manifest["secrets"]["runtime_access"]:
        secret = live_secrets.get(name)
        if not secret:
            findings.append(f"missing retained secret: {name}")
        elif int(secret.get("enabled_versions") or 0) < 1:
            findings.append(f"retained secret has no enabled version: {name}")
    for name in manifest["secrets"]["forbidden"]:
        secret = live_secrets.get(name)
        if secret and int(secret.get("enabled_versions") or 0) > 0:
            findings.append(f"forbidden secret remains usable: {name}")

    runtime_member = (
        "serviceAccount:" + desired_service["runtime_service_account"]
    )
    project_iam = snapshot.get("project_iam", {})
    if runtime_member in _binding_members(
        project_iam, "roles/secretmanager.secretAccessor"
    ):
        findings.append("project-wide secret access remains on runtime service account")
    for role in manifest["iam"]["required_project_roles"]:
        if runtime_member not in _binding_members(project_iam, role):
            findings.append(f"runtime service account is missing project role: {role}")
    per_secret = snapshot.get("secret_iam", {})
    for name in manifest["secrets"]["runtime_access"]:
        if runtime_member not in _binding_members(
            per_secret.get(name, {}), "roles/secretmanager.secretAccessor"
        ):
            findings.append(f"missing per-secret access for runtime: {name}")
    oauth_policy = per_secret.get("klaus-google-oauth-token", {})
    for role in manifest["iam"]["oauth_secret_additional_roles"]:
        if runtime_member not in _binding_members(oauth_policy, role):
            findings.append(f"OAuth secret is missing runtime role: {role}")

    firestore = snapshot.get("firestore", {})
    if firestore.get("database") != manifest["firestore"]["database"]:
        findings.append("Firestore database name drift")
    if firestore.get("deletion_protection") != "DELETE_PROTECTION_ENABLED":
        findings.append("Firestore deletion protection is not enabled")
    wanted_ttl = {
        (item["collection_group"], item["field"])
        for item in manifest["firestore"]["ttl_fields"]
    }
    actual_ttl = {
        (item.get("collection_group"), item.get("field"))
        for item in firestore.get("ttl_fields", [])
    }
    for collection_group, field in sorted(wanted_ttl - actual_ttl):
        findings.append(f"missing Firestore TTL: {collection_group}.{field}")

    archive = snapshot.get("archive", {})
    for field in ("bucket", "storage_class", "runtime_access"):
        if archive.get(field) != manifest["archive"][field]:
            findings.append(f"chat archive {field} drift")
    wanted_policies = set(manifest["artifact_registry"]["cleanup_policy_names"])
    actual_policies = set(snapshot.get("artifact_cleanup_policy_names", []))
    if wanted_policies - actual_policies:
        findings.append(
            "missing Artifact Registry cleanup policies: "
            + ", ".join(sorted(wanted_policies - actual_policies))
        )
    if snapshot.get("inventory_error"):
        findings.append(str(snapshot["inventory_error"]))
    for route in manifest["routes"]["retained"] + manifest["routes"]["tombstones"]:
        if route not in snapshot.get("observed_routes", []):
            findings.append(f"expected route missing from runtime: {route}")
    for connector in manifest["connectors"]:
        if connector not in snapshot.get("connectors", []):
            findings.append(f"retained connector missing: {connector}")

    desired_embedding = manifest["embedding"]
    live_embedding = snapshot.get("embedding", {})
    if live_embedding.get("project") != desired_embedding["project"]:
        findings.append("embedding project drift")
    if live_embedding.get("billing_enabled") is not True:
        findings.append("embedding project billing is not enabled")
    if live_embedding.get("model") != desired_embedding["model"]:
        findings.append("embedding model drift")
    if live_embedding.get("daily_request_limit") != desired_embedding["daily_request_limit"]:
        findings.append("embedding daily request limit drift")
    api_keys = live_embedding.get("api_keys", [])
    expected_api_services = ["generativelanguage.googleapis.com"]
    if len(api_keys) != 1 or api_keys[0].get("services") != expected_api_services:
        findings.append("embedding API key restriction drift")
    budget = live_embedding.get("budget", {})
    if budget.get("amount_ils") != desired_embedding["monthly_budget_ils"]:
        findings.append("embedding monthly budget drift")
    if budget.get("thresholds_percent") != desired_embedding["budget_alert_thresholds_percent"]:
        findings.append("embedding budget thresholds drift")
    project_number = live_embedding.get("project_number")
    if not project_number or f"projects/{project_number}" not in budget.get("projects", []):
        findings.append("embedding budget is not scoped to the embedding project")
    return findings


def _gcloud_json(*args: str) -> Any:
    """Run one read-only gcloud command and parse its JSON output."""
    command = ["gcloud", *args, "--format=json"]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(completed.stdout or "null")


def _basename(resource_name: str) -> str:
    """Return the final segment of a fully qualified GCP resource name."""
    return str(resource_name or "").rstrip("/").rsplit("/", 1)[-1]


def _normalize_service(raw: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Normalize Cloud Run describe JSON for the pure auditor."""
    template = raw.get("spec", {}).get("template", {}).get("spec", {})
    containers = template.get("containers", [])
    environment: dict[str, str] = {}
    bindings: dict[str, str] = {}
    for item in (containers[0].get("env", []) if containers else []):
        name = item.get("name")
        if "value" in item:
            environment[name] = str(item["value"])
        secret_key = (
            item.get("valueFrom", {})
            .get("secretKeyRef", {})
            .get("name")
        )
        if secret_key:
            bindings[name] = _basename(secret_key)
    return {
        "name": raw.get("metadata", {}).get("name"),
        "region": raw.get("metadata", {}).get("labels", {}).get(
            "cloud.googleapis.com/location"
        ),
        "runtime_service_account": template.get("serviceAccountName"),
        "environment": environment,
        "secret_bindings": bindings,
    }


def _normalize_scheduler(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Cloud Scheduler job resource."""
    http_target = raw.get("httpTarget", {})
    return {
        "name": _basename(raw.get("name", "")),
        "state": raw.get("state"),
        "schedule": raw.get("schedule"),
        "time_zone": raw.get("timeZone"),
        "uri": http_target.get("uri"),
    }


def _normalize_ttl(raw: dict[str, Any]) -> dict[str, str] | None:
    """Normalize a Firestore TTL field resource name."""
    parts = str(raw.get("name") or "").split("/")
    try:
        collection_group = parts[parts.index("collectionGroups") + 1]
        field = parts[parts.index("fields") + 1]
    except (ValueError, IndexError):
        return None
    return {"collection_group": collection_group, "field": field}


def _normalize_bucket_storage_class(raw: dict[str, Any]) -> str | None:
    """Read either current gcloud snake_case or API camelCase bucket JSON."""
    return (
        raw.get("default_storage_class")
        or raw.get("defaultStorageClass")
        or raw.get("storageClass")
    )


def _count_enabled_versions(project: str, name: str) -> int:
    """Count enabled secret versions without reading payloads."""
    versions = _gcloud_json(
        "secrets",
        "versions",
        "list",
        name,
        "--project",
        project,
    )
    return sum(
        1
        for version in versions or []
        if str(version.get("state", "")).upper() == "ENABLED"
    )


def _fetch_runtime_inventory(public_url: str) -> dict[str, Any]:
    """Read the deployed app's self-reported route and connector inventory."""
    request = urllib.request.Request(
        public_url.rstrip("/") + "/health/inventory",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {
            "observed_routes": [],
            "connectors": [],
            "inventory_error": f"runtime inventory unavailable: {type(exc).__name__}",
        }
    return {
        "observed_routes": list(payload.get("observed_routes") or []),
        "connectors": list(payload.get("connectors") or []),
        "runtime_embedding": dict(payload.get("embedding") or {}),
        "inventory_error": payload.get("inventory_error"),
    }


def _capture_embedding_state(manifest: dict[str, Any]) -> dict[str, Any]:
    """Read dedicated embedding-project key, billing, and budget metadata."""
    desired = manifest["embedding"]
    project = desired["project"]
    project_meta = _gcloud_json("projects", "describe", project)
    project_number = str(project_meta.get("projectNumber") or "")
    billing = _gcloud_json("billing", "projects", "describe", project)
    keys = _gcloud_json("services", "api-keys", "list", "--project", project)
    billing_account = _basename(billing.get("billingAccountName", ""))
    budgets = _gcloud_json(
        "billing", "budgets", "list", "--billing-account", billing_account
    )
    matched_budget = next(
        (
            budget
            for budget in budgets or []
            if f"projects/{project_number}"
            in budget.get("budgetFilter", {}).get("projects", [])
        ),
        {},
    )
    amount = matched_budget.get("amount", {}).get("specifiedAmount", {})
    amount_ils = None
    if amount.get("currencyCode") == "ILS":
        amount_ils = int(amount.get("units") or 0)
    return {
        "project": project,
        "project_number": project_number,
        "billing_enabled": billing.get("billingEnabled") is True,
        "api_keys": [
            {
                "services": sorted(
                    target.get("service")
                    for target in key.get("restrictions", {}).get("apiTargets", [])
                    if target.get("service")
                )
            }
            for key in keys or []
        ],
        "budget": {
            "amount_ils": amount_ils,
            "projects": matched_budget.get("budgetFilter", {}).get("projects", []),
            "thresholds_percent": sorted(
                int(float(rule.get("thresholdPercent", 0)) * 100)
                for rule in matched_budget.get("thresholdRules", [])
            ),
        },
    }


def capture_live_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    """Capture current metadata with read-only gcloud describe/list calls."""
    service = manifest["service"]
    project = service["project"]
    region = service["region"]
    raw_service = _gcloud_json(
        "run",
        "services",
        "describe",
        service["name"],
        "--project",
        project,
        "--region",
        region,
    )
    jobs = _gcloud_json(
        "scheduler",
        "jobs",
        "list",
        "--project",
        project,
        "--location",
        region,
    )
    listed_secrets = _gcloud_json("secrets", "list", "--project", project)
    secret_names = sorted(
        set(manifest["secrets"]["runtime_access"])
        | set(manifest["secrets"]["forbidden"])
    )
    existing = {_basename(item.get("name", "")) for item in listed_secrets or []}
    secrets = [
        {"name": name, "enabled_versions": _count_enabled_versions(project, name)}
        for name in secret_names
        if name in existing
    ]
    secret_iam = {
        name: _gcloud_json(
            "secrets",
            "get-iam-policy",
            name,
            "--project",
            project,
        )
        for name in manifest["secrets"]["runtime_access"]
        if name in existing
    }
    database = _gcloud_json(
        "firestore",
        "databases",
        "describe",
        "--database",
        manifest["firestore"]["database"],
        "--project",
        project,
    )
    raw_ttls = _gcloud_json(
        "firestore",
        "fields",
        "ttls",
        "list",
        "--database",
        manifest["firestore"]["database"],
        "--project",
        project,
    )
    ttl_fields = [
        normalized
        for item in raw_ttls or []
        if (normalized := _normalize_ttl(item)) is not None
    ]
    repository = _gcloud_json(
        "artifacts",
        "repositories",
        "describe",
        manifest["artifact_registry"]["repository"],
        "--location",
        manifest["artifact_registry"]["location"],
        "--project",
        project,
    )
    bucket = _gcloud_json(
        "storage",
        "buckets",
        "describe",
        f"gs://{manifest['archive']['bucket']}",
        "--project",
        project,
    )
    bucket_policy = _gcloud_json(
        "storage",
        "buckets",
        "get-iam-policy",
        f"gs://{manifest['archive']['bucket']}",
        "--project",
        project,
    )
    runtime_member = "serviceAccount:" + service["runtime_service_account"]
    runtime_bucket_access = any(
        runtime_member in binding.get("members", [])
        for binding in bucket_policy.get("bindings", [])
        if str(binding.get("role", "")).startswith("roles/storage.")
    )
    runtime_inventory = _fetch_runtime_inventory(service["public_url"])
    embedding = _capture_embedding_state(manifest)
    embedding.update(runtime_inventory.pop("runtime_embedding", {}))
    return {
        "service": _normalize_service(raw_service, manifest),
        "schedulers": [_normalize_scheduler(job) for job in jobs or []],
        "secrets": secrets,
        "project_iam": _gcloud_json("projects", "get-iam-policy", project),
        "secret_iam": secret_iam,
        "firestore": {
            "database": _basename(database.get("name", "")),
            "deletion_protection": database.get("deleteProtectionState"),
            "ttl_fields": ttl_fields,
        },
        "archive": {
            "bucket": manifest["archive"]["bucket"],
            "storage_class": _normalize_bucket_storage_class(bucket),
            "runtime_access": "present" if runtime_bucket_access else "none",
        },
        "artifact_cleanup_policy_names": sorted(
            (repository.get("cleanupPolicies") or {}).keys()
        ),
        "embedding": embedding,
        **runtime_inventory,
    }


def main() -> int:
    """Capture or load a snapshot, print drift, and return a CI-safe status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--write-snapshot", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    else:
        snapshot = capture_live_snapshot(manifest)
    if args.write_snapshot:
        args.write_snapshot.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    findings = audit_snapshot(manifest, snapshot)
    if findings:
        print("Production drift detected:")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("Production matches ops/desired-production.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
