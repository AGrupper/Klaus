"""Tests for core/weekly_training_review.py — Phase 20 weekly review gather.

Focus: the biometrics + Garmin-activities gather paths, which produced the
"Garmin data unavailable" / empty-biometrics symptom in production.

Root cause covered here:
  - The biometrics SQL selected phantom columns (hrv_status, sleep_hours) that
    do not exist in daily_biometrics, so Postgres rejected the whole query and
    biometrics came back None. The regression guard below asserts the SQL only
    references real columns.

Mock strategy
-------------
_gather_week_data imports its data sources lazily (inside the function), so we
patch the names on their *source* modules. Garmin/Postgres/Firestore are never
touched.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.weekly_training_review as wtr


@pytest.fixture
def patched_sources(monkeypatch):
    """Patch all five gather sources to benign defaults; yield handles so each
    test can override the one it cares about."""
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    handles = {
        "training_log": MagicMock(),
        "fetch_garmin_activities": MagicMock(return_value=[]),
        "query_health_database": MagicMock(return_value=[]),
        "meal_store": MagicMock(),
        "user_profile": MagicMock(),
        # Phase 23 Plan 04 — block + benchmark stores (default: no active block)
        "block_store": MagicMock(),
        "benchmark_store": MagicMock(),
    }
    handles["training_log"].return_value.get_range.return_value = []
    handles["meal_store"].return_value.get_day_aggregate.return_value = None
    handles["user_profile"].return_value.load.return_value = {}
    handles["block_store"].return_value.get_current.return_value = None
    handles["benchmark_store"].return_value.get_block_benchmarks.return_value = []

    with patch("memory.firestore_db.TrainingLogStore", handles["training_log"]), \
         patch("mcp_tools.garmin_tool.fetch_garmin_activities",
               handles["fetch_garmin_activities"]), \
         patch("mcp_tools.database_tool.query_health_database",
               handles["query_health_database"]), \
         patch("memory.firestore_db.MealStore", handles["meal_store"]), \
         patch("memory.firestore_db.UserProfileStore", handles["user_profile"]), \
         patch("memory.firestore_db.BlockStore", handles["block_store"]), \
         patch("memory.firestore_db.BenchmarkStore", handles["benchmark_store"]):
        yield handles


# ---------------------------------------------------------------------------
# Biometrics SQL — regression guard for the phantom-column bug
# ---------------------------------------------------------------------------

def test_biometrics_sql_uses_only_real_columns(patched_sources):
    """The biometrics query must not reference columns absent from
    daily_biometrics. This is the exact bug that returned 'column "hrv_status"
    does not exist' and made biometrics come back empty."""
    wtr._gather_week_data("2026-06-07")  # a Sunday
    sql = patched_sources["query_health_database"].call_args[0][0]
    # Phantom columns that broke the query:
    assert "hrv_status" not in sql
    assert "sleep_hours" not in sql
    # Real daily_biometrics columns that must be present:
    for col in ("hrv_baseline", "hrv_overnight", "sleep_duration",
                "resting_hr", "sleep_score"):
        assert col in sql


def test_biometrics_split_this_vs_last_week(patched_sources):
    """Rows are bucketed into this-week vs last-week by date, and the query
    succeeding means no error sentinel."""
    # today = Sunday 2026-06-07 → _prev_sunday → week 2026-05-31..2026-06-06;
    # last week → 2026-05-24..2026-05-30.
    patched_sources["query_health_database"].return_value = [
        {"date": "2026-06-02", "resting_hr": 40, "sleep_score": 81},  # this week
        {"date": "2026-05-26", "resting_hr": 42, "sleep_score": 70},  # last week
    ]
    data = wtr._gather_week_data("2026-06-07")
    assert [r["date"] for r in data["biometrics_this_week"]] == ["2026-06-02"]
    assert [r["date"] for r in data["biometrics_last_week"]] == ["2026-05-26"]


def test_biometrics_query_error_string_sets_none(patched_sources):
    """If query_health_database returns an error *string* (not a list), both
    biometrics buckets become None rather than raising."""
    patched_sources["query_health_database"].return_value = (
        'Error executing query: column "hrv_status" does not exist'
    )
    data = wtr._gather_week_data("2026-06-07")
    assert data["biometrics_this_week"] is None
    assert data["biometrics_last_week"] is None


# ---------------------------------------------------------------------------
# Garmin activities — split + graceful degradation
# ---------------------------------------------------------------------------

