# Master Blueprint: Klaus — Personal Hybrid Agent

## 1. Project Overview

Klaus is a cloud-hosted personal AI agent for Amit Grupper, deployed on Google Cloud Run.
He runs a **dual-model architecture** (brain + worker, with a separate free always-on
tick-brain and an emergency fallback) and integrates with Gmail, Google Calendar,
Things 3, Notion, Pinecone, Firestore, weather/Readwise/Garmin, and the local
Claude Code / multi-AI chat-log pipelines. Telegram is the primary interface.

As of milestone v2.0 (shipped 2026-05-23) Klaus is **self-aware, cost-transparent, and
judgment-driven autonomous** — every LLM call is metered, he can read his own source
code, he carries an auto-generated SELF.md identity manifest plus a persistent
self_state, he writes a daily reflection journal, and a cron-triggered autonomous
tick (`*/20 7-21` Asia/Jerusalem) lets him reach out proactively on his own with
repeat-suppression and an eval harness measuring his judgment quality.

Fully cloud-native — no local Mac runtime dependency.

## 2. Context Files Reference

Before writing any code, read and adhere to these:

- `docs/PRD.md` — product requirements, feature goals, original vision
- `docs/TECHNICAL_PLAN.md` — architecture, hosting, memory strategy, per-purpose model map
- `docs/USER.md` — Amit's personal context, routines, hardcoded scheduling rules
- `docs/AGENT.md` — Klaus's persona, tone, JARVIS/C-3PO voice directives
- `docs/CODING_STANDARDS.md` — code structure, readability, formatting rules
- `docs/SELF.md` — Klaus's own auto-generated capability manifest (regenerated on every deploy via `core/self_manifest.py`)
- `docs/DEPLOYMENT.md` — Cloud Run + Cloud Scheduler + Secret Manager operator runbook
- `docs/things_protocol.md` — reverse-engineered Things Cloud protocol + schema (no official API exists)
- `.planning/MILESTONES.md` + `.planning/ROADMAP.md` — what shipped, when, what's next

## 3. Model architecture (env-driven)

| Purpose | Model | Backend | Notes |
|---------|-------|---------|-------|
| Brain (smart agent) | `gemini-3.5-flash` | Gemini AI Studio | Orchestration, judgment, every conversation turn |
| Worker (hands) | `deepseek-v4-flash` | OpenAI-compat (DeepSeek API) | Tool execution, structured JSON, data gathering — $0.11/$0.22 per 1M tokens |
| Brain fallback | `claude-haiku-4-5` | Anthropic | Inline fallback on LLMError — diversity hedge |
| Tick-brain | `openai/gpt-oss-120b` | Groq (OpenAI-compat) | Always-on free reasoning for heartbeat + autonomous tick. Groq ids are namespaced — bare model names 404. qwen/qwen3-32b decommissioned by Groq 2026-07-17. Free tier: 8K tokens/request (TPM), 200K tokens/day (TPD). Every tick-brain request is admission-controlled to `input + max_tokens ≤ 7,200` (margin below the hard 8K ceiling; guarded by `tests/test_token_budget.py`) via `reasoning_effort=low` + `TICK_BRAIN_MAX_TOKENS=1024` — never raise the guard target to mask a prompt-bloat regression. A change-detection gate skips the Groq call when salient signals are unchanged since the last tick |
| Tick-brain fallback | `gemini-3.5-flash` | Gemini AI Studio | Used if Groq fails |
| Embeddings | `gemini-embedding-2` | Gemini AI Studio (**NOT Vertex**) | 768-dim, Pinecone cosine |

All model strings come from env vars (`SMART_AGENT_MODEL`, `WORKER_AGENT_MODEL`,
`SMART_AGENT_FALLBACK_MODEL`, `TICK_BRAIN_MODEL`, and matching `_BACKEND`/`_API_KEY`/`_BASE_URL`).
`core/self_manifest.py` reads these at generate-time so `docs/SELF.md` can never drift.

## 4. Live directory layout

