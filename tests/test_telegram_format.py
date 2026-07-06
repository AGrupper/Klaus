"""Tests for core/telegram_format.py — markdown → Telegram HTML / plain text.

Pure functions, no mocks. Covers the constructs Klaus actually emits (verified
from live Telegram screenshots 2026-07-06): **bold**, pipe tables, bullets,
headers, `code`, ``` fences, [links](url) — plus the escaping and
conservatism contracts (raw <>& escaped; snake_case underscores untouched).
"""
from __future__ import annotations

from core.telegram_format import to_plain_text, to_telegram_html


# ------------------------------------------------------------------ #
# to_telegram_html                                                    #
# ------------------------------------------------------------------ #

def test_plain_text_passes_through():
    assert to_telegram_html("Go crush it today!") == "Go crush it today!"


def test_bold_becomes_b_tags():
    assert to_telegram_html("hit **144.9g** today") == "hit <b>144.9g</b> today"


def test_italic_single_asterisk():
    assert to_telegram_html("that *was* fast") == "that <i>was</i> fast"


def test_bold_and_italic_disjoint():
    assert (
        to_telegram_html("**bold** and *italic*")
        == "<b>bold</b> and <i>italic</i>"
    )


def test_snake_case_underscores_untouched():
    # splits_source-style identifiers appear in Klaus's prose — single-underscore
    # italics are deliberately NOT converted.
    assert to_telegram_html("check splits_source now") == "check splits_source now"


def test_code_span():
    assert to_telegram_html("run `pytest` now") == "run <code>pytest</code> now"


def test_bold_marker_inside_code_span_is_inert():
    assert (
        to_telegram_html("literal `**not bold**` here")
        == "literal <code>**not bold**</code> here"
    )


def test_header_becomes_bold_line():
    assert to_telegram_html("## Weekly recap") == "<b>Weekly recap</b>"


def test_bullets_become_dots():
    assert to_telegram_html("- first\n* second") == "• first\n• second"


def test_link_becomes_anchor():
    assert (
        to_telegram_html("see [the plan](https://example.com/p?a=1)")
        == 'see <a href="https://example.com/p?a=1">the plan</a>'
    )


def test_raw_html_is_escaped():
    assert to_telegram_html("5 < 6 & 7 > 2") == "5 &lt; 6 &amp; 7 &gt; 2"


def test_code_fence_becomes_pre():
    out = to_telegram_html("before\n```\nx = 1 < 2\n```\nafter")
    assert out == "before\n<pre>x = 1 &lt; 2</pre>\nafter"


def test_pipe_table_becomes_aligned_pre():
    md = (
        "| Rep | Pace |\n"
        "| :--- | :--- |\n"
        "| **1** | 4:02/km |\n"
        "| **2** | 3:57/km |"
    )
    out = to_telegram_html(md)
    assert out.startswith("<pre>") and out.endswith("</pre>")
    body = out[len("<pre>"):-len("</pre>")]
    lines = body.split("\n")
    # separator row dropped; bold markers stripped inside cells; columns aligned
    assert lines == [
        "Rep  Pace",
        "1    4:02/km",
        "2    3:57/km",
    ]


def test_table_between_prose_keeps_prose():
    md = "Here are the splits:\n| a | b |\n| - | - |\n| 1 | 2 |\nGreat work."
    out = to_telegram_html(md)
    assert out.startswith("Here are the splits:\n<pre>")
    assert out.endswith("</pre>\nGreat work.")


def test_lone_pipe_line_is_not_a_table():
    assert to_telegram_html("| just one weird line |") == "| just one weird line |"


def test_empty_and_none_ish_inputs():
    assert to_telegram_html("") == ""
    assert to_plain_text("") == ""


def test_unclosed_fence_still_renders():
    out = to_telegram_html("```\ndangling")
    assert out == "<pre>dangling</pre>"


# ------------------------------------------------------------------ #
# to_plain_text                                                       #
# ------------------------------------------------------------------ #

def test_plain_strips_bold_and_keeps_content():
    assert to_plain_text("hit **144.9g** today") == "hit 144.9g today"


def test_plain_strips_header_and_bullets():
    assert to_plain_text("## Recap\n- one\n- two") == "Recap\n• one\n• two"


def test_plain_table_aligned_without_tags():
    md = "| a | b |\n| - | - |\n| 1 | 2 |"
    assert to_plain_text(md) == "a  b\n1  2"


def test_plain_link_keeps_text_only():
    assert to_plain_text("see [the plan](https://example.com)") == "see the plan"


def test_plain_never_escapes():
    assert to_plain_text("5 < 6 & 7 > 2") == "5 < 6 & 7 > 2"
