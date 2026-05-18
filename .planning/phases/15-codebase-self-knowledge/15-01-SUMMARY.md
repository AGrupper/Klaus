---
phase: 15-codebase-self-knowledge
plan: "01"
subsystem: mcp_tools
tags: [self-inspection, security, denylist, read-only, tdd]
dependency_graph:
  requires: []
  provides: [mcp_tools/self_inspect.py]
  affects: [core/tools.py (Plan 02 will register these tools)]
tech_stack:
  added: []
  patterns: [fnmatch denylist, Path.resolve() traversal guard, SOURCE_ROOT env override]
key_files:
  created:
    - mcp_tools/self_inspect.py
    - tests/test_self_inspect.py
  modified: []
decisions:
  - "Source root resolved via Path(__file__).resolve().parent.parent (worktree-safe); SOURCE_ROOT env var overrides for Cloud Run"
  - "Double denylist check: once on raw input path, once on resolved relative path (catches symlink tricks)"
  - "list_own_files excludes .env* via _is_excluded_from_listing so secret file names are not leaked even in directory listings"
  - "search_own_source skips denied files entirely before read_text so credential content never enters search results"
  - "TDD: 35 tests written RED-first, implementation written to pass them all GREEN"
metrics:
  duration: "2m 42s"
  completed: "2026-05-18"
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 0
---

# Phase 15 Plan 01: Self-Inspect Module Summary

## One-liner

Read-only codebase self-inspection module with fnmatch denylist and Path.resolve() traversal guard — 3 tool functions, 229 lines, 35 tests green.

## What Was Built

`mcp_tools/self_inspect.py` provides three functions that give Klaus genuine, always-current knowledge of his own deployed source code:

- `list_own_files(subdir=None)` — returns sorted list of relative source file paths from the project root, with optional subdirectory filter. Excludes `.git/`, `__pycache__/`, `*.pyc`, `.env*`, `node_modules/`. Path traversal in the `subdir` argument is blocked via `Path.resolve().relative_to(root)`.

- `read_own_source(path)` — returns file contents for safe relative paths. Rejects: absolute paths (`os.path.isabs`), paths matching the denylist before resolve, paths that resolve outside the project root, and applies a second denylist check on the fully-resolved relative path (catches symlink tricks).

- `search_own_source(query, max_results=20)` — case-insensitive substring search returning `{file, line, snippet}` matches. Skips all denied files before `read_text` so secret content never enters search results.

## Denylist Patterns

`.env`, `.env.*`, `*.env`, `*secret*`, `*credential*`, `*token*`, `*oauth*`, `*.json`, `__pycache__`, `*.pyc`

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (test) | d6d9cbd | 35 tests written, all failing |
| GREEN (feat) | 2b14708 | 35/35 tests passing |
| REFACTOR | — | Not needed — implementation clean on first pass |

## Verification Results

All plan verify commands passed:

```
SELF-01 list_own_files OK: 122 files
SELF-01 subdir OK: 15 files in mcp_tools/
SELF-02 traversal blocked OK
SELF-02 .env denied OK
SELF-02 safe file read OK: 229 lines
SELF-02 absolute path blocked OK
SELF-03 search OK: 91 matches
SELF-03 empty query rejected OK
ALL CHECKS PASSED

Module exports all 3 public functions: ['list_own_files', 'read_own_source', 'search_own_source']
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| d6d9cbd | test | RED: 35 failing tests for SELF-01/02/03 |
| 2b14708 | feat | GREEN: full implementation, all 35 tests pass |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed self-referential test string in test_nonexistent_query_returns_empty**

- **Found during:** GREEN phase verification (34/35 passing)
- **Issue:** The test used a literal string `"nonexistent_symbol_xyz_nothing_123"` as the absent query, but `search_own_source` scans the test file itself — so the literal appeared as a match, causing the assertion `total == 0` to fail.
- **Fix:** Rebuilt the absent query at runtime via `bytes.fromhex(...).decode()` so the string never appears as a literal in any scanned source file.
- **Files modified:** `tests/test_self_inspect.py`
- **Commit:** 2b14708 (bundled with GREEN commit)

## Known Stubs

None — all three functions are fully wired to the live filesystem via `_get_source_root()`.

## Threat Flags

All threats in the plan's `<threat_model>` are mitigated in this implementation:

| Threat | Mitigation Applied |
|--------|--------------------|
| T-15-01 Information Disclosure via read_own_source | `_is_denied()` on input + resolved path; fnmatch on both rel path and basename |
| T-15-02 Path Traversal | `os.path.isabs()` check + `Path.resolve().relative_to(root)` guard |
| T-15-03 .env name leak via list_own_files | `_is_excluded_from_listing()` filters `.env*` patterns |
| T-15-04 Secret content leak via search | `_is_denied()` per file before `read_text` |
| T-15-05 DoS via large repo | Accepted — project tree < 200 files |
| T-15-06 SOURCE_ROOT env var misuse | Accepted — operator-controlled only |

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| mcp_tools/self_inspect.py exists | FOUND |
| tests/test_self_inspect.py exists | FOUND |
| 15-01-SUMMARY.md exists | FOUND |
| Commit d6d9cbd (RED) exists | FOUND |
| Commit 2b14708 (GREEN) exists | FOUND |
| min_lines >= 80 (229 actual) | PASSED |
| STATE.md unmodified | CLEAN |
| ROADMAP.md unmodified | CLEAN |
