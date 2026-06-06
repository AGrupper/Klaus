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


# ====================================================================== #
# Phase 24 Plan 04 — Nutrition gather + dedup gate (NUTR-01/02/03, COACH-05)
# Task 1: _gather_nutrition_data + dedup gate wiring in run_proactive_alerts #
# ====================================================================== #


def _make_firestore_db_mock(*, meal_store=None, user_profile_store=None,
                             coaching_topic_store=None, block_store=None):
    """Build a sys.modules-level mock for memory.firestore_db.

    Patching "memory.firestore_db.X" via unittest.mock.patch fails in Python 3.14
    because pkgutil.resolve_name cannot do getattr(memory, "firestore_db") when the
    submodule is in sys.modules but the parent package attribute isn't set. Patching
    sys.modules["memory.firestore_db"] directly bypasses this — the local-import
    path inside _gather_nutrition_data does from memory.firestore_db import X which
    resolves via sys.modules["memory.firestore_db"].X, not via getattr.
    """
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock

    fake = ModuleType("memory.firestore_db")
    if meal_store is not None:
        fake.MealStore = meal_store
    else:
        fake.MealStore = MagicMock()
    if user_profile_store is not None:
        fake.UserProfileStore = user_profile_store
    else:
        fake.UserProfileStore = MagicMock()
    if coaching_topic_store is not None:
        fake.CoachingTopicStore = coaching_topic_store
    else:
        fake.CoachingTopicStore = MagicMock()
    if block_store is not None:
        fake.BlockStore = block_store
    else:
        fake.BlockStore = MagicMock()
    # Passthrough attrs that the real module exposes (avoids AttributeError on misc access)
    fake._make_firestore_client = MagicMock()
    return fake


