# core/chat_export_ingest.py
"""Multi-source AI chat export ingestion pipeline.

Parses export zips from Claude.ai, ChatGPT, and Gemini Takeout, embeds and
upserts chunks to Pinecone (kind="chat", source=<provider>), summarises each
conversation, and writes one row per conversation to the "Klaus AI Chat Imports"
Notion database.

Cloud Scheduler fires POST /cron/ingest-chat-exports daily at 04:30 Asia/Jerusalem.
Each tick processes up to CHAT_EXPORT_BATCH_MAX_CONVERSATIONS conversations within
CHAT_EXPORT_TIME_BUDGET_SEC, persisting progress in Firestore
(chat_export_ingest/state) so the backlog drains over multiple ticks.
Conversation-level dedup: re-exports are full dumps; each conv's update_marker is
stored so unchanged conversations are skipped on re-import.

Upload zips first with:
    scripts/upload_chat_export.sh <chatgpt|claude_ai|gemini> <path-to-zip>

Local dry-run:
    python -m core.chat_export_ingest --dry-run --zip <path> --provider <p>
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import io
import json
import logging
import os
import time
import uuid as _uuid_mod
import zipfile
from html.parser import HTMLParser

from core.chat_ingest import (
    MIN_TURN_CHARS,
    ParsedConversation,
    Turn,
    chunk_conversation,
    summarize_conversation,
    _get_memory_store,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants                                                          #
# ------------------------------------------------------------------ #

CHAT_EXPORT_BATCH_MAX_CONVERSATIONS = 20
CHAT_EXPORT_TIME_BUDGET_SEC = 45
_COLLECTION = "chat_export_ingest"
_STATE_DOC = "state"
_GCS_EXPORT_PREFIX = "chat-exports/"
_GEMINI_GAP_MINUTES = 30


# ------------------------------------------------------------------ #
# HTML helper                                                         #
# ------------------------------------------------------------------ #

class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _html_to_text(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


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
        logger.warning("chat_export_ingest: failed to read state", exc_info=True)
        return {}


def _set_state(fields: dict) -> None:
    try:
        client = _make_firestore_client()
        client.collection(_COLLECTION).document(_STATE_DOC).set(fields, merge=True)
    except Exception:
        logger.warning("chat_export_ingest: failed to write state", exc_info=True)


# ------------------------------------------------------------------ #
# Parsers                                                            #
# ------------------------------------------------------------------ #

def parse_claude_ai_export(json_bytes: bytes) -> list[ParsedConversation]:
    """Parse a Claude.ai conversations.json export into ParsedConversations.

    Export shape: array of conversation objects, each with uuid, name,
    created_at, updated_at, and a flat chat_messages[] list.
    Each message has sender ("human"/"assistant"), text, uuid, created_at.
    """
    data = json.loads(json_bytes)
    conversations: list[ParsedConversation] = []

    for conv_data in data:
        uuid = conv_data.get("uuid", "") or _uuid_mod.uuid4().hex
        name = conv_data.get("name") or "Claude.ai conversation"
        created_at = conv_data.get("created_at", "")
        updated_at = conv_data.get("updated_at", "")
        messages = conv_data.get("chat_messages", [])

        turns: list[Turn] = []
        for msg in messages:
            sender = msg.get("sender", "")
            role = "user" if sender == "human" else "assistant"

            text = msg.get("text", "")
            if not text:
                # Fallback: join text-type content blocks
                content = msg.get("content", [])
                if isinstance(content, list):
                    text = " ".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
            text = (text or "").strip()
            if len(text) < MIN_TURN_CHARS:
                continue

            turn_uuid = msg.get("uuid") or _uuid_mod.uuid4().hex
            ts = msg.get("created_at", "")
            turns.append(Turn(uuid=turn_uuid, role=role, text=text, timestamp=ts))

        if not turns:
            continue

        conversations.append(ParsedConversation(
            session_id=uuid,
            title=(name or "Claude.ai conversation")[:80],
            project="",
            machine_id="",
            started_at=created_at,
            ended_at=updated_at,
            source="claude_ai",
            turns=turns,
        ))

    return conversations


def parse_chatgpt_export(json_bytes: bytes) -> list[ParsedConversation]:
    """Parse a ChatGPT conversations.json export into ParsedConversations.

    Export shape: array of conversation objects. Each has title, create_time,
    update_time, conversation_id, and a mapping tree of message nodes keyed by ID.
    Linear thread is reconstructed by walking current_node → parent to root, then
    reversing to get chronological order.

    NOTE: OpenAI occasionally changes this format. Verify against a real export
    before running the production backfill.
    """
    data = json.loads(json_bytes)
    conversations: list[ParsedConversation] = []

    def _epoch_to_iso(epoch) -> str:
        if not epoch:
            return ""
        try:
            return datetime.datetime.fromtimestamp(
                float(epoch), tz=datetime.timezone.utc
            ).isoformat()
        except (OSError, OverflowError, ValueError, TypeError):
            return ""

    for conv_data in data:
        title = conv_data.get("title") or "ChatGPT conversation"
        create_time = conv_data.get("create_time", 0)
        update_time = conv_data.get("update_time", 0)
        conv_id = conv_data.get("conversation_id") or conv_data.get("id", "")
        if not conv_id:
            conv_id = _uuid_mod.uuid4().hex
        mapping = conv_data.get("mapping", {})
        current_node = conv_data.get("current_node")

        if not current_node or not mapping:
            continue

        # Walk current_node → parent to root; collect in reverse order
        node_ids: list[str] = []
        node_id: str | None = current_node
        while node_id and node_id in mapping:
            node_ids.append(node_id)
            node_id = mapping[node_id].get("parent")
        node_ids.reverse()  # now chronological

        turns: list[Turn] = []
        for nid in node_ids:
            node = mapping[nid]
            message = node.get("message")
            if not message:
                continue
            author = message.get("author", {})
            role = author.get("role", "")
            if role not in ("user", "assistant"):
                continue
            content = message.get("content", {})
            if not isinstance(content, dict):
                continue
            # Only handle standard text content
            if content.get("content_type") not in ("text", None):
                # skip code_execution_output, tether, etc.
                if content.get("content_type") != "text":
                    continue
            parts = content.get("parts", [])
            text = " ".join(str(p) for p in parts if p and isinstance(p, str)).strip()
            if len(text) < MIN_TURN_CHARS:
                continue
            ts = _epoch_to_iso(message.get("create_time"))
            turns.append(Turn(uuid=nid, role=role, text=text, timestamp=ts))

        if not turns:
            continue

        conversations.append(ParsedConversation(
            session_id=conv_id,
            title=title[:80],
            project="",
            machine_id="",
            started_at=_epoch_to_iso(create_time),
            ended_at=_epoch_to_iso(update_time),
            source="chatgpt",
            turns=turns,
        ))

    return conversations


def parse_gemini_export(json_bytes: bytes) -> list[ParsedConversation]:
    """Parse a Gemini Takeout MyActivity.json export into ParsedConversations.

    Export shape: flat array of activity records (no conversation IDs or grouping).
    Each record has title ("Prompted ..."), safeHtmlItem[0].html (HTML response),
    and time (ISO timestamp). "Created Gemini Canvas" records are skipped.

    Records are time-clustered into approximate conversations using a 30-minute
    gap threshold. session_id = sha1(earliest_record_time)[:16] — deterministic
    and stable because the activity log is immutable and append-only.
    """
    data = json.loads(json_bytes)

    # Filter canvas records and sort ascending by time
    records: list[tuple[str, dict]] = []
    for rec in data:
        title = rec.get("title", "")
        if title.startswith("Created Gemini Canvas"):
            continue
        t = rec.get("time", "")
        records.append((t, rec))
    records.sort(key=lambda x: x[0])

    if not records:
        return []

    # Cluster by 30-min gap
    clusters: list[list[tuple[str, dict]]] = []
    current_cluster: list[tuple[str, dict]] = [records[0]]

    for i in range(1, len(records)):
        prev_time_str = current_cluster[-1][0]
        curr_time_str = records[i][0]
        gap_minutes = _time_gap_minutes(prev_time_str, curr_time_str)

        if gap_minutes > _GEMINI_GAP_MINUTES:
            clusters.append(current_cluster)
            current_cluster = [records[i]]
        else:
            current_cluster.append(records[i])
    clusters.append(current_cluster)

    conversations: list[ParsedConversation] = []
    for cluster in clusters:
        earliest_time = cluster[0][0]
        latest_time = cluster[-1][0]
        session_id = hashlib.sha1(earliest_time.encode()).hexdigest()[:16]

        turns: list[Turn] = []
        first_prompt: str | None = None

        for time_str, rec in cluster:
            title_raw = rec.get("title", "")
            user_text = (
                title_raw[len("Prompted "):] if title_raw.startswith("Prompted ")
                else title_raw
            ).strip()

            if not first_prompt and user_text:
                first_prompt = user_text

            if len(user_text) >= MIN_TURN_CHARS:
                turns.append(Turn(
                    uuid=hashlib.sha1(f"{time_str}-user".encode()).hexdigest()[:16],
                    role="user",
                    text=user_text,
                    timestamp=time_str,
                ))

            safe_items = rec.get("safeHtmlItem", [])
            html_content = safe_items[0].get("html", "") if safe_items else ""
            assistant_text = _html_to_text(html_content).strip() if html_content else ""

            if len(assistant_text) >= MIN_TURN_CHARS:
                turns.append(Turn(
                    uuid=hashlib.sha1(f"{time_str}-assistant".encode()).hexdigest()[:16],
                    role="assistant",
                    text=assistant_text,
                    timestamp=time_str,
                ))

        if not turns:
            continue

        conversations.append(ParsedConversation(
            session_id=session_id,
            title=(first_prompt or "Gemini conversation")[:80],
            project="",
            machine_id="",
            started_at=earliest_time,
            ended_at=latest_time,
            source="gemini",
            turns=turns,
        ))

    return conversations


def _time_gap_minutes(t1: str, t2: str) -> float:
    """Return the gap in minutes between two ISO timestamp strings. Returns 0 on error."""
    try:
        dt1 = datetime.datetime.fromisoformat(t1.replace("Z", "+00:00"))
        dt2 = datetime.datetime.fromisoformat(t2.replace("Z", "+00:00"))
        return (dt2 - dt1).total_seconds() / 60
    except (ValueError, AttributeError):
        return 0.0


# ------------------------------------------------------------------ #
# Zip helpers                                                         #
# ------------------------------------------------------------------ #

def _locate_json(zip_file: zipfile.ZipFile, provider: str) -> bytes | None:
    """Find and return the bytes of the provider's JSON file inside the zip."""
    names = zip_file.namelist()
    if provider == "gemini":
        # Google Takeout: Takeout/My Activity/Gemini Apps/MyActivity.json
        target = next(
            (n for n in names if "Gemini Apps" in n and n.endswith("MyActivity.json")),
            None,
        )
        if target is None:
            target = next((n for n in names if n.endswith("MyActivity.json")), None)
    else:
        # claude_ai and chatgpt both use conversations.json
        target = next((n for n in names if n.endswith("conversations.json")), None)

    if target is None:
        return None
    return zip_file.read(target)


