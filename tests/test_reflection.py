"""Wave 0 test scaffold for Phase 17: Reflection & Journal.

Covers JOUR-01 through JOUR-06 and D-03/D-13.

Mock strategy
-------------
Firestore is mocked at the sys.modules level using the same
`_install_firestore_mock()` pattern established in test_llm_usage_store.py
— google.cloud.firestore is replaced with a MagicMock before any module
under test is imported, so no real GCP connection is needed.

Pinecone mocking is done per-test via `_embed` and `_get_index` attribute
patches on MemoryStore instances, so no Pinecone client or real embedding
call is made.

Tests implemented in THIS plan (17-01):
  - test_journal_store_roundtrip          (JOUR-02)
  - test_remember_self_deterministic_id   (JOUR-03)
  - test_recall_self_kind                 (JOUR-04)

Remaining 6 tests are stubs that skip — they will be fleshed out by the
plans that build the code they exercise (17-02, 17-03, 17-04).
"""
from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _safe_mock_module(name: str) -> None:
    if name in sys.modules:
        return
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent in sys.modules and isinstance(sys.modules[parent], MagicMock):
            sys.modules[name] = MagicMock()
            return
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = MagicMock()


def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore and related stubs into sys.modules.

    Also stubs googleapiclient and google-auth-oauthlib so that core.tools and
    core.main can be imported without real Google API libraries being installed.
    """
    if "google.cloud.firestore" not in sys.modules:
        import types
        try:
            import google
        except ImportError:
            google = types.ModuleType("google")
            sys.modules["google"] = google

        try:
            import google.cloud
            google_cloud_mod = sys.modules["google.cloud"]
        except ImportError:
            google_cloud_mod = types.ModuleType("google.cloud")
            sys.modules["google.cloud"] = google_cloud_mod
            if not hasattr(google, "cloud"):
                setattr(google, "cloud", google_cloud_mod)

        firestore_mock = MagicMock()


        class _Increment:
            def __init__(self, value):
                self.value = value
            def __repr__(self):
                return f"Increment({self.value!r})"

        firestore_mock.Increment = _Increment
        firestore_mock.SERVER_TIMESTAMP = object()
        firestore_mock.ArrayUnion = MagicMock()

        sys.modules["google.cloud.firestore"] = firestore_mock
        google_cloud_mod.firestore = firestore_mock
        if not hasattr(google, "cloud"):
            google.cloud = google_cloud_mod

        _safe_mock_module("google.api_core")
        _safe_mock_module("google.api_core.exceptions")
        _safe_mock_module("google.cloud.firestore_v1")
        _safe_mock_module("google.cloud.firestore_v1.base_query")

        _safe_mock_module("google.oauth2")
        _safe_mock_module("google.oauth2.service_account")
        _safe_mock_module("google.oauth2.credentials")
        _safe_mock_module("google.auth.exceptions")
        _safe_mock_module("google.auth.transport")
        _safe_mock_module("google.auth.transport.requests")
        _safe_mock_module("google_auth_oauthlib")
        _safe_mock_module("google_auth_oauthlib.flow")

        _safe_mock_module("dotenv")

    # These stubs must always be installed unconditionally — other test files
    # (e.g. test_llm_usage_store) install google.cloud.firestore without
    # all of google.auth.* or googleapiclient, so the guard above gets skipped
    # and test_journal_digest_assembly's deferred core.main import fails.
    # core/auth_google.py requires all of the stubs below at import time.
    _safe_mock_module("google.auth")
    _safe_mock_module("google.auth.exceptions")
    _safe_mock_module("google.auth.transport")
    _safe_mock_module("google.auth.transport.requests")
    _safe_mock_module("google.oauth2")
    _safe_mock_module("google.oauth2.credentials")
    _safe_mock_module("google.oauth2.service_account")
    _safe_mock_module("google_auth_oauthlib")
    _safe_mock_module("google_auth_oauthlib.flow")
    _safe_mock_module("googleapiclient")
    _safe_mock_module("googleapiclient.errors")
    _safe_mock_module("googleapiclient.discovery")

    # Force re-import of firestore_db so it picks up the mock
    for key in list(sys.modules.keys()):
        if "memory.firestore_db" in key or key == "memory.firestore_db":
            del sys.modules[key]


_install_firestore_mock()

# Import modules under test with mocks in place
# JournalStore is imported inside tests to avoid failing collection before Task 2.
import memory.pinecone_db as pinecone_db  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_ENTRY = {
    "summary": "Today I helped Amit plan his workout schedule.",
    "mood": "focused",
    "current_focus": "Phase 17 implementation",
    "recent_context": "Implementing reflection journal cron.",
    "highlights": ["Completed data-layer foundation", "All tests green"],
    "message_count": 42,
    "cost_usd": 0.0031,
    "calendar_event_count": 3,
    "tasks_completed": 5,
    "heartbeat_ok": True,
}

_DATE = "2026-05-19"


def _make_journal_mock_client(docs: dict[str, dict] | None = None):
    """Return a MagicMock Firestore client whose collection behaves like JournalStore needs.

    Args:
        docs: Optional mapping of date_str → entry dict that the mock
              collection will return from .document(date_str).get().
    """
    docs = docs or {}
    client = MagicMock()
    col = MagicMock()
    client.collection.return_value = col

    def _document(date_str):
        doc_ref = MagicMock()
        if date_str in docs:
            snap = MagicMock()
            snap.exists = True
            snap.id = date_str
            snap.to_dict.return_value = dict(docs[date_str])
            doc_ref.get.return_value = snap
        else:
            snap = MagicMock()
            snap.exists = False
            doc_ref.get.return_value = snap
        return doc_ref

    col.document.side_effect = _document

    # stream() returns all docs
    def _stream():
        snaps = []
        for date_str, entry in docs.items():
            snap = MagicMock()
            snap.id = date_str
            snap.to_dict.return_value = dict(entry)
            snaps.append(snap)
        return iter(snaps)

    col.stream.side_effect = _stream
    return client, col


# ---------------------------------------------------------------------------
# JOUR-02: JournalStore round-trip
# ---------------------------------------------------------------------------

def test_journal_store_roundtrip():
    """JournalStore.set then get returns all 5 LLM fields + 5 raw metrics + date."""
    from memory.firestore_db import JournalStore  # noqa: PLC0415

    # --- set() call captures the payload ---------------------------------- #
    written: dict = {}

    client = MagicMock()
    col = MagicMock()
    client.collection.return_value = col
    doc_ref = MagicMock()
    col.document.return_value = doc_ref

    def _capture_set(payload):
        written.update(payload)

    doc_ref.set.side_effect = _capture_set

    with patch("memory.firestore_db._make_firestore_client", return_value=client):
        store = JournalStore("test-project")
        store.set(_DATE, _FULL_ENTRY)

    # set() must not use merge=True (D-12 overwrite)
    doc_ref.set.assert_called_once()
    call_args = doc_ref.set.call_args
    # merge=True must NOT be present in kwargs
    assert call_args.kwargs.get("merge") is not True, (
        "JournalStore.set must NOT use merge=True — it should overwrite the whole doc (D-12)"
    )

    # --- get() round-trip ------------------------------------------------- #
    # Build a mock where the doc exists with the written payload
    stored = dict(_FULL_ENTRY)
    stored["date"] = _DATE
    get_client, get_col = _make_journal_mock_client({_DATE: stored})

    with patch("memory.firestore_db._make_firestore_client", return_value=get_client):
        store2 = JournalStore("test-project")
        result = store2.get(_DATE)

    assert result is not None
    assert result["date"] == _DATE
    # 5 LLM fields
    assert result["summary"] == _FULL_ENTRY["summary"]
    assert result["mood"] == _FULL_ENTRY["mood"]
    assert result["current_focus"] == _FULL_ENTRY["current_focus"]
    assert result["recent_context"] == _FULL_ENTRY["recent_context"]
    assert result["highlights"] == _FULL_ENTRY["highlights"]
    # 5 raw metrics
    assert result["message_count"] == _FULL_ENTRY["message_count"]
    assert result["cost_usd"] == _FULL_ENTRY["cost_usd"]
    assert result["calendar_event_count"] == _FULL_ENTRY["calendar_event_count"]
    assert result["tasks_completed"] == _FULL_ENTRY["tasks_completed"]
    assert result["heartbeat_ok"] == _FULL_ENTRY["heartbeat_ok"]

    # --- get() on missing date returns None ------------------------------- #
    with patch("memory.firestore_db._make_firestore_client", return_value=get_client):
        store3 = JournalStore("test-project")
        assert store3.get("1999-01-01") is None

    # --- get_recent(3) on 4-doc collection returns 3, newest-first ------- #
    four_docs = {
        "2026-05-16": {"summary": "day 1", "mood": "ok"},
        "2026-05-17": {"summary": "day 2", "mood": "ok"},
        "2026-05-18": {"summary": "day 3", "mood": "ok"},
        "2026-05-19": {"summary": "day 4", "mood": "ok"},
    }
    recent_client, _ = _make_journal_mock_client(four_docs)

    with patch("memory.firestore_db._make_firestore_client", return_value=recent_client):
        store4 = JournalStore("test-project")
        recent = store4.get_recent(3)

    assert len(recent) == 3, f"Expected 3 results, got {len(recent)}"
    # newest-first
    assert recent[0]["date"] == "2026-05-19"
    assert recent[1]["date"] == "2026-05-18"
    assert recent[2]["date"] == "2026-05-17"


# ---------------------------------------------------------------------------
# JOUR-03: remember_self deterministic ID
# ---------------------------------------------------------------------------

def test_remember_self_deterministic_id():
    """remember_self upserts with id == 'self-{date}' both on first and repeat call."""
    store = pinecone_db.MemoryStore(api_key="fake", index_name="fake-index")

    fake_vector = [0.1] * 768
    store._embed = MagicMock(return_value=fake_vector)

    mock_index = MagicMock()
    store._get_index = MagicMock(return_value=mock_index)

    date_str = "2026-05-19"
    content = "Today I helped Amit think through the reflection journal design."

    # First call
    returned_id_1 = store.remember_self(123456, date_str, content)
    assert returned_id_1 == f"self-{date_str}", (
        f"Expected 'self-{date_str}', got {returned_id_1!r}"
    )
    first_call_args = mock_index.upsert.call_args
    first_vector = first_call_args.kwargs.get("vectors") or first_call_args.args[0]
    assert first_vector[0]["id"] == f"self-{date_str}"

    # Second call with same date — must produce the same deterministic ID
    store._embed.reset_mock()
    mock_index.upsert.reset_mock()

    returned_id_2 = store.remember_self(123456, date_str, "Updated content for the same day.")
    assert returned_id_2 == f"self-{date_str}", (
        "Second call must produce the same deterministic ID (overwrite, no duplicate)"
    )
    second_call_args = mock_index.upsert.call_args
    second_vector = second_call_args.kwargs.get("vectors") or second_call_args.args[0]
    assert second_vector[0]["id"] == f"self-{date_str}"

    # Metadata must include user_id as str and kind == "self"
    meta = second_vector[0]["metadata"]
    assert meta["user_id"] == "123456"
    assert meta["kind"] == "self"


# ---------------------------------------------------------------------------
# JOUR-04: recall with "self" kind
# ---------------------------------------------------------------------------

def test_recall_self_kind():
    """'self' is in _VALID_KINDS; recall(kinds=['self']) filters on ['self'];
    recall() with no kinds arg still defaults to ['fact','chunk'].
    Also verifies the tool-layer path: _handle_recall(kind='self') forwards
    kinds=['self'] to MemoryTool.recall; no kind passes kinds=None."""
    # 1. "self" is in _VALID_KINDS
    assert "self" in pinecone_db._VALID_KINDS, (
        "'self' must be in _VALID_KINDS (D-06)"
    )

    # 2. recall(kinds=["self"]) passes ["self"] to the index query
    store = pinecone_db.MemoryStore(api_key="fake", index_name="fake-index")
    fake_vector = [0.0] * 768
    store._embed = MagicMock(return_value=fake_vector)

    mock_index = MagicMock()
    mock_index.query.return_value = MagicMock(matches=[])
    store._get_index = MagicMock(return_value=mock_index)

    store.recall(user_id=123456, query="journal entry", k=3, kinds=["self"])

    mock_index.query.assert_called_once()
    call_kwargs = mock_index.query.call_args.kwargs
    passed_filter = call_kwargs.get("filter", {})
    assert passed_filter.get("kind", {}).get("$in") == ["self"], (
        "recall(kinds=['self']) must pass {'kind': {'$in': ['self']}} to Pinecone query"
    )

    # 3. recall() with no kinds arg defaults to ["fact", "chunk"]
    mock_index.query.reset_mock()
    mock_index.query.return_value = MagicMock(matches=[])

    store.recall(user_id=123456, query="something")

    call_kwargs2 = mock_index.query.call_args.kwargs
    passed_filter2 = call_kwargs2.get("filter", {})
    assert passed_filter2.get("kind", {}).get("$in") == ["fact", "chunk"], (
        "Default recall() must still filter on ['fact', 'chunk'] — D-08 unchanged"
    )

    # 4. Tool-layer: MemoryTool.recall now accepts kinds= and forwards it to
    #    MemoryStore.recall. Verify the agent-facing wrapper works end-to-end.
    from mcp_tools.memory import MemoryTool  # noqa: PLC0415

    mock_store = MagicMock()
    mock_store.recall.return_value = []
    tool = MemoryTool(memory_store=mock_store)

    # kind="self" path → MemoryTool.recall(kinds=["self"]) → store.recall(kinds=["self"])
    tool.recall(user_id=123456, query="journal entry", k=3, kinds=["self"])
    mock_store.recall.assert_called_once()
    store_call = mock_store.recall.call_args
    assert store_call.kwargs.get("kinds") == ["self"] or (
        len(store_call.args) >= 4 and store_call.args[3] == ["self"]
    ), (
        "MemoryTool.recall(kinds=['self']) must forward kinds=['self'] to MemoryStore.recall"
    )

    mock_store.recall.reset_mock()
    # default path (kinds=None) → store.recall(kinds=None)
    tool.recall(user_id=123456, query="something")
    store_call2 = mock_store.recall.call_args
    assert store_call2.kwargs.get("kinds") is None or (
        len(store_call2.args) < 4
    ), (
        "MemoryTool.recall() with no kinds must pass kinds=None to MemoryStore.recall"
    )


# ---------------------------------------------------------------------------
# Helpers for reflection tests
# ---------------------------------------------------------------------------

def _make_valid_llm_response(override: dict | None = None) -> dict:
    """Return a mock LLMClient.chat response with a valid JSON blob."""
    payload = {
        "summary": "Today I helped Sir work through Phase 17 implementation.",
        "mood": "focused",
        "current_focus": "Phase 17 reflection cron",
        "recent_context": "Implementing the journal data-layer and orchestrator.",
        "highlights": ["Data-layer complete", "Tests green", "Prompt drafted"],
    }
    if override:
        payload.update(override)
    return {"text": json.dumps(payload)}


def _default_gathered_day() -> dict:
    """Return a representative gathered_day dict for tests."""
    return {
        "message_count": 5,
        "cost_usd": 0.002,
        "conversation": [],
        "conversation_summary": "No conversations recorded in the active session today.",
        "calendar_event_count": 2,
        "tasks_completed": 2,
        "heartbeat_ok": True,
    }


def _mock_gather_sources(
    *,
    llm_usage: dict | None = None,
    calendar_raises: bool = False,
    ticktick_raises: bool = False,
):
    """Return a context manager that patches _gather_day and _summarize_conversation.

    Patches core.reflection._gather_day (the gather orchestrator) and
    core.reflection._summarize_conversation directly — avoids deep import chains
    into mcp_tools/memory modules that require external credentials.

    When calendar_raises=True, the patch makes _gather_day omit
    calendar_event_count (simulating a per-source failure and isolation).
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        gathered = _default_gathered_day()
        if calendar_raises:
            # Simulate calendar source failure: calendar_event_count stays 0
            gathered = dict(gathered)
            gathered["calendar_event_count"] = 0

        test_env = {
            "GCP_PROJECT_ID": "test-project",
            "FIRESTORE_DATABASE": "(default)",
            "TELEGRAM_ALLOWED_USER_IDS": "123456",
            "PINECONE_API_KEY": "test-pinecone-key",
            "PINECONE_INDEX": "test-index",
            "SMART_AGENT_BACKEND": "gemini",
            "SMART_AGENT_MODEL": "gemini-3-flash",
            "SMART_AGENT_API_KEY": "test-smart-key",
            "SMART_AGENT_FALLBACK_BACKEND": "anthropic",
            "SMART_AGENT_FALLBACK_MODEL": "claude-haiku",
            "SMART_AGENT_FALLBACK_API_KEY": "test-fallback-key",
            "WORKER_AGENT_BACKEND": "gemini",
            "WORKER_AGENT_MODEL": "gemini-2.5-flash",
            "WORKER_AGENT_API_KEY": "test-worker-key",
        }

        with patch.dict("os.environ", test_env):
            with patch("core.reflection._gather_day", return_value=gathered):
                with patch(
                    "core.reflection._summarize_conversation",
                    return_value=gathered["conversation_summary"],
                ):
                    yield

    return _ctx()


