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
        # Five Fingers inline keyboard taps arrive as callback queries, not messages.
        if update.callback_query is not None:
            await self._handle_callback_query(update)
            return

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

        message_text = update.message.text or ""

        # Route slash commands before the general message path.
        if message_text == "/start":
            await self._handle_start(update, telegram_user_id)
        elif message_text == "/reset":
            await self._handle_reset(update, telegram_user_id)
        else:
            if getattr(update.message, 'forward_origin', None) or getattr(update.message, 'forward_date', None):
                message_text = f"[Forwarded Message]:\n{message_text}"
            await self._handle_text_message(update, telegram_user_id, message_text)

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

    async def _handle_callback_query(self, update: Update) -> None:
        """Handle Five Fingers inline keyboard taps.

        Two callback data shapes are recognised:
          ``ff_att|YYYY-MM-DD|roster_id|came|missed`` — mark attendance
          ``ff_save|YYYY-MM-DD``                      — confirm save

        Args:
            update: The originating Telegram Update (callback_query is not None).

        Returns:
            None — answers the callback query directly via Telegram.
        """
        query = update.callback_query
        data = query.data or ""

        if data.startswith("ff_att|"):
            parts = data.split("|")
            if len(parts) == 4:
                _, date_str, roster_id, status = parts
                try:
                    from core.tools import _get_attendance_store
                    _get_attendance_store().mark_attendance(date_str, roster_id, status)
                    symbol = "✅" if status == "came" else "❌"
                    await query.answer(symbol)
                except Exception as exc:
                    logger.exception(
                        "CallbackQuery ff_att failed for roster_id=%r: %s",
                        roster_id, exc,
                    )
                    await query.answer("שגיאה — נסה שוב")
            else:
                logger.warning("Malformed ff_att callback_data: %r", data)
                await query.answer()

        elif data.startswith("ff_save|"):
            await query.answer("נשמר ✓")

        else:
            logger.warning("Unrecognised callback_data: %r", data)
            await query.answer()

    async def _handle_text_message(
        self,
        update: Update,
        telegram_user_id: int,
        message_text: str,
    ) -> None:
        """Forward a plain text message to the orchestrator and reply with the result.

        Args:
            update:           The originating Telegram Update.
            telegram_user_id: Verified, allow-listed Telegram user ID.
            message_text:     Raw text content of the message.

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
