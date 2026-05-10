"""Things 3 cloud queue MCP tool.

Thin agent-facing wrapper over `memory.firestore_db.FirestoreQueue`.
Modularity rule (per `docs/CODING_STANDARDS.md` §5): this file contains
NO Gmail/Calendar logic and NO Things 3 / AppleScript logic — only the
write side of the cloud queue.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)


class ThingsQueueWriter:
    """Agent-facing tool that enqueues a Things 3 to-do for the local poller."""

    def __init__(self, firestore_queue: object) -> None:
        """
        Args:
            firestore_queue: A `memory.firestore_db.FirestoreQueue` instance.
        """
        self.queue = firestore_queue

    def add_todo(self, title: str, notes: str = "", deadline: str | None = None,
                 reminder: str | None = None,
                 tags: list[str] | None = None) -> dict:
        """Push a new to-do onto the cloud queue.

        Args:
            title: Task title shown in Things 3.
            notes: Optional notes body.
            deadline: Optional ISO 8601 date string (YYYY-MM-DD). Sets Things 3 due date.
            reminder: Optional datetime string (YYYY-MM-DDTHH:MM, local time). Sets
                Things 3 'when' / activation date — Things fires a notification at this time.
            tags: Optional list of Things 3 tag names.

        Returns:
            Dict with keys:
              - "queue_doc_id": Firestore document ID on success.
              - "title": Echo of the title.
              - "confirmation": Human-readable success message.
              Or on failure:
              - "error": Description of what went wrong.
              - "title": Echo of the title.
        """
        try:
            doc_id = self.queue.enqueue(
                title=title,
                notes=notes or "",
                deadline=deadline,
                reminder=reminder,
                tags=list(tags) if tags else [],
            )
        except GoogleAPICallError as exc:
            logger.error("ThingsQueueWriter.add_todo failed for title=%r: %s", title, exc)
            return {"error": f"Failed to queue task: {exc}", "title": title}

        return {
            "queue_doc_id": doc_id,
            "title": title,
            "confirmation": (
                f"Task '{title}' queued for Things 3. "
                "The Mac poller will inject it within ~30 seconds "
                "(or after wake if your Mac is asleep)."
            ),
        }


def _smoke_test() -> int:
    """Enqueue a test task via ThingsQueueWriter. Returns 0 on success, 1 on failure.

    Run with:  python -m mcp_tools.things_queue
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # WHY override=True: shell-exported vars silently shadow .env without this.
    load_dotenv(override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.error("GCP_PROJECT_ID is not set — check your .env file")
        return 1

    from memory.firestore_db import FirestoreQueue
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    queue = FirestoreQueue(project_id, database=database)
    writer = ThingsQueueWriter(firestore_queue=queue)

    result = writer.add_todo(
        title="smoke test — things queue writer",
        notes="created by mcp_tools.things_queue._smoke_test",
        tags=["smoke"],
    )
    print(result)
    if "error" in result:
        return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
