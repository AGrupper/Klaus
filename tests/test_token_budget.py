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
server-side for ``openai/gpt-oss-120b``) — not a char-count estimate. The
research notes ~300 tokens of headroom once Phase 32's slots are wired, which
is inside the margin an approximation could false-pass or false-fail.

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
    """Maximal MEM-04 conversation tail: 15 messages, 240 chars each."""
    tail = []
    for i in range(_CONVERSATION_TAIL_MAX_MESSAGES):
        role = "user" if i % 2 == 0 else "assistant"
        filler = f"Message #{i} discussing training load, meals, and schedule conflicts in detail. "
        text = (filler * 4)[:_CONVERSATION_TAIL_MAX_CHARS]
        ts = (now - timedelta(minutes=(_CONVERSATION_TAIL_MAX_MESSAGES - i) * 90)).astimezone(
            timezone.utc
        ).isoformat()
        tail.append({"role": role, "text": text, "ts": ts})
    return tail


def _build_training_reality_fixture(now: datetime) -> dict:
    """Maximal reconciled training_reality: today-3d..tomorrow (5 dates),
    each carrying a terminal evidence-precedence status string (D-01/D-02:
    Garmin/Hevy actual-activity evidence > training_log self-report >
    calendar/planned intent)."""
    today = now.astimezone(_TZ).date()
    statuses = [
        "completed: Easy run 8.2km in 42:15, avg HR 142 (Garmin, same-day match)",
        "completed: Upper body strength, 5 exercises, 41min, 3120kg volume (Hevy)",
        "skipped: rest day per plan, self-reported via training_log, no evidence expected",
        "planned: Interval session (6x800m) scheduled, session not yet due",
        "planned: Long run 18km @ tempo pace, scheduled, session not yet due",
    ]
    return {
        (today + timedelta(days=offset - 3)).isoformat(): statuses[offset]
        for offset in range(_TRAINING_REALITY_WINDOW_DAYS)
    }


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
    calendar = [
        {
            "id": f"evt-{i}",
            "summary": f"Busy-day calendar block #{i} — training/meetings/travel buffer",
            "start": (now + timedelta(hours=i)).astimezone(timezone.utc).isoformat(),
            "end": (now + timedelta(hours=i, minutes=45)).astimezone(timezone.utc).isoformat(),
            "description": "Prep notes and location detail typical of a real invite.",
        }
        for i in range(12)  # a genuinely packed day, not the API's 50-event cap
    ]

    ticktick_overdue = [
        {"title": f"Overdue task #{i} — reply / ship / follow up", "due": "2026-07-15"}
        for i in range(6)
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
        for i in range(3)
    ]

    standing_directives = [
        {
            "id": f"dir-{i}",
            "text": f"Standing directive #{i}: a lasting behavioral wish with real detail.",
            "origin": "user_chat",
            "expires_at": None,
            "condition_text": None,
        }
        for i in range(4)
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
        for i in range(5)
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
        "today_outreach_log": [f"topic-{i}:tick-{i}" for i in range(10)],
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

    assert total <= _GROQ_REQUEST_TOKEN_CEILING, (
        f"maximal triage prompt+completion budget {total} tokens "
        f"(system={system_tokens}, user={user_tokens}, "
        f"completion={_TICK_BRAIN_MAX_TOKENS}) exceeds Groq's "
        f"{_GROQ_REQUEST_TOKEN_CEILING}-token per-request ceiling for "
        "openai/gpt-oss-120b"
    )


def test_conversation_tail_fixture_respects_mem04_caps():
    """Sanity guard on the fixture itself — 15 messages, each <=240 chars."""
    now = datetime(2026, 7, 22, 14, 0, tzinfo=_TZ)
    tail = _build_conversation_tail_fixture(now)
    assert len(tail) == _CONVERSATION_TAIL_MAX_MESSAGES
    assert all(len(m["text"]) <= _CONVERSATION_TAIL_MAX_CHARS for m in tail)


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
    assert all(isinstance(v, str) and v for v in reality.values())
