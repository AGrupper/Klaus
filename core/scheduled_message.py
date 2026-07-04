# core/scheduled_message.py
"""Shared Telegram send + conversation-history injection for scheduled messages.

Used by core/proactive_alerts.py and core/morning_briefing.py, and (Phase 29)
by every outbound Klaus send path — proactive crons, hub chat replies, and
Telegram-turn replies — so push fan-out + the Telegram-mirror flag are
handled in exactly one place.

Phase 29 (PUSH-02/03): every send now fans out a Web Push (unless the hub
chat view was recently reported visible — the D-02 gate) and mirrors to
Telegram only while HubSettingsStore.telegram_mirror_enabled is True, at
full volume (D-10 — never disable_notification).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from telegram import Bot

if TYPE_CHECKING:
    import telegram

logger = logging.getLogger(__name__)


def _telegram_user_id() -> int:
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)


# ---------------------------------------------------------------------------
# D-02 in-hub chat-visibility gate — an in-process module variable (RESEARCH
# A5: single Cloud Run instance). NOT persisted to Firestore — see
# memory.firestore_db.HubSettingsStore docstring for why a stored
# chat_visible_until would be stale/misleading across instance restarts.
#
# mark_chat_visible() is called by GET /api/chat/messages
# (interfaces/web_server.py) whenever the client reports chat_visible=1 —
# refreshed on every 2.5s poll while the hub chat view is on-screen.
# ---------------------------------------------------------------------------

_chat_visible_until: float = 0.0


def mark_chat_visible(seconds: float = 8) -> None:
    """Mark the hub chat view as visible for `seconds` (default 8s — comfortably
    longer than the 2.5s poll cadence so back-to-back polls keep the window open).
    """
    global _chat_visible_until
    _chat_visible_until = time.monotonic() + seconds


def is_chat_visible() -> bool:
    """Return True if the hub chat view was reported visible within the window."""
    return time.monotonic() < _chat_visible_until


# ---------------------------------------------------------------------------
# Lazy module-level Bot accessor — lets callers without a bot instance (e.g.
# hub replies in interfaces/web_server.py::internal_process_hub_message)
# reuse this same send_and_inject delivery path instead of building their own
# Bot / Application.
# ---------------------------------------------------------------------------

_bot_instance: Bot | None = None


def _get_bot() -> Bot:
    """Return a lazily-constructed, process-wide Bot built from TELEGRAM_BOT_TOKEN."""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    return _bot_instance


# ---------------------------------------------------------------------------
# Lazy module-level HubSettingsStore accessor (CR-01) — mirrors _bot_instance:
# constructing a firestore.Client is expensive (credential resolution +
# channel setup), so build the store once per process instead of once per
# send. On construction failure nothing is cached, so the next send retries.
# ---------------------------------------------------------------------------

_hub_settings_store = None


def _get_hub_settings_store():
    """Return a lazily-constructed, process-wide HubSettingsStore."""
    global _hub_settings_store
    if _hub_settings_store is None:
        from memory.firestore_db import HubSettingsStore
        _hub_settings_store = HubSettingsStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
    return _hub_settings_store


def _load_hub_settings() -> dict:
    """SYNC — blocking gRPC Firestore read. Call ONLY via loop.run_in_executor
    (CR-01 / CLAUDE.md invariant: never block the event loop)."""
    return _get_hub_settings_store().get()


async def send_and_inject(
    bot: "Bot | None",
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,              # InlineKeyboardMarkup | None (Phase 20)
    message_class: str = "default",  # Phase 29 — CLASS_TTL selector (D-07)
    push: bool = True,               # Phase 29 — fan out a Web Push (PUSH-02)
) -> "telegram.Message | None":
    """Fan out a push, mirror to Telegram behind the flag, and optionally inject
    into conversation history.

    Order (Phase 29 / D-01..D-10): push (unless the hub chat is visible) ->
    Telegram send (only while telegram_mirror_enabled) -> conversation inject.

    Args:
        bot:                      Telegram Bot instance, or None to lazily build/
                                   reuse a module-level Bot via _get_bot() (hub
                                   replies have no bot instance of their own).
        text:                     Message text to send.
        inject_into_conversation: If True, append the message as an 'assistant'
                                  turn in FirestoreConversationStore so the next
                                  user message is a natural follow-up.
        reply_markup:             Optional InlineKeyboardMarkup to attach to the
                                  message (Phase 20 — check-in inline keyboards).
                                  Keyword-only, defaults to None so existing callers
                                  are unaffected.
        message_class:            Selects the push TTL bucket (core.push_sender
                                  .CLASS_TTL, D-07). Keyword-only, default "default".
        push:                     Whether to fan out a Web Push at all. Keyword-only,
                                  default True. Set False for callers that should
                                  never push (none currently — reserved for future
                                  callers).

    Returns:
        The sent ``telegram.Message``, or None if the Telegram mirror was
        skipped (telegram_mirror_enabled is False).

    Raises:
        Exception: Re-raises Telegram send failures (callers should handle retry).
                   Push failures are logged and swallowed (D-04) — they never
                   raise and never block the Telegram/inject steps.
    """
    user_id = _telegram_user_id()
    loop = asyncio.get_running_loop()

    # CR-01: HubSettingsStore.get() is a blocking gRPC Firestore read — running
    # it inline would block the event loop on EVERY outbound send (the exact
    # bug class behind the weekly-review-500 and 18-minute-reply incidents;
    # CLAUDE.md invariant: never block the event loop). Off-load it to a
    # thread, same as the push fan-out below.
    try:
        settings = await loop.run_in_executor(None, _load_hub_settings)
    except Exception:
        logger.warning(
            "scheduled_message: HubSettingsStore.get() failed — defaulting to mirror ON",
            exc_info=True,
        )
        settings = {"telegram_mirror_enabled": True}

    if push and not is_chat_visible():
        try:
            from core.push_sender import send_push_to_all
            await loop.run_in_executor(None, send_push_to_all, text, message_class)
        except Exception:
            # D-04: push failures are logged and swallowed, never raised — the
            # message is never lost, the Telegram mirror + Firestore
            # conversation remain the record.
            logger.warning("scheduled_message: push fan-out failed", exc_info=True)

    msg = None
    if settings.get("telegram_mirror_enabled", True):
        if bot is None:
            bot = _get_bot()
        # D-10: full volume, never disable_notification, while the mirror is on.
        msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)

    if not inject_into_conversation:
        return msg

    # CR-01 (pre-existing Phase-18 instance of the same defect): the
    # conversation append is also a blocking Firestore write — off-load it too.
    def _inject() -> None:
        from memory.firestore_conversation import FirestoreConversationStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        collection = os.getenv("FIRESTORE_COLLECTION_CONVERSATIONS", "conversations")
        store = FirestoreConversationStore(project_id=project_id, database=database, collection=collection)
        store.append(user_id, "assistant", text)

    try:
        await loop.run_in_executor(None, _inject)
        logger.info("scheduled_message: injected into conversation for user_id=%d", user_id)
    except Exception:
        logger.warning(
            "scheduled_message: conversation injection failed — message still sent",
            exc_info=True,
        )
    return msg