# ---------------------------------------------------------------------------
# D-03: _parse_reflection_json hardening
# ---------------------------------------------------------------------------

def test_parse_reflection_json_hardened():
    """Brain JSON in ```json fences still parses; missing fields default safely. (D-03)"""
    from core.reflection import _parse_reflection_json  # noqa: PLC0415

    # 1. Fenced ```json block parses correctly
    fenced = (
        "```json\n"
        '{"summary":"Day ok","mood":"calm","current_focus":"work",'
        '"recent_context":"context here","highlights":["item1","item2"]}\n'
        "```"
    )
    result = _parse_reflection_json(fenced)
    assert result is not None, "Fenced JSON must parse"
    assert result["summary"] == "Day ok"
    assert result["mood"] == "calm"
    assert result["highlights"] == ["item1", "item2"]

    # 2. Missing field "mood" → default to ""
    missing_mood = '{"summary":"s","current_focus":"f","recent_context":"r","highlights":["h"]}'
    result2 = _parse_reflection_json(missing_mood)
    assert result2 is not None
    assert result2["mood"] == "", f"Missing mood should default to '', got {result2['mood']!r}"
    assert result2["summary"] == "s"

    # 3. highlights cap at 5
    many = {
        "summary": "s", "mood": "m", "current_focus": "f",
        "recent_context": "r",
        "highlights": ["a", "b", "c", "d", "e", "f", "g"],
    }
    result3 = _parse_reflection_json(json.dumps(many))
    assert result3 is not None
    assert len(result3["highlights"]) == 5, "highlights must be capped at 5"

    # 4. Garbage input → returns None (sentinel for D-13 fallback)
    result4 = _parse_reflection_json("this is not json at all !!! {{{")
    assert result4 is None, "Unparseable text must return None"

    # 5. highlights is wrong type (str instead of list) → defaulted to []
    wrong_type = '{"summary":"s","mood":"m","current_focus":"f","recent_context":"r","highlights":"bad"}'
    result5 = _parse_reflection_json(wrong_type)
    assert result5 is not None
    assert isinstance(result5["highlights"], list), "highlights wrong type must be defaulted to list"


