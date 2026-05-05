"""Telegram long-poll transport for Klaus.

Thin wrapper around python-telegram-bot that registers command/message
handlers and delegates every Update to ``MessageRouter``.  All routing
and orchestrator logic lives in ``interfaces._router`` so that the
upcoming Cloud Run webhook transport (``interfaces.web_server``) can
share the same path without duplication.

Voice support is deferred to a later phase (docs/PRD.md §3).

Entry point:
    python -m interfaces.telegram_bot
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from core.main import AgentOrchestrator
from interfaces._router import MessageRouter, parse_allowed_user_ids

load_dotenv(override=True)

logger = logging.getLogger(__name__)


class TelegramBot:
    """Async Telegram bot (long-poll mode) that delegates to MessageRouter.

    Constructs a ``MessageRouter`` internally and wires it to
    python-telegram-bot handlers.  The ``run()`` method is the only
    transport-specific logic that lives here.

    Args:
        token:            Telegram Bot API token from @BotFather.
        orchestrator:     Shared ``AgentOrchestrator`` instance.
        allowed_user_ids: Set of Telegram user IDs permitted to use the bot.
    """

    def __init__(
        self,
        token: str,
        orchestrator: AgentOrchestrator,
        allowed_user_ids: set[int],
    ) -> None:
        self.token = token

        # WHY: construct MessageRouter here (not in run()) so the same router
        # instance is reused across all handler invocations, preserving any
        # future per-instance state without leaking transport details upward.
        self._router = MessageRouter(
            orchestrator=orchestrator,
            allowed_user_ids=allowed_user_ids,
        )

    # ------------------------------------------------------------------ #
    # Handler shims — thin one-liners that call into MessageRouter       #
    # ------------------------------------------------------------------ #

    async def _on_start(self, update: Update, context) -> None:
        """Handle the /start command by delegating to MessageRouter.

        Args:
            update:  Incoming Telegram Update.
            context: python-telegram-bot callback context (unused here).
        """
        await self._router.handle_update(update)

    async def _on_reset(self, update: Update, context) -> None:
        """Handle the /reset command by delegating to MessageRouter.

        Args:
            update:  Incoming Telegram Update.
            context: python-telegram-bot callback context (unused here).
        """
        await self._router.handle_update(update)

    async def _on_message(self, update: Update, context) -> None:
        """Handle a plain text message by delegating to MessageRouter.

        Args:
            update:  Incoming Telegram Update.
            context: python-telegram-bot callback context (unused here).
        """
        await self._router.handle_update(update)

    # ------------------------------------------------------------------ #
    # Long-poll entry-point                                              #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Build the python-telegram-bot Application and start long-polling.

        Registers handlers for /start, /reset, and plain text messages,
        then blocks until interrupted.
        """
        app = Application.builder().token(self.token).build()

        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("reset", self._on_reset))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        logger.info("Klaus Telegram bot starting (long-poll mode)...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


# ------------------------------------------------------------------ #
# Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    telegram_bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    allowed_ids = parse_allowed_user_ids()
    orchestrator = AgentOrchestrator()

    bot = TelegramBot(
        token=telegram_bot_token,
        orchestrator=orchestrator,
        allowed_user_ids=allowed_ids,
    )
    bot.run()
