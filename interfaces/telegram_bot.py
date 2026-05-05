"""Telegram text-message interface for Klaus.

Receives text messages from the user, routes them through AgentOrchestrator,
and sends the JARVIS-style response back. Voice support is deferred to a
later phase (docs/PRD.md §3).

Only responds to Telegram user IDs listed in TELEGRAM_ALLOWED_USER_IDS —
unauthorized senders are silently ignored so the bot does not reveal its
existence to random users.

Entry point:
    python -m interfaces.telegram_bot
"""
from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from core.main import AgentOrchestrator

load_dotenv(override=True)

logger = logging.getLogger(__name__)


class TelegramBot:
    """Async Telegram bot that routes text messages to AgentOrchestrator."""

    def __init__(self, token: str, orchestrator: AgentOrchestrator,
                 allowed_user_ids: set[int]) -> None:
        """
        Args:
            token:            Telegram Bot API token from @BotFather.
            orchestrator:     Shared AgentOrchestrator instance.
            allowed_user_ids: Set of Telegram user IDs permitted to use the bot.
        """
        self.token = token
        self.orchestrator = orchestrator
        self.allowed_user_ids = allowed_user_ids

    async def _on_message(self, update: Update, context) -> None:
        """Handle an incoming text message."""
        user_id = update.effective_user.id

        # Silently drop unauthorized senders.
        # WHY: do not acknowledge the bot's existence to unknown users.
        if user_id not in self.allowed_user_ids:
            logger.warning("Unauthorized message from user_id=%d — ignored.", user_id)
            return

        user_text = update.message.text
        logger.info("Incoming message user_id=%d: %.100s", user_id, user_text)

        try:
            # WHY to_thread: handle_message is synchronous and makes multiple
            # blocking API calls (Claude + Gemini + Google APIs). Running it in
            # a thread prevents it from freezing the asyncio event loop, which
            # would make the bot unresponsive to other messages or Telegram keepalives.
            response = await asyncio.to_thread(
                self.orchestrator.handle_message, user_text, user_id
            )
        except Exception as exc:
            # WHY: a crash in the orchestrator must never silently drop the
            # message. Surface a brief error so the user knows to retry.
            logger.exception("Orchestrator raised an unexpected exception: %s", exc)
            response = (
                "I encountered an unexpected issue, Sir. "
                "Please try again in a moment."
            )

        await update.message.reply_text(response)

    async def _on_start(self, update: Update, context) -> None:
        """Handle the /start command."""
        if update.effective_user.id not in self.allowed_user_ids:
            return
        await update.message.reply_text("Klaus online, Sir.")

    async def _on_reset(self, update: Update, context) -> None:
        """Handle the /reset command — clears this user's conversation history."""
        user_id = update.effective_user.id
        if user_id not in self.allowed_user_ids:
            return
        self.orchestrator.conversation_manager.clear(user_id)
        await update.message.reply_text("Conversation history cleared, Sir.")

    def run(self) -> None:
        """Build the application and start long-polling."""
        app = Application.builder().token(self.token).build()

        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("reset", self._on_reset))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        logger.info("Klaus Telegram bot starting (long-poll mode)...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


# ------------------------------------------------------------------ #
# Entry point helpers                                                #
# ------------------------------------------------------------------ #

def _parse_allowed_user_ids() -> set[int]:
    """Parse TELEGRAM_ALLOWED_USER_IDS from the environment.

    Expects a comma-separated string of integer Telegram user IDs.
    Example: TELEGRAM_ALLOWED_USER_IDS=123456789,987654321

    Raises:
        ValueError: If the variable is missing or contains non-integer values.
    """
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if not raw:
        raise ValueError(
            "TELEGRAM_ALLOWED_USER_IDS is not set.\n"
            "Find your Telegram user ID via @userinfobot, then add it to .env:\n"
            "  TELEGRAM_ALLOWED_USER_IDS=123456789"
        )
    user_ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                user_ids.add(int(part))
            except ValueError:
                raise ValueError(
                    f"Invalid Telegram user ID '{part}' in TELEGRAM_ALLOWED_USER_IDS. "
                    "All IDs must be integers."
                )
    return user_ids


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    allowed_ids = _parse_allowed_user_ids()
    orchestrator = AgentOrchestrator()

    bot = TelegramBot(
        token=token,
        orchestrator=orchestrator,
        allowed_user_ids=allowed_ids,
    )
    bot.run()
