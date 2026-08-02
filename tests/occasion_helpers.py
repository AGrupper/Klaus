"""Shared Wave-0 test scaffolding for every occasion test file (Phase 33).

Three helpers, used across `tests/test_autonomous.py`, `tests/test_nightly_review.py`,
`tests/test_morning_briefing.py`, `tests/test_weekly_training_review.py`,
`tests/test_heartbeat.py`, `tests/test_tools.py`, `tests/test_task_dispatch.py`,
and `tests/test_firestore_db.py`, so every occasion test in this phase builds
its fakes and fixtures from one source of truth instead of hand-rolling its own
copy:

- ``install_firestore_mock()`` — stubs ``google.cloud.firestore`` (+ auth libs)
  into ``sys.modules`` so store classes and ``core.autonomous`` import cleanly
  without real GCP credentials.
- ``make_occasion_verdict(...)`` — builds a ``TickBrain.think()``-shaped verdict
  dict, including the D-02 ``skip_cause`` taxonomy this phase introduces.
- ``make_occasion_situation(...)`` — builds a ``gather_situation()``-shaped
  situation dict carrying every key ``_build_triage_prompt``/``_compose_layer2``
  read, with an ``empty=True`` mode for the D-11/OCC-04 empty-gate-bypass tests.

This module is test-only support code: no production imports, no network calls,
no GCP. The ``now_context`` shape is reproduced locally (mirroring
``core.autonomous._now_context``) rather than importing ``core.autonomous``
directly, so this module can be imported before ``install_firestore_mock()``
has run without triggering an import-order failure.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

# D-02 (33-CONTEXT.md) — the four legitimate occasion skip causes, plus the
# empty string for "not a skip" / "should_act=True". Exported as the single
# source of truth every downstream occasion test asserts against.
#
# WR-01 — the four real causes now also live in production as
# ``core.tick_brain.SKIP_CAUSES`` (the parser validates against them). This set
# is that set plus "", which is an accepted ARGUMENT to make_occasion_verdict
# meaning "no skip cause" but is never emitted as a key.
# tests/test_tick_brain.py asserts the two stay in sync.
SKIP_CAUSES: frozenset[str] = frozenset(
    {"", "directive", "already_covered", "nothing_happened", "reaction_history"}
)

# Mirrors core.autonomous._TICK_TOTAL_PER_DAY (07:00..21:00 inclusive, every
# 20 minutes = 43 ticks/day) — duplicated here rather than imported so this
# module stays free of production imports (see module docstring).
_TICK_TOTAL_PER_DAY = 43
_TZ = ZoneInfo("Asia/Jerusalem")


# ---------------------------------------------------------------------------
# install_firestore_mock() — lifted verbatim from
# tests/test_autonomous.py::_install_firestore_mock (Phase 33 Plan 01, Task 1).
# test_autonomous.py keeps its own private copy unchanged so its existing
# tests do not shift; this is the shared export every later occasion test
# file imports instead of hand-rolling the same sys.modules stubbing.
# ---------------------------------------------------------------------------

def _safe_mock_module(name: str) -> None:
    if name in sys.modules:
        return
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent in sys.modules and isinstance(sys.modules[parent], MagicMock):
            sys.modules[name] = MagicMock()
            return
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = MagicMock()


def install_firestore_mock() -> None:
    """Install mock google.cloud.firestore + auth stubs into sys.modules.

    Mirrors the pattern from tests/test_reflection.py and
    tests/test_main_render_smart_system.py so the tested modules import
    cleanly without real Google API libraries installed.
    """
    if "google.cloud.firestore" not in sys.modules:
        import types
        try:
            import google
        except ImportError:
            google = types.ModuleType("google")
            sys.modules["google"] = google

        try:
            import google.cloud
            google_cloud_mod = sys.modules["google.cloud"]
        except ImportError:
            google_cloud_mod = types.ModuleType("google.cloud")
            sys.modules["google.cloud"] = google_cloud_mod
            if not hasattr(google, "cloud"):
                setattr(google, "cloud", google_cloud_mod)

        firestore_mock = MagicMock()

        class _Increment:
            def __init__(self, value):
                self.value = value
            def __repr__(self):
                return f"Increment({self.value!r})"

        firestore_mock.Increment = _Increment
        firestore_mock.SERVER_TIMESTAMP = object()
        firestore_mock.ArrayUnion = MagicMock()

        sys.modules["google.cloud.firestore"] = firestore_mock
        google_cloud_mod.firestore = firestore_mock
        if not hasattr(google, "cloud"):
            google.cloud = google_cloud_mod

        _safe_mock_module("google.api_core")
        _safe_mock_module("google.api_core.exceptions")
        _safe_mock_module("google.cloud.firestore_v1")
        _safe_mock_module("google.cloud.firestore_v1.base_query")

    _safe_mock_module("google.auth")
    _safe_mock_module("google.auth.exceptions")
    _safe_mock_module("google.auth.transport")
    _safe_mock_module("google.auth.transport.requests")
    _safe_mock_module("google.oauth2")
    _safe_mock_module("google.oauth2.credentials")
    _safe_mock_module("google.oauth2.service_account")
    _safe_mock_module("google_auth_oauthlib")
    _safe_mock_module("google_auth_oauthlib.flow")
    _safe_mock_module("googleapiclient")
    _safe_mock_module("googleapiclient.errors")
    _safe_mock_module("googleapiclient.discovery")

    _safe_mock_module("dotenv")


# ---------------------------------------------------------------------------
# make_occasion_verdict — TickBrain.think()-shaped fake verdict
# ---------------------------------------------------------------------------

def make_occasion_verdict(
    *,
    should_act: bool = True,
    draft: str = "...",
    reason: str = "...",
    skip_cause: str = "",
) -> dict:
    """Build a fake ``core.tick_brain.TickBrain.think()`` return dict.

    Args:
        should_act: Layer-1 verdict — whether the occasion should act.
        draft: Layer-1's free draft text (used verbatim as ``daily_note`` on a
            skip, per D-06).
        reason: One-sentence triage reasoning.
        skip_cause: D-02 taxonomy — one of ``SKIP_CAUSES``. Must be one of
            ``"directive"``, ``"already_covered"``, ``"nothing_happened"``,
            ``"reaction_history"``, or ``""`` (not a skip / cause not yet
            categorized).

    Raises:
        ValueError: if ``skip_cause`` is not a member of ``SKIP_CAUSES`` — this
            keeps every downstream test asserting against the same vocabulary
            (33-01-PLAN.md Task 1).

    WR-01 — the returned dict must be a shape ``TickBrain._parse_response`` can
    ACTUALLY emit. The original version always included ``draft``,
    ``topic_key`` and ``skip_cause`` keys, even when empty; the real parser
    omits every falsy optional field. That divergence is why nothing in the
    suite caught the parser dropping ``skip_cause`` entirely — every occasion
    test asserted against a fiction. ``tests/test_tick_brain.py`` now pins this
    helper's output against the real parser so the two cannot drift again.
    """
    if skip_cause not in SKIP_CAUSES:
        raise ValueError(
            f"skip_cause must be one of {sorted(SKIP_CAUSES)!r}, got {skip_cause!r}"
        )
    verdict: dict = {
        "should_act": should_act,
        "reason": reason,
    }
    # Falsy optionals are OMITTED, exactly as TickBrain._parse_response does.
    if draft:
        verdict["draft"] = draft
    if skip_cause:
        verdict["skip_cause"] = skip_cause
    return verdict


# ---------------------------------------------------------------------------
# make_occasion_situation — gather_situation()-shaped fake situation
# ---------------------------------------------------------------------------

def _build_now_context(now: datetime) -> dict:
    """Reproduce core.autonomous._now_context's shape without importing it.

    See module docstring — this module deliberately carries no production
    imports, so the small, pure now_context computation is duplicated here.
    """
    local = now.astimezone(_TZ)
    minutes_into_window = max(0, (local.hour - 7) * 60 + local.minute)
    tick_index = max(1, (minutes_into_window // 20) + 1)
    tick_index = min(tick_index, _TICK_TOTAL_PER_DAY)
    last_tick_local = local - timedelta(minutes=20)
    return {
        "now_iso": now.isoformat(),
        "now_local": local.strftime("%H:%M %Z"),
        "tick_index": tick_index,
        "tick_total": _TICK_TOTAL_PER_DAY,
        "last_tick_at": last_tick_local.strftime("%H:%M"),
    }


def make_occasion_situation(
    now: datetime, *, occasion: str = "nightly", empty: bool = False
) -> dict:
    """Build a ``gather_situation()``-shaped situation dict for occasion tests.

    Always carries every key ``core.autonomous._build_triage_prompt`` and
    ``core.autonomous._compose_layer2`` read from the situation dict, so any
    downstream occasion test can patch ``gather_situation``/the occasion's own
    specialized gather with this fixture and trust both prompt-builders resolve
    cleanly.

    Args:
        now: The tz-aware "current" datetime the situation is built for.
        occasion: Which occasion this situation represents (``"nightly"``,
            ``"morning"``, or ``"weekly_review"``) — carried through as an
            ``"occasion"`` key for callers that want it, mirroring the
            ``occasion`` parameter downstream plans add to
            ``run_autonomous_tick``.
        empty: When True, builds the D-11/OCC-04 empty-signals case — every
            trigger-shaped list stays empty and ``"empty"`` is set True, so
            tests can prove occasions bypass the empty-gate that a plain tick
            would honor.
    """
    situation: dict = {
        "occasion": occasion,
        "calendar": [],
        "ticktick_overdue": [],
        "unread_email_count": 0,
        "due_followups": [],
        "meals_since_last_tick": [],
        "training_status": {},
        "acwr": {"ratio": None},
        "habit_pending": [],
        "recovery": {},
        "training_evidence": {},
        "standing_directives": [],
        "hours_since_contact": 2.0,
        "self_state": {"current_focus": "", "mood": ""},
        "recent_journal_digest": "",
        "now_context": _build_now_context(now),
        "today_outreach_log": [],
        "conversation_tail": [],
        "training_reality": {},
        "empty": empty,
    }
    if not empty:
        # A minimal non-empty signal so a "live" situation is genuinely live —
        # mirrors tests/test_autonomous.py::_live_situation's default overdue item.
        situation["ticktick_overdue"] = [
            {"title": "example overdue item", "due": now.date().isoformat()}
        ]
    return situation
