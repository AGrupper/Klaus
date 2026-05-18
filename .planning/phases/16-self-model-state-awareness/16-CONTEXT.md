# Phase 16: Self-Model & State Awareness - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Klaus gains a static capability manifest (`docs/SELF.md`) auto-generated from live source, a persistent `SelfStateStore` in Firestore that survives conversation resets, a `get_self_status` direct tool, and full-file SELF.md injection into every `smart_system` prompt. The heartbeat gains a weekly SHA staleness check on SELF.md.

Scope is MODEL-01 through MODEL-06. Phase 17 owns reflection logic and journal writes; Phase 16 creates the store but leaves `current_focus`, `recent_context`, `mood` empty.

</domain>

<decisions>
## Implementation Decisions

### Manifest Generation & Refresh
- **D-01:** `generate_manifest()` runs as a CI step in `cloudbuild.yaml` on every deploy — SELF.md is always regenerated before the new image is deployed. No manual script needed; heartbeat SHA check (`check_code()`) remains as a safety net only (flags stale on weekly run, does NOT re-generate).
- **D-02:** `generate_manifest()` writes `docs/SELF.md` to disk (static file, CI-safe). It does NOT write to Firestore at build time — no CI-to-Firestore coupling.

### SELF.md Prompt Injection
- **D-03:** Full SELF.md content is injected into `smart_system` only (not worker). Stable content — benefits from Gemini prompt cache after the first message. Insertion point: `core/main.py` render step alongside the existing `{today_date}` replacement, stable-content-first ordering per MODEL-04.

### SelfStateStore Bootstrapping
- **D-04:** On Cloud Run startup, `AgentOrchestrator.__init__` calls `SelfStateStore.bootstrap_if_empty(identity_summary=<SELF.md intro paragraph>)`. This seeds the Firestore doc once if it doesn't exist. Phase 17 `run_reflection()` can overwrite all fields. The intro paragraph is the single source of truth — lives in SELF.md, copied to Firestore on first boot.
- **D-05:** Fields `current_focus`, `recent_context`, `mood` are empty strings / null in Phase 16. Injected self_state shows `identity_summary` only; blank fields are omitted from the injected snippet (don't show "mood: null" in the prompt).

### get_self_status Tool
- **D-06:** "Today's message count" is proxied via `LLMUsageStore` — count records for today where `purpose='smart_agent'`. Zero new infrastructure; reuses the cost data already being read. One brain call ≈ one user message.
- **D-07:** `get_self_status` is a brain-direct tool (added to `SMART_AGENT_DIRECT_TOOLS`, excluded from worker). Same registration pattern as `remember`, `recall`, `list_own_files`.

### Heartbeat Staleness Check
- **D-08:** `generate_manifest()` embeds a SHA/content hash in `docs/SELF.md` as a comment or metadata line. `check_code()` compares this hash against a fresh hash of the current tool schemas + cron routes. Fires as `severity=SEVERITY_FYI`, tier `"weekly"` — same tier as existing doc-drift check.

### Claude's Discretion
- SELF.md file structure and section layout (tools, crons, channels, limits)
- SHA/hash embedding format in SELF.md
- Exact injection placement within `smart_system` template (before or after existing content)
- `SelfStateStore.get()` graceful fallback when Firestore unavailable (return empty dict, never raise)
- `get_self_status` uptime definition (Cloud Run container start time via `/proc/uptime` or startup timestamp stored at boot)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §"Self-Model & State Awareness (Phase 16)" — MODEL-01 through MODEL-06, all acceptance criteria

### Architecture
- `docs/TECHNICAL_PLAN.md` — LLM-per-purpose map, model names, Firestore database naming
- `docs/AGENT.md` — Klaus persona and behavioral directives (informs identity_summary tone)

### Integration Points
- `core/main.py:219–222` — per-message prompt render step; SELF.md + self_state injection goes here
- `core/tools.py:39` — `SMART_AGENT_DIRECT_TOOLS` frozenset; `get_self_status` registration
- `core/tools.py:600–603` — `WORKER_TOOL_SCHEMAS` exclusion filter
- `core/tools.py:995+` — `_HANDLERS` dict; `get_self_status` handler lambda
- `core/heartbeat.py:378` — `check_code()` function; extend with SELF.md SHA check
- `memory/firestore_db.py` — Store class patterns (HeartbeatConfigStore, LLMUsageStore) are templates for SelfStateStore
- `memory/firestore_db.py:563` — `LLMUsageStore.summary()` for cost data in `get_self_status`

### Prior Phase Context
- `.planning/phases/15-codebase-self-knowledge/15-CONTEXT.md` — D-02 (direct tool registration pattern)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LLMUsageStore.summary(period="today")` → returns `{today_cost, month_cost, today_calls, month_calls}` — `get_self_status` can call `.summary("today")` and use `today_calls` as message count proxy
- `HeartbeatConfigStore` and `IncidentStore` in `memory/firestore_db.py` — pattern for new `SelfStateStore` (singleton document: `_make_firestore_client`, `.get()`, `.set(patch)` methods)
- `mcp_tools/self_inspect.py` — module structure template for `core/self_manifest.py`

### Established Patterns
- Direct tool registration: 5 sites in `core/tools.py` — `SMART_AGENT_DIRECT_TOOLS`, `TOOL_SCHEMAS`, `WORKER_TOOL_SCHEMAS` exclusion, `_HANDLERS`, `_handle_<name>()` function
- Store pattern: `__init__(project_id, database)` → `_make_firestore_client` → document methods
- Prompt template replacement: `_smart_prompt_template.replace("{today_date}", today_label)` at `main.py:220–221` — add SELF.md and self_state replacements here

### Integration Points
- `AgentOrchestrator.__init__` (`core/main.py:195+`) — add `SelfStateStore.bootstrap_if_empty()` call and load SELF.md content for injection
- `cloudbuild.yaml` — add `python core/self_manifest.py` step before the docker build step

</code_context>

<specifics>
## Specific Ideas

- SELF.md should include an honest "limits" section: Telegram-only outbound, no email send, no WhatsApp autonomous outbound, Pinecone valid kinds `{fact, chunk, chat}` (not `self` until Phase 17). This directly satisfies MODEL-02's "honest current limits" requirement.
- The injected self_state in `smart_system` should be compact: show only non-empty fields. Pre-Phase 17, only `identity_summary` will be present.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 16-self-model-state-awareness*
*Context gathered: 2026-05-18*