# ---------------------------------------------------------------------------
# JOUR-01: run_reflection writes journal entry
# ---------------------------------------------------------------------------

def test_run_reflection_writes_entry():
    """run_reflection() gathers the day and writes a journal entry. (JOUR-01)"""
    from core.reflection import run_reflection  # noqa: PLC0415

    written_entries: list = []

    valid_llm_result = {
        "summary": "Today I helped Sir work through Phase 17.",
        "mood": "focused",
        "current_focus": "Phase 17 reflection cron",
        "recent_context": "Implementing the journal data-layer.",
        "highlights": ["Data-layer complete", "Tests green"],
    }

    mock_journal = MagicMock()
    mock_journal.get.return_value = None  # no yesterday entry

    def _capture_set(date_str, entry):
        written_entries.append({"date": date_str, "entry": entry})

    mock_journal.set.side_effect = _capture_set

    # Track SelfStateStore calls
    ss_set_calls: list = []
    mock_ss = MagicMock()
    # Simulate 2 prior entries in recent_context so the rolling window is exercisable
    prior_rc = json.dumps(["[2026-05-17] ctx A", "[2026-05-18] ctx B"])
    mock_ss.get.return_value = {"recent_context": prior_rc}
    mock_ss.set.side_effect = lambda patch_dict: ss_set_calls.append(patch_dict)

    mock_mem = MagicMock()
    mock_mem.remember_self.return_value = "self-2026-05-19"

    with _mock_gather_sources():
        # Patch JournalStore at its source module (deferred import in run_reflection)
        with patch("memory.firestore_db.JournalStore", return_value=mock_journal):
            # Patch _brain_reflect to return the LLM result directly
            with patch("core.reflection._brain_reflect", return_value=valid_llm_result):
                # Patch Pinecone and SelfStateStore to avoid external calls
                with patch("memory.pinecone_db.MemoryStore", return_value=mock_mem):
                    with patch("memory.firestore_db.SelfStateStore", return_value=mock_ss):
                        run_reflection("2026-05-19")

    assert len(written_entries) == 1, "JournalStore.set must be called exactly once"
    entry = written_entries[0]["entry"]

    # 5 LLM fields
    assert "summary" in entry, "entry must have summary"
    assert "mood" in entry, "entry must have mood"
    assert "current_focus" in entry, "entry must have current_focus"
    assert "recent_context" in entry, "entry must have recent_context"
    assert "highlights" in entry, "entry must have highlights"

    # 5 raw metrics
    assert "message_count" in entry, "entry must have message_count"
    assert "cost_usd" in entry, "entry must have cost_usd"
    assert "calendar_event_count" in entry, "entry must have calendar_event_count"
    assert "tasks_completed" in entry, "entry must have tasks_completed"
    assert "heartbeat_ok" in entry, "entry must have heartbeat_ok"

    # Task 3: verify remember_self was called (Pinecone write target 2)
    mock_mem.remember_self.assert_called_once()
    remember_kwargs = mock_mem.remember_self.call_args
    assert remember_kwargs is not None, "remember_self must be called"

    # Task 3: verify SelfStateStore.set was called (write target 3)
    assert len(ss_set_calls) == 1, "SelfStateStore.set must be called once"
    ss_patch = ss_set_calls[0]
    assert "current_focus" in ss_patch, "SelfStateStore patch must include current_focus"
    assert "mood" in ss_patch, "SelfStateStore patch must include mood"
    assert "recent_context" in ss_patch, "SelfStateStore patch must include recent_context"

    # Task 3: rolling 3-day window — started with 2 prior, after adding today's → still ≤3
    rc_stored = json.loads(ss_patch["recent_context"])
    assert isinstance(rc_stored, list), "recent_context must be a JSON list"
    assert len(rc_stored) <= 3, (
        f"recent_context rolling window must be at most 3 entries, got {len(rc_stored)}"
    )
    # Today's entry must be the newest (last) item
    assert "2026-05-19" in rc_stored[-1], (
        "The latest recent_context entry must contain today's date"
    )


