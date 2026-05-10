"""Unit tests for mcp_tools/five_fingers/composer.py.

Pure-function tests — no I/O, no mocking required.
"""
from __future__ import annotations

import pytest

from mcp_tools.five_fingers.composer import (
    build_wa_link,
    normalize_phone,
    render_captains_status,
    render_personal,
)


# ---------------------------------------------------------------------------
# normalize_phone
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_local_ten_digit(self):
        assert normalize_phone("0521234567") == "972521234567"

    def test_e164_with_plus(self):
        assert normalize_phone("+972521234567") == "972521234567"

    def test_e164_without_plus(self):
        assert normalize_phone("972521234567") == "972521234567"

    def test_spaces_and_dashes_stripped(self):
        assert normalize_phone("+972 52-123 45 67") == "972521234567"

    def test_local_with_spaces(self):
        assert normalize_phone("052 123 4567") == "972521234567"

    def test_local_with_dashes(self):
        assert normalize_phone("052-123-4567") == "972521234567"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            normalize_phone("")

    def test_non_israeli_prefix_raises(self):
        # German number starting with 0049
        with pytest.raises(ValueError):
            normalize_phone("0049123456789")

    def test_result_is_exactly_12_digits(self):
        result = normalize_phone("0521234567")
        assert len(result) == 12
        assert result.isdigit()


# ---------------------------------------------------------------------------
# build_wa_link
# ---------------------------------------------------------------------------

class TestBuildWaLink:
    def test_hebrew_text_is_url_encoded(self):
        link = build_wa_link("972521234567", "שלום")
        # Hebrew characters encode to %D7 and %A9 / similar sequences.
        assert "%D7" in link.upper() or "%" in link

    def test_phone_appears_in_path_without_plus(self):
        link = build_wa_link("972521234567", "hello")
        assert "wa.me/972521234567" in link
        assert "+" not in link.split("?")[0]

    def test_link_format(self):
        link = build_wa_link("972521234567", "test message")
        assert link.startswith("https://wa.me/972521234567?text=")

    def test_special_chars_encoded(self):
        link = build_wa_link("972521234567", "hello world & more")
        assert " " not in link
        assert "&" not in link.split("?text=", 1)[1]


# ---------------------------------------------------------------------------
# render_personal
# ---------------------------------------------------------------------------

class TestRenderPersonal:
    def test_name_substituted(self):
        result = render_personal("שלום {name}, מה שלומך?", "יוסי")
        assert result == "שלום יוסי, מה שלומך?"

    def test_multiple_occurrences_replaced(self):
        result = render_personal("{name} — hey {name}!", "דוד")
        assert result == "דוד — hey דוד!"

    def test_no_placeholder_returns_unchanged(self):
        template = "אין כאן מקום-שם."
        assert render_personal(template, "יוסי") == template


# ---------------------------------------------------------------------------
# render_captains_status
# ---------------------------------------------------------------------------

class TestRenderCaptainsStatus:
    def test_empty_list(self):
        assert render_captains_status([]) == "אין בדיקות היום."

    def test_one_name(self):
        assert render_captains_status(["יוסי"]) == "היי, אני בודק היום עם יוסי."

    def test_two_names(self):
        result = render_captains_status(["יוסי", "דוד"])
        assert result == "היי, אני בודק היום עם יוסי ו-דוד."

    def test_three_names(self):
        result = render_captains_status(["יוסי", "דוד", "אבי"])
        assert result == "היי, אני בודק היום עם יוסי, דוד ו-אבי."
