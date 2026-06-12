"""In-memory fakes for Firestore collection/query objects.

The store read paths moved from "stream the whole collection, filter in
Python" to server-side ``where(...).order_by(...).limit(...)`` queries. A bare
MagicMock would silently pass every doc through those calls, so filtering
assertions would stop testing anything. ``FakeCollection`` implements the
query surface the stores use (where / order_by / limit / stream) over an
in-memory list of snapshot mocks, keeping the behavioural coverage real.

Usage:
    snap = make_snap("2026-06-01_evt", {"date": "2026-06-01", "slot": "evt"})
    store._col = FakeCollection([snap])
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


class FakeFieldFilter:
    """Stand-in for google.cloud.firestore_v1.base_query.FieldFilter.

    Same attribute names as the real class so FakeQuery reads them uniformly.
    """

    def __init__(self, field_path, op_string, value=None):
        self.field_path = field_path
        self.op_string = op_string
        self.value = value

    def __repr__(self):
        return f"FieldFilter({self.field_path!r}, {self.op_string!r}, {self.value!r})"


def install_fake_base_query() -> None:
    """Pin ``google.cloud.firestore_v1.base_query`` to a fake module whose
    FieldFilter actually captures (field, op, value).

    WHY: several test files stub that module slot with a bare MagicMock and the
    slot can be left poisoned for the session (a MagicMock ``FieldFilter(...)``
    returns one shared instance whose attributes are MagicMocks, so every
    server-side filter silently matches nothing). Calling this inside an
    isolated_modules-guarded installer makes the store tests order-immune;
    the fixture restores both sys.modules keys on teardown.
    """
    base_query_mod = ModuleType("google.cloud.firestore_v1.base_query")
    base_query_mod.FieldFilter = FakeFieldFilter  # type: ignore[attr-defined]
    fv1 = ModuleType("google.cloud.firestore_v1")
    fv1.__path__ = []  # type: ignore[attr-defined]
    fv1.base_query = base_query_mod  # type: ignore[attr-defined]
    sys.modules["google.cloud.firestore_v1"] = fv1
    sys.modules["google.cloud.firestore_v1.base_query"] = base_query_mod


def make_snap(doc_id: str, data: dict) -> MagicMock:
    """Build a Firestore document-snapshot mock."""
    snap = MagicMock(name=f"snap-{doc_id}")
    snap.id = doc_id
    snap.exists = True
    snap.to_dict.return_value = data
    return snap


def _filter_triple(args: tuple, kwargs: dict) -> tuple[str, str, object]:
    """Normalise where(...) arguments to (field, op, value).

    Supports both the keyword ``filter=FieldFilter(...)`` form the stores use
    in production and the positional fallback form.
    """
    if "filter" in kwargs:
        f = kwargs["filter"]
        # Real FieldFilter uses field_path/op_string; the fake one installed
        # by tests/test_firestore_db.py uses field/op. Accept both.
        field = getattr(f, "field_path", None) or getattr(f, "field")
        op = getattr(f, "op_string", None) or getattr(f, "op")
        return field, op, f.value
    field, op, value = args
    return field, op, value


class FakeQuery:
    """Chainable query over a snapshot list, mimicking Firestore semantics."""

    def __init__(self, snaps: list, filters=(), order=None, limit_n=None):
        self._snaps = snaps
        self._filters = tuple(filters)
        self._order = order  # (field, descending) or None
        self._limit = limit_n

    # ---- chainable builders ---- #

    def where(self, *args, **kwargs) -> "FakeQuery":
        triple = _filter_triple(args, kwargs)
        return FakeQuery(self._snaps, self._filters + (triple,), self._order, self._limit)

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FakeQuery":
        descending = str(direction).upper() == "DESCENDING"
        return FakeQuery(self._snaps, self._filters, (field, descending), self._limit)

    def limit(self, n: int) -> "FakeQuery":
        return FakeQuery(self._snaps, self._filters, self._order, n)

    # ---- execution ---- #

    @staticmethod
    def _field_value(snap, field: str):
        if field == "__name__":
            return snap.id
        return (snap.to_dict() or {}).get(field)

    def stream(self):
        result = []
        for snap in self._snaps:
            keep = True
            for field, op, value in self._filters:
                actual = self._field_value(snap, field)
                if actual is None:
                    # Firestore excludes docs missing the filtered field.
                    keep = False
                    break
                if op == "==":
                    keep = actual == value
                elif op == ">=":
                    keep = actual >= value
                elif op == "<=":
                    keep = actual <= value
                elif op == ">":
                    keep = actual > value
                elif op == "<":
                    keep = actual < value
                else:
                    raise NotImplementedError(f"FakeQuery op {op!r}")
                if not keep:
                    break
            if keep:
                result.append(snap)
        if self._order is not None:
            field, descending = self._order
            result.sort(key=lambda s: self._field_value(s, field), reverse=descending)
        if self._limit is not None:
            result = result[: self._limit]
        return iter(result)


class FakeCollection(FakeQuery):
    """A FakeQuery that also exposes ``document()`` like a CollectionReference.

    ``document()`` returns per-doc MagicMocks (memoised by id) so write-path
    tests can keep asserting on ``.set`` / ``.delete`` calls.

    ``subcollections`` maps doc_id -> {subcollection_name: FakeCollection} so
    read paths like ``col.document(date).collection("ticks").stream()``
    (TickLogStore) return real fake data instead of a bare MagicMock. Docs
    absent from the map get an empty FakeCollection for any subcollection
    name — mirroring Firestore, where missing docs have empty subcollections.
    """

    def __init__(self, snaps: list,
                 subcollections: dict[str, dict[str, "FakeCollection"]] | None = None):
        super().__init__(snaps)
        self._docs: dict[str, MagicMock] = {}
        self._subcollections = subcollections or {}

    def document(self, doc_id: str) -> MagicMock:
        if doc_id not in self._docs:
            doc = MagicMock(name=f"docref-{doc_id}")
            subs = self._subcollections.get(doc_id, {})
            doc.collection.side_effect = (
                lambda name, _subs=subs: _subs.get(name, FakeCollection([]))
            )
            self._docs[doc_id] = doc
        return self._docs[doc_id]


class FailingCollection(FakeCollection):
    """A FakeCollection whose stream() raises — for never-raise contract tests."""

    def __init__(self, exc: Exception):
        super().__init__([])
        self._exc = exc

    def where(self, *args, **kwargs) -> "FailingCollection":
        return self

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FailingCollection":
        return self

    def limit(self, n: int) -> "FailingCollection":
        return self

    def stream(self):
        raise self._exc
