"""Regression guard for routine-cutover containment in the deploy workflow."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
EXPECTED_ROUTINE_CUTOVERS = {
    "KLAUS_ROUTINE_MORNING_CUTOVER": "false",
    "KLAUS_ROUTINE_NIGHTLY_CUTOVER": "false",
    "KLAUS_ROUTINE_WEEKLY_CUTOVER": "false",
}


def test_deploy_pauses_all_routines_during_the_coordinated_skill_rollout():
    """Production deploys preserve the approved pre-shadow rollout state."""
    workflow = DEPLOY_WORKFLOW.read_text()

    for key, expected in EXPECTED_ROUTINE_CUTOVERS.items():
        assignments = re.findall(rf"\b{key}=([^,\"\\\s]+)", workflow)
        assert assignments == [expected], f"{key} assignments: {assignments}"
