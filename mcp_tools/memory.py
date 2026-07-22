"""Long-term memory MCP tool.

Thin agent-facing wrapper over `memory.pinecone_db.MemoryStore`.
Exposes `remember` and `recall` to the orchestrator's tool dispatch layer.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MemoryTool:
    """Agent-facing tool for reading and writing long-term memory."""

    def __init__(self, memory_store: object) -> None:
        """
        Args:
            memory_store: A `memory.pinecone_db.MemoryStore` instance.
        """
        self._store = memory_store

    def remember(self, user_id: int, content: str, kind: str) -> dict:
        """Store a memory and return a confirmation dict.

        Args:
            user_id: Telegram user ID.
            content: Text to store (max 2000 chars).
            kind:    "fact" or "chunk".

        Returns:
            Success: {"vector_id", "content", "kind", "confirmation"}
            Failure: {"error", "content"}
        """
        try:
            vector_id = self._store.remember(user_id, content, kind)
        except (ValueError, Exception) as exc:
            logger.error("MemoryTool.remember failed: %s", exc)
            return {"error": str(exc), "content": content}

        preview = content[:80] + ("…" if len(content) > 80 else "")
        return {
            "vector_id": vector_id,
            "content": content,
            "kind": kind,
            "confirmation": f"Saved {kind}: {preview}",
        }

    def recall(self, user_id: int, query: str, k: int = 5,
               kinds: list[str] | None = None) -> dict:
        """Search long-term memory and return matches.

        Args:
            user_id: Only return memories for this user.
            query:   Natural language search query.
            k:       Number of results (default 5, max 10).
            kinds:   Optional list of memory kinds to restrict search.
                     None defaults to ["fact", "chunk"] (default recall behavior).

        Returns:
            {"matches": [...], "count": int} or {"error": str, "query": str}
        """
        try:
            matches = self._store.recall(user_id, query, k, kinds=kinds)
        except Exception as exc:
            logger.error("MemoryTool.recall failed: %s", exc)
            return {"error": str(exc), "query": query}

        return {"matches": matches, "count": len(matches)}

    def forget_memory(self, vector_id: str) -> dict:
        """Deliberately hard-delete one stored memory by its Pinecone vector id.

        Amit's explicit "forget that" trigger (MEM-03, D-04) — the ONLY way a
        memory is removed. There is no auto-decay and no soft-delete/tombstone
        scheme; Pinecone's native `index.delete(ids=[...])` is the deliberate
        deletion mechanism (Don't Hand-Roll).

        Args:
            vector_id: The Pinecone vector id of the memory to delete.

        Returns:
            Success: {"ok": True, "vector_id": vector_id}
            Failure: {"ok": False, "error": ...} — never raises (ASVS V5).
        """
        if not isinstance(vector_id, str) or not vector_id.strip():
            return {"ok": False, "error": "vector_id must be a non-empty string."}

        try:
            self._store._get_index().delete(ids=[vector_id])
        except Exception as exc:
            logger.error("MemoryTool.forget_memory failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "vector_id": vector_id}

    def search_chat_history(self, user_id: int, query: str, k: int = 5, project: str | None = None) -> dict:
        """Search ingested Claude Code chat history via semantic similarity.

        Args:
            user_id: Telegram user ID.
            query:   Natural language search query.
            k:       Number of results (default 5, max 10).
            project: Optional project path filter (e.g. "/Users/amit/Desktop/Klaus").

        Returns:
            {"matches": [...], "count": int} or {"error": str, "query": str}
        """
        try:
            matches = self._store.recall(user_id, query, k, kinds=["chat"])
            if project:
                matches = [m for m in matches if project.lower() in (m.get("content") or "").lower()]
            return {"matches": matches, "count": len(matches)}
        except Exception as exc:
            logger.error("MemoryTool.search_chat_history failed: %s", exc)
            return {"error": str(exc), "query": query}
