# Phase 17: Reflection & Journal - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning

<domain>
## Phase Boundary

A daily reflection cron (`/cron/reflect`, 22:00 Asia/Jerusalem) gathers the day's
data, makes LLM calls to produce a structured journal entry, writes it to a new
`JournalStore` in Firestore (`journal/{date}`) and to Pinecone (`kind="self"`),
updates the Phase-16 `SelfStateStore` fields, and injects a digest of the last
~3 journal entries into every conversation. `get_self_status`'s `journal` stub is
filled in.

Scope is JOUR-01 through JOUR-06. Phase 18 owns autonomous outreach — Phase 17
only makes the self-model persistent and evolving.

</domain>

<decisions>
## Implementation Decisions

### Day Data Gathering
- **D-01:** `run_reflection()` gathers, each step best-effort (try/except — a failed
  source is omitted and noted, the reflection still runs and writes an entry):
  (a) today's message count + LLM cost from `LLMUsageStore.summary("today")`;
  (b) a conversation summary paragraph;
  (c) today's Google Calendar events via the existing calendar tool;
  (d) TickTick tasks completed today;
  (e) heartbeat last-run status.
- **D-02:** Two-tier LLM use — conversation summarization runs on the **worker**
  (`gemini-2.5-flash`, cheaper); the reflection itself runs on the **brain**
  (`gemini-3-flash-preview`). Both cost-metered via `LLMUsageStore`.

### Journal Entry Schema
- **D-03:** The reflection (brain) call outputs structured JSON with 5 fields:
  `summary` (2-3 sentence day overview), `mood` (short string), `current_focus`
  (string), `recent_context` (string), `highlights` (list of strings).
- **D-04:** The `journal/{date}` Firestore doc stores the 5 LLM fields **plus** the
  raw gathered metrics — `message_count`, `cost_usd`, `calendar_event_count`,
  `tasks_completed`, `heartbeat_ok` — so each entry is auditable against its inputs.
- **D-05:** `run_reflection()` updates `SelfStateStore` via `.set()`:
  `current_focus` and `mood` are **replaced**; `recent_context` is a **rolling
  3-day window** (append the latest, trim the oldest).

### Pinecone Self-Memory
- **D-06:** `kind="self"` added to `_VALID_KINDS` in `memory/pinecone_db.py` (JOUR-04).
- **D-07:** Each journal entry is upserted to Pinecone with a **deterministic vector
  ID `self-{date}`** so a re-run overwrites cleanly (no duplicate vector). Embedded
  text = `summary` + `highlights` joined. Needs a small new upsert path —
  `remember()` generates random UUIDs and cannot take a custom ID.
- **D-08:** Brain self-recall — **extend the existing `recall` direct tool with an
  optional `kind` parameter** (`"fact"`|`"chunk"`|`"self"`); `_handle_recall` passes
  `kinds=[kind]` through to `PineconeStore.recall()`. No new tool, no 6th direct-tool
  registration. `recall()` already accepts a `kinds` param. Default recall behavior
  (fact+chunk) is unchanged. (User deferred this choice to Claude — chosen for
  lowest surface area; journal recall is semantically the same vector search.)

### Reflection Cron
- **D-09:** `/cron/reflect` route added to `interfaces/web_server.py`, OIDC-authed via
  `_verify_cron_request`, logged via `_log_cron_run("reflect", ...)`. Same shape as
  `cron_proactive_alerts`. `CRON_DEV_BYPASS=true` skips auth for local testing.
- **D-10:** Cloud Scheduler runs `/cron/reflect` **daily at 22:00 Asia/Jerusalem**
  (after the 21:30 proactive-alerts cron — the day is effectively closed). The
  `journal/{date}` key uses the Asia/Jerusalem calendar date.
- **D-11:** Phase 17 delivers the route; the Cloud Scheduler job is created via a
  documented `gcloud` command (in the plan / `DEPLOYMENT.md`) — consistent with how
  the other 7 crons were set up.
- **D-12:** Idempotency — a second run on the same day **overwrites** `journal/{date}`
  and re-upserts the `self-{date}` vector (deterministic ID replaces). `self_state`
  reflects the latest run.
- **D-13:** If the core reflection LLM call fails (brain + fallback both error), write
  a **minimal fallback** `journal/{date}` doc with the raw metrics and a placeholder
  summary (`"reflection unavailable"`); the journal stays gap-free. `_log_cron_run`
  records the failure.

### Prompt Digest Injection (JOUR-06)
- **D-14:** Per-message `smart_system` assembly injects a `{journal_digest}`
  placeholder — a compact bullet block of the last ~3 journal entries, one line each:
  `- {date} (mood: {mood}): {summary}` plus the top highlight when `highlights` is
  non-empty.
- **D-15:** Placeholder ordering in the template: SELF.md (stable) → `{self_state}`
  → `{journal_digest}` → `{today_date}`. **Smart-only** — the worker never sees it
  (same exclusion as SELF.md, per Phase 16 D-03).

### get_self_status
- **D-16:** The `get_self_status` `journal` field (currently `None` at
  `core/tools.py:1159`) returns `{date, summary, mood}` from the most recent
  `JournalStore` entry.

