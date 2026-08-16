"""Amit's durable profile — the ambient facts Klaus should never have to be told.

`docs/USER.md` is the single source of who Amit is: where he lives, the shape of
his weeks, how long things actually take him, how he works, and the deterministic
scheduling rules Klaus applies on his behalf. This module reads it and hands it
to the rest of the system.

It exists because those facts used to live inside individual Claude skills, which
meant each skill knew a different subset — the nightly review knew a gym session
costs him 3h15m door to door, while the morning review, which also plans his day,
did not. Facts belong in one place that every surface reads.

Delivery: `profile_block()` is embedded in every `get_life_snapshot`, which all
four skills call first, so the facts arrive without any skill restating them.
`section()` backs the `read_user_profile` tool for the rarer case where Claude
wants one section verbatim.
"""
from __future__ import annotations

from core import doc_sections

USER_PROFILE_FILENAME = "USER.md"

# Guard rail for a payload that ships on every single turn. USER.md is ~6 KB of
# prose today; this leaves room to grow without anyone noticing they have made
# the snapshot expensive. Asserted by tests rather than enforced at runtime,
# because silently truncating Klaus's knowledge of Amit would be worse than a
# large payload.
PROFILE_SIZE_BUDGET_BYTES = 12_000

# Cached because USER.md is read on every snapshot but only changes on deploy.
# Keyed by nothing: a process serves exactly one repository checkout.
_CACHE: dict[str, str] | None = None


def reset_cache() -> None:
    """Drop the in-process profile cache. Used by tests."""
    global _CACHE
    _CACHE = None


def load_sections() -> dict[str, str]:
    """Return ``{section_slug: markdown}`` for every section of docs/USER.md.

    Returns:
        dict[str, str]: Sections in document order. Empty when the file is
        missing or contains no anchors — Klaus then runs without ambient
        profile context rather than failing the turn.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    content = doc_sections.read_document(USER_PROFILE_FILENAME)
    _CACHE = {} if content is None else doc_sections.split_sections(content)
    return _CACHE


def section(topic: str) -> str | None:
    """Return one profile section by slug, with the same fuzzy fallback as the guide.

    Args:
        topic: Section slug or a close approximation, e.g. ``"footprints"``.

    Returns:
        str | None: The section body, or None when no unambiguous match exists.
    """
    content = doc_sections.read_document(USER_PROFILE_FILENAME)
    if content is None:
        return None
    return doc_sections.find_section(content, topic)


def profile_block() -> dict:
    """Return the `profile` block embedded in every life snapshot.

    Returns:
        dict: ``{"source": ..., "sections": {slug: markdown}}``. The source path
        is included so Claude can say where a fact came from, and so a human
        reading a snapshot knows which file to edit to change Klaus's mind.
    """
    return {
        "source": f"docs/{USER_PROFILE_FILENAME}",
        "sections": load_sections(),
    }
