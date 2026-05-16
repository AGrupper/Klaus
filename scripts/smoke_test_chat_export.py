"""scripts/smoke_test_chat_export.py

End-to-end smoke test for the chat export ingest pipeline.

Run against real local export zips (downloaded from Claude.ai / Google Takeout / ChatGPT).
Does NOT write to Pinecone or Notion — just exercises parsing and chunking to verify
counts and spot-check content.

Usage:
    python scripts/smoke_test_chat_export.py \\
        --claude-ai ~/Downloads/claude-export.zip \\
        --gemini   ~/Downloads/takeout.zip \\
        --chatgpt  ~/Downloads/chatgpt-export.zip
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

# Make sure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.chat_export_ingest import (
    _locate_json,
    _parse_by_provider,
    parse_claude_ai_export,
    parse_gemini_export,
)
from core.chat_ingest import chunk_conversation


def smoke_provider(provider: str, zip_path: str) -> None:
    print(f"\n{'='*60}")
    print(f"Provider: {provider}  |  zip: {zip_path}")
    print("=" * 60)

    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    json_bytes = _locate_json(zf, provider)
    if json_bytes is None:
        print(f"  ERROR: no JSON found in zip for provider '{provider}'")
        return

    print(f"  JSON size: {len(json_bytes):,} bytes")

    conversations = _parse_by_provider(provider, json_bytes)
    print(f"  Parsed conversations: {len(conversations)}")

    empty_count = 0
    total_turns = 0
    total_chunks = 0
    for conv in conversations:
        if not conv.turns:
            empty_count += 1
            continue
        total_turns += len(conv.turns)
        chunks = chunk_conversation(conv)
        total_chunks += len(chunks)

    non_empty = len(conversations) - empty_count
    print(f"  Non-empty conversations: {non_empty}  (empty: {empty_count})")
    print(f"  Total turns: {total_turns}")
    print(f"  Total chunks: {total_chunks}")
    if non_empty:
        print(f"  Avg turns/conv: {total_turns / non_empty:.1f}")
        print(f"  Avg chunks/conv: {total_chunks / non_empty:.1f}")

    # Spot-check first 3 conversations
    shown = 0
    for conv in conversations:
        if not conv.turns or shown >= 3:
            break
        chunks = chunk_conversation(conv)
        print(f"\n  [{shown}] id={conv.session_id}  title={conv.title!r}")
        print(f"       turns={len(conv.turns)}  chunks={len(chunks)}")
        print(f"       started={conv.started_at[:10] if conv.started_at else '?'}  "
              f"ended={conv.ended_at[:10] if conv.ended_at else '?'}")
        if chunks:
            print(f"       first chunk ({len(chunks[0]['content'])} chars): "
                  f"{chunks[0]['content'][:120]!r}")
        shown += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat export ingest smoke test")
    parser.add_argument("--claude-ai", metavar="ZIP", help="Path to Claude.ai export zip")
    parser.add_argument("--gemini",    metavar="ZIP", help="Path to Gemini Takeout zip")
    parser.add_argument("--chatgpt",   metavar="ZIP", help="Path to ChatGPT export zip")
    args = parser.parse_args()

    if not any([args.claude_ai, args.gemini, args.chatgpt]):
        parser.print_help()
        sys.exit(1)

    if args.claude_ai:
        smoke_provider("claude_ai", args.claude_ai)
    if args.gemini:
        smoke_provider("gemini", args.gemini)
    if args.chatgpt:
        smoke_provider("chatgpt", args.chatgpt)

    print("\nSmoke test complete.")


if __name__ == "__main__":
    main()