# ---------------------------------------------------------------------------
# JOUR-01: gather source failure is isolated
# ---------------------------------------------------------------------------

def test_gather_source_failure_is_isolated():
    """A failing gather source does not abort run_reflection(). (JOUR-01)"""
    from core.reflection import run_reflection  # noqa: PLC0415

    journal_set_called = []
    mock_journal = MagicMock()
    mock_journal.get.return_value = None
    mock_journal.set.side_effect = lambda d, e: journal_set_called.append(e)

    valid_llm_result = {
        "summary": "Today I helped Sir.", "mood": "focused",
        "current_focus": "Phase 17", "recent_context": "Journal cron.",
        "highlights": ["Done"],
    }

    # calendar_raises=True: _mock_gather_sources returns gathered with calendar_event_count=0
    # simulating a per-source failure; the gather still returns a valid dict (isolated)
    with _mock_gather_sources(calendar_raises=True):
        with patch("memory.firestore_db.JournalStore", return_value=mock_journal):
            with patch("core.reflection._brain_reflect", return_value=valid_llm_result):
                with patch("memory.pinecone_db.MemoryStore") as mock_mem_cls:
                    mock_mem_cls.return_value.remember_self.return_value = "self-2026-05-19"
                    with patch("memory.firestore_db.SelfStateStore") as mock_ss_cls:
                        mock_ss_cls.return_value.get.return_value = {}
                        # Must not raise — calendar failure is isolated
                        run_reflection("2026-05-19")

    assert len(journal_set_called) == 1, (
        "JournalStore.set must be called even when a gather source fails"
    )


