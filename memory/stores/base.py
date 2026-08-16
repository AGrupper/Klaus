"""Shared plumbing every store depends on: the client factory, the
process-local read cache, JSON-safe document conversion, and the
server-side filter helper.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

from google.cloud import firestore

logger = logging.getLogger(__name__)


def _where(query, field: str, op: str, value):
    """Apply a server-side filter to a collection/query.

    Prefers the keyword ``filter=FieldFilter(...)`` form (the positional
    ``where(field, op, value)`` form is deprecated in google-cloud-firestore),
    falling back to positional if the FieldFilter import is unavailable.

    WHY server-side: the read paths previously streamed entire collections
    and filtered in Python — O(lifetime docs) billed reads per call. A range
    filter + order_by on the same single field uses Firestore's automatic
    indexes (no composite index needed).
    """
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        return query.where(filter=FieldFilter(field, op, value))
    except ImportError:
        return query.where(field, op, value)


# Sort-direction constant for order_by. The client library's
# firestore.Query.DESCENDING is literally this string; using the literal keeps
# the query builders independent of the (test-mocked) firestore module object.
_DESCENDING = "DESCENDING"


_READ_CACHE: dict[tuple, tuple[float, object]] = {}


_READ_CACHE_TTL_SEC = 600  # 10 minutes


def _cache_get(key: tuple):
    """Return the cached value for key, or None if absent/expired."""
    import time
    hit = _READ_CACHE.get(key)
    if hit is None:
        return None
    stored_at, value = hit
    if time.monotonic() - stored_at > _READ_CACHE_TTL_SEC:
        _READ_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value) -> None:
    import time
    _READ_CACHE[key] = (time.monotonic(), value)


def _cache_invalidate_prefix(prefix: tuple) -> None:
    """Drop every cache entry whose key starts with prefix."""
    for key in [k for k in _READ_CACHE if k[: len(prefix)] == prefix]:
        _READ_CACHE.pop(key, None)


def _make_firestore_client(project_id: str, database: str) -> firestore.Client:
    """Return an authenticated Firestore client.

    Uses a service-account key file when FIRESTORE_CREDENTIALS is set;
    falls back to gcloud application-default credentials otherwise.
    """
    credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/datastore"],
        )
        return firestore.Client(
            project=project_id, credentials=credentials, database=database
        )
    return firestore.Client(project=project_id, database=database)


def record_cron_run(job_id: str, ok: bool, *, backlog_done: bool | None = None) -> None:
    """Write a liveness ledger entry to heartbeat_runs/{job_id}.

    Called once per cron-endpoint invocation. On success, consecutive_failures
    is reset to 0; on failure it is incremented. Never raises.

    Args:
        job_id:       Stable identifier for the cron job (e.g. "ingest-chats").
        ok:           True if the endpoint succeeded, False on exception.
        backlog_done: For batch-processing pipelines: True when the backlog is
                      fully drained (no remaining work), False when items were
                      processed but more remain. None for non-batch crons.
                      When True, the heartbeat suppresses staleness alerts — the
                      pipeline has nothing to do and doesn't need to run again
                      until new work appears.
    """
    try:
        from datetime import datetime, timezone
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        payload = {
            "job_id": job_id,
            "last_run_at": datetime.now(timezone.utc),
            "last_ok": ok,
        }
        if ok:
            payload["consecutive_failures"] = 0
            payload["last_ok_at"] = datetime.now(timezone.utc)
        else:
            payload["consecutive_failures"] = firestore.Increment(1)
        if backlog_done is not None:
            payload["backlog_done"] = backlog_done
        client.collection("heartbeat_runs").document(job_id).set(payload, merge=True)
    except Exception:
        logger.warning("record_cron_run(%s, ok=%s) failed", job_id, ok, exc_info=True)


def _jsonsafe_doc(d: dict) -> dict:
    """Return a copy of a Firestore doc dict with non-JSON-serialisable values
    coerced to strings, so the result round-trips through ``json.dumps``.

    ``log_session`` stamps ``updated_at`` with ``firestore.SERVER_TIMESTAMP``,
    which reads back as a ``DatetimeWithNanoseconds`` — ``json.dumps`` raises on
    it. ``get_training_history`` json-encodes its result, so the timestamp is
    converted to ISO-8601 here (any other datetime-like value is handled too).
    """
    return {k: _jsonsafe_value(v) for k, v in d.items()}


def _jsonsafe_value(v):
    """Coerce a single value to a JSON-serialisable form, recursing into nested
    dicts and lists. The v4.0 user profile (Phase 21) nests dicts/lists several
    levels deep, so a shallow top-level pass would miss a datetime buried inside
    ``weekly_split`` or ``fueling_timeline`` (WR-21-03).
    """
    if isinstance(v, dict):
        return {k: _jsonsafe_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonsafe_value(x) for x in v]
    # psycopg2 returns Postgres NUMERIC/DECIMAL columns as Decimal, which
    # json.dumps cannot serialize (the /api/health/sleep 500). Coerce to float
    # here too, so any Postgres-backed payload that routes through this helper
    # is safe even if a reader forgets to coerce at the source.
    if isinstance(v, Decimal):
        return float(v)
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return str(v)
    return v
