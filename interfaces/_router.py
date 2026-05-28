"""Transport-agnostic message router for Klaus.

Centralises the routing logic — allow-list enforcement, command handling,
and orchestrator delegation — so multiple transports (Telegram long-poll,
Cloud Run webhook) can share it without duplicating code.

Usage:
    router = MessageRouter(orchestrator=orchestrator, allowed_user_ids={12345})
    await router.handle_update(update)   # called by any transport layer
"""
from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update

from core.main import AgentOrchestrator

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes an incoming Telegram Update through allow-list → command/message handler.

    This class is intentionally transport-agnostic: it depends only on the
    python-telegram-bot ``Update`` object (which is a plain data class) and the
    ``AgentOrchestrator``.  Transport concerns (long-poll vs. webhook) live
    entirely in the caller.

    Args:
        orchestrator:     Shared ``AgentOrchestrator`` instance.
        allowed_user_ids: Set of Telegram user IDs permitted to interact with Klaus.
                          All other senders are silently ignored so the bot does not
                          reveal its existence to random users.
    """

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        allowed_user_ids: set[int],
    ) -> None:
        self.orchestrator = orchestrator
        self.allowed_user_ids = allowed_user_ids

    # ------------------------------------------------------------------ #
    # Public dispatch entry-point                                        #
    # ------------------------------------------------------------------ #

    async def handle_update(self, update: Update) -> None:
        """Dispatch a Telegram Update to the correct internal handler.

        Silently drops updates from users not in the allow-list.
        Routes ``/start`` and ``/reset`` commands; everything else is
        treated as a plain text message and forwarded to the orchestrator.

        Args:
            update: A python-telegram-bot ``Update`` object (long-poll or webhook).

        Returns:
            None — responses are sent directly via ``update.message.reply_text``.
        """
        # Guard: ignore updates that carry no message (e.g. channel posts, edits).
        if update.message is None:
            return

        telegram_user_id = update.effective_user.id

        # WHY: silently drop unauthorised senders — replying with an error would
        # reveal the bot's existence to random users who stumble upon it.
        if telegram_user_id not in self.allowed_user_ids:
            logger.warning(
                "Unauthorised update from user_id=%d — silently ignored.",
                telegram_user_id,
            )
            return

        message_text = update.message.text or update.message.caption or ""

        photo_bytes = None
        photo_mime_type = None

        if update.message.photo:
            try:
                # get the largest photo size
                photo = update.message.photo[-1]
                file = await photo.get_file()
                photo_bytes = bytes(await file.download_as_bytearray())
                photo_mime_type = "image/jpeg"
                logger.info("Successfully downloaded photo, size=%d bytes", len(photo_bytes))
            except Exception as e:
                logger.exception("Failed to download Telegram photo: %s", e)

        # Route slash commands before the general message path.
        if message_text == "/start":
            await self._handle_start(update, telegram_user_id)
        elif message_text == "/reset":
            await self._handle_reset(update, telegram_user_id)
        else:
            if getattr(update.message, 'forward_origin', None) or getattr(update.message, 'forward_date', None):
                message_text = f"[Forwarded Message]:\n{message_text}"
            await self._handle_text_message(
                update,
                telegram_user_id,
                message_text,
                photo_bytes=photo_bytes,
                photo_mime_type=photo_mime_type,
            )

    # ------------------------------------------------------------------ #
    # Internal handlers                                                  #
    # ------------------------------------------------------------------ #

    async def _handle_start(self, update: Update, telegram_user_id: int) -> None:
        """Handle the /start command — confirms the bot is online.

        Args:
            update:           The originating Telegram Update.
            telegram_user_id: Verified, allow-listed Telegram user ID.

        Returns:
            None — sends reply directly via Telegram.
        """
        logger.info("/start received from user_id=%d.", telegram_user_id)
        await update.message.reply_text("Klaus online, Sir.")

    async def _handle_reset(self, update: Update, telegram_user_id: int) -> None:
        """Handle the /reset command — clears this user's conversation history.

        Args:
            update:           The originating Telegram Update.
            telegram_user_id: Verified, allow-listed Telegram user ID.

        Returns:
            None — sends reply directly via Telegram.
        """
        logger.info("/reset received from user_id=%d.", telegram_user_id)

        # WHY: clearing history lets the user start a fresh session when the
        # model has drifted or accumulated stale context.
        self.orchestrator.conversation_manager.clear(telegram_user_id)
        await update.message.reply_text("Conversation history cleared, Sir.")

    async def _handle_text_message(
        self,
        update: Update,
        telegram_user_id: int,
        message_text: str,
        photo_bytes: bytes | None = None,
        photo_mime_type: str | None = None,
    ) -> None:
        """Forward a message (text and optional photo) to the orchestrator and reply.

        Args:
            update:           The originating Telegram Update.
            telegram_user_id: Verified, allow-listed Telegram user ID.
            message_text:     Raw text content or caption of the message.
            photo_bytes:      Optional raw bytes of the downloaded photo.
            photo_mime_type:  Optional MIME type of the downloaded photo.

        Returns:
            None — sends reply directly via Telegram.
        """
        logger.info(
            "Incoming message user_id=%d: %.100s",
            telegram_user_id,
            message_text,
        )

        try:
            # WHY asyncio.to_thread: handle_message is synchronous and makes
            # multiple blocking API calls (Claude + Gemini + Google APIs).
            # Running it in a thread prevents freezing the asyncio event loop,
            # which would make the bot unresponsive to other messages or
            # Telegram keep-alives while the orchestrator is working.
            orchestrator_response = await asyncio.to_thread(
                self.orchestrator.handle_message,
                message_text,
                telegram_user_id,
                photo_bytes,
                photo_mime_type,
            )
        except Exception as exc:
            # WHY: a crash in the orchestrator must never silently discard the
            # user's message.  Surface a short error so the user knows to retry.
            logger.exception(
                "Orchestrator raised an unexpected exception for user_id=%d: %s",
                telegram_user_id,
                exc,
            )
            orchestrator_response = (
                "I encountered an unexpected issue, Sir. "
                "Please try again in a moment."
            )

        await update.message.reply_text(orchestrator_response)


# ------------------------------------------------------------------ #
# Module-level utility                                               #
# ------------------------------------------------------------------ #

def parse_allowed_user_ids() -> set[int]:
    """Parse TELEGRAM_ALLOWED_USER_IDS from the environment.

    Expects a comma-separated string of integer Telegram user IDs.
    Example env var:  TELEGRAM_ALLOWED_USER_IDS=123456789,987654321

    Returns:
        A set of integer Telegram user IDs.

    Raises:
        ValueError: If the variable is missing or any token is not a valid integer.
    """
    raw_env_value = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()

    if not raw_env_value:
        raise ValueError(
            "TELEGRAM_ALLOWED_USER_IDS is not set.\n"
            "Find your Telegram user ID via @userinfobot, then add it to .env:\n"
            "  TELEGRAM_ALLOWED_USER_IDS=123456789"
        )

    parsed_user_ids: set[int] = set()
    for token in raw_env_value.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            parsed_user_ids.add(int(token))
        except ValueError:
            raise ValueError(
                f"Invalid Telegram user ID '{token}' in TELEGRAM_ALLOWED_USER_IDS. "
                "All IDs must be integers."
            )

    return parsed_user_ids