```text
Klaus/
├── .env                    # (gitignored) local env vars
├── .env.example            # template
├── CLAUDE.md               # this file
├── docs/
│   ├── PRD.md              # product requirements
│   ├── TECHNICAL_PLAN.md   # architecture + per-phase technical details
│   ├── USER.md             # Amit's context, routines, scheduling rules
│   ├── AGENT.md            # Klaus's persona + tone
│   ├── CODING_STANDARDS.md # code style
│   ├── SELF.md             # auto-generated capability manifest
│   ├── DEPLOYMENT.md       # ops runbook: Cloud Run, crons, secrets, indexes
│   └── healthkit_shortcut.md # iOS healthkit shortcut configuration
├── core/
│   ├── main.py             # AgentOrchestrator, _run_smart_loop, render_smart_system
│   ├── auth_google.py      # Google OAuth persistent token mgmt
│   ├── llm_client.py       # Backend-agnostic LLM wrapper (Anthropic / Gemini / OpenAI-compat)
│   ├── tools.py            # All tool schemas + lazy-singleton accessors + _HANDLERS dispatch
│   ├── tick_brain.py       # Groq GPT-OSS-120B + Gemini fallback (think + system_override + topic_key)
│   ├── pricing.py          # MODEL_PRICING dict + compute_cost(model, in, out)
│   ├── heartbeat.py        # Hourly cron: stale-cron detection, SELF.md SHA, tick-brain reasoning
│   ├── proactive_alerts.py # 21:30 nightly: weather/overload/travel-time alerts
│   ├── morning_briefing.py # Push-triggered (POST /trigger/morning, no cron): Garmin-anchored daily briefing
│   ├── reflection.py       # Daily 22:00: gather day → journal entry → self_state update
│   ├── nightly_review.py   # Sleep-Focus-triggered nightly review + tomorrow prep (01:00 backstop)
│   ├── autonomous.py       # */20 7-21: 3-layer gather → tick-brain triage → brain compose
│   ├── scheduled_message.py# Telegram send + Firestore conversation injection
│   ├── task_dispatch.py    # Cloud Tasks enqueue → /internal/process-update (full-CPU turns)
│   ├── self_manifest.py    # Auto-generates docs/SELF.md (CI runs on every deploy)
│   ├── chat_ingest.py      # Daily 04:00: parse Claude Code JSONL → Pinecone + Notion
│   ├── chat_export_ingest.py # Daily 04:30: ChatGPT/Claude.ai/Gemini Takeout zips → same pipeline
│   ├── strength_ingest.py  # Daily 05:00: Hevy pull (backfill→delta) → StrengthSessionStore
│   ├── things_ingest.py    # */30 6-23: refresh the Things 3 mirror (cold-start backstop)
│   └── run_ingest.py       # Daily 05:15: Garmin per-run detail pull (presence-diff) → RunDetailStore
├── memory/
│   ├── firestore_conversation.py # Per-user conversation history
│   ├── things_store.py     # ThingsTaskStore: Things 3 read/write + Firestore mirror + sidecar
│   ├── firestore_db.py     # All Firestore stores: LLMUsage, SelfState, Journal,
│   │                       #   MorningBriefing, Followup, OutreachLog, TickLog, StrengthSession
│   └── pinecone_db.py      # MemoryStore: remember/recall + chat upserts
├── mcp_tools/
│   ├── database_tool.py    # Analytical PostgreSQL read-only queries
│   ├── gmail_tool.py       # Read-only Gmail
│   ├── calendar_tool.py    # Google Calendar list/create/free-busy/delete + Get Ready
│   ├── notion_tool.py      # 5 tools: search, get_page, query_db, create_page, append_blocks
│   ├── weather_tool.py     # wttr.in
│   ├── readwise_tool.py    # Daily reading highlights
│   ├── things_tool.py      # Things Cloud sync protocol (journal replay, commit) — writes gated
│   ├── hevy_tool.py        # Hevy strength API (full per-set workouts) + normalizer
│   ├── garmin_tool.py      # Sleep, HRV, body battery, resting HR
│   ├── routes_tool.py      # Google Routes API (traffic-aware drive time)
│   ├── memory.py           # remember/recall (Pinecone-backed)
│   ├── self_inspect.py     # list_own_files / read_own_source / search_own_source
│   └── healthkit_tool.py   # HealthKit integration tool (nutrition sync)
├── interfaces/
│   ├── web_server.py       # FastAPI: Telegram webhook + /cron/* OIDC-protected routes
│   └── _router.py          # Telegram message router + photo download
├── prompts/
│   ├── smart_agent.md      # Brain system prompt (includes {self_md}, {self_state}, {journal_digest})
│   ├── worker_agent.md     # Worker system prompt
│   ├── autonomous_triage.md# Tick-brain layer-1 judgment prompt (autonomous engine)
│   ├── autonomous.md       # Brain layer-2 compose prompt (autonomous engine)
│   ├── reflection.md       # Reflection cron compose prompt
│   ├── morning_briefing.md # Morning briefing compose prompt
│   ├── proactive_alert.md  # Evening alerts compose prompt
│   ├── heartbeat.md        # Tick-brain heartbeat reasoning prompt
│   ├── chat_summary.md     # Chat-ingest summary prompt (Notion DB rows)
│   └── meal_audit.md       # Meal auditing prompt
├── scripts/
│   ├── eval_tick_brain.py  # Measurement-only judgment eval runner
│   ├── spike_things_protocol.py # Read-only Things Cloud schema discovery
│   ├── backfill_notion_titles.py
│   ├── ingest_garmin_zip.py # Parses + ingests Garmin export zip to Postgres
│   ├── upload_claude_logs.{sh,ps1}
│   ├── upload_chat_export.sh
│   ├── run_chat_export_backfill.sh
│   ├── smoke_test_{notion,chat_ingest,chat_export}.py
│   ├── probe_garmin_export_keys.py # Helper script for Garmin keys exploration
│   └── test_healthkit_push.py # Sync payload test script
├── evals/
│   └── tick_brain/         # 5 seed fixtures + README — judgment quality harness
└── tests/                  # pytest — 630+ passing locally
```

## 5. Live infrastructure

