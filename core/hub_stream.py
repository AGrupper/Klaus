"""Throttled Firestore stream sink for hub streaming replies.

Bridges the Anthropic text stream (many delta callbacks per second) and the
HubStreamStore draft document (Firestore sustains ~1 write/sec per doc):
deltas accumulate in memory and flush at most once per ``min_write_interval``.
Each flush also reads back the stop button's ``cancel_requested`` flag — so
cancellation latency is bounded by the same interval.

Runs inside the Cloud Tasks worker's handle_message thread; all Firestore
calls here are synchronous by design.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

# Firestore sustained write limit is 1/sec per document; stay just above it.
DEFAULT_WRITE_INTERVAL_SECONDS = 1.0


class FirestoreStreamSink:
    """StreamSink implementation writing the draft to HubStreamStore."""

    def __init__(
        self,
        store,
        user_id: int,
        turn_id: str,
        min_write_interval: float = DEFAULT_WRITE_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._user_id = user_id
        self._turn_id = turn_id
        self._interval = min_write_interval
        self._clock = clock
        self._buffer = ""
        # Sentinel: first delta always flushes (shows "typing" fast).
        self._last_write: float | None = None

    @property
    def partial_text(self) -> str:
        return self._buffer

    def reset(self) -> None:
        """Discard the buffer at an iteration boundary (tool-round chatter)."""
        self._buffer = ""

    def delta(self, text: str) -> None:
        """Accumulate one chunk; flush + check the cancel flag when due.

        Raises:
            TurnCancelled: the user hit Stop — carries the accumulated partial.
        """
        self._buffer += text
        now = self._clock()
        if self._last_write is not None and now - self._last_write < self._interval:
            return
        self._last_write = now
        try:
            cancelled = self._store.write_draft(self._user_id, self._turn_id, self._buffer)
        except Exception:
            # A draft-write hiccup must never abort the reply itself.
            logger.warning("FirestoreStreamSink: draft flush failed", exc_info=True)
            return
        if cancelled:
            # Lazy import: keeps this module importable without dragging in the
            # full core.main dependency chain (also avoids a would-be cycle if
            # core.main ever needs this module).
            from core.main import TurnCancelled
            raise TurnCancelled(partial_text=self._buffer)
