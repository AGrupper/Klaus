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
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:fake-token")


@pytest.fixture(autouse=True)
def reset_module_singletons():
    """Reset the D-02 visibility gate + lazy-Bot singleton between tests so
    state from one test never leaks into another.
    """
    import core.scheduled_message as sm
    sm._chat_visible_until = 0.0
    sm._bot_instance = None
    yield
    sm._chat_visible_until = 0.0
    sm._bot_instance = None


@pytest.fixture(autouse=True)
def mock_hub_settings():
    """Default-mock HubSettingsStore so tests never hit real Firestore.

    Default: telegram_mirror_enabled=True (mirror ON) — matches the production
    default (D-08/D-09). Tests that need mirror OFF pass their own return_value.
    """
    mock_store = MagicMock()
    mock_store.get.return_value = {"telegram_mirror_enabled": True, "push_enabled_at": None}
    with patch("memory.firestore_db.HubSettingsStore", return_value=mock_store) as mock_cls:
        yield mock_store, mock_cls


@pytest.fixture(autouse=True)
def mock_send_push():
    """Default-mock core.push_sender.send_push_to_all so tests never hit real
    webpush / Secret Manager. The lazy `from core.push_sender import
    send_push_to_all` inside send_and_inject picks up this patched attribute.
    """
    with patch("core.push_sender.send_push_to_all") as mock_fn:
        mock_fn.return_value = {"sent": 1, "failed": 0, "removed": 0}
        yield mock_fn


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


# ---------------------------------------------------------------------------
# Pre-existing behavior — must still pass unchanged (backward compatibility)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Phase 29 (PUSH-02/03) — push fan-out + mirror gate + D-02 visibility gate
# ---------------------------------------------------------------------------

def test_mirror_on_pushes_and_sends_telegram(bot, mock_send_push):
    """Mirror ON (default): both push (via executor) AND Telegram fire."""
    from core.scheduled_message import send_and_inject
    asyncio.run(send_and_inject(bot, "Both channels", message_class="briefing"))

    mock_send_push.assert_called_once_with("Both channels", "briefing")
    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Both channels", reply_markup=None
    )


def test_mirror_off_skips_telegram_but_still_pushes(bot, mock_hub_settings, mock_send_push):
    """Mirror OFF: bot.send_message is NOT called; push + inject still run."""
    mock_store, _ = mock_hub_settings
    mock_store.get.return_value = {"telegram_mirror_enabled": False, "push_enabled_at": "2026-07-01T00:00:00+00:00"}

    mock_store_instance = MagicMock()
    MockConvStore = MagicMock(return_value=mock_store_instance)
    fake_mod = _make_fake_firestore_module(MockConvStore)

    with patch.dict(sys.modules, {"memory.firestore_conversation": fake_mod}):
        from core.scheduled_message import send_and_inject
        result = asyncio.run(
            send_and_inject(bot, "Push only", inject_into_conversation=True)
        )

    mock_send_push.assert_called_once_with("Push only", "default")
    bot.send_message.assert_not_called()
    mock_store_instance.append.assert_called_once_with(123456, "assistant", "Push only")
    assert result is None


def test_chat_visible_skips_push_but_mirror_still_sends(bot, mock_send_push):
    """is_chat_visible() True -> push is skipped; Telegram mirror still sends (D-02)."""
    from core.scheduled_message import mark_chat_visible, send_and_inject

    mark_chat_visible()
    asyncio.run(send_and_inject(bot, "Visible chat"))

    mock_send_push.assert_not_called()
    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Visible chat", reply_markup=None
    )


def test_push_false_skips_push_even_when_not_visible(bot, mock_send_push):
    """push=False opts a caller out of push fan-out entirely."""
    from core.scheduled_message import send_and_inject
    asyncio.run(send_and_inject(bot, "No push", push=False))

    mock_send_push.assert_not_called()
    bot.send_message.assert_called_once()


def test_push_failure_is_swallowed_not_raised(bot, mock_send_push):
    """D-04: a push exception must never propagate — Telegram send still happens."""
    mock_send_push.side_effect = Exception("webpush blew up")
    from core.scheduled_message import send_and_inject

    # Must not raise.
    asyncio.run(send_and_inject(bot, "Still delivered"))

    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Still delivered", reply_markup=None
    )


def test_hub_settings_lookup_failure_defaults_to_mirror_on(bot, mock_hub_settings, mock_send_push):
    """If HubSettingsStore.get() itself raises, default to mirror ON (fail open
    on the safe/visible side rather than silently going Telegram-dark)."""
    _, mock_cls = mock_hub_settings
    mock_cls.side_effect = Exception("Firestore unavailable")
    from core.scheduled_message import send_and_inject

    asyncio.run(send_and_inject(bot, "Fallback path"))

    bot.send_message.assert_called_once_with(
        chat_id=123456, text="Fallback path", reply_markup=None
    )


def test_none_bot_uses_lazy_bot_accessor(monkeypatch, mock_send_push):
    """bot=None (hub-reply caller) builds/reuses a module-level Bot via _get_bot()."""
    import core.scheduled_message as sm

    fake_bot_instance = AsyncMock()
    fake_bot_instance.send_message = AsyncMock()
    FakeBotClass = MagicMock(return_value=fake_bot_instance)
    monkeypatch.setattr(sm, "Bot", FakeBotClass)

    asyncio.run(sm.send_and_inject(None, "Hub reply text", message_class="chat_reply"))

    FakeBotClass.assert_called_once_with(token="1234:fake-token")
    fake_bot_instance.send_message.assert_called_once_with(
        chat_id=123456, text="Hub reply text", reply_markup=None
    )


def test_lazy_bot_is_reused_across_calls(monkeypatch, mock_send_push):
    """_get_bot() builds the Bot once and reuses it on subsequent None-bot calls."""
    import core.scheduled_message as sm

    fake_bot_instance = AsyncMock()
    fake_bot_instance.send_message = AsyncMock()
    FakeBotClass = MagicMock(return_value=fake_bot_instance)
    monkeypatch.setattr(sm, "Bot", FakeBotClass)

    asyncio.run(sm.send_and_inject(None, "first"))
    asyncio.run(sm.send_and_inject(None, "second"))

    FakeBotClass.assert_called_once_with(token="1234:fake-token")
    assert fake_bot_instance.send_message.call_count == 2


def test_mark_and_is_chat_visible():
    """Direct unit test of the D-02 visibility helpers."""
    from core.scheduled_message import is_chat_visible, mark_chat_visible

    mark_chat_visible(seconds=60)
    assert is_chat_visible() is True

    mark_chat_visible(seconds=-1)
    assert is_chat_visible() is False
