# Technical Architecture & Implementation Plan

## 1. Stack & Infrastructure
* **Language:** Python 3.11+
* **Hosting:** Google Cloud Run (Scales to zero, native integration with Google Cloud IAM/OAuth).
* **Primary Framework:** Raw Python with standard HTTP libraries and the official MCP Python SDK for tool definition. No LangChain or LlamaIndex.
* **State & Memory Database:** * Firestore (Google Cloud) for conversation history, roster, attendance, and briefing state. TickTick Open API for task management.
    * Pinecone (Free Tier) for unstructured memory/RAG.

## 2. Model Architecture
* **Smart Agent (brain):** Gemini 3.5 Flash (`gemini-3.5-flash`) — complex reasoning, tool orchestration, conversation. Fallback: Claude Haiku 4.5 (`claude-haiku-4-5`).
* **Worker Agent (hands):** DeepSeek V4 Flash (`deepseek-v4-flash`) via `openai` backend pointing to `https://api.deepseek.com/v1` — fast structured JSON output, data fetching, routing.
* Both backends are abstracted in `core/llm_client.py`; swappable via env vars (`SMART_AGENT_BACKEND`, `SMART_AGENT_MODEL`, `WORKER_AGENT_BASE_URL`, etc.).

## 3. Tool Development Plan (Custom MCPs)
We will build the following functional blocks:
1.  **Google Auth Manager:** Implements the OAuth 2.0 flow using `credentials.json` from a Google Cloud Project (Internal User Type). Manages token refresh permanently.
2.  **Gmail Tool:** Parses unread emails, summarizes, and extracts action items.
3.  **Calendar Tool:** Reads availability, proposes times, injects events, and deletes events (including paired Get Ready prep blocks for workouts).
4.  **TickTick Task Tool:** Writes tasks directly to TickTick via Open API. `reminder` (YYYY-MM-DDTHH:MM) sets a timed due date with a push notification alarm. `deadline` (YYYY-MM-DD) sets a silent due date. Fully cloud-native — no Mac dependency.

