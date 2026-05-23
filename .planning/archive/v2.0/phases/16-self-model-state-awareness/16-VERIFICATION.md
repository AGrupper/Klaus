---
phase: 16-self-model-state-awareness
verified: 2026-05-18T19:15:00Z
status: human_needed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/6
  gaps_closed:
    - "docs/SELF.md now lists 28 tools including get_self_status (SHA 16cddba5 matches fresh recompute)"
    - "_load_tool_data_fallback() in core/self_manifest.py now includes get_self_status in both the direct set (line 201) and the tools list (line 231)"
  gaps_remaining: []
  regressions: []
deferred:
  - truth: "docs/SELF.md lists all 9 cron jobs (including /cron/reflect and /cron/autonomous-tick)"
    addressed_in: "Phase 17 (JOUR-05) and Phase 18 (AUTO-06)"
    evidence: "JOUR-05: '/cron/reflect route added to interfaces/web_server.py with OIDC auth; Cloud Scheduler runs it daily ~22:00'. AUTO-06: '/cron/autonomous-tick route added'. Phase 16 Plan 01 explicitly hardcodes 7 active crons and marks the other 2 as TODO with a comment in SELF.md."
human_verification:
  - test: "Verify SELF.md injection survives container restart"
    expected: "After Cloud Run cold start, Klaus asked 'what can you do?' returns an answer that includes tool names and honest limits from SELF.md"
    why_human: "Cannot test Cloud Run cold start + Telegram conversation programmatically"
  - test: "Verify self_state bootstrap on first run"
    expected: "Firestore config/self_state doc is created on first startup with identity_summary populated from SELF.md intro paragraph"
    why_human: "Cannot query Firestore config/self_state doc without live GCP credentials"
  - test: "Verify get_self_status tool call from a live conversation"
    expected: "Klaus asked 'what is your current status?' calls get_self_status and returns today's cost, uptime, and message count"
    why_human: "Requires a live Telegram → Cloud Run conversation to test tool dispatch"
---

# Phase 16: Self-Model & State Awareness Verification Report

**Phase Goal:** A detailed, doubt-free manifest of everything Klaus is and can do, injected into every conversation — plus a persistent self-state that survives the 6h conversation reset.
**Verified:** 2026-05-18T19:15:00Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure (previous status: gaps_found, previous score: 5/6)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `generate_manifest()` auto-generates `docs/SELF.md` by introspecting tool schemas, cron routes, model map, memory stores with a content hash (MODEL-01) | VERIFIED | `core/self_manifest.py:404` — `generate_manifest()` present with `_compute_schema_hash()`, `_render_manifest()`, and `__main__` CLI entry. File writes to `docs/SELF.md` and returns `{path, sha, sections}`. |
| 2 | `docs/SELF.md` covers every tool, all active crons, outbound channels, memory layers, honest limits (MODEL-02) | VERIFIED | SELF.md now lists 28 tools including `get_self_status` at line 59. SHA embedded: `16cddba5c7b7d9663ed401f8b77445ac4406ae1b`. Fresh SHA recomputed = `16cddba5c7b7d9663ed401f8b77445ac4406ae1b` — exact match. `_load_tool_data_fallback()` includes `get_self_status` in both the `direct` set (line 201) and the `tools` list (line 231). |
| 3 | `SelfStateStore` persists identity_summary, current_focus, recent_context, mood, updated_at in Firestore config/self_state (MODEL-03) | VERIFIED | `class SelfStateStore` at `memory/firestore_db.py:601`. `bootstrap_if_empty()` seeds all 5 fields. `get()` returns {} on any error and never raises. No regression. |
| 4 | Per-message prompt assembly injects SELF.md digest (stable) + self_state (volatile), stable-first (MODEL-04) | VERIFIED | `core/main.py:253`: `.replace("{self_md}", self._self_md_content)`. `prompts/smart_agent.md` lines 1/3/7 confirm `{self_md}` < `{self_state}` < `{today_date}`. `AgentOrchestrator.__init__` loads SELF.md at line 207 and bootstraps store at line 212. No regression. |
| 5 | `get_self_status` direct tool returns uptime, today's message count, today/month cost; degrades gracefully when journal absent (MODEL-05) | VERIFIED | Registered at all 5 sites: SMART_AGENT_DIRECT_TOOLS (line 47), TOOL_SCHEMAS (line 643), WORKER_TOOL_SCHEMAS exclusion (line 702), `_handle_get_self_status()` (line 1115), `_HANDLERS` (line 1185). No regression. |
| 6 | Heartbeat `check_code()` flags stale SELF.md by comparing embedded SHA (weekly FYI tier) (MODEL-06) | VERIFIED | `core/heartbeat.py:475–515`: SHA extracted via regex; fresh SHA recomputed using identical algorithm. Appends `fingerprint="code:self-md-stale"` signal at `SEVERITY_FYI`. Gated `if weekly:`. SHA now matches (16cddba5) — mechanism confirmed correct. |

