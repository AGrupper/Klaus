"""Codebase self-inspection tools for the Klaus agent.

Provides three functions that let Klaus read and search his own deployed source
at conversation time. These functions are intentionally read-only and apply a
secret denylist so Klaus can never expose credentials via tool output.

Registration: core/tools.py registers these as SMART_AGENT_DIRECT_TOOLS
(brain-only, never delegated to the worker).
"""
from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source root discovery
# ---------------------------------------------------------------------------
# mcp_tools/ lives one level below the project root.  Path(__file__).parent.parent
# resolves to the project root whether the file is imported from Cloud Run or
# a local dev environment.  SOURCE_ROOT env var overrides for flexibility.

def _get_source_root() -> Path:
    env_override = os.environ.get("SOURCE_ROOT")
    if env_override:
        return Path(env_override).resolve()
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Secret denylist — patterns matched against relative paths and basenames
# ---------------------------------------------------------------------------
_DENYLIST_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.env",
    "*secret*",
    "*credential*",
    "*token*",
    "*oauth*",
    "*.json",        # OAuth JSON files at root level
    "__pycache__",
    "*.pyc",
)

def _is_denied(rel_path: str) -> bool:
    """Return True if rel_path matches any denylist pattern.

    Checks both the full relative path and just the basename so that patterns
    like '*secret*' match 'config/my_secret_key.txt' and 'my_secret_key.txt'.
    """
    basename = Path(rel_path).name
    for pattern in _DENYLIST_PATTERNS:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(basename, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Filesystem exclusion patterns for listing
# ---------------------------------------------------------------------------
_EXCLUDE_DIRS: frozenset[str] = frozenset({"__pycache__", ".git", "node_modules"})
_EXCLUDE_PATTERNS: tuple[str, ...] = ("*.pyc", ".env", ".env.*", "*.env")


def _is_excluded_from_listing(rel_path: str) -> bool:
    """Return True if a path should be omitted from list_own_files output."""
    parts = Path(rel_path).parts
    for part in parts:
        if part in _EXCLUDE_DIRS:
            return True
    basename = Path(rel_path).name
    for pattern in _EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(basename, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def list_own_files(subdir: str | None = None) -> dict[str, Any]:
    """List Klaus's deployed source files.

    Args:
        subdir: Optional relative subdirectory path (e.g. 'mcp_tools').
                When provided, only files within that directory are returned.
                When None, all source files from the project root are listed.

    Returns:
        {"files": ["path/to/file.py", ...], "count": N, "root": "/abs/path"}
    """
    root = _get_source_root()

    if subdir:
        search_root = (root / subdir).resolve()
        # Prevent path traversal in subdir argument
        try:
            search_root.relative_to(root)
        except ValueError:
            return {"error": f"Access denied: subdir '{subdir}' is outside the project root."}
        if not search_root.exists():
            return {"error": f"Directory not found: {subdir}"}
    else:
        search_root = root

    files: list[str] = []
    for abs_path in sorted(search_root.rglob("*")):
        if abs_path.is_dir():
            continue
        try:
            rel = abs_path.relative_to(root).as_posix()
        except ValueError:
            continue
        if _is_excluded_from_listing(rel):
            continue
        files.append(rel)

    return {"files": files, "count": len(files), "root": str(root)}


def read_own_source(path: str) -> dict[str, Any]:
    """Return the contents of a source file by relative path.

    Rejects:
    - Absolute paths
    - Path traversal (anything that resolves outside the project root)
    - Paths matching the secret denylist (.env*, *secret*, *credential*,
      *token*, *oauth*, *.json, __pycache__/, *.pyc)

    Args:
        path: Relative path from project root (e.g. 'core/tools.py').

    Returns:
        {"path": "core/tools.py", "content": "<file contents>", "lines": N}
        or {"error": "<reason>"} on denial or missing file.
    """
    if os.path.isabs(path):
        return {"error": "Access denied: absolute paths are not permitted. Use a relative path from the project root."}

    if _is_denied(path):
        return {"error": f"Access denied: '{path}' matches the secret denylist and cannot be read."}

    root = _get_source_root()
    target = (root / path).resolve()

    # Path traversal guard — resolved path must still be inside the project root
    try:
        target.relative_to(root)
    except ValueError:
        return {"error": f"Access denied: '{path}' resolves outside the project root."}

    if not target.exists():
        return {"error": f"File not found: '{path}'"}

    if not target.is_file():
        return {"error": f"Not a file: '{path}'"}

    # Final denylist check on the resolved relative path (catches symlink tricks)
    final_rel = target.relative_to(root).as_posix()
    if _is_denied(final_rel):
        return {"error": f"Access denied: resolved path '{final_rel}' matches the secret denylist."}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("read_own_source: cannot read %s: %s", target, exc)
        return {"error": f"Cannot read file: {exc}"}

    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return {"path": final_rel, "content": content, "lines": lines}


def search_own_source(query: str, max_results: int = 20) -> dict[str, Any]:
    """Full-text search across Klaus's source files.

    Performs a case-insensitive substring search on every non-denied source file.
    Returns line-level results: file path, 1-based line number, and the matching
    line content (stripped).

    Args:
        query: Substring to search for (case-insensitive).
        max_results: Maximum number of matches to return (default 20).

    Returns:
        {"matches": [{"file": "...", "line": N, "snippet": "..."}, ...], "total": M}
        where total is the number of matches found before the max_results cap.
    """
    if not query or not query.strip():
        return {"error": "query must be a non-empty string."}

    root = _get_source_root()
    needle = query.lower()
    matches: list[dict[str, Any]] = []
    total = 0

    for abs_path in sorted(root.rglob("*")):
        if abs_path.is_dir():
            continue
        try:
            rel = abs_path.relative_to(root).as_posix()
        except ValueError:
            continue
        if _is_excluded_from_listing(rel):
            continue
        if _is_denied(rel):
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                total += 1
                if len(matches) < max_results:
                    matches.append({
                        "file": rel,
                        "line": lineno,
                        "snippet": line.strip(),
                    })

    return {"matches": matches, "total": total, "query": query}
