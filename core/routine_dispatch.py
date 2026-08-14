"""Cloud Tasks enqueue helper retained solely for routine timeout fallbacks."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone


def enqueue_routine_fallback(correlation_id: str, delay_seconds: int) -> bool:
    """Schedule the deterministic routine fallback after its callback deadline."""
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    queue = os.environ.get("CLOUD_TASKS_QUEUE", "")
    project = os.environ.get("GCP_PROJECT_ID", "")
    location = os.environ.get("CLOUD_TASKS_LOCATION", "")
    service_url = os.environ.get("CLOUD_RUN_URL", "").rstrip("/")
    service_account = os.environ.get("CLOUD_SCHEDULER_SA_EMAIL", "")
    if not all((queue, project, location, service_url, service_account)):
        return False
    schedule = timestamp_pb2.Timestamp()
    schedule.FromDatetime(datetime.now(timezone.utc) + timedelta(seconds=delay_seconds))
    task = {
        "schedule_time": schedule,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{service_url}/internal/routine-fallback",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"correlation_id": correlation_id}).encode(),
            "oidc_token": {
                "service_account_email": service_account,
                "audience": service_url,
            },
        },
    }
    try:
        tasks_v2.CloudTasksClient().create_task(
            parent=f"projects/{project}/locations/{location}/queues/{queue}", task=task,
        )
    except Exception:
        return False
    return True
