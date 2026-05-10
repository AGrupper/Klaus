"""Pure-function message composer for the Five Fingers feature.

No I/O, no external dependencies beyond stdlib.  All functions are
stateless and have no side-effects.
"""
from __future__ import annotations

import urllib.parse


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

def normalize_phone(raw: str) -> str:
    """Convert any Israeli phone number format to E.164 without the leading '+'.

    The result is suitable for embedding in a ``wa.me`` URL.

    Args:
        raw: A phone number string in any common Israeli format, e.g.
            ``"0521234567"``, ``"+972521234567"``, ``"052 123-4567"``.

    Returns:
        A 12-character string of the form ``"972XXXXXXXXX"``.

    Raises:
        ValueError: If the input cannot be interpreted as an Israeli mobile
            number (prefix ``972`` or local ``05x``).
    """
    if not raw:
        raise ValueError(f"Cannot normalize phone number: {raw!r}")

    # Strip whitespace and dashes first, then strip a leading '+'.
    cleaned = raw.replace(" ", "").replace("-", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    if cleaned.startswith("972"):
        result = cleaned
    elif cleaned.startswith("0"):
        result = "972" + cleaned[1:]
    else:
        raise ValueError(f"Cannot normalize phone number: {raw!r}")

    # Israeli mobile numbers are always exactly 12 digits (972 + 9 digits).
    if len(result) != 12 or not result.isdigit():
        raise ValueError(f"Cannot normalize phone number: {raw!r}")

    return result


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def render_personal(template: str, name: str) -> str:
    """Replace every ``{name}`` placeholder in *template* with *name*.

    Args:
        template: A message template that may contain ``{name}`` tokens.
        name: The recipient's name to substitute.

    Returns:
        The template with all ``{name}`` occurrences replaced.  If the
        template contains no ``{name}`` token the original string is
        returned unchanged.
    """
    return template.replace("{name}", name)


# ---------------------------------------------------------------------------
# WhatsApp deep-link builder
# ---------------------------------------------------------------------------

def build_wa_link(phone_e164: str, message_text: str) -> str:
    """Build a WhatsApp deep-link pre-filled with *message_text*.

    Args:
        phone_e164: An already-normalised phone number without a leading
            ``+``, e.g. ``"972521234567"``.
        message_text: The message body (may contain Hebrew or any Unicode).

    Returns:
        A ``https://wa.me/…`` URL with the message percent-encoded.
    """
    encoded = urllib.parse.quote(message_text, safe="")
    return f"https://wa.me/{phone_e164}?text={encoded}"


# ---------------------------------------------------------------------------
# Captains-group status message
# ---------------------------------------------------------------------------

def render_captains_status(names: list[str]) -> str:
    """Generate the Hebrew status message for the captains WhatsApp group.

    Args:
        names: Ordered list of captain names being pinged today (0–3 items).

    Returns:
        A Hebrew sentence announcing which captains are being checked in
        with today, or a "no checks today" message for an empty list.

    Examples:
        >>> render_captains_status([])
        'אין בדיקות היום.'
        >>> render_captains_status(["יוסי"])
        'היי, אני בודק היום עם יוסי.'
        >>> render_captains_status(["יוסי", "דוד"])
        'היי, אני בודק היום עם יוסי ו-דוד.'
        >>> render_captains_status(["יוסי", "דוד", "אבי"])
        'היי, אני בודק היום עם יוסי, דוד ו-אבי.'
    """
    if not names:
        return "אין בדיקות היום."

    if len(names) == 1:
        joined = names[0]
    elif len(names) == 2:
        joined = f"{names[0]} ו-{names[1]}"
    else:
        # Comma-join all names except the last, then append the Hebrew "and".
        all_but_last = ", ".join(names[:-1])
        joined = f"{all_but_last} ו-{names[-1]}"

    return f"היי, אני בודק היום עם {joined}."
