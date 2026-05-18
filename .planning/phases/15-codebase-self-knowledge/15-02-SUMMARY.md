---
phase: 15-codebase-self-knowledge
plan: "02"
subsystem: core
tags: [tool-registration, self-inspection, brain-only, direct-tools, prompt-engineering]
dependency_graph:
  requires: [mcp_tools/self_inspect.py (Plan 01)]
  provides: [core/tools.py (5 registration sites), prompts/smart_agent.md (self-inspection section)]
  affects: [agent orchestrator (SMART_AGENT_DIRECT_TOOLS), worker agent (WORKER_TOOL_SCHEMAS exclusion)]
tech_stack:
  added: []
  patterns: [brain-only direct tools via SMART_AGENT_DIRECT_TOOLS frozenset, lazy-singleton import block, handler function + lambda dispatch pattern]
key_files:
  created: []
  modified:
    - core/tools.py
    - prompts/smart_agent.md
decisions:
  - "All 3 self-inspect tools registered as brain-only (D-02): added to SMART_AGENT_DIRECT_TOOLS and excluded from WORKER_TOOL_SCHEMAS"
  - "D-01 enforced in prompts/smart_agent.md: 'surface the answer directly — do not narrate the process'"
  - "Import placed in the lazy-singleton block (after line 620) to avoid triggering network I/O at module load time"
  - "Handler functions follow the established _handle_<tool_name>(**args) -> str pattern, wrapping self_inspect functions with json.dumps"
metrics:
  duration: "3m 32s"
  completed: "2026-05-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 2
---

# Phase 15 Plan 02: Tool Registration Summary

## One-liner

Wired the three self-inspect functions from Plan 01 into core/tools.py at all 5 required registration sites and added a CODEBASE SELF-INSPECTION section to prompts/smart_agent.md — Klaus can now read his own source on demand.

## What Was Built

### Task 1: core/tools.py — All 5 Registration Sites

**SITE 1 — SMART_AGENT_DIRECT_TOOLS** (line 39): Expanded the frozenset to include `list_own_files`, `read_own_source`, `search_own_source`. The orchestrator uses this set to route direct-calls and suppress "unexpected direct call" warnings.

**SITE 2 — TOOL_SCHEMAS** (before `delegate_to_worker`): Appended three schema dicts, each with "Call this directly — do NOT delegate to the worker." in the description. The LLM reads these descriptions to understand when and how to call the tools.

**SITE 3 — WORKER_TOOL_SCHEMAS** (exclusion set): Extended the filter set to exclude all 3 tool names. The worker agent (Gemini Flash) never sees these tools in its schema list.

**SITE 4 — Import block**: Added `from mcp_tools.self_inspect import list_own_files as _list_own_files, read_own_source as _read_own_source, search_own_source as _search_own_source` in the lazy-singleton block after the TickTick import.

**SITE 5 — Handler functions + _HANDLERS dict**: Added three handler functions (`_handle_list_own_files`, `_handle_read_own_source`, `_handle_search_own_source`) and three lambda entries in `_HANDLERS` mapping tool names to their handlers.

### Task 2: prompts/smart_agent.md — CODEBASE SELF-INSPECTION Section

Appended a new section after LONG-TERM MEMORY with:
- Usage rules for all three tools (list_own_files, read_own_source, search_own_source)
- Explicit "never via delegate_to_worker" instruction
- D-01 behavior rule: "surface the answer directly — do not narrate the process"

## Verification Results

Combined end-to-end verification passed:

```
ALL REGISTRATION SITES VERIFIED
prompts/smart_agent.md VERIFIED
```

Individual dispatch tests:
```
Site 1 SMART_AGENT_DIRECT_TOOLS OK
Site 2 TOOL_SCHEMAS OK
Site 3 WORKER_TOOL_SCHEMAS exclusion OK
Site 4+5 dispatch list_own_files OK: 118 files
Site 4+5 dispatch read_own_source denylist OK
Site 4+5 dispatch read_own_source safe file OK: 1179 lines
Site 4+5 dispatch search_own_source OK: 36 matches
ALL 5 REGISTRATION SITES VERIFIED
```

Success criterion 5 — `dispatch('search_own_source', {'query': 'LLMUsageStore'})` returns 96 matches including `memory/firestore_db.py`.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| b3734cb | feat | Register self-inspect tools at all 5 sites in core/tools.py |
| c494208 | feat | Add CODEBASE SELF-INSPECTION section to prompts/smart_agent.md |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all three handlers call the live self_inspect functions directly with no mocking or hardcoded returns.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-15-07 mitigated | core/tools.py | WORKER_TOOL_SCHEMAS exclusion set now contains all 3 tool names — verified by dispatch test that worker_names excludes list_own_files, read_own_source, search_own_source |

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| core/tools.py exists | FOUND |
| prompts/smart_agent.md exists | FOUND |
| Commit b3734cb (Task 1) exists | FOUND |
| Commit c494208 (Task 2) exists | FOUND |
| SMART_AGENT_DIRECT_TOOLS contains all 3 tools | PASSED |
| TOOL_SCHEMAS contains all 3 schemas with direct-call notice | PASSED |
| WORKER_TOOL_SCHEMAS excludes all 3 tools | PASSED |
| dispatch list_own_files returns files+count | PASSED |
| dispatch read_own_source .env returns error | PASSED |
| dispatch search_own_source returns matches | PASSED |
| prompts/smart_agent.md contains CODEBASE SELF-INSPECTION | PASSED |
| prompts/smart_agent.md contains do not narrate | PASSED |
| STATE.md unmodified | CLEAN |
| ROADMAP.md unmodified | CLEAN |
