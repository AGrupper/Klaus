"""Pure-function recommendation engine for the Five Fingers practice helper.

No I/O, no external dependencies beyond stdlib.  All logic is stateless
and has no side-effects.
"""
from __future__ import annotations

import dataclasses
import datetime


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Teammate:
    """A single member on the Five Fingers roster.

    Attributes:
        doc_id: Firestore document ID from the five_fingers_roster collection.
        name: Display name shown in reports.
        nickname: Preferred name used in outgoing messages; falls back to
            ``name`` when absent.
    """

    doc_id: str
    name: str
    nickname: str | None = None


@dataclasses.dataclass(frozen=True)
class PracticeRecord:
    """Snapshot of one practice session and who was pre-pinged.

    Attributes:
        practice_date: ISO date string (``YYYY-MM-DD``) of the session.
        attendance: Mapping of roster doc_id → ``"came"`` | ``"missed"`` |
            ``"unknown"``.
        pinged_pre_practice: Roster doc IDs whose teammates received a
            check-in message before this practice.
    """

    practice_date: str
    attendance: dict[str, str]
    pinged_pre_practice: list[str]


@dataclasses.dataclass(frozen=True)
class Suggestion:
    """A recommendation to check in with a specific teammate.

    Attributes:
        teammate: The :class:`Teammate` being recommended.
        reason: One of ``"missed_last_week"``, ``"shaky_attendance"``, or
            ``"social_checkin"``.
    """

    teammate: Teammate
    reason: str


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_ALWAYS_SHOWS_CAME_RATE = 0.90
_ALWAYS_SHOWS_MIN_RECORDS = 4
_ALWAYS_SHOWS_WINDOW = 6
_SOCIAL_CHECKIN_DAYS = 21
_MAX_SUGGESTIONS = 3


def _is_always_shows(doc_id: str, recent_practices: list[PracticeRecord]) -> bool:
    """Return True when a teammate's attendance history meets the always-shows threshold.

    The check considers up to the last 6 practices.  A minimum of 4 records
    with real data (``"came"`` or ``"missed"``) is required before the
    exclusion can apply.

    Args:
        doc_id: Roster document ID to evaluate.
        recent_practices: Full practice list, newest-first.

    Returns:
        ``True`` if the teammate should be excluded from rules 1 and 2.
    """
    window = recent_practices[:_ALWAYS_SHOWS_WINDOW]

    came_count = 0
    total_with_data = 0
    for record in window:
        status = record.attendance.get(doc_id)
        if status in ("came", "missed"):
            total_with_data += 1
            if status == "came":
                came_count += 1

    if total_with_data < _ALWAYS_SHOWS_MIN_RECORDS:
        return False

    return (came_count / total_with_data) >= _ALWAYS_SHOWS_CAME_RATE


def _missed_last_practice(doc_id: str, recent_practices: list[PracticeRecord]) -> bool:
    """Return True when the teammate's attendance at the most recent practice was ``"missed"``.

    Args:
        doc_id: Roster document ID.
        recent_practices: Practice list, newest-first.

    Returns:
        ``True`` if the most recent record marks the teammate as missed.
    """
    if not recent_practices:
        return False
    return recent_practices[0].attendance.get(doc_id) == "missed"


def _shaky_attendance(doc_id: str, recent_practices: list[PracticeRecord]) -> bool:
    """Return True when the teammate missed ≥2 of the last 4 practices.

    Only ``"missed"`` counts; ``"unknown"`` is ignored.

    Args:
        doc_id: Roster document ID.
        recent_practices: Practice list, newest-first.

    Returns:
        ``True`` if the teammate has shaky attendance in the four-practice window.
    """
    window = recent_practices[:4]
    missed_count = sum(
        1 for record in window if record.attendance.get(doc_id) == "missed"
    )
    return missed_count >= 2


def _within_social_window(
    today: datetime.date,
    practice_date_str: str,
) -> bool:
    """Return True when a practice date falls within the 21-day social-checkin window.

    Args:
        today: The reference date.
        practice_date_str: ISO date string of the practice.

    Returns:
        ``True`` if ``today - practice_date <= 21 days``.
    """
    practice_date = datetime.date.fromisoformat(practice_date_str)
    return (today - practice_date).days <= _SOCIAL_CHECKIN_DAYS


def _needs_social_checkin(
    doc_id: str,
    recent_practices: list[PracticeRecord],
    today: datetime.date,
) -> bool:
    """Return True when the teammate has not been pinged in the last 21 days.

    A teammate qualifies if their ``doc_id`` does NOT appear in any
    ``pinged_pre_practice`` list for practices within the 21-day window.

    Args:
        doc_id: Roster document ID.
        recent_practices: Practice list, newest-first.
        today: Reference date for the window calculation.

    Returns:
        ``True`` if the teammate should receive a social check-in.
    """
    for record in recent_practices:
        if not _within_social_window(today, record.practice_date):
            # Records are newest-first; once we exit the window we can stop.
            break
        if doc_id in record.pinged_pre_practice:
            return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend(
    roster: list[Teammate],
    recent_practices: list[PracticeRecord],
    today: str,
) -> list[Suggestion]:
    """Return up to 3 teammate suggestions for today's Five Fingers check-in.

    Rules are applied in strict priority order; a teammate matched by an
    earlier rule is not reconsidered for later rules.

    Rule 1 — ``missed_last_week``:
        Teammate was marked ``"missed"`` at the most recent practice.

    Rule 2 — ``shaky_attendance``:
        Teammate missed ≥2 of the last 4 practices (``"unknown"`` ignored).

    Rule 3 — ``social_checkin``:
        Teammate has not appeared in any ``pinged_pre_practice`` list within
        the past 21 days.

    Always-shows exclusion:
        Teammates with ≥4 records and ≥90% ``"came"`` rate over the last 6
        practices are excluded from rules 1 and 2, but remain eligible for
        rule 3.

    Args:
        roster: All active teammates.
        recent_practices: Practice records ordered newest-first.
        today: ISO date string used as the reference point for the 21-day
            social-checkin window.

    Returns:
        A list of at most 3 :class:`Suggestion` objects, ordered by rule
        priority and, within each rule group, by original roster order.
    """
    today_date = datetime.date.fromisoformat(today)
    suggestions: list[Suggestion] = []
    already_added: set[str] = set()

    # --- Rule 1: missed last practice ---
    for teammate in roster:
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break
        doc_id = teammate.doc_id
        if _is_always_shows(doc_id, recent_practices):
            continue
        if _missed_last_practice(doc_id, recent_practices):
            suggestions.append(Suggestion(teammate=teammate, reason="missed_last_week"))
            already_added.add(doc_id)

    # --- Rule 2: shaky attendance (not already captured by rule 1) ---
    for teammate in roster:
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break
        doc_id = teammate.doc_id
        if doc_id in already_added:
            continue
        if _is_always_shows(doc_id, recent_practices):
            continue
        if _shaky_attendance(doc_id, recent_practices):
            suggestions.append(Suggestion(teammate=teammate, reason="shaky_attendance"))
            already_added.add(doc_id)

    # --- Rule 3: social checkin (always-shows exclusion does NOT apply) ---
    for teammate in roster:
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break
        doc_id = teammate.doc_id
        if doc_id in already_added:
            continue
        if _needs_social_checkin(doc_id, recent_practices, today_date):
            suggestions.append(Suggestion(teammate=teammate, reason="social_checkin"))
            already_added.add(doc_id)

    return suggestions