## 4. Execution Phases
* **Phase 1:** Auth and scaffolding. Establish persistent Google OAuth. ✓ Complete.
* **Phase 2:** Build the Router/Main LLM abstraction and the Telegram Bot listener. ✓ Complete — dual-model (Claude brain + Gemini Flash hands), `core/llm_client.py`, `core/main.py`, `interfaces/telegram_bot.py`.
* **Phase 3:** Develop the custom Google Calendar and Gmail tools. ✓ Complete — list, create, free/busy, and delete (with workout prep block cleanup) all live and smoke-tested.
* **Phase 4:** Build task tool. ✓ Originally Things 3 queue (Firestore + Mac daemon). Replaced by TickTick Open API — `mcp_tools/ticktick_tool.py`, `mcp_tools/ticktick_auth.py`. Fully cloud-native, no Mac dependency. `reminder` → dueDate + push alarm; `deadline` → silent due date.
* **Phase 5:** Cloud Run deployment. ✓ Complete — Dockerfile, `interfaces/web_server.py` (FastAPI + Telegram webhook), GitHub Actions CI/CD with Workload Identity Federation, Secret Manager for all API keys.
* **Phase 6:** Conversation persistence + long-term memory. ✓ Complete — `memory/firestore_conversation.py` (Firestore per-user history), `memory/pinecone_db.py` (Pinecone RAG via gemini-embedding-2), `mcp_tools/memory.py` (remember/recall tools).
* **Phase 7:** External connections. ✓ Complete — `mcp_tools/weather_tool.py` (wttr.in), `mcp_tools/readwise_tool.py` (Readwise API), `mcp_tools/garmin_tool.py` (Garmin Connect), all registered as callable tools.
* **Phase 8:** Five Fingers practice helper. ✓ Complete — three cron-driven flows (pre-practice, post-practice attendance, morning-after follow-up). `wa.me` prefilled-link delivery via Telegram DM — no autonomous WhatsApp sending. New Firestore collections: `five_fingers_roster`, `five_fingers_practices`. New modules: `mcp_tools/five_fingers/` (composer, recommender, roster, attendance), `core/five_fingers.py`. Two new Cloud Scheduler jobs + OIDC-protected cron endpoints in `interfaces/web_server.py`. Inline-keyboard attendance entry wired into `interfaces/_router.py`.
* **Phase 9:** Proactive evening alerts. ✓ Complete — nightly Cloud Scheduler job (`30 21 * * *` Asia/Jerusalem) scans tomorrow's calendar and detects weather conflicts, overloaded days, and travel-time violations. Template-based detection (zero LLM cost on quiet days); Smart Agent composes message when alerts exist. `core/proactive_alerts.py` refactored to use `core/scheduled_message.py` (shared Telegram send + Firestore conversation injection). Cloud Scheduler job: `Klaus-proactive-alerts`.
* **Phase 10:** Morning briefing. ✓ Complete — Garmin-sync-anchored daily briefing via Telegram. State machine in Firestore (`morning_briefings/{date}`), polled every 10 min by Cloud Scheduler (`*/10 6-10 * * *` Asia/Jerusalem). Data sources: weather, calendar, Gmail, Garmin, TickTick tasks (real-time Open API, replaces Things 3 snapshot). Briefing injected into conversation history as assistant turn. Manual trigger via Smart Agent tool `run_morning_briefing`. Key modules: `core/morning_briefing.py`, `prompts/morning_briefing.md`. Cloud Scheduler job: `Klaus-morning-briefing-tick`.
* **Phase 11:** Notion integration. ✓ Complete — `mcp_tools/notion_tool.py` (5 tools: search, get_page, query_database, create_page, append_blocks), wired in `core/tools.py`. Internal integration token (`NOTION_API_TOKEN`), no OAuth flow. Read + create/append access. Auth pattern: static token (like `READWISE_TOKEN`).
* **Phase 12:** Claude Code chat-log ingestion. ✓ Complete — `core/chat_ingest.py` (parser, chunker, summarizer, batch controller), daily cron at 04:00 Asia/Jerusalem (`/cron/ingest-chats`). Embeds chunks → Pinecone (`kind="chat"`), summarizes sessions → Notion chat-log DB.
* **Phase 13:** Multi-Source AI Chat Export Ingestion. ✓ Complete — `core/chat_export_ingest.py`, daily cron at 04:30 Asia/Jerusalem (`/cron/ingest-chat-exports`). Ingests ChatGPT, Claude.ai, and Gemini Takeout zips.
* **Phase 14:** LLM Strategy & Cost Metering. ✓ Complete — Model strategy mapping, dual-model configuration (Gemini brain + DeepSeek worker), usage metering and storage in Firestore (`LLMUsageStore`).
* **Phase 15:** Multimodal Telegram Photo Support & Get Ready buffer fix. ✓ Complete — `interfaces/_router.py` (caption extraction + photo download), `core/main.py` (in-memory base64 injection), `core/llm_client.py` (native Gemini/OpenAI vision part conversion), and `mcp_tools/calendar_tool.py` (suppress workout travel for `"Get Ready"` events).


## Phase 12 — Claude Code Chat-Log Ingestion

### Architecture

**Data flow:**
```
Local machine (~/.claude/projects/)
    ↓ gcloud storage rsync (hourly, upload_claude_logs.sh/.ps1)
GCS bucket: gs://CHAT_LOGS_BUCKET/claude-code/{mac,pc}/
    ↓ Cloud Scheduler (0 4 * * * Asia/Jerusalem)
POST /cron/ingest-chats → core.chat_ingest.run_one_batch()
    ↓ parse_claude_code_jsonl (JSONL → ParsedConversation)
    ↓ _chunk_conversation (1800-char windows, 200-char overlap)
    ├── MemoryStore.upsert_chat_chunks → Pinecone (kind="chat")
    └── _summarize (Flash LLM) → notion_tool.upsert_database_row → Notion
```

