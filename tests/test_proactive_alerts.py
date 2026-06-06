# tests/test_proactive_alerts.py
from __future__ import annotations

import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Must import the module before any @patch decorators reference it,
# otherwise Python can't resolve "core.proactive_alerts.<attr>" at decoration time.
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
import core.proactive_alerts  # noqa: E402  (side-effect import for patch resolution)


@pytest.fixture(autouse=True)
def _restore_environ():
    """Snapshot/restore os.environ around every test.

    run_proactive_alerts constructs Firestore-backed stores, and
    _make_firestore_client runs load_dotenv(override=True) — which leaks
    GCP_PROJECT_ID from .env into os.environ. Without this fixture that leak
    bleeds into later tests whose training check-in then attempts real Firestore
    I/O. Restoring the snapshot keeps each test isolated.
    """
    snap = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snap)


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@patch("core.proactive_alerts._already_sent", return_value=True)
def test_skips_when_already_sent(mock_already_sent, mock_bot):
    """No Telegram send if we already processed this date."""
    from core.proactive_alerts import run_proactive_alerts
    asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_not_called()


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts", return_value=[])
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_no_alerts_marks_processed_no_send(
    mock_cal, mock_home, mock_weather, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """If no issues found, mark processed with alert_sent=False and don't send."""
    mock_cal.return_value.list_events.return_value = []
    # fetch_weather is imported locally inside run_proactive_alerts;
    # patch at source module so the local import gets the mock.
    with patch("mcp_tools.weather_tool.fetch_weather", side_effect=Exception("no weather")):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_not_called()
    mock_mark.assert_called_once_with("2026-05-12", alert_sent=False)


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_sends_telegram_when_alerts_found(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """When alerts detected, send Telegram and mark processed with alert_sent=True."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    # Patch _compose_alert directly so the test exercises the send path,
    # not the fallback path, regardless of env vars.
    with patch("core.proactive_alerts._compose_alert", return_value="LLM-produced alert text"):
        with patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
            from core.proactive_alerts import run_proactive_alerts
            asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_called_once()
    call_text = mock_bot.send_message.call_args.kwargs.get("text", "")
    assert call_text == "LLM-produced alert text"
    mock_mark.assert_called_once_with("2026-05-12", alert_sent=True)


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_plain_text_fallback_on_llm_failure(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """If LLM composition fails, fall back to plain text (still sends)."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    # LLMClient is imported locally inside _compose_alert; patch at source module
    with patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        with patch("core.llm_client.LLMClient", side_effect=Exception("LLM down")):
            from core.proactive_alerts import run_proactive_alerts
            asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))
    mock_bot.send_message.assert_called_once()
    # Should still have sent something (plain-text fallback)
    call_text = mock_bot.send_message.call_args.kwargs.get("text", "")
    assert call_text.startswith("Tomorrow (2026-05-12) — heads up, Sir:")


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_recovery_concern_injected_into_alert_context(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """RECOVERY-03 / D-16: when compute_recovery_concern returns a concern, it is
    injected into the alerts_context handed to _compose_alert (evening path parity
    with the morning briefing)."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    concern = {"level": "strong", "acwr": 1.6, "hrv_status": "unbalanced",
               "sleep_score": 52, "intensity": "high"}
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return "LLM-produced alert text"

    # compute_recovery_concern + fetch_garmin_today are imported locally inside
    # run_proactive_alerts; patch at their source modules so the local imports resolve.
    with patch("core.training_checkin.compute_recovery_concern", return_value=concern), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value={"date": "2026-05-12"}), \
         patch("core.proactive_alerts._compose_alert", side_effect=_capture), \
         patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))

    assert captured["ctx"].get("recovery_concern") == concern
    mock_bot.send_message.assert_called_once()


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts")
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_no_recovery_concern_key_when_none(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """D-13 no-fabrication: when compute_recovery_concern returns None, the
    recovery_concern key is absent from alerts_context (no 'all clear' placeholder)."""
    mock_cal.return_value.list_events.return_value = []
    mock_weather_fn.return_value = [
        {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
    ]
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return "LLM-produced alert text"

    with patch("core.training_checkin.compute_recovery_concern", return_value=None), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value={"date": "2026-05-12"}), \
         patch("core.proactive_alerts._compose_alert", side_effect=_capture), \
         patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-05-12"))

    assert "recovery_concern" not in captured["ctx"]


# ====================================================================== #
# Phase 23 Plan 03 — end-of-block benchmark trigger (BLOCK-02)            #
# ====================================================================== #

# NOTE: GCP_PROJECT_ID is deliberately NOT set at module scope — the existing tests
# rely on it being unset so the top-of-function training check-in no-ops. The two
# integration tests below scope it locally via patch.dict and neutralize the check-in.

_FACETS = ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"]


def _block(
    *,
    label="Aerobic Base",
    start_date="2026-06-21",
    end_date="2026-07-18",
    benchmark_due=False,
    doc_id="2026-06-21_aerobic_base",
):
    return {
        "doc_id": doc_id,
        "block_id": doc_id,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "focus_facets": list(_FACETS),
        "status": "active",
        "benchmark_due": benchmark_due,
    }


class TestEvaluateBenchmarkState:
    """Unit tests for the pure _evaluate_benchmark_state state machine (D-02/D-07/D-08/D-09)."""

    def test_no_benchmark_due_block_4(self):
        """D-02: Block 4 (race week) never benchmarks, even within 3 days."""
        from core.proactive_alerts import _evaluate_benchmark_state
        b = _block(label="Race Specificity → Taper → Race Week", end_date="2026-10-10")
        assert _evaluate_benchmark_state(b, "2026-10-09", 75, 80, 1.0) is None

    def test_more_than_3_days_returns_none(self):
        from core.proactive_alerts import _evaluate_benchmark_state
        assert _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-10", 75, 80, 1.0) is None

    def test_none_block_returns_none(self):
        from core.proactive_alerts import _evaluate_benchmark_state
        assert _evaluate_benchmark_state(None, "2026-07-16", 75, 80, 1.0) is None

    def test_validity_gate_pass(self):
        """benchmark_due + HRV 70/80 (87.5%) + ACWR 1.0 → window_open."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 70, 80, 1.0)
        assert s and s["state"] == "benchmark_window_open"
        assert s["facets"] == _FACETS

    def test_validity_gate_fail_hrv(self):
        """HRV 55/80 (68.75% < 70%) → deferred."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 55, 80, 1.0)
        assert s and s["state"] == "benchmark_deferred"

    def test_validity_gate_fail_acwr(self):
        """ACWR 1.35 (> 1.2) → deferred even with good HRV."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 75, 80, 1.35)
        assert s and s["state"] == "benchmark_deferred"

    def test_stale_window(self):
        """today > end_date with red gate → stale (one caveated prompt, D-09)."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-19", 55, 80, 1.35)
        assert s and s["state"] == "benchmark_stale"

    def test_gate_unknown_passes(self):
        """Missing hrv_baseline → gate unknown → PASS (err toward prompting)."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 75, None, None)
        assert s and s["state"] == "benchmark_window_open"

    def test_deferred_message_has_number(self):
        """D-08: deferred payload carries hrv_overnight + % of baseline for the numeric reason."""
        from core.proactive_alerts import _evaluate_benchmark_state
        s = _evaluate_benchmark_state(_block(end_date="2026-07-18"), "2026-07-16", 55, 80, 1.0)
        assert s["hrv_overnight"] == 55
        assert s["hrv_pct"] == round(55 / 80 * 100)  # 69


def _near_end_block1():
    """Block 1 whose end_date is 2 days from now (Asia/Jerusalem)."""
    from core.proactive_alerts import _TZ
    from datetime import datetime as _dt, timedelta as _td
    end = (_dt.now(_TZ).date() + _td(days=2)).isoformat()
    return _block(end_date=end)


@patch("core.proactive_alerts._already_sent", return_value=True)
def test_benchmark_check_before_dedup_gate(mock_already_sent, mock_bot):
    """Pitfall 3 / T-23-11: set_benchmark_due runs BEFORE the _already_sent gate,
    so the flag is still set even when the cron already sent for this date."""
    mock_bs = MagicMock()
    mock_bs.return_value.get_current.return_value = _near_end_block1()
    with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project"}), \
         patch("core.training_checkin.run_training_checkin", new=AsyncMock()), \
         patch("memory.firestore_db.BlockStore", mock_bs):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2026-07-16"))
    mock_bs.return_value.set_benchmark_due.assert_called_once()


