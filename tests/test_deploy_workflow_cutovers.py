"""Regression guard for routine-cutover containment in the deploy workflow."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
EXPECTED_ROUTINE_CUTOVERS = {
    "KLAUS_ROUTINE_MORNING_CUTOVER": "true",
    "KLAUS_ROUTINE_NIGHTLY_CUTOVER": "true",
    "KLAUS_ROUTINE_WEEKLY_CUTOVER": "true",
}


def test_deploy_enables_all_claude_routines():
    """Production deploy enables morning, nightly, and weekly Claude Routines."""
    workflow = DEPLOY_WORKFLOW.read_text()

    for key, expected in EXPECTED_ROUTINE_CUTOVERS.items():
        assignments = re.findall(rf"\b{key}=([^,\"\\\s]+)", workflow)
        assert assignments == [expected], f"{key} assignments: {assignments}"
