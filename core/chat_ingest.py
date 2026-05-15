# core/chat_ingest.py
"""Claude Code chat-log ingestion pipeline.

Parses ~/.claude/projects/**/*.jsonl files, embeds and upserts chunks to
Pinecone, summarises each session, and writes one Notion row per conversation.

Cloud Scheduler fires POST /cron/ingest-chats daily at 04:00 Asia/Jerusalem.
Each tick processes up to BATCH_MAX_FILES files within BATCH_TIME_BUDGET_SEC,
persisting progress in Firestore (chat_ingest/state) so the backlog drains
over multiple ticks (idempotent — generation-token dedup).

NOTE: user_id = first entry of TELEGRAM_ALLOWED_USER_IDS — single-user
system assumption. Klaus is not a multi-tenant product.

Local dry-run:
    python -m core.chat_ingest --dry-run --file ~/.claude/projects/.../foo.jsonl
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants                                                          #
# ------------------------------------------------------------------ #

MIN_TURN_CHARS = 12
CHUNK_MAX_CHARS = 1800
CHUNK_OVERLAP_CHARS = 200
BATCH_MAX_FILES = int(os.getenv("CHAT_INGEST_BATCH_MAX_FILES", "8"))
BATCH_TIME_BUDGET_SEC = int(os.getenv("CHAT_INGEST_TIME_BUDGET_SEC", "45"))
_COLLECTION = "chat_ingest"
_STATE_DOC = "state"
_GCS_PREFIX = "claude-code/"

# ------------------------------------------------------------------ #
# Dataclasses                                                        #
# ------------------------------------------------------------------ #

@dataclass
class Turn:
    uuid: str        # JSONL line UUID
    role: str        # "user" or "assistant"
    text: str        # cleaned text
    timestamp: str   # ISO string (may be empty)


@dataclass
class ParsedConversation:
    session_id: str
    title: str
    project: str          # decoded project path (e.g. "/Users/amit/Desktop/Klaus")
    machine_id: str       # "mac" or "pc", extracted from blob name prefix
    started_at: str
    ended_at: str
    turns: list[Turn] = field(default_factory=list)


# ------------------------------------------------------------------ #
# MemoryStore lazy singleton                                         #
# ------------------------------------------------------------------ #

_memory_store: "MemoryStore | None" = None  # type: ignore[name-defined]


def _get_memory_store():
    """Return (or lazily create) the MemoryStore singleton."""
    global _memory_store
    if _memory_store is None:
        from memory.pinecone_db import MemoryStore
        _memory_store = MemoryStore(
            api_key=os.environ["PINECONE_API_KEY"],
            index_name=os.getenv("PINECONE_INDEX_NAME", "Klaus-memory"),
        )
    return _memory_store


# ------------------------------------------------------------------ #
# Firestore helpers                                                  #
# ------------------------------------------------------------------ #

def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    return _mfc(os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)"))


def _get_state() -> dict:
    try:
        client = _make_firestore_client()
        snap = client.collection(_COLLECTION).document(_STATE_DOC).get()
        return snap.to_dict() or {} if snap.exists else {}
    except Exception:
        logger.warning("chat_ingest: failed to read state", exc_info=True)
        return {}


def _set_state(fields: dict) -> None:
    try:
        client = _make_firestore_client()
        client.collection(_COLLECTION).document(_STATE_DOC).set(fields, merge=True)
    except Exception:
        logger.warning("chat_ingest: failed to write state", exc_info=True)


# ------------------------------------------------------------------ #
# Path helpers                                                       #
# ------------------------------------------------------------------ #

def _decode_project_path(encoded: str) -> str:
    """Decode an encoded project directory name back to a filesystem path.

    The session file lives at ~/.claude/projects/{encoded}/{session_id}.jsonl.
    The encoded dir name is the project path with '/' replaced by '-'.
    We reverse that by replacing '-' with '/'.

    Edge cases:
    - Empty string → return as-is.
    - Already looks like a path (starts with '/') → return as-is.
    """
    if not encoded:
        return encoded
    if encoded.startswith("/"):
        return encoded
    # Replace leading '-' that represents the root '/' separator
    return encoded.replace("-", "/")


# ------------------------------------------------------------------ #
# Parsing                                                            #
# ------------------------------------------------------------------ #

def parse_claude_code_jsonl(
    blob_content: bytes,
    session_id: str,
    machine_id: str,
) -> ParsedConversation | None:
    """Parse a Claude Code JSONL session file into a ParsedConversation.

    Args:
        blob_content: Raw bytes of the .jsonl file.
        session_id:   Stem of the filename (used as fallback project decoder).
        machine_id:   "mac" or "pc" — extracted from the GCS blob path prefix.

    Returns:
        ParsedConversation if at least one valid turn was found, else None.
    """
    lines = blob_content.decode("utf-8", errors="replace").splitlines()

    turns: list[Turn] = []
    title: str | None = None
    project: str | None = None
    timestamps: list[str] = []

    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            logger.warning(
                "chat_ingest: malformed JSON line in session %s — skipping line",
                session_id,
            )
            continue

        obj_type = obj.get("type", "")

        # ---- Title extraction ----
        if obj_type == "ai-title":
            ai_title = obj.get("aiTitle")
            if ai_title:
                title = ai_title  # keep updating; last one wins
        elif obj_type == "last-prompt" and title is None:
            last_prompt = obj.get("lastPrompt", "")
            if last_prompt:
                title = last_prompt[:80]

        # ---- Project path ----
        if project is None and obj_type in ("user", "assistant"):
            cwd = obj.get("cwd")
            if cwd:
                project = cwd

        # ---- Turn extraction ----
        ts = obj.get("timestamp", "")

        if obj_type == "user":
            # Skip meta, sidechain, and tool-result turns
            if obj.get("isMeta") or obj.get("isSidechain"):
                continue
            if "toolUseResult" in obj:
                continue
            message = obj.get("message", {})
            content = message.get("content")
            if not isinstance(content, str):
                continue
            text = content.strip()
            if len(text) < MIN_TURN_CHARS:
                continue
            turn_uuid = obj.get("uuid", "")
            turns.append(Turn(uuid=turn_uuid, role="user", text=text, timestamp=ts))
            if ts:
                timestamps.append(ts)

        elif obj_type == "assistant":
            if obj.get("isSidechain"):
                continue
            message = obj.get("message", {})
            content = message.get("content")
            # content must be a list to join text blocks
            if not isinstance(content, list):
                continue
            text_parts = [
                block["text"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ]
            text = " ".join(text_parts).strip()
            if len(text) < MIN_TURN_CHARS:
                continue
            turn_uuid = obj.get("uuid", "")
            turns.append(Turn(uuid=turn_uuid, role="assistant", text=text, timestamp=ts))
            if ts:
                timestamps.append(ts)

    if not turns:
        return None

    # Fallback title
    if not title:
        title = "Claude Code session"

    # Fallback project
    if not project:
        project = _decode_project_path(session_id)

    # Timestamps
    started_at = min(timestamps) if timestamps else ""
    ended_at = max(timestamps) if timestamps else ""

    return ParsedConversation(
        session_id=session_id,
        title=title,
        project=project,
        machine_id=machine_id,
        started_at=started_at,
        ended_at=ended_at,
        turns=turns,
    )


# ------------------------------------------------------------------ #
# Chunking                                                           #
# ------------------------------------------------------------------ #

def _chunk_conversation(conv: ParsedConversation) -> list[dict]:
    """Slice conversation turns into embedding-ready chunks.

    Each chunk is prefixed with "[{title}] {role}: " so it carries context
    when retrieved in isolation from Pinecone.

    Returns a list of chunk dicts (user_id metadata is NOT filled here;
    run_one_batch injects it before calling upsert_chat_chunks).
    """
    _WINDOW = CHUNK_MAX_CHARS - CHUNK_OVERLAP_CHARS  # ~1600 chars of new content per window

    chunks: list[dict] = []

    for turn in conv.turns:
        prefix = f"[{conv.title}] {turn.role}: "
        prefixed = prefix + turn.text

        if len(prefixed) <= CHUNK_MAX_CHARS:
            chunks.append(_make_chunk(conv, turn, prefixed, 0))
        else:
            # Sliding-window split
            chunk_index = 0
            pos = 0
            while pos < len(prefixed):
                slice_text = prefixed[pos: pos + CHUNK_MAX_CHARS]
                chunks.append(_make_chunk(conv, turn, slice_text, chunk_index))
                chunk_index += 1
                pos += _WINDOW
                if pos >= len(prefixed):
                    break

    return chunks


def _make_chunk(
    conv: ParsedConversation,
    turn: Turn,
    content: str,
    chunk_index: int,
) -> dict:
    """Build a single chunk dict (without user_id — injected by caller)."""
    return {
        "id": f"cc-{conv.session_id}-{turn.uuid}-{chunk_index}",
        "content": content,
        "metadata": {
            # user_id is intentionally absent here; injected by run_one_batch
            "kind": "chat",
            "source": "claude_code",
            "machine_id": conv.machine_id,
            "project": conv.project,
            "conversation_id": conv.session_id,
            "conversation_title": conv.title,
            "role": turn.role,
            "ts": turn.timestamp,
        },
    }


# ------------------------------------------------------------------ #
# Summarisation                                                      #
# ------------------------------------------------------------------ #

def _summarize(conv: ParsedConversation) -> tuple[str, list[str]]:
    """Summarise a conversation via the Worker Agent LLM.

    Builds a role-prefixed transcript capped at ~12000 chars, calls the
    configured Flash model, and parses the JSON response.

    Returns:
        (summary_str, topics_list) — deterministic fallback on any error.
    """
    # Build transcript
    transcript_parts: list[str] = []
    total_chars = 0
    for turn in conv.turns:
        entry = f"{turn.role.upper()}: {turn.text[:600]}"
        if total_chars + len(entry) > 12000:
            break
        transcript_parts.append(entry)
        total_chars += len(entry)
    transcript = "\n\n".join(transcript_parts)

    # Load system prompt
    prompt_path = Path(__file__).parent.parent / "prompts" / "chat_summary.md"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("chat_ingest: chat_summary.md prompt missing — using inline fallback")
        system_prompt = (
            "Summarise the following Claude Code conversation in JSON: "
            '{"summary": "<one-paragraph summary>", "topics": ["<topic>", ...]}'
        )

    user_message = f"Conversation title: {conv.title}\n\n{transcript}"

    try:
        from core.llm_client import LLMClient
        client = LLMClient(
            backend=os.environ["WORKER_AGENT_BACKEND"],
            model=os.environ["WORKER_AGENT_MODEL"],
            api_key=os.environ["WORKER_AGENT_API_KEY"],
        )
        response = client.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
        )
        raw_text = (response.get("text") or "").strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        parsed = json.loads(raw_text)
        summary = str(parsed.get("summary", "")).strip()
        topics = [str(t) for t in parsed.get("topics", []) if t]
        if summary:
            return summary, topics
    except Exception:
        logger.warning(
            "chat_ingest: summarization failed for session %s",
            conv.session_id,
            exc_info=True,
        )

    # Deterministic fallback
    fallback_summary = "No summary available"
    for turn in conv.turns:
        if turn.role == "assistant" and turn.text:
            fallback_summary = turn.text[:200]
            break
    return fallback_summary, []


# ------------------------------------------------------------------ #
# Embedding helper (future use)                                      #
# ------------------------------------------------------------------ #

def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using the MemoryStore's embed method.

    Available for future use; run_one_batch doesn't call this directly
    because upsert_chat_chunks handles embedding internally.
    """
    store = _get_memory_store()
    return [store._embed(text) for text in texts]


