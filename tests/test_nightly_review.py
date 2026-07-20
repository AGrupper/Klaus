# tests/test_nightly_review.py
"""Tests for the nightly review (WS2): wind-down date mapping, idempotency,
send-after-build, light fallback, and the /trigger/nightly + /cron/nightly-backstop
route auth."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_TZ = ZoneInfo("Asia/Jerusalem")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")


# ---------------------------------------------------------------------------
# nightly_target_date — wind-down maps to the day it started on
# ---------------------------------------------------------------------------

def test_nightly_target_date_evening_stays_same_day():
    from core.nightly_review import nightly_target_date
    assert nightly_target_date(datetime(2026, 6, 10, 23, 0, tzinfo=_TZ)) == "2026-06-10"


def test_nightly_target_date_after_midnight_maps_to_prev_day():
    """A 01:00 backstop (or a 00:30 trigger) belongs to the previous evening."""
    from core.nightly_review import nightly_target_date
    assert nightly_target_date(datetime(2026, 6, 11, 1, 0, tzinfo=_TZ)) == "2026-06-10"


# ---------------------------------------------------------------------------
# Light plain-text fallback
# ---------------------------------------------------------------------------

def test_plain_text_fallback_is_light_and_includes_tomorrow():
    from core.nightly_review import _plain_text_fallback
    journal = {"summary": "Solid day — hit the lift and ate well."}
    tomorrow = {"calendar": [{"start": "2026-06-11T09:00:00+03:00", "summary": "Threshold run"}]}
    txt = _plain_text_fallback(journal, tomorrow)
    assert "Tomorrow:" in txt
    assert "Threshold run" in txt
    assert "sir" not in txt.lower()


def test_plain_text_fallback_empty_tomorrow():
    from core.nightly_review import _plain_text_fallback
    txt = _plain_text_fallback(None, {"calendar": []})
    assert "Nothing on the calendar." in txt


def test_plain_text_fallback_includes_planned_training():
    from core.nightly_review import _plain_text_fallback
    tomorrow = {
        "calendar": [],
        "planned_workouts": {
            "weekday": "Monday",
            "am": {"label": "Easy Run", "modality": "run"},
            "pm": {"label": "Lower Body A", "modality": "strength"},
        },
    }
    txt = _plain_text_fallback(None, tomorrow)
    assert "training" in txt.lower()
    assert "Easy Run" in txt
    assert "Lower Body A" in txt


# ---------------------------------------------------------------------------
# Phase 30.5 Plan 06 (BRAIN-01) — SMART_AGENT_FALLBACK_* Gemini compose fallback
# ---------------------------------------------------------------------------

def test_compose_nightly_brain_fails_gemini_fallback_composes(monkeypatch):
    """Brain raises -> SMART_AGENT_FALLBACK_* Gemini compose is used (not the plain template)."""
    from core.nightly_review import _compose_nightly
    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-smart-key")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_BACKEND", "gemini")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_API_KEY", "test-fallback-key")

    journal = {"summary": "Solid day."}
    tomorrow = {"calendar": []}

    call_count = {"n": 0}

    def _client_factory(*args, **kwargs):
        call_count["n"] += 1
        client = MagicMock()
        if call_count["n"] == 1:
            client.chat.side_effect = Exception("brain down")
        else:
            client.chat.return_value = {
                "text": "Gemini-composed nightly text.",
                "tool_calls": [], "stop_reason": "end_turn",
            }
        return client

    with patch("core.llm_client.LLMClient", side_effect=_client_factory), \
         patch("pathlib.Path.read_text", return_value="System prompt for {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        result = _compose_nightly(journal, tomorrow, "2026-06-11")

    assert result == "Gemini-composed nightly text."
    assert "Tomorrow:" not in result


def test_compose_nightly_brain_and_fallback_fail_returns_plain_template(monkeypatch):
    """Brain + Gemini fallback both raise -> deterministic _plain_text_fallback returned."""
    from core.nightly_review import _compose_nightly
    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-smart-key")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_BACKEND", "gemini")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("SMART_AGENT_FALLBACK_API_KEY", "test-fallback-key")

    journal = {"summary": "Solid day."}
    tomorrow = {"calendar": []}

    with patch("core.llm_client.LLMClient", side_effect=Exception("all LLMs down")), \
         patch("pathlib.Path.read_text", return_value="System prompt for {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        result = _compose_nightly(journal, tomorrow, "2026-06-11")

    assert "Nothing on the calendar." in result


# ---------------------------------------------------------------------------
# Planned-workout gather — tomorrow's weekly_split sessions
# ---------------------------------------------------------------------------

def _profile_stores_mock(weekly_split: dict):
    """Patch target for core.tools._block_stores → (_, _, profiles) with .load()."""
    profiles = MagicMock()
    profiles.load.return_value = {"weekly_split": weekly_split}
    return (MagicMock(), MagicMock(), profiles)


def test_planned_workouts_returns_tomorrow_split():
    from core.nightly_review import _planned_workouts_for
    split = {
        "Monday": {
            "am": {"label": "Easy Run", "modality": "run", "priority": "A"},
            "pm": {"label": "Lower Body A", "modality": "strength", "priority": "A"},
        },
    }
    with patch("core.tools._block_stores", return_value=_profile_stores_mock(split)):
        # 2026-06-15 is a Monday
        out = _planned_workouts_for("2026-06-15")
    assert out["weekday"] == "Monday"
    assert out["am"]["label"] == "Easy Run"
    assert out["pm"]["label"] == "Lower Body A"


def test_planned_workouts_case_insensitive_day_key():
    from core.nightly_review import _planned_workouts_for
    split = {"monday": {"am": {"label": "Easy Run"}, "pm": {"label": "Lower A"}}}
    with patch("core.tools._block_stores", return_value=_profile_stores_mock(split)):
        out = _planned_workouts_for("2026-06-15")  # Monday
    assert out is not None
    assert out["am"]["label"] == "Easy Run"


def test_planned_workouts_absent_returns_none():
    from core.nightly_review import _planned_workouts_for
    with patch("core.tools._block_stores", return_value=_profile_stores_mock({})):
        out = _planned_workouts_for("2026-06-15")
    assert out is None


def test_planned_workouts_swallows_errors():
    from core.nightly_review import _planned_workouts_for
    with patch("core.tools._block_stores", side_effect=RuntimeError("firestore down")):
        out = _planned_workouts_for("2026-06-15")
    assert out is None


def test_gather_tomorrow_includes_planned_workouts():
    """_gather_tomorrow wires _planned_workouts_for into its output under planned_workouts."""
    import core.nightly_review as nr
    split_out = {"weekday": "Monday", "am": {"label": "Easy Run"}, "pm": {"label": "Lower A"}}
    with patch.object(nr, "_planned_workouts_for", return_value=split_out), \
         patch("core.tools._get_calendar_tool", side_effect=RuntimeError("skip")), \
         patch("memory.firestore_db.TaskStore", side_effect=RuntimeError("skip")), \
         patch("mcp_tools.weather_tool.fetch_weather", side_effect=RuntimeError("skip")):
        data = nr._gather_tomorrow("2026-06-15")
    assert data["planned_workouts"] == split_out


# ---------------------------------------------------------------------------
# Phase 31 (DIR-03/06/07) — standing directives woven into the nightly
# narrative; nightly is EXEMPT from veto (D-21)
# ---------------------------------------------------------------------------

def test_gather_tomorrow_includes_standing_directives():
    """_gather_tomorrow reads StandingDirectiveStore.list_active() into
    data['standing_directives'] — the 5th render_standing_directives_block()
    injection site (DIR-03), interim CONTEXT only (never a veto)."""
    import core.nightly_review as nr
    directives = [{"id": "d1", "text": "No training nudges after 9pm", "origin": "user_chat",
                   "expires_at": None, "condition_text": None}]
    mock_store = MagicMock()
    mock_store.list_active.return_value = directives
    with patch("memory.firestore_db.StandingDirectiveStore", return_value=mock_store), \
         patch.object(nr, "_planned_workouts_for", return_value=None), \
         patch("core.tools._get_calendar_tool", side_effect=RuntimeError("skip")), \
         patch("memory.firestore_db.TaskStore", side_effect=RuntimeError("skip")), \
         patch("mcp_tools.weather_tool.fetch_weather", side_effect=RuntimeError("skip")):
        data = nr._gather_tomorrow("2026-06-15")
    assert data["standing_directives"] == directives


def test_gather_tomorrow_standing_directives_gather_failure_is_sentinel_empty():
    """A StandingDirectiveStore failure is isolated — sentinel [] not a crash."""
    import core.nightly_review as nr
    with patch("memory.firestore_db.StandingDirectiveStore", side_effect=RuntimeError("firestore down")), \
         patch.object(nr, "_planned_workouts_for", return_value=None), \
         patch("core.tools._get_calendar_tool", side_effect=RuntimeError("skip")), \
         patch("memory.firestore_db.TaskStore", side_effect=RuntimeError("skip")), \
         patch("mcp_tools.weather_tool.fetch_weather", side_effect=RuntimeError("skip")):
        data = nr._gather_tomorrow("2026-06-15")
    assert data["standing_directives"] == []


def _compose_nightly_env(monkeypatch):
    monkeypatch.setenv("SMART_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("SMART_AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "test-smart-key")


def _capture_compose_call(response_text: str):
    """Return (client_factory, captured) — client_factory feeds LLMClient.chat and
    captured['messages']/['system'] records what _compose_nightly sent."""
    captured: dict = {}

    def _client_factory(*args, **kwargs):
        client = MagicMock()

        def _chat(**chat_kwargs):
            captured["messages"] = chat_kwargs.get("messages")
            captured["system"] = chat_kwargs.get("system")
            return {"text": response_text}

        client.chat.side_effect = _chat
        return client

    return _client_factory, captured


def test_compose_nightly_payload_includes_rendered_standing_directives_block(monkeypatch):
    """An active directive produces a rendered standing_directives_block in the
    compose payload, DISTINCT from directive_items."""
    from core.nightly_review import _compose_nightly
    _compose_nightly_env(monkeypatch)

    journal = {"summary": "ok", "highlights": [], "directive_items": []}
    tomorrow = {
        "calendar": [],
        "standing_directives": [{"text": "No pings after 10pm", "origin": "user_chat"}],
    }

    client_factory, captured = _capture_compose_call("Night text.")
    with patch("core.llm_client.LLMClient", side_effect=client_factory), \
         patch("pathlib.Path.read_text", return_value="SYS {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        result = _compose_nightly(journal, tomorrow, "2026-06-11")

    assert result == "Night text."
    payload = json.loads(captured["messages"][0]["content"])
    assert "standing_directives_block" in payload
    assert "No pings after 10pm" in payload["standing_directives_block"]
    assert payload["directive_items"] == []
    assert payload["standing_directives_block"] != payload["directive_items"]


def test_compose_nightly_payload_includes_directive_proposal_with_veto_context(monkeypatch):
    """A proposal from tonight's reflection reaches the compose payload's
    directive_items — the composed message (mocked) carries the veto option."""
    from core.nightly_review import _compose_nightly
    _compose_nightly_env(monkeypatch)

    proposal_item = {
        "type": "proposal", "text": "Ease off weekend morning pings", "id": "abc123",
        "rationale": "ignored 2 outreach attempts",
    }
    journal = {"summary": "ok", "highlights": [], "directive_items": [proposal_item]}
    tomorrow = {"calendar": []}

    client_factory, captured = _capture_compose_call(
        "Standing order noted, Sir — say the word and I'll drop it."
    )
    with patch("core.llm_client.LLMClient", side_effect=client_factory), \
         patch("pathlib.Path.read_text", return_value="SYS {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        result = _compose_nightly(journal, tomorrow, "2026-06-11")

    payload = json.loads(captured["messages"][0]["content"])
    assert payload["directive_items"] == [proposal_item]
    assert "drop it" in result


def test_compose_nightly_payload_always_carries_expiry_note(monkeypatch):
    """An expiry note is always present in directive_items reaching the composer (D-07)."""
    from core.nightly_review import _compose_nightly
    _compose_nightly_env(monkeypatch)

    expiry_item = {"type": "expiry", "directive_id": "france-1", "reason": "back from France"}
    journal = {"summary": "ok", "highlights": [], "directive_items": [expiry_item]}
    tomorrow = {"calendar": []}

    client_factory, captured = _capture_compose_call("Night text with the expiry noted.")
    with patch("core.llm_client.LLMClient", side_effect=client_factory), \
         patch("pathlib.Path.read_text", return_value="SYS {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        _compose_nightly(journal, tomorrow, "2026-06-11")

    payload = json.loads(captured["messages"][0]["content"])
    assert expiry_item in payload["directive_items"]


def test_compose_nightly_no_directive_activity_payload_stays_empty(monkeypatch):
    """No directive activity -> directive_items == [] and standing_directives_block
    == '' — no clutter injected into an otherwise-unchanged narrative payload."""
    from core.nightly_review import _compose_nightly
    _compose_nightly_env(monkeypatch)

    journal = {"summary": "ok", "highlights": []}  # no directive_items key at all
    tomorrow = {"calendar": []}  # no standing_directives key at all

    client_factory, captured = _capture_compose_call("Quiet night.")
    with patch("core.llm_client.LLMClient", side_effect=client_factory), \
         patch("pathlib.Path.read_text", return_value="SYS {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        _compose_nightly(journal, tomorrow, "2026-06-11")

    payload = json.loads(captured["messages"][0]["content"])
    assert payload["directive_items"] == []
    assert payload["standing_directives_block"] == ""


def test_compose_nightly_never_emits_skip_verdict_even_with_covering_directive(monkeypatch):
    """Nightly is EXEMPT from directive veto (D-21) — _compose_nightly always
    returns composed text, never a skip signal, even when an active directive
    plausibly covers the whole nightly content."""
    from core.nightly_review import _compose_nightly
    _compose_nightly_env(monkeypatch)

    journal = {"summary": "ok", "highlights": [], "directive_items": []}
    tomorrow = {
        "calendar": [{"start": "2026-06-12T09:00:00+03:00", "summary": "Threshold run"}],
        "standing_directives": [{"text": "Don't send me any messages at night", "origin": "user_chat"}],
    }

    client_factory, captured = _capture_compose_call("Tomorrow: Threshold run at 09:00.")
    with patch("core.llm_client.LLMClient", side_effect=client_factory), \
         patch("pathlib.Path.read_text", return_value="SYS {today_date}"), \
         patch("core.autonomous._get_orchestrator", side_effect=Exception("no orchestrator")):
        result = _compose_nightly(journal, tomorrow, "2026-06-11")

    assert isinstance(result, str) and result, (
        "_compose_nightly must always return composed text — no skip-verdict path exists for nightly"
    )


# ---------------------------------------------------------------------------
# run_nightly — idempotency + send/mark-after-build
# ---------------------------------------------------------------------------

def test_run_nightly_idempotent_skips_when_already_sent():
    import core.nightly_review as nr
    send_mock = AsyncMock()
    with patch.object(nr, "was_sent", return_value=True), \
         patch("core.scheduled_message.send_and_inject", new=send_mock):
        result = asyncio.run(nr.run_nightly(MagicMock(), "2026-06-10", trigger="backstop"))
    assert result is False
    send_mock.assert_not_awaited()


def test_run_nightly_sends_injects_and_marks_state():
    import core.nightly_review as nr
    send_mock = AsyncMock()
    set_calls: dict = {}
    with patch.object(nr, "was_sent", return_value=False), \
         patch.object(nr, "_build_nightly",
                      return_value={"text": "night text", "structured": {"tomorrow_date": "2026-06-11"}}), \
         patch.object(nr, "_set_state", side_effect=lambda d, f: set_calls.update({d: f})), \
         patch("core.scheduled_message.send_and_inject", new=send_mock):
        result = asyncio.run(nr.run_nightly(MagicMock(), "2026-06-10", trigger="focus"))

    assert result is True
    send_mock.assert_awaited_once()
    # injected into conversation history
    assert send_mock.await_args.kwargs.get("inject_into_conversation") is True
    # state marked sent AFTER send, with the tomorrow snapshot for the morning delta
    assert set_calls["2026-06-10"]["status"] == "sent"
    assert set_calls["2026-06-10"]["trigger"] == "focus"
    assert set_calls["2026-06-10"]["structured"]["tomorrow_date"] == "2026-06-11"


# ---------------------------------------------------------------------------
# Route auth — /trigger/nightly + /cron/nightly-backstop
# ---------------------------------------------------------------------------

def _build_test_client(env_patch: dict):
    """Import web_server with the heavy deps stubbed and return a TestClient + module.

    Mirrors tests/test_reflection.py::test_cron_reflect_route stubbing so the route
    layer is exercised without booting the real orchestrator.
    """
    telegram_stub = MagicMock(name="telegram")
    stubs = {
        "telegram": sys.modules.get("telegram", telegram_stub),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if "interfaces.web_server" in key:
            del sys.modules[key]
    return stubs, env_patch


def test_trigger_nightly_rejects_missing_token():
    """No bypass + no Authorization header → 401."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "NIGHTLY_TRIGGER_TOKEN": "s3cret-token",
        "CRON_DEV_BYPASS": "false",
    })
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            client = TestClient(ws.app)
            resp = client.post("/trigger/nightly")
    assert resp.status_code == 401


