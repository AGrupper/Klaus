"""Unit tests for MemoryStore.upsert_chat_chunks batched embedding (no live API).

The embed and Pinecone clients are mocked — these tests pin the batching
contract: one embed_content call per _EMBED_BATCH_SIZE chunk slice, vectors
zipped back to the right chunk ids/metadata, and no per-chunk rate-limit
sleeps (the old 500ms-per-chunk pattern blew the chat-ingest time budget).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from memory.pinecone_db import _EMBED_BATCH_SIZE, MemoryStore


def _make_store() -> tuple[MemoryStore, MagicMock]:
    """A MemoryStore with a mocked Pinecone index (no network)."""
    store = MemoryStore(api_key="fake", index_name="fake-index")
    index = MagicMock(name="pinecone-index")
    store._index = index
    return store, index


def _chunk(n: int) -> dict:
    return {
        "id": f"cc-session-{n}",
        "content": f"chunk content {n}",
        "metadata": {"kind": "chat", "session_id": "session"},
    }


class TestUpsertChatChunks:
    def test_empty_chunks_short_circuits(self):
        store, index = _make_store()
        assert store.upsert_chat_chunks(user_id=1, chunks=[]) == 0
        index.upsert.assert_not_called()

    def test_single_embed_call_for_small_batch(self):
        """N <= _EMBED_BATCH_SIZE chunks → exactly one embed round-trip."""
        store, index = _make_store()
        chunks = [_chunk(i) for i in range(5)]

        with patch.object(
            store, "_embed_batch", return_value=[[0.1] * 768 for _ in range(5)]
        ) as mock_embed:
            count = store.upsert_chat_chunks(user_id=42, chunks=chunks)

        assert count == 5
        mock_embed.assert_called_once_with([c["content"] for c in chunks])

    def test_slices_embed_calls_at_batch_size(self):
        """N > _EMBED_BATCH_SIZE chunks → ceil(N / batch) embed calls."""
        store, index = _make_store()
        n = _EMBED_BATCH_SIZE + 3
        chunks = [_chunk(i) for i in range(n)]

        with patch.object(
            store,
            "_embed_batch",
            side_effect=lambda texts: [[0.1] * 768 for _ in texts],
        ) as mock_embed:
            count = store.upsert_chat_chunks(user_id=42, chunks=chunks)

        assert count == n
        assert mock_embed.call_count == 2
        assert len(mock_embed.call_args_list[0].args[0]) == _EMBED_BATCH_SIZE
        assert len(mock_embed.call_args_list[1].args[0]) == 3

    def test_vectors_carry_chunk_ids_and_metadata(self):
        """Each upserted vector keeps its chunk's id and enriched metadata."""
        store, index = _make_store()
        chunks = [_chunk(0), _chunk(1)]

        with patch.object(
            store, "_embed_batch", return_value=[[0.1] * 768, [0.2] * 768]
        ):
            store.upsert_chat_chunks(user_id=42, chunks=chunks)

        index.upsert.assert_called_once()
        vectors = index.upsert.call_args.kwargs["vectors"]
        assert [v["id"] for v in vectors] == ["cc-session-0", "cc-session-1"]
        assert vectors[0]["values"] == [0.1] * 768
        assert vectors[1]["values"] == [0.2] * 768
        for i, v in enumerate(vectors):
            assert v["metadata"]["user_id"] == "42"
            assert v["metadata"]["kind"] == "chat"
            assert v["metadata"]["content"] == f"chunk content {i}"

    def test_no_sleep_in_upsert_path(self):
        """The per-chunk rate-limit sleep is gone for good."""
        store, index = _make_store()
        chunks = [_chunk(i) for i in range(3)]

        with patch.object(
            store, "_embed_batch", return_value=[[0.1] * 768 for _ in range(3)]
        ), patch("time.sleep") as mock_sleep:
            store.upsert_chat_chunks(user_id=1, chunks=chunks)

        mock_sleep.assert_not_called()


class TestEmbedBatch:
    def test_one_vector_per_text_in_order(self):
        store, _ = _make_store()

        def _embedding(values):
            e = MagicMock()
            e.values = values
            return e

        response = MagicMock()
        response.embeddings = [_embedding([0.1] * 768), _embedding([0.2] * 768)]
        genai_client = MagicMock()
        genai_client.models.embed_content.return_value = response
        store._genai = genai_client

        vectors = store._embed_batch(["text a", "text b"])

        assert vectors == [[0.1] * 768, [0.2] * 768]
        genai_client.models.embed_content.assert_called_once()
        # Each text must be its own Content object — a plain str list is
        # coerced by the SDK into ONE multi-part content (single embedding).
        contents = genai_client.models.embed_content.call_args.kwargs["contents"]
        assert len(contents) == 2
        assert contents[0].parts[0].text == "text a"
        assert contents[1].parts[0].text == "text b"
