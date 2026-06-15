"""Tests for core/task_dispatch.py — Cloud Tasks dispatch for Telegram updates.

WHY this module exists: the Telegram webhook ACKs immediately and used to
process the update in a Starlette BackgroundTask. Background tasks run AFTER
the response is sent, so on a CPU-throttled Cloud Run service the whole agent
turn crawls (observed: an 18-minute reply on 2026-06-12). enqueue_update()
hands the update to Cloud Tasks, which POSTs it back to
/internal/process-update — the turn then runs inside a tracked request with
full CPU.

google-cloud-tasks is lazy-imported inside enqueue_update, so these tests
stub the client via sys.modules and never need real GCP credentials.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


_ENV = {
    "GCP_PROJECT_ID": "test-project",
    "CLOUD_TASKS_QUEUE": "klaus-updates",
    "CLOUD_TASKS_LOCATION": "me-west1",
    "CLOUD_RUN_URL": "https://klaus.example.run.app",
    "CLOUD_SCHEDULER_SA_EMAIL": "sa@test-project.iam.gserviceaccount.com",
}


@pytest.fixture()
def fake_tasks_v2():
    """Stub google.cloud.tasks_v2 in sys.modules and reset the client singleton.

    WHY google + google.cloud are also stubbed: `from google.cloud import tasks_v2`
    is a namespace-package import. Python resolves it by looking up `google.cloud`
    in sys.modules first, then reading `tasks_v2` as an attribute. Without
    stubbing the parent packages, the import raises ModuleNotFoundError even when
    `google.cloud.tasks_v2` is in sys.modules (fix for test environments where
    google-cloud-tasks is not installed).
    """
    fake = MagicMock(name="tasks_v2")
    fake_client = MagicMock(name="CloudTasksClient")
    fake_client.queue_path.return_value = (
        "projects/test-project/locations/me-west1/queues/klaus-updates"
    )
    fake.CloudTasksClient.return_value = fake_client

    # Stub the namespace-package parents so `from google.cloud import tasks_v2` resolves.
    fake_google_cloud = MagicMock(name="google.cloud")
    fake_google_cloud.tasks_v2 = fake
    fake_google = sys.modules.get("google") or MagicMock(name="google")
    if hasattr(fake_google, "cloud"):
        # Preserve existing google.cloud stub if present (e.g. from google-auth).
        pass
    else:
        fake_google.cloud = fake_google_cloud

    with patch.dict(sys.modules, {
        "google.cloud.tasks_v2": fake,
        "google.cloud": fake_google_cloud,
    }):
        import core.task_dispatch as td
        td._client = None  # reset lazy singleton between tests
        yield fake, fake_client
        td._client = None


class TestEnqueueUpdate:

    def test_returns_false_when_queue_env_unset(self, monkeypatch, fake_tasks_v2):
        """No CLOUD_TASKS_QUEUE → dispatch disabled → False, no client built."""
        fake, fake_client = fake_tasks_v2
        from core.task_dispatch import enqueue_update

        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("CLOUD_TASKS_QUEUE", raising=False)

        assert enqueue_update({"update_id": 1}) is False
        fake.CloudTasksClient.assert_not_called()

    def test_enqueues_task_with_oidc_and_payload(self, monkeypatch, fake_tasks_v2):
        """Happy path: creates a task targeting /internal/process-update with
        the OIDC service account and the raw update JSON as body."""
        fake, fake_client = fake_tasks_v2
        from core.task_dispatch import enqueue_update

        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)

        payload = {"update_id": 42, "message": {"text": "hi"}}
        assert enqueue_update(payload) is True

        fake_client.create_task.assert_called_once()
        _, kwargs = fake_client.create_task.call_args
        request = kwargs.get("request") or fake_client.create_task.call_args[0][0]
        task = request["task"]
        http = task["http_request"]
        assert request["parent"] == (
            "projects/test-project/locations/me-west1/queues/klaus-updates"
        )
        assert http["url"] == "https://klaus.example.run.app/internal/process-update"
        assert http["oidc_token"]["service_account_email"] == (
            "sa@test-project.iam.gserviceaccount.com"
        )
        assert http["oidc_token"]["audience"] == "https://klaus.example.run.app"
        assert json.loads(http["body"].decode("utf-8")) == payload

    def test_returns_false_when_create_task_raises(self, monkeypatch, fake_tasks_v2):
        """Cloud Tasks outage must not lose the update — caller falls back."""
        fake, fake_client = fake_tasks_v2
        from core.task_dispatch import enqueue_update

        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)
        fake_client.create_task.side_effect = RuntimeError("queue unavailable")

        assert enqueue_update({"update_id": 7}) is False


class TestEnqueueHubMessage:

    def test_enqueue_hub_message_targets_correct_url(self, monkeypatch, fake_tasks_v2):
        """Happy path: creates a task targeting /internal/process-hub-message with
        the OIDC service account and {content, user_id} JSON as body.

        Covers CHAT-02: hub messages must go through the dedicated
        /internal/process-hub-message full-CPU path (never /internal/process-update
        and never a Starlette BackgroundTask).
        """
        fake, fake_client = fake_tasks_v2
        from core.task_dispatch import enqueue_hub_message

        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)

        assert enqueue_hub_message("hi", 123) is True

        fake_client.create_task.assert_called_once()
        _, kwargs = fake_client.create_task.call_args
        request = kwargs.get("request") or fake_client.create_task.call_args[0][0]
        task = request["task"]
        http = task["http_request"]

        # URL must target the hub-specific endpoint, not /internal/process-update
        assert http["url"].endswith("/internal/process-hub-message"), (
            f"Expected URL ending with /internal/process-hub-message, got: {http['url']}"
        )
        # Payload must carry content + user_id (not a Telegram Update object)
        body = json.loads(http["body"].decode("utf-8"))
        assert body == {"content": "hi", "user_id": 123}
        # OIDC token must be present (same service account as enqueue_update)
        assert http["oidc_token"]["service_account_email"] == (
            "sa@test-project.iam.gserviceaccount.com"
        )
        assert http["oidc_token"]["audience"] == "https://klaus.example.run.app"

    def test_returns_false_when_queue_env_unset(self, monkeypatch, fake_tasks_v2):
        """No CLOUD_TASKS_QUEUE → dispatch disabled → False (same as enqueue_update)."""
        fake, fake_client = fake_tasks_v2
        from core.task_dispatch import enqueue_hub_message

        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("CLOUD_TASKS_QUEUE", raising=False)

        assert enqueue_hub_message("hi", 123) is False
        fake.CloudTasksClient.assert_not_called()

    def test_returns_false_when_create_task_raises(self, monkeypatch, fake_tasks_v2):
        """Cloud Tasks outage must not raise — caller surfaces 503 instead."""
        fake, fake_client = fake_tasks_v2
        from core.task_dispatch import enqueue_hub_message

        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)
        fake_client.create_task.side_effect = RuntimeError("queue unavailable")

        assert enqueue_hub_message("hi", 123) is False