**New components:**
- `core/chat_ingest.py` — parser, chunker, summarizer, batch controller
- `prompts/chat_summary.md` — Flash system prompt for JSON summary
- `scripts/upload_claude_logs.{sh,ps1}` — rsync wrappers per OS
- Notion chat-log DB — browsable session index (user-created)

**Bounded-batch state machine (Firestore `chat_ingest/state`):**
- `completed` map: `{blob_name: generation}` — generation-token dedup
- Each tick processes ≤8 files within ≤45s, persisting after each file
- Backfill: run `gcloud scheduler jobs run klaus-chat-ingest` repeatedly until `done:true`

**Memory scoping:**
- `recall()` default: `kind $in ["fact", "chunk"]` — chat excluded
- `search_chat_history()` tool: `kind $in ["chat"]` — explicitly scoped
- Pinecone IDs: `cc-{session_id}-{message_uuid}-{chunk_index}` (deterministic)

**IAM:**
- `klaus-log-uploader@{project}.iam.gserviceaccount.com` → `roles/storage.objectCreator` (bucket only)
- Cloud Run runtime SA → `roles/storage.objectViewer` (bucket only)

**GCS bucket:** `klaus-chat-logs-{project-id}`, uniform access, versioning off

## 5. Live Infrastructure (as of Phase 11)
* **Cloud Run service:** `Klaus-agent` — region `me-west1`, project `Klaus-agent`
* **Firestore database:** `Klaus-firestore`
  * Collection `conversations` — per-user conversation history (Phase 6)
  * Collection `five_fingers_roster` — Phase 8 sub-team roster (one doc per teammate)
  * Collection `five_fingers_practices` — Phase 8 attendance log (one doc per practice, ID = YYYY-MM-DD)
  * Collection `morning_briefings/{date}` — Phase 10 state machine + structured metadata
* **Pinecone index:** `Klaus-memory` — serverless, AWS, dimension=768, cosine
* **Cloud Scheduler jobs:**
  * `Klaus-proactive-alerts` — `30 21 * * *` Asia/Jerusalem (Phase 9)
  * `Klaus-morning-briefing-tick` — `*/10 6-10 * * *` Asia/Jerusalem (Phase 10)
  * `Klaus-chat-ingest` — `0 4 * * *` Asia/Jerusalem (Phase 12)
  * `Klaus-chat-export-ingest` — `30 4 * * *` Asia/Jerusalem (Phase 13)
* **Firestore collections:**
  * `chat_ingest/state` — Phase 12 blob-level dedup (`completed` map: blob_name → generation)
  * `chat_export_ingest/state` — Phase 13 conversation-level dedup (`conversations` map: conv_id → update_marker; `completed_blobs` map: blob_name → generation)
* **Secrets in Secret Manager:** `Klaus-anthropic-key`, `Klaus-gemini-key`, `Klaus-telegram-token`, `Klaus-telegram-webhook-secret`, `Klaus-google-oauth-token`, `Klaus-pinecone-key`, `Klaus-home-address`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `READWISE_TOKEN`, `TICKTICK_CLIENT_ID`, `TICKTICK_CLIENT_SECRET`, `TICKTICK_ACCESS_TOKEN`, `TICKTICK_REFRESH_TOKEN`, `NOTION_API_TOKEN`

## Phase 13 — Multi-Source AI Chat Export Ingestion

**Data flow:**
```
~/Downloads/<export>.zip
    ↓ scripts/upload_chat_export.sh <provider> <zip>
gs://CHAT_LOGS_BUCKET/chat-exports/{chatgpt,claude_ai,gemini}/<file>.zip
    ↓ Cloud Scheduler (daily 04:30 Asia/Jerusalem)
POST /cron/ingest-chat-exports → core.chat_export_ingest.run_one_batch()
    ↓ open zip in memory → locate JSON → dispatch by provider
    ↓ parse_{claude_ai,chatgpt,gemini}_export → list[ParsedConversation]
    ↓ conversation-level dedup (Firestore: chat_export_ingest/state)
    ↓ chunk_conversation (1800-char windows, 200 overlap) — shared from Phase 12
    ├── MemoryStore.upsert_chat_chunks → Pinecone (kind="chat", source=<provider>)
    └── summarize_conversation (Flash) → notion_tool → "Klaus AI Chat Imports" DB
```