class TestGatherNutritionData:
    """Unit tests for _gather_nutrition_data — best-effort gather with MealStore mock."""

    def test_gather_nutrition_data_function_exists(self):
        """_gather_nutrition_data must be importable from core.proactive_alerts."""
        from core.proactive_alerts import _gather_nutrition_data  # noqa: F401

    def test_gather_nutrition_data_returns_dict(self):
        """_gather_nutrition_data returns a dict with expected keys."""
        import sys
        from core.proactive_alerts import _gather_nutrition_data
        from unittest.mock import MagicMock

        mock_ms_inst = MagicMock()
        mock_ms_inst.get_day.return_value = []
        mock_ms_inst.get_day_aggregate.return_value = {"totals": {}}
        mock_ms_cls = MagicMock(return_value=mock_ms_inst)

        mock_ups_inst = MagicMock()
        mock_ups_inst.load.return_value = {
            "nutrition_targets": {"protein_g": 150, "carbs_g": 350},
            "weekly_split": {},
        }
        mock_ups_cls = MagicMock(return_value=mock_ups_inst)

        fake_db = _make_firestore_db_mock(
            meal_store=mock_ms_cls, user_profile_store=mock_ups_cls
        )
        old = sys.modules.get("memory.firestore_db")
        sys.modules["memory.firestore_db"] = fake_db
        try:
            with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-proj"}):
                result = _gather_nutrition_data("2026-06-06", garmin_activities=[])
        finally:
            if old is not None:
                sys.modules["memory.firestore_db"] = old
            else:
                sys.modules.pop("memory.firestore_db", None)

        assert isinstance(result, dict)

    def test_gather_nutrition_no_meal_day_returns_missing_data(self):
        """On a no-meal day (get_day returns []), returns a missing-data context — no crash.

        Pitfall 7: get_day returns [] not None on empty days.
        """
        import sys
        from core.proactive_alerts import _gather_nutrition_data
        from unittest.mock import MagicMock

        mock_ms_inst = MagicMock()
        mock_ms_inst.get_day.return_value = []          # Pitfall 7: empty list, not None
        mock_ms_inst.get_day_aggregate.return_value = {"totals": {}}
        mock_ms_cls = MagicMock(return_value=mock_ms_inst)

        mock_ups_inst = MagicMock()
        mock_ups_inst.load.return_value = {
            "nutrition_targets": {"protein_g": 150, "carbs_g": 350},
            "weekly_split": {},
        }
        mock_ups_cls = MagicMock(return_value=mock_ups_inst)

        fake_db = _make_firestore_db_mock(
            meal_store=mock_ms_cls, user_profile_store=mock_ups_cls
        )
        old = sys.modules.get("memory.firestore_db")
        sys.modules["memory.firestore_db"] = fake_db
        try:
            with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-proj"}):
                result = _gather_nutrition_data("2026-06-06", garmin_activities=[])
        finally:
            if old is not None:
                sys.modules["memory.firestore_db"] = old
            else:
                sys.modules.pop("memory.firestore_db", None)

        # Must not crash; meals key is present (empty list is valid)
        assert "meals" in result
        assert result["meals"] == []

    def test_gather_nutrition_data_has_required_keys(self):
        """_gather_nutrition_data returns all expected keys from the spec."""
        import sys
        from core.proactive_alerts import _gather_nutrition_data
        from unittest.mock import MagicMock

        mock_ms_inst = MagicMock()
        mock_ms_inst.get_day.return_value = [
            {"timestamp": "2026-06-06T08:00:00", "protein_g": 40, "carbs_g": 60}
        ]
        mock_ms_inst.get_day_aggregate.return_value = {
            "totals": {"protein_g": 40, "carbs_g": 60}
        }
        mock_ms_cls = MagicMock(return_value=mock_ms_inst)

        mock_ups_inst = MagicMock()
        mock_ups_inst.load.return_value = {
            "nutrition_targets": {"protein_g": 150, "carbs_g": 350},
            "weekly_split": {},
        }
        mock_ups_cls = MagicMock(return_value=mock_ups_inst)

        fake_db = _make_firestore_db_mock(
            meal_store=mock_ms_cls, user_profile_store=mock_ups_cls
        )
        old = sys.modules.get("memory.firestore_db")
        sys.modules["memory.firestore_db"] = fake_db
        try:
            with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-proj"}):
                result = _gather_nutrition_data("2026-06-06", garmin_activities=[])
        finally:
            if old is not None:
                sys.modules["memory.firestore_db"] = old
            else:
                sys.modules.pop("memory.firestore_db", None)

        expected_keys = {"meals", "macro_totals", "macro_gaps", "slot_misses", "am_anchor", "pm_anchor"}
        for key in expected_keys:
            assert key in result, f"Expected key '{key}' missing from _gather_nutrition_data result"

    def test_gather_nutrition_store_failure_no_crash(self):
        """MealStore failure is handled best-effort — no crash (T-24-14 mitigation)."""
        import sys
        from core.proactive_alerts import _gather_nutrition_data
        from unittest.mock import MagicMock

        # MealStore raises on construction
        mock_ms_cls = MagicMock(side_effect=Exception("Firestore down"))

        fake_db = _make_firestore_db_mock(meal_store=mock_ms_cls)
        old = sys.modules.get("memory.firestore_db")
        sys.modules["memory.firestore_db"] = fake_db
        try:
            with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-proj"}):
                # Must NOT raise
                result = _gather_nutrition_data("2026-06-06", garmin_activities=[])
        finally:
            if old is not None:
                sys.modules["memory.firestore_db"] = old
            else:
                sys.modules.pop("memory.firestore_db", None)

        # Degraded result: meals defaults to []
        assert isinstance(result, dict)
        assert result.get("meals") == []


