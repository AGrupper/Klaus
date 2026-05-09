"""Pinecone-backed long-term memory store.

Stores durable facts and contextual chunks about the user as vector
embeddings (Gemini gemini-embedding-2 truncated to 768-dim) for semantic search.

Two kinds of memory:
  "fact"  — short atomic statement ("Amit's gym is Mon/Wed/Fri").
  "chunk" — longer contextual passage (a story, evolving situation).

Both are stored in the same serverless index, distinguished by the
"kind" metadata field. `recall` queries both kinds together and returns
results ranked by semantic similarity.

Per-user isolation is enforced via a `user_id` metadata filter on every
query — memories from different users never mix.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CONTENT_MAX_CHARS = 2000
_VALID_KINDS = frozenset({"fact", "chunk"})


class MemoryStore:
    """Pinecone-backed vector memory with Gemini embeddings.

    Lazy-initialises both the Pinecone index and the Gemini embed client
    on first use so that importing this module never triggers network I/O.
    """

    def __init__(self, api_key: str, index_name: str) -> None:
        """
        Args:
            api_key:    Pinecone API key.
            index_name: Name of the pre-created serverless Pinecone index
                        (dimension=768, metric=cosine).
        """
        self._api_key = api_key
        self._index_name = index_name
        self._index = None   # lazy: Pinecone Index object
        self._genai = None   # lazy: google.genai Client

    # ------------------------------------------------------------------ #
    # Public interface                                                   #
    # ------------------------------------------------------------------ #

    def remember(self, user_id: int, content: str, kind: str) -> str:
        """Embed and store a memory.

        Args:
            user_id: Telegram user ID (used to scope the memory to one user).
            content: Text to store. Max CONTENT_MAX_CHARS characters.
            kind:    "fact" for atomic statements, "chunk" for longer passages.

        Returns:
            The Pinecone vector ID for the stored memory.

        Raises:
            ValueError: If kind is invalid or content exceeds the char cap.
        """
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"kind must be 'fact' or 'chunk', got {kind!r}."
            )
        if len(content) > CONTENT_MAX_CHARS:
            raise ValueError(
                f"content is {len(content)} chars — exceeds the {CONTENT_MAX_CHARS}-char "
                "limit. Summarise before saving."
            )

        vector = self._embed(content)
        vector_id = str(uuid.uuid4())
        ts = datetime.now(tz=timezone.utc).isoformat()

        self._get_index().upsert(vectors=[{
            "id": vector_id,
            "values": vector,
            "metadata": {
                "user_id": str(user_id),
                "kind": kind,
                "content": content,
                "ts": ts,
            },
        }])
        logger.debug("Stored %s memory (id=%s) for user_id=%d.", kind, vector_id, user_id)
        return vector_id

    def recall(self, user_id: int, query: str, k: int = 5) -> list[dict]:
        """Search memories for query, scoped to user_id.

        Args:
            user_id: Only return memories belonging to this user.
            query:   Natural language search query.
            k:       Number of results to return (clamped to 10).

        Returns:
            List of dicts: [{"kind", "content", "score", "ts"}, ...]
            sorted by descending similarity score.
        """
        k = min(k, 10)
        vector = self._embed(query)
        result = self._get_index().query(
            vector=vector,
            top_k=k,
            # WHY $eq filter: ensures memories from other users are never
            # returned even if the index grows to multiple users later.
            filter={"user_id": {"$eq": str(user_id)}},
            include_metadata=True,
        )
        return [
            {
                "kind": m.metadata.get("kind"),
                "content": m.metadata.get("content"),
                "score": round(float(m.score), 4),
                "ts": m.metadata.get("ts"),
            }
            for m in result.matches
        ]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _get_index(self):
        if self._index is None:
            from pinecone import Pinecone
            pc = Pinecone(api_key=self._api_key)
            self._index = pc.Index(self._index_name)
        return self._index

    def _embed(self, text: str) -> list[float]:
        """Embed text using Gemini gemini-embedding-2 truncated to 768-dim."""
        from google.genai import types
        client = self._get_genai()
        response = client.models.embed_content(
            model="gemini-embedding-2",
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return list(response.embeddings[0].values)

    def _get_genai(self):
        if self._genai is None:
            from google import genai
            # WHY: reuse the Worker Agent API key — same Gemini key already
            # provisioned in both local .env and Cloud Run Secret Manager.
            api_key = os.environ["WORKER_AGENT_API_KEY"]
            self._genai = genai.Client(api_key=api_key)
        return self._genai