**New / changed components:**
- `core/chat_export_ingest.py` — three parsers + bounded-batch runner
- `core/chat_ingest.py` — light refactor: `chunk_conversation` / `summarize_conversation` now public; `ParsedConversation.source` field added; `_make_chunk` uses source-derived ID prefix map
- `mcp_tools/notion_tool.py` — `build_ai_chat_properties` for the new DB
- `scripts/upload_chat_export.sh` — uploads a zip to `gs://{CHAT_LOGS_BUCKET}/chat-exports/<provider>/`
- `interfaces/web_server.py` — `/cron/ingest-chat-exports` route

**Pinecone metadata per chunk:**
- `kind="chat"`, `source=<claude_ai|chatgpt|gemini>`, `conversation_id`, `conversation_title`, `role`, `ts`
- ID prefix map: `cc-` (claude_code), `cla-` (claude_ai), `gpt-` (chatgpt), `gem-` (gemini)

**Gemini clustering:**
- Activity log = flat records with `title` ("Prompted …"), `safeHtmlItem[0].html`, `time`
- Sort ascending, cluster by >30-min gap → ~37 conversations from 255 records
- `session_id = sha1(earliest_time)[:16]` — deterministic (activity log is immutable)

## LLM Strategy — Per-Purpose Model Map

Added Phase 14. This table is the authoritative reference for which model handles
each purpose. Phase 15 (self-knowledge) and Phase 16 (SELF.md) ingest this table.

| Purpose | Backend | Model | Env Vars | Notes |
|---------|---------|-------|----------|-------|
| Smart Agent (brain) | gemini | gemini-3.5-flash | SMART_AGENT_BACKEND / MODEL / API_KEY | Orchestration, judgment, crafting responses |
| Worker Agent (hands) | openai (DeepSeek-compat) | deepseek-v4-flash | WORKER_AGENT_BACKEND / MODEL / API_KEY / BASE_URL | Tool execution, data gathering, structured JSON; base_url=https://api.deepseek.com/v1 |
| Smart Agent fallback | anthropic | claude-haiku-4-5 | SMART_AGENT_FALLBACK_BACKEND / MODEL / API_KEY | Activated inline on LLMError from brain |
| Tick-brain | openai (Groq-compat) | qwen3-32b (default) | TICK_BRAIN_BACKEND / MODEL / API_KEY / BASE_URL | Free Groq tier; falls back to Smart Agent on error |
| Embeddings | gemini | gemini-embedding-2 | (uses SMART_AGENT_API_KEY) | AI Studio only — NOT Vertex AI; decoupled from worker key |

### Model Selection Rationale

- **Gemini 3.5 Flash** as brain: frontier reasoning at low cost, native tool-use, Google ecosystem
- **DeepSeek V4 Flash** as worker: $0.11/$0.22 per 1M tokens — 3× cheaper than Gemini Flash, excellent structured JSON, OpenAI-compatible API
- **Claude Haiku** as fallback: diversity hedge — different provider means different failure modes
- **Groq/Qwen3-32B** for tick-brain: free tier, 0.5s latency, does not train on data, OpenAI-compatible
- **gemini-embedding-2** for embeddings: available via AI Studio (NOT Vertex AI — embedding model is AI Studio only)

### Cost Model

Measure everything, cap nothing (explicit user preference). Cost is recorded per call via
`LLMUsageStore` (Phase 14) and surfaced in `get_self_status` (Phase 16).
Free models (Groq) return cost=0.0 by design — see `core/pricing.py::compute_cost()`.

> **Numbering note.** Sections below labelled "Phase 15: Multimodal Telegram" were
> implemented as an interim feature between Phases 14 and the start of the
> Consciousness & Autonomy milestone work. The milestone-scoped roadmap
> (`.planning/MILESTONES.md`, `.planning/PROJECT.md`) uses a different scheme
> where Phases 15-18 refer to milestone-v2.0 deliverables. Both numbering
> schemes are valid in context. The "Milestone v2.0 Phases" section at the
> end of this file covers Phases 15-18 in the milestone sense.