class TestDedupGateWiring:
    """Integration tests for CoachingTopicStore dedup gate in run_proactive_alerts.

    Verifies: already-raised topic excluded from coaching_topics_new; add_topic called
    only after send success; Jerusalem-time date key used.

    Uses sys.modules patching for memory.firestore_db to work around Python 3.14
    pkgutil.resolve_name getattr limitation (same pre-existing issue as the benchmark
    tests in this file that also patch memory.firestore_db.BlockStore).
    """

    def _run_cron(
        self,
        *,
        mock_ms_inst,
        mock_ups_inst,
        mock_cts_inst,
        mock_bs_inst=None,
        compose_side_effect=None,
        send_side_effect=None,
        cts_raises=False,
    ):
        """Run run_proactive_alerts with all external I/O mocked.

        Uses sys.modules["memory.firestore_db"] patching to work around Python 3.14.
        Returns the mock_cts instance so callers can assert on its calls.
        """
        import sys
        from types import ModuleType
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_bot = AsyncMock()
        captured = {}

        if compose_side_effect is None:
            def _capture(ctx):
                captured["ctx"] = ctx
                return "Alert text"
            compose_side_effect = _capture
        else:
            original_side_effect = compose_side_effect
            def _capture(ctx):
                captured["ctx"] = ctx
                return original_side_effect(ctx)
            compose_side_effect = _capture

        if send_side_effect is None:
            async def _ok_send(*args, **kwargs):
                pass
            send_side_effect = _ok_send

        # Build a fake memory.firestore_db module via sys.modules
        fake_db = ModuleType("memory.firestore_db")
        fake_db.MealStore = MagicMock(return_value=mock_ms_inst)
        fake_db.UserProfileStore = MagicMock(return_value=mock_ups_inst)
        if cts_raises:
            fake_db.CoachingTopicStore = MagicMock(side_effect=Exception("Firestore down"))
        else:
            fake_db.CoachingTopicStore = MagicMock(return_value=mock_cts_inst)
        _mock_bs = mock_bs_inst or MagicMock()
        _mock_bs.get_current.return_value = None
        fake_db.BlockStore = MagicMock(return_value=_mock_bs)
        fake_db._make_firestore_client = MagicMock()

        old_db = sys.modules.get("memory.firestore_db")
        sys.modules["memory.firestore_db"] = fake_db

        # Also patch the memory package attribute so getattr(memory, "firestore_db")
        # returns our fake (needed for pkgutil.resolve_name in Python 3.14).
        import memory as _memory_pkg
        old_attr = getattr(_memory_pkg, "firestore_db", None)
        _memory_pkg.firestore_db = fake_db

        try:
            with patch.dict(os.environ, {"GCP_PROJECT_ID": "test-proj"}), \
                 patch("core.training_checkin.run_training_checkin", new=AsyncMock()), \
                 patch("core.proactive_alerts._already_sent", return_value=False), \
                 patch("core.proactive_alerts._get_calendar_tool") as mock_cal, \
                 patch("core.proactive_alerts._home_address", return_value=""), \
                 patch("core.proactive_alerts._detect_weather_conflicts", return_value=[
                     {"event_summary": "Run", "event_time": "07:00", "issue": "rain 40%"}
                 ]), \
                 patch("core.proactive_alerts._detect_overloaded_day", return_value=None), \
                 patch("core.proactive_alerts._detect_travel_issues", return_value=[]), \
                 patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value={}), \
                 patch("mcp_tools.garmin_tool.fetch_garmin_activities", return_value=[]), \
                 patch("mcp_tools.garmin_tool.compute_acwr_from_db", return_value={}), \
                 patch("core.training_checkin.compute_recovery_concern", return_value=None), \
                 patch("core.proactive_alerts._compose_alert", side_effect=compose_side_effect), \
                 patch("core.scheduled_message.send_and_inject", side_effect=send_side_effect), \
                 patch("mcp_tools.weather_tool.fetch_weather", return_value={"tomorrow": {}}), \
                 patch("core.proactive_alerts._mark_processed"):
                mock_cal.return_value.list_events.return_value = []

                try:
                    asyncio.run(
                        __import__("core.proactive_alerts", fromlist=["run_proactive_alerts"])
                        .run_proactive_alerts(mock_bot, "2026-06-07")
                    )
                except Exception as exc:
                    captured["exc"] = exc
        finally:
            if old_db is not None:
                sys.modules["memory.firestore_db"] = old_db
            else:
                sys.modules.pop("memory.firestore_db", None)
            if old_attr is not None:
                _memory_pkg.firestore_db = old_attr
            elif hasattr(_memory_pkg, "firestore_db"):
                delattr(_memory_pkg, "firestore_db")

        return captured, mock_bot, mock_cts_inst

    def _make_mock_ms(self, *, protein_g=40, carbs_g=60, with_meals=True):
        from unittest.mock import MagicMock
        ms = MagicMock()
        if with_meals:
            ms.get_day.return_value = [
                {"timestamp": "2026-06-06T08:00:00", "protein_g": protein_g, "carbs_g": carbs_g}
            ]
            ms.get_day_aggregate.return_value = {"totals": {"protein_g": protein_g, "carbs_g": carbs_g}}
        else:
            ms.get_day.return_value = []
            ms.get_day_aggregate.return_value = {"totals": {}}
        return ms

    def _make_mock_ups(self):
        from unittest.mock import MagicMock
        ups = MagicMock()
        ups.load.return_value = {
            "nutrition_targets": {"protein_g": 150, "carbs_g": 350},
            "weekly_split": {},
        }
        return ups

    def _make_mock_cts(self, *, already_raised=None):
        from unittest.mock import MagicMock
        cts = MagicMock()
        _raised = already_raised or []
        cts.has_topic.side_effect = lambda d, t: t in _raised
        cts.topics_today.return_value = list(_raised)
        return cts

    def test_already_raised_topic_excluded_from_new_topics(self):
        """Dedup gate: a topic in CoachingTopicStore.topics_today is excluded from
        coaching_topics_new fed to compose (COACH-05)."""
        mock_ms = self._make_mock_ms(protein_g=40)   # 40g < 120g floor → protein-miss
        mock_ups = self._make_mock_ups()
        mock_cts = self._make_mock_cts(already_raised=["protein-miss"])

        captured, _, _ = self._run_cron(
            mock_ms_inst=mock_ms,
            mock_ups_inst=mock_ups,
            mock_cts_inst=mock_cts,
        )

        ctx = captured.get("ctx", {})
        new_topics = ctx.get("coaching_topics_new", [])
        assert "protein-miss" not in new_topics, (
            "protein-miss was already raised today — must not appear in coaching_topics_new"
        )
        already_raised = ctx.get("coaching_topics_already_raised", [])
        assert "protein-miss" in already_raised

    def test_add_topic_not_called_when_send_fails(self):
        """Write-after-send discipline: add_topic must NOT be called when send fails
        (T-24-12 mitigation — false dedup block on crash-between-write-and-send)."""
        async def _fail_send(*args, **kwargs):
            raise RuntimeError("Telegram down")

        mock_ms = self._make_mock_ms(with_meals=False)
        mock_ups = self._make_mock_ups()
        mock_cts = self._make_mock_cts()

        captured, _, mock_cts_inst = self._run_cron(
            mock_ms_inst=mock_ms,
            mock_ups_inst=mock_ups,
            mock_cts_inst=mock_cts,
            send_side_effect=_fail_send,
        )

        # add_topic must NOT have been called (write-before-send would be T-24-12)
        mock_cts_inst.add_topic.assert_not_called()

    def test_add_topic_called_after_successful_send(self):
        """Write-after-send discipline: add_topic IS called after send succeeds."""
        mock_ms = self._make_mock_ms(protein_g=40)   # 40g < 120g floor → protein-miss
        mock_ups = self._make_mock_ups()
        mock_cts = self._make_mock_cts()

        captured, _, mock_cts_inst = self._run_cron(
            mock_ms_inst=mock_ms,
            mock_ups_inst=mock_ups,
            mock_cts_inst=mock_cts,
        )

        assert mock_cts_inst.add_topic.called, "add_topic must be called after successful send"

    def test_dedup_gate_failure_is_fail_open(self):
        """CoachingTopicStore failure (store raises) must not crash the cron — all
        topics fire (fail-open per T-24-14 mitigation)."""
        mock_ms = self._make_mock_ms(with_meals=False)
        mock_ups = self._make_mock_ups()
        mock_cts = MagicMock()  # won't be used — cts_raises=True

        captured, _, _ = self._run_cron(
            mock_ms_inst=mock_ms,
            mock_ups_inst=mock_ups,
            mock_cts_inst=mock_cts,
            cts_raises=True,
        )

        # Compose was still called (cron continued despite CoachingTopicStore failure)
        assert "ctx" in captured, "compose must still be called when dedup gate fails"

    def test_jerusalem_time_used_for_coaching_topic_key(self):
        """The Jerusalem-time date key is used for CoachingTopicStore calls (not UTC)."""
        from zoneinfo import ZoneInfo
        import datetime as _dt_mod

        il_date_today = _dt_mod.datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

        mock_ms = self._make_mock_ms(with_meals=False)
        mock_ups = self._make_mock_ups()
        mock_cts = self._make_mock_cts()

        captured, _, mock_cts_inst = self._run_cron(
            mock_ms_inst=mock_ms,
            mock_ups_inst=mock_ups,
            mock_cts_inst=mock_cts,
        )

        # Any call to has_topic or topics_today must use the Israel-time date
        all_calls = (
            list(mock_cts_inst.has_topic.call_args_list)
            + list(mock_cts_inst.topics_today.call_args_list)
        )
        for c in all_calls:
            date_arg = c.args[0] if c.args else c.kwargs.get("date_str")
            assert date_arg == il_date_today, (
                f"CoachingTopicStore called with '{date_arg}', "
                f"expected Jerusalem-time date '{il_date_today}'"
            )


