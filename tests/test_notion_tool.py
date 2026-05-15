"""Unit tests for mcp_tools/notion_tool.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


# ------------------------------------------------------------------ #
# TestTextToBlocks                                                   #
# ------------------------------------------------------------------ #

class TestTextToBlocks:
    def test_empty_returns_empty(self):
        from mcp_tools.notion_tool import _text_to_blocks
        assert _text_to_blocks("") == []

    def test_paragraph(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("Hello world")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hello world"

    def test_heading1(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("# My Heading")
        assert blocks[0]["type"] == "heading_1"
        assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "My Heading"

    def test_heading2(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("## Sub Heading")
        assert blocks[0]["type"] == "heading_2"
        assert blocks[0]["heading_2"]["rich_text"][0]["text"]["content"] == "Sub Heading"

    def test_heading3(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("### Sub Sub Heading")
        assert blocks[0]["type"] == "heading_3"
        assert blocks[0]["heading_3"]["rich_text"][0]["text"]["content"] == "Sub Sub Heading"

    def test_bullet_dash(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("- item one")
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "item one"

    def test_bullet_star(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("* item one")
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "item one"

    def test_numbered(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("1. first item")
        assert blocks[0]["type"] == "numbered_list_item"
        assert blocks[0]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "first item"

    def test_todo_unchecked(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("[ ] do something")
        assert blocks[0]["type"] == "to_do"
        assert blocks[0]["to_do"]["checked"] is False
        assert blocks[0]["to_do"]["rich_text"][0]["text"]["content"] == "do something"

    def test_todo_checked(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("[x] done thing")
        assert blocks[0]["type"] == "to_do"
        assert blocks[0]["to_do"]["checked"] is True
        assert blocks[0]["to_do"]["rich_text"][0]["text"]["content"] == "done thing"

    def test_empty_lines_skipped(self):
        from mcp_tools.notion_tool import _text_to_blocks
        blocks = _text_to_blocks("line1\n\nline2")
        assert len(blocks) == 2

    def test_mixed(self):
        from mcp_tools.notion_tool import _text_to_blocks
        text = "# Title\n- bullet\nplain paragraph"
        blocks = _text_to_blocks(text)
        assert len(blocks) == 3
        assert blocks[0]["type"] == "heading_1"
        assert blocks[1]["type"] == "bulleted_list_item"
        assert blocks[2]["type"] == "paragraph"


# ------------------------------------------------------------------ #
# TestBlocksToText                                                   #
# ------------------------------------------------------------------ #

def _rt(content: str) -> list:
    """Helper to build a rich_text list."""
    return [{"type": "text", "text": {"content": content}, "plain_text": content}]


class TestBlocksToText:
    def test_paragraph(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": _rt("Hello")}}]
        text, children = _blocks_to_text(blocks)
        assert "Hello\n" in text
        assert children == []

    def test_heading1(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "heading_1", "heading_1": {"rich_text": _rt("Title")}}]
        text, children = _blocks_to_text(blocks)
        assert text == "# Title\n"

    def test_heading2(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "heading_2", "heading_2": {"rich_text": _rt("Sub")}}]
        text, children = _blocks_to_text(blocks)
        assert text == "## Sub\n"

    def test_heading3(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "heading_3", "heading_3": {"rich_text": _rt("SubSub")}}]
        text, children = _blocks_to_text(blocks)
        assert text == "### SubSub\n"

    def test_bullet(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt("item")}}]
        text, children = _blocks_to_text(blocks)
        assert text == "- item\n"

    def test_todo_checked(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "to_do", "to_do": {"rich_text": _rt("done"), "checked": True}}]
        text, children = _blocks_to_text(blocks)
        assert text == "[x] done\n"

    def test_todo_unchecked(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "to_do", "to_do": {"rich_text": _rt("todo"), "checked": False}}]
        text, children = _blocks_to_text(blocks)
        assert text == "[ ] todo\n"

    def test_child_page_in_children(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "child_page", "id": "page-123", "child_page": {"title": "Child Title"}}]
        text, children = _blocks_to_text(blocks)
        assert text == ""
        assert len(children) == 1
        assert children[0] == {"id": "page-123", "title": "Child Title", "type": "page"}

    def test_child_database_in_children(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "child_database", "id": "db-456", "child_database": {"title": "My DB"}}]
        text, children = _blocks_to_text(blocks)
        assert text == ""
        assert len(children) == 1
        assert children[0] == {"id": "db-456", "title": "My DB", "type": "database"}

    def test_numbered(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "numbered_list_item", "numbered_list_item": {"rich_text": _rt("first item")}}]
        text, children = _blocks_to_text(blocks)
        assert text == "1. first item\n"

    def test_unknown_type_skipped(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [{"type": "synced_block", "synced_block": {}}]
        text, children = _blocks_to_text(blocks)
        assert text == ""
        assert children == []

    def test_mixed(self):
        from mcp_tools.notion_tool import _blocks_to_text
        blocks = [
            {"type": "heading_1", "heading_1": {"rich_text": _rt("Title")}},
            {"type": "paragraph", "paragraph": {"rich_text": _rt("Para")}},
            {"type": "child_page", "id": "cp-1", "child_page": {"title": "Sub"}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt("Bullet")}},
        ]
        text, children = _blocks_to_text(blocks)
        assert "# Title\n" in text
        assert "Para\n" in text
        assert "- Bullet\n" in text
        assert len(children) == 1
        assert children[0]["id"] == "cp-1"


# ------------------------------------------------------------------ #
# TestRoundTrip                                                      #
# ------------------------------------------------------------------ #

class TestRoundTrip:
    def test_round_trip_paragraph(self):
        from mcp_tools.notion_tool import _text_to_blocks, _blocks_to_text
        original = "Hello world"
        blocks = _text_to_blocks(original)
        # Patch plain_text so _blocks_to_text can read the blocks we produced
        for b in blocks:
            btype = b["type"]
            for seg in b[btype]["rich_text"]:
                seg["plain_text"] = seg["text"]["content"]
        text, _ = _blocks_to_text(blocks)
        assert text.strip() == original

    def test_round_trip_bullets(self):
        from mcp_tools.notion_tool import _text_to_blocks, _blocks_to_text
        original = "- alpha\n- beta\n- gamma"
        blocks = _text_to_blocks(original)
        for b in blocks:
            btype = b["type"]
            for seg in b[btype]["rich_text"]:
                seg["plain_text"] = seg["text"]["content"]
        text, _ = _blocks_to_text(blocks)
        for line in ["- alpha", "- beta", "- gamma"]:
            assert line in text

    def test_round_trip_headings(self):
        from mcp_tools.notion_tool import _text_to_blocks, _blocks_to_text
        original = "# H1\n## H2\n### H3"
        blocks = _text_to_blocks(original)
        for b in blocks:
            btype = b["type"]
            for seg in b[btype]["rich_text"]:
                seg["plain_text"] = seg["text"]["content"]
        text, _ = _blocks_to_text(blocks)
        assert "# H1" in text
        assert "## H2" in text
        assert "### H3" in text

    def test_round_trip_todo(self):
        from mcp_tools.notion_tool import _text_to_blocks, _blocks_to_text
        original = "[ ] pending\n[x] done"
        blocks = _text_to_blocks(original)
        for b in blocks:
            for seg in b["to_do"]["rich_text"]:
                seg["plain_text"] = seg["text"]["content"]
        text, _ = _blocks_to_text(blocks)
        assert "[ ] pending" in text
        assert "[x] done" in text


# ------------------------------------------------------------------ #
# TestSearch                                                         #
# ------------------------------------------------------------------ #

class TestSearch:
    def _page_result(self, page_id="p1", title="My Page", url="u"):
        return {
            "id": page_id,
            "object": "page",
            "url": url,
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": title}],
                }
            },
        }

    def test_success(self):
        from mcp_tools.notion_tool import search
        mock_response = {"results": [self._page_result()]}
        with patch("mcp_tools.notion_tool._api_post", return_value=mock_response):
            result = search("test")
        assert result["count"] == 1
        assert result["query"] == "test"
        assert result["results"][0] == {"id": "p1", "title": "My Page", "type": "page", "url": "u"}

    def test_filter_type_page(self):
        from mcp_tools.notion_tool import search
        mock_response = {"results": []}
        with patch("mcp_tools.notion_tool._api_post", return_value=mock_response) as mock_post:
            search("test", filter_type="page")
        body = mock_post.call_args[0][1]
        assert body["filter"] == {"value": "page", "property": "object"}

    def test_no_filter_when_none(self):
        from mcp_tools.notion_tool import search
        mock_response = {"results": []}
        with patch("mcp_tools.notion_tool._api_post", return_value=mock_response) as mock_post:
            search("test", filter_type=None)
        body = mock_post.call_args[0][1]
        assert "filter" not in body

    def test_api_error(self):
        from mcp_tools.notion_tool import search
        with patch("mcp_tools.notion_tool._api_post", side_effect=requests.RequestException("fail")):
            result = search("test")
        assert result == {"error": "fail", "query": "test"}


# ------------------------------------------------------------------ #
# TestGetPage                                                        #
# ------------------------------------------------------------------ #

def _make_page_data(page_id="page-1", title="My Page"):
    return {
        "id": page_id,
        "object": "page",
        "url": f"https://notion.so/{page_id}",
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


def _make_block_children(blocks):
    return {"results": blocks, "has_more": False, "next_cursor": None}


class TestGetPage:
    def test_success(self):
        from mcp_tools.notion_tool import get_page
        page_data = _make_page_data("page-1", "My Page")
        para_block = {
            "type": "paragraph",
            "paragraph": {"rich_text": _rt("Hello text")},
        }
        block_resp = _make_block_children([para_block])

        with patch("mcp_tools.notion_tool._api_get", return_value=page_data), \
             patch("mcp_tools.notion_tool._fetch_block_children", return_value=block_resp):
            result = get_page("page-1")

        assert result["id"] == "page-1"
        assert result["title"] == "My Page"
        assert "Hello text" in result["text"]
        assert result["children"] == []

    def test_child_page_in_children(self):
        from mcp_tools.notion_tool import get_page
        page_data = _make_page_data("page-1", "Parent")
        child_block = {
            "type": "child_page",
            "id": "child-99",
            "child_page": {"title": "Child"},
        }
        block_resp = _make_block_children([child_block])

        with patch("mcp_tools.notion_tool._api_get", return_value=page_data), \
             patch("mcp_tools.notion_tool._fetch_block_children", return_value=block_resp):
            result = get_page("page-1")

        assert len(result["children"]) == 1
        assert result["children"][0]["id"] == "child-99"
        assert result["children"][0]["title"] == "Child"
        assert result["children"][0]["type"] == "page"

    def test_api_error(self):
        from mcp_tools.notion_tool import get_page
        with patch("mcp_tools.notion_tool._api_get", side_effect=requests.RequestException("not found")):
            result = get_page("bad-id")
        assert "error" in result
        assert result["page_id"] == "bad-id"


# ------------------------------------------------------------------ #
# TestQueryDatabase                                                  #
# ------------------------------------------------------------------ #

def _make_db_data(db_id="db-1"):
    return {
        "id": db_id,
        "object": "database",
        "properties": {
            "Name": {"type": "title"},
            "Status": {"type": "status"},
            "Tags": {"type": "multi_select"},
        },
    }


def _make_db_row(row_id="row-1", title="Row Title"):
    return {
        "id": row_id,
        "url": f"https://notion.so/{row_id}",
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            },
            "Status": {
                "type": "status",
                "status": {"name": "In Progress"},
            },
            "Tags": {
                "type": "multi_select",
                "multi_select": [{"name": "tag1"}, {"name": "tag2"}],
            },
        },
    }


class TestQueryDatabase:
    def test_success(self):
        from mcp_tools.notion_tool import query_database
        db_data = _make_db_data("db-1")
        row = _make_db_row("row-1", "Row Title")
        query_resp = {"results": [row], "has_more": False, "next_cursor": None}

        with patch("mcp_tools.notion_tool._api_get", return_value=db_data), \
             patch("mcp_tools.notion_tool._fetch_db_query", return_value=query_resp):
            result = query_database("db-1")

        assert result["database_id"] == "db-1"
        assert result["schema"] == {"Name": "title", "Status": "status", "Tags": "multi_select"}
        assert result["count"] == 1
        row_out = result["rows"][0]
        assert row_out["id"] == "row-1"
        assert row_out["properties"]["Name"] == "Row Title"
        assert row_out["properties"]["Status"] == "In Progress"
        assert row_out["properties"]["Tags"] == ["tag1", "tag2"]

    def test_filter_passed_through(self):
        from mcp_tools.notion_tool import query_database
        db_data = _make_db_data("db-1")
        query_resp = {"results": [], "has_more": False, "next_cursor": None}
        my_filter = {"property": "Status", "status": {"equals": "Done"}}

        with patch("mcp_tools.notion_tool._api_get", return_value=db_data), \
             patch("mcp_tools.notion_tool._fetch_db_query", return_value=query_resp) as mock_query:
            query_database("db-1", filter=my_filter)

        call_kwargs = mock_query.call_args[1]
        assert call_kwargs["filter"] == my_filter

    def test_api_error(self):
        from mcp_tools.notion_tool import query_database
        with patch("mcp_tools.notion_tool._api_get", side_effect=requests.RequestException("timeout")):
            result = query_database("db-bad")
        assert "error" in result
        assert result["database_id"] == "db-bad"


# ------------------------------------------------------------------ #
# TestCreatePage                                                     #
# ------------------------------------------------------------------ #

class TestCreatePage:
    def _mock_post(self, page_id="new-page-1"):
        return {"id": page_id, "url": f"https://notion.so/{page_id}"}

    def test_creates_under_database(self):
        from mcp_tools.notion_tool import create_page
        with patch("mcp_tools.notion_tool._api_post", return_value=self._mock_post()) as mock_post:
            create_page("db-123", "database", "My Page")
        body = mock_post.call_args[0][1]
        assert body["parent"] == {"database_id": "db-123"}

    def test_creates_under_page(self):
        from mcp_tools.notion_tool import create_page
        with patch("mcp_tools.notion_tool._api_post", return_value=self._mock_post()) as mock_post:
            create_page("pg-123", "page", "My Sub Page")
        body = mock_post.call_args[0][1]
        assert body["parent"] == {"page_id": "pg-123"}

    def test_invalid_parent_type(self):
        from mcp_tools.notion_tool import create_page
        result = create_page("x", "workspace", "Title")
        assert "error" in result

    def test_content_converted_to_blocks(self):
        from mcp_tools.notion_tool import create_page
        with patch("mcp_tools.notion_tool._api_post", return_value=self._mock_post()) as mock_post:
            create_page("db-123", "database", "Title", content="- item one")
        body = mock_post.call_args[0][1]
        assert "children" in body
        assert isinstance(body["children"], list)
        assert len(body["children"]) > 0

    def test_custom_properties_passed_through(self):
        from mcp_tools.notion_tool import create_page
        custom_props = {"X": {"y": "z"}}
        with patch("mcp_tools.notion_tool._api_post", return_value=self._mock_post()) as mock_post:
            create_page("db-123", "database", "Title", properties=custom_props)
        body = mock_post.call_args[0][1]
        assert body["properties"] == custom_props

    def test_success_returns_confirmation(self):
        from mcp_tools.notion_tool import create_page
        with patch("mcp_tools.notion_tool._api_post", return_value=self._mock_post("new-1")):
            result = create_page("db-123", "database", "My Page")
        assert result["page_id"] == "new-1"
        assert "confirmation" in result

    def test_api_error(self):
        from mcp_tools.notion_tool import create_page
        with patch("mcp_tools.notion_tool._api_post", side_effect=requests.RequestException("bad")):
            result = create_page("db-123", "database", "Title")
        assert "error" in result
        assert result["title"] == "Title"


# ------------------------------------------------------------------ #
# TestPaginate                                                       #
# ------------------------------------------------------------------ #

class TestPaginate:
    def test_truncated_when_max_pages_exhausted(self):
        """_paginate returns truncated=True when _MAX_PAGES iterations all had has_more=True."""
        from mcp_tools.notion_tool import _paginate, _MAX_PAGES
        call_count = 0
        def always_has_more(page_size=100, start_cursor=None):
            nonlocal call_count
            call_count += 1
            return {"results": [{"id": f"r{call_count}"}], "has_more": True, "next_cursor": "cursor"}
        results, truncated = _paginate(always_has_more)
        assert call_count == _MAX_PAGES
        assert truncated is True


# ------------------------------------------------------------------ #
# TestHeaders                                                        #
# ------------------------------------------------------------------ #

class TestHeaders:
    def test_missing_token_returns_error_dict(self):
        """Missing NOTION_API_TOKEN returns {"error": ...} via search(), not KeyError."""
        import os
        original = os.environ.pop("NOTION_API_TOKEN", None)
        try:
            from mcp_tools.notion_tool import search
            result = search("test")
            assert "error" in result
            assert "NOTION_API_TOKEN" in result["error"]
        finally:
            if original is not None:
                os.environ["NOTION_API_TOKEN"] = original


# ------------------------------------------------------------------ #
# TestAppendBlocks                                                   #
# ------------------------------------------------------------------ #

class TestAppendBlocks:
    def test_success(self):
        from mcp_tools.notion_tool import append_blocks
        with patch("mcp_tools.notion_tool._api_patch", return_value={}) as mock_patch:
            result = append_blocks("page-1", "hello")
        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        assert call_args[0][0] == "blocks/page-1/children"
        assert len(call_args[0][1]["children"]) == 1
        assert result["page_id"] == "page-1"
        assert result["appended"] == 1
        assert "confirmation" in result

    def test_empty_content(self):
        from mcp_tools.notion_tool import append_blocks
        with patch("mcp_tools.notion_tool._api_patch") as mock_patch:
            result = append_blocks("page-1", "")
        mock_patch.assert_not_called()
        assert "error" in result

    def test_chunked_large_content(self):
        from mcp_tools.notion_tool import append_blocks, _BLOCK_CHUNK
        big_content = "\n".join(f"line {i}" for i in range(_BLOCK_CHUNK + 1))
        with patch("mcp_tools.notion_tool._api_patch", return_value={}) as mock_patch:
            result = append_blocks("page-1", big_content)
        assert mock_patch.call_count == 2
        assert result["appended"] == _BLOCK_CHUNK + 1

    def test_api_error(self):
        from mcp_tools.notion_tool import append_blocks
        with patch("mcp_tools.notion_tool._api_patch", side_effect=requests.RequestException("fail")):
            result = append_blocks("page-1", "some content")
        assert "error" in result
        assert result["page_id"] == "page-1"