## Phase 15 (interim) — Multimodal Telegram Photo Support & Get Ready Buffer Fix

### Telegram Photo Vision Ingestion
To keep conversational context rich while maintaining a lean state layer:
1. **Telegram Ingestion**:
   - `telegram_bot.py` is configured with `(filters.TEXT | filters.PHOTO)` in its message handler.
   - `interfaces/_router.py` downloads the highest resolution file from the Telegram photo array using asynchronous file fetching and stores the byte array in memory.
   - The caption (`update.message.caption`) serves as the text prompt, fallback to empty string if no caption is provided.
2. **Dynamic Memory Injections**:
   - `core/main.py` handles the downstream payload. The orchestrator accepts optional `photo_bytes` and `photo_mime_type`.
   - At loop execution in `_run_smart_loop()`, we deep-copy the persistent message array.
   - The photo bytes are encoded to base64 and inserted as an Anthropic-canonical `image` block inside the final `user` turn:
     ```python
     {
         "type": "image",
         "source": {
             "type": "base64",
             "media_type": photo_mime_type,
             "data": photo_base64,
         }
     }
     ```
   - By executing a deep copy and only injecting the image block in memory, we avoid storing massive base64 strings in Firestore conversation history, saving substantial read/write overhead and token cost.
3. **LLM Wire-Format Conversions**:
   - `core/llm_client.py`'s `_GeminiBackend` catches `image` blocks and compiles them via the `google-genai` SDK using `types.Part.from_bytes(data=img_bytes, mime_type=block["source"]["media_type"])`.
   - `_OpenAIBackend` accumulates consecutive text and image blocks and maps them into standard OpenAI multimodal list schemas using standard data URIs (`data:{media_type};base64,{img_data}`).
   - **Gemini Thinking Signature Preservation**: To prevent `400 INVALID_ARGUMENT` failures under Gemini thinking models (such as `gemini-3.5-flash`), `_GeminiBackend.chat()` extracts the model's `thought_signature` reasoning state from the response candidate parts, base64-encodes it, and passes it through the unified envelope. The orchestrator preserves this signature on its intermediate `text` and `tool_use` content blocks inside the conversation history, allowing `_convert_messages()` to reconstruct and bind the decoded `thought_signature` bytes back to native `types.Part` objects on the subsequent tool-response turn.

### Get Ready Buffer Recursion Break
1. **Tool-Level Suppression**:
   - `mcp_tools/calendar_tool.py`'s `create_event()` intercept checks if the event summary starts with `"Get Ready"` (case-insensitive). If so, it disables `is_workout`, preventing the scheduler from creating nested pre-workout travel/prep buffers.
2. **Smart Prompt Instruction**:
   - `prompts/smart_agent.md` clarifies that `"Get Ready"` buffers are automatically generated at the tool-level, explicitly forbidding the Smart Agent from creating travel or preparation blocks manually.

---

# Milestone v2.0 Phases — Consciousness & Autonomy ✓ Shipped 2026-05-23

These phases use the milestone-scoped numbering documented in `.planning/MILESTONES.md`
and `.planning/archive/v2.0/phases/`. Full per-plan execution paper trail (CONTEXT, RESEARCH,
PLAN, SUMMARY, VERIFICATION, REVIEW) lives in `.planning/archive/v2.0/phases/<phase>/`.

## Phase 14 — Foundation: Cost Metering + Tick-Brain + LLM Strategy ✓

Already covered above (§4 Execution Phases line 36 + § LLM Strategy table).

Highlights:
- `core/pricing.py` — `MODEL_PRICING` dict + `compute_cost(model, in_tokens, out_tokens)`. Free models return 0.0.
- `memory/firestore_db.py::LLMUsageStore` — records every call to `llm_usage/{YYYY-MM-DD}` with model, purpose, in/out tokens, cost.
- `core/tick_brain.py` — Groq Qwen3-32B primary + Gemini fallback. Used by heartbeat + Phase 18 autonomous engine.
- `core/llm_client.py` — all 3 backends surface token usage; `purpose` param threaded through; `_OpenAIBackend` accepts a per-instance `base_url` (so Groq can be targeted without mutating the env).

