"""Unit tests for core.chat_export_ingest — Phase 13."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.chat_export_ingest import (
    _html_to_text,
    _time_gap_minutes,
    parse_claude_ai_export,
    parse_chatgpt_export,
    parse_gemini_export,
)
from core.chat_ingest import MIN_TURN_CHARS

# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

_LONG = "This is a sufficiently long text string for testing purposes."


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Build an in-memory zip from a filename→bytes dict."""
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ================================================================== #
# 1. _html_to_text                                                   #
# ================================================================== #

class TestHtmlToText:
    def test_strips_tags(self):
        assert _html_to_text("<p>Hello world</p>") == "Hello world"

    def test_nested_tags(self):
        result = _html_to_text("<div><b>bold</b> and <i>italic</i></div>")
        assert "bold" in result
        assert "italic" in result

    def test_empty_string(self):
        assert _html_to_text("") == ""

    def test_plain_text_passthrough(self):
        assert _html_to_text("no tags here") == "no tags here"


# ================================================================== #
# 2. _time_gap_minutes                                               #
# ================================================================== #

class TestTimeGapMinutes:
    def test_thirty_min_gap(self):
        t1 = "2026-01-01T10:00:00Z"
        t2 = "2026-01-01T10:30:00Z"
        assert _time_gap_minutes(t1, t2) == pytest.approx(30.0)

    def test_zero_gap(self):
        t = "2026-01-01T12:00:00Z"
        assert _time_gap_minutes(t, t) == pytest.approx(0.0)

    def test_invalid_returns_zero(self):
        assert _time_gap_minutes("bad", "also-bad") == 0.0


# ================================================================== #
# 3. parse_claude_ai_export                                          #
# ================================================================== #

def _claude_ai_export(convs: list) -> bytes:
    return json.dumps(convs).encode()


def _claude_ai_conv(
    uuid="conv-1",
    name="Test convo",
    created_at="2026-01-01T10:00:00Z",
    updated_at="2026-01-01T10:05:00Z",
    messages=None,
):
    if messages is None:
        messages = [
            {"uuid": "m1", "sender": "human", "text": _LONG, "created_at": "2026-01-01T10:00:00Z"},
            {"uuid": "m2", "sender": "assistant", "text": _LONG, "created_at": "2026-01-01T10:01:00Z"},
        ]
    return {
        "uuid": uuid,
        "name": name,
        "created_at": created_at,
        "updated_at": updated_at,
        "chat_messages": messages,
    }


class TestParseClaudeAiExport:
    def test_basic_parse(self):
        data = _claude_ai_export([_claude_ai_conv()])
        convs = parse_claude_ai_export(data)
        assert len(convs) == 1
        conv = convs[0]
        assert conv.session_id == "conv-1"
        assert conv.source == "claude_ai"
        assert conv.title == "Test convo"
        assert len(conv.turns) == 2

    def test_sender_human_becomes_user_role(self):
        data = _claude_ai_export([_claude_ai_conv()])
        conv = parse_claude_ai_export(data)[0]
        assert conv.turns[0].role == "user"
        assert conv.turns[1].role == "assistant"

    def test_empty_messages_skipped(self):
        """Conversation with no messages → excluded from result."""
        data = _claude_ai_export([_claude_ai_conv(messages=[])])
        convs = parse_claude_ai_export(data)
        assert convs == []

    def test_short_text_filtered(self):
        """Messages shorter than MIN_TURN_CHARS are dropped."""
        short = "x" * (MIN_TURN_CHARS - 1)
        messages = [{"uuid": "m1", "sender": "human", "text": short, "created_at": ""}]
        data = _claude_ai_export([_claude_ai_conv(messages=messages)])
        convs = parse_claude_ai_export(data)
        assert convs == []

    def test_content_fallback(self):
        """If text field is empty, falls back to joining content blocks."""
        messages = [
            {
                "uuid": "m1",
                "sender": "human",
                "text": "",
                "content": [{"type": "text", "text": _LONG}],
                "created_at": "",
            }
        ]
        data = _claude_ai_export([_claude_ai_conv(messages=messages)])
        convs = parse_claude_ai_export(data)
        assert len(convs) == 1
        assert _LONG in convs[0].turns[0].text

    def test_multiple_conversations(self):
        data = _claude_ai_export([_claude_ai_conv("c1"), _claude_ai_conv("c2")])
        convs = parse_claude_ai_export(data)
        assert len(convs) == 2
        ids = {c.session_id for c in convs}
        assert ids == {"c1", "c2"}

    def test_title_truncated_to_80(self):
        long_name = "A" * 120
        data = _claude_ai_export([_claude_ai_conv(name=long_name)])
        conv = parse_claude_ai_export(data)[0]
        assert len(conv.title) == 80

    def test_started_at_and_ended_at(self):
        data = _claude_ai_export([_claude_ai_conv(
            created_at="2026-03-01T08:00:00Z",
            updated_at="2026-03-01T09:00:00Z",
        )])
        conv = parse_claude_ai_export(data)[0]
        assert conv.started_at == "2026-03-01T08:00:00Z"
        assert conv.ended_at == "2026-03-01T09:00:00Z"


