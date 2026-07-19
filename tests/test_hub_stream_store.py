"""Tests for HubStreamStore — the hub streaming draft document.

One doc per user under collection 'hub_stream'. The Cloud Tasks worker writes
the accumulating draft (throttled to ~1/sec by the caller); the /api/chat
messages poll reads it; POST /api/chat/stop flips cancel_requested, which the
worker picks up on its next throttled write.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_store():
    # Import + patch on the LIVE module object: other test files replace
    # memory.firestore_db in sys.modules at collection time, so a module-level
    # import here could bind HubStreamStore from a different module object than
    # a string-target patch would hit (order-dependent full-suite failures).
    import memory.firestore_db as fdb

    with patch.object(fdb, "_make_firestore_client") as mock_make:
        client = MagicMock(name="firestore_client")
        mock_make.return_value = client
        store = fdb.HubStreamStore(project_id="test-project")
    doc_ref = client.collection.return_value.document.return_value
    return store, client, doc_ref


def test_start_turn_initializes_generating_doc():
    store, client, doc_ref = _make_store()
    store.start_turn(123456, "turn-abc")

    client.collection.assert_called_with("hub_stream")
    client.collection.return_value.document.assert_called_with("123456")
    payload = doc_ref.set.call_args.args[0]
    assert payload["turn_id"] == "turn-abc"
    assert payload["text"] == ""
    assert payload["status"] == "generating"
    assert payload["cancel_requested"] is False


def test_write_draft_updates_text_and_reports_cancel_flag():
    store, _client, doc_ref = _make_store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"turn_id": "turn-abc", "cancel_requested": True}
    doc_ref.get.return_value = snap

    cancelled = store.write_draft(123456, "turn-abc", "partial text so far")

    assert cancelled is True
    _args, kwargs = doc_ref.set.call_args
    assert _args[0]["text"] == "partial text so far"
    assert kwargs.get("merge") is True


def test_write_draft_returns_false_when_not_cancelled():
    store, _client, doc_ref = _make_store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"turn_id": "turn-abc", "cancel_requested": False}
    doc_ref.get.return_value = snap

    assert store.write_draft(123456, "turn-abc", "hi") is False


def test_finish_turn_marks_done_and_clears_text():
    store, _client, doc_ref = _make_store()
    store.finish_turn(123456, "turn-abc", status="done")
    payload = doc_ref.set.call_args.args[0]
    assert payload["status"] == "done"
    assert payload["text"] == ""


def test_request_cancel_sets_flag():
    store, _client, doc_ref = _make_store()
    store.request_cancel(123456)
    _args, kwargs = doc_ref.set.call_args
    assert _args[0]["cancel_requested"] is True
    assert kwargs.get("merge") is True


def test_get_draft_returns_doc_or_none():
    store, _client, doc_ref = _make_store()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "turn_id": "turn-abc", "text": "typing…", "status": "generating",
        "cancel_requested": False,
    }
    doc_ref.get.return_value = snap
    draft = store.get_draft(123456)
    assert draft == {"turn_id": "turn-abc", "text": "typing…", "status": "generating"}

    snap.exists = False
    assert store.get_draft(123456) is None


def test_read_failures_never_raise():
    """The poll path must never 500 because the draft read hiccuped."""
    store, _client, doc_ref = _make_store()
    doc_ref.get.side_effect = RuntimeError("firestore down")
    assert store.get_draft(123456) is None
    # write_draft reports "not cancelled" on read failure but still writes.
    assert store.write_draft(123456, "t", "text") is False