def test_garmin_activities_split_and_no_error(patched_sources):
    """Activities split across this/last week; garmin_error stays False on success."""
    patched_sources["fetch_garmin_activities"].return_value = [
        {"date": "2026-06-02T18:30:00", "type": "running", "training_load": 6.0},
        {"date": "2026-05-26T19:00:00", "type": "strength_training", "training_load": 3.0},
    ]
    data = wtr._gather_week_data("2026-06-07")
    assert data["garmin_error"] is False
    assert [a["date"][:10] for a in data["activities"]] == ["2026-06-02"]
    assert [a["date"][:10] for a in data["last_week_activities"]] == ["2026-05-26"]


def test_garmin_activities_failure_sets_error_flag(patched_sources):
    """fetch_garmin_activities raising → garmin_error True, gather still returns."""
    patched_sources["fetch_garmin_activities"].side_effect = RuntimeError("garmin down")
    data = wtr._gather_week_data("2026-06-07")
    assert data["garmin_error"] is True
    assert data["activities"] is None
    assert data["last_week_activities"] is None
    # Other sources are unaffected — the gather is best-effort per-source.
    assert "biometrics_this_week" in data


# ---------------------------------------------------------------------------
# v3.0 cron regression — Phase 21 Plan 04 guard
# ---------------------------------------------------------------------------

def test_weekly_review_athletic_goals_from_full_v4_schema(patched_sources):
    """Weekly review gather resolves athletic_goals from a full v4.0 schema profile
    without raising. The new structured keys (dated_goals, weekly_split, etc.) must
    not break the athletic_goals fetch path.

    Regression guard: Plan 21 expanded UserProfileStore._SCAFFOLD with new structured
    fields. The weekly review reads only profile.get("athletic_goals") — it must
    tolerate all new keys silently (athletic_goals retained per Plan 01).
    """
    full_v4_profile = {
        "athletic_goals": ["Run half-marathon under 1:30", "100kg bench press"],
        "dated_goals": [
            {"goal_label": "Oct peak", "target_date": "2026-10-01",
             "metrics": ["100kg bench", "120kg squat", "1:25 HM"]},
            {"goal_label": "Nov peak", "target_date": "2026-11-01",
             "metrics": ["125 push-ups", "35 pull-ups", "9:30 3k", "55s 400m"]},
        ],
        "weekly_split": {
            "Monday": {
                "am": {"label": "Upper strength", "modality": "lift", "priority": "high"},
                "pm": {"label": "Easy run", "modality": "run", "priority": "medium"},
            },
            "Tuesday": {
                "am": {"label": "Rest", "modality": "rest", "priority": "low"},
                "pm": {"label": "Lower strength", "modality": "lift", "priority": "high"},
            },
        },
        "nutrition_targets": {
            "protein_g": 150,
            "carbs_g": 350,
            "fueling_slots": ["pre-workout", "intra-workout", "post-workout"],
        },
        "supplement_schedule": [
            {"slot": "morning", "items": ["creatine", "vitamin D"]},
            {"slot": "pre-workout", "items": ["beta-alanine"]},
        ],
        "fueling_timeline": [
            {"timing": "07:00", "food": "oats + protein shake"},
            {"timing": "pre-workout", "food": "banana + energy gel"},
            {"timing": "post-workout", "food": "rice + chicken"},
        ],
        "plan_start_date": "2026-06-21",
        "training_constraints": ["no back squats during deload"],
        "recovery_preferences": {"min_sleep_hours": 7},
        "schema_version": 2,
    }
    patched_sources["user_profile"].return_value.load.return_value = full_v4_profile

    # Should not raise; athletic_goals resolves correctly from the full schema
    data = wtr._gather_week_data("2026-06-07")

    assert "athletic_goals" in data
    assert data["athletic_goals"] == ["Run half-marathon under 1:30", "100kg bench press"]


def test_weekly_review_athletic_goals_absent_in_v4_schema(patched_sources):
    """If profile has v4.0 structured fields but no athletic_goals key,
    the gather returns an empty list (default) without raising — defensive .get().
    """
    v4_profile_no_legacy = {
        "dated_goals": [{"goal_label": "Oct peak", "target_date": "2026-10-01", "metrics": []}],
        "plan_start_date": "2026-06-21",
        "schema_version": 2,
    }
    patched_sources["user_profile"].return_value.load.return_value = v4_profile_no_legacy

    data = wtr._gather_week_data("2026-06-07")

    # athletic_goals absent → defaults to [] without KeyError
    assert data["athletic_goals"] == []


