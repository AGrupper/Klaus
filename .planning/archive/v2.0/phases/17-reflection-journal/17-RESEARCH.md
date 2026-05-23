# Phase 17: Reflection & Journal - Research

**Researched:** 2026-05-19
**Domain:** Daily reflection cron + persistent self-model loop (Firestore + Pinecone + dual-model LLM)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

CONTEXT.md decisions **D-01 through D-18 are LOCKED** — research does not relitigate them.
Copied verbatim:

- **D-01:** `run_reflection()` gathers, each step best-effort (try/except — a failed source is omitted and noted, the reflection still runs and writes an entry): (a) today's message count + LLM cost from `LLMUsageStore.summary("today")`; (b) a conversation summary paragraph; (c) today's Google Calendar events via the existing calendar tool; (d) TickTick tasks completed today; (e) heartbeat last-run status.
- **D-02:** Two-tier LLM use — conversation summarization runs on the **worker** (`gemini-2.5-flash`, cheaper); the reflection itself runs on the **brain** (`gemini-3-flash-preview`). Both cost-metered via `LLMUsageStore`.
- **D-03:** The reflection (brain) call outputs structured JSON with 5 fields: `summary` (2-3 sentence day overview), `mood` (short string), `current_focus` (string), `recent_context` (string), `highlights` (list of strings).
- **D-04:** The `journal/{date}` Firestore doc stores the 5 LLM fields **plus** the raw gathered metrics — `message_count`, `cost_usd`, `calendar_event_count`, `tasks_completed`, `heartbeat_ok` — so each entry is auditable against its inputs.
- **D-05:** `run_reflection()` updates `SelfStateStore` via `.set()`: `current_focus` and `mood` are **replaced**; `recent_context` is a **rolling 3-day window** (append the latest, trim the oldest).
- **D-06:** `kind="self"` added to `_VALID_KINDS` in `memory/pinecone_db.py` (JOUR-04).
- **D-07:** Each journal entry is upserted to Pinecone with a **deterministic vector ID `self-{date}`** so a re-run overwrites cleanly. Embedded text = `summary` + `highlights` joined. Needs a small new upsert path — `remember()` generates random UUIDs and cannot take a custom ID.
- **D-08:** Brain self-recall — **extend the existing `recall` direct tool with an optional `kind` parameter** (`"fact"`|`"chunk"`|`"self"`); `_handle_recall` passes `kinds=[kind]` through. No new tool. Default recall behavior (fact+chunk) unchanged.
- **D-09:** `/cron/reflect` route added to `interfaces/web_server.py`, OIDC-authed via `_verify_cron_request`, logged via `_log_cron_run("reflect", ...)`. Same shape as `cron_proactive_alerts`. `CRON_DEV_BYPASS=true` skips auth.
- **D-10:** Cloud Scheduler runs `/cron/reflect` **daily at 22:00 Asia/Jerusalem**. The `journal/{date}` key uses the Asia/Jerusalem calendar date.
- **D-11:** Phase 17 delivers the route; the Cloud Scheduler job is created via a documented `gcloud` command.
- **D-12:** Idempotency — a second run on the same day **overwrites** `journal/{date}` and re-upserts the `self-{date}` vector. `self_state` reflects the latest run.
- **D-13:** If the core reflection LLM call fails (brain + fallback both error), write a **minimal fallback** `journal/{date}` doc with raw metrics and placeholder summary (`"reflection unavailable"`). `_log_cron_run` records the failure.
- **D-14:** Per-message `smart_system` assembly injects a `{journal_digest}` placeholder — a compact bullet block of the last ~3 journal entries, one line each: `- {date} (mood: {mood}): {summary}` plus top highlight when `highlights` is non-empty.
- **D-15:** Placeholder ordering in the template: SELF.md (stable) → `{self_state}` → `{journal_digest}` → `{today_date}`. **Smart-only** — the worker never sees it.
- **D-16:** The `get_self_status` `journal` field returns `{date, summary, mood}` from the most recent `JournalStore` entry.
- **D-17:** `prompts/reflection.md` is written in **first person as Klaus** ("Today I helped Amit..."). Tone aligned with `docs/AGENT.md` persona.
- **D-18:** The reflection prompt receives **yesterday's journal entry** (`summary` + `current_focus` from `journal/{yesterday}`) as input. Best-effort — absent on the first ever run.

### Claude's Discretion

- Digest empty state: with fewer than 3 entries, include whatever exists; omit the block entirely when empty (consistent with Phase 16 D-05 blank-field omission).
- `highlights[]` cap (suggest 3-5 items), exact `reflection.md` wording, and JSON-parse hardening for the brain's structured output.
- Embedded-text truncation if `summary` + `highlights` exceeds Pinecone `CONTENT_MAX_CHARS`.
- `user_id` sourcing for `run_reflection()` — reuse whatever owner-ID env var the proactive-alerts cron already uses for Pinecone scoping and conversation lookup.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. Phase 18 owns autonomous outreach. Phase 17 only makes the self-model persistent and evolving.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| JOUR-01 | `run_reflection()` gathers the day (conversation history, message count, LLM cost, heartbeat, calendar) and produces a journal entry + updated self_state fields | All five gather sources confirmed available — see Standard Stack + Architectural Responsibility Map. **Conversation history is the one constrained source** (see Pitfall 1). |
| JOUR-02 | `JournalStore` writes `journal/{date}` docs in Firestore | `SelfStateStore` (`firestore_db.py:601`) is the verified template; `AttendanceStore` (`:226`) is the verified date-keyed pattern. See Code Examples. |
| JOUR-03 | Each journal entry is upserted to Pinecone with `kind="self"` | `MemoryStore` confirmed at `pinecone_db.py:32`. Needs new `remember_self()` path — `remember()` cannot take a custom vector ID. See Code Examples. |
| JOUR-04 | `kind="self"` added to `_VALID_KINDS`; self-recall requires explicit `kinds=["self"]` | `_VALID_KINDS` confirmed at `pinecone_db.py:29`. `recall()` already accepts `kinds`. See Code Examples. |
| JOUR-05 | `/cron/reflect` route added with OIDC auth; Cloud Scheduler runs it ~22:00 | `cron_proactive_alerts` at `web_server.py:310` is the verified shape template. See Code Examples. |
| JOUR-06 | Per-message prompt assembly injects a digest of the last ~3 journal entries | Render step confirmed at `core/main.py:251-256`. `{journal_digest}` placeholder must be added to `prompts/smart_agent.md`. See Code Examples. |
</phase_requirements>