**Score: 6/6 truths verified**

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | SELF.md lists /cron/reflect (9th cron) | Phase 17 | JOUR-05: "/cron/reflect route added to interfaces/web_server.py with OIDC auth". Phase 16 Plan 01 intentionally hardcodes 7 active crons and adds a `<!-- TODO Phase 17: /cron/reflect; Phase 18: /cron/autonomous-tick -->` comment. |
| 2 | SELF.md lists /cron/autonomous-tick (10th cron) | Phase 18 | AUTO-06: "/cron/autonomous-tick route added; Cloud Scheduler fires */20 7-21 * * *". |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/self_manifest.py` | generate_manifest() + _compute_schema_hash() + CLI | VERIFIED | All functions present. `_load_tool_data_fallback()` now includes `get_self_status` at lines 201 and 231. |
| `docs/SELF.md` | 7-section capability manifest with SHA comment, 28 tools | VERIFIED | 28 tools confirmed (grep count). `get_self_status` present at line 59. SHA `16cddba5` embedded and matches fresh recompute exactly. |
| `memory/firestore_db.py` | SelfStateStore class | VERIFIED | `class SelfStateStore` at line 601 with `get()`, `set()`, `bootstrap_if_empty()`. |
| `core/main.py` | SELF.md + self_state injection at prompt render | VERIFIED | `_load_self_md()` at line 207, `_build_self_state_store()` at line 212, `.replace("{self_md}", ...)` at line 253. |
| `prompts/smart_agent.md` | {self_md} and {self_state} placeholders before {today_date} | VERIFIED | Line 1: `{self_md}`, line 3: `{self_state}`, line 7: `{today_date}`. Ordering correct. |
| `core/tools.py` | get_self_status at all 5 sites | VERIFIED | Lines 47, 643, 702, 1115, 1185 confirmed. |
| `core/heartbeat.py` | check_code() SHA staleness block | VERIFIED | Block at lines 475–515. SHA now matching — check will pass on next weekly run. |
| `.github/workflows/deploy.yml` | Generate SELF.md step before docker build | VERIFIED | Lines 46–47: `python core/self_manifest.py`, before docker build at line 49. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `core/self_manifest.py generate_manifest()` | `docs/SELF.md` | `out_path.write_text()` | WIRED | Line 422: `out_path.write_text(content, ...)` |
| `memory/firestore_db.py SelfStateStore` | Firestore config/self_state | `_doc_ref.set(merge=True)` | WIRED | `_COLLECTION = "config"`, `_DOCUMENT = "self_state"` |
| `core/main.py AgentOrchestrator.handle_message` | `prompts/smart_agent.md {self_md}` | `.replace("{self_md}", self._self_md_content)` | WIRED | `core/main.py:253` |
| `core/main.py AgentOrchestrator.__init__` | `memory/firestore_db.py SelfStateStore` | `_build_self_state_store()` | WIRED | `core/main.py:212` |
| `core/tools.py _handle_get_self_status` | `memory/firestore_db.py LLMUsageStore.summary()` | direct function call | WIRED | Lines 1139–1147 |
| `core/heartbeat.py check_code()` | `docs/SELF.md <!-- sha: ... --> line` | regex extraction + fresh hash | WIRED | Lines 484–500 |
| `.github/workflows/deploy.yml` | `core/self_manifest.py` | `run: python core/self_manifest.py` | WIRED | Line 47 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `prompts/smart_agent.md` (via main.py render) | `self._self_md_content` | `_load_self_md()` reads `docs/SELF.md` from disk at startup | Yes — reads committed SELF.md file; fallback is empty string with warning | FLOWING |
| `core/main.py` handle_message self_state_snippet | `self._self_state_store.get()` | Firestore `config/self_state` document | Yes on Cloud Run with GCP_PROJECT_ID set; empty string if unavailable | FLOWING (Firestore not verifiable locally) |
| `core/tools.py _handle_get_self_status` | `uptime_seconds` | `/proc/uptime` (Linux) | Yes on Cloud Run; "unavailable" string on macOS — graceful degradation | FLOWING |
| `core/tools.py _handle_get_self_status` | `today_data`, `month_data` | `LLMUsageStore.summary("today"/"month")` → Firestore `llm_usage/{date}` | Yes on Cloud Run with GCP_PROJECT_ID set; "unavailable" string otherwise | FLOWING (Firestore not verifiable locally) |

### Behavioral Spot-Checks

Step 7b: SKIPPED for most checks — no runnable entry point without GCP credentials (Cloud Run environment required for Firestore, Telegram).

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| generate_manifest() produces SELF.md with 28 tools | `grep -c "^\| \`" docs/SELF.md` | 28 | PASS |
| get_self_status present in SELF.md Tools table | `grep "get_self_status" docs/SELF.md` | Line 59: brain-direct entry confirmed | PASS |
| _load_tool_data_fallback() includes get_self_status | `grep -n "get_self_status" core/self_manifest.py` | Lines 201 (direct set) and 231 (tools list) | PASS |
| SELF.md SHA matches fresh recompute | Python SHA recompute | Stored=16cddba5, Fresh=16cddba5 — exact match | PASS |
| get_self_status in SMART_AGENT_DIRECT_TOOLS | Grep core/tools.py line 47 | `"get_self_status"` present | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MODEL-01 | 16-01-PLAN.md | `generate_manifest()` auto-generates `docs/SELF.md` with SHA/content hash | SATISFIED | `core/self_manifest.py:404` fully implements `generate_manifest()` + `_compute_schema_hash()`. SELF.md written with embedded `<!-- sha: ... -->` |
| MODEL-02 | 16-01-PLAN.md | `docs/SELF.md` covers every tool, every cron (all 9 including new ones), channels, limits | SATISFIED | SELF.md now lists 28/28 tools including `get_self_status`. 7 active crons listed; 2 Phase 17/18 crons deferred per plan design. SHA fresh and matching. |
| MODEL-03 | 16-01-PLAN.md | `SelfStateStore` persists identity_summary, current_focus, recent_context, mood, updated_at | SATISFIED | All 5 fields seeded in `bootstrap_if_empty()`. `get()` never raises. `set()` raises on failure for caller handling. |
| MODEL-04 | 16-02-PLAN.md | Per-message prompt assembly injects SELF.md (stable) + self_state (volatile), stable-first | SATISFIED | `core/main.py:253` stable-first chained `.replace()`. `prompts/smart_agent.md` placeholders at lines 1, 3, 7. |
| MODEL-05 | 16-03-PLAN.md | `get_self_status` direct tool returns uptime, message count, today/month cost, degrades gracefully | SATISFIED | All 5 registration sites confirmed. Returns uptime, costs, message count, journal=null. Never raises. |
| MODEL-06 | 16-04-PLAN.md | Heartbeat `check_code()` flags stale `SELF.md` by comparing embedded SHA (weekly FYI tier) | SATISFIED | Block at heartbeat.py:475–515. Fires `SEVERITY_FYI` signal `code:self-md-stale` when stored != fresh. SHA now matching — mechanism confirmed correct. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `.github/workflows/deploy.yml` | 47 | `python core/self_manifest.py` with no preceding `pip install` | Warning | CR-02: If python-dotenv is not pre-installed on the runner, manifest step may fail on `import dotenv` in transitive deps. ubuntu-latest typically has python-dotenv pre-installed but not guaranteed. Not a Phase 16 blocker. |
| `core/heartbeat.py` | 673 | `asyncio.get_event_loop().run_until_complete()` in async context | Warning | WR-01 (pre-existing): calling `run_until_complete()` from inside a running event loop raises `RuntimeError` on Python 3.10+. Not introduced by Phase 16; not a Phase 16 blocker. |

No blockers. The MODEL-02 gap is closed. The remaining anti-patterns are pre-existing warnings carried from the initial verification.

### Human Verification Required

#### 1. SELF.md Injection End-to-End

**Test:** Deploy to Cloud Run and send a Telegram message: "What exactly can you do? Give me the complete list."
**Expected:** Klaus returns an exhaustive answer covering all 28 tools (including get_self_status), all 7 active cron jobs, the outbound channels, and honest limits including "Telegram-only" and "Gmail read-only." The answer should not hallucinate any capabilities not in SELF.md.
**Why human:** Cannot test Telegram conversation + Cloud Run prompt assembly without live deployment.

#### 2. SelfStateStore Bootstrap in Firestore

**Test:** On first deploy after Phase 16, inspect the Firestore `config/self_state` document.
**Expected:** Document exists with `identity_summary` containing the Klaus persona paragraph from SELF.md Identity section. Fields `current_focus`, `recent_context`, `mood` are empty strings. `bootstrapped_at` and `updated_at` are server timestamps.
**Why human:** Requires GCP Console / Firestore access to verify document existence and field values.

#### 3. get_self_status Tool Dispatch

**Test:** Send "What's your current operational status?" to Klaus in a live conversation.
**Expected:** Klaus calls `get_self_status` directly (brain-direct, not via delegate_to_worker), and responds with today's LLM cost in USD, today's message count, container uptime, and notes that the journal field is blank pending Phase 17.
**Why human:** Requires live Telegram → Cloud Run round trip to verify tool dispatch routing and response content.

### Gaps Summary

All automated gaps are closed. The single MODEL-02 gap from the initial verification has been resolved:

- `docs/SELF.md` now lists 28 tools (was 27). `get_self_status` is present at line 59 with routing `brain-direct`.
- SHA `16cddba5c7b7d9663ed401f8b77445ac4406ae1b` embedded in SELF.md matches the fresh recompute exactly — the heartbeat's staleness check will now correctly pass on its next weekly run.
- `_load_tool_data_fallback()` in `core/self_manifest.py` now includes `get_self_status` in both the `direct` set (line 201) and the `tools` list (line 231), closing the CI dry-run fallback gap (WR-02 from initial verification).

Phase 16 goal is fully achieved at the automated verification level. Three human verification items remain — all require live Cloud Run + Firestore access and cannot be verified programmatically.

---

_Verified: 2026-05-18T19:15:00Z_
_Verifier: Claude (gsd-verifier)_
