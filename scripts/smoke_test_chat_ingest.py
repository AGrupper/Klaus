"""Smoke test for Phase 12 chat-log ingestion pipeline.

Run this after:
  1. Deploying the Phase 12 code to Cloud Run
  2. Running upload_claude_logs.sh at least once (so GCS has real JSONL files)
  3. Setting NOTION_CHAT_LOG_DB_ID in .env

Usage:
    python scripts/smoke_test_chat_ingest.py

The test:
  1. Parses a local JSONL file (no network needed) — dry-run sanity check
  2. [Optional] Lists blobs in GCS bucket (requires CHAT_LOGS_BUCKET + ADC)
  3. [Optional] Runs run_one_batch() in dry-run mode (if DRY_RUN_BATCH=1)
  4. Checks the Notion DB for existing rows (if NOTION_CHAT_LOG_DB_ID is set)
  5. Tests idempotency: calls upsert_database_row twice with the same session ID
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv(override=True)

from core.chat_ingest import (  # noqa: E402
    ParsedConversation,
    _chunk_conversation,
    parse_claude_code_jsonl,
)


# ------------------------------------------------------------------ #
# Env checks                                                         #
# ------------------------------------------------------------------ #

def _check_env() -> None:
    """Print env status for optional and required variables."""
    token = os.getenv("NOTION_API_TOKEN")
    if not token:
        print(
            "WARNING: NOTION_API_TOKEN is not set.\n"
            "         Tests 3 and 4 require it. Add to .env:\n"
            "             NOTION_API_TOKEN=secret_..."
        )

    bucket = os.getenv("CHAT_LOGS_BUCKET")
    if not bucket:
        print(
            "WARNING: CHAT_LOGS_BUCKET is not set.\n"
            "         Test 2 will be skipped."
        )

    db_id = os.getenv("NOTION_CHAT_LOG_DB_ID")
    if not db_id:
        print(
            "WARNING: NOTION_CHAT_LOG_DB_ID is not set.\n"
            "         Tests 3 and 4 will be skipped."
        )


def _result_label(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


# ------------------------------------------------------------------ #
# Main                                                               #
# ------------------------------------------------------------------ #

def main() -> None:
    _check_env()

    passed = 0
    total = 4

    NOTION_DB_ID = os.getenv("NOTION_CHAT_LOG_DB_ID")
    CHAT_LOGS_BUCKET = os.getenv("CHAT_LOGS_BUCKET")
    NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN")

    # ------------------------------------------------------------------
    # Test 1 — Local JSONL parse (no network)
    # ------------------------------------------------------------------
    print("\n[1/4] Local JSONL parse — searching ~/.claude/projects/ ...")
    try:
        claude_projects = Path.home() / ".claude" / "projects"
        jsonl_files = list(claude_projects.rglob("*.jsonl"))

        if not jsonl_files:
            print("      SKIP — no .jsonl files found under ~/.claude/projects/")
            print(f"  [{_result_label(False)}] local JSONL parse — skipped (no files)")
        else:
            jsonl_path = jsonl_files[0]
            session_id = jsonl_path.stem
            print(f"      Using file: {jsonl_path}")

            content = jsonl_path.read_bytes()
            conv = parse_claude_code_jsonl(content, session_id, machine_id="mac")

            # Both None (zero turns) and a ParsedConversation are valid outcomes.
            assert conv is None or isinstance(conv, ParsedConversation), (
                f"Expected ParsedConversation or None, got {type(conv)}"
            )

            if conv is None:
                print("      File has zero valid turns — result is None (valid).")
                print(f"      Session ID: {session_id}")
            else:
                assert conv.title, "title must be a non-empty string"
                assert conv.session_id == session_id, (
                    f"session_id mismatch: {conv.session_id!r} != {session_id!r}"
                )
                chunks = _chunk_conversation(conv)
                print(f"      Title:  {conv.title}")
                print(f"      Turns:  {len(conv.turns)}")
                print(f"      Chunks: {len(chunks)}")

            print(f"  [{_result_label(True)}] local JSONL parse")
            passed += 1
    except Exception as exc:
        print(f"  [{_result_label(False)}] local JSONL parse — {exc}")

    # ------------------------------------------------------------------
    # Test 2 — GCS bucket access (skip if CHAT_LOGS_BUCKET not set)
    # ------------------------------------------------------------------
    print("\n[2/4] GCS bucket access ...")
    if not CHAT_LOGS_BUCKET:
        print("      SKIP — CHAT_LOGS_BUCKET not set.")
        print(f"  [SKIP] GCS bucket access")
        # Don't decrement total — count as neutral skip
        passed += 1  # treat skip as non-failure (same as smoke_test_notion skip pattern)
        # Actually align with the spec: skip is not a pass — re-adjust
        passed -= 1
        total -= 1
    else:
        try:
            import google.cloud.storage  # noqa: PLC0415

            storage_client = google.cloud.storage.Client()
            bucket = storage_client.bucket(CHAT_LOGS_BUCKET)
            blobs = list(bucket.list_blobs(prefix="claude-code/"))

            if not blobs:
                print("      SKIP — bucket exists but contains no blobs under claude-code/")
                print(f"  [SKIP] GCS bucket access — no blobs yet")
                total -= 1
            else:
                print(f"      Found {len(blobs)} blob(s) under claude-code/")
                print(f"  [{_result_label(True)}] GCS bucket access")
                passed += 1
        except Exception as exc:
            print(f"  [{_result_label(False)}] GCS bucket access — {exc}")

    # ------------------------------------------------------------------
    # Test 3 — Notion chat-log DB read
    # ------------------------------------------------------------------
    print("\n[3/4] Notion chat-log DB read ...")
    if not NOTION_API_TOKEN or not NOTION_DB_ID:
        missing = []
        if not NOTION_API_TOKEN:
            missing.append("NOTION_API_TOKEN")
        if not NOTION_DB_ID:
            missing.append("NOTION_CHAT_LOG_DB_ID")
        print(f"      SKIP — {', '.join(missing)} not set.")
        print(f"  [SKIP] Notion chat-log DB read")
        total -= 1
    else:
        try:
            from mcp_tools.notion_tool import query_database  # noqa: PLC0415

            result = query_database(database_id=NOTION_DB_ID)
            assert "schema" in result, "missing 'schema' key in query_database response"
            assert "rows" in result, "missing 'rows' key in query_database response"
            row_count = len(result["rows"])
            print(f"      Row count: {row_count}")
            print(f"      Schema keys: {list(result['schema'].keys())}")
            print(f"  [{_result_label(True)}] Notion chat-log DB read")
            passed += 1
        except Exception as exc:
            print(f"  [{_result_label(False)}] Notion chat-log DB read — {exc}")

    # ------------------------------------------------------------------
    # Test 4 — Notion upsert idempotency
    # ------------------------------------------------------------------
    print("\n[4/4] Notion upsert idempotency ...")
    if not NOTION_API_TOKEN or not NOTION_DB_ID:
        missing = []
        if not NOTION_API_TOKEN:
            missing.append("NOTION_API_TOKEN")
        if not NOTION_DB_ID:
            missing.append("NOTION_CHAT_LOG_DB_ID")
        print(f"      SKIP — {', '.join(missing)} not set.")
        print(f"  [SKIP] Notion upsert idempotency")
        total -= 1
    else:
        try:
            from mcp_tools.notion_tool import (  # noqa: PLC0415
                query_database,
                upsert_database_row,
            )

            TEST_SESSION_ID = "smoke-test-idempotency-check"

            def _make_properties(summary_text: str) -> dict:
                return {
                    "Name": {
                        "title": [{"text": {"content": "SMOKE TEST — DELETE ME"}}]
                    },
                    "Session ID": {
                        "rich_text": [{"text": {"content": TEST_SESSION_ID}}]
                    },
                    "Summary": {
                        "rich_text": [{"text": {"content": summary_text}}]
                    },
                }

            # First upsert — should create
            result1 = upsert_database_row(
                NOTION_DB_ID,
                "Session ID",
                TEST_SESSION_ID,
                _make_properties("First smoke-test summary"),
            )
            print(f"      First upsert action: {result1.get('action')}")

            # Second upsert with different summary — should update, not create
            result2 = upsert_database_row(
                NOTION_DB_ID,
                "Session ID",
                TEST_SESSION_ID,
                _make_properties("Updated smoke-test summary — idempotency verified"),
            )
            print(f"      Second upsert action: {result2.get('action')}")

            assert result2.get("action") == "updated", (
                f"Expected action='updated' on second upsert, got {result2.get('action')!r}"
            )

            # Verify no duplicate rows
            from mcp_tools.notion_tool import _fetch_db_query  # noqa: PLC0415

            filter_obj = {
                "property": "Session ID",
                "rich_text": {"equals": TEST_SESSION_ID},
            }
            check = _fetch_db_query(NOTION_DB_ID, filter=filter_obj, page_size=10)
            matching_rows = check.get("results", [])
            assert len(matching_rows) == 1, (
                f"Expected exactly 1 row with session_id={TEST_SESSION_ID!r}, "
                f"found {len(matching_rows)}"
            )
            print(f"      Duplicate check: {len(matching_rows)} row(s) — OK")
            print("      Cleanup: test row left as 'SMOKE TEST — DELETE ME' for manual removal.")
            print(f"  [{_result_label(True)}] Notion upsert idempotency")
            passed += 1
        except Exception as exc:
            print(f"  [{_result_label(False)}] Notion upsert idempotency — {exc}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Smoke test complete: {passed}/{total} tests passed.")
    if passed == total and total > 0:
        print("All chat-ingest pipeline checks passed.")
    else:
        skipped = total - passed
        print(
            f"{skipped} test(s) failed or were skipped.\n"
            "Check env vars (NOTION_API_TOKEN, CHAT_LOGS_BUCKET, NOTION_CHAT_LOG_DB_ID)\n"
            "and ensure GCS + Notion are accessible."
        )
    print("=" * 50 + "\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
