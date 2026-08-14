"""Pure planning helpers for bounded Secret Manager version retention."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _version_number(record: dict[str, Any]) -> int:
    """Return the numeric Secret Manager version, sorting aliases last."""
    raw = str(record.get("version") or record.get("name") or "").rsplit("/", 1)[-1]
    try:
        return int(raw)
    except ValueError:
        return -1


def _created_at(record: dict[str, Any]) -> datetime | None:
    """Parse an RFC3339 create timestamp when one is available."""
    value = record.get("created_at")
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_retention_plan(
    versions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    keep_count: int = 2,
    destroy_grace_days: int = 0,
) -> dict[str, list[str]]:
    """Plan a fail-safe latest-plus-rollback retention transition.

    Enabled versions beyond ``keep_count`` are disabled. Only versions that
    were already disabled when this function was called are eligible for
    destruction, so no version can cross both state transitions in one run.
    ``destroy_grace_days`` additionally protects recently-created disabled
    versions when a timestamp is available.
    """
    if keep_count < 2:
        raise ValueError("keep_count must preserve latest plus one rollback")
    if destroy_grace_days < 0:
        raise ValueError("destroy_grace_days must be non-negative")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=destroy_grace_days)
    usable = sorted(
        (
            record
            for record in versions
            if str(record.get("state") or "").upper() in {"ENABLED", "DISABLED"}
            and _version_number(record) >= 0
        ),
        key=_version_number,
        reverse=True,
    )
    enabled = [
        record
        for record in usable
        if str(record.get("state") or "").upper() == "ENABLED"
    ]
    selected = enabled[:keep_count]
    if len(selected) < keep_count:
        selected_numbers = {_version_number(record) for record in selected}
        selected.extend(
            record
            for record in usable
            if _version_number(record) not in selected_numbers
            and str(record.get("state") or "").upper() == "DISABLED"
        )
        selected = selected[:keep_count]
    keep = [str(_version_number(record)) for record in selected]
    keep_set = set(keep)
    disable: list[str] = []
    destroy: list[str] = []
    for record in usable:
        number = str(_version_number(record))
        if number in keep_set:
            continue
        state = str(record.get("state") or "").upper()
        if state == "ENABLED":
            disable.append(number)
            continue
        created_at = _created_at(record)
        if destroy_grace_days and (created_at is None or created_at > cutoff):
            continue
        destroy.append(number)
    return {"keep": keep, "disable": disable, "destroy": destroy}


def _state_name(value: Any) -> str:
    """Normalize proto enum values to their symbolic state name."""
    name = getattr(value, "name", None)
    return str(name or value).rsplit(".", 1)[-1].upper()


def _as_record(version: Any) -> dict[str, Any]:
    """Convert a SecretVersion proto into the pure planner's record shape."""
    create_time = getattr(version, "create_time", None)
    if hasattr(create_time, "timestamp"):
        created_at = datetime.fromtimestamp(
            create_time.timestamp(), tz=timezone.utc
        ).isoformat()
    else:
        created_at = None
    name = str(getattr(version, "name", ""))
    return {
        "name": name,
        "version": name.rsplit("/", 1)[-1],
        "state": _state_name(getattr(version, "state", "")),
        "created_at": created_at,
    }


def plan_for_client(
    client: Any,
    parent: str,
    *,
    keep_count: int = 2,
    destroy_grace_days: int = 0,
) -> dict[str, list[str]]:
    """Read versions and return the bounded transition plan."""
    versions = [
        _as_record(version)
        for version in client.list_secret_versions(
            request={"parent": parent},
            timeout=20,
        )
    ]
    return build_retention_plan(
        versions,
        keep_count=keep_count,
        destroy_grace_days=destroy_grace_days,
    )


def apply_plan(client: Any, parent: str, plan: dict[str, list[str]]) -> None:
    """Apply a precomputed two-phase plan without recomputing live state."""
    for version in plan["disable"]:
        client.disable_secret_version(
            request={"name": f"{parent}/versions/{version}"}, timeout=20
        )
    for version in plan["destroy"]:
        client.destroy_secret_version(
            request={"name": f"{parent}/versions/{version}"}, timeout=20
        )
