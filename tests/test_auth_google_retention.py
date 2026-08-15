"""Google OAuth operator-reauthorization retention regression tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.auth_google import SecretManagerTokenStorage
from core.secret_retention import build_retention_plan


def _version(number: int, state: str) -> SimpleNamespace:
    """Return a minimal SecretVersion-shaped test object."""
    return SimpleNamespace(
        name=f"projects/klaus-agent/secrets/klaus-google-oauth-token/versions/{number}",
        state=SimpleNamespace(name=state),
        create_time=SimpleNamespace(timestamp=lambda: float(number)),
    )


def test_secret_manager_save_keeps_two_and_prunes_in_two_phases():
    """A new grant keeps newest+rollback and prunes older stored grants."""
    client = MagicMock()
    client.list_secret_versions.return_value = [
        _version(5, "ENABLED"),
        _version(4, "ENABLED"),
        _version(3, "ENABLED"),
        _version(2, "DISABLED"),
        _version(1, "DESTROYED"),
    ]
    storage = SecretManagerTokenStorage(
        project_id="klaus-agent",
        secret_name="klaus-google-oauth-token",
    )

    with patch(
        "google.cloud.secretmanager.SecretManagerServiceClient",
        return_value=client,
    ):
        storage.save('{"token":"fresh"}')

    client.add_secret_version.assert_called_once()
    client.disable_secret_version.assert_called_once_with(
        request={
            "name": "projects/klaus-agent/secrets/klaus-google-oauth-token/versions/3"
        },
        timeout=20,
    )
    client.destroy_secret_version.assert_called_once_with(
        request={
            "name": "projects/klaus-agent/secrets/klaus-google-oauth-token/versions/2"
        },
        timeout=20,
    )
    assert client.destroy_secret_version.call_args.kwargs["request"]["name"].endswith(
        "/2"
    )


def test_secret_manager_save_does_not_fail_when_best_effort_pruning_fails(caplog):
    """A persisted grant remains saved when operator retention fails."""
    client = MagicMock()
    client.list_secret_versions.side_effect = PermissionError("no version-manager role")
    storage = SecretManagerTokenStorage(
        project_id="klaus-agent",
        secret_name="klaus-google-oauth-token",
    )

    with patch(
        "google.cloud.secretmanager.SecretManagerServiceClient",
        return_value=client,
    ):
        storage.save('{"token":"fresh"}')

    client.add_secret_version.assert_called_once()
    assert "retention cleanup failed" in caplog.text


def test_secret_manager_save_still_surfaces_write_failure():
    """Retention must not hide failure to persist the newly consented grant."""
    client = MagicMock()
    client.add_secret_version.side_effect = RuntimeError("write failed")
    storage = SecretManagerTokenStorage(
        project_id="klaus-agent",
        secret_name="klaus-google-oauth-token",
    )

    with patch(
        "google.cloud.secretmanager.SecretManagerServiceClient",
        return_value=client,
    ), pytest.raises(RuntimeError, match="write failed"):
        storage.save('{"token":"fresh"}')

    client.list_secret_versions.assert_not_called()


def test_retention_prefers_two_enabled_versions_over_newer_disabled_version():
    """A disabled version must not displace the last working rollback token."""
    plan = build_retention_plan(
        [
            {"version": "5", "state": "ENABLED"},
            {"version": "4", "state": "DISABLED"},
            {"version": "3", "state": "ENABLED"},
        ],
        keep_count=2,
    )

    assert plan["keep"] == ["5", "3"]
    assert plan["disable"] == []
    assert plan["destroy"] == ["4"]