# ---------------------------------------------------------------------------
# Phase 23 Plan 04 — block + benchmark gather (BLOCK-01 / BLOCK-03)
# ---------------------------------------------------------------------------

_FACETS = ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"]


def _wtr_block(label="Capacity Build", end_date="2026-08-15",
               start_date="2026-07-19", doc_id="2026-07-19_capacity_build"):
    return {
        "doc_id": doc_id,
        "block_id": doc_id,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "focus_facets": list(_FACETS),
        "status": "active",
        "benchmark_due": False,
    }


def test_gather_week_includes_current_block(patched_sources):
    """BLOCK-01/BLOCK-03: an active block surfaces current_block (with week_num)
    and block_benchmarks from the store."""
    patched_sources["block_store"].return_value.get_current.return_value = _wtr_block()
    benches = [{"facet": "bench_press_1rm", "value": 92.0, "date": "2026-08-10"}]
    patched_sources["benchmark_store"].return_value.get_block_benchmarks.return_value = benches
    data = wtr._gather_week_data("2026-08-09")  # a Sunday inside Block 2
    assert data["current_block"] is not None
    assert data["current_block"]["label"] == "Capacity Build"
    assert "week_num" in data["current_block"]
    assert data["block_benchmarks"] == benches


def test_gather_week_precycle(patched_sources):
    """Pre-cycle (before 2026-06-21): pre_cycle_countdown set, current_block None."""
    # default fixture get_current → None
    data = wtr._gather_week_data("2026-06-07")  # a Sunday before the anchor
    assert data["current_block"] is None
    assert data.get("pre_cycle_countdown") == (
        __import__("datetime").date(2026, 6, 21) - __import__("datetime").date(2026, 6, 7)
    ).days


def test_gather_week_block_failure_sets_defaults(patched_sources):
    """Pitfall 4: a store failure defaults current_block None + block_benchmarks []."""
    patched_sources["block_store"].return_value.get_current.side_effect = RuntimeError("down")
    data = wtr._gather_week_data("2026-08-09")
    assert data["current_block"] is None
    assert data["block_benchmarks"] == []


# ---------------------------------------------------------------------------
# Phase 24 Plan 05 — dedup gate + {coaching_guide} + per-facet + quality trend
# (COACH-05, PROG-01, PROG-04, D-17)
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_sources_with_coaching(patched_sources, monkeypatch):
    """Extend patched_sources with a CoachingTopicStore mock."""
    coaching_store = MagicMock()
    coaching_store.return_value.topics_today.return_value = []
    patched_sources["coaching_topic_store"] = coaching_store
    with patch("memory.firestore_db.CoachingTopicStore", coaching_store):
        yield patched_sources


def test_gather_week_includes_coaching_topics_today(patched_sources_with_coaching):
    """COACH-05: _gather_week_data (or run_weekly_review) sets coaching_topics_today."""
    patched_sources_with_coaching["coaching_topic_store"].return_value.topics_today.return_value = [
        "structural-critique:protein-target"
    ]
    data = wtr._gather_week_data("2026-06-07")
    assert "coaching_topics_today" in data
    assert data["coaching_topics_today"] == ["structural-critique:protein-target"]


def test_gather_week_coaching_topics_fail_open(patched_sources):
    """COACH-05: CoachingTopicStore failure → coaching_topics_today = [] (fail-open)."""
    with patch("memory.firestore_db.CoachingTopicStore", side_effect=RuntimeError("firestore down")):
        data = wtr._gather_week_data("2026-06-07")
    assert data.get("coaching_topics_today") == []


def test_compose_review_injects_coaching_guide(patched_sources_with_coaching):
    """PROG-01 / D-17: _compose_review injects {coaching_guide} into the system prompt."""
    # Capture the system prompt sent to the LLM
    captured_prompts = []

    mock_client = MagicMock()
    mock_client.chat.side_effect = lambda messages, system, **kw: (
        captured_prompts.append(system) or {"text": "Review text", "tool_calls": [], "stop_reason": "end_turn"}
    )

    coaching_guide_content = "## Slim Coaching Core\nAll about periodization."

    mock_orchestrator = MagicMock()
    mock_orchestrator._coaching_guide_content = coaching_guide_content

    with patch("core.llm_client.LLMClient", return_value=mock_client), \
         patch("pathlib.Path.read_text", return_value="System prompt {coaching_guide} end"), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("core.autonomous._get_orchestrator", return_value=mock_orchestrator):
        wtr._compose_review({}, "2026-06-07")

    assert captured_prompts, "No system prompt captured — _compose_review did not call LLM"
    assert coaching_guide_content in captured_prompts[0], (
        "{coaching_guide} placeholder was not replaced with coaching guide content"
    )


