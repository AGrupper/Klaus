"""Tests for the Paper Hub backend additions.

Covers:
  - compute_routine_streak: pure streak semantics (done chain, miss break,
    pending neutrality, empty-day neutrality, done_today gating)
  - /api/routines: 401 gate, grouped GET (members + Unassigned), create,
    delete detaches members
  - /api/settings PATCH: hex/font validation, persistence round-trip
  - /api/notifications: 401 gate, typed feed shaping (review/action/alert/system)

Mock strategy mirrors tests/test_habits_api.py: Firestore mocked at module
level, heavy web_server deps stubbed per-test, stores patched by string at
"memory.firestore_db.<Store>" (the facade path the routes import lazily).
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Firestore mock — installed BEFORE any memory.firestore_db import
# (verbatim pattern from test_habits_api.py)
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> None:
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
    firestore_mock.SERVER_TIMESTAMP = object()

    class _ArrayUnion:
        def __init__(self, values):
            self.values = list(values)

    firestore_mock.ArrayUnion = _ArrayUnion
    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    class _FieldFilter:
        def __init__(self, field, op, value):
            self.field, self.op, self.value = field, op, value

    bq = sys.modules.get("google.cloud.firestore_v1.base_query", MagicMock())
    bq.FieldFilter = _FieldFilter
    sys.modules["google.cloud.firestore_v1.base_query"] = bq
    if "google.cloud.firestore_v1" in sys.modules:
        sys.modules["google.cloud.firestore_v1"].base_query = bq
    else:
        fv1 = MagicMock()
        fv1.base_query = bq
        sys.modules["google.cloud.firestore_v1"] = fv1

    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    for key in list(sys.modules.keys()):
        if key == "memory.firestore_db" or key.startswith("memory.stores"):
            del sys.modules[key]


_install_firestore_mock()

_ENV: dict[str, str] = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    "CRON_DEV_BYPASS": "false",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _stub_web_server_imports() -> dict:
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth.google": MagicMock(name="core.auth.google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs


# ---------------------------------------------------------------------------
# Pure function: compute_routine_streak
# ---------------------------------------------------------------------------

TODAY = date(2026, 8, 17)


def _daily_habit(habit_id: str) -> dict:
    return {
        "id": habit_id,
        "name": habit_id,
        "schedule_history": [{"effective_from": "2020-01-01", "days": "daily"}],
    }


def _completions(habit_id: str, dates: list[str]) -> dict:
    return {habit_id: {d: {"done": True} for d in dates}}


def _iso(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


class TestComputeRoutineStreak:
    def _compute(self, members, completions):
        from memory.stores.habits import compute_routine_streak
        return compute_routine_streak(members, completions, TODAY)

    def test_all_members_done_chain_counts(self):
        """3 consecutive full days (incl. today) → streak 3, done_today True."""
        members = [_daily_habit("a"), _daily_habit("b")]
        done_days = [_iso(0), _iso(1), _iso(2)]
        completions = {**_completions("a", done_days), **_completions("b", done_days)}
        result = self._compute(members, completions)
        assert result["streak"] == 3
        assert result["done_today"] is True
        assert result["scheduled_today"] == 2
        assert result["completed_today"] == 2

    def test_partial_day_older_than_yesterday_breaks(self):
        """A day (< yesterday) where one member missed breaks the streak."""
        members = [_daily_habit("a"), _daily_habit("b")]
        completions = {
            **_completions("a", [_iso(0), _iso(1), _iso(2), _iso(3)]),
            **_completions("b", [_iso(0), _iso(1), _iso(3)]),  # missed _iso(2)
        }
        result = self._compute(members, completions)
        assert result["streak"] == 2  # today + yesterday only

    def test_pending_today_is_neutral_not_break(self):
        """Incomplete today (backfill window) skips without breaking (D-12)."""
        members = [_daily_habit("a")]
        completions = _completions("a", [_iso(1), _iso(2)])  # today not done yet
        result = self._compute(members, completions)
        assert result["streak"] == 2
        assert result["done_today"] is False

    def test_unscheduled_day_is_neutral(self):
        """A weekday-gap day doesn't break the chain (mirrors habit semantics)."""
        # Scheduled every day EXCEPT the weekday of _iso(1)
        gap_weekday = (TODAY - timedelta(days=1)).weekday()
        days = [d for d in range(7) if d != gap_weekday]
        member = {
            "id": "a", "name": "a",
            "schedule_history": [{"effective_from": "2020-01-01", "days": days}],
        }
        completions = _completions("a", [_iso(0), _iso(2)])
        result = self._compute([member], completions)
        assert result["streak"] == 2

    def test_empty_routine_never_done_today(self):
        """No members → streak 0 and done_today False (no flame for nothing)."""
        result = self._compute([], {})
        assert result == {
            "streak": 0, "done_today": False,
            "scheduled_today": 0, "completed_today": 0,
        }


