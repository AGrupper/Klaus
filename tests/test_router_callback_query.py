# tests/test_router_callback_query.py
"""RED tests for Phase 20 Plan 03:
  - send_and_inject accepts reply_markup + returns telegram.Message
  - MessageRouter dispatches callback_query updates (not dropped)
  - Unauthorised callback_query is rejected
  - Known prefixes (rpe:, watchoff:, skipreason:) are dispatched
  - Unknown prefix is logged + discarded, not raised
  - Existing text-message path is unaffected
  - reply_to_message triggers pending-note check path
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Fixtures / env setup                                                        #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def env(monkeypatch, isolated_modules):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")
    # The router resolves the handler via `import core.training_checkin as _checkin`,
    # which (CPython IMPORT_FROM) reads the `training_checkin` attribute on the `core`
    # package and only falls back to sys.modules if that attribute is absent. When an
    # earlier test imported the real module, that attribute is set, so a per-test
    # `patch.dict(sys.modules, {"core.training_checkin": fake})` would be bypassed.
    # Evict both here (restored by isolated_modules on teardown) so the patch wins.
    sys.modules.pop("core.training_checkin", None)
    core_pkg = sys.modules.get("core")
    if core_pkg is not None and hasattr(core_pkg, "training_checkin"):
        delattr(core_pkg, "training_checkin")


@pytest.fixture
def bot():
    b = AsyncMock()
    mock_msg = MagicMock()
    mock_msg.message_id = 42
    b.send_message = AsyncMock(return_value=mock_msg)
    return b


# --------------------------------------------------------------------------- #
# Task 1: send_and_inject — reply_markup pass-through + Message return        #
# --------------------------------------------------------------------------- #

def test_send_and_inject_passes_reply_markup_to_send_message(bot):
    """reply_markup kwarg is forwarded to bot.send_message."""
    from core.scheduled_message import send_and_inject
    kb = MagicMock(name="InlineKeyboardMarkup")
    result = asyncio.run(send_and_inject(bot, "Pick your RPE", reply_markup=kb))
    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Pick your RPE", reply_markup=kb
    )


def test_send_and_inject_returns_message(bot):
    """send_and_inject returns the telegram.Message from bot.send_message."""
    from core.scheduled_message import send_and_inject
    result = asyncio.run(send_and_inject(bot, "Test"))
    assert result is bot.send_message.return_value


def test_send_and_inject_returns_message_with_inject(bot):
    """Returns the Message even when inject_into_conversation=True."""
    fake_mod = types.ModuleType("memory.firestore_conversation")
    mock_store_instance = MagicMock()
    fake_mod.FirestoreConversationStore = MagicMock(return_value=mock_store_instance)

    with patch.dict(sys.modules, {"memory.firestore_conversation": fake_mod}):
        from core.scheduled_message import send_and_inject
        result = asyncio.run(
            send_and_inject(bot, "Inject me", inject_into_conversation=True)
        )
    assert result is bot.send_message.return_value


def test_send_and_inject_no_reply_markup_by_default(bot):
    """Existing callers (no reply_markup) still receive reply_markup=None in call."""
    from core.scheduled_message import send_and_inject
    asyncio.run(send_and_inject(bot, "Hello"))
    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Hello", reply_markup=None
    )


# --------------------------------------------------------------------------- #
# Task 2: Router — callback_query dispatch                                    #
# --------------------------------------------------------------------------- #

def _make_router():
    """Build a MessageRouter with stubbed orchestrator."""
    # Stub core.main so MessageRouter can import without real dependencies
    import importlib

    fake_orchestrator = MagicMock()
    fake_orchestrator.handle_message = MagicMock(return_value="ok")
    fake_orchestrator.conversation_manager = MagicMock()

    # Patch core.main so MessageRouter import is cheap
    with patch.dict(sys.modules, {"core.main": MagicMock()}):
        from interfaces._router import MessageRouter

    router = MessageRouter(
        orchestrator=fake_orchestrator,
        allowed_user_ids={123456},
    )
    return router, fake_orchestrator


def _make_callback_update(user_id: int, data: str) -> MagicMock:
    """Build a fake Update with callback_query set and message=None."""
    update = MagicMock()
    update.message = None  # callback_query updates have no .message
    cq = AsyncMock()
    cq.data = data
    cq.answer = AsyncMock()
    update.callback_query = cq
    user = MagicMock()
    user.id = user_id
    update.effective_user = user
    return update


def _make_message_update(user_id: int, text: str = "hello", reply_to=None) -> MagicMock:
    """Build a fake Update with a plain text message."""
    update = MagicMock()
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.photo = []
    msg.reply_to_message = reply_to
    msg.forward_origin = None
    msg.forward_date = None
    update.message = msg
    update.callback_query = None
    user = MagicMock()
    user.id = user_id
    update.effective_user = user
    return update


def test_callback_query_not_dropped():
    """callback_query from allowed user reaches _handle_callback_query (not silently dropped)."""
    router, _ = _make_router()
    router._handle_callback_query = AsyncMock()

    update = _make_callback_update(user_id=123456, data="rpe:2026-06-01_abc123:7")
    asyncio.run(router.handle_update(update))

    router._handle_callback_query.assert_awaited_once_with(update)


def test_callback_query_unauthorised_rejected():
    """callback_query from user NOT in allowed_user_ids is silently ignored."""
    router, _ = _make_router()
    router._handle_callback_query = AsyncMock()

    update = _make_callback_update(user_id=999999, data="rpe:2026-06-01_abc123:7")
    asyncio.run(router.handle_update(update))

    router._handle_callback_query.assert_not_awaited()


def test_callback_query_answers_spinner():
    """_handle_callback_query calls cq.answer() to clear the Telegram spinner."""
    router, _ = _make_router()

    # Stub training_checkin with a dummy handler
    fake_checkin = MagicMock()
    fake_checkin.handle_rpe_callback = AsyncMock()
    with patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        update = _make_callback_update(user_id=123456, data="rpe:2026-06-01_abc123:7")
        asyncio.run(router._handle_callback_query(update))

    update.callback_query.answer.assert_awaited_once()


def test_callback_query_dispatches_rpe_prefix():
    """rpe: prefix routes to handle_rpe_callback in core.training_checkin."""
    router, _ = _make_router()

    fake_checkin = MagicMock()
    fake_checkin.handle_rpe_callback = AsyncMock()
    fake_checkin.handle_watchoff_callback = AsyncMock()
    fake_checkin.handle_skipreason_callback = AsyncMock()
    with patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        update = _make_callback_update(user_id=123456, data="rpe:2026-06-01_abc123:7")
        asyncio.run(router._handle_callback_query(update))

    fake_checkin.handle_rpe_callback.assert_awaited_once()
    fake_checkin.handle_watchoff_callback.assert_not_awaited()
    fake_checkin.handle_skipreason_callback.assert_not_awaited()


def test_callback_query_dispatches_watchoff_prefix():
    """watchoff: prefix routes to handle_watchoff_callback."""
    router, _ = _make_router()

    fake_checkin = MagicMock()
    fake_checkin.handle_rpe_callback = AsyncMock()
    fake_checkin.handle_watchoff_callback = AsyncMock()
    fake_checkin.handle_skipreason_callback = AsyncMock()
    with patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        update = _make_callback_update(user_id=123456, data="watchoff:2026-06-01_abc123:done")
        asyncio.run(router._handle_callback_query(update))

    fake_checkin.handle_watchoff_callback.assert_awaited_once()
    fake_checkin.handle_rpe_callback.assert_not_awaited()


def test_callback_query_dispatches_skipreason_prefix():
    """skipreason: prefix routes to handle_skipreason_callback."""
    router, _ = _make_router()

    fake_checkin = MagicMock()
    fake_checkin.handle_rpe_callback = AsyncMock()
    fake_checkin.handle_watchoff_callback = AsyncMock()
    fake_checkin.handle_skipreason_callback = AsyncMock()
    with patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        update = _make_callback_update(user_id=123456, data="skipreason:2026-06-01_abc123:rest_recovery")
        asyncio.run(router._handle_callback_query(update))

    fake_checkin.handle_skipreason_callback.assert_awaited_once()
    fake_checkin.handle_rpe_callback.assert_not_awaited()


def test_callback_query_unknown_prefix_does_not_crash():
    """Unknown callback_data prefix is logged + discarded — no exception raised."""
    router, _ = _make_router()

    fake_checkin = MagicMock()
    fake_checkin.handle_rpe_callback = AsyncMock()
    fake_checkin.handle_watchoff_callback = AsyncMock()
    fake_checkin.handle_skipreason_callback = AsyncMock()
    with patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        update = _make_callback_update(user_id=123456, data="unknown:data")
        # Should not raise
        asyncio.run(router._handle_callback_query(update))

    fake_checkin.handle_rpe_callback.assert_not_awaited()
    fake_checkin.handle_watchoff_callback.assert_not_awaited()
    fake_checkin.handle_skipreason_callback.assert_not_awaited()


def test_callback_import_error_handled_gracefully():
    """If core.training_checkin is not yet importable, callback is answered + returns silently."""
    router, _ = _make_router()

    update = _make_callback_update(user_id=123456, data="rpe:2026-06-01_abc123:7")
    # Force ImportError by removing any existing stub
    modules_without_checkin = {k: v for k, v in sys.modules.items() if k != "core.training_checkin"}
    with patch.dict(sys.modules, {"core.training_checkin": None}, clear=False):
        # patch to raise ImportError
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "core.training_checkin":
                raise ImportError("not yet implemented")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Must not raise
            asyncio.run(router._handle_callback_query(update))

    # Spinner must still be answered
    update.callback_query.answer.assert_awaited_once()


def test_existing_text_message_path_unaffected():
    """A normal text message (no callback_query) still reaches _handle_text_message."""
    router, fake_orch = _make_router()
    router._handle_text_message = AsyncMock()

    update = _make_message_update(user_id=123456, text="Good morning")
    asyncio.run(router.handle_update(update))

    router._handle_text_message.assert_awaited_once()


def test_reply_to_message_routes_to_pending_note_check():
    """A text message with reply_to_message set triggers _check_pending_note_reply."""
    router, _ = _make_router()
    router._check_pending_note_reply = AsyncMock(return_value=True)
    router._handle_text_message = AsyncMock()

    reply_to = MagicMock()
    reply_to.message_id = 99
    update = _make_message_update(user_id=123456, text="My note text", reply_to=reply_to)

    asyncio.run(router.handle_update(update))

    router._check_pending_note_reply.assert_awaited_once_with(update)
    # _handle_text_message NOT called because _check_pending_note_reply returned True
    router._handle_text_message.assert_not_awaited()


def test_reply_to_message_falls_through_when_not_pending_note():
    """If _check_pending_note_reply returns False, the message falls through to normal handling."""
    router, _ = _make_router()
    router._check_pending_note_reply = AsyncMock(return_value=False)
    router._handle_text_message = AsyncMock()

    reply_to = MagicMock()
    reply_to.message_id = 99
    update = _make_message_update(user_id=123456, text="Not a note reply", reply_to=reply_to)

    asyncio.run(router.handle_update(update))

    router._check_pending_note_reply.assert_awaited_once_with(update)
    router._handle_text_message.assert_awaited_once()


def test_plain_typed_message_checks_pending_note_without_reply_gesture():
    """A plain text message (no reply gesture) still routes through the pending-
    note check first, so a typed answer to a prompt is captured."""
    router, _ = _make_router()
    router._check_pending_note_reply = AsyncMock(return_value=True)
    router._handle_text_message = AsyncMock()

    update = _make_message_update(user_id=123456, text="got home late", reply_to=None)
    asyncio.run(router.handle_update(update))

    router._check_pending_note_reply.assert_awaited_once_with(update)
    router._handle_text_message.assert_not_awaited()


def test_slash_skip_dismisses_open_pending_note():
    """'/skip' with an open session routes to _handle_skip_pending_note and not text."""
    router, _ = _make_router()
    router._handle_skip_pending_note = AsyncMock(return_value=True)
    router._handle_text_message = AsyncMock()

    update = _make_message_update(user_id=123456, text="/skip")
    asyncio.run(router.handle_update(update))

    router._handle_skip_pending_note.assert_awaited_once_with(123456)
    router._handle_text_message.assert_not_awaited()


def test_slash_skip_falls_through_without_open_session():
    """'/skip' with no open session falls through to normal handling."""
    router, _ = _make_router()
    router._handle_skip_pending_note = AsyncMock(return_value=False)
    router._handle_text_message = AsyncMock()

    update = _make_message_update(user_id=123456, text="/skip")
    asyncio.run(router.handle_update(update))

    router._handle_skip_pending_note.assert_awaited_once_with(123456)
    router._handle_text_message.assert_awaited_once()


def _patch_store(session):
    store = MagicMock()
    store.get_open_note_session.return_value = session
    return MagicMock(return_value=store)


def test_check_pending_note_reply_captures_plain_typed_skipreason_other():
    """Plain typed answer (no reply gesture) to an awaiting_skipreason_other
    session dispatches to attach_skipreason_other_note."""
    router, _ = _make_router()
    session = {
        "session_key": "2026-06-02_evt1",
        "state": "awaiting_skipreason_other",
        "message_id": 555,
        "event_date": "2026-06-02",
    }
    fake_checkin = MagicMock()
    fake_checkin.attach_skipreason_other_note = AsyncMock()
    fake_checkin.attach_note = AsyncMock()

    update = _make_message_update(user_id=123456, text="got home late", reply_to=None)
    with patch("memory.firestore_db.PendingPromptStore", _patch_store(session)), \
         patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        result = asyncio.run(router._check_pending_note_reply(update))

    assert result is True
    fake_checkin.attach_skipreason_other_note.assert_awaited_once()
    fake_checkin.attach_note.assert_not_awaited()


def test_check_pending_note_reply_captures_notes_state():
    """awaiting_notes session dispatches to attach_note."""
    router, _ = _make_router()
    session = {"session_key": "2026-06-02_evt1", "state": "awaiting_notes", "message_id": 9}
    fake_checkin = MagicMock()
    fake_checkin.attach_skipreason_other_note = AsyncMock()
    fake_checkin.attach_note = AsyncMock()

    update = _make_message_update(user_id=123456, text="felt great", reply_to=None)
    with patch("memory.firestore_db.PendingPromptStore", _patch_store(session)), \
         patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        result = asyncio.run(router._check_pending_note_reply(update))

    assert result is True
    fake_checkin.attach_note.assert_awaited_once()
    fake_checkin.attach_skipreason_other_note.assert_not_awaited()


def test_check_pending_note_reply_no_session_returns_false():
    """No open session → returns False so the message falls through to the brain."""
    router, _ = _make_router()
    fake_checkin = MagicMock()
    update = _make_message_update(user_id=123456, text="what's the weather", reply_to=None)
    with patch("memory.firestore_db.PendingPromptStore", _patch_store(None)), \
         patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        result = asyncio.run(router._check_pending_note_reply(update))

    assert result is False


def test_check_pending_note_reply_reply_gesture_requires_matching_message_id():
    """With an explicit reply gesture, a mismatched message_id is NOT captured
    (the user replied to some other/older message)."""
    router, _ = _make_router()
    session = {"session_key": "k", "state": "awaiting_notes", "message_id": 100}
    fake_checkin = MagicMock()
    fake_checkin.attach_note = AsyncMock()

    reply_to = MagicMock()
    reply_to.message_id = 999  # does not match session message_id 100
    update = _make_message_update(user_id=123456, text="note", reply_to=reply_to)
    with patch("memory.firestore_db.PendingPromptStore", _patch_store(session)), \
         patch.dict(sys.modules, {"core.training_checkin": fake_checkin}):
        result = asyncio.run(router._check_pending_note_reply(update))

    assert result is False
    fake_checkin.attach_note.assert_not_awaited()
