"""Outside-in tests for the one-off Claude nightly incident repair."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest


REVIEW_PATH = "nightly_reviews/2026-08-09"
JOURNAL_PATH = "journal/2026-08-09"
SELF_STATE_PATH = "config/self_state"
RUN_PATH = "routine_runs/a485e1a9914893c100eb2dce1d25b53e"
CORRELATION_ID = "a485e1a9914893c100eb2dce1d25b53e"


class FakeSnapshot:
    """Minimal Firestore snapshot backed by a fake document dictionary."""

    def __init__(self, data: dict | None) -> None:
        self._data = deepcopy(data) if data is not None else None
        self.exists = data is not None

    def to_dict(self) -> dict:
        """Return the stored document data as Firestore would."""
        return deepcopy(self._data) if self._data is not None else {}


class FakeDocumentReference:
    """Firestore document reference operating on one fake path."""

    def __init__(self, client: "FakeFirestoreClient", path: str) -> None:
        self._client = client
        self.path = path

    def get(self) -> FakeSnapshot:
        """Read this document without changing the fake client."""
        self._client.read_paths.append(self.path)
        return FakeSnapshot(self._client.docs.get(self.path))


class FakeBatch:
    """Collect writes until a single simulated atomic commit."""

    def __init__(self, client: "FakeFirestoreClient") -> None:
        self._client = client
        self._operations: list[tuple[str, FakeDocumentReference, dict | None, bool]] = []

    def set(self, reference: FakeDocumentReference, data: dict, *, merge: bool = False) -> None:
        """Queue a Firestore set operation."""
        self._operations.append(("set", reference, deepcopy(data), merge))

    def delete(self, reference: FakeDocumentReference) -> None:
        """Queue a Firestore delete operation."""
        self._operations.append(("delete", reference, None, False))

    def update(self, reference: FakeDocumentReference, data: dict) -> None:
        """Queue the self-state update used by this repair."""
        self._operations.append(("update", reference, deepcopy(data), False))

    def commit(self) -> None:
        """Apply all queued operations together, after all validation has passed."""
        self._client.commit_calls += 1
        staged = deepcopy(self._client.docs)
        for operation, reference, data, merge in self._operations:
            if operation == "delete":
                staged.pop(reference.path, None)
            elif operation == "set":
                if merge:
                    staged.setdefault(reference.path, {}).update(data or {})
                else:
                    staged[reference.path] = data or {}
            else:
                current = staged[reference.path]
                for field in ("source", "reflection_date", "proposed_mood"):
                    if field in (data or {}):
                        current.pop(field, None)
                for field, value in (data or {}).items():
                    if field not in {"source", "reflection_date", "proposed_mood"}:
                        current[field] = value
        self._client.docs = staged


class FakeFirestoreClient:
    """Small Firestore-compatible fake that records reads and atomic commits."""

    def __init__(self, docs: dict[str, dict]) -> None:
        self.docs = deepcopy(docs)
        self.read_paths: list[str] = []
        self.commit_calls = 0
        self.batch_created = 0

    def document(self, path: str) -> FakeDocumentReference:
        """Return a path-addressed fake Firestore document reference."""
        return FakeDocumentReference(self, path)

    def batch(self) -> FakeBatch:
        """Create the sole batch used by an eligible repair."""
        self.batch_created += 1
        return FakeBatch(self)


def incident_documents() -> dict[str, dict]:
    """Return hand-checked fixtures of the four observed incident documents."""
    return {
        REVIEW_PATH: {
            "review_id": "nightly:2026-08-09",
            "correlation_id": CORRELATION_ID,
            "routine": "nightly",
            "target_date": "2026-08-09",
            "routine_status": "published_claude",
            "provider": "claude_subscription",
            "review_text": "test text eighteen",
            "structured": {
                "reflection": {"summary": "test reflection", "mood": "steady"},
                "self_state": {"proposed_mood": "steady"},
                "quiet_night": True,
            },
            "action_ids": [],
            "partial_actions": [],
            "published_at": "2026-08-09T20:00:00+00:00",
            "updated_at": "observed-review-update-time",
        },
        JOURNAL_PATH: {
            "summary": "test reflection",
            "mood": "steady",
            "source": "claude_subscription",
            "correlation_id": CORRELATION_ID,
            "date": "2026-08-09",
            "updated_at": "observed-journal-update-time",
        },
        SELF_STATE_PATH: {
            "identity_summary": "Klaus is Amit's personal hybrid agent.",
            "mood": "calm",
            "current_focus": "Monday planning",
            "recent_context": "A legitimate morning briefing ran.",
            "daily_note": "Monday is under control.",
            "daily_note_date": "2026-08-10",
            "source": "claude_subscription",
            "reflection_date": "2026-08-09",
            "proposed_mood": "steady",
        },
        RUN_PATH: {
            "correlation_id": CORRELATION_ID,
            "routine": "nightly",
            "target_date": "2026-08-09",
            "status": "published_claude",
            "review_id": "nightly:2026-08-09",
            "published_at": "2026-08-09T20:00:00+00:00",
        },
    }


def test_repair_replaces_only_known_incident_data_and_preserves_morning_state():
    """Eligible incident data is atomically invalidated without losing later state."""
    from scripts.repair_claude_routine_incident import repair_incident

    client = FakeFirestoreClient(incident_documents())

    result = repair_incident(client, repaired_at="2026-08-10T09:00:00+00:00")

    assert result == {
        "repaired": True,
        "already_repaired": False,
        "documents": ["nightly_review", "journal", "self_state", "routine_run"],
    }
    assert client.read_paths == [REVIEW_PATH, JOURNAL_PATH, SELF_STATE_PATH, RUN_PATH]
    assert client.commit_calls == 1
    assert client.docs[REVIEW_PATH]["review_text"].startswith("Invalidated nightly review")
    assert client.docs[REVIEW_PATH]["correlation_id"] == CORRELATION_ID
    assert client.docs[REVIEW_PATH]["published_at"] == "2026-08-09T20:00:00+00:00"
    assert JOURNAL_PATH not in client.docs
    assert "proposed_mood" not in client.docs[SELF_STATE_PATH]
    assert "source" not in client.docs[SELF_STATE_PATH]
    assert "reflection_date" not in client.docs[SELF_STATE_PATH]
    assert client.docs[SELF_STATE_PATH]["daily_note_date"] == "2026-08-10"
    assert client.docs[SELF_STATE_PATH]["daily_note"] == "Monday is under control."
    assert client.docs[SELF_STATE_PATH]["current_focus"] == "Monday planning"
    assert client.docs[RUN_PATH]["incident_invalidated"] is True
    assert client.docs[RUN_PATH]["status"] == "published_claude"


def test_repair_aborts_before_creating_a_batch_when_correlation_id_differs():
    """A document from another run cannot be swept into this repair."""
    from scripts.repair_claude_routine_incident import repair_incident

    documents = incident_documents()
    documents[REVIEW_PATH]["correlation_id"] = "different-correlation-id"
    client = FakeFirestoreClient(documents)

    with pytest.raises(ValueError, match="precondition"):
        repair_incident(client, repaired_at="2026-08-10T09:00:00+00:00")

    assert client.batch_created == 0
    assert client.commit_calls == 0
    assert client.docs == documents


def test_repair_aborts_before_creating_a_batch_when_placeholder_changed():
    """A changed placeholder might be authoritative and must remain untouched."""
    from scripts.repair_claude_routine_incident import repair_incident

    documents = incident_documents()
    documents[REVIEW_PATH]["review_text"] = "A potentially authoritative review."
    client = FakeFirestoreClient(documents)

    with pytest.raises(ValueError, match="precondition"):
        repair_incident(client, repaired_at="2026-08-10T09:00:00+00:00")

    assert client.batch_created == 0
    assert client.commit_calls == 0
    assert client.docs == documents


def test_repair_is_idempotent_after_a_completed_invalidation():
    """A rerun reports its safe terminal state without a second commit."""
    from scripts.repair_claude_routine_incident import repair_incident

    client = FakeFirestoreClient(incident_documents())
    repair_incident(client, repaired_at="2026-08-10T09:00:00+00:00")

    result = repair_incident(client, repaired_at="2026-08-10T10:00:00+00:00")

    assert result == {
        "repaired": False,
        "already_repaired": True,
        "documents": ["nightly_review", "journal", "self_state", "routine_run"],
    }
    assert client.commit_calls == 1


def test_dry_run_inspects_and_redacts_known_placeholder_without_creating_batch():
    """Dry-run validates eligibility while keeping placeholder content out of output."""
    from scripts.repair_claude_routine_incident import inspect_incident

    client = FakeFirestoreClient(incident_documents())

    result = inspect_incident(client)

    assert result == {
        "eligible": True,
        "already_repaired": False,
        "documents": ["nightly_review", "journal", "self_state", "routine_run"],
    }
    assert client.batch_created == 0
    assert client.commit_calls == 0
    assert "test text eighteen" not in repr(result)


def test_cli_defaults_to_the_read_only_repair_inspection(monkeypatch, capsys):
    """Omitting --apply cannot create a batch or commit an incident repair."""
    import sys
    from scripts import repair_claude_routine_incident as repair

    client = FakeFirestoreClient(incident_documents())
    monkeypatch.setattr(repair, "_client", lambda: client)
    monkeypatch.setattr(sys, "argv", ["repair_claude_routine_incident.py"])

    assert repair.main() == 0

    assert json.loads(capsys.readouterr().out) == {
        "already_repaired": False,
        "documents": ["nightly_review", "journal", "self_state", "routine_run"],
        "dry_run": True,
        "eligible": True,
    }
    assert client.batch_created == 0
    assert client.commit_calls == 0