@patch("core.proactive_alerts._mark_processed")
@patch("core.proactive_alerts._already_sent", return_value=False)
@patch("core.proactive_alerts._detect_travel_issues", return_value=[])
@patch("core.proactive_alerts._detect_overloaded_day", return_value=None)
@patch("core.proactive_alerts._detect_weather_conflicts", return_value=[])
@patch("core.proactive_alerts._home_address", return_value="Tel Aviv")
@patch("core.proactive_alerts._get_calendar_tool")
def test_benchmark_only_night_still_sends(
    mock_cal, mock_home, mock_weather_fn, mock_overload, mock_travel,
    mock_already_sent, mock_mark, mock_bot
):
    """BLOCK-02 SC / T-23-10: a benchmark-only deload night (no weather/overload/travel
    alert) must NOT hit the no-alert early return — it still composes and sends."""
    mock_cal.return_value.list_events.return_value = []
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return "LLM alert text"

    mock_bs = MagicMock()
    mock_bs.return_value.get_current.return_value = _near_end_block1()
    with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project"}), \
         patch("core.training_checkin.run_training_checkin", new=AsyncMock()), \
         patch("memory.firestore_db.BlockStore", mock_bs), \
         patch("mcp_tools.garmin_tool.fetch_garmin_today",
               return_value={"hrv_overnight": 75, "hrv_baseline": 80}), \
         patch("mcp_tools.garmin_tool.compute_acwr_from_db", return_value={"ratio": 1.0}), \
         patch("core.training_checkin.compute_recovery_concern", return_value=None), \
         patch("core.proactive_alerts._compose_alert", side_effect=_capture), \
         patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}):
        from core.proactive_alerts import run_proactive_alerts
        asyncio.run(run_proactive_alerts(mock_bot, "2099-01-01"))

    assert captured.get("ctx", {}).get("benchmark", {}).get("state") == "benchmark_window_open"
    mock_bot.send_message.assert_called_once()


