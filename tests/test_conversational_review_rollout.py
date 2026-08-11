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
    assert "KLAUS_ROUTINE_MORNING_CUTOVER=true" in workflow
    assert "KLAUS_ROUTINE_WEEKLY_CUTOVER=false" in workflow


def test_rollout_verifies_live_paused_revision_before_claude_edits():
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text()

    pause = text.index("KLAUS_ROUTINE_NIGHTLY_CUTOVER=false")
    live_revision = text.index("Inspect the live Cloud Run revision/environment")
    all_cutovers_paused = text.index("all three live routine cutovers are false")
    skill_metadata = text.index("MCP metadata reports expected skill version 7.1.0")
    upload = text.index("Upload all four 7.1.0 ZIP files")

    assert pause < live_revision < all_cutovers_paused < skill_metadata < upload


def test_rollout_verifies_live_restoration_before_nightly_uat():
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text()

    restore = text.index("KLAUS_ROUTINE_NIGHTLY_CUTOVER=true")
    commit_and_push = text.index("Commit and push the restoration")
    deployed = text.index("wait for its deployment")
    health = text.index("verify `/health`")
    live_revision = text.index("inspect the live Cloud Run environment")
    restored_cutovers = text.index(
        "nightly=true while morning=false and weekly=false"
    )
    live_uat = text.index("Run one nightly live UAT")

    assert restore < commit_and_push < deployed < health < live_revision
    assert live_revision < restored_cutovers < live_uat