## Summary

Phase 17 is an **integration phase on a mature codebase** — no new frameworks, no library selection. Every integration point cited in CONTEXT.md `<canonical_refs>` was verified against the live codebase and is accurate, with three corrections noted below. The work is: one new module (`core/reflection.py`), one new prompt (`prompts/reflection.md`), one new Firestore Store class (`JournalStore`), one new Pinecone upsert path, one new cron route, and one new prompt placeholder. All patterns to replicate already exist and are battle-tested by the 7 existing crons and 2 existing scheduled-message flows.

The single most important research question — **"what conversation data can a 22:00 cron actually read?"** — is now answered definitively. `FirestoreConversationStore.get(user_id)` enforces a `SESSION_TIMEOUT_HOURS` (default **6**) staleness gate: if the conversation doc's `updated_at` is older than 6 hours, `get()` returns `[]`. A 22:00 cron will therefore see conversation history **only if Amit messaged Klaus after ~16:00 that day**. On a quiet day it reads nothing. This is exactly the best-effort behavior CONTEXT.md D-01 anticipated — `message_count` from `LLMUsageStore` remains the accurate full-day figure, and the conversation-summary paragraph must degrade gracefully to "no conversations today" rather than fail.

Three corrections to CONTEXT.md `<canonical_refs>`: (1) the Pinecone class is `MemoryStore`, not `PineconeStore` — `<canonical_refs>` and `<code_context>` call it `PineconeStore`; the actual class name is `MemoryStore` (`pinecone_db.py:32`). (2) Line numbers for `recall()` drift: `recall()` is at `pinecone_db.py:96`, and the `kinds` default `["fact","chunk"]` is at `:112`. (3) The cron route at `web_server.py:310` is `cron_proactive_alerts` — verified correct.

**Primary recommendation:** Build `core/reflection.py` as a self-contained `run_reflection(bot=None)` orchestrator that mirrors `core/proactive_alerts.py` structure exactly (module-level entry function, `_make_firestore_client` helper reuse, `LLMClient` constructed inline from env vars, plain-text/minimal fallback on LLM failure). Add `JournalStore` to `memory/firestore_db.py` modeled on `SelfStateStore` + `AttendanceStore` (date-keyed). Wire the cron route as a near-verbatim copy of `cron_proactive_alerts`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cron trigger + OIDC auth | API / Backend (`interfaces/web_server.py`) | Cloud Scheduler (external) | Existing 7 crons all live as FastAPI routes; `/cron/reflect` follows suit |
| Day-data gathering | API / Backend (`core/reflection.py`) | — | Pure orchestration; calls existing tool/store layers |
| Conversation summarization LLM call | Worker model (`gemini-2.5-flash`) | — | D-02: cheaper model for the summarization sub-task |
| Reflection reasoning LLM call | Brain model (`gemini-3-flash-preview`) | Fallback (`claude-haiku-4-5`) | D-02: judgment task uses the brain; D-13 fallback chain |
| Journal persistence | Database (`JournalStore` → Firestore `journal/{date}`) | — | Date-keyed doc collection, mirrors `AttendanceStore` |
| Journal vector memory | Database (Pinecone `kind="self"`) | — | Semantic recall; same index as fact/chunk/chat |
| self_state mutation | Database (`SelfStateStore` → `config/self_state`) | — | Phase-16 singleton doc; reflection is its first writer |
| Digest injection | API / Backend (`core/main.py` render step) | — | Per-message prompt assembly, smart-only (D-15) |
| `get_self_status` journal field | API / Backend (`core/tools.py`) | — | Direct tool, reads latest `JournalStore` entry |

**Note on the cron's lack of request context:** `run_reflection()` runs inside a Cloud Scheduler-triggered route — there is no Telegram `user_id` from a request. The owner ID must be sourced the same way `core/scheduled_message.py:_telegram_user_id()` does it: `int(os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip())`. This is the verified, established pattern for owner-ID sourcing in cron context (resolves CONTEXT.md "Claude's Discretion" item 4).

## Standard Stack

No new packages. Phase 17 uses only what is already installed and in use.

### Core (existing, reused)
| Component | Location | Purpose in Phase 17 |
|-----------|----------|---------------------|
| `LLMUsageStore.summary("today")` | `memory/firestore_db.py:519` | D-01(a): `smart_calls` (message-count proxy) + `total_cost_usd` |
| `SelfStateStore` | `memory/firestore_db.py:601` | D-05: `current_focus`/`mood`/`recent_context` update target; also the `JournalStore` template |
| `AttendanceStore` | `memory/firestore_db.py:226` | Verified template for a **date-keyed** Firestore collection (`journal/{date}`) |
| `MemoryStore` | `memory/pinecone_db.py:32` | D-06/D-07: `kind="self"` upsert + recall (NOTE: class is `MemoryStore`, not `PineconeStore`) |
| `LLMClient` | `core/llm_client.py:48` | D-02: worker summarization + brain reflection; `chat(messages, system=, tools=, purpose=)` |
| `GoogleCalendarManager.list_events` | `mcp_tools/calendar_tool.py:71` | D-01(c): today's events |
| `get_today_tasks()` | `mcp_tools/ticktick_tool.py:159` | D-01(d): TickTick tasks (see Pitfall 4 — no "completed today" view) |
| `_read_cron_ledger()` | `core/heartbeat.py:117` | D-01(e): heartbeat last-run status from `heartbeat_runs` collection |
| `_verify_cron_request` / `_log_cron_run` | `interfaces/web_server.py:227` / `:273` | D-09: OIDC auth + liveness ledger |
| `cron_proactive_alerts` | `interfaces/web_server.py:310` | D-09: shape template for `/cron/reflect` |

### Supporting (existing, reused)
| Component | Location | When to Use |
|-----------|----------|-------------|
| `_make_firestore_client(project_id, database)` | `memory/firestore_db.py:24` | Build a Firestore client inside `core/reflection.py` (proactive_alerts re-imports it — `proactive_alerts.py:80`) |
| `_telegram_user_id()` pattern | `core/scheduled_message.py:17` | Source owner `user_id` for Pinecone scoping in cron context |
| `compute_cost()` | `core/pricing.py:27` | Automatic — `LLMClient.chat()` meters every call already (`llm_client.py:105-125`) |
| `_load_prompt()` | `core/main.py:485` | Reference for loading `prompts/reflection.md` (or read inline like `proactive_alerts._compose_alert`) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `remember_self()` method on `MemoryStore` | Reuse `remember()` | `remember()` hard-codes `uuid.uuid4()` (`pinecone_db.py:80`) — cannot produce the deterministic `self-{date}` ID D-07 requires. A new path is mandatory, not optional. |
| `run_reflection()` taking no `bot` arg | `run_reflection(bot)` like `run_proactive_alerts` | Phase 17 does **not** send a Telegram message (Phase 18 owns outreach). `bot` is unused — keep the signature `run_reflection()` parameterless or accept `target_date` only, like the gather step. |
| `JournalStore` as a sibling of `SelfStateStore` | Generic key-value store | Date-keyed collection with `get_recent(n)` needs its own class — mirrors `AttendanceStore.recent_practices(n)`. |

