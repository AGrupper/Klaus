"""Shared parsing for Klaus's anchored markdown reference documents.

Klaus keeps two long-lived reference documents that Claude reads in pieces
rather than whole: `docs/COACHING_GUIDE.md` (how to coach) and `docs/USER.md`
(who Amit is). Both mark their sections with anchors:

    <!-- SECTION: threshold-runs -->

This module is the one place that knows that convention. It was extracted from
`read_coaching_guide`, which owned it alone, when `docs/USER.md` became the
single source of ambient user facts and needed exactly the same lookup.

Security note, carried over unchanged from the original implementation
(T-22-04): a caller-supplied topic is normalised to a slug and used **only**
inside a regular expression matched against anchors authored in the file. It is
never concatenated into a filesystem path, so `..`, `/` and absolute paths
simply fail to match an anchor and return nothing. The document filename is
always chosen by Klaus, never by the caller.
"""
from __future__ import annotations

import re
from pathlib import Path

# Minimum length for a word to be usable as a fuzzy-match key. Shorter words
# ("run", "go") match too many anchors to identify a section (WR-02).
_MIN_FUZZY_WORD_LEN = 4

_ANCHOR_PREFIX = "<!-- SECTION:"


def docs_path(filename: str) -> Path:
    """Return the absolute path to a document in the repository's docs/ directory.

    Args:
        filename: Bare filename, e.g. ``"USER.md"``. Chosen by Klaus, never by a
            tool caller.

    Returns:
        Path: ``<repo root>/docs/<filename>``.
    """
    # This module lives in core/, so parent.parent is the repository root. Kept
    # identical to the original read_coaching_guide construction, which existing
    # tests patch through pathlib.Path.resolve.
    root = Path(__file__).resolve().parent.parent
    return root / "docs" / filename


def read_document(filename: str) -> str | None:
    """Read a docs/ markdown file.

    Args:
        filename: Bare filename inside docs/, e.g. ``"COACHING_GUIDE.md"``.

    Returns:
        str | None: File contents, or None when the file cannot be read. Callers
        turn None into their own error payload; this never raises.
    """
    try:
        return docs_path(filename).read_text(encoding="utf-8")
    except OSError:
        # WHY: a missing or unreadable reference document must degrade to a clear
        # tool error rather than crashing a Claude turn mid-conversation.
        return None


def slugify(topic: str) -> str:
    """Normalise a caller-supplied topic into an anchor slug.

    Args:
        topic: Raw topic string, e.g. ``"Threshold Runs"``.

    Returns:
        str: Lowercased, hyphen-separated slug, e.g. ``"threshold-runs"``.
    """
    return topic.strip().lower().replace(" ", "-").replace("_", "-")


def split_sections(content: str) -> dict[str, str]:
    """Split an anchored document into ``{slug: section_text}``.

    Args:
        content: Full markdown text of the document.

    Returns:
        dict[str, str]: One entry per ``<!-- SECTION: slug -->`` anchor, in
        document order, with surrounding whitespace stripped. Any preamble
        before the first anchor is not included.
    """
    return {
        slug: text for slug, text in _iter_sections(content)
    }


def _iter_sections(content: str):
    """Yield ``(slug, section_text)`` per anchor, in document order.

    Kept separate from :func:`split_sections` because the fuzzy fallback must
    count *anchors*, not deduplicated slugs: a document that accidentally repeats
    a slug is ambiguous, and collapsing it into a dict would hide that.
    """
    pattern = re.compile(
        r"<!-- SECTION: ([^>]+?) -->(.*?)(?=" + re.escape(_ANCHOR_PREFIX) + r"|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        yield match.group(1).strip().lower(), match.group(2).strip()


def find_section(content: str, topic: str) -> str | None:
    """Find one section by exact slug, falling back to an unambiguous word match.

    The fallback exists because Claude asks for topics in its own words. It only
    fires when a single anchor matches, so an ambiguous request returns nothing
    rather than a confidently wrong section (WR-02).

    Args:
        content: Full markdown text of the document.
        topic: Caller-supplied topic; normalised internally.

    Returns:
        str | None: The section body, or None when no unambiguous match exists.
    """
    slug = slugify(topic)
    pairs = list(_iter_sections(content))

    for name, text in pairs:
        if name == slug:
            return text

    # Fuzzy fallback: try each sufficiently long word from the requested slug and
    # accept it only when exactly one anchor contains it.
    for word in slug.split("-"):
        if len(word) < _MIN_FUZZY_WORD_LEN:
            continue
        matches = [text for name, text in pairs if word in name]
        if len(matches) == 1:
            return matches[0]

    return None