## Phase 15 (v2.0) — Codebase Self-Knowledge ✓

**Goal:** Klaus can read and search his own deployed source.

**New module:** `mcp_tools/self_inspect.py` — `list_files(subdir=None)`, `read_source(path)`, `search_source(query)`. Path-traversal rejection + secret denylist (`.env*`, `*secret*`, `*credential*`, `*token*`, OAuth JSON).

**3 brain-direct tools** wired in `core/tools.py` at all 5 sites (TOOL_SCHEMAS, _HANDLERS, SMART_AGENT_DIRECT_TOOLS, lazy-singleton accessor, WORKER_TOOL_SCHEMAS exclusion):
- `list_own_files(subdir?)`
- `read_own_source(path)`
- `search_own_source(query)`

`prompts/smart_agent.md` has a `SELF-INSPECTION` section telling Klaus he can inspect his own source. Direct-call only — never delegated to worker.

## Phase 16 (v2.0) — Self-Model & State Awareness ✓

**Goal:** Klaus carries a stable self-model + mutable self-state, both injected on every conversation turn.

**`docs/SELF.md`** — auto-generated capability manifest. `core/self_manifest.py::generate_manifest()` introspects live tool schemas, cron routes, outbound channels, the model map (read from env vars — `SMART_AGENT_MODEL` etc.), and memory layers. Embeds a SHA so `core/heartbeat.py::check_code()` can flag staleness weekly. CI regenerates SELF.md on every Cloud Run deploy.

**`memory/firestore_db.py::SelfStateStore`** — persists `identity_summary`, `current_focus`, `recent_context`, `mood`, `updated_at` in Firestore `config/self_state`. Bootstraps from SELF.md intro paragraph on first run.

**Prompt assembly** (`core/main.py::AgentOrchestrator.render_smart_system`): per-message render step substitutes `{self_md}` (stable digest) + `{self_state}` (volatile) + `{journal_digest}` + `{today_date}` into `prompts/smart_agent.md`. Stable content goes first for prompt-cache friendliness.

**`get_self_status` direct tool** in `core/tools.py` — returns uptime, today's message count, today/month LLM cost (from `LLMUsageStore`), latest heartbeat status. Degrades gracefully when journal absent.

## Phase 17 (v2.0) — Reflection & Journal ✓

**Goal:** Klaus reflects nightly, writes a journal entry, and updates his self-state.

**`core/reflection.py::run_reflection()`** — gathers the day (conversation history, message count, LLM cost, heartbeat snapshot, calendar events via the shared `core/tools._get_calendar_tool()` singleton, TickTick today-tasks count) and composes a journal entry via the brain. Per-source try/except isolation — one failing source doesn't sink the whole reflection.

**`memory/firestore_db.py::JournalStore`** — writes `journal/{YYYY-MM-DD}` docs in Firestore.

**Pinecone integration** — each journal entry upserts to Pinecone with `kind="self"`. `memory/pinecone_db.py::_VALID_KINDS` now `{"fact", "chunk", "chat", "self"}`. Self-recall requires explicit `kinds=["self"]` — default `recall()` excludes journal entries to avoid polluting curated memory.

**Cloud Scheduler:** `klaus-reflect` fires `0 22 * * *` Asia/Jerusalem → `POST /cron/reflect` (OIDC-protected) in `interfaces/web_server.py`. After reflection, `SelfStateStore.update()` evolves Klaus's self-state with the day's insights.

**Per-message prompt assembly** also injects a digest of the last ~3 journal entries into `{journal_digest}` so Klaus carries forward context from recent days.

## Phase 18 (v2.0) — The Autonomous Engine (capstone) ✓

**Goal:** Judgment-driven proactive outreach with repeat-suppression and an eval harness.