**Installation:** None required.

**Version verification:** No new dependencies — skipped. All components verified by direct codebase read on 2026-05-19.

## Architecture Patterns

### System Architecture Diagram

```
                       Cloud Scheduler (22:00 Asia/Jerusalem, OIDC token)
                                        │
                                        ▼
                  POST /cron/reflect  [interfaces/web_server.py]
                                        │
                          _verify_cron_request()  ◄── CRON_DEV_BYPASS=true skips
                                        │
                                        ▼
                       core.reflection.run_reflection()
                                        │
        ┌───────────────────────────────┼────────────────────────────────┐
        ▼                ▼               ▼               ▼                ▼
  LLMUsageStore    Conversation    GoogleCalendar   get_today_tasks   _read_cron_ledger
  .summary("today")  Store.get()   .list_events()   (TickTick)        (heartbeat_runs)
  msg_count,cost   [6h-gated!]     today's events   tasks             last-run status
        │                │               │               │                │
        └────────────────┴───────────────┴───────────────┴────────────────┘
                                        │  each step try/except (D-01)
                                        ▼
                          gathered_day  (dict of metrics + raw data)
                                        │
                    ┌───────────────────┴────────────────────┐
                    ▼                                         │
        Worker LLM call (gemini-2.5-flash)                     │
        summarize conversation → 1 paragraph                   │
                    │                                          │
                    └──────────────┬───────────────────────────┘
                                   ▼
        + journal/{yesterday}.summary + current_focus  (D-18 continuity input)
                                   │
                                   ▼
        Brain LLM call (gemini-3-flash-preview → claude-haiku-4-5 fallback)
        prompts/reflection.md (first-person) → structured JSON
        {summary, mood, current_focus, recent_context, highlights[]}
                                   │
              ┌────────────────────┼─────────────────────┐
              │  JSON parse OK      │  both models fail   │
              ▼                     │                     ▼
   ┌──────────────────────┐         │          minimal fallback doc
   │ 3 write targets:     │         │          {raw metrics +
   │ 1. JournalStore.set  │◄────────┘          "reflection unavailable"}
   │    journal/{date}    │
   │    (5 fields + raw)  │
   │ 2. MemoryStore       │
   │    kind="self"       │
   │    id="self-{date}"  │
   │ 3. SelfStateStore.set│
   │    focus/mood replace│
   │    recent_context    │
   │    3-day rolling     │
   └──────────────────────┘
                                   │
                          _log_cron_run("reflect", ok)
                                   │
   ── next conversation ──────────►│
   core/main.py render step reads last ~3 journal entries
   → {journal_digest} placeholder in smart_system (smart-only, D-15)
```

### Recommended Project Structure
```
core/
├── reflection.py        # NEW — run_reflection() orchestrator + gather helpers + LLM calls
prompts/
├── reflection.md        # NEW — first-person reflection system prompt (D-17)
memory/
├── firestore_db.py      # MODIFIED — add JournalStore class
├── pinecone_db.py       # MODIFIED — add "self" to _VALID_KINDS + remember_self() path
interfaces/
├── web_server.py        # MODIFIED — add cron_reflect route
core/
├── main.py              # MODIFIED — assemble {journal_digest}, add .replace() at render step
├── tools.py             # MODIFIED — recall schema gains kind param; _handle_recall; get_self_status journal field
prompts/
├── smart_agent.md       # MODIFIED — add {journal_digest} placeholder after {self_state}
tests/
├── test_reflection.py   # NEW — Wave 0
```

### Pattern 1: Firestore Store class
**What:** A class wrapping one Firestore collection, `_make_firestore_client` in `__init__`, reads return `{}`/`None` on error and never raise, writes via `.set(..., merge=True)`.
**When to use:** `JournalStore`.
**Example:** see Code Examples below — modeled on `SelfStateStore` (`firestore_db.py:601`) for the `get`/`set` shape and `AttendanceStore` (`:226`) for the date-keyed collection + `recent_*(n)` query.

### Pattern 2: Cron route
**What:** `async def` route → `await _verify_cron_request(request)` → `try:` run logic + `_log_cron_run(job_id, ok=True)` → `except:` `_log_cron_run(job_id, ok=False); raise`.
**When to use:** `/cron/reflect`.
**Example:** `cron_proactive_alerts` (`web_server.py:310-331`) is the verbatim template. Note one structural difference: proactive-alerts needs `_application.bot`; reflection does **not** send a message, so `run_reflection()` can run without the bot — but the `if _application is None` guard pattern is still worth keeping for consistency, OR run reflection in an executor like `cron_ingest_chats` does (`web_server.py:395-404`) since `run_reflection()` is synchronous/blocking work.

### Pattern 3: Cron-context LLM call
**What:** Construct `LLMClient` inline from env vars inside the module; call `client.chat(messages=[...], system=prompt, purpose="...")`; fall back to a deterministic plain-text path on any `Exception`.
**When to use:** Both the worker summarization call and the brain reflection call.
**Example:** `core/proactive_alerts.py:_compose_alert` (`:334-366`) and `core/morning_briefing.py:250-267`.

