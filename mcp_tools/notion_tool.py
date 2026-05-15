"""Notion API integration — search, read, query, and write pages.

Uses the Notion REST API v1 with a static integration token.

Five public functions:
  search(query, filter_type)                          → dict
  get_page(page_id)                                   → dict
  query_database(database_id, filter, sorts)          → dict
  create_page(parent_id, parent_type, title, content) → dict
  append_blocks(page_id, content)                     → dict

Auth: reads NOTION_API_TOKEN from os.environ (static token, never expires).
No SDK — uses requests only.
"""
from __future__ import annotations

import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_MAX_PAGES = 3
_MAX_RESULTS = 300
_BLOCK_CHUNK = 100


# ------------------------------------------------------------------ #
# HTTP helpers                                                       #
# ------------------------------------------------------------------ #

def _headers() -> dict:
    token = os.environ.get("NOTION_API_TOKEN", "")
    if not token:
        raise requests.RequestException("NOTION_API_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _api_get(path: str, **kwargs) -> dict | list:
    """GET {_API_BASE}/{path}."""
    resp = requests.get(f"{_API_BASE}/{path}", headers=_headers(), timeout=15, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _api_post(path: str, body: dict) -> dict:
    """POST {_API_BASE}/{path}."""
    resp = requests.post(f"{_API_BASE}/{path}", json=body, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _api_patch(path: str, body: dict) -> dict:
    """PATCH {_API_BASE}/{path}."""
    resp = requests.patch(f"{_API_BASE}/{path}", json=body, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------ #
# Text / block helpers                                               #
# ------------------------------------------------------------------ #

def _rich_text_to_str(rich_text: list) -> str:
    """Concatenate plain_text segments from a Notion rich_text list."""
    return "".join(seg.get("plain_text", "") for seg in rich_text)


def _extract_title(obj: dict) -> str:
    """Extract the human-readable title from a page or database object."""
    if obj.get("object") == "database":
        return "".join(seg.get("plain_text", "") for seg in obj.get("title", []))
    if obj.get("object") == "page":
        for prop in obj.get("properties", {}).values():
            if prop.get("type") == "title":
                return _rich_text_to_str(prop["title"])
    return ""


def _flatten_properties(props: dict) -> dict:
    """Flatten Notion property values to Python-native types."""
    result: dict = {}
    for name, prop in props.items():
        ptype = prop.get("type")
        if ptype == "title":
            result[name] = _rich_text_to_str(prop["title"])
        elif ptype == "rich_text":
            result[name] = _rich_text_to_str(prop["rich_text"])
        elif ptype == "number":
            result[name] = prop["number"]
        elif ptype == "checkbox":
            result[name] = prop["checkbox"]
        elif ptype == "select":
            result[name] = prop["select"]["name"] if prop["select"] else None
        elif ptype == "multi_select":
            result[name] = [s["name"] for s in prop.get("multi_select", [])]
        elif ptype == "date":
            result[name] = prop["date"]["start"] if prop["date"] else None
        elif ptype == "url":
            result[name] = prop["url"]
        elif ptype == "email":
            result[name] = prop["email"]
        elif ptype == "phone_number":
            result[name] = prop["phone_number"]
        elif ptype == "status":
            result[name] = prop["status"]["name"] if prop["status"] else None
        # others: skip
    return result


def _text_to_blocks(text: str) -> list[dict]:
    """Convert plain text / light markdown into a list of Notion block dicts."""
    blocks: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        # Headings
        if line.startswith("### "):
            btype = "heading_3"
            content = line[4:]
        elif line.startswith("## "):
            btype = "heading_2"
            content = line[3:]
        elif line.startswith("# "):
            btype = "heading_1"
            content = line[2:]
        # To-do
        elif line.startswith("[ ] "):
            content = line[4:]
            blocks.append({
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": content}}],
                    "checked": False,
                },
            })
            continue
        elif line.startswith("[x] "):
            content = line[4:]
            blocks.append({
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": content}}],
                    "checked": True,
                },
            })
            continue
        # Bullets
        elif line.startswith("- ") or line.startswith("* "):
            btype = "bulleted_list_item"
            content = line[2:]
        # Numbered list
        elif re.match(r"^\d+\. ", line):
            btype = "numbered_list_item"
            content = re.sub(r"^\d+\. ", "", line, count=1)
        else:
            btype = "paragraph"
            content = line

        blocks.append({
            "type": btype,
            btype: {"rich_text": [{"type": "text", "text": {"content": content}}]},
        })
    return blocks


def _blocks_to_text(blocks: list[dict]) -> tuple[str, list[dict]]:
    """Convert Notion block dicts to (readable_text, children_list)."""
    lines: list[str] = []
    children: list[dict] = []

    for block in blocks:
        btype = block.get("type")
        if btype == "paragraph":
            lines.append(f"{_rich_text_to_str(block['paragraph']['rich_text'])}\n")
        elif btype == "heading_1":
            lines.append(f"# {_rich_text_to_str(block['heading_1']['rich_text'])}\n")
        elif btype == "heading_2":
            lines.append(f"## {_rich_text_to_str(block['heading_2']['rich_text'])}\n")
        elif btype == "heading_3":
            lines.append(f"### {_rich_text_to_str(block['heading_3']['rich_text'])}\n")
        elif btype == "bulleted_list_item":
            lines.append(f"- {_rich_text_to_str(block['bulleted_list_item']['rich_text'])}\n")
        elif btype == "numbered_list_item":
            lines.append(f"1. {_rich_text_to_str(block['numbered_list_item']['rich_text'])}\n")
        elif btype == "to_do":
            text = _rich_text_to_str(block["to_do"]["rich_text"])
            prefix = "[x]" if block["to_do"]["checked"] else "[ ]"
            lines.append(f"{prefix} {text}\n")
        elif btype == "child_page":
            children.append({
                "id": block["id"],
                "title": block["child_page"]["title"],
                "type": "page",
            })
        elif btype == "child_database":
            children.append({
                "id": block["id"],
                "title": block["child_database"]["title"],
                "type": "database",
            })
        # others: skip

    return "".join(lines), children


# ------------------------------------------------------------------ #
# Pagination helpers                                                 #
# ------------------------------------------------------------------ #

def _fetch_block_children(
    page_id: str,
    page_size: int = 100,
    start_cursor: str | None = None,
) -> dict:
    params: dict = {"page_size": page_size}
    if start_cursor:
        params["start_cursor"] = start_cursor
    return _api_get(f"blocks/{page_id}/children", params=params)


def _fetch_db_query(
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    page_size: int = 100,
    start_cursor: str | None = None,
) -> dict:
    body: dict = {"page_size": page_size}
    if filter:
        body["filter"] = filter
    if sorts:
        body["sorts"] = sorts
    if start_cursor:
        body["start_cursor"] = start_cursor
    return _api_post(f"databases/{database_id}/query", body)


def _paginate(fetch_fn, *args, page_size: int = 100, **kwargs) -> tuple[list, bool]:
    """Auto-follow Notion pagination up to _MAX_PAGES / _MAX_RESULTS."""
    results: list = []
    cursor: str | None = None
    for _ in range(_MAX_PAGES):
        data = fetch_fn(*args, page_size=page_size, start_cursor=cursor, **kwargs)
        results.extend(data.get("results", []))
        if not data.get("has_more") or len(results) >= _MAX_RESULTS:
            return results[:_MAX_RESULTS], len(results) > _MAX_RESULTS
        cursor = data.get("next_cursor")
    return results[:_MAX_RESULTS], True


# ------------------------------------------------------------------ #
# Public API                                                         #
# ------------------------------------------------------------------ #

def search(query: str, filter_type: str | None = None) -> dict:
    """Search across all Notion pages and databases.

    Args:
        query: The search string.
        filter_type: Optional "page" or "database" to restrict results.

    Returns:
        Dict with "results", "count", "query" on success,
        or "error" + "query" on failure.
    """
    body: dict = {"query": query, "page_size": 20}
    if filter_type in ("page", "database"):
        body["filter"] = {"value": filter_type, "property": "object"}
    try:
        data = _api_post("search", body)
        results = [
            {
                "id": r["id"],
                "title": _extract_title(r),
                "type": r["object"],
                "url": r.get("url", ""),
            }
            for r in data.get("results", [])
        ]
        return {"results": results, "count": len(results), "query": query, "truncated": data.get("has_more", False)}
    except requests.RequestException as exc:
        return {"error": str(exc), "query": query}


def get_page(page_id: str) -> dict:
    """Fetch a Notion page with its content and child references.

    Args:
        page_id: The Notion page ID (UUID).

    Returns:
        Dict with id, title, text, properties, children, truncated on success,
        or "error" + "page_id" on failure.
    """
    try:
        page_data = _api_get(f"pages/{page_id}")
        title = _extract_title(page_data)
        flat_props = _flatten_properties(page_data.get("properties", {}))
        blocks, truncated = _paginate(_fetch_block_children, page_id)
        text, children = _blocks_to_text(blocks)
        return {
            "id": page_id,
            "title": title,
            "text": text,
            "properties": flat_props,
            "children": children,
            "truncated": truncated,
        }
    except requests.RequestException as exc:
        return {"error": str(exc), "page_id": page_id}


def query_database(
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    page_size: int = 100,
) -> dict:
    """Query a Notion database and return flattened rows.

    Args:
        database_id: The Notion database ID.
        filter: Optional Notion filter object.
        sorts: Optional Notion sorts list.
        page_size: Number of results per API page.

    Returns:
        Dict with database_id, schema, rows, count, truncated on success,
        or "error" + "database_id" on failure.
    """
    try:
        db_data = _api_get(f"databases/{database_id}")
        schema = {name: props["type"] for name, props in db_data.get("properties", {}).items()}
        rows_raw, truncated = _paginate(
            _fetch_db_query,
            database_id,
            filter=filter,
            sorts=sorts,
            page_size=page_size,
        )
        rows = [
            {
                "id": r["id"],
                "url": r.get("url", ""),
                "properties": _flatten_properties(r.get("properties", {})),
            }
            for r in rows_raw
        ]
        return {
            "database_id": database_id,
            "schema": schema,
            "rows": rows,
            "count": len(rows),
            "truncated": truncated,
        }
    except requests.RequestException as exc:
        return {"error": str(exc), "database_id": database_id}


def create_page(
    parent_id: str,
    parent_type: str,
    title: str,
    content: str | None = None,
    properties: dict | None = None,
) -> dict:
    """Create a new Notion page under a database or another page.

    Args:
        parent_id: ID of the parent database or page.
        parent_type: "database" or "page".
        title: The page title.
        content: Optional markdown/plain text to convert to blocks.
        properties: Optional custom properties dict (overrides default title property).

    Returns:
        Dict with page_id, url, confirmation on success,
        or "error" + "title" on failure.
    """
    try:
        if parent_type == "database":
            parent = {"database_id": parent_id}
        elif parent_type == "page":
            parent = {"page_id": parent_id}
        else:
            return {"error": f"parent_type must be 'database' or 'page', got {parent_type!r}"}

        body: dict = {
            "parent": parent,
            "properties": properties if properties is not None else {
                "title": {"title": [{"type": "text", "text": {"content": title}}]}
            },
        }
        if content:
            body["children"] = _text_to_blocks(content)

        data = _api_post("pages", body)
        return {
            "page_id": data["id"],
            "url": data.get("url", ""),
            "confirmation": f"Page '{title}' created.",
        }
    except requests.RequestException as exc:
        return {"error": str(exc), "title": title}


def append_blocks(page_id: str, content: str) -> dict:
    """Append markdown/plain-text content as blocks to an existing page.

    Args:
        page_id: The Notion page ID to append to.
        content: Markdown or plain text to convert into blocks.

    Returns:
        Dict with page_id, appended count, confirmation on success,
        or "error" on failure.
    """
    try:
        blocks = _text_to_blocks(content)
        if not blocks:
            return {"error": "No content to append — empty input."}
        for i in range(0, len(blocks), _BLOCK_CHUNK):
            _api_patch(f"blocks/{page_id}/children", {"children": blocks[i : i + _BLOCK_CHUNK]})
        return {
            "page_id": page_id,
            "appended": len(blocks),
            "confirmation": f"Appended {len(blocks)} block(s) to page.",
        }
    except requests.RequestException as exc:
        return {"error": str(exc), "page_id": page_id}