def test_trigger_nightly_rejects_bad_token():
    """Wrong bearer → 403."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "NIGHTLY_TRIGGER_TOKEN": "s3cret-token",
        "CRON_DEV_BYPASS": "false",
    })
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            client = TestClient(ws.app)
            resp = client.post("/trigger/nightly", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403


def test_trigger_nightly_dev_bypass_acks_and_runs_in_background():
    """CRON_DEV_BYPASS=true skips auth; route returns 202 immediately and the nightly
    runs in a background task (Starlette TestClient executes background tasks in-cycle)."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "CRON_DEV_BYPASS": "true",
    })
    run_mock = AsyncMock(return_value=True)
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            with patch("core.nightly_review.run_nightly", run_mock):
                ws._log_cron_run = lambda *a, **k: None  # type: ignore[attr-defined]
                ws._application = MagicMock()  # TestClient w/o `with` skips lifespan
                client = TestClient(ws.app)
                resp = client.post("/trigger/nightly")
    # Phone gets an instant ack, not the slow compose result.
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True}
    # The background task still ran the nightly with the focus trigger.
    run_mock.assert_awaited_once()
    assert run_mock.await_args.kwargs.get("trigger") == "focus"


def test_nightly_backstop_rejects_unauthenticated():
    """/cron/nightly-backstop uses OIDC verification → 401 without a bearer."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "CRON_DEV_BYPASS": "false",
        "CLOUD_RUN_URL": "https://example.run.app",
        "CLOUD_SCHEDULER_SA_EMAIL": "sched@example.iam.gserviceaccount.com",
    })
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            client = TestClient(ws.app)
            resp = client.post("/cron/nightly-backstop")
    assert resp.status_code == 401


def test_nightly_backstop_dev_bypass_runs_nightly():
    """CRON_DEV_BYPASS=true → backstop invokes run_nightly with trigger='backstop'."""
    stubs, env_patch = _build_test_client({
        "GCP_PROJECT_ID": "test-project",
        "FIRESTORE_DATABASE": "(default)",
        "TELEGRAM_BOT_TOKEN": "1234:fake",
        "TELEGRAM_ALLOWED_USER_IDS": "123456",
        "CRON_DEV_BYPASS": "true",
    })
    run_mock = AsyncMock(return_value=False)
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        with patch.dict(os.environ, env_patch):
            with patch("core.nightly_review.run_nightly", run_mock):
                ws._log_cron_run = lambda *a, **k: None  # type: ignore[attr-defined]
                ws._application = MagicMock()  # TestClient w/o `with` skips lifespan
                client = TestClient(ws.app)
                resp = client.post("/cron/nightly-backstop")
    assert resp.status_code == 200
    assert resp.json() == {"sent": False}
    run_mock.assert_awaited_once()
    assert run_mock.await_args.kwargs.get("trigger") == "backstop"