- **Cloud Run service:** `klaus-agent` in `me-west1`, project `klaus-agent`
- **Firestore database:** `klaus-firestore` (lowercase k — uppercase causes silent 404s)
- **Pinecone index:** `klaus-memory` (768-dim, cosine)
- **Cloud Scheduler jobs:** heartbeat (hourly), chat-ingest (04:00), chat-export-ingest (04:30), **klaus-nightly-backstop (01:00, writes journal/self_state + sends the nightly review if the Sleep-Focus trigger didn't)**, **klaus-autonomous-tick (*/20 7-21)**, weekly-training-review (Sun 10:00), **klaus-strength-sync (05:00, Hevy pull)**, **klaus-run-sync (05:15, Garmin per-run detail pull)**, **klaus-things-sync (*/30 6-23, Things 3 mirror refresh)**. Nightly review is normally triggered organically by the iOS Sleep-Focus automation → `POST /trigger/nightly` (the nightly flow writes the journal via `_ensure_reflection`); the morning briefing is triggered the same way, by an iOS wake-up automation → `POST /trigger/morning` (Phase 33, D-08/D-31 — exact trigger mechanism varies by iOS version, see `docs/sleep_focus_off_shortcut.md` §3.0), with no cron backstop by design (D-09). **Retired:** proactive-alerts (21:30) and reflect (22:00) — folded into the nightly review; the morning's polling cron (*/10 6-10) — retired in plan 33-13 once the wake-up trigger was confirmed live in production (2026-08-01).

## 6. Invariants

- All GCP/Pinecone resource names lowercase `klaus-` (uppercase = silent 404)
- `load_dotenv` always with `override=True` (default silently ignores `.env` if shell already exported)
- Embeddings via Gemini AI Studio, **never Vertex** (embedding model is AI Studio only)
- Brain never routes through worker first — the brain (`gemini-3.5-flash`) sees every message and decides
- Autonomous tick cost gating: Layer 0 (gather, $0) → Layer 1 (tick-brain Groq, $0) → Layer 2 (brain, costs money) — brain only runs when tick-brain affirmatively says "speak up"
- `OutreachLogStore.append` is gated on `send_and_inject` success (D-10) — no log entry if delivery failed
- `_get_orchestrator()` is a process-wide singleton with double-checked locking — AgentOrchestrator is built once per Cloud Run instance, not 43× per day
- Agent turns must run INSIDE a tracked request (Cloud Tasks → `/internal/process-update`), never in a Starlette BackgroundTask — background tasks run after the response and Cloud Run throttles CPU once no request is in flight (2026-06-12: 18-minute reply). Telegram still gets its instant webhook ACK
- Every LLM client carries an explicit timeout (`LLM_TIMEOUT_SECONDS`, default 120s) — SDK defaults are 600s and a single hung provider call stalls the whole turn
- HealthKit/Lifesum meal timestamps are canonical slot times (08:00/12:00/20:00), NOT actual eating times — never build features that infer eating time from them
- Task backend is selected in **one** place — `memory.firestore_db.get_task_store()` (`TASK_BACKEND=things|firestore`). Never construct `TaskStore`/`ThingsTaskStore` directly: the briefing, nightly review, reflection, and autonomous tick each used to build their own, so flipping the backend left every proactive feature reading an abandoned store. Guarded by a test in `tests/test_tools.py`
- Things Cloud is **unofficial and fails by returning plausible wrong data, never by raising** (see `docs/things_protocol.md`). Three traps, all found only by diffing against the running app: journal opcode `t=2` is DELETE (treating it as an edit resurrects deleted items); the page cursor is `start + len(items)`, NOT `current-item-index` (which is the head — using it silently drops everything past page one); and trashing a project leaves its children with `tr=False`. Always read through `things_tool.live_todos()` / `replay_journal()`, which encode these rules — never hand-roll the filter or the pagination
- Things `sr` (scheduled, "when I'll do it") and `dd` (deadline, "when it's due") are **separate fields**. `due_date`→`sr`, `hard_deadline_at`→`dd`; rescheduling moves `sr` only. Things has no priority field — `priority` and the other Klaus-only planning fields live in the `task_meta` sidecar
- Things owns recurrence: it spawns the next instance itself, so `complete()` returns `next_id: None` and Klaus must never create the follow-up. Klaus never hard-deletes a to-do either — `task_delete` trashes, which is recoverable
- Things item ids are **Base58**, not Base62 — the alphabet excludes `0`, `O`, `I`, `l`. Committing an id containing one of those **crashes Things on launch on every device** (`decodeBase58String.mapBase58` in the trace). Always mint ids with `things_tool.new_uuid()`; `commit()` refuses malformed ids and bad note checksums as a last line of defence (2026-08-13: three outages before this was spotted)
- A note's `ch` field **must** be `zlib.crc32(text.encode("utf-8"))`. A wrong checksum is accepted by the server, then **crashes Things on launch on every device** (assertion inside `LegacySCHistoryPerformSync`); the journal is append-only so recovery means appending a delete for the poisoned item. A placeholder `ch=0` passes every test because it is correct for an *empty* note — it only detonates once real text is attached. Always build notes via `things_tool.build_note()` (2026-08-13 incident)
