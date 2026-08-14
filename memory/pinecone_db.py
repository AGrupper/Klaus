"""Pinecone-backed long-term memory store.

Stores durable facts and contextual chunks about the user as vector
embeddings (Gemini gemini-embedding-2 truncated to 768-dim) for semantic search.

Three active kinds of memory:
  "fact"  — short atomic statement ("Amit's gym is Mon/Wed/Fri").
  "chunk" — longer contextual passage (a story, evolving situation).
  "self"  — journal/self-memory entry written by Claude's nightly routine.

Existing archived chat vectors remain in the index but have no runtime read or
write path. Active memories are distinguished by the
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
_VALID_KINDS = frozenset({"fact", "chunk", "self"})
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DAILY_REQUEST_LIMIT = 200


class EmbeddingQuotaExceeded(RuntimeError):
    """Raised before provider invocation when usage cannot be reserved."""


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

    def __init__(
        self,
        api_key: str,
        index_name: str,
        *,
        embedding_usage_store=None,
    ) -> None:
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
        self._embedding_usage_store = embedding_usage_store

    # ------------------------------------------------------------------ #
    # Public interface                                                   #
    # ------------------------------------------------------------------ #

    def remember(self, user_id: int, content: str, kind: str) -> str:
        """Embed and store a memory.

        Args:
            user_id: Canonical Klaus user ID used to isolate and meter memory.
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

        vector = self._embed(content, user_id=user_id)
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
                     (archived imports are excluded from curated memory recall).

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
        vector = self._embed(query, user_id=user_id)
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
            user_id:  Canonical Klaus user ID (scopes the vector to one user).
            date_str: YYYY-MM-DD date string — forms the deterministic vector
                      ID ``self-{date_str}``.
            content:  Text to embed (typically summary + highlights). Truncated
                      to CONTENT_MAX_CHARS if longer.

        Returns:
            The deterministic Pinecone vector ID ``self-{date_str}``.
        """
        if len(content) > CONTENT_MAX_CHARS:
            content = content[:CONTENT_MAX_CHARS]
        vector = self._embed(content, user_id=user_id)
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

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _get_index(self):
        if self._index is None:
            from pinecone import Pinecone
            pc = Pinecone(api_key=self._api_key)
            self._index = pc.Index(self._index_name)
        return self._index

    def _embed(self, text: str, *, user_id: str | int | None = None) -> list[float]:
        """Reserve quota, then embed with the sole approved Gemini model."""
        canonical_user = str(user_id or os.environ.get("KLAUS_USER_ID", "")).strip()
        if not canonical_user:
            raise EmbeddingQuotaExceeded(
                "Embedding quota unavailable: KLAUS_USER_ID is not configured"
            )
        usage_store = self._get_embedding_usage_store()
        try:
            reserved = usage_store.reserve(
                canonical_user,
                limit=EMBEDDING_DAILY_REQUEST_LIMIT,
            )
        except Exception as exc:
            raise EmbeddingQuotaExceeded(
                "Embedding quota unavailable; provider call was blocked"
            ) from exc
        if not reserved:
            raise EmbeddingQuotaExceeded(
                f"Embedding daily request limit ({EMBEDDING_DAILY_REQUEST_LIMIT}) reached"
            )

        from google.genai import types
        client = self._get_genai()
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        self._record_embedding_usage(
            response,
            user_id=canonical_user,
            item_count=1,
        )
        return list(response.embeddings[0].values)

    def _record_embedding_usage(
        self,
        response,
        *,
        user_id: str | int,
        item_count: int,
    ) -> None:
        """Best-effort meter using provider-reported tokens and an operator rate."""
        try:
            metadata = getattr(response, "usage_metadata", None)
            token_value = getattr(metadata, "prompt_token_count", None)
            if not isinstance(token_value, (int, float)):
                token_value = getattr(metadata, "total_token_count", 0)
            input_tokens = int(token_value) if isinstance(token_value, (int, float)) else 0
            per_million = float(
                os.environ.get("GEMINI_EMBEDDING_COST_PER_MILLION_TOKENS", "0")
            )
            cost_usd = input_tokens * per_million / 1_000_000
            self._get_embedding_usage_store().record(
                user_id=user_id,
                input_tokens=input_tokens,
                item_count=item_count,
                cost_usd=cost_usd,
            )
        except Exception:
            logger.warning("Could not record Gemini embedding usage", exc_info=True)

    def _get_embedding_usage_store(self):
        """Build the persisted ledger lazily without network I/O at import."""
        if self._embedding_usage_store is None:
            from memory.firestore_db import EmbeddingUsageStore

            self._embedding_usage_store = EmbeddingUsageStore(
                os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
                os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
            )
        return self._embedding_usage_store

    def _get_genai(self):
        if self._genai is None:
            from google import genai
            api_key = os.environ.get("GEMINI_EMBEDDING_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "GEMINI_EMBEDDING_API_KEY is required for Gemini embeddings"
                )
            self._genai = genai.Client(api_key=api_key)
        return self._genai
