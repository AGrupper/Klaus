"""Unit tests for mcp_tools/ticktick_tool.py."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

def _make_task(title="Buy milk", due=None, status=0, tags=None):
    return {"title": title, "dueDate": due, "status": status, "tags": tags or []}


# ------------------------------------------------------------------ #
# _to_ticktick_datetime                                              #
# ------------------------------------------------------------------ #

class TestToTicktickDatetime:
    def test_deadline_produces_midnight(self):
        from mcp_tools.ticktick_tool import _to_ticktick_datetime
        result = _to_ticktick_datetime("2026-06-01", is_reminder=False)
        assert result.startswith("2026-06-01T00:00:00")

    def test_reminder_preserves_time(self):
        from mcp_tools.ticktick_tool import _to_ticktick_datetime
        result = _to_ticktick_datetime("2026-06-01T19:00", is_reminder=True)
        assert "2026-06-01T19:00:00" in result

    def test_result_contains_tz_offset(self):
        from mcp_tools.ticktick_tool import _to_ticktick_datetime
        result = _to_ticktick_datetime("2026-06-01T09:30", is_reminder=True)
        # Asia/Jerusalem offset is +02 or +03 depending on DST
        assert "+" in result or result.endswith("Z")


# ------------------------------------------------------------------ #
# add_task                                                           #
# ------------------------------------------------------------------ #

class TestAddTask:
    def _patch(self, created=None):
        created = created or {"id": "abc123", "title": "Test"}
        return patch("mcp_tools.ticktick_tool._api_post", return_value=created)

    def test_success_returns_task_id(self):
        with self._patch():
            from mcp_tools.ticktick_tool import add_task
            result = add_task("Buy milk")
        assert result["task_id"] == "abc123"
        assert result["title"] == "Buy milk"
        assert "error" not in result

    def test_reminder_sets_dueDate_and_alarm(self):
        with patch("mcp_tools.ticktick_tool._api_post") as mock_post:
            mock_post.return_value = {"id": "x"}
            from mcp_tools.ticktick_tool import add_task
            add_task("Test", reminder="2026-05-20T19:00")
        body = mock_post.call_args[0][1]
        assert "T19:00:00" in body["dueDate"]
        assert body["reminders"] == ["TRIGGER:PT0S"]

    def test_deadline_sets_dueDate_no_alarm(self):
        with patch("mcp_tools.ticktick_tool._api_post") as mock_post:
            mock_post.return_value = {"id": "x"}
            from mcp_tools.ticktick_tool import add_task
            add_task("Test", deadline="2026-06-01")
        body = mock_post.call_args[0][1]
        assert "2026-06-01" in body["dueDate"]
        assert "reminders" not in body

    def test_reminder_wins_over_deadline(self):
        with patch("mcp_tools.ticktick_tool._api_post") as mock_post:
            mock_post.return_value = {"id": "x"}
            from mcp_tools.ticktick_tool import add_task
            add_task("Test", deadline="2026-06-01", reminder="2026-05-20T19:00")
        body = mock_post.call_args[0][1]
        assert "T19:00:00" in body["dueDate"]
        assert body["reminders"] == ["TRIGGER:PT0S"]

    def test_http_error_returns_error_dict(self):
        import requests
        with patch("mcp_tools.ticktick_tool._api_post",
                   side_effect=requests.HTTPError("500")):
            from mcp_tools.ticktick_tool import add_task
            result = add_task("Test")
        assert "error" in result
        assert result["title"] == "Test"

    def test_tags_passed_through(self):
        with patch("mcp_tools.ticktick_tool._api_post") as mock_post:
            mock_post.return_value = {"id": "x"}
            from mcp_tools.ticktick_tool import add_task
            add_task("Test", tags=["work", "urgent"])
        body = mock_post.call_args[0][1]
        assert body["tags"] == ["work", "urgent"]

    def test_project_id_env_var(self, monkeypatch):
        monkeypatch.setenv("TICKTICK_PROJECT_ID", "proj_abc")
        with patch("mcp_tools.ticktick_tool._api_post") as mock_post:
            mock_post.return_value = {"id": "x"}
            from mcp_tools.ticktick_tool import add_task
            add_task("Test")
        body = mock_post.call_args[0][1]
        assert body["projectId"] == "proj_abc"


# ------------------------------------------------------------------ #
# get_today_tasks                                                    #
# ------------------------------------------------------------------ #

class TestGetTodayTasks:
    def _projects(self):
        return [{"id": "p1"}, {"id": "p2"}]

    def _project_data(self, tasks):
        return {"tasks": tasks}

    def test_today_and_overdue_split(self):
        today = date.today().isoformat()
        yesterday = "2000-01-01"
        tasks_p1 = [
            _make_task("Today task", due=f"{today}T09:00:00+03:00"),
            _make_task("Overdue task", due=f"{yesterday}T09:00:00+03:00"),
        ]

        def fake_get(endpoint):
            if endpoint == "project":
                return [{"id": "p1"}]
            return {"tasks": tasks_p1}

        with patch("mcp_tools.ticktick_tool._api_get", side_effect=fake_get):
            from mcp_tools.ticktick_tool import get_today_tasks
            result = get_today_tasks()

        assert len(result["today"]) == 1
        assert result["today"][0]["title"] == "Today task"
        assert len(result["overdue"]) == 1
        assert result["overdue"][0]["title"] == "Overdue task"
        assert result["staleness_warning"] is None

    def test_completed_tasks_excluded(self):
        today = date.today().isoformat()
        tasks = [_make_task("Done", due=f"{today}T09:00:00", status=2)]

        with patch("mcp_tools.ticktick_tool._api_get",
                   side_effect=lambda ep: [{"id": "p1"}] if ep == "project" else {"tasks": tasks}):
            from mcp_tools.ticktick_tool import get_today_tasks
            result = get_today_tasks()

        assert result["today"] == []

    def test_tasks_without_due_date_excluded(self):
        tasks = [_make_task("No due", due=None)]

        with patch("mcp_tools.ticktick_tool._api_get",
                   side_effect=lambda ep: [{"id": "p1"}] if ep == "project" else {"tasks": tasks}):
            from mcp_tools.ticktick_tool import get_today_tasks
            result = get_today_tasks()

        assert result["today"] == []
        assert result["overdue"] == []

    def test_api_failure_returns_staleness_warning(self):
        import requests
        with patch("mcp_tools.ticktick_tool._api_get",
                   side_effect=requests.HTTPError("401")):
            from mcp_tools.ticktick_tool import get_today_tasks
            result = get_today_tasks()

        assert result.get("staleness_warning") == "Task data unavailable, sir."

    def test_due_today_always_empty(self):
        with patch("mcp_tools.ticktick_tool._api_get", return_value=[]):
            from mcp_tools.ticktick_tool import get_today_tasks
            result = get_today_tasks()
        assert result["due_today"] == []
