# tests/test_scheduled_message.py
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")


@pytest.fixture
def bot():
    b = AsyncMock()
    b.send_message = AsyncMock()
    return b


def _make_fake_firestore_module(store_class):
    """Build a minimal fake memory.firestore_conversation module.

    memory.firestore_conversation is not importable in the test environment
    (google-cloud-firestore is not installed), so we inject a fake module into
    sys.modules before the lazy import inside send_and_inject fires.
    """
    fake_mod = types.ModuleType("memory.firestore_conversation")
    fake_mod.FirestoreConversationStore = store_class
    return fake_mod


def test_sends_telegram_message(bot):
    from core.scheduled_message import send_and_inject
    asyncio.run(send_and_inject(bot, "Hello, sir."))
    # Phase 20: reply_markup=None is now passed through (backward-compatible default)
    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Hello, sir.", reply_markup=None
    )


def test_no_conversation_inject_by_default(bot):
    """With inject_into_conversation=False (default), we return early before the
    lazy import of FirestoreConversationStore. Verify only send_message is called;
    if Firestore were touched it would raise (not mocked), failing the test."""
    from core.scheduled_message import send_and_inject
    asyncio.run(send_and_inject(bot, "Hello"))
    # Phase 20: reply_markup=None is now forwarded to bot.send_message
    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Hello", reply_markup=None
    )


def test_injects_into_conversation_when_flag_set(bot):
    mock_store_instance = MagicMock()
    MockStore = MagicMock(return_value=mock_store_instance)
    fake_mod = _make_fake_firestore_module(MockStore)

    # Inject the fake module so the lazy `from memory.firestore_conversation
    # import FirestoreConversationStore` inside send_and_inject resolves it.
    with patch.dict(sys.modules, {"memory.firestore_conversation": fake_mod}):
        from core.scheduled_message import send_and_inject
        asyncio.run(send_and_inject(bot, "Briefing text", inject_into_conversation=True))

    mock_store_instance.append.assert_called_once_with(123456, "assistant", "Briefing text")


def test_injection_failure_does_not_raise(bot):
    """If conversation injection fails, the message was still sent — no re-raise."""
    MockStore = MagicMock(side_effect=Exception("Firestore down"))
    fake_mod = _make_fake_firestore_module(MockStore)

    with patch.dict(sys.modules, {"memory.firestore_conversation": fake_mod}):
        from core.scheduled_message import send_and_inject
        # Must not raise even though FirestoreConversationStore() blows up.
        asyncio.run(send_and_inject(bot, "Briefing", inject_into_conversation=True))

    bot.send_message.assert_called_once()
