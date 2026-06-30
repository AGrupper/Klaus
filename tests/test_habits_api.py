"""Tests for /api/habits/* routes in interfaces/web_server.py.

Phase 28 — HABIT-01/02/04, TIME-06 (TDD — Task 1 RED; Task 2 GREEN)

Covers:
  - test_habits_routes_require_session: GET/POST/checkin without session → 401 (T-28-AC)
  - TestCheckinEndpoint: done toggle; yesterday accept; today-2 reject 400 (T-28-backfill/D-11)
  - test_list_scheduled_today: scheduled_today + done_today flags in GET /api/habits (TIME-06)
  - test_patch_schedule_rejects_past_effective_from: past effective_from → 400 (T-28-schedule/D-19)
  - test_hard_delete_requires_completing: active habit hard-delete → 409

Mock strategy
-------------
Firestore mock installed at module level (mirrors test_task_store.py / test_habit_store.py).
Heavy web_server deps (telegram, core.main, interfaces._router) stubbed via
patch.dict(sys.modules, stubs) around each test (mirrors test_hub_chat.py).
require_hub_session dependency overridden for authenticated tests.
HabitStore is patched via patch("memory.firestore_db.HabitStore", return_value=instance)
to avoid real Firestore connections; _is_scheduled is a pure function and does not need
to be mocked.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_TZ = ZoneInfo("Asia/Jerusalem")


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# (verbatim from test_task_store.py / test_habit_store.py)
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore and related stubs into sys.modules."""
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        if "google" not in sys.modules or isinstance(sys.modules["google"], MagicMock):
            google_mod = ModuleType("google")
            google_mod.__path__ = []
            sys.modules["google"] = google_mod
        else:
            google_mod = sys.modules["google"]

        if "google.cloud" not in sys.modules or isinstance(
            sys.modules["google.cloud"], MagicMock
        ):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()

    class _Increment:
        def __init__(self, value):
            self.value = value

        def __repr__(self):
            return f"Increment({self.value!r})"

    class _ArrayUnion:
        def __init__(self, values):
            self.values = list(values)

        def __repr__(self):
            return f"ArrayUnion({self.values!r})"

    firestore_mock.Increment = _Increment
    firestore_mock.ArrayUnion = _ArrayUnion
    firestore_mock.SERVER_TIMESTAMP = object()

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    # google.api_core.exceptions
    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    # google.cloud.firestore_v1.base_query — only FieldFilter is consumed
    class _FieldFilter:
        def __init__(self, field, op, value):
            self.field = field
            self.op = op
            self.value = value

        def __repr__(self):
            return f"FieldFilter({self.field!r}, {self.op!r}, {self.value!r})"

    bq = sys.modules.get("google.cloud.firestore_v1.base_query", MagicMock())
    bq.FieldFilter = _FieldFilter
    sys.modules["google.cloud.firestore_v1.base_query"] = bq
    if "google.cloud.firestore_v1" in sys.modules:
        sys.modules["google.cloud.firestore_v1"].base_query = bq
    else:
        fv1 = MagicMock()
        fv1.base_query = bq
        sys.modules["google.cloud.firestore_v1"] = fv1

    # google.oauth2
    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    # dotenv
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db so it picks up the mocks
    for key in list(sys.modules.keys()):
        if "memory.firestore_db" in key or key == "memory.firestore_db":
            del sys.modules[key]


# Install at module level — must run before any memory.firestore_db import.
_install_firestore_mock()


# ---------------------------------------------------------------------------
# Test environment
# ---------------------------------------------------------------------------

_ENV: dict[str, str] = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    # CRON_DEV_BYPASS=false forces real hub-session auth on every /api/* request.
    # Tests that want auth bypassed use app.dependency_overrides instead.
    "CRON_DEV_BYPASS": "false",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _stub_web_server_imports() -> dict:
    """Return sys.modules stubs for heavy web_server dependencies.

    Clears the cached web_server module so the next import picks up the stubs,
    mirroring test_hub_chat.py and test_web_server.py.
    """
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_habit(habit_id: str = "hab1", status: str = "active") -> dict:
    """Return a minimal habit definition dict (daily schedule)."""
    return {
        "id": habit_id,
        "name": "Morning Pushups",
        "type": "habit",
        "dose": None,
        "slot": "Morning",
        "status": status,
        # "daily" → _is_scheduled returns True for every date
        "schedule_history": [{"effective_from": "2020-01-01", "days": "daily"}],
        "created_at": "2026-06-01T00:00:00+00:00",
    }


def _today_iso() -> str:
    return datetime.now(_TZ).date().isoformat()


def _yesterday_iso() -> str:
    return (datetime.now(_TZ).date() - timedelta(days=1)).isoformat()


