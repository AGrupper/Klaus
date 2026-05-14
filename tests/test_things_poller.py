# tests/test_things_poller.py
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest
from google.api_core.exceptions import GoogleAPICallError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(doc_id: str = "abc123", title: str = "Test task",
               deadline: str | None = None, reminder: str | None = None) -> dict:
    return {
        "doc_id": doc_id,
        "title": title,
        "notes": "",
        "deadline": deadline,
        "reminder": reminder,
        "tags": [],
        "status": "pending",
    }


def _make_poller():
    """Return a ThingsPoller with a fully mocked FirestoreQueue."""
    from local_mac.things_poller import ThingsPoller
    queue = MagicMock()
    queue.fetch_pending.return_value = []
    return ThingsPoller(firestore_queue=queue, poll_interval_seconds=0), queue


# ---------------------------------------------------------------------------
# _iso_to_applescript_date
# ---------------------------------------------------------------------------

class TestIsoToApplescriptDate:
    def test_plain_date(self):
        from local_mac.things_poller import _iso_to_applescript_date
        assert _iso_to_applescript_date("2026-05-15") == "15/05/2026"

    def test_datetime_string_strips_time(self):
        from local_mac.things_poller import _iso_to_applescript_date
        assert _iso_to_applescript_date("2026-05-15T19:00") == "15/05/2026"

    def test_single_digit_day_and_month(self):
        from local_mac.things_poller import _iso_to_applescript_date
        assert _iso_to_applescript_date("2026-01-05") == "05/01/2026"


# ---------------------------------------------------------------------------
# _build_applescript
# ---------------------------------------------------------------------------

class TestBuildApplescript:
    def test_no_reminder_no_deadline(self):
        poller, _ = _make_poller()
        script = poller._build_applescript(_make_task())
        assert 'make new to do' in script
        assert 'schedule' not in script
        assert 'activation date' not in script

    def test_deadline_uses_dd_mm_yyyy(self):
        poller, _ = _make_poller()
        script = poller._build_applescript(_make_task(deadline="2026-05-20"))
        assert '20/05/2026' in script
        assert '2026-05-20' not in script  # ISO format must NOT appear

    def test_reminder_uses_schedule_verb_not_property(self):
        poller, _ = _make_poller()
        script = poller._build_applescript(_make_task(reminder="2026-05-15T19:00"))
        assert 'schedule t for date' in script
        assert 'activation date:(' not in script  # the read-only property must NOT be set

    def test_reminder_date_in_dd_mm_yyyy(self):
        poller, _ = _make_poller()
        script = poller._build_applescript(_make_task(reminder="2026-05-15T19:00"))
        assert '15/05/2026' in script

    def test_reminder_assigns_todo_to_variable(self):
        poller, _ = _make_poller()
        script = poller._build_applescript(_make_task(reminder="2026-05-15T19:00"))
        assert 'set t to make new to do' in script


# ---------------------------------------------------------------------------
# run_forever poll loop — claim-before-inject behaviour
# ---------------------------------------------------------------------------

class TestRunForeverClaimBeforeInject:
    """Regression tests for the infinite-duplication bug.

    Root cause: AppleScript (CalledProcessError / TimeoutExpired) was raised
    AFTER Things 3 had already created the to-do, but the doc was left as
    'pending' because mark_consumed was never called. The doc was re-fetched
    every 30s and the to-do was re-created infinitely.

    Fix: claim doc as 'in_flight' BEFORE running AppleScript. Failed in-flight
    docs are excluded from fetch_pending and never auto-retried.
    """

    def _run_one_tick(self, poller, queue, tasks):
        """Run exactly one poll tick with the given task list."""
        queue.fetch_pending.return_value = tasks
        # Patch push_things_snapshot and time.sleep so the loop stops after one tick.
        with patch("local_mac.things_poller.push_things_snapshot"), \
             patch("local_mac.things_poller.time.sleep", side_effect=StopIteration):
            try:
                poller.run_forever()
            except StopIteration:
                pass

    def test_happy_path_marks_in_flight_then_consumed(self):
        poller, queue = _make_poller()
        task = _make_task()
        with patch.object(poller, "inject_into_things"):
            self._run_one_tick(poller, queue, [task])

        queue.mark_in_flight.assert_called_once_with("abc123")
        queue.mark_consumed.assert_called_once_with("abc123")

    def test_timeout_leaves_doc_in_flight_not_re_injected(self):
        """THE regression test: CalledProcessError/TimeoutExpired must not
        leave the doc as 'pending'. mark_in_flight is called first; on failure
        mark_consumed must NOT be called so the doc stays in_flight."""
        poller, queue = _make_poller()
        task = _make_task()
        with patch.object(poller, "inject_into_things",
                          side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=60)):
            self._run_one_tick(poller, queue, [task])

        queue.mark_in_flight.assert_called_once_with("abc123")
        queue.mark_consumed.assert_not_called()

    def test_called_process_error_leaves_doc_in_flight(self):
        poller, queue = _make_poller()
        task = _make_task()
        with patch.object(poller, "inject_into_things",
                          side_effect=subprocess.CalledProcessError(1, "osascript")):
            self._run_one_tick(poller, queue, [task])

        queue.mark_in_flight.assert_called_once_with("abc123")
        queue.mark_consumed.assert_not_called()

    def test_mark_in_flight_failure_skips_injection(self):
        """If Firestore claim fails, Things 3 must NOT be touched."""
        poller, queue = _make_poller()
        task = _make_task()
        queue.mark_in_flight.side_effect = GoogleAPICallError("network error")
        with patch.object(poller, "inject_into_things") as mock_inject:
            self._run_one_tick(poller, queue, [task])

        mock_inject.assert_not_called()
        queue.mark_consumed.assert_not_called()

    def test_multiple_tasks_each_claimed_independently(self):
        poller, queue = _make_poller()
        tasks = [_make_task("id1", "Task 1"), _make_task("id2", "Task 2")]
        with patch.object(poller, "inject_into_things"):
            self._run_one_tick(poller, queue, tasks)

        queue.mark_in_flight.assert_has_calls([call("id1"), call("id2")])
        queue.mark_consumed.assert_has_calls([call("id1"), call("id2")])
