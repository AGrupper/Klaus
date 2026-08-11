"""Versioned Firestore fake for routine transaction and response-boundary tests."""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone


class StaleTransaction(RuntimeError):
    """Raised when an optimistic transaction commits against an old version."""


class VersionedSnapshot:
    """Immutable snapshot of one fake Firestore document version."""

    def __init__(self, data: dict | None):
        self._data = copy.deepcopy(data)

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict:
        return copy.deepcopy(self._data or {})


class VersionedDocument:
    """Document reference backed by a versioned in-memory client."""

    def __init__(self, client, collection: str, key: str):
        self._client = client
        self._path = (collection, key)

    def get(self, transaction=None):
        if transaction is not None:
            return transaction.read(self)
        return VersionedSnapshot(self._client.read_path(self._path)[0])

    def create(self, data: dict) -> None:
        from google.api_core.exceptions import AlreadyExists

        with self._client.lock:
            if self._path in self._client.documents:
                raise AlreadyExists("document exists")
            self._client.documents[self._path] = (
                self._client.materialize(data),
                1,
            )

    def set(self, data: dict, merge: bool = False) -> None:
        self._client.write_path(self._path, data, merge=merge)


class VersionedCollection:
    """Collection reference producing versioned document references."""

    def __init__(self, client, name: str):
        self._client = client
        self._name = name

    def document(self, key: str) -> VersionedDocument:
        return VersionedDocument(self._client, self._name, key)


class VersionedTransaction:
    """Buffer writes and validate every read version at commit time."""

    def __init__(self, client):
        self._client = client
        self._reads = {}
        self._writes = []
        self._paused = False

    def reset(self) -> None:
        self._reads = {}
        self._writes = []

    def read(self, doc_ref: VersionedDocument) -> VersionedSnapshot:
        data, version = self._client.read_path(doc_ref._path)
        self._reads[doc_ref._path] = version
        if self._client.claim_pause(self) and not self._paused:
            self._paused = True
            self._client.read_barrier.set()
            if not self._client.resume_barrier.wait(timeout=2):
                raise AssertionError("timed out waiting to resume stale transaction")
        return VersionedSnapshot(data)

    def update(self, doc_ref: VersionedDocument, patch: dict) -> None:
        self._writes.append((doc_ref._path, copy.deepcopy(patch), True))

    def set(self, doc_ref: VersionedDocument, data: dict, merge: bool = False) -> None:
        self._writes.append((doc_ref._path, copy.deepcopy(data), merge))

    def commit(self) -> None:
        with self._client.lock:
            for path, read_version in self._reads.items():
                current_version = self._client.documents.get(path, (None, 0))[1]
                if current_version != read_version:
                    self._client.stale_commits += 1
                    raise StaleTransaction(path)
            for path, data, merge in self._writes:
                self._client.write_path_locked(path, data, merge=merge)


class VersionedFirestoreClient:
    """Minimal Firestore client with optimistic conflict/retry instrumentation."""

    def __init__(self, *, server_timestamp=None):
        self.documents = {}
        self.lock = threading.RLock()
        self.server_timestamp = server_timestamp
        self.stale_commits = 0
        self.retries = 0
        self.transaction_attempts = 0
        self.write_history = []
        self.read_barrier = threading.Event()
        self.resume_barrier = threading.Event()
        self._pause_armed = False
        self._pause_owner = None

    def collection(self, name: str) -> VersionedCollection:
        return VersionedCollection(self, name)

    def transaction(self) -> VersionedTransaction:
        return VersionedTransaction(self)

    def arm_next_transaction_read_pause(self) -> None:
        """Pause the next transaction after its first versioned read."""
        self.read_barrier.clear()
        self.resume_barrier.clear()
        self._pause_armed = True
        self._pause_owner = None

    def claim_pause(self, transaction: VersionedTransaction) -> bool:
        with self.lock:
            if self._pause_armed and self._pause_owner is None:
                self._pause_owner = transaction
            return self._pause_owner is transaction

    def read_path(self, path) -> tuple[dict | None, int]:
        with self.lock:
            data, version = self.documents.get(path, (None, 0))
            return copy.deepcopy(data), version

    def write_path(self, path, data: dict, *, merge: bool) -> None:
        with self.lock:
            self.write_path_locked(path, data, merge=merge)

    def write_path_locked(self, path, data: dict, *, merge: bool) -> None:
        current, version = self.documents.get(path, ({}, 0))
        materialized = self.materialize(data)
        stored = {**current, **materialized} if merge else materialized
        self.documents[path] = (stored, version + 1)
        self.write_history.append((path, copy.deepcopy(materialized), merge))

    def materialize(self, value):
        """Resolve SERVER_TIMESTAMP like Firestore before a later read."""
        if self.server_timestamp is not None and value is self.server_timestamp:
            return datetime.now(timezone.utc)
        if isinstance(value, dict):
            return {key: self.materialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.materialize(item) for item in value]
        return copy.deepcopy(value)

    def get_document(self, collection: str, key: str) -> dict | None:
        return self.read_path((collection, key))[0]


def transactional_with_retry(function):
    """Firestore-compatible decorator that retries stale optimistic commits."""

    def wrapped(transaction):
        while True:
            transaction.reset()
            transaction._client.transaction_attempts += 1
            result = function(transaction)
            try:
                transaction.commit()
            except StaleTransaction:
                transaction._client.retries += 1
                continue
            return result

    return wrapped
