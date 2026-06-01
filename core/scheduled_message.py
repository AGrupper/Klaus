# core/scheduled_message.py
"""Shared Telegram send + conversation-history injection for scheduled messages.

Used by core/proactive_alerts.py and core/morning_briefing.py.
Keeps the Telegram send + Firestore append in one place.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from telegram import Bot

if TYPE_CHECKING:
    import telegram

logger = logging.getLogger(__name__)


def _telegram_user_id() -> int:
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)


async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,              # InlineKeyboardMarkup | None (Phase 20)
) -> "telegram.Message":
    """Send a Telegram message and optionally append it to conversation history.

    Args:
        bot:                      Telegram Bot instance.
        text:                     Message text to send.
        inject_into_conversation: If True, append the message as an 'assistant'
                                  turn in FirestoreConversationStore so the next
                                  user message is a natural follow-up.
        reply_markup:             Optional InlineKeyboardMarkup to attach to the
                                  message (Phase 20 — check-in inline keyboards).
                                  Keyword-only, defaults to None so existing callers
                                  are unaffected.

    Returns:
        The sent ``telegram.Message`` (message_id used for reply-to detection).

    Raises:
        Exception: Re-raises Telegram send failures (callers should handle retry).
    """
    user_id = _telegram_user_id()
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)

    if not inject_into_conversation:
        return msg

    try:
        from memory.firestore_conversation import FirestoreConversationStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        collection = os.getenv("FIRESTORE_COLLECTION_CONVERSATIONS", "conversations")
        store = FirestoreConversationStore(project_id=project_id, database=database, collection=collection)
        store.append(user_id, "assistant", text)
        logger.info("scheduled_message: injected into conversation for user_id=%d", user_id)
    except Exception:
        logger.warning(
            "scheduled_message: conversation injection failed — message still sent",
            exc_info=True,
        )
    return msg
