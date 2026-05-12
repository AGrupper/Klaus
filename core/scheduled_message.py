# core/scheduled_message.py
"""Shared Telegram send + conversation-history injection for scheduled messages.

Used by core/proactive_alerts.py and core/morning_briefing.py.
Keeps the Telegram send + Firestore append in one place.
"""
from __future__ import annotations

import logging
import os

from telegram import Bot

logger = logging.getLogger(__name__)


def _telegram_user_id() -> int:
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)


async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
) -> None:
    """Send a Telegram message and optionally append it to conversation history.

    Args:
        bot:                      Telegram Bot instance.
        text:                     Message text to send.
        inject_into_conversation: If True, append the message as an 'assistant'
                                  turn in FirestoreConversationStore so the next
                                  user message is a natural follow-up.
    Raises:
        Exception: Re-raises Telegram send failures (callers should handle retry).
    """
    user_id = _telegram_user_id()
    await bot.send_message(chat_id=user_id, text=text)

    if not inject_into_conversation:
        return

    try:
        from memory.firestore_conversation import FirestoreConversationStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        store = FirestoreConversationStore(project_id=project_id, database=database)
        store.append(user_id, "assistant", text)
        logger.info("scheduled_message: injected into conversation for user_id=%d", user_id)
    except Exception:
        logger.warning(
            "scheduled_message: conversation injection failed — message still sent",
            exc_info=True,
        )