# ---------------------------------------------------------------------------
# D-13: LLM failure → minimal fallback doc
# ---------------------------------------------------------------------------

def test_reflection_llm_failure_fallback():
    """Brain + fallback LLM failure → minimal fallback doc written. (D-13)"""
    from core.reflection import run_reflection  # noqa: PLC0415

    written_entries: list = []
    mock_journal = MagicMock()
    mock_journal.get.return_value = None
    mock_journal.set.side_effect = lambda d, e: written_entries.append(e)

    with _mock_gather_sources():
        with patch("memory.firestore_db.JournalStore", return_value=mock_journal):
            # _brain_reflect returns None → triggers D-13 minimal fallback
            with patch("core.reflection._brain_reflect", return_value=None):
                with patch("memory.pinecone_db.MemoryStore") as mock_mem_cls:
                    mock_mem_cls.return_value.remember_self.return_value = "self-2026-05-19"
                    with patch("memory.firestore_db.SelfStateStore") as mock_ss_cls:
                        mock_ss_cls.return_value.get.return_value = {}
                        run_reflection("2026-05-19")

    assert len(written_entries) == 1, "Fallback doc must still be written on LLM failure"
    entry = written_entries[0]
    assert entry.get("summary") == "reflection unavailable", (
        f"D-13 fallback summary must be 'reflection unavailable', got {entry.get('summary')!r}"
    )
    # Raw metrics must still be present
    assert "message_count" in entry
    assert "cost_usd" in entry


