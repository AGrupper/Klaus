"""TickTick task integration — add tasks and read today's task list.

Uses the TickTick Open API (developer.ticktick.com).

Two public functions:
  add_task(title, notes, deadline, reminder, tags, project_id) → dict
  get_today_tasks() → dict with today/overdue/due_today lists

Field mapping from Klaus schema → TickTick:
  title    → title
  notes    → content
  deadline → dueDate (YYYY-MM-DDT00:00:00+TZ), no push alarm
  reminder → dueDate (YYYY-MM-DDTHH:MM:SS+TZ), alarm at due time
  tags     → tags

If both deadline and reminder are supplied, reminder wins (push notification
intent takes precedence over the silent due date).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from mcp_tools.ticktick_auth import get_valid_access_token, refresh_and_persist

logger = logging.getLogger(__name__)

_API_BASE = "https://ticktick.com/open/v1"
_TZ = ZoneInfo("Asia/Jerusalem")


# ------------------------------------------------------------------ #
# HTTP helpers (auto-retry on 401)                                   #
# ------------------------------------------------------------------ #

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """Shared keep-alive session — reuses the TLS connection across API calls.

    No auth state lives on the session (the bearer header is built per call
    via _headers), so sharing is safe and the 401-refresh retry still works.
    """
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_valid_access_token()}",
        "Content-Type": "application/json",
    }


def _api_get(endpoint: str, **kwargs) -> dict | list:
    """GET {_API_BASE}/{endpoint}, refreshing on 401."""
    url = f"{_API_BASE}/{endpoint}"
    resp = _get_session().get(url, headers=_headers(), timeout=15, **kwargs)
    if resp.status_code == 401:
        token = refresh_and_persist()
        resp = _get_session().get(url,
                                  headers={"Authorization": f"Bearer {token}",
                                           "Content-Type": "application/json"},
                                  timeout=15, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _api_post(endpoint: str, body: dict) -> dict:
    """POST {_API_BASE}/{endpoint}, refreshing on 401."""
    url = f"{_API_BASE}/{endpoint}"
    resp = _get_session().post(url, headers=_headers(), json=body, timeout=15)
    if resp.status_code == 401:
        token = refresh_and_persist()
        resp = _get_session().post(url,
                                   headers={"Authorization": f"Bearer {token}",
                                            "Content-Type": "application/json"},
                                   json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------ #
# Timezone helpers                                                   #
# ------------------------------------------------------------------ #

def _to_ticktick_datetime(dt_str: str, is_reminder: bool) -> str:
    """Convert a Klaus date/datetime string to a TickTick dueDate string.

    Args:
        dt_str: "YYYY-MM-DD" (deadline) or "YYYY-MM-DDTHH:MM" (reminder).
        is_reminder: True → include time component; False → midnight.

    Returns:
        ISO 8601 datetime string with Asia/Jerusalem offset.
    """
    if is_reminder:
        # Parse "YYYY-MM-DDTHH:MM" — no seconds, no tz
        naive = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
    else:
        # Deadline: date-only, use start of day
        naive = datetime.strptime(dt_str, "%Y-%m-%d")
    local = naive.replace(tzinfo=_TZ)
    # TickTick expects the offset in +HH:MM form, not 'Israel Standard Time'
    return local.isoformat()


# ------------------------------------------------------------------ #
# Public API                                                         #
# ------------------------------------------------------------------ #

def add_task(
    title: str,
    notes: str | None = None,
    deadline: str | None = None,
    reminder: str | None = None,
    tags: list[str] | None = None,
    project_id: str | None = None,
) -> dict:
    """Add a task to TickTick.

    Args:
        title: Task title.
        notes: Optional body text.
        deadline: Optional date-only due date "YYYY-MM-DD". No push alarm.
        reminder: Optional datetime "YYYY-MM-DDTHH:MM". Adds a push alarm at that time.
                  If both deadline and reminder are set, reminder wins.
        tags: Optional tag list.
        project_id: Target project. Defaults to TICKTICK_PROJECT_ID env var, then Inbox.

    Returns:
        Dict with "task_id", "title", "confirmation" on success,
        or "error" + "title" on failure.
    """
    body: dict = {"title": title}

    if notes:
        body["content"] = notes

    if reminder:
        body["dueDate"] = _to_ticktick_datetime(reminder, is_reminder=True)
        body["reminders"] = ["TRIGGER:PT0S"]
    elif deadline:
        body["dueDate"] = _to_ticktick_datetime(deadline, is_reminder=False)

    if tags:
        body["tags"] = list(tags)

    pid = project_id or os.getenv("TICKTICK_PROJECT_ID") or None
    if pid:
        body["projectId"] = pid

    try:
        created = _api_post("task", body)
    except requests.HTTPError as exc:
        logger.error("ticktick_tool.add_task failed for title=%r: %s", title, exc)
        return {"error": f"Failed to create TickTick task: {exc}", "title": title}

    task_id = created.get("id", "")
    return {
        "task_id": task_id,
        "title": title,
        "confirmation": f"Task '{title}' added to TickTick.",
    }


def get_today_tasks() -> dict:
    """Return today's and overdue TickTick tasks for the morning briefing.

    Fetches all incomplete tasks across all projects, then filters by dueDate
    relative to today in Asia/Jerusalem.

    Returns:
        {
            "today":    [{"title": str, "tags": list[str]}, ...],
            "overdue":  [{"title": str, "due": str, "tags": list[str]}, ...],
            "due_today": [],  # TickTick has no separate concept; matches today
            "staleness_warning": None,  # real-time API, never stale
        }
    Never raises — returns error indicator dict on any failure.
    """
    today = date.today().isoformat()  # "YYYY-MM-DD" in local time
    today_tasks: list[dict] = []
    overdue_tasks: list[dict] = []

    try:
        projects = _api_get("project")
        if not isinstance(projects, list):
            raise ValueError(f"Unexpected /project response: {type(projects)}")

        for project in projects:
            pid = project.get("id")
            if not pid:
                continue
            try:
                data = _api_get(f"project/{pid}/data")
            except requests.HTTPError:
                logger.warning("ticktick_tool: failed to fetch project %s tasks", pid)
                continue

            tasks = data.get("tasks") or [] if isinstance(data, dict) else []
            for task in tasks:
                if task.get("status") != 0:  # 0 = incomplete
                    continue
                due_raw = task.get("dueDate") or ""
                title = task.get("title") or ""
                task_tags = task.get("tags") or []

                if not due_raw:
                    continue  # skip tasks with no due date

                # Extract date portion (first 10 chars of ISO string)
                due_date = due_raw[:10]

                if due_date == today:
                    today_tasks.append({"title": title, "tags": task_tags})
                elif due_date < today:
                    overdue_tasks.append({"title": title, "due": due_date, "tags": task_tags})

    except Exception:
        logger.warning("ticktick_tool.get_today_tasks failed", exc_info=True)
        return {"staleness_warning": "Task data unavailable, sir."}

    return {
        "today": today_tasks,
        "overdue": overdue_tasks,
        "due_today": [],
        "staleness_warning": None,
    }
