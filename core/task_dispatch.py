"""Cloud Tasks dispatch — run Telegram updates inside a tracked request.

WHY this exists: the Telegram webhook ACKs with 200 immediately and used to
process the update in a Starlette BackgroundTask. Background tasks run AFTER
the response is sent, and Cloud Run (request-based billing, default CPU
throttling) cuts the container to a sliver of CPU once no request is in
flight — so the whole agent turn crawled (observed 2026-06-12: a 6.5-minute
stall on one worker call, an 18-minute reply overall).

enqueue_update() hands the raw update JSON to Cloud Tasks, which POSTs it
back to ``/internal/process-update`` with an OIDC token (same service
account + verification path as the Cloud Scheduler crons). The agent turn
then runs inside that tracked request with full CPU. This keeps the
instant-ACK contract with Telegram without paying for always-on CPU
(``--no-cpu-throttling`` would bill the instance ~24/7).

Env vars:
    CLOUD_TASKS_QUEUE        — queue name (e.g. "klaus-updates"); unset/empty
                               disables dispatch and the webhook falls back to
                               the in-process background path.
    CLOUD_TASKS_LOCATION     — queue region (default "me-central1"; Cloud
                               Tasks is not offered in me-west1).
    GCP_PROJECT_ID           — project hosting the queue.
    CLOUD_RUN_URL            — service base URL; also the OIDC audience.
    CLOUD_SCHEDULER_SA_EMAIL — service account for the task's OIDC token
                               (reused from the crons; it already holds
                               run.invoker on this service).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# Lazy singleton — CloudTasksClient builds a gRPC channel; one per process.
_client = None

# Upper bound Cloud Tasks waits for /internal/process-update before counting
# the attempt as failed. Must stay below the Cloud Run request timeout so the
# request is never killed mid-turn from the outside.
_DISPATCH_DEADLINE_SECONDS = 540


def _get_client():
    global _client  # noqa: PLW0603
    if _client is None:
        from google.cloud import tasks_v2  # lazy import (startup cost)
        _client = tasks_v2.CloudTasksClient()
    return _client


def enqueue_update(payload: dict) -> bool:
    """Enqueue one Telegram update JSON for full-CPU processing.

    Args:
        payload: The raw update JSON exactly as Telegram delivered it —
                 re-deserialised by /internal/process-update.

    Returns:
        True if the task was created; False on ANY failure (queue env unset,
        missing config, Cloud Tasks outage). Never raises — the webhook must
        always be able to fall back to in-process handling so an update is
        never dropped.
    """
    queue = os.getenv("CLOUD_TASKS_QUEUE", "")
    if not queue:
        return False
    try:
        project = os.environ["GCP_PROJECT_ID"]
        # WHY me-central1: Cloud Tasks is not offered in me-west1 (the
        # service's own region); me-central1 is the nearest supported one.
        location = os.getenv("CLOUD_TASKS_LOCATION", "me-central1")
        base_url = os.environ["CLOUD_RUN_URL"]
        sa_email = os.environ["CLOUD_SCHEDULER_SA_EMAIL"]

        client = _get_client()
        parent = client.queue_path(project, location, queue)
        task = {
            "dispatch_deadline": {"seconds": _DISPATCH_DEADLINE_SECONDS},
            "http_request": {
                "http_method": "POST",
                "url": f"{base_url}/internal/process-update",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode("utf-8"),
                "oidc_token": {
                    "service_account_email": sa_email,
                    # WHY: audience must match what _verify_cron_request
                    # validates (the bare service URL), not the full path.
                    "audience": base_url,
                },
            },
        }
        client.create_task(request={"parent": parent, "task": task})
        return True
    except Exception:
        logger.exception(
            "Cloud Tasks enqueue failed for update_id=%s — falling back to "
            "in-process handling",
            payload.get("update_id"),
        )
        return False


def enqueue_hub_message(
    content: str, user_id: int, attachments: list[dict] | None = None,
    regenerate: bool = False,
) -> bool:
    """Enqueue a hub chat message for full-CPU agent processing.

    Mirrors enqueue_update exactly — same queue, same OIDC token, same
    dispatch deadline — but targets /internal/process-hub-message instead
    of /internal/process-update, and carries a simple {content, user_id}
    payload instead of a raw Telegram Update.

    WHY a dedicated endpoint (D-09 / CLAUDE.md invariant): hub messages must
    run the agent turn inside a tracked Cloud Tasks request with full CPU.
    Reusing /internal/process-update would require a Telegram Update object;
    the hub has no such object. A dedicated endpoint keeps the paths clean.

    Args:
        content: The user's message text.
        user_id: The Telegram user ID (FirestoreConversationStore key) so the
                 agent turn shares the same conversation history as Telegram.
        attachments: Optional attachment metadata dicts from /api/chat/upload
                 ({id, kind, mime, name, size}). Metadata only — the bytes
                 stay in GCS (Cloud Tasks bodies cap at ~1MB) and the worker
                 re-downloads them by id.

    Returns:
        True if the task was created; False on ANY failure (queue env unset,
        missing config, Cloud Tasks outage). Never raises — the /api/chat
        route must be able to surface a 503 to the client rather than crash.
    """
    queue = os.getenv("CLOUD_TASKS_QUEUE", "")
    if not queue:
        return False
    try:
        project = os.environ["GCP_PROJECT_ID"]
        # WHY me-central1: Cloud Tasks is not offered in me-west1 (the
        # service's own region); me-central1 is the nearest supported one.
        location = os.getenv("CLOUD_TASKS_LOCATION", "me-central1")
        base_url = os.environ["CLOUD_RUN_URL"]
        sa_email = os.environ["CLOUD_SCHEDULER_SA_EMAIL"]

        client = _get_client()
        parent = client.queue_path(project, location, queue)
        payload: dict = {"content": content, "user_id": user_id}
        if attachments:
            payload["attachments"] = attachments
        if regenerate:
            # Hub regenerate: the user message is already the trailing history
            # entry (its old reply was popped) — the worker must not re-append.
            payload["regenerate"] = True
        task = {
            "dispatch_deadline": {"seconds": _DISPATCH_DEADLINE_SECONDS},
            "http_request": {
                "http_method": "POST",
                "url": f"{base_url}/internal/process-hub-message",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode("utf-8"),
                "oidc_token": {
                    "service_account_email": sa_email,
                    # WHY: audience must match what _verify_cron_request
                    # validates (the bare service URL), not the full path.
                    "audience": base_url,
                },
            },
        }
        client.create_task(request={"parent": parent, "task": task})
        return True
    except Exception:
        logger.exception(
            "Cloud Tasks enqueue failed for hub message (user_id=%s) — "
            "caller should surface 503 to the client",
            user_id,
        )
        return False
