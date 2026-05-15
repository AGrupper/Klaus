"""Smoke test for all 5 Notion MCP tools against the real Notion workspace.

Run this after setting NOTION_API_TOKEN in .env. Requires the integration to
have access to at least one page or database.

Usage:
    python scripts/smoke_test_notion.py

Prerequisites:
    1. Create a Notion integration at https://www.notion.so/my-integrations
    2. Copy the Internal Integration Token into .env:
           NOTION_API_TOKEN=secret_...
    3. Share at least one Notion page or database with the integration.
    4. Run this script. Each test prints PASS or FAIL with a short reason.

The script exercises:
    - notion_search
    - notion_get_page
    - notion_query_database
    - notion_create_page
    - notion_append_blocks
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure the project root is on sys.path so mcp_tools is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv(override=True)

from mcp_tools.notion_tool import (  # noqa: E402  (import after sys.path patch)
    append_blocks as notion_append_blocks,
    create_page as notion_create_page,
    get_page as notion_get_page,
    query_database as notion_query_database,
    search as notion_search,
)


def _check_env() -> None:
    token = os.getenv("NOTION_API_TOKEN")
    if not token:
        print(
            "ERROR: NOTION_API_TOKEN is not set.\n"
            "Add it to .env and re-run:\n"
            "    NOTION_API_TOKEN=secret_..."
        )
        sys.exit(1)


def _result_label(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def main() -> None:
    _check_env()

    passed = 0
    total = 5

    # Shared state passed between tests.
    first_page_id: str | None = None
    created_page_id: str | None = None

    # ------------------------------------------------------------------
    # Test 1 — notion_search
    # ------------------------------------------------------------------
    print("\n[1/5] notion_search — searching for 'project' ...")
    try:
        result = notion_search(query="project")
        assert isinstance(result.get("results"), list), "missing 'results' list"
        assert "count" in result, "missing 'count' key"
        count = result["count"]
        results = result["results"]
        print(f"      Found {count} result(s).")
        if results:
            # Try to surface the first result's title.
            first = results[0]
            title = (
                first.get("title")
                or first.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "")
                or first.get("id", "<no title>")
            )
            print(f"      First result title: {title}")
            first_page_id = first.get("id")
        print(f"  [{_result_label(True)}] notion_search")
        passed += 1
    except Exception as exc:
        print(f"  [{_result_label(False)}] notion_search — {exc}")

    # ------------------------------------------------------------------
    # Test 2 — notion_get_page
    # ------------------------------------------------------------------
    print("\n[2/5] notion_get_page ...")
    if first_page_id is None:
        print("      SKIP — no page ID from test 1 (search returned no results).")
        print(f"  [{_result_label(False)}] notion_get_page — skipped")
    else:
        try:
            result = notion_get_page(page_id=first_page_id)
            assert "title" in result, "missing 'title' key"
            assert "text" in result, "missing 'text' key"
            print(f"      Page title: {result['title']}")
            print(f"  [{_result_label(True)}] notion_get_page")
            passed += 1
        except Exception as exc:
            print(f"  [{_result_label(False)}] notion_get_page — {exc}")

    # ------------------------------------------------------------------
    # Test 3 — notion_query_database
    # ------------------------------------------------------------------
    print("\n[3/5] notion_query_database — searching for databases ...")
    try:
        db_search = notion_search(query="", filter_type="database")
        databases = db_search.get("results", [])
        if not databases:
            # Fallback: try searching without a filter on "project" and pick any db.
            db_search = notion_search(query="project", filter_type="database")
            databases = db_search.get("results", [])

        if not databases:
            print("      SKIP — no databases accessible to this integration.")
            print(f"  [{_result_label(False)}] notion_query_database — skipped")
        else:
            db_id = databases[0]["id"]
            print(f"      Querying database {db_id} ...")
            result = notion_query_database(database_id=db_id)
            assert "schema" in result, "missing 'schema' key"
            assert "rows" in result, "missing 'rows' key"
            schema_keys = list(result["schema"].keys())
            print(f"      Schema keys: {schema_keys}")
            print(f"  [{_result_label(True)}] notion_query_database")
            passed += 1
    except Exception as exc:
        print(f"  [{_result_label(False)}] notion_query_database — {exc}")

    # ------------------------------------------------------------------
    # Test 4 — notion_create_page
    # ------------------------------------------------------------------
    print("\n[4/5] notion_create_page — creating throwaway sub-page ...")
    if first_page_id is None:
        print("      SKIP — no parent page ID from test 1.")
        print(f"  [{_result_label(False)}] notion_create_page — skipped")
    else:
        try:
            result = notion_create_page(
                parent_id=first_page_id,
                parent_type="page",
                title="Klaus Smoke Test — DELETE ME",
                content="- Automated smoke test\n- Safe to delete",
            )
            assert "page_id" in result, "missing 'page_id' key"
            created_page_id = result["page_id"]
            url = result.get("url", "<no url>")
            print(f"      Created page ID: {created_page_id}")
            print(f"      URL: {url}")
            print(f"  [{_result_label(True)}] notion_create_page")
            passed += 1
        except Exception as exc:
            print(f"  [{_result_label(False)}] notion_create_page — {exc}")

    # ------------------------------------------------------------------
    # Test 5 — notion_append_blocks
    # ------------------------------------------------------------------
    print("\n[5/5] notion_append_blocks — appending to created page ...")
    if created_page_id is None:
        print("      SKIP — no created page ID from test 4.")
        print(f"  [{_result_label(False)}] notion_append_blocks — skipped")
    else:
        try:
            result = notion_append_blocks(
                page_id=created_page_id,
                content="- Smoke test complete",
            )
            assert "appended" in result, "missing 'appended' key"
            print(f"      Appended: {result['appended']}")
            print(f"  [{_result_label(True)}] notion_append_blocks")
            passed += 1
        except Exception as exc:
            print(f"  [{_result_label(False)}] notion_append_blocks — {exc}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Smoke test complete: {passed}/{total} tests passed.")
    if passed == total:
        print("All Notion tools are working correctly.")
    else:
        print(
            f"{total - passed} test(s) failed or were skipped.\n"
            "Check that your integration has access to at least one page and database."
        )
    print("="*50 + "\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