def _parse_by_provider(provider: str, json_bytes: bytes) -> list[ParsedConversation]:
    """Dispatch to the correct parser based on provider name."""
    if provider == "claude_ai":
        return parse_claude_ai_export(json_bytes)
    if provider == "chatgpt":
        return parse_chatgpt_export(json_bytes)
    if provider == "gemini":
        return parse_gemini_export(json_bytes)
    logger.warning("chat_export_ingest: unknown provider %r — skipping", provider)
    return []


# ------------------------------------------------------------------ #
# Batch runner                                                        #
# ------------------------------------------------------------------ #

def run_one_batch() -> dict:
    """Process a bounded batch of unprocessed export-zip conversations from GCS.

    Reads progress from Firestore, lists zip blobs under chat-exports/, and
    processes up to CHAT_EXPORT_BATCH_MAX_CONVERSATIONS conversations within
    CHAT_EXPORT_TIME_BUDGET_SEC. Conversation-level dedup via Firestore state.

    Returns:
        {"ok": True, "processed": N, "remaining": M, "done": bool}
    """
    import google.cloud.storage  # lazy import

    batch_max = int(os.getenv(
        "CHAT_EXPORT_BATCH_MAX_CONVERSATIONS", str(CHAT_EXPORT_BATCH_MAX_CONVERSATIONS)
    ))
    batch_budget = int(os.getenv(
        "CHAT_EXPORT_TIME_BUDGET_SEC", str(CHAT_EXPORT_TIME_BUDGET_SEC)
    ))

    state = _get_state()
    completed_blobs: dict = state.get("completed_blobs", {})
    processed_conversations: dict = state.get("conversations", {})

    user_id = int(os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip())

    storage_client = google.cloud.storage.Client()
    bucket_name = os.environ["CHAT_LOGS_BUCKET"]
    bucket = storage_client.bucket(bucket_name)
    all_blobs = list(bucket.list_blobs(prefix=_GCS_EXPORT_PREFIX))
    zip_blobs = [b for b in all_blobs if b.name.endswith(".zip")]

    # Only blobs not yet fully drained
    work_blobs = [
        b for b in zip_blobs
        if completed_blobs.get(b.name) != str(b.generation)
    ]

    processed_count = 0
    start_time = time.monotonic()

    for blob in work_blobs:
        if processed_count >= batch_max or time.monotonic() - start_time >= batch_budget:
            break

        try:
            # Provider from path: chat-exports/{provider}/filename.zip
            path_parts = blob.name.split("/")
            provider = path_parts[1] if len(path_parts) >= 3 else "unknown"

            zip_bytes = blob.download_as_bytes()
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
            json_bytes = _locate_json(zf, provider)

            if json_bytes is None:
                logger.warning(
                    "chat_export_ingest: no JSON found in %s — marking done", blob.name
                )
                completed_blobs[blob.name] = str(blob.generation)
                _set_state({"completed_blobs": completed_blobs})
                continue

            conversations = _parse_by_provider(provider, json_bytes)
            blob_fully_drained = True

            for conv in conversations:
                if processed_count >= batch_max or time.monotonic() - start_time >= batch_budget:
                    blob_fully_drained = False
                    break

                update_marker = conv.ended_at or conv.started_at or conv.session_id
                if processed_conversations.get(conv.session_id) == update_marker:
                    continue  # unchanged — skip

                try:
                    chunks = chunk_conversation(conv)
                    for chunk in chunks:
                        chunk["metadata"]["user_id"] = str(user_id)

                    store = _get_memory_store()
                    store.upsert_chat_chunks(user_id, chunks)

                    _title, summary, topics = summarize_conversation(conv)

                    from mcp_tools.notion_tool import build_ai_chat_properties, upsert_database_row
                    properties = build_ai_chat_properties(conv, summary, topics)
                    upsert_database_row(
                        os.environ["NOTION_AI_CHAT_DB_ID"],
                        "Conversation ID",
                        conv.session_id,
                        properties,
                    )

                    processed_conversations[conv.session_id] = update_marker
                    _set_state({"conversations": processed_conversations})
                    processed_count += 1
                    logger.info(
                        "chat_export_ingest: processed %s conv=%s (%d turns, %d chunks)",
                        provider, conv.session_id, len(conv.turns), len(chunks),
                    )
                except Exception:
                    blob_fully_drained = False
                    logger.warning(
                        "chat_export_ingest: failed on conv %s in %s — skipping",
                        conv.session_id, blob.name, exc_info=True,
                    )

            if blob_fully_drained:
                completed_blobs[blob.name] = str(blob.generation)
                _set_state({"completed_blobs": completed_blobs})

        except Exception:
            logger.warning(
                "chat_export_ingest: failed processing blob %s — skipping",
                blob.name, exc_info=True,
            )

    # Re-count remaining after this tick
    remaining = sum(
        1 for b in work_blobs
        if completed_blobs.get(b.name) != str(b.generation)
    )
    done = remaining <= 0

    return {"ok": True, "processed": processed_count, "remaining": remaining, "done": done}


