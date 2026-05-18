# Phase 15: Codebase Self-Knowledge - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Klaus gains 3 new tools — `list_own_files`, `read_own_source`, `search_own_source` — that let him read and search his own deployed source code at conversation time. These are brain-direct tools (excluded from the worker). The phase also updates `prompts/smart_agent.md` to tell Klaus these tools exist.

</domain>

<decisions>
## Implementation Decisions

### Conversation Behavior
- **D-01:** When Klaus uses self-inspect tools to answer a question, he answers directly without narrating that he is reading source. He surfaces the answer, not the mechanism.

### Tool Access Policy
- **D-02:** All 3 self-inspect tools are brain-only (direct tools), excluded from the worker — same pattern as `remember`, `recall`, `search_chat_history`. They go into `SMART_AGENT_DIRECT_TOOLS` and are excluded from `WORKER_TOOL_SCHEMAS`.

### Claude's Discretion
- Source root discovery strategy (env var vs `__file__`-relative)
- Search output format (line-level snippets with file + line_num + context)
- `list_own_files` file type scope and exclusion rules
- Denylist implementation for `read_own_source`
- How to phrase the self-inspection capability in `prompts/smart_agent.md`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §"Codebase Self-Knowledge (Phase 15)" — SELF-01 through SELF-05, all acceptance criteria

### Architecture
- `docs/TECHNICAL_PLAN.md` — LLM-per-purpose map; Phase 15 is referenced as a consumer of this table

### Integration Points
- `core/tools.py` — 5 registration sites: `TOOL_SCHEMAS`, `SMART_AGENT_DIRECT_TOOLS`, `WORKER_TOOL_SCHEMAS` exclusion, `_HANDLERS`, handler functions
- `prompts/smart_agent.md` — prompt file to update

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `mcp_tools/` — convention for new tool modules (one file per integration)
- `SMART_AGENT_DIRECT_TOOLS` frozenset in `core/tools.py:39` — add all 3 tools here
- `WORKER_TOOL_SCHEMAS` filter in `core/tools.py:600-603` — exclusion by name

### Established Patterns
- Handler functions defined as `_handle_<tool_name>(**args)` in `core/tools.py`
- `_HANDLERS` dict maps tool name → lambda wrapper at `core/tools.py:995`
- Tool descriptions include "Call this directly — do NOT delegate to the worker." for direct tools (see lines 202, 232, 256)

### Integration Points
- `mcp_tools/self_inspect.py` (NEW) — 3 tool functions called by `core/tools.py` handlers
- `core/tools.py` — single file, 5 edit sites
- `prompts/smart_agent.md` — add a brief self-inspection capability note

</code_context>

<specifics>
## Specific Ideas

- No specific references — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 15-codebase-self-knowledge*
*Context gathered: 2026-05-18*
