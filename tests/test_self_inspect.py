"""Tests for mcp_tools/self_inspect.py — RED phase.

These tests cover SELF-01, SELF-02, SELF-03 acceptance criteria.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import guard — tests fail at RED phase because module does not exist yet
# ---------------------------------------------------------------------------

MODULE_PATH = "mcp_tools.self_inspect"


def _import_module():
    if MODULE_PATH in sys.modules:
        return sys.modules[MODULE_PATH]
    return importlib.import_module(MODULE_PATH)


# ---------------------------------------------------------------------------
# SELF-01: list_own_files
# ---------------------------------------------------------------------------

class TestListOwnFiles:
    """SELF-01: list_own_files returns sorted source file paths."""

    def test_returns_dict_with_files_key(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "files" in result, f"Missing 'files' key: {result}"

    def test_count_key_matches_files_length(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert result["count"] == len(result["files"])

    def test_root_key_is_absolute_path(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert Path(result["root"]).is_absolute()

    def test_no_git_files_leaked(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert all(not f.startswith(".git/") for f in result["files"]), \
            ".git/ files leaked into listing"

    def test_no_pycache_files_leaked(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert all("__pycache__" not in f for f in result["files"]), \
            "__pycache__ files leaked"

    def test_no_pyc_files(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert all(not f.endswith(".pyc") for f in result["files"]), \
            ".pyc files leaked"

    def test_no_env_files_leaked(self):
        mod = _import_module()
        result = mod.list_own_files()
        env_files = [f for f in result["files"] if Path(f).name.startswith(".env")]
        assert not env_files, f".env files leaked: {env_files}"

    def test_self_inspect_py_is_included(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert "mcp_tools/self_inspect.py" in result["files"], \
            "self_inspect.py not listed in own files"

    def test_subdir_filter_mcp_tools(self):
        mod = _import_module()
        result = mod.list_own_files("mcp_tools")
        assert "files" in result
        assert all(f.startswith("mcp_tools/") for f in result["files"]), \
            f"subdir filter broken, non-mcp_tools paths returned: {result['files'][:3]}"

    def test_subdir_nonexistent_returns_error(self):
        mod = _import_module()
        result = mod.list_own_files("nonexistent_dir_xyz")
        assert "error" in result, f"Expected error for nonexistent subdir: {result}"

    def test_subdir_traversal_blocked(self):
        mod = _import_module()
        result = mod.list_own_files("../../etc")
        assert "error" in result, f"Path traversal in subdir not blocked: {result}"

    def test_returns_nonempty_list(self):
        mod = _import_module()
        result = mod.list_own_files()
        assert result["count"] > 0, "No files returned by list_own_files"


# ---------------------------------------------------------------------------
# SELF-02: read_own_source
# ---------------------------------------------------------------------------

class TestReadOwnSource:
    """SELF-02: read_own_source enforces denylist and path safety."""

    def test_safe_file_returns_content(self):
        mod = _import_module()
        result = mod.read_own_source("mcp_tools/self_inspect.py")
        assert "content" in result, f"Expected content key: {result}"
        assert "list_own_files" in result["content"], \
            "Self-read content sanity check failed"

    def test_safe_file_returns_path_key(self):
        mod = _import_module()
        result = mod.read_own_source("mcp_tools/self_inspect.py")
        assert "path" in result
        assert result["path"] == "mcp_tools/self_inspect.py"

    def test_safe_file_returns_lines_key(self):
        mod = _import_module()
        result = mod.read_own_source("mcp_tools/self_inspect.py")
        assert "lines" in result
        assert isinstance(result["lines"], int)
        assert result["lines"] > 0

    def test_env_file_denied(self):
        mod = _import_module()
        result = mod.read_own_source(".env")
        assert "error" in result, f".env not denied: {result}"
        assert "content" not in result, ".env content leaked"

    def test_env_star_denied(self):
        mod = _import_module()
        # .env.local pattern
        result = mod.read_own_source(".env.local")
        assert "error" in result, f".env.local not denied: {result}"

    def test_path_traversal_blocked(self):
        mod = _import_module()
        result = mod.read_own_source("../../etc/passwd")
        assert "error" in result, f"Path traversal not blocked: {result}"
        assert "content" not in result, "Traversal content leaked"

    def test_absolute_path_blocked(self):
        mod = _import_module()
        result = mod.read_own_source("/etc/passwd")
        assert "error" in result, f"Absolute path not blocked: {result}"

    def test_nonexistent_file_returns_error(self):
        mod = _import_module()
        result = mod.read_own_source("nonexistent_file_xyz.py")
        assert "error" in result, f"Missing file should return error: {result}"

    def test_json_file_denied(self):
        mod = _import_module()
        # *.json matches the denylist (OAuth JSON files)
        result = mod.read_own_source("credentials.json")
        assert "error" in result, f".json file not denied: {result}"

    def test_secret_pattern_denied(self):
        mod = _import_module()
        result = mod.read_own_source("config/my_secret_key.txt")
        assert "error" in result, f"*secret* pattern not denied: {result}"

    def test_token_pattern_denied(self):
        mod = _import_module()
        result = mod.read_own_source("auth/token_store.py")
        assert "error" in result, f"*token* pattern not denied: {result}"


# ---------------------------------------------------------------------------
# SELF-03: search_own_source
# ---------------------------------------------------------------------------

class TestSearchOwnSource:
    """SELF-03: search_own_source returns line-level matches."""

    def test_known_symbol_found(self):
        mod = _import_module()
        result = mod.search_own_source("list_own_files")
        assert "matches" in result, f"Missing matches key: {result}"
        assert result["total"] > 0, "Expected matches for 'list_own_files'"

    def test_matches_have_required_keys(self):
        mod = _import_module()
        result = mod.search_own_source("list_own_files")
        for match in result["matches"]:
            assert "file" in match, f"Match missing 'file': {match}"
            assert "line" in match, f"Match missing 'line': {match}"
            assert "snippet" in match, f"Match missing 'snippet': {match}"

    def test_line_numbers_are_positive_int(self):
        mod = _import_module()
        result = mod.search_own_source("list_own_files")
        for match in result["matches"]:
            assert isinstance(match["line"], int)
            assert match["line"] >= 1

    def test_nonexistent_query_returns_empty(self):
        mod = _import_module()
        # Build the absent query at runtime to avoid the literal appearing in source
        # so the search never finds itself in this test file.
        absent = bytes.fromhex("5a5151515f4e4f545f494e5f534f555243455f5a5151").decode()
        result = mod.search_own_source(absent)
        assert "matches" in result
        assert result["matches"] == [], f"Expected empty list: {result['matches']}"
        assert result["total"] == 0

    def test_empty_query_returns_error(self):
        mod = _import_module()
        result = mod.search_own_source("")
        assert "error" in result, f"Empty query not rejected: {result}"

    def test_whitespace_only_query_returns_error(self):
        mod = _import_module()
        result = mod.search_own_source("   ")
        assert "error" in result, f"Whitespace-only query not rejected: {result}"

    def test_max_results_respected(self):
        mod = _import_module()
        result = mod.search_own_source("def ", max_results=5)
        assert len(result["matches"]) <= 5

    def test_query_key_in_result(self):
        mod = _import_module()
        result = mod.search_own_source("list_own_files")
        assert "query" in result
        assert result["query"] == "list_own_files"

    def test_case_insensitive_search(self):
        mod = _import_module()
        lower = mod.search_own_source("list_own_files")
        upper = mod.search_own_source("LIST_OWN_FILES")
        # Both should find the same total matches (case-insensitive)
        assert lower["total"] == upper["total"], \
            f"Case-insensitive mismatch: lower={lower['total']}, upper={upper['total']}"

    def test_no_secrets_in_search_results(self):
        mod = _import_module()
        # Searching for something that might appear in .env — results should not
        # include snippets from denied files
        result = mod.search_own_source("TELEGRAM_BOT_TOKEN")
        for match in result["matches"]:
            # Denied files must not appear in results
            assert not match["file"].startswith(".env"), \
                f".env file appeared in search results: {match}"

    def test_llm_usage_store_found(self):
        """SELF-01 success criterion: LLMUsageStore exists in memory/firestore_db.py."""
        mod = _import_module()
        result = mod.search_own_source("LLMUsageStore")
        assert result["total"] >= 1, \
            f"LLMUsageStore not found — expected in memory/firestore_db.py; total={result['total']}"

    def test_total_key_present(self):
        mod = _import_module()
        result = mod.search_own_source("def ")
        assert "total" in result
        assert isinstance(result["total"], int)
