"""Local macOS poller for the Things 3 cloud queue.

Standalone daemon that runs on the user's MacBook (NOT in Cloud Run).
It polls the Firestore queue populated by the cloud agent and injects
each pending task into Things 3 via AppleScript (per `docs/PRD.md` §2 and
`docs/TECHNICAL_PLAN.md` §3.5).

Usage:
    python -m local_mac.things_poller           # long-running daemon
    python -m local_mac.things_poller --once    # drain once then exit
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)

# Seconds before an osascript call is considered hung and killed.
APPLESCRIPT_TIMEOUT_SECONDS = 60


def _escape_applescript(value: str) -> str:
    """Escape backslashes and double quotes for safe embedding in AppleScript strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _iso_to_applescript_date(iso_date: str) -> str:
    """Convert an ISO date string to DD/MM/YYYY for AppleScript on Israeli locale (en_IL).

    AppleScript's `date` coercion is locale-sensitive. On Israeli/European locales
    the expected format is DD/MM/YYYY. Passing YYYY-MM-DD silently produces wrong dates
    (e.g. "2026-05-15" parses as Nov 16, 2025 on en_IL).

    Args:
        iso_date: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM" (time component is ignored;
                  use the `schedule` verb for the date, not activation date property).

    Returns:
        "DD/MM/YYYY" string suitable for `date "..."` in AppleScript on en_IL.
    """
    date_part = iso_date[:10]  # strip any time component
    year, month, day = date_part.split("-")
    return f"{day}/{month}/{year}"


def _shape_task(t: dict) -> dict:
    """Project a things.py raw task dict to the snapshot schema."""
    return {
        "uuid": t.get("uuid", ""),
        "title": t.get("title", ""),
        "area": t.get("area", "") or "",
        "project": t.get("project", "") or None,
        "due_date": t.get("deadline") or None,
    }


def push_things_snapshot(firestore_queue) -> None:
    """Read today's Things 3 tasks and write a snapshot to Firestore.

    Called inside the main poll loop. Failures are logged but never raised —
    they must not crash the long-running poller daemon.

    NOTE: Requires the things.py library on the Mac. Install with:
        pip install things.py

    Args:
        firestore_queue: A FirestoreQueue instance (used to access the Firestore client).
    """
    try:
        import things
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Jerusalem")
        today_iso = datetime.now(tz).date().isoformat()

        today_tasks = [_shape_task(t) for t in (things.today() or [])]
        today_uuids = {t["uuid"] for t in today_tasks}

        all_due = things.due() or []
        overdue = [
            _shape_task(t) for t in all_due
            if t.get("deadline") and t["deadline"] < today_iso
        ]
        due_today = [
            _shape_task(t) for t in all_due
            if t.get("deadline") == today_iso and t.get("uuid", "") not in today_uuids
        ]

        snapshot = {
            "version": 1,
            "updated_at": datetime.now(tz).isoformat(),
            "today": today_tasks,
            "overdue": overdue,
            "due_today": due_today,
        }

        # Write snapshot to Firestore using the queue's underlying client.
        # FirestoreQueue exposes its Firestore client as ._client (see memory/firestore_db.py).
        firestore_queue._client.collection("things_snapshot").document("latest").set(snapshot)
        logger.debug(
            "push_things_snapshot: wrote %d today, %d overdue, %d due_today",
            len(today_tasks), len(overdue), len(due_today),
        )
    except ImportError:
        logger.warning("push_things_snapshot: things.py not installed — run: pip install things.py")
    except Exception as exc:
        logger.warning("push_things_snapshot: failed — %s", exc)


