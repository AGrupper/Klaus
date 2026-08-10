from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_runbook_documents_atomic_skill_rollout():
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text()
    for phrase in (
        "Claude skill 7.1.0 coordinated rollout",
        "KLAUS_ROUTINE_NIGHTLY_CUTOVER=false",
        "Upload all four 7.1.0 ZIP files",
        "Edit all three saved Remote Routine instructions",
        "exact published review text",
        "KLAUS_ROUTINE_NIGHTLY_CUTOVER=true",
    ):
        assert phrase in text


def test_production_cutovers_remain_independent():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "KLAUS_ROUTINE_MORNING_CUTOVER=false" in workflow
    assert "KLAUS_ROUTINE_WEEKLY_CUTOVER=false" in workflow