# ====================================================================== #
# Phase 24 Plan 04 — Task 2: Prompt content assertions                   #
# proactive_alert.md + smart_agent.md strict-coaching, nutrition, dedup  #
# ====================================================================== #


class TestPromptContent:
    """Assert the critical coaching-behavior markers are present in the prompt files.

    These tests are purely structural (file-read assertions) — they do not invoke
    the LLM. They verify that the required behaviors were not accidentally omitted
    or overwritten during editing.
    """

    @staticmethod
    def _read_prompt(name: str) -> str:
        """Read a prompt file from the prompts/ directory."""
        from pathlib import Path
        path = Path(__file__).parent.parent / "prompts" / name
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ #
    # proactive_alert.md assertions                                       #
    # ------------------------------------------------------------------ #

    def test_proactive_alert_has_your_call_sir(self):
        """Recovery-conflict block must include 'your call, Sir' — the SC-2/COACH-04
        single-ranked-recommendation hand-off (D-07)."""
        content = self._read_prompt("proactive_alert.md").lower()
        assert "your call, sir" in content, (
            "proactive_alert.md must contain 'your call, Sir' for the recovery-conflict "
            "single-ranked-recommendation hand-off (COACH-04 / D-07)"
        )

    def test_proactive_alert_has_one_ranked_rec_instruction(self):
        """Recovery-conflict block must forbid menus — exactly one ranked recommendation."""
        content = self._read_prompt("proactive_alert.md").lower()
        # At least one of: "one ranked", "exactly one", "single rec", "one recommendation"
        markers = ["one ranked", "exactly one", "single rec", "one recommendation",
                   "one rec", "single ranked"]
        assert any(m in content for m in markers), (
            "proactive_alert.md must explicitly instruct exactly one ranked recommendation "
            "(COACH-04 / D-07 — never a menu)"
        )

    def test_proactive_alert_no_softening_skip_pushback(self):
        """Skip-pushback block must forbid softening/hedging (COACH-03 / D-05)."""
        content = self._read_prompt("proactive_alert.md").lower()
        markers = ["no softening", "no hedging", "forbid hedge", "without hedging",
                   "without softening", "do not hedge", "do not soften", "strict",
                   "no hedge"]
        assert any(m in content for m in markers), (
            "proactive_alert.md must explicitly forbid softening/hedging in skip-pushback "
            "(COACH-03 / D-05)"
        )

    def test_proactive_alert_forbids_dated_projection(self):
        """Skip-pushback block must NOT introduce dated projection language —
        'N weeks behind' / 'on track for' is Phase 25 scope."""
        content = self._read_prompt("proactive_alert.md")
        content_lower = content.lower()
        # If the phrase appears, it MUST be in a prohibition (e.g. "do NOT say '...'")
        for phrase in ["weeks behind", "on track for"]:
            if phrase in content_lower:
                # Acceptable only if the surrounding text forbids it
                idx = content_lower.find(phrase)
                window = content_lower[max(0, idx - 80): idx + 80]
                assert any(neg in window for neg in [
                    "do not", "never", "not", "forbid", "avoid", "no dated"
                ]), (
                    f"proactive_alert.md contains '{phrase}' without a prohibition — "
                    f"dated projection is Phase 25 scope, not Phase 24"
                )

    def test_proactive_alert_has_supplement_riders(self):
        """Nutrition block must reference the supplement riders (NUTR-03 / D-11):
        D3+K2/Omega-3 (post-am-run), Creatine (pm-post-lift), Mg-Glycinate (pre-bed)."""
        content = self._read_prompt("proactive_alert.md").lower()
        # Check for at least two of the three supplements (flex for spelling variants)
        supplements = ["d3", "omega-3", "omega3", "creatine",
                       "mg-glycinate", "mg glycinate", "magnesium glycinate",
                       "zinc", "copper", "k2"]
        found = sum(1 for s in supplements if s in content)
        assert found >= 2, (
            f"proactive_alert.md must reference supplement riders (D3+K2/Omega-3, "
            f"Creatine, Mg-Glycinate) — found {found} of the expected supplement names"
        )

    def test_proactive_alert_references_structural_miss(self):
        """Nutrition block must frame misses as structural, not daily micro-optimization."""
        content = self._read_prompt("proactive_alert.md").lower()
        markers = ["structural", "structurally", "structural miss"]
        assert any(m in content for m in markers), (
            "proactive_alert.md must frame fueling/macro misses as 'structural' — "
            "not daily micro-optimization (NUTR-01 / D-12)"
        )

    def test_proactive_alert_has_dedup_semantics(self):
        """Dedup semantics must be present: already-raised topics not repeated (COACH-05)."""
        content = self._read_prompt("proactive_alert.md").lower()
        markers = [
            "already", "coaching_topics_already_raised", "already_raised",
            "already raised", "not repeat", "do not repeat", "skip", "suppress",
            "already said", "already flagged",
        ]
        assert any(m in content for m in markers), (
            "proactive_alert.md must include dedup semantics — instructions not to repeat "
            "topics already raised today (COACH-05)"
        )

    def test_proactive_alert_has_nutrition_section(self):
        """Nutrition accountability section must exist in proactive_alert.md (NUTR-01/02)."""
        content = self._read_prompt("proactive_alert.md").lower()
        markers = ["nutrition", "macro", "protein", "fueling", "carb"]
        assert any(m in content for m in markers), (
            "proactive_alert.md must include a nutrition accountability section (NUTR-01/02)"
        )

    # ------------------------------------------------------------------ #
    # smart_agent.md assertions                                           #
    # ------------------------------------------------------------------ #

    def test_smart_agent_reactive_never_suppressed(self):
        """smart_agent.md must state reactive chat is never suppressed by cron topics
        (COACH-05 / D-03)."""
        content = self._read_prompt("smart_agent.md").lower()
        markers = [
            "reactive", "never suppress", "always answer", "not suppress",
            "never suppressed", "always answer", "reactive chat", "reactive coaching",
        ]
        assert any(m in content for m in markers), (
            "smart_agent.md must state that reactive chat answers are never suppressed "
            "by cron topics (COACH-05 / D-03)"
        )

    def test_smart_agent_has_strict_pushback_format(self):
        """smart_agent.md must include the strict-pushback/single-rec format for
        reactive coaching queries (COACH-03/04 / D-05/06/07)."""
        content = self._read_prompt("smart_agent.md").lower()
        # Accept any of these as evidence of the reactive strict-coaching format
        markers = [
            "your call, sir",
            "one ranked",
            "exactly one",
            "single rec",
            "skip pushback",
            "strict.*pushback",
            "reactive.*strict",
            "named.*session",
            "named session",
            "concrete.*deficit",
            "concrete deficit",
        ]
        import re
        assert any(
            (re.search(m, content) is not None if ".*" in m else m in content)
            for m in markers
        ), (
            "smart_agent.md must include the strict-pushback format for reactive coaching "
            "queries — named session, deficit in concrete units, single ranked rec, "
            "'your call, Sir' (COACH-03/04)"
        )
