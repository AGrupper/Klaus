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

        Phase 20: dispatches inline-keyboard callback_query updates BEFORE
        the message guard so button taps are not silently dropped (Pitfall 2).

        Args:
            update: A python-telegram-bot ``Update`` object (long-poll or webhook).

        Returns:
            None — responses are sent directly via ``update.message.reply_text``
            or ``cq.answer()`` + follow-up messages.
        """
        # Phase 20: dispatch inline-keyboard button taps before the message guard.
        # WHY: callback_query updates have update.message=None, so the guard below
        # would silently drop them (Pitfall 2). T-20-04 access control: check
        # allowed_user_ids BEFORE dispatching any callback.
        if update.callback_query is not None:
            if (
                update.effective_user is None
                or update.effective_user.id not in self.allowed_user_ids
            ):
                logger.warning("Unauthorised callback_query — silently ignored.")
                return
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

        # Phase 20: reply-to detection for notes step.
        # WHY: when the user replies to a pending notes prompt, the message carries
        # reply_to_message with the message_id of the prompt we sent.  We route this
        # to the pending-note path BEFORE the normal command/text path.
        if update.message.reply_to_message is not None:
            handled = await self._check_pending_note_reply(update)
            if handled:
                return
            # else fall through to normal text handling

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

    async def _handle_callback_query(self, update: Update) -> None:
        """Dispatch an inline-keyboard button tap.

        Phase 20 — T-20-04/T-20-05 mitigations:
        - Allow-list guard is enforced in ``handle_update`` before this method.
        - cq.answer() is called immediately to clear the Telegram spinner.
        - Dispatch is restricted to known prefixes; unknown prefix is logged
          + discarded (no crash, T-20-05 input validation).
        - core.training_checkin is imported lazily so this plan ships
          independently of Plan 04 (lazy import + ImportError guard).

        Args:
            update: Telegram Update carrying a non-None ``callback_query``.
        """
        cq = update.callback_query
        await cq.answer()                       # dismiss the Telegram spinner immediately
        data = cq.data or ""
        user_id = update.effective_user.id

        try:
            import core.training_checkin as _checkin
        except ImportError:
            logger.warning(
                "training_checkin module unavailable for callback %r — Plan 04 not yet deployed",
                data,
            )
            return

        if data.startswith("rpe:"):
            await _checkin.handle_rpe_callback(self.orchestrator, user_id, cq, data)
        elif data.startswith("watchoff:"):
            await _checkin.handle_watchoff_callback(self.orchestrator, user_id, cq, data)
        elif data.startswith("skipreason:"):
            await _checkin.handle_skipreason_callback(self.orchestrator, user_id, cq, data)
        else:
            logger.warning("training_checkin: unknown callback_data=%r", data)

    async def _check_pending_note_reply(self, update: Update) -> bool:
        """Check whether a reply-to message matches a pending notes session.

        Phase 20: when a user replies to the notes prompt Klaus sent, we detect
        it here via ``reply_to_message.message_id`` and route the text to
        ``core.training_checkin.attach_note``.

        Args:
            update: Telegram Update whose ``message.reply_to_message`` is not None.

        Returns:
            True if the reply was handled (caller should return); False to fall
            through to normal text handling.
        """
        try:
            replied_to_id = update.message.reply_to_message.message_id

            from memory.firestore_db import PendingPromptStore
            project_id = os.environ["GCP_PROJECT_ID"]
            database = os.getenv("FIRESTORE_DATABASE", "(default)")
            store = PendingPromptStore(project_id=project_id, database=database)

            user_id = update.effective_user.id
            session = store.get_open_note_session(user_id)
            if session is None:
                return False

            # Match by message_id
            if session.get("message_id") != replied_to_id:
                return False

            # Route to attach_note — lazy import so Plan 03 ships independently
            try:
                import core.training_checkin as _checkin
            except ImportError:
                logger.warning(
                    "_check_pending_note_reply: training_checkin module unavailable"
                )
                return False

            note_text = update.message.text or update.message.caption or ""
            await _checkin.attach_note(self.orchestrator, user_id, session, note_text)
            return True

        except Exception:
            logger.warning(
                "_check_pending_note_reply: unexpected error — falling through",
                exc_info=True,
            )
            return False

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
