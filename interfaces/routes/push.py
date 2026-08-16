"""Web Push subscription and VAPID key APIs.

The public VAPID key is public by definition and is the one Hub route with no
session gate besides sign-in itself. Subscriptions are keyed by a digest of the
endpoint so re-subscribing the same browser updates rather than duplicates.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from interfaces.hub_auth import require_hub_session
from interfaces.routes._stores import _get_hub_settings_store, _get_push_store

logger = logging.getLogger(__name__)

router = APIRouter()





@router.post("/api/push/subscribe")
async def api_push_subscribe(
    request: Request,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Validate and upsert a browser Web Push subscription (PUSH-01).

    POST /api/push/subscribe with body ``{subscription: {endpoint, keys:
    {p256dh, auth}}, user_agent}``.

    Input validation (ASVS V5 / T-29-11): ``endpoint`` must start with
    ``https://`` and ``keys.p256dh`` / ``keys.auth`` must both be present —
    the auth gate means only Amit can ever reach this route, but the endpoint
    is still attacker-shaped input (it's whatever the browser handed back
    from ``pushManager.subscribe``) so we validate before it touches
    Firestore.

    D-14: on the FIRST successful upsert (``HubSettingsStore.get()``'s
    ``push_enabled_at`` is unset/None) this stamps
    ``push_enabled_at=SERVER_TIMESTAMP`` — the heartbeat's anchor for
    detecting "push was enabled but zero subscriptions remain". Later
    subscribes (second device, re-subscribe after key rotation, etc.) leave
    it untouched.

    Returns:
        JSONResponse: ``{"ok": True}``
    Raises:
        HTTPException 400: endpoint is not https, or keys are missing (T-29-11).
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    body = await request.json()
    sub = body.get("subscription") or {}
    endpoint = sub.get("endpoint", "")
    keys = sub.get("keys") or {}
    user_agent = body.get("user_agent", "")

    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail={"error": "invalid subscription"})

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _get_push_store().upsert, sub, user_agent)

    # D-14: stamp push_enabled_at exactly once, on the first successful subscribe.
    settings_store = _get_hub_settings_store()
    settings = await loop.run_in_executor(None, settings_store.get)
    if not settings.get("push_enabled_at"):
        from google.cloud import firestore  # lazy import — mirrors memory/firestore_db.py

        await loop.run_in_executor(
            None, settings_store.set, {"push_enabled_at": firestore.SERVER_TIMESTAMP}
        )

    return JSONResponse(content={"ok": True})


@router.get("/api/push/vapid-public-key")
async def api_vapid_public_key(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Serve the VAPID application-server public key (PUSH-01).

    GET /api/push/vapid-public-key — the frontend passes this base64url key
    to ``pushManager.subscribe`` when registering a new subscription.

    Returns:
        JSONResponse: ``{"key": VAPID_PUBLIC_KEY}``
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    return JSONResponse(content={"key": os.environ["VAPID_PUBLIC_KEY"]})