### Reflection Prompt
- **D-17:** `prompts/reflection.md` is written in **first person as Klaus** ("Today I
  helped Amit..."). The journal reads as Klaus's own diary — `mood`/`focus` are
  genuinely his. Tone aligned with `docs/AGENT.md` persona.
- **D-18:** The reflection prompt receives **yesterday's journal entry** (`summary` +
  `current_focus` from `journal/{yesterday}`) as input for day-to-day continuity.
  Best-effort — absent on the first ever run.

### Claude's Discretion
- Digest empty state: with fewer than 3 entries, include whatever exists; omit the
  block entirely when empty (consistent with Phase 16 D-05 blank-field omission).
- `highlights[]` cap (suggest 3-5 items), exact `reflection.md` wording, and
  JSON-parse hardening for the brain's structured output.
- Embedded-text truncation if `summary` + `highlights` exceeds Pinecone
  `CONTENT_MAX_CHARS`.
- `user_id` sourcing for `run_reflection()` (the cron has no request context) —
  reuse whatever owner-ID env var the proactive-alerts cron already uses for
  Pinecone scoping and conversation lookup.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — JOUR-01 through JOUR-06, all acceptance criteria
- `.planning/ROADMAP.md` §"Phase 17 — Reflection & Journal" — key files + success criteria

### Architecture
- `docs/TECHNICAL_PLAN.md` — LLM-per-purpose model map, Firestore database naming
- `docs/AGENT.md` — Klaus persona and behavioral directives (informs `reflection.md` tone)

### Integration Points
- `memory/firestore_db.py:601` — `SelfStateStore` (template for the new `JournalStore`;
  also the target of the `self_state` update in D-05)
- `memory/firestore_db.py:519` — `LLMUsageStore.summary()` for day cost + message count
- `memory/pinecone_db.py:29` — `_VALID_KINDS` frozenset (add `"self"`)
- `memory/pinecone_db.py:55` — `remember()` (random-UUID pattern; new `self-{date}`
  upsert path needed)
- `memory/pinecone_db.py:96` — `recall()` (already accepts `kinds` param)
- `interfaces/web_server.py:227` — `_verify_cron_request` (OIDC auth)
- `interfaces/web_server.py:273` — `_log_cron_run`
- `interfaces/web_server.py:310` — `cron_proactive_alerts` (shape template for `/cron/reflect`)
- `core/main.py:205–257` — per-message prompt render step; `{journal_digest}` placeholder
- `core/tools.py:238` / `:697` / `:904` / `:1180` — `recall` tool registration sites
  (schema, worker-exclusion list, `_handle_recall`, `_HANDLERS` dispatch)
- `core/tools.py:1159` — `result["journal"] = None` stub in `get_self_status` (fill in)

### Prior Phase Context
- `.planning/phases/16-self-model-state-awareness/16-CONTEXT.md` — D-03 (smart-only
  prompt injection + stable-content-first ordering), D-04/D-05 (`SelfStateStore`
  bootstrap + blank-field omission), Store class patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SelfStateStore` (`memory/firestore_db.py:601`) — singleton-doc Store with
  `get()`/`set(patch)`/`bootstrap_if_empty()`; `JournalStore` mirrors this but keyed
  by date (`journal/{date}`) instead of a fixed document.
- `LLMUsageStore.summary("today")` — returns `smart_calls` (message-count proxy) +
  `total_cost_usd`; D-01's cost/count gather reuses this directly.
- `cron_proactive_alerts` (`interfaces/web_server.py:310`) — OIDC verify →
  run logic → `_log_cron_run` try/except shape; `/cron/reflect` copies it.
- `recall()` already takes `kinds` — D-08 only needs the tool-layer param plumbing.

### Established Patterns
- Store pattern: `__init__(project_id, database)` → `_make_firestore_client` →
  document methods; all Firestore reads return `{}`/`None` on error, never raise.
- Direct tool registration: `recall` is already a direct tool — D-08 modifies its
  schema + `_handle_recall` rather than adding a new tool.
- Prompt template replacement at `core/main.py` render step:
  `.replace("{self_state}", ...)` etc. — add `.replace("{journal_digest}", ...)`.
- Inline brain→Haiku fallback (`core/main.py:260–291`) is the reference for the
  reflection call's model-fallback chain.

### Integration Points
- `cloudbuild.yaml` — no new CI step needed (SELF.md regen from Phase 16 is unaffected).
- `AgentOrchestrator` per-message render — `{journal_digest}` assembled here, smart-only.

</code_context>

<specifics>
## Specific Ideas

- The journal must read as Klaus's own first-person diary, not a system log (D-17) —
  this is the milestone's "consciousness" theme made concrete.
- `recent_context` as a rolling 3-day window (D-05) is deliberately redundant with the
  injected digest (JOUR-06) — it keeps continuity even if digest injection fails.
- Cost discipline: summarization is pushed to the worker model (D-02); only the
  reflection reasoning uses the brain.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

### Research flag (for researcher/planner)
- Conversation-history retrievability: with 6h conversation resets,
  `FirestoreConversationStore.get(user_id)` may return only the current window, not
  the full day. The D-01 summary paragraph is best-effort over whatever is
  retrievable; `message_count` from `LLMUsageStore` remains the accurate full-day
  figure. The researcher should confirm what conversation data a 22:00 cron can
  actually read.

</deferred>

---

*Phase: 17-reflection-journal*
*Context gathered: 2026-05-19*
