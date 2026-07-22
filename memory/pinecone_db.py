"""Pinecone-backed long-term memory store.

Stores durable facts and contextual chunks about the user as vector
embeddings (Gemini gemini-embedding-2 truncated to 768-dim) for semantic search.

Four kinds of memory:
  "fact"  — short atomic statement ("Amit's gym is Mon/Wed/Fri").
  "chunk" — longer contextual passage (a story, evolving situation).
  "chat"  — ingested Claude Code chat-log chunk (Phase 12+).
  "self"  — journal/self-memory entry written by the reflection cron (Phase 17).

All four are stored in the same serverless index, distinguished by the
"kind" metadata field. `recall` queries fact/chunk by default and returns
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
_VALID_KINDS = frozenset({"fact", "chunk", "chat", "self"})  # D-06: "self" added Phase 17


def _blend_recency(cosine: float, ts: str | None) -> float:
    """Scale a cosine score by a bounded exponential age decay.

    ``final = cosine * ((1 - W) + W * 0.5^(age_days / half_life))`` — a brand
    new memory keeps its full score; an infinitely old one keeps (1 - W) of
    it. Memories without a parseable ``ts`` (pre-Phase-17 vectors) get no
    penalty, so old curated facts are never buried by the upgrade.
    """
    if not ts:
        return cosine
    try:
        age_days = (
            datetime.now(tz=timezone.utc) - datetime.fromisoformat(ts)
        ).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return cosine
    age_days = max(0.0, age_days)
    decay = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
    return cosine * ((1.0 - _RECENCY_WEIGHT) + _RECENCY_WEIGHT * decay)

# Texts per Gemini embed_content call — also matches Pinecone's recommended
# upsert batch size, so one embed round-trip feeds one upsert slice.
_EMBED_BATCH_SIZE = 100

# Recency re-ranking (recall): pure cosine ranking surfaces a 2-year-old fact
# over yesterday's if the wording matches, so recall over-fetches and blends
# in a mild exponential age decay. The weight bounds recency's influence —
# it can scale a score by at most _RECENCY_WEIGHT (30%), so a strongly
# relevant old memory still beats a weakly relevant fresh one.
_RECENCY_HALF_LIFE_DAYS = 90
_RECENCY_WEIGHT = 0.3

# Phase 32 (Plan 06, MEM-01): ambient auto-recall score floor. A candidate
# whose BLENDED (post-recency-decay) score falls below this is excluded from
# the involuntary "Things you remember" surface — a marginal cosine match
# auto-injected into every turn is noisier than useful. The deliberate
# `recall()` tool call stays unthresholded (D-03): a marginal match is still
# useful when Amit/Klaus explicitly asks to search memory.
# [ASSUMED] tunable — re-tune from the raw (score, was_injected) debug log
# once real production score distributions are available (first weeks live).
AMBIENT_MIN_SCORE = 0.5


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
                f"kind must be one of {sorted(_VALID_KINDS)!r}, got {kind!r}."
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

    def recall(self, user_id: int, query: str, k: int = 5, kinds: list[str] | None = None) -> list[dict]:
        """Search memories for query, scoped to user_id.

        Args:
            user_id: Only return memories belonging to this user.
            query:   Natural language search query.
            k:       Number of results to return (clamped to 10).
            kinds:   If provided, filter results to only these memory kinds.
                     If None (default), returns only "fact" and "chunk" memories
                     (chat chunks excluded to avoid polluting curated memory recall).

        Returns:
            List of dicts: [{"kind", "content", "score", "ts"}, ...]
            sorted by descending blended score (cosine similarity scaled by a
            mild recency decay — see _blend_recency). UNTHRESHOLDED (D-03) —
            a deliberate tool call can still surface a marginal match; see
            `recall_ambient` for the score-floored auto-inject path.
        """
        k = min(k, 10)
        ranked = self._rank_candidates(user_id, query, k, kinds)
        return ranked[:k]

    def recall_ambient(
        self, user_id: int, query: str, k: int = 5,
        min_score: float = AMBIENT_MIN_SCORE, kinds: list[str] | None = None,
    ) -> list[dict]:
        """Score-thresholded recall for involuntary, every-turn auto-inject (MEM-01).

        Identical ranking to `recall()`, but candidates whose BLENDED score
        falls below `min_score` are excluded before slicing to `k` — a weak
        match auto-surfaced into every chat turn is noise, not memory. The
        deliberate `recall()` tool call is intentionally left unthresholded
        (D-03: two different needs) so this is a separate method, not a
        `recall(..., min_score=...)` param that would change tool behavior.

        Args:
            user_id:   Only return memories belonging to this user.
            query:     Natural language search query (the live user message).
            k:         Max number of results to return (clamped to 10).
            min_score: Blended-score floor — see `AMBIENT_MIN_SCORE`.
            kinds:     Same as `recall()`.

        Returns:
            List of dicts (same shape as `recall()`), score >= min_score only,
            sorted by descending blended score, at most k entries.
        """
        k = min(k, 10)
        ranked = self._rank_candidates(user_id, query, k, kinds)
        # Debug-log the raw (score, was_injected) pairs so the min_score floor
        # can be re-tuned from real production data (research recommendation).
        for r in ranked:
            logger.debug(
                "ambient recall candidate: score=%.4f min_score=%.2f was_injected=%s",
                r["score"], min_score, r["score"] >= min_score,
            )
        return [r for r in ranked if r["score"] >= min_score][:k]

    def _rank_candidates(
        self, user_id: int, query: str, k: int, kinds: list[str] | None,
    ) -> list[dict]:
        """Shared over-fetch + recency-blend ranking used by recall/recall_ambient.

        Returns ALL ranked candidates (not sliced to k) so callers can apply
        their own post-filter (e.g. recall_ambient's score floor) before
        truncating — filtering after slicing would silently return fewer
        than k results even when qualifying candidates exist further down
        the over-fetched list.
        """
        _kinds = kinds if kinds is not None else ["fact", "chunk"]
        vector = self._embed(query)
        result = self._get_index().query(
            vector=vector,
            # Over-fetch so the recency re-rank has candidates to promote —
            # the freshest relevant memory may sit just below the raw top-k.
            top_k=max(20, k * 2),
            # WHY $eq filter: ensures memories from other users are never
            # returned even if the index grows to multiple users later.
            filter={"user_id": {"$eq": str(user_id)}, "kind": {"$in": _kinds}},
            include_metadata=True,
        )
        ranked = [
            {
                "kind": m.metadata.get("kind"),
                "content": m.metadata.get("content"),
                "score": round(_blend_recency(float(m.score), m.metadata.get("ts")), 4),
                "ts": m.metadata.get("ts"),
            }
            for m in result.matches
        ]
        ranked.sort(key=lambda r: r["score"], reverse=True)
        return ranked

    def remember_self(self, user_id: int, date_str: str, content: str) -> str:
        """Upsert a journal entry with a deterministic vector ID (self-{date}).

        A re-run for the same date overwrites the existing vector — no
        duplicates (D-07/D-12). Truncates content over CONTENT_MAX_CHARS
        rather than raising (Pitfall 2 — unlike remember() which raises).

        metadata.user_id is set to str(user_id), identical to remember()'s
        format, so recall()'s $eq user filter isolates journal vectors per
        owner (Security Domain: cross-user leak mitigation).

        Args:
            user_id:  Telegram user ID (scopes the vector to one user).
            date_str: YYYY-MM-DD date string — forms the deterministic vector
                      ID ``self-{date_str}``.
            content:  Text to embed (typically summary + highlights). Truncated
                      to CONTENT_MAX_CHARS if longer.

        Returns:
            The deterministic Pinecone vector ID ``self-{date_str}``.
        """
        if len(content) > CONTENT_MAX_CHARS:
            content = content[:CONTENT_MAX_CHARS]
        vector = self._embed(content)
        vector_id = f"self-{date_str}"
        ts = datetime.now(tz=timezone.utc).isoformat()
        self._get_index().upsert(vectors=[{
            "id": vector_id,
            "values": vector,
            "metadata": {
                "user_id": str(user_id),
                "kind": "self",
                "content": content,
                "ts": ts,
            },
        }])
        return vector_id

    def upsert_chat_chunks(self, user_id: int, chunks: list[dict]) -> int:
        """Embed and upsert a batch of chat chunks to Pinecone.

        Each chunk dict must have:
          - "id": deterministic vector ID (e.g. "cc-{session_id}-{uuid}-{n}")
          - "content": text to embed
          - "metadata": dict with kind="chat" and other metadata fields

        Args:
            user_id: Telegram user ID (injected into each chunk's metadata).
            chunks:  List of chunk dicts from _chunk_conversation.

        Returns:
            Number of vectors upserted.
        """
        if not chunks:
            return 0

        # Embed in batches — one API round-trip per _EMBED_BATCH_SIZE texts
        # instead of one call (plus a rate-limit sleep) per chunk. The old
        # per-chunk 500ms sleep made a 100-chunk file take ~50s, blowing the
        # chat-ingest cron's 45s time budget; batching brings it to one call.
        contents = [chunk["content"] for chunk in chunks]
        embeddings: list[list[float]] = []
        for i in range(0, len(contents), _EMBED_BATCH_SIZE):
            embeddings.extend(self._embed_batch(contents[i : i + _EMBED_BATCH_SIZE]))

        vectors = []
        for chunk, vector in zip(chunks, embeddings):
            meta = dict(chunk.get("metadata", {}))
            meta["user_id"] = str(user_id)
            meta.setdefault("kind", "chat")
            meta["content"] = chunk["content"]
            vectors.append({
                "id": chunk["id"],
                "values": vector,
                "metadata": meta,
            })

        # Upsert in slices of 100 (Pinecone recommended batch size)
        index = self._get_index()
        for i in range(0, len(vectors), 100):
            index.upsert(vectors=vectors[i : i + 100])

        logger.debug("Upserted %d chat chunk(s) for user_id=%d.", len(vectors), user_id)
        return len(vectors)

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

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts in a single Gemini API call.

        Returns one 768-dim embedding per input text, in order. Callers
        slice to _EMBED_BATCH_SIZE.

        WHY explicit Content objects: google-genai coerces a plain
        ``list[str]`` into ONE multi-part content and returns a single
        embedding for the whole batch (verified live against SDK 2.8.0).
        Wrapping each text in its own ``types.Content`` is what makes the
        API treat them as separate inputs.
        """
        from google.genai import types
        client = self._get_genai()
        response = client.models.embed_content(
            model="gemini-embedding-2",
            contents=[
                types.Content(parts=[types.Part(text=text)]) for text in texts
            ],
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return [list(e.values) for e in response.embeddings]

    def _get_genai(self):
        if self._genai is None:
            from google import genai
            # WHY SMART_AGENT_API_KEY: embeddings use Gemini (Google AI Studio).
            # The worker key is now DeepSeek, so we source the Gemini key
            # from the smart agent (which is still a Google model).
            api_key = os.environ["SMART_AGENT_API_KEY"]
            self._genai = genai.Client(api_key=api_key)
        return self._genai