def test_run_weekly_review_writes_topics_after_send():
    """T-24-17: add_topic called only after successful send_and_inject (write-after-send)."""
    import asyncio
    from unittest.mock import AsyncMock

    add_topic_calls = []

    mock_cts_instance = MagicMock()
    mock_cts_instance.add_topic.side_effect = lambda d, t: add_topic_calls.append((d, t))
    mock_cts_class = MagicMock(return_value=mock_cts_instance)

    week_data_with_topics = {
        "coaching_topics_today": [],
        "coaching_topics_included": ["structural-critique:protein-target"],
    }

    bot = AsyncMock()

    with patch("core.weekly_training_review._gather_week_data", return_value=week_data_with_topics), \
         patch("core.weekly_training_review._compose_review", return_value="Review text"), \
         patch("core.scheduled_message.send_and_inject", new_callable=AsyncMock) as mock_send, \
         patch("memory.firestore_db.CoachingTopicStore", mock_cts_class):
        asyncio.run(wtr.run_weekly_review(bot, "2026-06-07"))

    mock_send.assert_called_once()
    assert len(add_topic_calls) == 1
    assert ("2026-06-07", "structural-critique:protein-target") in add_topic_calls


def test_run_weekly_review_no_topic_write_when_send_fails():
    """T-24-17: add_topic must NOT be called if send_and_inject raises."""
    import asyncio
    from unittest.mock import AsyncMock

    add_topic_calls = []

    mock_cts_instance = MagicMock()
    mock_cts_instance.add_topic.side_effect = lambda d, t: add_topic_calls.append((d, t))
    mock_cts_class = MagicMock(return_value=mock_cts_instance)

    week_data_with_topics = {
        "coaching_topics_included": ["structural-critique:protein-target"],
    }

    bot = AsyncMock()

    with patch("core.weekly_training_review._gather_week_data", return_value=week_data_with_topics), \
         patch("core.weekly_training_review._compose_review", return_value="Review text"), \
         patch("core.scheduled_message.send_and_inject",
               new_callable=AsyncMock, side_effect=RuntimeError("telegram down")), \
         patch("memory.firestore_db.CoachingTopicStore", mock_cts_class):
        try:
            asyncio.run(wtr.run_weekly_review(bot, "2026-06-07"))
        except RuntimeError:
            pass  # send failure propagates — that is expected

    # No topic writes should have happened
    assert add_topic_calls == []


def test_weekly_review_prompt_has_per_facet_instruction():
    """PROG-01 / D-17: prompt must instruct per-facet within-block reporting."""
    content = open("prompts/weekly_training_review.md").read()
    lower = content.lower()
    assert any(kw in lower for kw in ["facet", "top-set", "acwr", "threshold volume"]), (
        "prompts/weekly_training_review.md missing per-facet within-block framing"
    )


def test_weekly_review_prompt_has_quality_trend_instruction():
    """PROG-04 / D-17: prompt must instruct session quality trend reporting."""
    content = open("prompts/weekly_training_review.md").read()
    lower = content.lower()
    assert any(kw in lower for kw in ["quality", "strong", "neutral", "grind"]), (
        "prompts/weekly_training_review.md missing session quality trend instruction"
    )


def test_weekly_review_prompt_forbids_dated_projection():
    """Phase 25 fence: prompt must not introduce dated-projection language as instructions."""
    content = open("prompts/weekly_training_review.md").read()
    lower = content.lower()
    # If "weeks behind" or "on track for" appears, it must be inside a "do NOT" prohibition
    for phrase in ["weeks behind", "on track for"]:
        if phrase in lower:
            # Find the context — look for a nearby "do not" or "never" or "not project"
            idx = lower.index(phrase)
            context_window = lower[max(0, idx - 120):idx + 60]
            assert any(neg in context_window for neg in ["do not", "never", "not project", "forbid", "prohibited"]), (
                f"Dated projection phrase '{phrase}' found in prompt without a prohibition clause — "
                "Phase 25 fence violated"
            )
