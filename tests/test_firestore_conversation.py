"""Tests for FirestoreConversationStore session-window behaviour (CR-02).

get() returns the active LLM-context window (active session only; [] after the
idle timeout — the bounded context the agent relies on). get_full() returns the
entire stored history regardless of idle, so the hub renders one continuous
conversation. Verified against a mocked Firestore client.

Test isolation: stubs google.cloud.firestore + google.api_core.exceptions into
sys.modules and flushes memory.firestore_conversation; each test opts into the
conftest `isolated_modules` fixture so sys.modules is restored on teardown.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import MagicMock


def _install_firestore_mock() -> None:
    """Stub google.cloud.firestore + google.api_core.exceptions, then flush
    memory.firestore_conversation so it re-imports against the stubs."""
    for name in ("google", "google.cloud"):
        if name not in sys.modules or isinstance(sys.modules.get(name), MagicMock):
            mod = ModuleType(name)
            mod.__path__ = []  # mark as a package
            sys.modules[name] = mod

    firestore_mock = MagicMock()
    firestore_mock.SERVER_TIMESTAMP = object()
    # @firestore.transactional must be a pass-through decorator at import time.
    firestore_mock.transactional = lambda fn: fn
    sys.modules["google.cloud.firestore"] = firestore_mock
    sys.modules["google.cloud"].firestore = firestore_mock

    api_core = ModuleType("google.api_core")
    exc = ModuleType("google.api_core.exceptions")
    exc.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})  # type: ignore[attr-defined]
    sys.modules["google.api_core"] = api_core
    sys.modules["google.api_core.exceptions"] = exc

    sys.modules.pop("memory.firestore_conversation", None)


def _store_with_doc(doc: dict):
    from memory.firestore_conversation import FirestoreConversationStore  # noqa: PLC0415

    store = FirestoreConversationStore(project_id="p", database="(default)")
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = doc
    store._col.document.return_value.get.return_value = snap
    return store


_RECENT = datetime.now(timezone.utc)
_IDLE = datetime.now(timezone.utc) - timedelta(hours=10)
_MSGS = [
    {"role": "user", "content": "a"},
    {"role": "assistant", "content": "b"},
    {"role": "user", "content": "c"},
]


def test_get_returns_active_session_window(monkeypatch, isolated_modules):
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store = _store_with_doc(
        {"messages": _MSGS, "session_start_index": 2, "updated_at": _RECENT}
    )
    # The agent's active context window starts at the session boundary.
    assert store.get(1) == [{"role": "user", "content": "c"}]


def test_get_returns_empty_after_idle_timeout(monkeypatch, isolated_modules):
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store = _store_with_doc(
        {"messages": _MSGS, "session_start_index": 0, "updated_at": _IDLE}
    )
    # Idle beyond the timeout → bounded context is empty until the next append.
    assert store.get(1) == []


def test_get_full_returns_entire_history_even_after_idle(monkeypatch, isolated_modules):
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store = _store_with_doc(
        {"messages": _MSGS, "session_start_index": 2, "updated_at": _IDLE}
    )
    # The hub shows the whole conversation regardless of idle (CR-02).
    assert store.get_full(1) == _MSGS


# ---------------------------------------------------------------------------
# pop_trailing_assistant (hub regenerate feature)
# ---------------------------------------------------------------------------

def _store_for_pop(doc: dict):
    """Store whose transactional pop helper sees `doc` and records the write."""
    from memory.firestore_conversation import FirestoreConversationStore  # noqa: PLC0415

    store = FirestoreConversationStore(project_id="p", database="(default)")
    snap = MagicMock()
    snap.exists = doc is not None
    snap.to_dict.return_value = doc
    doc_ref = store._col.document.return_value
    doc_ref.get.return_value = snap
    return store, doc_ref


def test_pop_trailing_assistant_removes_reply_and_returns_user_text(
    monkeypatch, isolated_modules,
):
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store, doc_ref = _store_for_pop({
        "messages": [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ],
        "session_start_index": 0,
        "updated_at": _RECENT,
    })

    result = store.pop_trailing_assistant(1)

    assert result == "q2"
    # The transactional write (transaction.set(doc_ref, payload), mirroring
    # _txn_append) drops only the trailing assistant message.
    txn = store._client.transaction.return_value
    written = txn.set.call_args.args[1]
    assert written["messages"] == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]


def test_pop_trailing_assistant_noops_when_last_is_user(
    monkeypatch, isolated_modules,
):
    """A turn is already in flight (last message is the user's) — nothing to
    regenerate; must not mutate history."""
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store, doc_ref = _store_for_pop({
        "messages": [{"role": "user", "content": "pending"}],
        "session_start_index": 0,
        "updated_at": _RECENT,
    })

    assert store.pop_trailing_assistant(1) is None
    store._client.transaction.return_value.set.assert_not_called()


def test_pop_trailing_assistant_noops_on_empty_history(
    monkeypatch, isolated_modules,
):
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store, doc_ref = _store_for_pop({
        "messages": [], "session_start_index": 0, "updated_at": _RECENT,
    })
    assert store.pop_trailing_assistant(1) is None
    store._client.transaction.return_value.set.assert_not_called()