# ====================================================================== #
# Phase 24 Plan 02 — Nutrition accountability pure functions              #
# NUTR-01: macro-gap detection (Task 1)                                   #
# NUTR-02/03: slot mapping, miss detection, supplement riders (Task 2)    #
# ====================================================================== #


class TestMacroGapCheck:
    """Unit tests for _macro_gap_check (NUTR-01) — pure function, no I/O."""

    def test_protein_below_floor_returns_flag(self):
        """protein 110g < 120g floor → protein-miss flag (NUTR-01, D-09)."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 110, "carbs_g": 300},
            day_type="normal",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        assert len(flags) == 1
        flag = flags[0]
        assert flag["topic_key"] == "protein-miss"
        assert "severity" in flag
        assert "description" in flag
        # Description must name the real number and the target
        assert "110" in flag["description"]
        assert "150" in flag["description"]

    def test_protein_marginal_shortfall_no_flag(self):
        """protein 145g — marginal shortfall, NOT flagged (D-09 rule)."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 145, "carbs_g": 300},
            day_type="normal",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        protein_flags = [f for f in flags if f["topic_key"] == "protein-miss"]
        assert protein_flags == [], "Marginal shortfall must NOT produce a flag (D-09)"

    def test_protein_meets_floor_no_flag(self):
        """protein 120g (exactly at floor) → no flag."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 120, "carbs_g": 300},
            day_type="normal",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        protein_flags = [f for f in flags if f["topic_key"] == "protein-miss"]
        assert protein_flags == []

    def test_carbs_below_normal_floor_returns_flag(self):
        """carbs 240g < 250g normal floor → carb-miss flag."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 130, "carbs_g": 240},
            day_type="normal",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        carb_flags = [f for f in flags if "carb-miss" in f["topic_key"]]
        assert len(carb_flags) == 1

    def test_carbs_normal_day_290g_no_flag(self):
        """carbs 290g on a normal day → no flag (long-run floor only applies to long_run)."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 130, "carbs_g": 290},
            day_type="normal",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        carb_flags = [f for f in flags if "carb-miss" in f["topic_key"]]
        assert carb_flags == []

    def test_carbs_long_run_day_290g_returns_flag(self):
        """carbs 290g on long_run day (< 300g floor) → carb-miss:long-run-day flag."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 130, "carbs_g": 290},
            day_type="long_run",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        carb_flags = [f for f in flags if "carb-miss" in f["topic_key"]]
        assert len(carb_flags) == 1
        assert "long-run-day" in carb_flags[0]["topic_key"]

    def test_deload_day_carbs_210g_no_flag(self):
        """carbs 210g on a deload day (> 200g floor) → no flag."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 130, "carbs_g": 210},
            day_type="deload",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        carb_flags = [f for f in flags if "carb-miss" in f["topic_key"]]
        assert carb_flags == []

    def test_deload_day_carbs_190g_returns_flag(self):
        """carbs 190g on a deload day (< 200g floor) → carb-miss flag."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 130, "carbs_g": 190},
            day_type="deload",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        carb_flags = [f for f in flags if "carb-miss" in f["topic_key"]]
        assert len(carb_flags) == 1

    def test_all_met_returns_empty(self):
        """All macros met → empty list returned."""
        from core.proactive_alerts import _macro_gap_check
        flags = _macro_gap_check(
            totals={"protein_g": 155, "carbs_g": 360},
            day_type="normal",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        assert flags == []

    def test_macro_thresholds_dict_exists(self):
        """MACRO_THRESHOLDS module-level dict must exist."""
        import core.proactive_alerts as pa
        assert hasattr(pa, "MACRO_THRESHOLDS"), "MACRO_THRESHOLDS must be defined at module level"
        t = pa.MACRO_THRESHOLDS
        assert "protein" in t
        assert "carbs" in t

    def test_no_io_in_macro_gap_check(self):
        """_macro_gap_check must be callable with no env vars and no external calls."""
        # Should not raise even with no GCP env vars set
        from core.proactive_alerts import _macro_gap_check
        result = _macro_gap_check(
            totals={"protein_g": 100, "carbs_g": 200},
            day_type="rest",
            targets={"protein_g": 150, "carbs_g": 350},
        )
        # rest day uses deload floor (200g for carbs); 200g == floor → no carb flag
        # protein 100g < 120g → protein-miss
        assert isinstance(result, list)
        protein_flags = [f for f in result if f["topic_key"] == "protein-miss"]
        assert len(protein_flags) == 1


class TestSlotMappingAndMissDetection:
    """Unit tests for _resolve_anchor_times, _map_meals_to_slots, _detect_slot_misses (NUTR-02/03)."""

    def _make_meal(self, ts_iso: str) -> dict:
        return {
            "timestamp": ts_iso,
            "protein_g": 30,
            "carbs_g": 50,
            "fat_g": 10,
            "fiber_g": 3,
            "calories": 410,
            "meal_type": 1,
            "food_item": "Test meal",
        }

    # --- _resolve_anchor_times ---

    def test_resolve_anchor_garmin_running_activity(self):
        """AM anchor resolved from Garmin running activity (priority 1)."""
        from core.proactive_alerts import _resolve_anchor_times
        activities = [
            {"type": "running", "date": "2026-06-06T07:15:00", "activity_id": "a1"},
        ]
        am, pm = _resolve_anchor_times("2026-06-06", activities, [])
        assert am is not None
        assert am.hour == 7 and am.minute == 15

    def test_resolve_anchor_trail_running(self):
        """trail_running type also resolves AM anchor."""
        from core.proactive_alerts import _resolve_anchor_times
        activities = [
            {"type": "trail_running", "date": "2026-06-06T06:45:00", "activity_id": "a1"},
        ]
        am, _ = _resolve_anchor_times("2026-06-06", activities, [])
        assert am is not None

    def test_resolve_anchor_garmin_strength_pm(self):
        """PM anchor resolved from Garmin strength_training activity (priority 1)."""
        from core.proactive_alerts import _resolve_anchor_times
        activities = [
            {"type": "strength_training", "date": "2026-06-06T19:00:00", "activity_id": "a2"},
        ]
        _, pm = _resolve_anchor_times("2026-06-06", activities, [])
        assert pm is not None
        assert pm.hour == 19

    def test_resolve_anchor_calendar_run_event(self):
        """AM anchor resolved from calendar event with 'run' in summary (priority 2)."""
        from core.proactive_alerts import _resolve_anchor_times
        events = [
            {"summary": "Morning run", "start": "2026-06-06T07:30:00"},
        ]
        am, _ = _resolve_anchor_times("2026-06-06", [], events)
        assert am is not None

    def test_resolve_anchor_rest_day_none(self):
        """Rest day with no activities and no calendar events → both anchors None."""
        from core.proactive_alerts import _resolve_anchor_times
        am, pm = _resolve_anchor_times("2026-06-06", [], [])
        assert am is None
        assert pm is None

    # --- _detect_slot_misses ---

    def test_slot_miss_post_am_run_detected(self):
        """AM anchor present, no meal in [anchor+15m, anchor+90m] → post-am-run miss."""
        from core.proactive_alerts import _detect_slot_misses
        from datetime import datetime as _dt
        am_anchor = _dt(2026, 6, 6, 7, 15)
        # Meal at 06:00 — outside the post-run reload window
        meals = [self._make_meal("2026-06-06T06:00:00")]
        misses = _detect_slot_misses(meals, am_anchor, None, "2026-06-06")
        assert "post-am-run" in misses

    def test_slot_no_miss_when_meal_in_post_am_run_window(self):
        """Meal in [anchor+15m, anchor+90m] → no post-am-run miss."""
        from core.proactive_alerts import _detect_slot_misses
        from datetime import datetime as _dt
        am_anchor = _dt(2026, 6, 6, 7, 15)
        # Meal at 07:45 = anchor+30m → inside the window
        meals = [self._make_meal("2026-06-06T07:45:00")]
        misses = _detect_slot_misses(meals, am_anchor, None, "2026-06-06")
        assert "post-am-run" not in misses

    def test_rest_day_no_am_anchor_no_post_am_run_miss(self):
        """Pitfall 2: am_anchor is None → post-am-run must NOT fire (D-10)."""
        from core.proactive_alerts import _detect_slot_misses
        meals = []  # No meals on a rest day
        misses = _detect_slot_misses(meals, None, None, "2026-06-06")
        assert "post-am-run" not in misses, "post-am-run must NOT fire when am_anchor is None"
        assert "pm-post-lift" not in misses, "pm-post-lift must NOT fire when pm_anchor is None"

    def test_rest_day_pre_bed_can_still_fire(self):
        """pre-bed fires on rest day when no meal in 21:00–23:59 window (slot #6 is always checked)."""
        from core.proactive_alerts import _detect_slot_misses
        # Only meal is at 18:00 — before the pre-bed window
        meals = [self._make_meal("2026-06-06T18:00:00")]
        misses = _detect_slot_misses(meals, None, None, "2026-06-06")
        assert "pre-bed" in misses

    def test_pre_bed_no_miss_when_meal_in_window(self):
        """pre-bed does NOT fire when a meal falls in 21:00–23:59."""
        from core.proactive_alerts import _detect_slot_misses
        meals = [self._make_meal("2026-06-06T21:30:00")]
        misses = _detect_slot_misses(meals, None, None, "2026-06-06")
        assert "pre-bed" not in misses

    def test_pm_post_lift_miss_detected(self):
        """PM anchor present, no meal in [anchor+15m, anchor+90m] → pm-post-lift miss."""
        from core.proactive_alerts import _detect_slot_misses
        from datetime import datetime as _dt
        pm_anchor = _dt(2026, 6, 6, 19, 0)
        # Meal at 16:00 — outside the post-lift window
        meals = [self._make_meal("2026-06-06T16:00:00")]
        misses = _detect_slot_misses(meals, None, pm_anchor, "2026-06-06")
        assert "pm-post-lift" in misses

    def test_no_pm_post_lift_miss_when_pm_anchor_none(self):
        """Pitfall 2: pm_anchor is None → pm-post-lift must NOT fire."""
        from core.proactive_alerts import _detect_slot_misses
        meals = []
        misses = _detect_slot_misses(meals, None, None, "2026-06-06")
        assert "pm-post-lift" not in misses

    # --- _map_meals_to_slots ---

    def test_map_meals_post_am_run_slot(self):
        """Meal in [anchor+15m, anchor+90m] → appears in post-am-run slot."""
        from core.proactive_alerts import _map_meals_to_slots
        from datetime import datetime as _dt
        am_anchor = _dt(2026, 6, 6, 7, 15)
        meal = self._make_meal("2026-06-06T07:45:00")
        slot_map = _map_meals_to_slots([meal], am_anchor, None)
        assert "post-am-run" in slot_map
        assert len(slot_map["post-am-run"]) == 1

    def test_map_meals_pre_bed_slot_fixed_window(self):
        """Meal in 21:00–23:59 → appears in pre-bed slot."""
        from core.proactive_alerts import _map_meals_to_slots
        meal = self._make_meal("2026-06-06T22:00:00")
        slot_map = _map_meals_to_slots([meal], None, None)
        assert "pre-bed" in slot_map
        assert len(slot_map["pre-bed"]) == 1

    # --- SLOT_SUPPLEMENTS constant ---

    def test_slot_supplements_constant_exists(self):
        """SLOT_SUPPLEMENTS module-level dict must exist with correct mappings (NUTR-03)."""
        import core.proactive_alerts as pa
        assert hasattr(pa, "SLOT_SUPPLEMENTS"), "SLOT_SUPPLEMENTS must be defined at module level"
        ss = pa.SLOT_SUPPLEMENTS
        assert ss.get("post-am-run") == "D3+K2/Omega-3"
        assert ss.get("pm-post-lift") == "Creatine"
        assert ss.get("pre-bed") == "Mg-Glycinate/Zinc/Copper"

    def test_slot_functions_no_io(self):
        """All slot functions are callable without any Firestore/Garmin environment."""
        from core.proactive_alerts import (
            _resolve_anchor_times,
            _map_meals_to_slots,
            _detect_slot_misses,
        )
        # These must complete with no external I/O (no GCP env vars needed)
        am, pm = _resolve_anchor_times("2026-06-06", [], [])
        slot_map = _map_meals_to_slots([], am, pm)
        misses = _detect_slot_misses([], am, pm, "2026-06-06")
        assert isinstance(slot_map, dict)
        assert isinstance(misses, list)
