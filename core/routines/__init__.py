"""Routine coordination and the deterministic rules that run without Claude.

Klaus fires a Remote Routine at Claude and waits. If Claude misses the
deadline a deterministic fallback is published instead, because a routine
must never produce silence."""
