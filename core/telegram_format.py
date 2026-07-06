# core/telegram_format.py
"""Convert model-emitted markdown into Telegram-renderable HTML (or plain text).

The brain writes GitHub-style markdown (**bold**, pipe tables, ``` fences,
bullets, [links](url)). Telegram renders none of that as plain text — users
see literal asterisks and pipes. Telegram's HTML parse_mode supports a small
tag set (<b> <i> <code> <pre> <a>), and tables aren't supported at all, so
tables are re-laid-out as aligned monospace text inside <pre>.

Two pure entry points, no I/O:
  - to_telegram_html(text): for bot.send_message(..., parse_mode="HTML").
  - to_plain_text(text):    markdown stripped — for Web Push bodies (OS
    notifications render no markup) and as the fallback when Telegram
    rejects the HTML entity parse.

Conversions are deliberately conservative: single-underscore italics are NOT
converted (snake_case identifiers like splits_source appear in Klaus's prose
and would mangle), and anything unrecognized passes through escaped-verbatim
so a formatting miss can never eat content.
"""
from __future__ import annotations

import html
import re

# Inline patterns. Bold before italic; the italic pattern refuses to touch
# ** pairs so leftover bold markers never half-match.
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_CODE_SPAN = re.compile(r"`([^`\n]+?)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*]\s+")
_TABLE_SEPARATOR_CELL = re.compile(r":?-+:?")

_PLACEHOLDER = "\x00{}\x00"


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _split_blocks(text: str) -> list[tuple[str, list[str]]]:
    """Split into ("code" | "table" | "text", lines) blocks, in order."""
    lines = text.split("\n")
    blocks: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("```"):
            content: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                content.append(lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            blocks.append(("code", content))
            continue
        if _is_table_row(lines[i]):
            rows: list[str] = []
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append(lines[i])
                i += 1
            # A lone pipe line isn't a table — fall through as text.
            blocks.append(("table" if len(rows) >= 2 else "text", rows))
            continue
        run: list[str] = []
        while (
            i < len(lines)
            and not lines[i].strip().startswith("```")
            and not _is_table_row(lines[i])
        ):
            run.append(lines[i])
            i += 1
        blocks.append(("text", run))
    return blocks


def _strip_inline(line: str) -> str:
    """Remove inline markdown markers, keeping the content (plain-text mode)."""
    line = _LINK.sub(r"\1", line)
    line = _BOLD.sub(r"\1", line)
    line = _ITALIC.sub(r"\1", line)
    line = _CODE_SPAN.sub(r"\1", line)
    header = _HEADER.match(line)
    if header:
        line = header.group(1)
    line = _BULLET.sub(r"\g<1>• ", line)
    return line


def _table_to_text(rows: list[str]) -> str:
    """Re-lay a markdown pipe table as column-aligned plain text."""
    parsed: list[list[str]] = []
    for row in rows:
        cells = [ _strip_inline(c.strip()) for c in row.strip().strip("|").split("|") ]
        non_empty = [c for c in cells if c]
        if non_empty and all(_TABLE_SEPARATOR_CELL.fullmatch(c) for c in non_empty):
            continue  # the |---|---| divider row
        parsed.append(cells)
    if not parsed:
        return ""
    ncols = max(len(r) for r in parsed)
    widths = [
        max((len(r[c]) if c < len(r) else 0) for r in parsed) for c in range(ncols)
    ]
    return "\n".join(
        "  ".join(
            (r[c] if c < len(r) else "").ljust(widths[c]) for c in range(ncols)
        ).rstrip()
        for r in parsed
    )


def _inline_to_html(line: str) -> str:
    """Escape one line, then convert inline markdown to Telegram HTML tags."""
    line = html.escape(line, quote=False)

    # Pull code spans out first so bold/italic markers inside them are inert.
    code_spans: list[str] = []

    def _stash(m: re.Match) -> str:
        code_spans.append(f"<code>{m.group(1)}</code>")
        return _PLACEHOLDER.format(len(code_spans) - 1)

    line = _CODE_SPAN.sub(_stash, line)

    line = _LINK.sub(r'<a href="\2">\1</a>', line)
    header = _HEADER.match(line)
    if header:
        line = f"<b>{header.group(1)}</b>"
    line = _BULLET.sub(r"\g<1>• ", line)
    line = _BOLD.sub(r"<b>\1</b>", line)
    line = _ITALIC.sub(r"<i>\1</i>", line)

    for idx, span in enumerate(code_spans):
        line = line.replace(_PLACEHOLDER.format(idx), span)
    return line


def to_telegram_html(text: str) -> str:
    """Render markdown-ish model output as Telegram HTML (parse_mode="HTML")."""
    if not text:
        return text
    out: list[str] = []
    for kind, lines in _split_blocks(text):
        if kind == "code":
            out.append(f"<pre>{html.escape(chr(10).join(lines), quote=False)}</pre>")
        elif kind == "table":
            out.append(f"<pre>{html.escape(_table_to_text(lines), quote=False)}</pre>")
        else:
            out.extend(_inline_to_html(l) for l in lines)
    return "\n".join(out)


def to_plain_text(text: str) -> str:
    """Strip markdown for surfaces with no markup at all (push bodies, fallback)."""
    if not text:
        return text
    out: list[str] = []
    for kind, lines in _split_blocks(text):
        if kind == "code":
            out.extend(lines)
        elif kind == "table":
            out.append(_table_to_text(lines))
        else:
            out.extend(_strip_inline(l) for l in lines)
    return "\n".join(out)
