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
    for key in desired_service["forbidden_environment"]:
        if key in environment:
            findings.append(f"forbidden environment variable present: {key}")

    bindings = live_service.get("secret_bindings", {})
    for variable, secret_name in desired_service["secret_bindings"].items():
        if bindings.get(variable) != secret_name:
            findings.append(
                f"secret binding drift for {variable}: expected {secret_name!r}, "
                f"got {bindings.get(variable)!r}"
            )

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
        if name not in live_secrets:
            findings.append(f"missing retained secret: {name}")
    for name in manifest["secrets"]["forbidden"]:
        secret = live_secrets.get(name)
        if secret and int(secret.get("usable_versions") or 0) > 0:
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
    for route in manifest["routes"]["retained"] + manifest["routes"]["tombstones"]:
        if route not in snapshot.get("observed_routes", []):
            findings.append(f"expected route missing from runtime: {route}")
    for connector in manifest["connectors"]:
        if connector not in snapshot.get("connectors", []):
            findings.append(f"retained connector missing: {connector}")
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


def _count_usable_versions(project: str, name: str) -> int:
    """Count enabled or disabled secret versions without reading payloads."""
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
        if str(version.get("state", "")).upper() in {"ENABLED", "DISABLED"}
    )


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
        {"name": name, "usable_versions": _count_usable_versions(project, name)}
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
        # Route/connector lists are checked against the checked-in app in CI;
        # GCP does not expose application route metadata.
        "observed_routes": list(manifest["routes"]["retained"])
        + list(manifest["routes"]["tombstones"]),
        "connectors": list(manifest["connectors"]),
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