# ------------------------------------------------------------------ #
# Batch runner                                                       #
# ------------------------------------------------------------------ #

def run_one_batch() -> dict:
    """Process a bounded batch of unprocessed JSONL blobs from GCS.

    Reads progress from Firestore, lists blobs in the configured bucket,
    and processes up to BATCH_MAX_FILES files within BATCH_TIME_BUDGET_SEC.

    Returns:
        {"ok": True, "processed": N, "remaining": M, "done": bool}
    """
    import google.cloud.storage  # lazy import — triggers no I/O at import time

    state = _get_state()
    completed: dict = state.get("completed", {})

    # Determine user_id from env (single-user system)
    user_id = int(os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip())

    # List all JSONL blobs under the prefix
    storage_client = google.cloud.storage.Client()
    bucket_name = os.environ["CHAT_LOGS_BUCKET"]
    bucket = storage_client.bucket(bucket_name)
    all_blobs = list(bucket.list_blobs(prefix=_GCS_PREFIX))
    jsonl_blobs = [b for b in all_blobs if b.name.endswith(".jsonl")]

    # Work queue: blobs not yet processed at the current generation
    work_queue = [
        b for b in jsonl_blobs
        if completed.get(b.name) != str(b.generation)
    ]

    processed_count = 0
    start_time = time.monotonic()

    for blob in work_queue:
        if processed_count >= BATCH_MAX_FILES:
            break
        if time.monotonic() - start_time >= BATCH_TIME_BUDGET_SEC:
            break

        try:
            # Extract machine_id from blob path: claude-code/{machine_id}/...
            path_parts = blob.name.split("/")
            machine_id = path_parts[1] if len(path_parts) > 1 else "unknown"

            # Extract session_id from filename stem
            session_id = Path(blob.name).stem

            content = blob.download_as_bytes()
            conv = parse_claude_code_jsonl(content, session_id, machine_id)

            if conv is None:
                # Zero turns — mark as done, skip embedding/notion
                logger.info(
                    "chat_ingest: %s has zero valid turns — marking complete",
                    blob.name,
                )
                completed[blob.name] = str(blob.generation)
                _set_state({"completed": completed})
                processed_count += 1
                continue

            # Chunk and inject user_id into metadata
            chunks = _chunk_conversation(conv)
            for chunk in chunks:
                chunk["metadata"]["user_id"] = str(user_id)

            # Upsert chunks to Pinecone
            store = _get_memory_store()
            store.upsert_chat_chunks(user_id, chunks)

            # Summarise and write to Notion
            summary, topics = _summarize(conv)

            from mcp_tools.notion_tool import build_chat_log_properties, upsert_database_row
            properties = build_chat_log_properties(conv, summary, topics)
            upsert_database_row(
                os.environ["NOTION_CHAT_LOG_DB_ID"],
                "Session ID",
                conv.session_id,
                properties,
            )

            completed[blob.name] = str(blob.generation)
            _set_state({"completed": completed})
            processed_count += 1
            logger.info(
                "chat_ingest: processed %s (%d turns, %d chunks)",
                blob.name,
                len(conv.turns),
                len(chunks),
            )

        except Exception:
            logger.warning(
                "chat_ingest: failed processing %s — skipping",
                blob.name,
                exc_info=True,
            )
            # Leave blob in work queue so it can be retried next tick.
            continue

    remaining = len(work_queue) - processed_count
    done = remaining == 0

    return {
        "ok": True,
        "processed": processed_count,
        "remaining": remaining,
        "done": done,
    }


# ------------------------------------------------------------------ #
# Async wrapper                                                      #
# ------------------------------------------------------------------ #

async def handle_tick() -> dict:
    """Async wrapper for Cloud Run route handler.

    Offloads the blocking run_one_batch() call to the default thread
    executor so the event loop remains unblocked.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_one_batch)


# ------------------------------------------------------------------ #
# CLI dry-run                                                        #
# ------------------------------------------------------------------ #

def _cli() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Chat ingest local dry-run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", help="Path to a local .jsonl file to parse and preview")
    args = parser.parse_args()

    if args.dry_run and args.file:
        with open(args.file, "rb") as f:
            content = f.read()
        session_id = Path(args.file).stem
        conv = parse_claude_code_jsonl(content, session_id, "mac")
        if conv is None:
            print("Zero turns after filtering — file would be skipped.")
        else:
            print(f"Title: {conv.title}")
            print(f"Project: {conv.project}")
            print(f"Turns: {len(conv.turns)}")
            chunks = _chunk_conversation(conv)
            print(f"Chunks: {len(chunks)}")
            print(f"First chunk: {chunks[0]['content'][:200] if chunks else 'n/a'}")
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()