# ------------------------------------------------------------------ #
# Async wrapper                                                       #
# ------------------------------------------------------------------ #

async def handle_tick() -> dict:
    """Async wrapper for Cloud Run route handler."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_one_batch)


# ------------------------------------------------------------------ #
# CLI dry-run                                                         #
# ------------------------------------------------------------------ #

def _cli() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Chat export ingest local dry-run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--zip", help="Path to a local export zip file")
    parser.add_argument(
        "--provider",
        choices=["claude_ai", "chatgpt", "gemini"],
        help="Export provider",
    )
    args = parser.parse_args()

    if args.dry_run and args.zip and args.provider:
        with open(args.zip, "rb") as f:
            zip_bytes = f.read()
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        json_bytes = _locate_json(zf, args.provider)
        if json_bytes is None:
            print(f"No JSON found in {args.zip} for provider {args.provider}")
            return

        conversations = _parse_by_provider(args.provider, json_bytes)
        print(f"Parsed {len(conversations)} conversations from {args.provider}")
        for i, conv in enumerate(conversations[:5]):
            chunks = chunk_conversation(conv)
            print(
                f"  [{i}] {conv.title!r} | turns={len(conv.turns)} chunks={len(chunks)}"
                f" | id={conv.session_id} | started={conv.started_at[:10] if conv.started_at else '?'}"
            )
            if chunks:
                print(f"       first chunk: {chunks[0]['content'][:120]!r}")
        if len(conversations) > 5:
            print(f"  ... and {len(conversations) - 5} more")
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()
