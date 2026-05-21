"""Backfill meaningful Flash-generated titles into existing "Klaus Chat Logs" Notion rows.

Usage:
    python scripts/backfill_notion_titles.py [--dry-run] [--limit N]

Flags:
    --dry-run   Print old → new title pairs without writing to Notion.
    --limit N   Process at most N rows (useful for spot-checks).

The script paginates the full Notion DB using _fetch_db_query (bypassing the
300-row cap of query_database), generates one past-tense sentence title per row
via a single Flash call, and writes it back via update_page_properties.

Re-runnable: each run simply overwrites the Name property.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SKIP_SUMMARIES = {"No summary available", "Session too short to summarize."}

_TITLE_PROMPT = (
    "Write one past-tense sentence with a verb (~8-15 words) that describes "
    "what was built or debugged in this session. Output ONLY the sentence — "
    "no quotes, no trailing punctuation beyond a period.\n\nSummary:\n{summary}"
)


def _fetch_all_rows(db_id: str) -> list[dict]:
    """Paginate the full DB, returning all raw Notion page objects."""
    from mcp_tools import notion_tool
    rows: list[dict] = []
    cursor: str | None = None
    page_num = 0

    while True:
        page_num += 1
        resp = notion_tool._fetch_db_query(
            database_id=db_id,
            filter=None,
            sorts=None,
            page_size=100,
            start_cursor=cursor,
        )
        results = resp.get("results", [])
        rows.extend(results)
        logger.info("Page %d: fetched %d rows (total so far: %d)", page_num, len(results), len(rows))

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
        if not cursor:
            break

    return rows


def _generate_title(summary: str, llm_client) -> str:
    """Call Flash with the summary and return a stripped title sentence."""
    prompt = _TITLE_PROMPT.format(summary=summary)
    response = llm_client.chat(
        messages=[{"role": "user", "content": prompt}],
        system="You are a concise technical title writer.",
    )
    raw = (response.get("text") or "").strip()
    # Strip surrounding quotes if Flash adds them
    raw = raw.strip('"').strip("'").strip()
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Notion 'Klaus Chat Logs' titles")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N rows")
    args = parser.parse_args()

    db_id = os.environ["NOTION_CHAT_LOG_DB_ID"]

    from core.llm_client import LLMClient
    from mcp_tools import notion_tool

    llm = LLMClient(
        backend=os.environ["WORKER_AGENT_BACKEND"],
        model=os.environ["WORKER_AGENT_MODEL"],
        api_key=os.environ["WORKER_AGENT_API_KEY"],
        base_url=os.environ.get("WORKER_AGENT_BASE_URL"),
    )

    logger.info("Fetching all rows from Notion DB %s …", db_id)
    all_rows = _fetch_all_rows(db_id)
    logger.info("Total rows fetched: %d", len(all_rows))

    if args.limit:
        all_rows = all_rows[: args.limit]
        logger.info("Limiting to %d rows (--limit)", args.limit)

    updated = skipped = failed = 0

    for row in all_rows:
        page_id: str = row["id"]
        props = row.get("properties", {})
        flat = notion_tool._flatten_properties(props)

        current_name: str = flat.get("Name", "").strip()
        summary: str = flat.get("Summary", "").strip()

        if not summary or summary in _SKIP_SUMMARIES:
            logger.info("SKIP  %s (no usable summary)", page_id)
            skipped += 1
            continue

        try:
            new_title = _generate_title(summary, llm)
            if not new_title:
                logger.warning("SKIP  %s (Flash returned empty title)", page_id)
                skipped += 1
                continue

            if args.dry_run:
                print(f"DRY   {page_id[:8]}…  OLD: {current_name!r}")
                print(f"                      NEW: {new_title!r}")
            else:
                notion_tool.update_page_properties(
                    page_id,
                    {
                        "Name": {
                            "title": [
                                {"type": "text", "text": {"content": new_title[:2000]}}
                            ]
                        }
                    },
                )
                logger.info("OK    %s → %r", page_id[:8], new_title)
                updated += 1

            time.sleep(0.3)

        except Exception:
            logger.warning("FAIL  %s", page_id, exc_info=True)
            failed += 1
            continue

    print(
        f"\nDone. updated={updated}  skipped={skipped}  failed={failed}"
        + (" (dry-run, no writes)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
