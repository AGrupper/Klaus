"""Pinecone-backed vector memory (RAG).

Stores unstructured long-term memory — past conversations, extracted
preferences, recurring context — as embeddings for similarity search at
inference time (per `docs/TECHNICAL_PLAN.md` §1).

Stub only — implementation lands later than Phase 4.
"""
from __future__ import annotations


class PineconeMemory:
    """Vector store wrapper for the agent's long-term memory."""

    def __init__(self, api_key: str, index_name: str) -> None:
        self.api_key = api_key
        self.index_name = index_name

    def upsert(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        """Embed `text` and store it under `doc_id` with optional metadata."""
        raise NotImplementedError("stub — RAG phase")

    def query(self, text: str, top_k: int = 5) -> list[dict]:
        """Return up to `top_k` semantically similar memories."""
        raise NotImplementedError("stub — RAG phase")