# ================================================================== #
# 4. parse_chatgpt_export                                            #
# ================================================================== #

def _make_chatgpt_mapping(turns: list[tuple[str, str]]) -> tuple[dict, str]:
    """Build a minimal ChatGPT mapping tree from (role, text) pairs.

    Returns (mapping_dict, current_node_id).
    """
    mapping: dict = {}
    prev_id: str | None = None

    for i, (role, text) in enumerate(turns):
        nid = f"node-{i}"
        mapping[nid] = {
            "id": nid,
            "parent": prev_id,
            "children": [],
            "message": {
                "id": nid,
                "author": {"role": role},
                "content": {"content_type": "text", "parts": [text]},
                "create_time": 1700000000.0 + i,
            },
        }
        if prev_id:
            mapping[prev_id]["children"].append(nid)
        prev_id = nid

    current_node = f"node-{len(turns) - 1}" if turns else ""
    return mapping, current_node


def _chatgpt_export(convs: list) -> bytes:
    return json.dumps(convs).encode()


class TestParseChatgptExport:
    def test_basic_parse(self):
        mapping, current_node = _make_chatgpt_mapping([
            ("user", _LONG),
            ("assistant", _LONG),
        ])
        data = _chatgpt_export([{
            "title": "Test chat",
            "create_time": 1700000000.0,
            "update_time": 1700000120.0,
            "conversation_id": "gpt-conv-1",
            "mapping": mapping,
            "current_node": current_node,
        }])
        convs = parse_chatgpt_export(data)
        assert len(convs) == 1
        conv = convs[0]
        assert conv.session_id == "gpt-conv-1"
        assert conv.source == "chatgpt"
        assert conv.title == "Test chat"
        assert len(conv.turns) == 2

    def test_roles_correct(self):
        mapping, current_node = _make_chatgpt_mapping([
            ("user", _LONG),
            ("assistant", _LONG),
        ])
        data = _chatgpt_export([{
            "title": "T", "create_time": 0, "update_time": 0,
            "conversation_id": "c1", "mapping": mapping, "current_node": current_node,
        }])
        conv = parse_chatgpt_export(data)[0]
        assert conv.turns[0].role == "user"
        assert conv.turns[1].role == "assistant"

    def test_system_nodes_skipped(self):
        """system role nodes are not included in turns."""
        mapping, current_node = _make_chatgpt_mapping([
            ("system", "You are a helpful assistant."),
            ("user", _LONG),
            ("assistant", _LONG),
        ])
        data = _chatgpt_export([{
            "title": "T", "create_time": 0, "update_time": 0,
            "conversation_id": "c1", "mapping": mapping, "current_node": current_node,
        }])
        conv = parse_chatgpt_export(data)[0]
        roles = [t.role for t in conv.turns]
        assert "system" not in roles
        assert len(conv.turns) == 2

    def test_missing_current_node_skipped(self):
        data = _chatgpt_export([{
            "title": "T", "create_time": 0, "update_time": 0,
            "conversation_id": "c1", "mapping": {}, "current_node": None,
        }])
        convs = parse_chatgpt_export(data)
        assert convs == []

    def test_short_turns_filtered(self):
        short = "x" * (MIN_TURN_CHARS - 1)
        mapping, current_node = _make_chatgpt_mapping([("user", short)])
        data = _chatgpt_export([{
            "title": "T", "create_time": 0, "update_time": 0,
            "conversation_id": "c1", "mapping": mapping, "current_node": current_node,
        }])
        convs = parse_chatgpt_export(data)
        assert convs == []

    def test_epoch_timestamps_converted(self):
        mapping, current_node = _make_chatgpt_mapping([("user", _LONG)])
        data = _chatgpt_export([{
            "title": "T",
            "create_time": 1700000000.0,
            "update_time": 1700000060.0,
            "conversation_id": "c1",
            "mapping": mapping,
            "current_node": current_node,
        }])
        conv = parse_chatgpt_export(data)[0]
        assert "T" in conv.started_at  # ISO string contains a T separator
        assert conv.started_at.startswith("2023")  # epoch 1700000000 ≈ Nov 2023


