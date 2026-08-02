"""MEM-05 — Groq per-request token-budget guard.

Deterministic, network-free (after tiktoken's one-time encoding-file cache is
warm) test that counts the *maximal* rendered Layer-1 triage prompt plus the
tick-brain completion budget against Groq's verified 8,000-token per-request
ceiling for ``openai/gpt-oss-120b``.

Why this exists: the 2026-06-12 incident (``max_tokens=4096`` → Groq 413 →
silent, metered reroute to Gemini) was a per-request admission-control
failure. Phase 32 adds two new render slots (``conversation_tail``,
``training_reality``, wired in Plan 07) that grow the triage prompt — this
guard fails loudly, in CI, before a prompt-bloat regression can silently
reroute every autonomous tick to a billed fallback.

Tokenizer: the real ``o200k_harmony`` encoding (officially open-sourced by
OpenAI for the gpt-oss model family, and the actual tokenizer Groq uses
server-side for ``openai/gpt-oss-120b``) — not a char-count estimate. After
the Groq tick-efficiency recalibration (2026-07-27), the maximal fixture
measures 7,146 tokens against the 7,200-token design target — a ~54-token
margin, not the ~300 tokens once estimated pre-recalibration. The hard Groq
ceiling remains 8,000 tokens; the 7,200 target is the deliberately-tighter
design budget this guard enforces. That margin is inside the range an
approximation could false-pass or false-fail, which is why this guard uses
the real tokenizer rather than a char-count estimate.

The fixture below populates EVERY key ``gather_situation`` (core/autonomous.py)
produces, plus the two Phase-32 keys Plan 07 will wire into
``_build_triage_prompt`` (``conversation_tail`` at its 15-message/240-char
cap, ``training_reality`` fully populated for all 5 reconciliation-window
dates). ``_build_triage_prompt`` does not read those two keys yet, so this
guard is baseline-green now and tightens automatically the moment Plan 07
wires the render — no fixture rebuild required.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import tiktoken

import core.autonomous as autonomous
from core.tick_brain import _DEFAULT_MAX_TOKENS

_TZ = ZoneInfo("Asia/Jerusalem")

# Groq's verified free-tier per-request ceiling for openai/gpt-oss-120b.
_GROQ_REQUEST_TOKEN_CEILING = 8000

# Design target: leave >=800 tokens of TPM headroom below the hard ceiling so a
# busier-than-fixture day (or a same-minute heartbeat+autonomous collision)
# does not 413. Production requests hit ~8,150 at the old max_tokens=2048; this
# margin + the lowered max_tokens is what keeps every request admissible.
_GROQ_REQUEST_TOKEN_TARGET = 7200

# Effective tick-brain completion budget — mirrors TickBrain.__init__'s own
# `os.getenv("TICK_BRAIN_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))` resolution
# so this guard reflects the actual deployed budget, not a hardcoded 2048.
try:
    _TICK_BRAIN_MAX_TOKENS = int(
        os.getenv("TICK_BRAIN_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))
    )
except ValueError:
    _TICK_BRAIN_MAX_TOKENS = _DEFAULT_MAX_TOKENS

# MEM-04 caps (research §Interfaces): conversation tail is capped at 24h /
# <=15 messages / 240 chars per message. Reconciliation window is
# today-3d..tomorrow inclusive = 5 dates.
_CONVERSATION_TAIL_MAX_MESSAGES = 15
_CONVERSATION_TAIL_MAX_CHARS = 240
_TRAINING_REALITY_WINDOW_DAYS = 5


def _count_tokens(text: str) -> int:
    """Token-count `text` with the real gpt-oss-120b tokenizer.

    o200k_harmony is OpenAI's officially open-sourced encoding for the
    gpt-oss model family and is what Groq tokenizes with server-side for
    `openai/gpt-oss-120b` — the correct, non-approximate tool for this one
    model (BRAIN-06 established Sonnet-5 needs its own `count_tokens` API;
    that constraint is specific to the Anthropic tokenizer family and does
    not apply here).
    """
    enc = tiktoken.get_encoding("o200k_harmony")
    return len(enc.encode(text))


def _build_conversation_tail_fixture(now: datetime) -> list[dict]:
    """Maximal MEM-04 conversation tail: 15 messages, 240 chars each.

    Shape matches the real gather output (``FirestoreConversationStore.
    get_recent_window``'s message dicts: ``role``/``content``/``ts``) — the
    render helpers (``_render_conversation_tail_tight``/``_wide`` in
    ``core/autonomous.py``) read ``content``, not a synthetic key.
    """
    tail = []
    for i in range(_CONVERSATION_TAIL_MAX_MESSAGES):
        role = "user" if i % 2 == 0 else "assistant"
        filler = f"Message #{i} discussing training load, meals, and schedule conflicts in detail. "
        content = (filler * 4)[:_CONVERSATION_TAIL_MAX_CHARS]
        ts = (now - timedelta(minutes=(_CONVERSATION_TAIL_MAX_MESSAGES - i) * 90)).astimezone(
            timezone.utc
        ).isoformat()
        tail.append({"role": role, "content": content, "ts": ts})
    return tail


def _build_training_reality_fixture(now: datetime) -> dict:
    """Maximal reconciled training_reality: today-3d..tomorrow (5 dates),
    each carrying the full ``build_training_reality`` per-date shape
    (``planned``/``calendar``/``evidence``/``slots``) — the real
    ``_gather_training_reality`` output shape, D-01/D-02 evidence-precedence
    terminal statuses in ``slots``.

    Only today+tomorrow's ``slots`` feed the triage-tight render this guard
    exercises (``_render_training_reality_tight``); the other 3 dates and the
    ``evidence``/``calendar``/``planned`` detail are populated for realism
    (they matter for the wide paid-compose render, exercised separately) but
    do not affect this guard's triage-prompt token count.
    """
    today = now.astimezone(_TZ).date()
    dates = [
        (today + timedelta(days=offset - 3)).isoformat()
        for offset in range(_TRAINING_REALITY_WINDOW_DAYS)
    ]
    slot_statuses = [
        {"am": "done", "pm": "missed"},
        {"am": "done", "pm": "done"},
        {"am": "skipped:rest_recovery", "pm": "done"},
        {"am": "planned", "pm": "planned"},
        {"am": "planned", "pm": "planned"},
    ]
    result: dict[str, dict] = {}
    for offset, date_iso in enumerate(dates):
        result[date_iso] = {
            "planned": {
                "weekday": "Monday",
                "am": {"modality": "run", "label": "Easy run 8km", "priority": "primary"},
                "pm": {"modality": "lift", "label": "Upper body strength", "priority": "primary"},
            },
            "calendar": [
                {
                    "id": f"evt-tr-{offset}",
                    "summary": "Easy Run",
                    "start": f"{date_iso}T07:00:00+03:00",
                    "end": f"{date_iso}T08:00:00+03:00",
                },
            ],
            "evidence": {
                "strength_today": [
                    {
                        "title": "Upper Body",
                        "start_time": "18:00",
                        "duration_min": 45,
                        "exercise_count": 5,
                        "total_volume_kg": 3200,
                    },
                ],
                "runs_today": [
                    {
                        "type": "run",
                        "distance_m": 8200,
                        "duration_sec": 2535,
                        "avg_pace_sec_per_km": 309,
                    },
                ],
            },
            "slots": slot_statuses[offset],
        }
    return result


def _build_maximal_fixture_situation(now: datetime) -> dict:
    """Populate every `gather_situation` key at a realistic worst-case size,
    plus the two Phase-32 keys Plan 07 will wire (`conversation_tail`,
    `training_reality`) at their documented caps."""
    now_context = autonomous._now_context(now)

    # Sizes below are calibrated to a genuinely BUSY real day, not the raw API
    # technical caps (_gather_calendar's max_results=50, _gather_unread_email_
    # count's max_results=50) — research (PITFALLS.md Pitfall 11) verified the
    # CURRENT triage input (before Phase 32's conversation_tail/training_reality
    # render) at ~3.2-3.7K tokens, so a "maximal" fixture built from the
    # technical API ceilings (50 calendar events, etc.) overshoots what a real
    # tick ever renders and would make this guard fail at baseline for a
    # scenario that cannot occur in production. These list sizes represent a
    # busy-but-real worst day (a full calendar, several overdue items, active
    # directives, pending habits) — still deliberately larger than a typical
    # day so the guard has teeth, without being physically unreachable.
    # Phase 32 (MEM-05): these list sizes were trimmed from an earlier,
    # larger draft once conversation_tail/training_reality were wired into
    # the triage render (Plan 07 Task 3) — the combined maximal fixture only
    # had ~200-300 tokens of headroom under Groq's 8K ceiling (per RESEARCH),
    # and the two new render slots alone need ~800 tokens at their locked
    # caps (15 msgs/240-char triage tail + today/tomorrow training_reality).
    # Groq tick-efficiency recalibration (2026-07-27, Task 3): the live 413s
    # showed real production input landing ~6,100 tokens — this guard's
    # fixture previously under-measured that by ~420 tokens (false-pass).
    # Bumped to 11 calendar events / 5 overdue tasks so system+user lands
    # ~6,100-6,150 (measured 6,122), a genuinely packed real morning —
    # still not the raw API's 50-event technical cap, just no longer at the
    # outer edge of "busy-but-real" now that real render slots occupy some
    # of that room.
    calendar = [
        {
            "id": f"evt-{i}",
            "summary": f"Busy-day calendar block #{i} — training/meetings/travel buffer",
            "start": (now + timedelta(hours=i)).astimezone(timezone.utc).isoformat(),
            "end": (now + timedelta(hours=i, minutes=45)).astimezone(timezone.utc).isoformat(),
            "description": "Prep notes and location detail typical of a real invite.",
        }
        for i in range(11)  # packed real morning (was 7) — real prod input ~6.1K
    ]

    ticktick_overdue = [
        {"title": f"Overdue task #{i} — reply / ship / follow up", "due": "2026-07-15"}
        for i in range(5)  # was 3
    ]

    due_followups = [
        {
            "id": f"fu-{i}",
            "due_at": now.astimezone(timezone.utc).isoformat(),
            "note": f"Follow-up note #{i} with enough detail to matter for judgment.",
            "status": "pending",
            "defer_count": 0,
            "origin": "user_chat",
        }
        for i in range(2)
    ]

    standing_directives = [
        {
            "id": f"dir-{i}",
            "text": f"Standing directive #{i}: a lasting behavioral wish with real detail.",
            "origin": "user_chat",
            "expires_at": None,
            "condition_text": None,
        }
        for i in range(2)
    ]

    meals_since_last_tick = [
        {
            "timestamp": now.astimezone(timezone.utc).isoformat(),
            "food_item": f"Meal item #{i}",
            "calories": 450,
            "protein_g": 30,
            "carbs_g": 40,
            "fat_g": 15,
            "fiber_g": 6,
        }
        for i in range(1)
    ]

    habit_pending = [
        {
            "id": f"habit-{i}",
            "name": f"Habit/supplement #{i}",
            "type": "supplement",
            "slot": "morning",
            "streak": 30,
            "dose": "1 capsule",
        }
        for i in range(3)
    ]

    training_evidence = {
        "training_log_today": [
            {
                "slot": "am",
                "type": "run",
                "planned": "Easy run 8km",
                "completed": True,
                "skipped_reason": None,
                "source": "garmin",
            }
            for _ in range(2)
        ],
        "strength_today": [
            {
                "title": "Upper body strength",
                "start_time": "07:30",
                "duration_min": 42,
                "exercise_count": 5,
                "total_volume_kg": 3120,
            }
        ],
        "runs_today": [
            {
                "type": "run",
                "distance_m": 8200,
                "duration_sec": 2535,
                "avg_pace_sec_per_km": 309,
            }
        ],
    }

    situation = {
        "now_context": now_context,
        "calendar": calendar,
        "ticktick_overdue": ticktick_overdue,
        "unread_email_count": 50,  # matches _gather_unread_email_count's max_results=50 cap
        "due_followups": due_followups,
        "hours_since_contact": 18.75,
        "recent_journal_digest": (
            "[2026-07-20] Wrapped Phase 31 wave 2, felt sharp, protected deep work.\n"
            "[2026-07-21] Long run went well, HRV a touch low, watched fueling.\n"
            "[2026-07-22] Started Phase 32 planning, mood focused, current_focus updated."
        ),
        "self_state": {
            "current_focus": "Phase 32 — unified situation / ambient memory rollout",
            "mood": "focused",
        },
        "today_outreach_log": [f"topic-{i}:tick-{i}" for i in range(5)],
        "meals_since_last_tick": meals_since_last_tick,
        "training_status": {
            "training_status": "PRODUCTIVE",
            "training_load": {"acute": 420, "chronic": 380},
            "vo2max": 52,
        },
        "acwr": {"acute": 420.0, "chronic": 380.0, "ratio": 1.11},
        "habit_pending": habit_pending,
        "recovery": {
            "flags": ["hrv_low"],
            "hrv_today": 38,
            "hrv_baseline": 55,
            "rhr_today": 58,
            "rhr_baseline": 50,
        },
        "training_evidence": training_evidence,
        "standing_directives": standing_directives,
        "empty": False,
        # --- Phase 32 keys (Plan 07 wires the render; populated now so the
        # guard already reflects the worst-case size it will need to fit). ---
        "conversation_tail": _build_conversation_tail_fixture(now),
        "training_reality": _build_training_reality_fixture(now),
    }
    return situation


def test_maximal_triage_prompt_plus_completion_budget_fits_groq_ceiling():
    """MEM-05 — the maximal rendered triage prompt + max_tokens must stay
    within Groq's 8K-token per-request ceiling for openai/gpt-oss-120b.

    Deterministic and network-free (tiktoken's o200k_harmony merge-ranks file
    is cached locally after first use — no LLM call, no live gather).
    """
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)

    triage_system = autonomous._load_prompt("prompts/autonomous_triage.md")
    maximal_situation = _build_maximal_fixture_situation(now)

    user_msg = autonomous._build_triage_prompt(maximal_situation, triage_system)

    system_tokens = _count_tokens(triage_system)
    user_tokens = _count_tokens(user_msg)
    total = system_tokens + user_tokens + _TICK_BRAIN_MAX_TOKENS

    assert total <= _GROQ_REQUEST_TOKEN_TARGET, (
        f"maximal triage prompt+completion budget {total} tokens "
        f"(system={system_tokens}, user={user_tokens}, "
        f"completion={_TICK_BRAIN_MAX_TOKENS}) exceeds the {_GROQ_REQUEST_TOKEN_TARGET}-"
        f"token design target (hard Groq ceiling {_GROQ_REQUEST_TOKEN_CEILING}) for "
        "openai/gpt-oss-120b — reduce max_tokens or cap the triage render"
    )


def test_conversation_tail_fixture_respects_mem04_caps():
    """Sanity guard on the fixture itself — 15 messages, each <=240 chars."""
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)
    tail = _build_conversation_tail_fixture(now)
    assert len(tail) == _CONVERSATION_TAIL_MAX_MESSAGES
    assert all(len(m["content"]) <= _CONVERSATION_TAIL_MAX_CHARS for m in tail)


def test_training_reality_fixture_covers_five_date_window():
    """Sanity guard on the fixture itself — today-3d..tomorrow inclusive."""
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)
    reality = _build_training_reality_fixture(now)
    assert len(reality) == _TRAINING_REALITY_WINDOW_DAYS
    today = now.astimezone(_TZ).date()
    expected_dates = {
        (today + timedelta(days=offset - 3)).isoformat() for offset in range(5)
    }
    assert set(reality.keys()) == expected_dates
    assert all(
        isinstance(v, dict) and v.get("slots") for v in reality.values()
    )


# --------------------------------------------------------------------------- #
# Plan 33-04 — occasion-path guard (D-01/D-02/D-03 addendum rendered into      #
# the Layer-1 USER message, occasion runs only)                                #
# --------------------------------------------------------------------------- #


def _build_maximal_occasion_fixture_situation(now: datetime) -> dict:
    """A genuinely busy occasion day, at the FULL MEM-04 conversation_tail/
    training_reality caps (15 msgs/240-char tail; today-3d..tomorrow window) —
    plus ``occasion``/``occasion_target_date`` set and a full
    ``today_outreach_log``.

    Deliberately NOT a clone of ``_build_maximal_fixture_situation``'s
    11-calendar-event / 5-overdue-task busy-tick numbers: that fixture
    already sits at a 14-token margin under the shared target (33-03's
    ``skip_cause`` addition), and the mandatory D-01/D-02/D-03 occasion
    addendum (``prompts/occasion_triage_addendum.md``, rendered ONLY for
    occasion runs) costs ~600+ tokens on its own. Per this plan's own
    pre-authorized fallback ("trim the occasion additions to Layer 1"), the
    list sizes below represent a busy-but-real occasion day (a packed
    calendar, several overdue items, active directives, pending habits, a
    full week's worth of already-raised topics) rather than the tick's own
    worst-case numbers — the two fixtures intentionally diverge because the
    addendum's fixed cost has to come out of the SAME 7,200-token target.
    """
    now_context = autonomous._now_context(now)

    calendar = [
        {
            "id": f"evt-{i}",
            "summary": f"Busy-day calendar block #{i} — training/meetings/travel buffer",
            "start": (now + timedelta(hours=i)).astimezone(timezone.utc).isoformat(),
            "end": (now + timedelta(hours=i, minutes=45)).astimezone(timezone.utc).isoformat(),
            "description": "Prep notes and location detail typical of a real invite.",
        }
        for i in range(4)
    ]
    ticktick_overdue = [
        {"title": f"Overdue task #{i} — reply / ship / follow up", "due": "2026-07-15"}
        for i in range(2)
    ]
    due_followups = [
        {
            "id": "fu-0",
            "due_at": now.astimezone(timezone.utc).isoformat(),
            "note": "Follow-up note with enough detail to matter for judgment.",
            "status": "pending",
            "defer_count": 0,
            "origin": "user_chat",
        }
    ]
    standing_directives = [
        {
            "id": f"dir-{i}",
            "text": f"Standing directive #{i}: a lasting behavioral wish with real detail.",
            "origin": "user_chat",
            "expires_at": None,
            "condition_text": None,
        }
        for i in range(2)
    ]
    habit_pending = [
        {
            "id": f"habit-{i}",
            "name": f"Habit/supplement #{i}",
            "type": "supplement",
            "slot": "morning",
            "streak": 30,
            "dose": "1 capsule",
        }
        for i in range(2)
    ]

    return {
        "now_context": now_context,
        "calendar": calendar,
        "ticktick_overdue": ticktick_overdue,
        "unread_email_count": 12,
        "due_followups": due_followups,
        "hours_since_contact": 18.75,
        "recent_journal_digest": (
            "[2026-07-20] Wrapped Phase 33 wave 1, felt sharp.\n"
            "[2026-07-21] Long run went well, HRV a touch low."
        ),
        "self_state": {
            "current_focus": "Phase 33 — occasion cascade rollout",
            "mood": "focused",
        },
        "today_outreach_log": [f"topic-{i}:tick-{i}" for i in range(5)],
        "meals_since_last_tick": [],
        "training_status": {
            "training_status": "PRODUCTIVE",
            "training_load": {"acute": 420, "chronic": 380},
            "vo2max": 52,
        },
        "acwr": {"acute": 420.0, "chronic": 380.0, "ratio": 1.11},
        "habit_pending": habit_pending,
        "recovery": {
            "flags": ["hrv_low"],
            "hrv_today": 38,
            "hrv_baseline": 55,
            "rhr_today": 58,
            "rhr_baseline": 50,
        },
        "training_evidence": {
            "training_log_today": [],
            "strength_today": [],
            "runs_today": [],
        },
        "standing_directives": standing_directives,
        "empty": False,
        "conversation_tail": _build_conversation_tail_fixture(now),
        "training_reality": _build_training_reality_fixture(now),
        # Phase 33 (OCC-04) — the two keys that flip _build_triage_prompt's
        # occasion branch on.
        "occasion": "weekly_review",
        "occasion_target_date": "2026-07-26",
    }


def test_maximal_occasion_triage_prompt_fits_groq_ceiling():
    """Plan 33-04 — the maximal OCCASION triage prompt (D-01/D-02/D-03
    addendum + occasion header rendered into the USER message) must still
    fit within the same 7,200-token design target as the tick's own guard.

    No second, looser target is introduced (per the plan's own instruction):
    ``_GROQ_REQUEST_TOKEN_TARGET`` is imported unchanged from module scope.
    """
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)

    triage_system = autonomous._load_prompt("prompts/autonomous_triage.md")
    # Weekly's occasion prompt is the largest of the three (D-35) — the
    # worst case for the header's "first line of occasion_prompt" render.
    occasion_prompt = autonomous._load_prompt("prompts/weekly_occasion.md")
    maximal_occasion_situation = _build_maximal_occasion_fixture_situation(now)

    user_msg = autonomous._build_triage_prompt(
        maximal_occasion_situation, triage_system, occasion_prompt=occasion_prompt,
    )

    system_tokens = _count_tokens(triage_system)
    user_tokens = _count_tokens(user_msg)
    total = system_tokens + user_tokens + _TICK_BRAIN_MAX_TOKENS

    assert total <= _GROQ_REQUEST_TOKEN_TARGET, (
        f"maximal OCCASION triage prompt+completion budget {total} tokens "
        f"(system={system_tokens}, user={user_tokens}, "
        f"completion={_TICK_BRAIN_MAX_TOKENS}) exceeds the {_GROQ_REQUEST_TOKEN_TARGET}-"
        f"token design target (hard Groq ceiling {_GROQ_REQUEST_TOKEN_CEILING}) for "
        "openai/gpt-oss-120b — trim the occasion additions to Layer 1 (the "
        "fold-in text and the occasion prompt belong at Layer 2 instead)"
    )


# --------------------------------------------------------------------------- #
# CR-01 (33-REVIEW.md) — the occasion digest fix: occasion_data (the weekly's #
# full week_data) is now rendered, capped, into the Layer-1 prompt. This must #
# still fit inside the SAME 7,200-token target, and a PATHOLOGICALLY large    #
# occasion_data (hundreds of training_log entries) must not blow it — the    #
# digest is count/scalar-based, not a dump of the source lists.              #
# --------------------------------------------------------------------------- #


def _build_pathological_weekly_occasion_data(n_sessions: int = 300) -> dict:
    """A deliberately oversized ``week_data``-shaped occasion_data — WAY past
    anything a real week could produce (a real week has <= ~14 sessions) — to
    prove the digest's cost does NOT scale with source-data size."""
    training_log = [
        {
            "date": "2026-07-20",
            "quality": "grind" if i % 3 == 0 else "solid",
            "session_id": f"sess-{i}",
            "modality": "run",
            "notes": "A " * 100,  # pathologically long free-text field
        }
        for i in range(n_sessions)
    ]
    projections = {
        facet: {
            "facet": facet,
            "confidence": "high",
            "data_point_count": 10,
            "on_track": i % 2 == 0,
            "gap": 1.23,
            "projected_value": 100.0,
            "target_value": 105.0,
            "target_date": "2026-12-31",
            "unit": "kg",
            "confidence_label": "high confidence",
        }
        for i, facet in enumerate(
            ["bench_press_1rm", "squat_1rm", "threshold_pace", "push_ups", "pull_ups"]
        )
    }
    coaching_topics_included = [
        f"structural-critique:{'x' * 200}:{i}" for i in range(50)  # pathologically long keys
    ]
    return {
        "training_log": training_log,
        "training_log_error": False,
        "projections": projections,
        "coaching_topics_included": coaching_topics_included,
    }


def test_maximal_occasion_triage_prompt_with_digest_fits_groq_ceiling():
    """CR-01 — with a PATHOLOGICALLY oversized occasion_data merged in (far
    beyond any real week), the rendered digest must still keep the maximal
    occasion triage prompt under the same 7,200-token design target."""
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)

    triage_system = autonomous._load_prompt("prompts/autonomous_triage.md")
    occasion_prompt = autonomous._load_prompt("prompts/weekly_occasion.md")
    situation = _build_maximal_occasion_fixture_situation(now)
    situation.update(_build_pathological_weekly_occasion_data())

    user_msg = autonomous._build_triage_prompt(
        situation, triage_system, occasion_prompt=occasion_prompt,
    )

    assert "Occasion digest:" in user_msg

    system_tokens = _count_tokens(triage_system)
    user_tokens = _count_tokens(user_msg)
    total = system_tokens + user_tokens + _TICK_BRAIN_MAX_TOKENS

    assert total <= _GROQ_REQUEST_TOKEN_TARGET, (
        f"maximal OCCASION triage prompt+completion budget {total} tokens "
        f"(system={system_tokens}, user={user_tokens}, "
        f"completion={_TICK_BRAIN_MAX_TOKENS}) exceeds the {_GROQ_REQUEST_TOKEN_TARGET}-"
        f"token design target with the CR-01 occasion digest rendered — the "
        "digest must be shrunk, never the 7,200 target raised"
    )


def test_tick_path_token_total_unchanged_by_cr01():
    """CR-01 — a plain */20 tick (no ``occasion`` key) must render a
    byte-identical prompt after the CR-01 fix; its token total is unchanged."""
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)
    triage_system = autonomous._load_prompt("prompts/autonomous_triage.md")
    tick_situation = _build_maximal_fixture_situation(now)

    user_msg = autonomous._build_triage_prompt(tick_situation, triage_system)

    assert "Occasion digest:" not in user_msg
    system_tokens = _count_tokens(triage_system)
    user_tokens = _count_tokens(user_msg)
    total = system_tokens + user_tokens + _TICK_BRAIN_MAX_TOKENS

    # Same assertion/target as test_maximal_triage_prompt_fits_groq_ceiling —
    # this test's purpose is the *unchanged* claim, verified by the
    # unconditional presence of the three tick-only keys below.
    assert total <= _GROQ_REQUEST_TOKEN_TARGET

    for key in ("unread_email_count", "meals_since_last_tick", "hours_since_contact"):
        assert f'"{key}"' in user_msg, (
            f"tick path must still render {key!r} — CR-01 only drops it on occasion runs"
        )


def test_occasion_path_drops_tick_only_keys():
    """CR-01 — the three tick-only keys (meaningless on a scheduled occasion)
    are absent from the occasion snapshot, present on the tick path."""
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)
    triage_system = autonomous._load_prompt("prompts/autonomous_triage.md")

    occasion_situation = _build_maximal_occasion_fixture_situation(now)
    occasion_prompt = autonomous._load_prompt("prompts/weekly_occasion.md")
    occasion_user_msg = autonomous._build_triage_prompt(
        occasion_situation, triage_system, occasion_prompt=occasion_prompt,
    )

    for key in ("unread_email_count", "meals_since_last_tick", "hours_since_contact"):
        assert f'"{key}"' not in occasion_user_msg, (
            f"{key!r} must be dropped from the occasion snapshot — meaningless "
            "outside the */20 tick cadence"
        )

    tick_situation = _build_maximal_fixture_situation(now)
    tick_user_msg = autonomous._build_triage_prompt(tick_situation, triage_system)
    for key in ("unread_email_count", "meals_since_last_tick", "hours_since_contact"):
        assert f'"{key}"' in tick_user_msg
