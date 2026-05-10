"""Unit tests for RosterStore and AttendanceStore.

All Firestore I/O is mocked via unittest.mock — no live connection required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(doc_id: str, data: dict, exists: bool = True) -> MagicMock:
    snap = MagicMock()
    snap.id = doc_id
    snap.exists = exists
    snap.to_dict.return_value = dict(data) if exists else {}
    return snap


def _patch_client(store_class_path: str):
    """Return a context-manager that patches firestore.Client for a store."""
    return patch(f"{store_class_path}.firestore.Client")


# ---------------------------------------------------------------------------
# RosterStore
# ---------------------------------------------------------------------------

class TestRosterStoreAdd:
    def test_stores_correct_payload(self):
        from memory.firestore_db import RosterStore

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_fs.SERVER_TIMESTAMP = "SERVER_TS"

            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col

            mock_doc_ref = MagicMock()
            mock_doc_ref.id = "abc123"
            mock_col.add.return_value = (None, mock_doc_ref)

            store = RosterStore(project_id="test-proj")
            returned_id = store.add(
                name="Yossi",
                phone_e164="972521234567",
                nickname="Yoss",
                notes="captain",
            )

        assert returned_id == "abc123"
        mock_col.add.assert_called_once()
        payload = mock_col.add.call_args[0][0]
        assert payload["name"] == "Yossi"
        assert payload["phone_e164"] == "972521234567"
        assert payload["nickname"] == "Yoss"
        assert payload["notes"] == "captain"
        assert payload["active"] is True
        assert payload["created_at"] == "SERVER_TS"
        assert payload["updated_at"] == "SERVER_TS"


class TestRosterStoreListActive:
    def test_returns_only_active_docs(self):
        from memory.firestore_db import RosterStore
        from unittest.mock import patch as _patch

        active_snap = _make_snapshot("id1", {"name": "Yossi", "active": True})
        inactive_snap = _make_snapshot("id2", {"name": "Dani", "active": False})

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client

            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col

            mock_query = MagicMock()
            mock_col.where.return_value = mock_query
            # Only active docs are returned by the Firestore where() filter
            mock_query.stream.return_value = iter([active_snap])

            store = RosterStore(project_id="test-proj")
            results = store.list_active()

        assert len(results) == 1
        assert results[0]["name"] == "Yossi"
        assert results[0]["doc_id"] == "id1"

    def test_doc_id_injected(self):
        from memory.firestore_db import RosterStore

        snap = _make_snapshot("xyz", {"name": "Roni", "active": True})

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_query = MagicMock()
            mock_col.where.return_value = mock_query
            mock_query.stream.return_value = iter([snap])

            store = RosterStore(project_id="test-proj")
            results = store.list_active()

        assert results[0]["doc_id"] == "xyz"


class TestRosterStoreDeactivate:
    def test_sets_active_false(self):
        from memory.firestore_db import RosterStore

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_fs.SERVER_TIMESTAMP = "SERVER_TS"

            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col

            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref

            store = RosterStore(project_id="test-proj")
            store.deactivate("id1")

        mock_doc_ref.update.assert_called_once_with({
            "active": False,
            "updated_at": "SERVER_TS",
        })


class TestRosterStoreGet:
    def test_returns_none_for_missing_doc(self):
        from memory.firestore_db import RosterStore

        missing_snap = _make_snapshot("nope", {}, exists=False)

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref
            mock_doc_ref.get.return_value = missing_snap

            store = RosterStore(project_id="test-proj")
            result = store.get("nope")

        assert result is None

    def test_returns_none_for_inactive_doc(self):
        from memory.firestore_db import RosterStore

        inactive_snap = _make_snapshot("id2", {"name": "Dani", "active": False})

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref
            mock_doc_ref.get.return_value = inactive_snap

            store = RosterStore(project_id="test-proj")
            result = store.get("id2")

        assert result is None

    def test_returns_doc_with_doc_id(self):
        from memory.firestore_db import RosterStore

        snap = _make_snapshot("id3", {"name": "Kobi", "active": True})

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref
            mock_doc_ref.get.return_value = snap

            store = RosterStore(project_id="test-proj")
            result = store.get("id3")

        assert result is not None
        assert result["doc_id"] == "id3"
        assert result["name"] == "Kobi"


# ---------------------------------------------------------------------------
# AttendanceStore
# ---------------------------------------------------------------------------

class TestAttendanceStoreUpsert:
    def test_creates_doc_with_correct_fields(self):
        from memory.firestore_db import AttendanceStore

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref

            store = AttendanceStore(project_id="test-proj")
            store.upsert_practice(
                "2026-05-10",
                practice_datetime="2026-05-10T18:00:00",
                captains_message_sent=False,
            )

        mock_col.document.assert_called_once_with("2026-05-10")
        mock_doc_ref.set.assert_called_once()
        payload, kwargs = mock_doc_ref.set.call_args[0][0], mock_doc_ref.set.call_args[1]
        assert payload["practice_date"] == "2026-05-10"
        assert payload["practice_datetime"] == "2026-05-10T18:00:00"
        assert payload["captains_message_sent"] is False
        assert kwargs.get("merge") is True


class TestAttendanceStoreMarkAttendance:
    def test_rejects_invalid_status(self):
        from memory.firestore_db import AttendanceStore

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_fs.Client.return_value = MagicMock()

            store = AttendanceStore(project_id="test-proj")
            with pytest.raises(ValueError, match="Invalid attendance status"):
                store.mark_attendance("2026-05-10", "roster_id_1", "present")

    def test_updates_nested_attendance_map(self):
        from memory.firestore_db import AttendanceStore

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref

            store = AttendanceStore(project_id="test-proj")
            store.mark_attendance("2026-05-10", "roster_id_1", "came")

        mock_doc_ref.update.assert_called_once_with(
            {"attendance.roster_id_1": "came"}
        )


class TestAttendanceStoreAddPingedPre:
    def test_uses_array_union_for_dedup(self):
        from memory.firestore_db import AttendanceStore

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_fs.ArrayUnion.return_value = "ARRAY_UNION_SENTINEL"

            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_doc_ref = MagicMock()
            mock_col.document.return_value = mock_doc_ref

            store = AttendanceStore(project_id="test-proj")
            store.add_pinged_pre("2026-05-10", ["id1", "id2"])

        mock_fs.ArrayUnion.assert_called_once_with(["id1", "id2"])
        mock_doc_ref.update.assert_called_once_with({
            "pinged_pre_practice": "ARRAY_UNION_SENTINEL",
        })


class TestAttendanceStoreRecentPractices:
    def test_returns_newest_first(self):
        from memory.firestore_db import AttendanceStore

        snaps = [
            _make_snapshot("2026-05-03", {"practice_date": "2026-05-03"}),
            _make_snapshot("2026-05-10", {"practice_date": "2026-05-10"}),
            _make_snapshot("2026-04-26", {"practice_date": "2026-04-26"}),
        ]

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_col.stream.return_value = iter(snaps)

            store = AttendanceStore(project_id="test-proj")
            results = store.recent_practices(n=3)

        dates = [r["practice_date"] for r in results]
        assert dates == ["2026-05-10", "2026-05-03", "2026-04-26"]

    def test_respects_n_limit(self):
        from memory.firestore_db import AttendanceStore

        snaps = [
            _make_snapshot("2026-05-03", {"practice_date": "2026-05-03"}),
            _make_snapshot("2026-05-10", {"practice_date": "2026-05-10"}),
            _make_snapshot("2026-04-26", {"practice_date": "2026-04-26"}),
        ]

        with patch("memory.firestore_db.firestore") as mock_fs:
            mock_client = MagicMock()
            mock_fs.Client.return_value = mock_client
            mock_col = MagicMock()
            mock_client.collection.return_value = mock_col
            mock_col.stream.return_value = iter(snaps)

            store = AttendanceStore(project_id="test-proj")
            results = store.recent_practices(n=2)

        assert len(results) == 2
        assert results[0]["practice_date"] == "2026-05-10"