class ThingsPoller:
    """Polls Firestore and injects to-dos into Things 3 locally via AppleScript."""

    def __init__(self, firestore_queue: object, poll_interval_seconds: int = 30) -> None:
        """
        Args:
            firestore_queue: A `memory.firestore_db.FirestoreQueue` instance.
            poll_interval_seconds: Seconds to sleep between Firestore polls.
        """
        self.queue = firestore_queue
        self.poll_interval_seconds = poll_interval_seconds

    def run_forever(self) -> None:
        """Block indefinitely, draining pending tasks into Things 3 each tick."""
        logger.info("Things poller starting (poll_interval=%ds)", self.poll_interval_seconds)
        while True:
            try:
                pending = self.queue.fetch_pending(limit=25)
            except GoogleAPICallError as exc:
                # WHY: transient Firestore outage must not kill the long-running daemon.
                logger.error("fetch_pending failed, will retry next tick: %s", exc)
                time.sleep(self.poll_interval_seconds)
                continue

            for task in pending:
                doc_id = task.get("doc_id")

                # WHY claim before inject: AppleScript may fail (exit code 1, timeout)
                # AFTER Things 3 has already accepted the to-do. Without this claim step
                # the doc stays "pending" and gets re-injected every 30s, creating
                # infinite duplicates. Claiming first means a failed injection leaves the
                # doc "in_flight" — excluded from fetch_pending — so it never re-runs
                # automatically. To retry, manually reset status to "pending" in Firestore.
                try:
                    self.queue.mark_in_flight(doc_id)
                except GoogleAPICallError as exc:
                    logger.error(
                        "mark_in_flight failed for doc_id=%r — skipping this tick: %s",
                        doc_id, exc,
                    )
                    continue

                try:
                    self.inject_into_things(task)
                except (subprocess.CalledProcessError,
                        subprocess.TimeoutExpired,
                        FileNotFoundError) as exc:
                    logger.error(
                        "AppleScript injection failed for doc_id=%r title=%r — "
                        "doc left in 'in_flight' (will NOT auto-retry; inspect/reset manually): %s",
                        doc_id, task.get("title"), exc,
                    )
                    continue

                try:
                    self.queue.mark_consumed(doc_id)
                    logger.info("Injected & consumed doc_id=%r title=%r", doc_id, task.get("title"))
                except GoogleAPICallError as exc:
                    # Doc is in_flight; Things 3 has the task. No duplicate risk on restart
                    # because in_flight is excluded from fetch_pending.
                    logger.error(
                        "Injected doc_id=%r into Things 3 but mark_consumed failed — "
                        "doc stuck in 'in_flight' (no duplicate risk; reconcile manually): %s",
                        doc_id, exc,
                    )

            # Push Things 3 snapshot to Firestore for the morning briefing.
            push_things_snapshot(self.queue)

            time.sleep(self.poll_interval_seconds)

    def inject_into_things(self, task: dict) -> None:
        """Execute the AppleScript that creates a Things 3 to-do.

        Args:
            task: Dict from FirestoreQueue.fetch_pending, containing at minimum
                  "title" and optionally "notes", "deadline", "tags".

        Raises:
            subprocess.CalledProcessError: If osascript exits non-zero.
            subprocess.TimeoutExpired: If Things 3 is unresponsive for APPLESCRIPT_TIMEOUT_SECONDS.
            FileNotFoundError: If osascript is not found (non-macOS host).
        """
        script = self._build_applescript(task)
        # WHY capture_output=True: prevents osascript chatter from polluting daemon logs.
        # We only surface stderr on failure via the CalledProcessError exception.
        result = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            timeout=APPLESCRIPT_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        logger.debug("osascript stdout: %s", result.stdout.strip())

    def _build_applescript(self, task: dict) -> str:
        """Build the AppleScript string to create one Things 3 to-do.

        Args:
            task: Task dict with keys title, notes, deadline, reminder, tags.

        Returns:
            A complete AppleScript string ready for `osascript -e`.
        """
        title = _escape_applescript(task.get("title") or "untitled")
        notes = task.get("notes") or ""
        tags: list[str] = task.get("tags") or []
        deadline: str | None = task.get("deadline")
        reminder: str | None = task.get("reminder")

        # Build the property list piecewise so optional fields don't introduce
        # empty-string values (Things 3 accepts them, but it looks cleaner without).
        props = [f'name:"{title}"']

        if notes:
            props.append(f'notes:"{_escape_applescript(notes)}"')

        if tags:
            # WHY braces: AppleScript list literal uses curly braces, not brackets.
            tag_list = ", ".join(f'"{_escape_applescript(t)}"' for t in tags)
            props.append(f"tag names:{{{tag_list}}}")

        if deadline:
            # WHY DD/MM/YYYY: AppleScript `date` coercion is locale-sensitive.
            # On Israeli locale (en_IL) the expected format is DD/MM/YYYY;
            # passing YYYY-MM-DD silently parses to a wrong date (e.g. 2026-05-20
            # becomes Nov 16, 2025).
            props.append(f'due date:(date "{_iso_to_applescript_date(deadline)}")')

        properties = "{" + ", ".join(props) + "}"

        if reminder:
            # WHY `schedule` verb instead of `activation date` property:
            # Things 3's sdef declares `activation date` as access="r" (read-only).
            # Setting it in `make new to do with properties` raises AppleEvent error
            # -10000. The `schedule` verb is the correct API; it sets the day the
            # task appears in Today. Note: Things 3's `schedule` accepts a date only
            # (time component is ignored); minute-precise reminders require the
            # Things URL scheme and are not supported via AppleScript.
            activation_date = _iso_to_applescript_date(reminder)
            return (
                'tell application "Things3"\n'
                f'    set t to make new to do with properties {properties}\n'
                f'    schedule t for date "{activation_date}"\n'
                'end tell'
            )

        return (
            'tell application "Things3"\n'
            f'    make new to do with properties {properties}\n'
            'end tell'
        )


