"""Things sync cron — keeps the Firestore mirror of Amit's Things 3 list warm.

Pull-based: Things Cloud exposes no webhooks, and its journal is an append-only
delta log cursored by a server index (see ``docs/things_protocol.md``).

This is a **backstop, not the primary path**.  ``ThingsTaskStore`` checks the head
index on read and pulls a delta itself, so conversational reads are already fresh.
The cron exists so that:

  * a Cloud Run cold start finds a populated mirror instead of replaying the whole
    journal on Amit's first message of the day, and
  * if Things Cloud is unreachable when a briefing fires, the mirror it falls back
    to is hours old rather than days.

The heavy lifting lives in ``ThingsTaskStore._refresh``: cursor handling, delta
application, and mirror persistence.  Duplicating any of that here would risk
reintroducing the pagination bug the store already solves, so this module stays a
thin trigger.

Local dry-run::

    THINGS_EMAIL=... THINGS_PASSWORD=... GCP_PROJECT_ID=... \\
        python -m core.ingest.things
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


def run_one_batch() -> dict:
    """Force a mirror refresh from Things Cloud.

    Never raises — mirrors the ingest-cron contract used by
    ``core/strength_ingest.py`` so ``/cron/*`` handling is uniform.

    Returns:
        ``{"ok": True, "mode": "delta"|"replay", "cursor": int, "entities": int,
        "open_todos": int, "elapsed_ms": int, "done": True}`` on success, or
        ``{"ok": False, "error": str, "done": True}`` on failure.

    ``done`` is always True: a refresh drains to the journal head in one call,
    so unlike the paged Hevy/Garmin ingests there is never a backlog to resume.
    """
    started = time.monotonic()
    try:
        from memory.things_store import ThingsTaskStore, _cache

        cursor_before = _cache.get("cursor", 0)
        was_cold = _cache.get("state") is None

        store = ThingsTaskStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        state = store._refresh(force=True)

        stale = _cache.get("stale_reason")
        if stale:
            logger.warning("things_ingest: refresh degraded: %s", stale)
            return {"ok": False, "error": stale, "done": True}

        result = {
            "ok": True,
            "mode": "replay" if was_cold else "delta",
            "cursor": _cache.get("cursor", 0),
            "advanced": _cache.get("cursor", 0) - cursor_before,
            "entities": len(state),
            "open_todos": len(store.list()),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "done": True,
        }
        logger.info("things_ingest: %s", result)
        return result
    except Exception as exc:                     # noqa: BLE001 — cron must not raise
        logger.warning("things_ingest: sync failed", exc_info=True)
        return {"ok": False, "error": str(exc), "done": True}


if __name__ == "__main__":
    import json

    from dotenv import load_dotenv

    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_one_batch(), indent=2))
