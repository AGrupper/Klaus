"""Synchronous Web Push fan-out (Phase 29 — PUSH-02).

`send_push_to_all` is the single push-sending primitive: it loads the VAPID
private key from Secret Manager (cached), builds one JSON payload, and sends
it to every stored subscription via `pywebpush.webpush`, reconciling the
subscription store based on the response.

SYNC / blocking (pywebpush wraps `requests`). Every caller MUST invoke this
via `loop.run_in_executor(None, send_push_to_all, text, message_class)` from
an async context — never call it directly from a coroutine. This is the same
class of bug as the weekly-review-500 incident (CLAUDE.md invariant: never
block the event loop).

Analogs: core/auth_google.py::SecretManagerTokenStorage (Secret Manager load
shape) and core/heartbeat.py::check_tokens (per-item try/except/classify
shape).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# D-07: per-message-class push TTL (seconds). Time-critical classes expire
# fast (pointless once the moment has passed); everything else persists a
# full day — plenty for Amit to open his phone, and comfortably under APNs'
# 28-day cap.
CLASS_TTL: dict = {
    "leave_by": 3600,       # traffic/leave-by alerts — stale after an hour
    "habit_nudge": 3600,    # slot nudges — pointless after the slot passes
    "chat_reply": 86400,
    "briefing": 86400,
    "review": 86400,
    "alert": 86400,         # heartbeat/system alerts
    "default": 86400,
}

_VAPID_SUB_CLAIM = "mailto:amit.grupper@gmail.com"
_VAPID_SECRET_NAME = "klaus-vapid-private-key"

# Module-level cache — the VAPID private key is loaded from Secret Manager
# once per process and reused for every send (never logged, never returned
# in any tool/route response — T-29-05).
_VAPID_PRIVATE_KEY: str | None = None


def _get_vapid_private_key() -> str:
    """Lazily load and cache the VAPID private key from Secret Manager.

    Mirrors core/auth_google.py::SecretManagerTokenStorage.load's
    access_secret_version call shape.
    """
    global _VAPID_PRIVATE_KEY
    if _VAPID_PRIVATE_KEY is not None:
        return _VAPID_PRIVATE_KEY

    from google.cloud import secretmanager

    project_id = os.environ["GCP_PROJECT_ID"]
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{_VAPID_SECRET_NAME}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    _VAPID_PRIVATE_KEY = response.payload.data.decode("utf-8")
    return _VAPID_PRIVATE_KEY


def _reconcile(fn, *args) -> None:
    """Best-effort subscription-store bookkeeping (WR-03).

    PushSubscriptionStore.record_success/record_failure/delete re-raise on
    Firestore failure by documented design. Inside the fan-out loop a
    bookkeeping failure must NEVER (a) reclassify a delivered push as a
    failure, or (b) abort the remaining subscriptions — so wrap every
    reconciliation write and log instead of raising.
    """
    try:
        fn(*args)
    except Exception:
        logger.warning(
            "push_sender: subscription bookkeeping %s(%s) failed — delivery result unaffected",
            getattr(fn, "__name__", str(fn)),
            args[0] if args else "",
            exc_info=True,
        )


def _get_subscription_store():
    """Return a PushSubscriptionStore using env-driven project/database config.

    Lazy-imported inside the helper (module-cheap-import discipline — mirrors
    core/tools.py::_get_task_store).
    """
    from memory.firestore_db import PushSubscriptionStore

    return PushSubscriptionStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def send_push_to_all(text: str, message_class: str = "default") -> dict:
    """Fan out one push message to every stored subscription.

    SYNC — always call via loop.run_in_executor from async contexts.

    Args:
        text: The message body. Truncated to 1000 chars in the payload (D-12
            documented deviation — see note below).
        message_class: Selects the TTL from CLASS_TTL (D-07).

    Returns:
        {"sent": int, "failed": int, "removed": int}
    """
    from pywebpush import webpush, WebPushException

    store = _get_subscription_store()
    payload = json.dumps({
        "title": "Klaus",
        # DEVIATION (justified, D-12): D-12 calls for "full message text" as
        # the body, but APNs caps encrypted push payloads at ~4KB
        # (RESEARCH.md Assumption A8) and iOS truncates/expands the display
        # regardless. Nothing is lost: the full text is always available in
        # the Firestore conversation store + Telegram mirror.
        "body": text[:1000],
        "url": "/",
        "class": message_class,
    })
    ttl = CLASS_TTL.get(message_class, CLASS_TTL["default"])
    results = {"sent": 0, "failed": 0, "removed": 0}

    for sub in store.list_all():
        endpoint = sub.get("endpoint", "")
        # WR-03: the try/except covers ONLY the webpush() delivery attempt.
        # Store reconciliation happens outside it via _reconcile so a
        # Firestore blip can neither misrecord a delivered push as a failure
        # nor abort the remaining fan-out.
        try:
            webpush(
                subscription_info={"endpoint": endpoint, "keys": sub.get("keys", {})},
                data=payload,
                vapid_private_key=_get_vapid_private_key(),
                # Fresh dict every call — pywebpush mutates the claims dict
                # it's given (Pitfall 5); sharing one across sends corrupts
                # later sends.
                vapid_claims={"sub": _VAPID_SUB_CLAIM},
                ttl=ttl,
                timeout=10,  # CLAUDE.md invariant: explicit timeout, always
            )
        except WebPushException as ex:
            status = ex.response.status_code if ex.response is not None else None
            if status in (404, 410):
                # Dead subscription — the browser/OS revoked it. Remove it
                # so future fan-outs don't keep hitting a dead endpoint.
                _reconcile(store.delete, endpoint)
                results["removed"] += 1
            else:
                _reconcile(store.record_failure, endpoint, f"{status}: {ex}")
                results["failed"] += 1
            continue
        except Exception as ex:  # DNS failure, timeout, etc.
            _reconcile(store.record_failure, endpoint, str(ex))
            results["failed"] += 1
            continue
        _reconcile(store.record_success, endpoint)
        results["sent"] += 1

    return results
