"""Shared, cached prompt-file loader.

Prompt files under ``prompts/`` change only on deploy (a new container image),
so re-reading them from disk on every call — the autonomous tick previously
loaded three prompt files from disk on every compose, 43 ticks a day — is
wasted I/O. ``functools.lru_cache`` gives an unbounded-TTL in-process cache,
which is exactly right for files that are immutable for the lifetime of the
process.

Tests that need to observe fresh disk reads can call
``load_prompt.cache_clear()``.
"""

from __future__ import annotations

import functools
from pathlib import Path


@functools.lru_cache(maxsize=32)
def load_prompt(relative_path: str) -> str:
    """Load a prompt file by project-root-relative path, cached per process.

    Cloud Run sets CWD to ``/workspace`` (the project root); local dev runs
    from the project root too, so a relative path resolves identically in
    both environments.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = Path(relative_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path.resolve()}. "
            "Ensure you are running from the project root."
        )
    return path.read_text(encoding="utf-8").strip()
