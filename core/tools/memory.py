"""Long-term semantic memory, backed by Pinecone.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.tools.registry import tool
from core.tools.state import _get_current_user_id

logger = logging.getLogger(__name__)

# Lazy singletons — see core/tools/calendar.py for why they are not built at
# import time.
from memory.pinecone_db import MemoryStore  # noqa: E402
from mcp_tools.memory import MemoryTool  # noqa: E402

_memory_store: MemoryStore | None = None
_memory_tool: MemoryTool | None = None


def _get_memory_store() -> MemoryStore:
    """Return the shared MemoryStore instance, building it on first call."""
    global _memory_store
    if _memory_store is None:
        api_key = os.environ["PINECONE_API_KEY"]
        index_name = os.getenv("PINECONE_INDEX_NAME", "klaus-memory")
        _memory_store = MemoryStore(api_key=api_key, index_name=index_name)
    return _memory_store


def _get_memory_tool() -> MemoryTool:
    """Return the shared MemoryTool instance, building it on first call."""
    global _memory_tool
    if _memory_tool is None:
        _memory_tool = MemoryTool(memory_store=_get_memory_store())
    return _memory_tool


@tool({
        "name": "remember",
        "description": (
            "Save a durable piece of information about the user to long-term memory. "
            "Available through Claude MCP. "
            "Use kind='fact' for short atomic statements (preferred). "
            "Use kind='chunk' for longer contextual passages where the narrative "
            "or emotional thread matters more than a single statement. "
            "Content cap: 2000 characters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to store. Max 2000 characters.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["fact", "chunk"],
                    "description": (
                        "'fact': short atomic statement e.g. 'Amit's gym is Mon/Wed/Fri'. "
                        "'chunk': longer contextual passage (a story, evolving situation). "
                        "Prefer 'fact' when in doubt."
                    ),
                },
            },
            "required": ["content", "kind"],
        },
    })
def _handle_remember(content: str, kind: str) -> str:
    """Delegate to MemoryTool.remember and serialise the result."""
    result = _get_memory_tool().remember(_get_current_user_id(), content, kind)
    return json.dumps(result)


@tool({
        "name": "recall",
        "description": (
            "Search long-term memory for information relevant to a query. "
            "Available through Claude MCP. "
            "Returns top-k matches across facts and chunks, ranked by semantic "
            "similarity. Call proactively before asking the user clarifying questions "
            "about their preferences or history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10).",
                },
                "kind": {
                    "type": "string",
                    "enum": ["fact", "chunk", "self"],
                    "description": (
                        "Optional. Restrict recall to one memory kind. "
                        "'self' searches Klaus's own journal entries. "
                        "Omit for the default fact+chunk search."
                    ),
                },
            },
            "required": ["query"],
        },
    })
def _handle_recall(query: str, k: int = 5, kind: str | None = None) -> str:
    """Delegate to MemoryTool.recall and serialise the result."""
    kinds = [kind] if kind else None   # None → recall() default ["fact","chunk"]
    result = _get_memory_tool().recall(_get_current_user_id(), query, k, kinds=kinds)
    return json.dumps(result)


@tool({
        "name": "forget_memory",
        "description": (
            "Deliberately and permanently delete one stored memory by its vector id — "
            "Amit's explicit 'forget that' trigger (MEM-03). "
            "This is a hard delete with no undo. Only call when "
            "Amit has clearly asked to forget or correct a specific stored fact — e.g. "
            "after a `recall` surfaced it and Amit disputes it, or the nightly review "
            "flagged a `memory_contradiction` and Amit confirmed the drop. Never call "
            "speculatively or without an explicit trigger."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vector_id": {
                    "type": "string",
                    "description": (
                        "The Pinecone vector id of the memory to delete — returned by a "
                        "prior `remember`/`recall` call, or surfaced as `vector_id` in a "
                        "nightly memory_contradiction flag."
                    ),
                },
            },
            "required": ["vector_id"],
        },
    })
def _handle_forget_memory(vector_id: str) -> str:
    """Delegate to MemoryTool.forget_memory and serialise the result."""
    result = _get_memory_tool().forget_memory(vector_id)
    return json.dumps(result)
