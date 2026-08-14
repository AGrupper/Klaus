#!/usr/bin/env python3
"""Evaluate seven-day retirement quarantine evidence without mutating GCP."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "ops" / "policies" / "quarantine.json"


def _parse_timestamp(value: str) -> datetime:
    """Parse a required timezone-aware RFC3339 timestamp."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("quarantine timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_quarantine(
    policy: dict[str, Any],
    evidence: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return blocking findings; an empty result permits operator review."""
    findings: list[str] = []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        started = _parse_timestamp(evidence["observation_started_at"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"invalid observation start: {exc}"]
    minimum = timedelta(days=int(policy["minimum_observation_days"]))
    if current - started < minimum:
        findings.append("minimum seven-day observation window is not complete")
    if int(evidence.get("access_count", -1)) != int(policy["required_access_count"]):
        findings.append("retired resource access count is not zero")
    if int(evidence.get("generative_usage_count", -1)) != int(
        policy["required_generative_usage_count"]
    ):
        findings.append("generative provider usage count is not zero")
    if evidence.get("resources_still_disabled") is not True:
        findings.append("one or more quarantined resources are not disabled")
    expected_routines = {"morning", "nightly", "weekly"}
    actual_routines = set(evidence.get("claude_routines_successful", []))
    if expected_routines - actual_routines:
        findings.append(
            "missing successful Claude routines: "
            + ", ".join(sorted(expected_routines - actual_routines))
        )
    return findings


def main() -> int:
    """Evaluate operator-collected evidence and return a deletion gate status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    findings = evaluate_quarantine(policy, evidence)
    if findings:
        print("Quarantine deletion gate is closed:")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("Quarantine evidence satisfies the seven-day deletion gate.")
    print("This is an audit result only; no resource was deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