def _day_before_yesterday_iso() -> str:
    return (datetime.now(_TZ).date() - timedelta(days=2)).isoformat()


# ---------------------------------------------------------------------------
# Auth gate: no session → 401 (T-28-AC)
# ---------------------------------------------------------------------------

def test_habits_routes_require_session():
    """GET /api/habits, POST /api/habits, and POST /api/habits/{id}/checkin
    without a session cookie must return 401 (T-28-AC).

    No dependency override is set so the real require_hub_session runs.
    CRON_DEV_BYPASS=false ensures the bypass is inactive.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, _ENV):
            client = TestClient(ws.app, raise_server_exceptions=False)

            get_resp = client.get("/api/habits")
            assert get_resp.status_code == 401, (
                f"GET /api/habits must return 401 without session, got {get_resp.status_code}"
            )

            post_resp = client.post("/api/habits", json={
                "name": "Morning Run", "type": "habit",
            })
            assert post_resp.status_code == 401, (
                f"POST /api/habits must return 401 without session, got {post_resp.status_code}"
            )

            checkin_resp = client.post(
                "/api/habits/hab1/checkin",
                json={"date": _today_iso(), "done": True},
            )
            assert checkin_resp.status_code == 401, (
                f"POST /api/habits/{{id}}/checkin must return 401 without session, "
                f"got {checkin_resp.status_code}"
            )


# ---------------------------------------------------------------------------
# TestCheckinEndpoint — toggle, yesterday accept, today-2 reject
# ---------------------------------------------------------------------------

class TestCheckinEndpoint:
    """POST /api/habits/{id}/checkin behavior (D-07, D-11, D-12, T-28-backfill)."""

    def _call_checkin(self, payload: dict) -> "Response":  # type: ignore[return]
        """Helper: POST /api/habits/hab1/checkin with the given payload.

        Sets up a fresh TestClient with auth bypassed via dependency override
        and HabitStore.log_completion mocked.
        """
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            mock_store = MagicMock()
            mock_store.log_completion.return_value = None

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.HabitStore", return_value=mock_store):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        return client.post("/api/habits/hab1/checkin", json=payload)
                finally:
                    ws.app.dependency_overrides.clear()

    def test_checkin_done_today_returns_200(self):
        """done=True for today → 200 {"ok": True} and log_completion called (D-07)."""
        resp = self._call_checkin({"date": _today_iso(), "done": True})
        assert resp.status_code == 200, (
            f"Expected 200 for today checkin, got {resp.status_code}: {resp.text}"
        )
        assert resp.json() == {"ok": True}

    def test_checkin_undone_today_returns_200(self):
        """done=False for today → 200 (un-check toggle, D-07)."""
        resp = self._call_checkin({"date": _today_iso(), "done": False})
        assert resp.status_code == 200, (
            f"Expected 200 for today un-check, got {resp.status_code}: {resp.text}"
        )
        assert resp.json() == {"ok": True}

    def test_checkin_accepts_yesterday(self):
        """Yesterday's date is within the backfill window (D-11) — must return 200."""
        resp = self._call_checkin({"date": _yesterday_iso(), "done": True})
        assert resp.status_code == 200, (
            f"Expected 200 for yesterday checkin (backfill window), "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_checkin_rejects_day_before_yesterday(self):
        """Date older than yesterday is outside the backfill window (D-11/D-12) — 400.

        Required by T-28-backfill: any date before yesterday (in Asia/Jerusalem) must
        be rejected so Amit cannot retroactively rewrite locked history.
        """
        resp = self._call_checkin({"date": _day_before_yesterday_iso(), "done": True})
        assert resp.status_code == 400, (
            f"Expected 400 for day-before-yesterday date (outside backfill window), "
            f"got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", {})
        assert "error" in detail, (
            f"400 response body must include 'error' key in detail, got: {detail}"
        )


# ---------------------------------------------------------------------------
# test_list_scheduled_today — TIME-06 API contract
# ---------------------------------------------------------------------------

def test_list_scheduled_today():
    """GET /api/habits returns scheduled_today + done_today flags (TIME-06).

    A daily habit (schedule_history[0].days="daily") must have scheduled_today=True.
    When no completion exists for today, done_today=False.
    After a completion is present (mock updated), done_today=True.

    The flags allow the HabitsBand (TIME-06) to render one-tap items without
    making additional per-habit calls.
    """
    today_iso = _today_iso()
    habit = _make_habit("hab1")

    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        mock_store = MagicMock()
        mock_store.list_active.return_value = [habit]
        mock_store.get_completions_for_date.return_value = {}  # not done yet
        mock_store.get_history.return_value = {"streak": 3, "grid": []}

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = (
                lambda: "amit.grupper@gmail.com"
            )
            try:
                with patch("memory.firestore_db.HabitStore", return_value=mock_store):
                    client = TestClient(ws.app, raise_server_exceptions=True)

                    # Scenario 1: no completion yet — scheduled_today=True, done_today=False
                    resp1 = client.get("/api/habits")
                    assert resp1.status_code == 200, (
                        f"Expected 200 for GET /api/habits, got {resp1.status_code}: {resp1.text}"
                    )
                    data1 = resp1.json()
                    assert "habits" in data1, (
                        f"Response must have 'habits' key, got: {list(data1.keys())}"
                    )
                    assert len(data1["habits"]) == 1, (
                        f"Expected 1 habit, got: {len(data1['habits'])}"
                    )
                    h1 = data1["habits"][0]
                    assert "scheduled_today" in h1, (
                        f"Habit must have 'scheduled_today' flag (TIME-06), keys: {list(h1.keys())}"
                    )
                    assert "done_today" in h1, (
                        f"Habit must have 'done_today' flag (TIME-06), keys: {list(h1.keys())}"
                    )
                    assert h1["scheduled_today"] is True, (
                        f"Daily habit must have scheduled_today=True, got: {h1.get('scheduled_today')}"
                    )
                    assert h1["done_today"] is False, (
                        f"Habit with no completion must have done_today=False, "
                        f"got: {h1.get('done_today')}"
                    )

                    # Scenario 2: completion present — done_today must flip to True
                    mock_store.get_completions_for_date.return_value = {
                        "hab1": {
                            "habit_id": "hab1",
                            "date": today_iso,
                            "done": True,
                            "dose_taken": None,
                            "logged_at": "2026-06-30T10:00:00+00:00",
                        }
                    }
                    resp2 = client.get("/api/habits")
                    assert resp2.status_code == 200
                    h2 = resp2.json()["habits"][0]
                    assert h2["done_today"] is True, (
                        f"Habit with a completion must have done_today=True, "
                        f"got: {h2.get('done_today')}"
                    )
            finally:
                ws.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# test_patch_schedule_rejects_past_effective_from — D-19 gate (T-28-schedule)
# ---------------------------------------------------------------------------

def test_patch_schedule_rejects_past_effective_from():
    """PATCH /api/habits/{id} with a schedule revision whose effective_from is in the
    past must return 400 (D-19 / T-28-schedule).

    Sending effective_from="2020-01-01" (always in the past) with a days change
    must be rejected to prevent retroactive history rewrites.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        mock_store = MagicMock()
        mock_store.get.return_value = _make_habit("hab1")
        mock_store.update.return_value = _make_habit("hab1")

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = (
                lambda: "amit.grupper@gmail.com"
            )
            try:
                with patch("memory.firestore_db.HabitStore", return_value=mock_store):
                    client = TestClient(ws.app, raise_server_exceptions=False)
                    resp = client.patch(
                        "/api/habits/hab1",
                        json={
                            "days": [0, 2, 4],          # Mon/Wed/Fri schedule change
                            "effective_from": "2020-01-01",  # always in the past
                        },
                    )
            finally:
                ws.app.dependency_overrides.clear()

    assert resp.status_code == 400, (
        f"Expected 400 for past effective_from schedule revision (D-19), "
        f"got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", {})
    assert "error" in detail, (
        f"400 response must include 'error' key in detail, got: {detail}"
    )


# ---------------------------------------------------------------------------
# test_hard_delete_requires_completing — D-20 gate
# ---------------------------------------------------------------------------

def test_hard_delete_requires_completing():
    """Hard-delete on an active (non-soft-deleted) habit must return 409.

    The hard-delete route must first check that the habit's status is
    'completing' (i.e., it has gone through the soft-delete / undo-toast flow).
    An active habit → 409 so the client must soft-delete first.
    """
    stubs = _stub_web_server_imports()
    active_habit = _make_habit("hab1", status="active")
    assert active_habit["status"] == "active", "test setup: habit must be active"

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        mock_store = MagicMock()
        # get() returns an active habit (status="active", not "completing")
        mock_store.get.return_value = active_habit

        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = (
                lambda: "amit.grupper@gmail.com"
            )
            try:
                with patch("memory.firestore_db.HabitStore", return_value=mock_store):
                    client = TestClient(ws.app, raise_server_exceptions=False)
                    resp = client.post("/api/habits/hab1/hard-delete")
            finally:
                ws.app.dependency_overrides.clear()

    assert resp.status_code == 409, (
        f"Expected 409 for hard-delete on active habit (D-20 gate), "
        f"got {resp.status_code}: {resp.text}"
    )