# ---------------------------------------------------------------------------
# /api/routines
# ---------------------------------------------------------------------------

def test_routines_routes_require_session():
    """GET/POST /api/routines without a session cookie → 401."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, _ENV):
            client = TestClient(ws.app, raise_server_exceptions=False)
            assert client.get("/api/routines").status_code == 401
            assert client.post("/api/routines", json={"name": "X"}).status_code == 401
            assert client.get("/api/notifications").status_code == 401
            assert client.get("/api/followups").status_code == 401
            assert client.patch(
                "/api/settings", json={"appearance": {
                    "accent": "#1C2540", "flame": "#B02A2A", "font": "default"}},
            ).status_code == 401


class TestRoutinesFeed:
    def _get_routines(self, routine_store, habit_store):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.RoutineStore", return_value=routine_store), \
                         patch("memory.firestore_db.HabitStore", return_value=habit_store):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        return client.get("/api/routines")
                finally:
                    ws.app.dependency_overrides.clear()

    def test_grouping_streak_and_unassigned(self):
        """Members group under their routine; orphans land in Unassigned."""
        routine_store = MagicMock()
        routine_store.list_all.return_value = [
            {"id": "r1", "name": "Nightly routine", "emoji": "🌙", "order": 1},
        ]
        habit_store = MagicMock()
        habit_a = {**_daily_habit("a"), "routine_id": "r1"}
        habit_b = _daily_habit("b")  # no routine_id → Unassigned
        habit_store.list_active.return_value = [habit_a, habit_b]
        today_iso = date.today().isoformat()
        habit_store.get_all_completions.return_value = {
            "a": {today_iso: {"done": True, "dose_taken": None}},
        }

        resp = self._get_routines(routine_store, habit_store)
        assert resp.status_code == 200
        routines = resp.json()["routines"]
        assert [r["name"] for r in routines] == ["Nightly routine", "Unassigned"]

        nightly = routines[0]
        assert [h["id"] for h in nightly["habits"]] == ["a"]
        assert nightly["habits"][0]["done_today"] is True
        assert nightly["scheduled_today"] == 1
        assert nightly["completed_today"] == 1
        assert isinstance(nightly["streak"], int)

        unassigned = routines[1]
        assert unassigned["id"] is None
        assert [h["id"] for h in unassigned["habits"]] == ["b"]
        assert unassigned["habits"][0]["done_today"] is False

    def test_create_routine_validates_and_returns_doc(self):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            store = MagicMock()
            store.create.return_value = {
                "id": "r9", "name": "Deep work", "emoji": None, "order": 0,
                "created_at": "2026-08-17T00:00:00+00:00",
            }
            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.RoutineStore", return_value=store), \
                         patch("memory.firestore_db.HabitStore", return_value=MagicMock()):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        ok = client.post("/api/routines", json={"name": "Deep work"})
                        assert ok.status_code == 200
                        assert ok.json()["id"] == "r9"
                        # Empty name must fail validation
                        bad = client.post("/api/routines", json={"name": ""})
                        assert bad.status_code == 422
                finally:
                    ws.app.dependency_overrides.clear()


def test_routine_store_delete_detaches_members():
    """RoutineStore.delete reassigns members to None and never deletes them."""
    from memory.stores.habits import RoutineStore

    store = RoutineStore.__new__(RoutineStore)  # skip __init__ (no client)
    store._col = MagicMock()
    habit_store = MagicMock()
    habit_store.list_active.return_value = [
        {"id": "a", "routine_id": "r1"},
        {"id": "b", "routine_id": "r2"},
        {"id": "c", "routine_id": "r1"},
    ]
    detached = store.delete("r1", habit_store)
    assert detached == 2
    habit_store.update.assert_any_call("a", {"routine_id": None})
    habit_store.update.assert_any_call("c", {"routine_id": None})
    habit_store.delete.assert_not_called()
    store._col.document.assert_called_with("r1")


# ---------------------------------------------------------------------------
# /api/settings PATCH
# ---------------------------------------------------------------------------

class TestSettingsPatch:
    def _patch_settings(self, payload, settings_store):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch(
                        "interfaces.routes.misc._get_hub_settings_store",
                        return_value=settings_store,
                    ):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        return client.patch("/api/settings", json=payload)
                finally:
                    ws.app.dependency_overrides.clear()

    def test_valid_patch_persists_and_echoes(self):
        store = MagicMock()
        appearance = {"accent": "#20563A", "flame": "#8F2D3C", "font": "rounded"}
        store.get.return_value = {
            "push_enabled_at": None,
            "appearance": appearance,
            "home_sections": {"leaveby": True, "stats": False,
                              "corner": True, "portfolio": False},
        }
        resp = self._patch_settings(
            {"appearance": appearance, "home_sections": {"stats": False}}, store
        )
        assert resp.status_code == 200
        store.set.assert_called_once_with({
            "appearance": appearance,
            "home_sections": {"stats": False},
        })
        assert resp.json()["appearance"]["font"] == "rounded"

    def test_bad_hex_and_font_rejected(self):
        store = MagicMock()
        bad_hex = self._patch_settings(
            {"appearance": {"accent": "1C2540", "flame": "#B02A2A", "font": "default"}},
            store,
        )
        assert bad_hex.status_code == 422
        bad_font = self._patch_settings(
            {"appearance": {"accent": "#1C2540", "flame": "#B02A2A", "font": "comic"}},
            store,
        )
        assert bad_font.status_code == 422
        bad_section = self._patch_settings({"home_sections": {"nonsense": True}}, store)
        assert bad_section.status_code == 422
        store.set.assert_not_called()

    def test_empty_patch_rejected(self):
        assert self._patch_settings({}, MagicMock()).status_code == 400


# ---------------------------------------------------------------------------
# /api/notifications
# ---------------------------------------------------------------------------

class TestNotificationsFeed:
    def test_typed_feed_shape_and_order(self):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient

            reviews_store = MagicMock()
            reviews_store.list_recent.return_value = [{
                "review_id": "rev1",
                "routine": "nightly",
                "target_date": "2026-08-16",
                "published_at": "2026-08-16T23:30:00+03:00",
                "review_text": "Protein landed at 158 g. " * 30,
                "claude_session_url": "https://claude.ai/chat/abc",
            }]
            actions_store = MagicMock()
            actions_store.get_recent.return_value = [{
                "id": "act1", "action": "task_create",
                "detail": "Filed 'call the base' to Things",
                "at": "2026-08-17T10:41:00+03:00",
            }]
            # get_days batches the whole window into one Firestore round trip;
            # only today carries entries, the other days are simply absent.
            outreach_store = MagicMock()
            outreach_store.get_days.side_effect = lambda days: {
                date.today().isoformat(): [
                    {"topic_key": "deadline:t1", "time": "17:20",
                     "final": "Hard deadline, Sir.", "kind": "hard_deadline"},
                    {"topic_key": "automation:x", "time": "14:02",
                     "final": "Automation failure, Sir: Garmin stale.",
                     "kind": "automation_failure"},
                ],
            }

            with patch.dict(os.environ, _ENV):
                ws.app.dependency_overrides[ws.require_hub_session] = (
                    lambda: "amit.grupper@gmail.com"
                )
                try:
                    with patch("memory.firestore_db.RoutineReviewStore",
                               return_value=reviews_store), \
                         patch("memory.firestore_db.RoutineRunStore",
                               return_value=MagicMock()), \
                         patch("memory.firestore_db.ActionLogStore",
                               return_value=actions_store), \
                         patch("memory.firestore_db.OutreachLogStore",
                               return_value=outreach_store), \
                         patch("core.hub.reviews._review_for_client",
                               side_effect=lambda review, runs: review):
                        client = TestClient(ws.app, raise_server_exceptions=False)
                        resp = client.get("/api/notifications?days=3")
                finally:
                    ws.app.dependency_overrides.clear()

            assert resp.status_code == 200
            items = resp.json()["notifications"]
            by_type = {i["type"] for i in items}
            assert by_type == {"review", "action", "alert", "system"}

            review = next(i for i in items if i["type"] == "review")
            assert review["title"] == "Nightly review"
            assert review["claude_session_url"] == "https://claude.ai/chat/abc"
            assert len(review["body"]) <= 245  # snippet, not the whole review

            system = next(i for i in items if i["type"] == "system")
            assert system["id"] == "automation:x"

            # Newest first
            ats = [i["at"] for i in items]
            assert ats == sorted(ats, reverse=True)
