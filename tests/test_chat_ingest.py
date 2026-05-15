"""Unit tests for core.chat_ingest — Phase 12."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.chat_ingest import (
    MIN_TURN_CHARS,
    BATCH_MAX_FILES,
    CHUNK_MAX_CHARS,
    CHUNK_OVERLAP_CHARS,
    ParsedConversation,
    Turn,
    _chunk_conversation,
    _decode_project_path,
    parse_claude_code_jsonl,
)


# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

def _make_jsonl(*objects) -> bytes:
    """Build a JSONL bytes payload from a list of dicts."""
    return b"\n".join(json.dumps(obj).encode() for obj in objects)


def _user_turn(
    text: str,
    uuid: str = "u1",
    sidechain: bool = False,
    meta: bool = False,
    tool_result: bool = False,
) -> dict:
    """Build a minimal user turn object."""
    obj = {
        "type": "user",
        "uuid": uuid,
        "isMeta": meta,
        "isSidechain": sidechain,
        "message": {"content": text},
        "timestamp": "2026-01-01T10:00:00.000Z",
    }
    if tool_result:
        obj["toolUseResult"] = {"result": "something"}
    return obj


def _assistant_turn(text: str, uuid: str = "a1", sidechain: bool = False) -> dict:
    """Build a minimal assistant turn object."""
    return {
        "type": "assistant",
        "uuid": uuid,
        "isSidechain": sidechain,
        "message": {"content": [{"type": "text", "text": text}]},
        "timestamp": "2026-01-01T10:01:00.000Z",
    }


# Enough text to survive MIN_TURN_CHARS filter
_LONG_ENOUGH = "This is a valid turn with sufficient length."


# ================================================================== #
# 1. Parser — keep rules                                             #
# ================================================================== #

class TestParserKeepRules:
    def test_valid_user_turn_is_kept(self):
        """type==user, isMeta falsy, isSidechain falsy, no toolUseResult, str content → kept."""
        blob = _make_jsonl(_user_turn(_LONG_ENOUGH, uuid="u-keep"))
        conv = parse_claude_code_jsonl(blob, "sess1", "mac")
        assert conv is not None
        assert len(conv.turns) == 1
        assert conv.turns[0].role == "user"
        assert conv.turns[0].uuid == "u-keep"

    def test_valid_assistant_turn_is_kept(self):
        """type==assistant, isSidechain falsy, content is list with text blocks → kept."""
        blob = _make_jsonl(_assistant_turn(_LONG_ENOUGH, uuid="a-keep"))
        conv = parse_claude_code_jsonl(blob, "sess2", "mac")
        assert conv is not None
        assert len(conv.turns) == 1
        assert conv.turns[0].role == "assistant"
        assert conv.turns[0].uuid == "a-keep"

    def test_both_roles_are_kept(self):
        """Both a user and an assistant turn in one file → both kept in order."""
        blob = _make_jsonl(
            _user_turn(_LONG_ENOUGH, uuid="u1"),
            _assistant_turn(_LONG_ENOUGH, uuid="a1"),
        )
        conv = parse_claude_code_jsonl(blob, "sess3", "mac")
        assert conv is not None
        assert len(conv.turns) == 2
        assert conv.turns[0].role == "user"
        assert conv.turns[1].role == "assistant"


# ================================================================== #
# 2. Parser — drop rules                                             #
# ================================================================== #

class TestParserDropRules:
    def test_drop_meta_user_turn(self):
        """isMeta=True → user turn dropped."""
        blob = _make_jsonl(_user_turn(_LONG_ENOUGH, meta=True))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_sidechain_user_turn(self):
        """isSidechain=True on user turn → dropped."""
        blob = _make_jsonl(_user_turn(_LONG_ENOUGH, sidechain=True))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_sidechain_assistant_turn(self):
        """isSidechain=True on assistant turn → dropped."""
        blob = _make_jsonl(_assistant_turn(_LONG_ENOUGH, sidechain=True))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_tool_use_result(self):
        """User turn with toolUseResult → dropped."""
        blob = _make_jsonl(_user_turn(_LONG_ENOUGH, tool_result=True))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_user_turn_list_content(self):
        """User turn where message.content is a list (not str) → dropped."""
        obj = {
            "type": "user",
            "uuid": "u-list",
            "isMeta": False,
            "isSidechain": False,
            "message": {"content": [{"type": "text", "text": _LONG_ENOUGH}]},
            "timestamp": "2026-01-01T10:00:00.000Z",
        }
        blob = _make_jsonl(obj)
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_short_user_turn(self):
        """User turn text shorter than MIN_TURN_CHARS → dropped."""
        short_text = "x" * (MIN_TURN_CHARS - 1)
        blob = _make_jsonl(_user_turn(short_text))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_short_assistant_turn(self):
        """Assistant turn text shorter than MIN_TURN_CHARS → dropped."""
        short_text = "y" * (MIN_TURN_CHARS - 1)
        blob = _make_jsonl(_assistant_turn(short_text))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_type_tool_result(self):
        """type==tool_result → not a user or assistant turn, ignored."""
        obj = {
            "type": "tool_result",
            "uuid": "tr1",
            "message": {"content": "some tool output that is long enough"},
            "timestamp": "2026-01-01T10:00:00.000Z",
        }
        blob = _make_jsonl(obj)
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_drop_type_thinking(self):
        """type==thinking → not a user or assistant turn, ignored."""
        obj = {
            "type": "thinking",
            "uuid": "th1",
            "message": {"content": "internal reasoning that is long enough surely"},
            "timestamp": "2026-01-01T10:00:00.000Z",
        }
        blob = _make_jsonl(obj)
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_exactly_min_chars_is_kept(self):
        """A turn of exactly MIN_TURN_CHARS passes the length filter."""
        exact_text = "a" * MIN_TURN_CHARS
        blob = _make_jsonl(_user_turn(exact_text))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert len(conv.turns) == 1


# ================================================================== #
# 3. Parser — zero-turn file                                         #
# ================================================================== #

class TestParserZeroTurns:
    def test_all_filtered_returns_none(self):
        """File where all turns are filtered returns None."""
        blob = _make_jsonl(
            _user_turn(_LONG_ENOUGH, meta=True),
            _user_turn(_LONG_ENOUGH, sidechain=True),
            _assistant_turn(_LONG_ENOUGH, sidechain=True),
        )
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is None

    def test_empty_file_returns_none(self):
        """Empty file returns None."""
        conv = parse_claude_code_jsonl(b"", "s", "mac")
        assert conv is None

    def test_only_whitespace_lines_returns_none(self):
        """File with only blank lines returns None."""
        conv = parse_claude_code_jsonl(b"\n\n   \n", "s", "mac")
        assert conv is None


# ================================================================== #
# 4. Parser — malformed lines                                        #
# ================================================================== #

class TestParserMalformedLines:
    def test_malformed_line_logs_warning_and_continues(self, caplog):
        """Non-JSON garbage logs a warning; valid turns in the same file are kept."""
        valid = _user_turn(_LONG_ENOUGH, uuid="u-good")
        raw = json.dumps(valid).encode() + b"\nNOT_JSON{{{" + b"\n" + json.dumps(valid).encode()
        with caplog.at_level(logging.WARNING, logger="core.chat_ingest"):
            conv = parse_claude_code_jsonl(raw, "sess-bad", "mac")

        # At least one warning about malformed JSON
        assert any("malformed" in r.message.lower() for r in caplog.records)
        # Valid turns still parsed
        assert conv is not None
        assert len(conv.turns) == 2

    def test_malformed_line_only_returns_none(self, caplog):
        """File with only a malformed line returns None (no valid turns)."""
        raw = b"NOT_JSON{{{"
        with caplog.at_level(logging.WARNING, logger="core.chat_ingest"):
            conv = parse_claude_code_jsonl(raw, "sess-only-bad", "mac")
        assert conv is None


# ================================================================== #
# 5. Parser — title extraction                                       #
# ================================================================== #

class TestParserTitleExtraction:
    def test_last_ai_title_wins(self):
        """When multiple ai-title objects exist, the last aiTitle value is used."""
        first_title = {"type": "ai-title", "aiTitle": "First Title"}
        second_title = {"type": "ai-title", "aiTitle": "Second Title (last)"}
        blob = _make_jsonl(
            first_title,
            _user_turn(_LONG_ENOUGH),
            second_title,
        )
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert conv.title == "Second Title (last)"

    def test_fallback_to_last_prompt(self):
        """When no ai-title, last-prompt[:80] is used as title."""
        long_prompt = "A" * 120
        last_prompt_obj = {"type": "last-prompt", "lastPrompt": long_prompt}
        blob = _make_jsonl(
            last_prompt_obj,
            _user_turn(_LONG_ENOUGH),
        )
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert conv.title == long_prompt[:80]

    def test_fallback_to_last_prompt_short(self):
        """Short last-prompt is kept in full."""
        prompt_text = "Short prompt"
        last_prompt_obj = {"type": "last-prompt", "lastPrompt": prompt_text}
        blob = _make_jsonl(
            last_prompt_obj,
            _user_turn(_LONG_ENOUGH),
        )
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert conv.title == prompt_text

    def test_fallback_to_default_title(self):
        """When neither ai-title nor last-prompt exists, title is 'Claude Code session'."""
        blob = _make_jsonl(_user_turn(_LONG_ENOUGH))
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert conv.title == "Claude Code session"

    def test_ai_title_takes_precedence_over_last_prompt(self):
        """ai-title wins over last-prompt even if last-prompt appears after."""
        blob = _make_jsonl(
            {"type": "last-prompt", "lastPrompt": "from last-prompt"},
            {"type": "ai-title", "aiTitle": "from ai-title"},
            _user_turn(_LONG_ENOUGH),
        )
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert conv.title == "from ai-title"

    def test_last_prompt_not_used_when_ai_title_seen_first(self):
        """last-prompt does NOT overwrite a title already set by ai-title."""
        blob = _make_jsonl(
            {"type": "ai-title", "aiTitle": "ai-title-value"},
            {"type": "last-prompt", "lastPrompt": "last-prompt-value"},
            _user_turn(_LONG_ENOUGH),
        )
        conv = parse_claude_code_jsonl(blob, "s", "mac")
        assert conv is not None
        assert conv.title == "ai-title-value"


# ================================================================== #
# 6. _decode_project_path                                            #
# ================================================================== #

class TestDecodeProjectPath:
    def test_empty_string(self):
        assert _decode_project_path("") == ""

    def test_already_a_path(self):
        """Strings starting with '/' are returned as-is."""
        assert _decode_project_path("/Users/amit/Desktop/Klaus") == "/Users/amit/Desktop/Klaus"

    def test_single_segment(self):
        """'-' is treated as path separator and replaced by '/'."""
        # No leading slash because the encoded string doesn't start with '/'
        assert _decode_project_path("Users-amit-Desktop-Klaus") == "Users/amit/Desktop/Klaus"

    def test_literal_hyphen_preserved(self):
        """'--' in encoded name decodes to a literal '-' in the output."""
        # e.g. 'Users-amit-my--project' → 'Users/amit/my-project'
        assert _decode_project_path("Users-amit-my--project") == "Users/amit/my-project"

    def test_mixed_separators_and_hyphens(self):
        """Combined path separators and literal hyphens decode correctly."""
        # encoded 'Users-amit-Desktop-my--cool--app'
        # → Users/amit/Desktop/my-cool-app
        assert _decode_project_path("Users-amit-Desktop-my--cool--app") == "Users/amit/Desktop/my-cool-app"


# ================================================================== #
# 7. Chunking — deterministic IDs                                    #
# ================================================================== #

class TestChunkingDeterministicIds:
    def test_chunk_id_format(self):
        """Chunk IDs follow cc-{session_id}-{turn_uuid}-{chunk_index} format."""
        conv = ParsedConversation(
            session_id="sess-abc",
            title="Test",
            project="/proj",
            machine_id="mac",
            started_at="",
            ended_at="",
            turns=[Turn(uuid="turn-xyz", role="user", text=_LONG_ENOUGH, timestamp="")],
        )
        chunks = _chunk_conversation(conv)
        assert len(chunks) >= 1
        assert chunks[0]["id"] == "cc-sess-abc-turn-xyz-0"

    def test_chunk_id_increments_per_chunk(self):
        """For a multi-chunk turn, index increments: -0, -1, ..."""
        long_text = "W" * (CHUNK_MAX_CHARS * 3)
        conv = ParsedConversation(
            session_id="s",
            title="T",
            project="",
            machine_id="mac",
            started_at="",
            ended_at="",
            turns=[Turn(uuid="t1", role="assistant", text=long_text, timestamp="")],
        )
        chunks = _chunk_conversation(conv)
        for i, chunk in enumerate(chunks):
            assert chunk["id"] == f"cc-s-t1-{i}"


# ================================================================== #
# 8. Chunking — short turn = single chunk                            #
# ================================================================== #

class TestChunkingShortTurn:
    def test_short_turn_produces_one_chunk(self):
        """Turn whose prefixed text <= CHUNK_MAX_CHARS → exactly 1 chunk."""
        text = "A" * 50  # well under 1800
        conv = ParsedConversation(
            session_id="s",
            title="T",
            project="",
            machine_id="mac",
            started_at="",
            ended_at="",
            turns=[Turn(uuid="u1", role="user", text=text, timestamp="")],
        )
        chunks = _chunk_conversation(conv)
        assert len(chunks) == 1

    def test_chunk_contains_prefix(self):
        """Single chunk content starts with the [title] role: prefix."""
        conv = ParsedConversation(
            session_id="s",
            title="MyTitle",
            project="",
            machine_id="mac",
            started_at="",
            ended_at="",
            turns=[Turn(uuid="u1", role="user", text="Hello there friend!", timestamp="")],
        )
        chunks = _chunk_conversation(conv)
        assert chunks[0]["content"].startswith("[MyTitle] user: ")


# ================================================================== #
# 9. Chunking — long turn = multiple chunks with overlap             #
# ================================================================== #

class TestChunkingLongTurn:
    def _make_long_conv(self, char_count: int) -> ParsedConversation:
        text = "X" * char_count
        return ParsedConversation(
            session_id="s",
            title="T",
            project="",
            machine_id="mac",
            started_at="",
            ended_at="",
            turns=[Turn(uuid="t1", role="assistant", text=text, timestamp="")],
        )

    def test_long_turn_produces_multiple_chunks(self):
        """Turn whose prefixed text > CHUNK_MAX_CHARS → more than 1 chunk."""
        conv = self._make_long_conv(CHUNK_MAX_CHARS * 3)
        chunks = _chunk_conversation(conv)
        assert len(chunks) > 1

    def test_overlap_between_consecutive_chunks(self):
        """End of chunk N and start of chunk N+1 share ~CHUNK_OVERLAP_CHARS characters."""
        # Build text long enough to force at least 2 chunks after prefixing
        prefix_overhead = len("[T] assistant: ")
        text_length = CHUNK_MAX_CHARS * 2
        conv = self._make_long_conv(text_length)
        chunks = _chunk_conversation(conv)
        assert len(chunks) >= 2

        # The tail of chunk[0] and the head of chunk[1] should overlap
        end_of_first = chunks[0]["content"][-CHUNK_OVERLAP_CHARS:]
        start_of_second = chunks[1]["content"][:CHUNK_OVERLAP_CHARS]
        assert end_of_first == start_of_second

    def test_no_content_lost_across_chunks(self):
        """The last chunk contains the end of the full prefixed string."""
        conv = self._make_long_conv(CHUNK_MAX_CHARS * 2)
        chunks = _chunk_conversation(conv)
        prefix = "[T] assistant: "
        full_text = prefix + ("X" * CHUNK_MAX_CHARS * 2)
        # First chunk must start at position 0
        assert chunks[0]["content"] == full_text[:CHUNK_MAX_CHARS]
        # Last chunk must contain the final characters of the full text
        assert chunks[-1]["content"] == full_text[-(len(chunks[-1]["content"])):]


# ================================================================== #
# 10. recall kinds filter                                            #
# ================================================================== #

class TestRecallKindsFilter:
    """Tests for MemoryStore.recall() kinds filtering — all offline."""

    def _make_store_with_mock_index(self):
        """Create a MemoryStore with a mocked Pinecone index and embed method."""
        from memory.pinecone_db import MemoryStore
        store = MemoryStore(api_key="fake-key", index_name="fake-index")

        # Mock the index so no network calls happen
        mock_index = MagicMock()
        mock_index.query.return_value = MagicMock(matches=[])
        store._index = mock_index

        # Mock _embed so no Gemini calls happen
        store._embed = MagicMock(return_value=[0.0] * 768)

        return store, mock_index

    def test_default_kinds_excludes_chat(self):
        """recall() without kinds argument filters to fact and chunk (not chat)."""
        store, mock_index = self._make_store_with_mock_index()
        store.recall(user_id=1, query="test query")

        args, kwargs = mock_index.query.call_args
        passed_filter = kwargs.get("filter") or args[0] if args else kwargs["filter"]
        assert passed_filter["kind"] == {"$in": ["fact", "chunk"]}

    def test_default_kinds_not_chat(self):
        """Verify 'chat' is NOT in the default kinds list."""
        store, mock_index = self._make_store_with_mock_index()
        store.recall(user_id=1, query="test query")

        _, kwargs = mock_index.query.call_args
        kinds_in_filter = kwargs["filter"]["kind"]["$in"]
        assert "chat" not in kinds_in_filter

    def test_explicit_chat_kind(self):
        """recall() with kinds=['chat'] passes only chat to Pinecone filter."""
        store, mock_index = self._make_store_with_mock_index()
        store.recall(user_id=1, query="test query", kinds=["chat"])

        _, kwargs = mock_index.query.call_args
        assert kwargs["filter"]["kind"] == {"$in": ["chat"]}

    def test_explicit_multiple_kinds(self):
        """recall() with explicit kinds=['fact', 'chat'] passes both."""
        store, mock_index = self._make_store_with_mock_index()
        store.recall(user_id=1, query="test query", kinds=["fact", "chat"])

        _, kwargs = mock_index.query.call_args
        kinds_in_filter = kwargs["filter"]["kind"]["$in"]
        assert set(kinds_in_filter) == {"fact", "chat"}

    def test_user_id_filter_always_present(self):
        """user_id filter is always passed to Pinecone regardless of kinds."""
        store, mock_index = self._make_store_with_mock_index()
        store.recall(user_id=42, query="something")

        _, kwargs = mock_index.query.call_args
        assert kwargs["filter"]["user_id"] == {"$eq": "42"}

    def test_recall_returns_empty_list_on_no_matches(self):
        """recall() returns [] when Pinecone returns no matches."""
        store, _ = self._make_store_with_mock_index()
        result = store.recall(user_id=1, query="no matches")
        assert result == []


# ================================================================== #
# Shared fixture: inject fake google.cloud.storage into sys.modules #
# ================================================================== #

def _make_gcs_mock(blobs: list) -> tuple[MagicMock, MagicMock]:
    """Return (mock_storage_module, mock_client_instance) wired with the given blobs."""
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = blobs
    mock_client.bucket.return_value = mock_bucket

    mock_storage = MagicMock()
    mock_storage.Client.return_value = mock_client

    mock_cloud = MagicMock()
    mock_cloud.storage = mock_storage

    mock_google = MagicMock()
    mock_google.cloud = mock_cloud

    return mock_storage, mock_client


def _make_good_blob(name: str, generation: int = 1) -> MagicMock:
    blob = MagicMock()
    blob.name = name
    blob.generation = generation
    valid_line = json.dumps(_user_turn(_LONG_ENOUGH, uuid="u1")).encode()
    blob.download_as_bytes.return_value = valid_line
    return blob


def _make_bad_blob(name: str, generation: int = 1) -> MagicMock:
    """Blob whose download_as_bytes raises an exception."""
    blob = MagicMock()
    blob.name = name
    blob.generation = generation
    blob.download_as_bytes.side_effect = RuntimeError("simulated GCS error")
    return blob


_BATCH_ENV = {
    "TELEGRAM_ALLOWED_USER_IDS": "12345",
    "CHAT_LOGS_BUCKET": "fake-bucket",
    "NOTION_CHAT_LOG_DB_ID": "fake-notion-db-id",
}


# ================================================================== #
# 11. run_one_batch — batch limit                                    #
# ================================================================== #

class TestRunOneBatchBatchLimit:
    """Test run_one_batch respects BATCH_MAX_FILES."""

    def _run_batch(self, blobs, batch_max: int = 3, time_budget: int = 999):
        """Run run_one_batch fully mocked; return result dict."""
        mock_storage, mock_client = _make_gcs_mock(blobs)

        mock_store = MagicMock()
        mock_store.upsert_chat_chunks.return_value = 0

        env = {**_BATCH_ENV, "CHAT_INGEST_BATCH_MAX_FILES": str(batch_max),
               "CHAT_INGEST_TIME_BUDGET_SEC": str(time_budget)}

        # Build a fake google.cloud.storage module hierarchy so that the
        # `import google.cloud.storage` lazy import inside run_one_batch resolves
        # to our mock client — without needing google-cloud-storage installed.
        mock_gcs_module = MagicMock()
        mock_gcs_module.Client = mock_storage.Client
        mock_cloud_module = MagicMock()
        mock_cloud_module.storage = mock_gcs_module
        mock_google_module = MagicMock()
        mock_google_module.cloud = mock_cloud_module

        with patch.dict("os.environ", env), \
             patch("core.chat_ingest._get_state", return_value={}), \
             patch("core.chat_ingest._set_state"), \
             patch("core.chat_ingest._get_memory_store", return_value=mock_store), \
             patch("core.chat_ingest._summarize", return_value=("summary", [])), \
             patch.dict(
                 sys.modules,
                 {
                     "google": mock_google_module,
                     "google.cloud": mock_cloud_module,
                     "google.cloud.storage": mock_gcs_module,
                     "mcp_tools.notion_tool": MagicMock(
                         build_chat_log_properties=MagicMock(return_value={}),
                         upsert_database_row=MagicMock(),
                     ),
                 },
             ):
            from core.chat_ingest import run_one_batch
            return run_one_batch()

    def test_batch_limit_respected(self):
        """With 10 blobs in queue and BATCH_MAX_FILES=3, only 3 are processed."""
        blobs = [_make_good_blob(f"claude-code/mac/session-{i}.jsonl", i) for i in range(10)]
        result = self._run_batch(blobs, batch_max=3)
        assert result["ok"] is True
        assert result["processed"] == 3
        assert result["remaining"] == 7
        assert result["done"] is False

    def test_done_when_all_processed(self):
        """When queue has fewer blobs than batch max, done=True."""
        blobs = [_make_good_blob(f"claude-code/mac/session-{i}.jsonl", i) for i in range(2)]
        result = self._run_batch(blobs, batch_max=5)
        assert result["processed"] == 2
        assert result["done"] is True


# ================================================================== #
# 12. run_one_batch — per-file error isolation                       #
# ================================================================== #

class TestRunOneBatchErrorIsolation:
    """Test that a per-blob error does not abort the entire batch."""

    def _run_batch_with_blobs(self, blobs, batch_max: int = 10):
        mock_storage, mock_client = _make_gcs_mock(blobs)

        mock_store = MagicMock()
        mock_store.upsert_chat_chunks.return_value = 0

        env = {**_BATCH_ENV, "CHAT_INGEST_BATCH_MAX_FILES": str(batch_max),
               "CHAT_INGEST_TIME_BUDGET_SEC": "999"}

        mock_gcs_module = MagicMock()
        mock_gcs_module.Client = mock_storage.Client
        mock_cloud_module = MagicMock()
        mock_cloud_module.storage = mock_gcs_module
        mock_google_module = MagicMock()
        mock_google_module.cloud = mock_cloud_module

        with patch.dict("os.environ", env), \
             patch("core.chat_ingest._get_state", return_value={}), \
             patch("core.chat_ingest._set_state"), \
             patch("core.chat_ingest._get_memory_store", return_value=mock_store), \
             patch("core.chat_ingest._summarize", return_value=("summary", [])), \
             patch.dict(
                 sys.modules,
                 {
                     "google": mock_google_module,
                     "google.cloud": mock_cloud_module,
                     "google.cloud.storage": mock_gcs_module,
                     "mcp_tools.notion_tool": MagicMock(
                         build_chat_log_properties=MagicMock(return_value={}),
                         upsert_database_row=MagicMock(),
                     ),
                 },
             ):
            from core.chat_ingest import run_one_batch
            return run_one_batch()

    def test_blob_2_error_does_not_crash_batch(self):
        """Blob 2 of 3 raises an exception; batch doesn't crash and processes blobs 1 and 3."""
        blobs = [
            _make_good_blob("claude-code/mac/session-1.jsonl", 1),
            _make_bad_blob("claude-code/mac/session-2.jsonl", 2),
            _make_good_blob("claude-code/mac/session-3.jsonl", 3),
        ]
        result = self._run_batch_with_blobs(blobs)
        assert result["ok"] is True
        # Blob 2 failed → only blobs 1 and 3 counted as processed
        assert result["processed"] == 2

    def test_all_blobs_fail_returns_zero_processed(self):
        """When all blobs fail, processed=0 but batch still returns ok=True."""
        blobs = [_make_bad_blob(f"claude-code/mac/session-{i}.jsonl", i) for i in range(3)]
        result = self._run_batch_with_blobs(blobs)
        assert result["ok"] is True
        assert result["processed"] == 0