# ================================================================== #
# 5. parse_gemini_export                                             #
# ================================================================== #

def _gemini_record(title: str, html: str, time: str) -> dict:
    return {
        "title": title,
        "safeHtmlItem": [{"html": html}],
        "time": time,
    }


def _gemini_export(records: list) -> bytes:
    return json.dumps(records).encode()


class TestParseGeminiExport:
    def test_basic_parse(self):
        records = [
            _gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:00:00Z"),
        ]
        convs = parse_gemini_export(_gemini_export(records))
        assert len(convs) == 1
        conv = convs[0]
        assert conv.source == "gemini"
        assert len(conv.turns) == 2  # user + assistant

    def test_canvas_records_skipped(self):
        records = [
            _gemini_record("Created Gemini Canvas something", "<p>canvas</p>", "2026-01-01T10:00:00Z"),
            _gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:05:00Z"),
        ]
        convs = parse_gemini_export(_gemini_export(records))
        assert len(convs) == 1

    def test_clustering_by_gap(self):
        """Records >30 min apart → separate conversations."""
        records = [
            _gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T09:00:00Z"),
            _gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:00:00Z"),  # 60 min gap
        ]
        convs = parse_gemini_export(_gemini_export(records))
        assert len(convs) == 2

    def test_clustering_within_gap(self):
        """Records ≤30 min apart → same conversation."""
        records = [
            _gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:00:00Z"),
            _gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:20:00Z"),  # 20 min gap
        ]
        convs = parse_gemini_export(_gemini_export(records))
        assert len(convs) == 1
        # Two records → 4 turns (2 user + 2 assistant)
        assert len(convs[0].turns) == 4

    def test_session_id_deterministic(self):
        """session_id = sha1(earliest_time)[:16], same input → same ID."""
        time_str = "2026-03-15T14:30:00Z"
        records = [_gemini_record(f"Prompted {_LONG}", f"<p>{_LONG}</p>", time_str)]
        convs = parse_gemini_export(_gemini_export(records))
        expected_id = hashlib.sha1(time_str.encode()).hexdigest()[:16]
        assert convs[0].session_id == expected_id

    def test_html_stripped_from_assistant(self):
        html = "<p>This is <b>bold</b> text that is long enough to pass the filter.</p>"
        records = [_gemini_record(f"Prompted {_LONG}", html, "2026-01-01T10:00:00Z")]
        conv = parse_gemini_export(_gemini_export(records))[0]
        asst_turn = next(t for t in conv.turns if t.role == "assistant")
        assert "<" not in asst_turn.text
        assert "bold" in asst_turn.text

    def test_prompted_prefix_stripped(self):
        prompt = "What is the meaning of life and everything?"
        records = [
            _gemini_record(f"Prompted {prompt}", f"<p>{_LONG}</p>", "2026-01-01T10:00:00Z")
        ]
        conv = parse_gemini_export(_gemini_export(records))[0]
        user_turn = next(t for t in conv.turns if t.role == "user")
        assert user_turn.text == prompt

    def test_empty_input(self):
        convs = parse_gemini_export(_gemini_export([]))
        assert convs == []

    def test_sorts_ascending_by_time(self):
        """Newest-first input (as Google exports) is sorted to chronological order."""
        records = [
            _gemini_record(f"Prompted second {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:10:00Z"),
            _gemini_record(f"Prompted first {_LONG}", f"<p>{_LONG}</p>", "2026-01-01T10:00:00Z"),
        ]
        convs = parse_gemini_export(_gemini_export(records))
        # Both within 30 min → one cluster; title = first prompt (earliest time)
        assert len(convs) == 1
        assert "first" in convs[0].title