### Anti-Patterns to Avoid
- **Calling the orchestrator's LLM clients:** Do not import `AgentOrchestrator` to reach its `smart_agent`. Build fresh `LLMClient` instances from env vars (the proactive-alerts pattern). The orchestrator is a request-scoped singleton; crons construct their own clients.
- **Letting a failed gather source abort the run:** D-01 mandates per-source try/except. A calendar API failure must not prevent the journal entry from being written.
- **Reusing `remember()` for the journal vector:** It generates a random UUID — re-runs would create duplicate vectors. D-07 needs a deterministic `self-{date}` ID via a new upsert path.
- **Injecting `{journal_digest}` into the worker prompt:** D-15 is explicit — smart-only, same exclusion as SELF.md (Phase 16 D-03). `worker_system` at `core/main.py:257` must not gain the placeholder.
- **Trusting brain JSON blindly:** Gemini may wrap JSON in markdown fences or add prose. Harden the parse (strip ```json fences, locate the first `{`...last `}`). D-13 fallback catches total failure, but a parse helper prevents a malformed-but-non-empty response from corrupting `self_state`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Firestore client construction | New client setup with credential logic | `_make_firestore_client(project_id, database)` (`firestore_db.py:24`) | Handles `FIRESTORE_CREDENTIALS` vs ADC; proactive_alerts already re-imports it |
| Owner `user_id` in cron context | New env var or hard-coded ID | `int(os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip())` per `scheduled_message.py:17` | Established cron-context owner-ID pattern; same scoping Pinecone fact/chunk memories use |
| Today's message count + cost | Manual conversation counting | `LLMUsageStore.summary("today")` → `smart_calls`, `total_cost_usd` | Already the message-count proxy used by `get_self_status` (`tools.py:1144`) |
| OIDC token verification | Custom JWT validation | `_verify_cron_request` (`web_server.py:227`) | Shared by all 7 crons; handles `CRON_DEV_BYPASS` |
| Cron liveness tracking | New status doc | `_log_cron_run("reflect", ok)` → `record_cron_run` → `heartbeat_runs/{job_id}` | Heartbeat's `check_cron_health` auto-monitors any job in `_CRON_MAX_STALENESS_HOURS` |
| LLM cost metering | Manual token accounting | `LLMClient.chat()` meters automatically (`llm_client.py:105-125`) | Pass `purpose="reflect"`/`"reflect_summary"`; metering is free and never raises |
| Israel-time "today" | Manual UTC offset math | `datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()` | The pattern in every existing cron route |

**Key insight:** Phase 17 has near-zero genuinely new logic. The only truly new code is (a) the `JournalStore` class body, (b) the `remember_self()` upsert path, (c) the gather-and-reflect orchestration in `run_reflection()`, and (d) the digest-assembly snippet in `core/main.py`. Everything else is copy-adapt from `proactive_alerts.py` + `SelfStateStore` + `cron_proactive_alerts`.

## Runtime State Inventory

> Phase 17 is **additive, not a rename/refactor.** This section is included for completeness; nothing pre-existing is being renamed.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New: `journal/{date}` Firestore collection; new Pinecone vectors `kind="self"` id `self-{date}`. Modified: `config/self_state` gains non-empty `current_focus`/`mood`/`recent_context` (Phase 16 left them `""`). | None pre-existing to migrate. First reflection run populates everything. |
| Live service config | New Cloud Scheduler job `reflect` (22:00 Asia/Jerusalem) — created post-deploy via `gcloud` (D-11). Not in git; documented as a command. | Add `gcloud scheduler` command to plan / `DEPLOYMENT.md`. |
| OS-registered state | None — Cloud Run, no OS-level registrations. | None. |
| Secrets/env vars | No new secrets. Reuses `GCP_PROJECT_ID`, `FIRESTORE_DATABASE`, `TELEGRAM_ALLOWED_USER_IDS`, `SMART_AGENT_*`, `WORKER_AGENT_*`, `PINECONE_*`, `CLOUD_RUN_URL`, `CLOUD_SCHEDULER_SA_EMAIL`, `CRON_DEV_BYPASS`. | None. |
| Build artifacts | None — no package rename, no compiled artifacts. `docs/SELF.md` regen (Phase 16 `generate_manifest()`) will now pick up the new `/cron/reflect` route and updated cron count on next deploy. | Verify `generate_manifest()` enumerates the new route — likely automatic; flag for the planner to confirm SELF.md regen reflects 8 crons. |

## Common Pitfalls

### Pitfall 1: The 6-hour conversation window — the central research question
**What goes wrong:** A planner assumes `run_reflection()` can read the full day's conversation. It cannot.
**Why it happens:** `FirestoreConversationStore.get(user_id)` (`memory/firestore_conversation.py:109-127`) checks `updated_at` against `SESSION_TIMEOUT_HOURS` (default **6**, `firestore_conversation.py:87`). If the conversation doc is older than 6h, `get()` returns `[]` — the messages are still in Firestore but the getter treats them as an expired session. A 22:00 cron reads conversation history **only if Amit messaged after ~16:00**.
**How to avoid:**
- The conversation-summary paragraph (D-01b) is genuinely best-effort. If `get()` returns `[]`, the summary step must yield `"No conversations recorded in the active session today."` and the reflection still runs.
- `message_count` (from `LLMUsageStore.summary("today").smart_calls`) is the **accurate full-day figure** — this is per-call accounting, not session-gated. Use it for the metric; never derive the count from conversation history.
- Do **not** try to bypass the gate by reading the raw `conversations/{user_id}` doc directly — that contradicts the session-window design and risks surfacing stale context. Best-effort over `get()` is the correct, CONTEXT-sanctioned behavior.
**Warning signs:** Journal entries that say "quiet day, no conversation" when `message_count` is high → the gate ate the history; that is expected, not a bug.
**Confidence:** HIGH — verified by direct read of `firestore_conversation.py` and `core/main.py:80`.

### Pitfall 2: Pinecone content cap and embed quota
**What goes wrong:** `MemoryStore.remember()` raises `ValueError` if content > `CONTENT_MAX_CHARS` (2000, `pinecone_db.py:28`). The new `remember_self()` path must enforce the same cap or truncate.
**Why it happens:** `summary` + joined `highlights` can plausibly exceed 2000 chars.
**How to avoid:** In the new upsert path, truncate the embedded text to `CONTENT_MAX_CHARS` before embedding (CONTEXT.md "Claude's Discretion" explicitly delegates this). Also: `_embed()` calls `gemini-embedding-2` via AI Studio — a single embed per reflection is well within quota (the 0.5s burst-sleep in `upsert_chat_chunks` is for batches; one embed needs no sleep).
**Warning signs:** `ValueError: content is N chars` from the reflection cron.
**Confidence:** HIGH.

### Pitfall 3: Brain structured-output fragility
**What goes wrong:** D-03 wants strict JSON with 5 fields. Gemini 3 Flash may return JSON inside ```json fences, or add a sentence before/after.
**Why it happens:** The `LLMClient.chat()` envelope returns `text` — there is no JSON mode enforced in the wrapper.
**How to avoid:** Write a `_parse_reflection_json(text)` helper: strip markdown fences, slice from first `{` to last `}`, `json.loads`, validate all 5 keys present with correct types, default missing fields. If parsing fails entirely → D-13 minimal fallback. The morning_briefing/proactive_alert prompts ask for prose (no parse needed); reflection is the first cron needing structured output, so the parse helper is genuinely new code.
**Warning signs:** `json.JSONDecodeError` or `KeyError` after the brain call.
**Confidence:** HIGH.

### Pitfall 4: TickTick has no "completed today" query
**What goes wrong:** D-01(d) says "TickTick tasks completed today." `get_today_tasks()` (`ticktick_tool.py:159`) returns only **incomplete** tasks (`status != 0` are skipped, `ticktick_tool.py:195`). There is no existing "completed today" accessor.
**Why it happens:** `get_today_tasks()` was built for the morning briefing (what's due), not for retrospective accounting.
**How to avoid:** Two options for the planner — (a) interpret D-01(d) as "today's tasks" (due today, the data `get_today_tasks()` already returns) and record the count; or (b) add a small new TickTick accessor that fetches completed tasks. Option (a) is lower-surface-area and consistent with "best-effort gather"; the TickTick Open API's completed-task endpoint is `GET /open/v1/project/{projectId}/data` which already returns completed items but `get_today_tasks` filters them out. **Recommendation: the planner should explicitly decide and note this** — it is the one place where D-01's wording ("completed today") does not match an existing accessor. Flag as Open Question.
**Confidence:** MEDIUM — `get_today_tasks()` behavior is HIGH-confidence verified; the "best interpretation of D-01(d)" is a planning judgment call.

### Pitfall 5: Cron job-id and heartbeat monitoring
**What goes wrong:** `_log_cron_run("reflect", ...)` writes to `heartbeat_runs/reflect`, but `core/heartbeat.py:_CRON_MAX_STALENESS_HOURS` (`:108-113`) does **not** include `"reflect"` — so the heartbeat will not flag a stalled reflect cron.
**Why it happens:** The staleness dict is a hard-coded allow-list of 4 jobs.
**How to avoid:** Add `"reflect": 26` to `_CRON_MAX_STALENESS_HOURS` so heartbeat monitors it (a daily job tolerates 26h like proactive-alerts). This is a one-line change the planner should include — otherwise a silently-dead reflection cron goes unnoticed. Note: `check_cron_health` also flags **any** job in the ledger with a failure streak ≥ 3 (`heartbeat.py:164-169`), so failures are caught regardless; only staleness needs the dict entry.
**Confidence:** HIGH.

### Pitfall 6: First-run absence of yesterday's journal
**What goes wrong:** D-18 feeds `journal/{yesterday}` into the prompt. On the first ever run there is no yesterday entry.
**How to avoid:** `JournalStore.get(yesterday_date)` returns `None` (the `SelfStateStore`/`AttendanceStore` pattern). The reflection prompt's continuity section must be conditionally omitted when absent — same blank-field omission discipline as Phase 16 D-05 and the `{journal_digest}` empty-state rule.
**Confidence:** HIGH.

## Code Examples

### JournalStore (new class in memory/firestore_db.py — modeled on SelfStateStore + AttendanceStore)
```python
# Source: pattern verified from SelfStateStore (firestore_db.py:601) +
#         AttendanceStore date-keyed collection (firestore_db.py:226).
class JournalStore:
    """Daily reflection journal stored in Firestore.

    Collection: journal
    Document ID: YYYY-MM-DD (Asia/Jerusalem calendar date).

    Each doc stores the 5 LLM reflection fields (summary, mood, current_focus,
    recent_context, highlights) plus the raw gathered metrics for auditability.
    """

    _COLLECTION = "journal"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def get(self, date_str: str) -> dict | None:
        """Return the journal doc for a date, or None. Never raises."""
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return None
            data = snap.to_dict() or {}
            data["date"] = snap.id
            return data
        except Exception:
            logger.warning("JournalStore.get(%r) failed", date_str, exc_info=True)
            return None

    def set(self, date_str: str, entry: dict) -> None:
        """Overwrite the journal doc for a date (D-12 idempotency). Raises on failure."""
        try:
            self._col.document(date_str).set(
                {**entry, "date": date_str, "updated_at": firestore.SERVER_TIMESTAMP}
            )
        except Exception:
            logger.error("JournalStore.set(%r) failed", date_str, exc_info=True)
            raise

    def get_recent(self, n: int) -> list[dict]:
        """Return the most-recent n journal docs, newest-first. Returns [] on error."""
        # WHY stream() + Python sort: single-user; journal will hold < a few thousand
        # docs, far below the level where a composite index is worth the overhead.
        try:
            snaps = self._col.stream()
        except Exception:
            logger.warning("JournalStore.get_recent failed", exc_info=True)
            return []
        results = []
        for snap in snaps:
            data = snap.to_dict() or {}
            data["date"] = snap.id
            results.append(data)
        results.sort(key=lambda d: d.get("date", ""), reverse=True)
        return results[:n]
```
Note: D-12 says "overwrite" — `JournalStore.set` uses `.set()` **without** `merge=True` so a re-run replaces the whole doc cleanly (a re-run with fewer fields should not leave stale keys). `SelfStateStore.set` uses `merge=True` because it patches; `JournalStore` writes the full entry each time.

### Pinecone: add "self" kind + deterministic-ID upsert path
```python
# Source: memory/pinecone_db.py — _VALID_KINDS at :29, remember() at :55.
_VALID_KINDS = frozenset({"fact", "chunk", "chat", "self"})   # D-06: add "self"

# New method on MemoryStore — remember() cannot take a custom ID (it hard-codes
# uuid.uuid4() at pinecone_db.py:80). D-07 needs deterministic self-{date}.
def remember_self(self, user_id: int, date_str: str, content: str) -> str:
    """Upsert a journal entry with a deterministic vector ID (self-{date}).

    A re-run for the same date overwrites the existing vector — no duplicates.
    """
    if len(content) > CONTENT_MAX_CHARS:
        content = content[:CONTENT_MAX_CHARS]   # truncate per CONTEXT discretion
    vector = self._embed(content)
    vector_id = f"self-{date_str}"
    ts = datetime.now(tz=timezone.utc).isoformat()
    self._get_index().upsert(vectors=[{
        "id": vector_id,
        "values": vector,
        "metadata": {
            "user_id": str(user_id),
            "kind": "self",
            "content": content,
            "ts": ts,
        },
    }])
    return vector_id
```

### recall tool: optional `kind` parameter (D-08)
```python
# Source: core/tools.py — recall schema at :237, _handle_recall at :904,
#         _HANDLERS entry at :1180. recall() already accepts kinds (pinecone_db.py:96).

# 1. In TOOL_SCHEMAS recall entry (:237), add to "properties":
#       "kind": {
#           "type": "string",
#           "enum": ["fact", "chunk", "self"],
#           "description": "Optional. Restrict recall to one memory kind. "
#                          "'self' searches Klaus's own journal entries. "
#                          "Omit for the default fact+chunk search.",
#       }
#    "kind" is NOT added to "required" — default behavior unchanged.

# 2. _handle_recall (:904):
def _handle_recall(query: str, k: int = 5, kind: str | None = None) -> str:
    kinds = [kind] if kind else None          # None → recall() default ["fact","chunk"]
    result = _get_memory_tool().recall(_get_current_user_id(), query, k, kinds=kinds)
    return json.dumps(result)

# 3. MemoryTool.recall (mcp_tools/memory.py:49) currently has signature
#    recall(self, user_id, query, k=5) — it does NOT forward `kinds`.
#    It must gain a `kinds` param and pass it to self._store.recall(...).
#    (search_chat_history already calls self._store.recall(..., kinds=["chat"]) —
#     proof the underlying store supports it; only MemoryTool.recall needs the param.)
```
**Important correction for the planner:** `MemoryTool.recall` (`mcp_tools/memory.py:49`) does **not** currently accept `kinds`. D-08 says "`recall()` already accepts a `kinds` param" — true for `MemoryStore.recall`, but the agent-facing `MemoryTool.recall` wrapper does not forward it. The plan must add `kinds` to `MemoryTool.recall` as well. This is a real (small) gap between D-08's wording and the code.

### /cron/reflect route (verbatim adaptation of cron_proactive_alerts, web_server.py:310)
```python
# Source: interfaces/web_server.py:310 cron_proactive_alerts + :381 cron_ingest_chats
#         (executor pattern for synchronous work).
@app.post("/cron/reflect")
async def cron_reflect(request: Request) -> JSONResponse:
    """Daily reflection — gather the day, write a journal entry, evolve self_state.

    Schedule: 0 22 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.reflection as _reflection
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        loop = _asyncio.get_running_loop()
        # run_reflection is blocking (Firestore + LLM); run off the event loop.
        await loop.run_in_executor(None, _reflection.run_reflection, today)
        _log_cron_run("reflect", ok=True)
    except Exception:
        _log_cron_run("reflect", ok=False)
        raise
    return JSONResponse(content={"ok": True})
```
Rationale for the executor: `run_reflection()` is synchronous blocking work (Firestore reads, two LLM calls). `cron_ingest_chats` (`web_server.py:395-404`) already uses `loop.run_in_executor` for the same reason. Proactive-alerts is `async` end-to-end because it `await`s `bot.send_message`; reflection sends nothing, so a synchronous `run_reflection(today)` run in an executor is the cleaner fit. The planner may choose either; the executor approach avoids making every gather helper `async`.

### {journal_digest} assembly in core/main.py (D-14/D-15)
```python
# Source: core/main.py:240-256 — self_state snippet assembly + render step.
# Add a journal-digest snippet alongside the existing self_state snippet, then
# add one .replace() call. {journal_digest} goes AFTER {self_state}, BEFORE
# {today_date} (D-15 ordering: stable SELF.md → self_state → journal_digest → date).

journal_digest = ""
if self._journal_store is not None:
    entries = self._journal_store.get_recent(3)         # newest-first
    if entries:
        lines = ["**Recent journal:**"]
        for e in entries:
            mood = e.get("mood", "")
            summary = e.get("summary", "")
            line = f"- {e.get('date','')} (mood: {mood}): {summary}"
            highlights = e.get("highlights") or []
            if highlights:
                line += f" | {highlights[0]}"
            lines.append(line)
        journal_digest = "\n".join(lines)
    # else: leave journal_digest = "" — block omitted entirely (empty-state rule)

smart_system = (
    self._smart_prompt_template
    .replace("{self_md}", self._self_md_content)
    .replace("{self_state}", self_state_snippet)
    .replace("{journal_digest}", journal_digest)     # NEW — after self_state
    .replace("{today_date}", today_label)
)
# worker_system is UNCHANGED — D-15 smart-only.
```
The orchestrator needs a `self._journal_store` built in `__init__` exactly like `self._self_state_store` via a `_build_journal_store()` helper mirroring `_build_self_state_store()` (`core/main.py:553-563`). `prompts/smart_agent.md` must add a `{journal_digest}` placeholder — current file has `{self_md}` line 1, `{self_state}` line 3; insert `{journal_digest}` on a new line after `{self_state}`.

### get_self_status journal field (D-16, tools.py:1159)
```python
# Source: core/tools.py:1158-1159 — replace `result["journal"] = None`.
# --- Journal (Phase 17) ---
try:
    project_id = _os.environ.get("GCP_PROJECT_ID")
    if project_id:
        database = _os.environ.get("FIRESTORE_DATABASE", "(default)")
        from memory.firestore_db import JournalStore
        recent = JournalStore(project_id=project_id, database=database).get_recent(1)
        if recent:
            j = recent[0]
            result["journal"] = {
                "date": j.get("date"),
                "summary": j.get("summary"),
                "mood": j.get("mood"),
            }
        else:
            result["journal"] = None
    else:
        result["journal"] = None
except Exception as exc:
    result["journal"] = None
    result["journal_error"] = str(exc)
```

### Cloud Scheduler job creation (D-11 — documented gcloud command)
```bash
# Source: pattern for the existing 7 crons. Add to DEPLOYMENT.md.
gcloud scheduler jobs create http reflect \
  --schedule="0 22 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${CLOUD_RUN_URL}/cron/reflect" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${CLOUD_RUN_URL}" \
  --location="${SCHEDULER_LOCATION}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `self_state` fields (`current_focus`, `mood`, `recent_context`) empty strings | Phase 17 `run_reflection()` is their first writer | This phase | `core/main.py`'s self_state snippet (`:243-249`) already omits blank fields — once reflection runs, the snippet starts showing real data automatically. No render-step change needed for self_state itself. |
| `get_self_status.journal` hard-coded `None` | Returns latest `JournalStore` entry | This phase | Closes the Phase-16 MODEL-05 "degrades gracefully when journal absent" forward-reference. |
| `_VALID_KINDS = {fact, chunk, chat}` | `+ self` | This phase | Recall can now target journal memories. |
| 7 Cloud Scheduler crons | 8 (adds `reflect`) | This phase | `docs/SELF.md` regen (`generate_manifest()`) should reflect 8; `_CRON_MAX_STALENESS_HOURS` needs the `reflect` entry. |

**Deprecated/outdated:** None. CONTEXT.md `<canonical_refs>` line numbers are accurate except: the Pinecone class is `MemoryStore` not `PineconeStore` (naming only — methods `remember`/`recall` are as cited); `recall()` is at `:96` and its `kinds` default at `:112` (CONTEXT cites `:96` for recall — correct).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | D-01(d) "tasks completed today" is best satisfied by recording the count from `get_today_tasks()` (today's due tasks) since no "completed today" accessor exists | Pitfall 4 / Open Questions | LOW — both interpretations produce an auditable metric; planner should explicitly decide. The reflection still runs either way. |
| A2 | Running `run_reflection()` in a thread-pool executor (sync) is preferable to making it `async` | Code Examples (cron route) | LOW — both work; `cron_ingest_chats` precedent supports the executor. Planner may choose async. |
| A3 | `generate_manifest()` (Phase 16) auto-discovers the new `/cron/reflect` route for SELF.md without manual edits | Runtime State Inventory | LOW-MEDIUM — if `generate_manifest()` hard-codes a route list, SELF.md won't update. Planner should verify by reading `generate_manifest()`. |
| A4 | `gemini-2.5-flash` (worker) can produce a usable conversation-summary paragraph from a plain-text prompt without tool schemas | D-02 implementation | LOW — it is a pure summarization task well within worker capability; verified the worker model is used for structured/text output throughout the codebase. |

## Open Questions

1. **D-01(d) "TickTick tasks completed today" — which data source?**
   - What we know: `get_today_tasks()` (`ticktick_tool.py:159`) returns only **incomplete** tasks; completed tasks (`status != 0`) are filtered out. The TickTick Open API endpoint `GET /open/v1/project/{id}/data` does return completed items in its response, but the existing accessor discards them.
   - What's unclear: whether the planner should (a) record the count of today's *due* tasks (zero new code) or (b) add a small new "completed today" accessor to `ticktick_tool.py`.
   - Recommendation: Option (a) for minimal surface area and consistency with "best-effort gather" — record `tasks_today_count` from `get_today_tasks()["today"]`. If the user later wants genuine completion tracking, that is a clean fast-follow. The planner should make this an explicit, documented decision in the plan.

2. **`MemoryTool.recall` does not forward `kinds` — confirm the plan adds it.**
   - What we know: `MemoryStore.recall` accepts `kinds`; `MemoryTool.recall` (the agent-facing wrapper, `mcp_tools/memory.py:49`) does not. D-08's wording ("`recall()` already accepts a `kinds` param") is true only for the lower-level store.
   - What's unclear: nothing — this is just a gap to flag so the plan covers all three layers (schema, `MemoryTool.recall`, `_handle_recall`).
   - Recommendation: The plan's D-08 task must touch `mcp_tools/memory.py` as well as `core/tools.py`.

3. **SELF.md regeneration scope.**
   - What we know: Phase 16 `generate_manifest()` introspects cron routes for SELF.md and embeds a content hash for staleness detection.
   - What's unclear: whether adding `/cron/reflect` + the `recall` schema change triggers an automatic SELF.md update on next deploy, or needs a manual regen step.
   - Recommendation: Planner reads `generate_manifest()` (Phase 16 deliverable) and confirms the route is auto-discovered. If `cloudbuild.yaml` runs the regen on deploy (CONTEXT `<code_context>` says no new CI step needed), this is automatic — but worth one verification read.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Firestore (`google-cloud-firestore`) | `JournalStore`, all stores | ✓ | in use | — |
| Pinecone (`pinecone`) | `kind="self"` upsert/recall | ✓ | in use | — |
| Gemini API (`google-genai`) | brain + worker LLM calls, embeddings | ✓ | in use | — |
| Anthropic (`anthropic`) | brain fallback (`claude-haiku-4-5`) | ✓ | in use | — |
| Cloud Scheduler | triggers `/cron/reflect` | ✓ | external — created post-deploy via gcloud | `CRON_DEV_BYPASS=true` for local test |
| Google Calendar API | D-01(c) today's events | ✓ | in use | per-source try/except (D-01) |
| TickTick Open API | D-01(d) tasks | ✓ | in use | per-source try/except (D-01) |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** The Cloud Scheduler `reflect` job does not exist yet (created post-deploy, D-11) — local/CI testing uses `CRON_DEV_BYPASS=true` to hit `/cron/reflect` directly, exactly as the phase success criteria specify.

## Validation Architecture

> `.planning/config.json` not found in repo root. Treating `nyquist_validation` as enabled (default). The project uses `pytest` (14 test files in `tests/`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` (verified — `tests/` contains 14 `test_*.py` files, e.g. `test_proactive_alerts.py`, `test_llm_usage_store.py`) |
| Config file | None at repo root (no `pytest.ini`/`pyproject.toml [tool.pytest]` found) — pytest uses defaults; `tests/__init__.py` present |
| Quick run command | `pytest tests/test_reflection.py -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JOUR-01 | `run_reflection()` gathers + writes a journal entry; failed source omitted, run still completes | unit | `pytest tests/test_reflection.py::test_run_reflection_writes_entry -x` | ❌ Wave 0 |
| JOUR-01 | A failing gather source (e.g. calendar raises) does not abort the run | unit | `pytest tests/test_reflection.py::test_gather_source_failure_is_isolated -x` | ❌ Wave 0 |
| JOUR-02 | `JournalStore.set`/`get`/`get_recent` round-trip; date-keyed | unit | `pytest tests/test_reflection.py::test_journal_store_roundtrip -x` | ❌ Wave 0 |
| JOUR-03 | `remember_self` upserts with deterministic `self-{date}` id; re-run overwrites | unit | `pytest tests/test_reflection.py::test_remember_self_deterministic_id -x` | ❌ Wave 0 |
| JOUR-04 | `"self"` in `_VALID_KINDS`; `recall(kinds=["self"])` round-trips; default recall unchanged | unit | `pytest tests/test_reflection.py::test_recall_self_kind -x` | ❌ Wave 0 |
| JOUR-05 | `/cron/reflect` returns 200; `CRON_DEV_BYPASS` skips auth; `_log_cron_run("reflect")` called | integration | `pytest tests/test_reflection.py::test_cron_reflect_route -x` | ❌ Wave 0 |
| JOUR-06 | `{journal_digest}` assembled from `get_recent(3)`; empty when no entries; absent from worker prompt | unit | `pytest tests/test_reflection.py::test_journal_digest_assembly -x` | ❌ Wave 0 |
| D-13 | brain+fallback failure → minimal fallback doc written with raw metrics | unit | `pytest tests/test_reflection.py::test_reflection_llm_failure_fallback -x` | ❌ Wave 0 |
| D-03 | brain JSON wrapped in ```json fences still parses; missing field defaults safely | unit | `pytest tests/test_reflection.py::test_parse_reflection_json_hardened -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_reflection.py -x -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`; manual success criteria 1-4 from ROADMAP §"Phase 17" (cron → Firestore doc, self_state fields, Pinecone upsert, digest in assembled prompt).

### Wave 0 Gaps
- [ ] `tests/test_reflection.py` — covers JOUR-01 through JOUR-06 + D-03/D-13. Mock Firestore (`unittest.mock` of `_make_firestore_client`) and `LLMClient.chat` — `tests/test_proactive_alerts.py` and `tests/test_llm_usage_store.py` are the pattern references.
- [ ] No `conftest.py` exists in `tests/` — if shared fixtures (mock Firestore client, mock `LLMClient`) are needed across files, add `tests/conftest.py`. Otherwise per-file fixtures suffice (existing files do not use a conftest).
- [ ] Framework install: none — `pytest` is already the project test runner.

## Security Domain

> `.planning/config.json` absent → `security_enforcement` treated as enabled. Phase 17 is a backend cron + datastore phase, single-user, no new auth surface.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new user-facing auth; single-user system |
| V3 Session Management | no | No sessions introduced |
| V4 Access Control | yes | `/cron/reflect` MUST go through `_verify_cron_request` (OIDC, `web_server.py:227`) — same control as all 7 crons. `CRON_DEV_BYPASS` is dev-only and gated on an env var. |
| V5 Input Validation | yes | Brain LLM output is parsed as JSON before being written to Firestore/Pinecone — harden the parse (Pitfall 3). LLM output is not executed, only stored, so injection risk is low; still validate the 5 expected keys/types. |
| V6 Cryptography | no | No new crypto; OIDC verification reuses `verify_oauth2_token` |

### Known Threat Patterns for {FastAPI cron route + Firestore + Pinecone, single-user GCP}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthenticated cron trigger (anyone POSTs `/cron/reflect`) | Spoofing / Elevation | `_verify_cron_request` OIDC token + audience + SA-email check — already enforced; the new route must call it first, before any work |
| `CRON_DEV_BYPASS` left `true` in production | Elevation | Confirm prod env does not set it; it defaults to `"false"` (`web_server.py:239`). Plan/DEPLOYMENT.md should note this. |
| LLM output containing prompt-injection text written verbatim into the journal | Tampering | Low impact — journal is single-user, read back only into Klaus's own prompt. Validate JSON structure; do not `eval`/execute any field. The digest injects `summary`/`mood` as plain text into a prompt — acceptable for a single-user trusted-owner system. |
| Pinecone metadata size / content cap bypass | DoS | Truncate to `CONTENT_MAX_CHARS` before embed (Pitfall 2) |
| Cross-user memory leak via `kind="self"` | Information Disclosure | `recall()` already filters `user_id` with `$eq` (`pinecone_db.py:117-119`); `remember_self` must set `metadata.user_id` identically — the example above does. |

## Sources

### Primary (HIGH confidence)
- Direct codebase read (2026-05-19) — `memory/firestore_db.py` (`SelfStateStore` :601, `LLMUsageStore` :519, `AttendanceStore` :226, `_make_firestore_client` :24)
- Direct codebase read — `memory/pinecone_db.py` (`MemoryStore` :32, `_VALID_KINDS` :29, `remember` :55, `recall` :96, `CONTENT_MAX_CHARS` :28)
- Direct codebase read — `memory/firestore_conversation.py` (`get` :109-127, `SESSION_TIMEOUT_HOURS` :87) — **resolves the central research question**
- Direct codebase read — `interfaces/web_server.py` (`_verify_cron_request` :227, `_log_cron_run` :273, `cron_proactive_alerts` :310, `cron_ingest_chats` executor :395)
- Direct codebase read — `core/main.py` (render step :251-256, self_state snippet :240-249, `_build_self_state_store` :553)
- Direct codebase read — `core/tools.py` (`recall` schema :237, `_handle_recall` :904, `_HANDLERS` :1180, `get_self_status` journal stub :1159, `SMART_AGENT_DIRECT_TOOLS` :39, `WORKER_TOOL_SCHEMAS` :692)
- Direct codebase read — `core/proactive_alerts.py` (full — cron-context LLM + fallback pattern), `core/scheduled_message.py` (`_telegram_user_id` :17), `core/heartbeat.py` (`_read_cron_ledger` :117, `_CRON_MAX_STALENESS_HOURS` :108)
- Direct codebase read — `mcp_tools/memory.py` (`MemoryTool.recall` :49 — confirmed it does NOT forward `kinds`)
- Direct codebase read — `mcp_tools/calendar_tool.py` (`list_events` :71), `mcp_tools/ticktick_tool.py` (`get_today_tasks` :159 — confirmed incomplete-only filter)
- Direct codebase read — `core/llm_client.py` (`LLMClient.chat` :83, auto-metering :105), `core/pricing.py` (`MODEL_PRICING` :15)
- `docs/TECHNICAL_PLAN.md` §2 + §"LLM Strategy" — verified model map
- `docs/AGENT.md`, `prompts/smart_agent.md` — persona + placeholder structure for `reflection.md` tone
- `.planning/REQUIREMENTS.md` (JOUR-01–06), `.planning/STATE.md`, `.planning/phases/17-reflection-journal/17-CONTEXT.md`

### Secondary (MEDIUM confidence)
- None — all claims verified against live code.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every component read directly from the live codebase; no new dependencies.
- Architecture: HIGH — `/cron/reflect`, `JournalStore`, `remember_self`, digest injection all have verified existing templates.
- Pitfalls: HIGH — the conversation-window gate, TickTick filter, `MemoryTool.recall` gap, and `_CRON_MAX_STALENESS_HOURS` omission were each confirmed by reading the relevant source.
- Central research question (conversation retrievability): HIGH — resolved by `firestore_conversation.py:109-127` + `SESSION_TIMEOUT_HOURS` default 6.

**Research date:** 2026-05-19
**Valid until:** 2026-06-18 (stable established codebase; 30-day window). Line numbers may drift with any edit to the cited files — the planner should treat them as approximate and grep-confirm before editing.