def _smoke_test() -> int:
    """Drain pending queue tasks into Things 3 (--once) or run forever as a daemon.

    Run with:
        python -m local_mac.things_poller --once    # drain once, exit
        python -m local_mac.things_poller           # long-running daemon
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # WHY override=True: shell-exported vars silently shadow .env without this.
    load_dotenv(override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.error("GCP_PROJECT_ID is not set — check your .env file")
        return 1

    collection = os.getenv("FIRESTORE_COLLECTION_THINGS_QUEUE", "things_queue")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    poll_interval = int(os.getenv("THINGS_POLLER_INTERVAL_SECONDS", "30"))

    # Import here (not at module top) to keep the modularity boundary clear:
    # this file may be copied to the Mac without the full cloud-side codebase,
    # but memory.firestore_db IS required and must be on sys.path.
    from memory.firestore_db import FirestoreQueue
    firestore_queue = FirestoreQueue(
        project_id=project_id, collection=collection, database=database,
    )
    poller = ThingsPoller(firestore_queue=firestore_queue, poll_interval_seconds=poll_interval)

    if "--once" in sys.argv:
        logger.info("--once mode: draining pending tasks and exiting.")
        try:
            pending = poller.queue.fetch_pending(limit=25)
        except GoogleAPICallError as exc:
            logger.error("fetch_pending failed: %s", exc)
            return 1

        if not pending:
            logger.info("No pending tasks found.")
            return 0

        for task in pending:
            doc_id = task.get("doc_id")
            try:
                poller.queue.mark_in_flight(doc_id)
            except GoogleAPICallError as exc:
                logger.error("mark_in_flight failed for doc_id=%r — skipping: %s", doc_id, exc)
                continue
            try:
                poller.inject_into_things(task)
            except (subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    FileNotFoundError) as exc:
                logger.error(
                    "Failed to inject doc_id=%r — doc left in 'in_flight': %s", doc_id, exc,
                )
                continue
            try:
                poller.queue.mark_consumed(doc_id)
                logger.info("Injected & consumed doc_id=%r title=%r", doc_id, task.get("title"))
            except GoogleAPICallError as exc:
                logger.error("Failed to mark_consumed doc_id=%r: %s", doc_id, exc)
        return 0

    poller.run_forever()
    return 0  # unreachable, but satisfies the type checker


if __name__ == "__main__":
    sys.exit(_smoke_test())
