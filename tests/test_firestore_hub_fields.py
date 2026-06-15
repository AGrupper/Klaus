"""Tests for Phase 26 hub backend field additions to Firestore stores.

WHY this module exists: Phase 26 (v5.0 Klaus Hub) adds two fields to
UserProfileStore._SCAFFOLD (session_version, telegram_user_id) so the hub
auth layer can implement sign-out-everywhere (D-02) and bridge hub Google
identity to the Firestore conversation key (RESEARCH Open Question 2). It
also tests that SelfStateStore.set() can accept daily_note and
daily_note_date keys (TIME-07 coach note source).

Pattern: mock Firestore client/doc-ref so these tests run without real GCP
credentials. Mirrors test_firestore_db.py/_install_firestore_mock() pattern.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------ #
# Firestore mock installation                                        #
# ------------------------------------------------------------------ #

def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore and related stubs into sys.modules.

    Mirrors the pattern from tests/test_firestore_db.py so memory.firestore_db
    imports cleanly without real GCP credentials or installed SDK.
    Returns the firestore mock for assertions.
    """
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        if "google" not in sys.modules or isinstance(sys.modules["google"], MagicMock):
            google_mod = ModuleType("google")
            google_mod.__path__ = []
            sys.modules["google"] = google_mod
        else:
            google_mod = sys.modules["google"]

        if "google.cloud" not in sys.modules or isinstance(sys.modules["google.cloud"], MagicMock):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()
    firestore_mock.SERVER_TIMESTAMP = object()

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    # Also stub google.api_core.exceptions so the import guard in firestore_db.py works.
    exc_mod = ModuleType("google.api_core.exceptions")
    exc_mod.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})  # type: ignore[attr-defined]
    sys.modules["google.api_core"] = ModuleType("google.api_core")
    sys.modules["google.api_core.exceptions"] = exc_mod

    return firestore_mock


def _flush_firestore_db_module() -> None:
    """Remove cached memory.firestore_db from sys.modules so next import picks up stubs."""
    for key in list(sys.modules.keys()):
        if key == "memory.firestore_db" or key.startswith("memory.firestore_db."):
            del sys.modules[key]


# ------------------------------------------------------------------ #
# Task 1 — UserProfileStore scaffold fields                          #
# ------------------------------------------------------------------ #

class TestUserProfileScaffold:
    """Assert that the UserProfileStore._SCAFFOLD carries the new hub fields."""

    def test_userprofile_scaffold_has_session_version(self, isolated_modules):
        """session_version must default to 0 in the scaffold.

        Used by /api/auth/revoke-all (D-02) to invalidate all existing
        session cookies by bumping this counter.
        """
        _install_firestore_mock()
        _flush_firestore_db_module()

        from memory.firestore_db import UserProfileStore  # noqa: PLC0415
        scaffold = UserProfileStore._SCAFFOLD
        assert "session_version" in scaffold, (
            "UserProfileStore._SCAFFOLD must contain 'session_version' for D-02 "
            "sign-out-everywhere support"
        )
        assert scaffold["session_version"] == 0, (
            "session_version must default to 0 (int) — bumped by revoke-all"
        )

    def test_userprofile_scaffold_has_telegram_user_id(self, isolated_modules):
        """telegram_user_id must default to None in the scaffold.

        The hub keys FirestoreConversationStore on this field to bridge the
        hub's Google identity (email) to the Telegram user_id conversation key
        (RESEARCH Open Question 2).
        """
        _install_firestore_mock()
        _flush_firestore_db_module()

        from memory.firestore_db import UserProfileStore  # noqa: PLC0415
        scaffold = UserProfileStore._SCAFFOLD
        assert "telegram_user_id" in scaffold, (
            "UserProfileStore._SCAFFOLD must contain 'telegram_user_id' to bridge "
            "hub Google identity to Firestore conversation key"
        )
        assert scaffold["telegram_user_id"] is None, (
            "telegram_user_id must default to None — populated once via admin/setup"
        )


# ------------------------------------------------------------------ #
# Task 1 — SelfStateStore accepts daily_note                         #
# ------------------------------------------------------------------ #

class TestSelfStateSetAcceptsDailyNote:
    """Assert SelfStateStore.set() can write daily_note + daily_note_date.

    These two fields are the TIME-07 coach note source: written by
    core/morning_briefing.py after compose; read by /api/today.
    SelfStateStore.set() already merges arbitrary patch dicts — the test
    confirms the keys are forwarded to the underlying doc.set() call.
    """

    def test_selfstate_set_accepts_daily_note(self, isolated_modules):
        """set({"daily_note": ..., "daily_note_date": ...}) must call doc.set
        with both keys merged in (alongside updated_at SERVER_TIMESTAMP).
        """
        _install_firestore_mock()
        _flush_firestore_db_module()

        from memory.firestore_db import SelfStateStore  # noqa: PLC0415

        # Build a SelfStateStore with a mocked Firestore client.
        fake_client = MagicMock(name="firestore_client")
        fake_doc_ref = MagicMock(name="doc_ref")
        fake_col = MagicMock(name="collection")
        fake_client.collection.return_value = fake_col
        fake_col.document.return_value = fake_doc_ref

        with patch(
            "memory.firestore_db._make_firestore_client",
            return_value=fake_client,
        ):
            store = SelfStateStore(
                project_id="test-project",
                database="(default)",
            )

        patch_dict = {
            "daily_note": "Rest well — HRV low, easy run today.",
            "daily_note_date": "2026-06-13",
        }
        store.set(patch_dict)

        # doc_ref.set() must have been called with the patch keys + SERVER_TIMESTAMP.
        fake_doc_ref.set.assert_called_once()
        call_args = fake_doc_ref.set.call_args
        written_dict = call_args[0][0]  # positional first arg
        assert written_dict["daily_note"] == "Rest well — HRV low, easy run today."
        assert written_dict["daily_note_date"] == "2026-06-13"
        assert "updated_at" in written_dict, (
            "SelfStateStore.set() must always merge updated_at SERVER_TIMESTAMP"
        )
        # merge=True must be passed (not a full overwrite)
        kwargs = call_args[1] if call_args[1] else {}
        assert kwargs.get("merge") is True, (
            "SelfStateStore.set() must use merge=True to avoid clobbering "
            "other self_state fields"
        )