### 3-layer cost-gating pipeline

```
gather_situation()        Layer 0   8 sources, no LLM             $0.00
        ↓
empty-signals gate (D-11) Layer 0   if nothing happening → EXIT   $0.00
        ↓
tick_brain.think()        Layer 1   Groq qwen3-32b judgment       $0.00 (free tier)
  purpose='tick_autonomous'         {should_act, reason, draft, topic_key}
        ↓
  if should_act=False → EXIT                                       $0.00
        ↓
_compose_layer2()         Layer 2   gemini-3.5-flash compose       costs money
  purpose='autonomous_compose'      synthetic [{role:user, content}] via
                                    AgentOrchestrator._run_smart_loop
        ↓
send_and_inject()         Telegram delivery + Firestore conversation injection
        ↓
OutreachLogStore.append() D-10: only after send success — repeat-suppression key
```

**Brain (paid) never runs unless tick-brain (free) affirmatively says "speak up".**

### Components

- **`core/autonomous.py`** (825 LOC) — `gather_situation`, `run_autonomous_tick`, `_compose_layer2`, `_compose_followup`, `_get_orchestrator` (process-wide singleton with double-checked locking), `_SMART_LOOP_ERROR_SENTINELS`.
- **`prompts/autonomous_triage.md`** — Layer 1 tick-brain system prompt. Wide-latitude framing (no cadence cap, no hours-since-contact floor). Mandates JSON output: `{should_act, reason, draft, topic_key}`. Today's outreach log is informative-not-blocking.
- **`prompts/autonomous.md`** — Layer 2 brain compose prompt with `{self_md}` / `{self_state}` / `{journal_digest}` / `{today_date}` placeholders. Includes follow-up fire variant with `{action: send|defer}` schema and D-14 force-fire on `defer_count >= 3`.
- **`memory/firestore_db.py`** — three new stores:
  - `FollowupStore` — scheduled follow-ups (add, list_due, mark_done, cancel, defer). Composite index on (`status`, `due_at`).
  - `OutreachLogStore` — per-day topic_key log. `append()` uses `firestore.ArrayUnion` (deep-equality dedup) — never put server-timestamp sentinels inside the entry dict.
  - `TickLogStore` — per-tick decision audit log. Best-effort, never raises.
- **`core/tools.py`** — three brain-direct tools, wired at all 5 sites (15+ edit points):
  - `schedule_followup(when, note)` — accepts ISO 8601 or natural-language (dateutil fallback)
  - `list_followups()` — strips internal fields
  - `cancel_followup(id)` — idempotent (D-15)
  All three excluded from `WORKER_TOOL_SCHEMAS` — brain-only.
- **`core/tick_brain.py`** (Phase 18 extension) — `think(prompt, system_override=None)` and `_parse_response` passes through `topic_key`. Purpose strings layered: `tick_autonomous` / `tick_autonomous_fallback` when override set; `tick` / `tick_fallback` when not (heartbeat backward compat preserved).
- **`interfaces/web_server.py`** — `POST /cron/autonomous-tick` (OIDC-protected, calls `core.autonomous.run_autonomous_tick(_application.bot, now)`).
- **`core/heartbeat.py::_CRON_MAX_STALENESS_HOURS`** — `'autonomous-tick': 1` (one hour = 3 missed 20-min ticks).
- **`evals/tick_brain/fixtures/0001..0005-*.json`** — 5 seed `SituationSnapshot` fixtures (one per trigger type + one obvious-negative) with `ground_truth.should_speak` labels. Fixture 0003 (due-followup) is `should_speak=false` because D-13 routes follow-ups around tick-brain.
- **`scripts/eval_tick_brain.py`** (366 LOC) — loads fixtures, runs each through `TickBrain.think(prompt, system_override=<autonomous_triage.md>)`, scores predicted vs ground-truth. Outputs overall precision/recall/F1 + per-trigger-type breakdown. Safe-mode returns (`parse_failure`, `llm_error`) tracked as a separate "errored" bucket — NOT counted as predicted-False (Pitfall 8). Exit code 0 always (measurement tool, not a CI gate).

