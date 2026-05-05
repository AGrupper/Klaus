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
APPLESCRIPT_TIMEOUT_SECONDS = 15


def _escape_applescript(value: str) -> str:
    """Escape backslashes and double quotes for safe embedding in AppleScript strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
                # Sleep and retry; fetch_pending also swallows errors and returns [],
                # but mark_consumed re-raises so we guard here too.
                logger.error("fetch_pending failed, will retry next tick: %s", exc)
                time.sleep(self.poll_interval_seconds)
                continue

            for task in pending:
                doc_id = task.get("doc_id")
                try:
                    self.inject_into_things(task)
                except (subprocess.CalledProcessError,
                        subprocess.TimeoutExpired,
                        FileNotFoundError) as exc:
                    # WHY do NOT mark consumed: leave the doc pending so it retries
                    # on the next poll. The user can investigate and re-run.
                    logger.error(
                        "AppleScript injection failed for doc_id=%r title=%r: %s",
                        doc_id, task.get("title"), exc,
                    )
                    continue

                try:
                    self.queue.mark_consumed(doc_id)
                    logger.info("Injected & consumed doc_id=%r title=%r", doc_id, task.get("title"))
                except GoogleAPICallError as exc:
                    # WHY log loudly: the task is already in Things 3 but still shows
                    # "pending" in Firestore, so the next poll will try to inject it again
                    # (duplicate). This is the safer failure mode for a solo-user setup.
                    logger.error(
                        "Injected doc_id=%r into Things 3 but mark_consumed failed — "
                        "may appear as duplicate on next poll: %s",
                        doc_id, exc,
                    )

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
            task: Task dict with keys title, notes, deadline, tags.

        Returns:
            A complete AppleScript string ready for `osascript -e`.
        """
        title = _escape_applescript(task.get("title") or "untitled")
        notes = task.get("notes") or ""
        tags: list[str] = task.get("tags") or []
        deadline: str | None = task.get("deadline")

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
            # WHY `due date:(date "YYYY-MM-DD")`: Things 3's AppleScript dictionary
            # exposes "due date" as the deadline property; the `date` coercion
            # parses ISO dates without time components cleanly on macOS.
            props.append(f'due date:(date "{deadline}")')

        properties = "{" + ", ".join(props) + "}"
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
                poller.inject_into_things(task)
                poller.queue.mark_consumed(doc_id)
                logger.info("Injected & consumed doc_id=%r title=%r", doc_id, task.get("title"))
            except (subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    FileNotFoundError) as exc:
                logger.error("Failed to inject doc_id=%r: %s", doc_id, exc)
            except GoogleAPICallError as exc:
                logger.error("Failed to mark_consumed doc_id=%r: %s", doc_id, exc)
        return 0

    poller.run_forever()
    return 0  # unreachable, but satisfies the type checker


if __name__ == "__main__":
    sys.exit(_smoke_test())
