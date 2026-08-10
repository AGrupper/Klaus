"""Regression guard for routine-cutover containment in the deploy workflow."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
ROUTINE_CUTOVERS = (
    "KLAUS_ROUTINE_MORNING_CUTOVER",
    "KLAUS_ROUTINE_NIGHTLY_CUTOVER",
    "KLAUS_ROUTINE_WEEKLY_CUTOVER",
)


def test_deploy_keeps_all_routine_cutovers_explicitly_disabled():
    """Production deploys keep every routine cutover false during recovery."""
    workflow = DEPLOY_WORKFLOW.read_text()

    for key in ROUTINE_CUTOVERS:
        assignments = re.findall(rf"\b{key}=([^,\"\\\s]+)", workflow)
        assert assignments == ["false"], f"{key} assignments: {assignments}"