### Cloud Scheduler

- `klaus-autonomous-tick` — `*/20 7-21 * * *` Asia/Jerusalem (43 ticks/day inclusive). OIDC bearer required.

### Cost expectation (typical day)

- ~most ticks: $0.00 (Layer 0 empty gate)
- Remaining: $0.00 (tick-brain says no — Groq free tier)
- Rare (a handful per day): a few hundredths of a cent each (Layer 2 brain compose)

### Key invariants (verified by tests in `tests/test_autonomous.py`)

- `OutreachLogStore.append` is gated on send success (D-10)
- All 4 placeholders are resolved before `_run_smart_loop` is called (Pitfall 2 / BLOCKER 5b)
- `_run_smart_loop` sentinel return falls back to tick-brain draft (D-19 / BLOCKER 3) — the `CONNECTIVITY_ERROR_TEXT` constant in `core/main.py` is asserted to contain every entry in `_SMART_LOOP_ERROR_SENTINELS` by `test_sentinel_substring_matches_main_constant`, so future edits to the canned error message can't silently break Layer-2 failure detection
- `_get_orchestrator()` is a singleton — built once per Cloud Run instance, not 43 times/day
- Synthetic Layer-2 user message does NOT pollute conversation history (Pitfall 2)
- `defer_count >= 3` force-fires on the next due tick (D-14)
- Empty/missing `topic_key` from tick-brain triggers handler synthesis (Pitfall 4)
- Layer 1 purpose strings stay `tick_autonomous` / `tick_autonomous_fallback`; heartbeat purposes (`tick` / `tick_fallback`) are preserved untouched

---

# Live Infrastructure (post-v2.0)

Updated to reflect the 9-cron production state. The §5 inventory above predates Phases 17-18.

**Cloud Run service:** `klaus-agent` — region `me-west1`, project `klaus-agent`

**Firestore database:** `klaus-firestore` (lowercase `klaus` — uppercase causes silent 404s). Collections:
- `conversations` — per-user history (Phase 6)
- `five_fingers_roster`, `five_fingers_practices` — Phase 8
- `morning_briefings/{date}` — Phase 10 state machine
- `chat_ingest/state`, `chat_export_ingest/state` — Phases 12-13 dedup
- `llm_usage/{date}` — Phase 14 cost metering
- `config/self_state` — Phase 16 mutable self-state
- `journal/{date}` — Phase 17 reflection journal
- `followups`, `outreach_log/{date}`, `tick_logs/{date}/ticks/{HH:MM}` — Phase 18

**Pinecone index:** `klaus-memory` — serverless, AWS, 768-dim, cosine. Valid kinds: `{"fact", "chunk", "chat", "self"}`.

**Cloud Scheduler jobs (9 total):**
- `klaus-heartbeat` — `0 * * * *`
- `klaus-proactive-alerts` — `30 21 * * *` Asia/Jerusalem (Phase 9)
- `klaus-morning-briefing-tick` — `*/10 6-10 * * *` Asia/Jerusalem (Phase 10)
- `klaus-five-fingers-morning` — Wed/Sun 10:30 (Phase 8)
- `klaus-five-fingers-evening` — Wed/Sun 21:15 (Phase 8)
- `klaus-chat-ingest` — `0 4 * * *` Asia/Jerusalem (Phase 12)
- `klaus-chat-export-ingest` — `30 4 * * *` Asia/Jerusalem (Phase 13)
- `klaus-reflect` — `0 22 * * *` Asia/Jerusalem (Phase 17 v2.0)
- `klaus-autonomous-tick` — `*/20 7-21 * * *` Asia/Jerusalem (Phase 18 v2.0)

**Secrets in Secret Manager:** all the original v1.0 secrets plus `klaus-tick-brain-key` (Groq API key for Phase 14/18 tick-brain).

See `docs/DEPLOYMENT.md` for operator runbook (creating jobs, rotating secrets, the Firestore composite index on `followups(status, due_at)`, and the Five Fingers job-id-collision migration paragraph).