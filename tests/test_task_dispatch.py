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
    """Stub google.cloud.tasks_v2 in sys.modules and reset the client singleton."""
    fake = MagicMock(name="tasks_v2")
    fake_client = MagicMock(name="CloudTasksClient")
    fake_client.queue_path.return_value = (
        "projects/test-project/locations/me-west1/queues/klaus-updates"
    )
    fake.CloudTasksClient.return_value = fake_client
    with patch.dict(sys.modules, {
        "google.cloud.tasks_v2": fake,
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
