"""Safely invalidate the known 2026-08-09 Claude nightly placeholder incident.

This is intentionally a one-off, exact-match repair.  It defaults to a read-only
dry run; production mutation requires an explicit ``--apply`` and is limited to
one Firestore batch spanning the four documented incident records.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make direct ``python scripts/...`` invocation behave like package imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google.cloud import firestore


INCIDENT_DATE = "2026-08-09"
INCIDENT_CORRELATION_ID = "a485e1a9914893c100eb2dce1d25b53e"
INCIDENT_REASON = "schema-probe placeholder published by Claude nightly routine"

REVIEW_PATH = f"nightly_reviews/{INCIDENT_DATE}"
JOURNAL_PATH = f"journal/{INCIDENT_DATE}"
SELF_STATE_PATH = "config/self_state"
RUN_PATH = f"routine_runs/{INCIDENT_CORRELATION_ID}"

PLACEHOLDER_REVIEW_TEXT = "test text eighteen"
PLACEHOLDER_STRUCTURED = {
    "reflection": {"summary": "test reflection", "mood": "steady"},
    "self_state": {"proposed_mood": "steady"},
    "quiet_night": True,
}
PLACEHOLDER_JOURNAL = {
    "summary": "test reflection",
    "mood": "steady",
    "source": "claude_subscription",
    "correlation_id": INCIDENT_CORRELATION_ID,
    "date": INCIDENT_DATE,
}
PLACEHOLDER_SELF_STATE = {
    "source": "claude_subscription",
    "reflection_date": INCIDENT_DATE,
    "proposed_mood": "steady",
}
INVALIDATED_REVIEW_TEXT = (
    "Invalidated nightly review: this record was not authoritative because a "
    "schema-probe placeholder was published."
)
INVALIDATED_STRUCTURED = {
    "invalidated": True,
    "reason": INCIDENT_REASON,
    "original_placeholder_removed": True,
}
DOCUMENT_NAMES = ["nightly_review", "journal", "self_state", "routine_run"]


def _read_incident_documents(client: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any] | None]]:
    """Read every target document before any repair write can be created."""
    references = {
        "nightly_review": client.document(REVIEW_PATH),
        "journal": client.document(JOURNAL_PATH),
        "self_state": client.document(SELF_STATE_PATH),
        "routine_run": client.document(RUN_PATH),
    }
    documents: dict[str, dict[str, Any] | None] = {}
    for name, reference in references.items():
        snapshot = reference.get()
        documents[name] = snapshot.to_dict() if snapshot.exists else None
    return references, documents


def _is_already_repaired(documents: dict[str, dict[str, Any] | None]) -> bool:
    """Return whether all four records show the completed repair state."""
    review = documents["nightly_review"] or {}
    self_state = documents["self_state"] or {}
    routine_run = documents["routine_run"] or {}
    return (
        documents["journal"] is None
        and review.get("review_text") == INVALIDATED_REVIEW_TEXT
        and review.get("structured") == INVALIDATED_STRUCTURED
        and review.get("invalid_reason") == INCIDENT_REASON
        and bool(review.get("invalidated_at"))
        and "source" not in self_state
        and "reflection_date" not in self_state
        and "proposed_mood" not in self_state
        and bool(self_state.get("incident_repaired_at"))
        and routine_run.get("incident_invalidated") is True
        and routine_run.get("incident_reason") == INCIDENT_REASON
        and bool(routine_run.get("incident_repaired_at"))
    )


def _require_incident_preconditions(documents: dict[str, dict[str, Any] | None]) -> None:
    """Raise before writes unless every observed placeholder value still matches."""
    review = documents["nightly_review"]
    journal = documents["journal"]
    self_state = documents["self_state"]
    routine_run = documents["routine_run"]
    if review is None or journal is None or self_state is None or routine_run is None:
        raise ValueError("incident precondition failed: a target document is missing")
    if (
        review.get("correlation_id") != INCIDENT_CORRELATION_ID
        or review.get("routine") != "nightly"
        or review.get("target_date") != INCIDENT_DATE
        or review.get("review_text") != PLACEHOLDER_REVIEW_TEXT
        or review.get("structured") != PLACEHOLDER_STRUCTURED
    ):
        raise ValueError("incident precondition failed: nightly review differs")
    if any(journal.get(key) != value for key, value in PLACEHOLDER_JOURNAL.items()):
        raise ValueError("incident precondition failed: journal differs")
    if any(self_state.get(key) != value for key, value in PLACEHOLDER_SELF_STATE.items()):
        raise ValueError("incident precondition failed: self-state differs")
    if (
        routine_run.get("correlation_id") != INCIDENT_CORRELATION_ID
        or routine_run.get("routine") != "nightly"
        or routine_run.get("target_date") != INCIDENT_DATE
        or routine_run.get("status") != "published_claude"
        or routine_run.get("review_id") != f"nightly:{INCIDENT_DATE}"
    ):
        raise ValueError("incident precondition failed: routine run differs")


def _summary(*, eligible: bool, already_repaired: bool) -> dict[str, Any]:
    """Build a redacted result that identifies documents but never their content."""
    return {
        "eligible": eligible,
        "already_repaired": already_repaired,
        "documents": list(DOCUMENT_NAMES),
    }


def inspect_incident(client: Any) -> dict[str, Any]:
    """Validate the repair preconditions and return a read-only redacted summary."""
    _, documents = _read_incident_documents(client)
    if _is_already_repaired(documents):
        return _summary(eligible=False, already_repaired=True)
    _require_incident_preconditions(documents)
    return _summary(eligible=True, already_repaired=False)


def repair_incident(client: Any, *, repaired_at: str) -> dict[str, Any]:
    """Atomically invalidate the exact incident records after strict validation.

    Args:
        client: Firestore-compatible client exposing document reads and batches.
        repaired_at: UTC ISO-8601 audit timestamp supplied by the operator.

    Returns:
        A redacted status dictionary; reruns report ``already_repaired``.

    Raises:
        ValueError: If any target is missing, altered, or only partly repaired.
    """
    references, documents = _read_incident_documents(client)
    if _is_already_repaired(documents):
        return {
            "repaired": False,
            "already_repaired": True,
            "documents": list(DOCUMENT_NAMES),
        }
    _require_incident_preconditions(documents)

    # Preconditions are now known for all four documents.  Commit once so no
    # intermediate state can leave a partial repair if the process exits.
    batch = client.batch()
    batch.set(
        references["nightly_review"],
        {
            "review_text": INVALIDATED_REVIEW_TEXT,
            "structured": INVALIDATED_STRUCTURED,
            "invalidated_at": repaired_at,
            "invalid_reason": INCIDENT_REASON,
        },
        merge=True,
    )
    batch.delete(references["journal"])
    batch.update(
        references["self_state"],
        {
            "source": firestore.DELETE_FIELD,
            "reflection_date": firestore.DELETE_FIELD,
            "proposed_mood": firestore.DELETE_FIELD,
            "incident_repaired_at": repaired_at,
        },
    )
    batch.set(
        references["routine_run"],
        {
            "incident_invalidated": True,
            "incident_reason": INCIDENT_REASON,
            "incident_repaired_at": repaired_at,
        },
        merge=True,
    )
    batch.commit()
    return {
        "repaired": True,
        "already_repaired": False,
        "documents": list(DOCUMENT_NAMES),
    }


def _client() -> Any:
    """Create the Firestore client only when the command-line utility is run."""
    load_dotenv(override=True)
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return firestore.Client(project=project_id, database=database)


def main() -> int:
    """Run a redacted dry-run by default or commit only after ``--apply``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the validated repair batch; omit for a read-only dry-run",
    )
    args = parser.parse_args()
    client = _client()
    inspection = inspect_incident(client)
    if not args.apply or inspection["already_repaired"]:
        print(json.dumps({"dry_run": not args.apply, **inspection}, sort_keys=True))
        return 0
    repaired_at = datetime.now(timezone.utc).isoformat()
    result = repair_incident(client, repaired_at=repaired_at)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