# ================================================================== #
# 6. run_one_batch — dedup skip                                      #
# ================================================================== #

_BATCH_ENV = {
    "TELEGRAM_ALLOWED_USER_IDS": "12345",
    "CHAT_LOGS_BUCKET": "fake-bucket",
    "NOTION_AI_CHAT_DB_ID": "fake-notion-db-id",
    "GCP_PROJECT_ID": "fake-project",
}


def _make_gcs_mock(blobs: list):
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = blobs
    mock_client.bucket.return_value = mock_bucket
    mock_storage = MagicMock()
    mock_storage.Client.return_value = mock_client
    mock_gcs_module = MagicMock()
    mock_gcs_module.Client = mock_storage.Client
    mock_cloud_module = MagicMock()
    mock_cloud_module.storage = mock_gcs_module
    mock_google_module = MagicMock()
    mock_google_module.cloud = mock_cloud_module
    return mock_google_module, mock_cloud_module, mock_gcs_module


def _make_claude_ai_zip_blob(name: str, generation: int = 1) -> MagicMock:
    """Blob that contains a valid Claude.ai zip with one conversation."""
    convs = [_claude_ai_conv()]
    zip_bytes = _make_zip({"conversations.json": json.dumps(convs).encode()})
    blob = MagicMock()
    blob.name = name
    blob.generation = generation
    blob.download_as_bytes.return_value = zip_bytes
    return blob


class TestRunOneBatchDedup:
    def _run(self, blobs, initial_state: dict):
        mock_google, mock_cloud, mock_gcs = _make_gcs_mock(blobs)
        mock_store = MagicMock()
        mock_store.upsert_chat_chunks.return_value = 0

        with patch.dict("os.environ", _BATCH_ENV), \
             patch("core.chat_export_ingest._get_state", return_value=initial_state), \
             patch("core.chat_export_ingest._set_state"), \
             patch("core.chat_export_ingest._get_memory_store", return_value=mock_store), \
             patch("core.chat_export_ingest.summarize_conversation", return_value=("title", "summary", [])), \
             patch.dict(
                 sys.modules,
                 {
                     "google": mock_google,
                     "google.cloud": mock_cloud,
                     "google.cloud.storage": mock_gcs,
                     "mcp_tools.notion_tool": MagicMock(
                         build_ai_chat_properties=MagicMock(return_value={}),
                         upsert_database_row=MagicMock(),
                     ),
                 },
             ):
            from core.chat_export_ingest import run_one_batch
            return run_one_batch(), mock_store

    def test_fresh_blob_is_processed(self):
        blob = _make_claude_ai_zip_blob("chat-exports/claude_ai/export.zip", generation=1)
        result, mock_store = self._run([blob], {})
        assert result["ok"] is True
        assert result["processed"] == 1
        assert mock_store.upsert_chat_chunks.called

    def test_conversation_already_processed_is_skipped(self):
        """If conv session_id → update_marker is already in state, skip re-embedding."""
        blob = _make_claude_ai_zip_blob("chat-exports/claude_ai/export.zip", generation=1)
        # Pre-load state with the conversation already processed
        state = {"conversations": {"conv-1": "2026-01-01T10:05:00Z"}}
        result, mock_store = self._run([blob], state)
        assert result["ok"] is True
        assert result["processed"] == 0
        assert not mock_store.upsert_chat_chunks.called

    def test_completed_blob_is_skipped(self):
        """If blob.name → generation already in completed_blobs, skip download entirely."""
        blob = _make_claude_ai_zip_blob("chat-exports/claude_ai/export.zip", generation=5)
        state = {"completed_blobs": {"chat-exports/claude_ai/export.zip": "5"}}
        result, mock_store = self._run([blob], state)
        assert result["processed"] == 0
        assert not mock_store.upsert_chat_chunks.called


# ================================================================== #
# 7. run_one_batch — batch limit                                      #
# ================================================================== #

