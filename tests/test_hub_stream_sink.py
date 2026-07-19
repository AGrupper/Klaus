"""Tests for core/hub_stream.py — the throttled Firestore stream sink.

The sink sits between the Anthropic stream (delta callbacks, many per second)
and the HubStreamStore draft doc (sustained write limit ~1/sec): it buffers
text and flushes at most once per interval, checking the stop button's
cancel flag on each flush.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _make_sink(interval: float = 1.0):
    # Lazy import (see test_hub_stream_store.py): keeps this module collectable
    # regardless of what earlier test files did to sys.modules.
    from core.hub_stream import FirestoreStreamSink

    store = MagicMock()
    store.write_draft.return_value = False
    clock = _FakeClock()
    sink = FirestoreStreamSink(
        store, user_id=123456, turn_id="turn-1",
        min_write_interval=interval, clock=clock,
    )
    return sink, store, clock


def test_writes_are_throttled_to_the_interval():
    sink, store, clock = _make_sink(interval=1.0)

    sink.delta("a")          # first delta flushes immediately
    sink.delta("b")          # 0s later — buffered only
    sink.delta("c")
    assert store.write_draft.call_count == 1

    clock.now += 1.1
    sink.delta("d")          # interval elapsed — flush accumulated text
    assert store.write_draft.call_count == 2
    assert store.write_draft.call_args.args == (123456, "turn-1", "abcd")


def test_cancel_flag_raises_turn_cancelled_with_partial():
    from core.main import TurnCancelled

    sink, store, clock = _make_sink(interval=1.0)
    sink.delta("first half")
    store.write_draft.return_value = True

    clock.now += 1.1
    with pytest.raises(TurnCancelled) as exc_info:
        sink.delta(" second")
    assert exc_info.value.partial_text == "first half second"


def test_reset_clears_buffer_between_iterations():
    sink, store, clock = _make_sink(interval=1.0)
    sink.delta("tool-round chatter")
    sink.reset()
    clock.now += 1.1
    sink.delta("real answer")
    assert store.write_draft.call_args.args == (123456, "turn-1", "real answer")
    assert sink.partial_text == "real answer"


def test_store_write_failure_never_kills_the_turn():
    """A Firestore hiccup on a draft flush must not abort the reply."""
    sink, store, clock = _make_sink(interval=1.0)
    store.write_draft.side_effect = RuntimeError("firestore down")
    sink.delta("still fine")  # must not raise
    assert sink.partial_text == "still fine"