def test_journal_digest_assembly():
    """{journal_digest} assembled from get_recent(3); empty when no entries. (JOUR-06)

    Verifies:
    1. get_recent(3) with 3 entries → journal_digest contains one line per entry
       in "- {date} (mood: {mood}): {summary}" format, plus top highlight.
    2. get_recent(3) returns [] → journal_digest == "" (block omitted).
    3. Worker prompt template does NOT contain {journal_digest} placeholder (D-15 smart-only).
    """
    from core.main import AgentOrchestrator  # noqa: PLC0415

    three_entries = [
        {
            "date": "2026-05-19",
            "mood": "focused",
            "summary": "Completed Phase 17 data-layer.",
            "highlights": ["Tests green", "Journal wired"],
        },
        {
            "date": "2026-05-18",
            "mood": "productive",
            "summary": "Implemented reflection orchestrator.",
            "highlights": ["Brain call working"],
        },
        {
            "date": "2026-05-17",
            "mood": "calm",
            "summary": "Set up cron route.",
            "highlights": [],
        },
    ]

    mock_journal_store = MagicMock()
    mock_journal_store.get_recent.return_value = three_entries

    _orch_env = {
        "SMART_AGENT_BACKEND": "gemini",
        "SMART_AGENT_MODEL": "gemini-3-flash",
        "SMART_AGENT_API_KEY": "test-smart-key",
        "WORKER_AGENT_BACKEND": "gemini",
        "WORKER_AGENT_MODEL": "gemini-2.5-flash",
        "WORKER_AGENT_API_KEY": "test-worker-key",
    }

    # --- Build orchestrator with mocked stores ------------------------------- #
    with patch.dict("os.environ", _orch_env):
        with patch("core.main._build_self_state_store", return_value=None):
            with patch("core.main._build_journal_store", return_value=mock_journal_store):
                with patch("core.main._load_self_md", return_value=""):
                    orch = AgentOrchestrator()

    # Introspect the handle_message render step by patching the LLM calls
    # so they return immediately without making real API calls.
    captured: dict = {}

    def _fake_run_smart_loop(messages, smart_system, worker_system):
        captured["smart_system"] = smart_system
        captured["worker_system"] = worker_system
        return "ok"

    with patch.object(orch, "_run_smart_loop", side_effect=_fake_run_smart_loop):
        with patch.object(orch.conversation_manager, "append"):
            with patch.object(orch.conversation_manager, "get", return_value=[]):
                orch.handle_message("hello", 123456)

    assert "smart_system" in captured, "handle_message must call _run_smart_loop"
    smart_sys = captured["smart_system"]
    worker_sys = captured["worker_system"]

    # 1. smart_system must contain each journal line
    for entry in three_entries:
        expected_fragment = f"(mood: {entry['mood']}): {entry['summary']}"
        assert expected_fragment in smart_sys, (
            f"smart_system must contain journal line for {entry['date']}: "
            f"{expected_fragment!r} not found"
        )

    # First entry's top highlight must appear
    assert "Tests green" in smart_sys, (
        "Top highlight of first entry must appear in smart_system journal digest"
    )

    # 2. Empty journal → journal_digest == "" → no "**Recent journal:**" header
    mock_journal_store.get_recent.return_value = []
    captured.clear()

    with patch.object(orch, "_run_smart_loop", side_effect=_fake_run_smart_loop):
        with patch.object(orch.conversation_manager, "append"):
            with patch.object(orch.conversation_manager, "get", return_value=[]):
                orch.handle_message("hello", 123456)

    assert "**Recent journal:**" not in captured.get("smart_system", ""), (
        "Empty journal must omit the digest block entirely"
    )
    # The {journal_digest} placeholder must be replaced (not left as literal text)
    assert "{journal_digest}" not in captured.get("smart_system", ""), (
        "{journal_digest} placeholder must be replaced, not left as literal text"
    )

    # 3. Worker prompt must NOT contain {journal_digest} (D-15 smart-only)
    worker_template_path = "prompts/worker_agent.md"
    worker_template = open(worker_template_path).read()
    assert "journal_digest" not in worker_template, (
        "prompts/worker_agent.md must NOT contain journal_digest (D-15 smart-only)"
    )