class TestRunOneBatchBatchLimit:
    def _run_multi(self, n_blobs: int, batch_max: int):
        blobs = [
            _make_claude_ai_zip_blob(f"chat-exports/claude_ai/export-{i}.zip", i)
            for i in range(n_blobs)
        ]
        mock_google, mock_cloud, mock_gcs = _make_gcs_mock(blobs)
        mock_store = MagicMock()
        mock_store.upsert_chat_chunks.return_value = 0
        env = {**_BATCH_ENV, "CHAT_EXPORT_BATCH_MAX_CONVERSATIONS": str(batch_max)}

        with patch.dict("os.environ", env), \
             patch("core.chat_export_ingest._get_state", return_value={}), \
             patch("core.chat_export_ingest._set_state"), \
             patch("core.chat_export_ingest._get_memory_store", return_value=mock_store), \
             patch("core.chat_export_ingest.summarize_conversation", return_value=("title", "summary", [])), \
             patch.dict(
                 sys.modules,
                 {
                     "google": mock_google,
                     "google.cloud": mock_cloud,
                     "google.cloud.storage": mock_gcs,
                     "mcp_tools.notion_tool": MagicMock(
                         build_ai_chat_properties=MagicMock(return_value={}),
                         upsert_database_row=MagicMock(),
                     ),
                 },
             ):
            from core.chat_export_ingest import run_one_batch
            return run_one_batch()

    def test_batch_limit_respected(self):
        result = self._run_multi(n_blobs=5, batch_max=3)
        assert result["ok"] is True
        assert result["processed"] <= 3


# ================================================================== #
# 8. run_one_batch — error isolation                                  #
# ================================================================== #

class TestRunOneBatchErrorIsolation:
    def test_bad_blob_does_not_crash_batch(self):
        good_blob = _make_claude_ai_zip_blob("chat-exports/claude_ai/good.zip", 1)
        bad_blob = MagicMock()
        bad_blob.name = "chat-exports/claude_ai/bad.zip"
        bad_blob.generation = 2
        bad_blob.download_as_bytes.side_effect = RuntimeError("GCS error")

        blobs = [bad_blob, good_blob]
        mock_google, mock_cloud, mock_gcs = _make_gcs_mock(blobs)
        mock_store = MagicMock()
        mock_store.upsert_chat_chunks.return_value = 0

        with patch.dict("os.environ", _BATCH_ENV), \
             patch("core.chat_export_ingest._get_state", return_value={}), \
             patch("core.chat_export_ingest._set_state"), \
             patch("core.chat_export_ingest._get_memory_store", return_value=mock_store), \
             patch("core.chat_export_ingest.summarize_conversation", return_value=("title", "summary", [])), \
             patch.dict(
                 sys.modules,
                 {
                     "google": mock_google,
                     "google.cloud": mock_cloud,
                     "google.cloud.storage": mock_gcs,
                     "mcp_tools.notion_tool": MagicMock(
                         build_ai_chat_properties=MagicMock(return_value={}),
                         upsert_database_row=MagicMock(),
                     ),
                 },
             ):
            from core.chat_export_ingest import run_one_batch
            result = run_one_batch()

        assert result["ok"] is True
        assert result["processed"] == 1  # good blob processed despite bad blob


# ================================================================== #
# 9. _locate_json                                                     #
# ================================================================== #

class TestLocateJson:
    def test_claude_ai_finds_conversations_json(self):
        import io, zipfile
        from core.chat_export_ingest import _locate_json
        zip_bytes = _make_zip({"conversations.json": b'[]'})
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        result = _locate_json(zf, "claude_ai")
        assert result == b'[]'

    def test_gemini_finds_myactivity_json(self):
        import io, zipfile
        from core.chat_export_ingest import _locate_json
        zip_bytes = _make_zip({
            "Takeout/My Activity/Gemini Apps/MyActivity.json": b'[]'
        })
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        result = _locate_json(zf, "gemini")
        assert result == b'[]'

    def test_missing_file_returns_none(self):
        import io, zipfile
        from core.chat_export_ingest import _locate_json
        zip_bytes = _make_zip({"other.txt": b"irrelevant"})
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        result = _locate_json(zf, "claude_ai")
        assert result is None
