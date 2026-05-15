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

    def recall(self, user_id: int, query: str, k: int = 5) -> dict:
        """Search long-term memory and return matches.

        Args:
            user_id: Only return memories for this user.
            query:   Natural language search query.
            k:       Number of results (default 5, max 10).

        Returns:
            {"matches": [...], "count": int} or {"error": str, "query": str}
        """
        try:
            matches = self._store.recall(user_id, query, k)
        except Exception as exc:
            logger.error("MemoryTool.recall failed: %s", exc)
            return {"error": str(exc), "query": query}

        return {"matches": matches, "count": len(matches)}

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
