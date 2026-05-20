# Phase 18: The Autonomous Engine (Capstone) - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Klaus decides on his own judgment when to proactively reach out. A 20-min cron
tick (`*/20 7-21` Asia/Jerusalem) runs a 3-layer pipeline:

- **Layer 0 (free gather):** `gather_situation()` fetches calendar, TickTick,
  unread email count, due follow-ups, hours_since_contact, recent journal,
  current self_state, and today's outreach log.
- **Layer 1 (tick-brain judgment):** Free Groq/Qwen3-32B (existing
  `core/tick_brain.py`) judges whether to speak. Returns
  `{should_act, reason, draft, topic_key}`.
- **Layer 2 (main-brain compose):** On escalation, runs the full smart_agent
  tool-loop with `prompts/autonomous.md` as the system prompt and the situation
  snapshot + tick-brain draft as the synthetic user message.

Sends land in Telegram **and** in conversation history (so the user's reply is
a natural follow-up). Repeat-suppression via per-day `outreach_log/{date}`.
User-scheduled `schedule_followup(when, note)` follow-ups fire on time via the
same tick. A judgment eval harness (`evals/tick_brain/` + `scripts/eval_tick_brain.py`)
scores tick-brain precision/recall against labeled situation snapshots.

Scope is AUTO-01 through AUTO-09 plus INFRA-01. The reflection cron, SelfStateStore,
JournalStore, and journal_digest injection are all Phase 17 — Phase 18 only consumes them.

</domain>

<decisions>
## Implementation Decisions

### Outreach latitude

- **D-01:** Allowed trigger types: **overdue TickTick tasks**, **calendar gaps /
  overload** (within the day, after the morning briefing has been delivered),
  **long silence** (hours_since_contact crosses Klaus's own judgment threshold),
  and **due follow-ups** (always). **Not** same-day event prep — the 21:30
  proactive-alerts cron + morning-briefing-tick already cover tomorrow's prep
  and same-day boot.
- **D-02:** **No cadence cap.** Klaus uses judgment, not a frequency throttle.
  No "max N per day" rule in the triage prompt. Mirrors PROJECT.md's "measure,
  never enforce."
- **D-03:** **Mixed-register voice.** Action when there is one (overdue task,
  travel buffer mismatch → suggested action), observation when there isn't
  (long-silence check-in, pattern notice — observational in Klaus's first-person
  voice). The triage `draft` and Layer-2 compose both follow this rule.
- **D-04:** The **triage call sees Klaus's self-state** alongside the raw
  situation: last ~3 journal entries (the same digest from Phase 17 D-14) +
  `current_focus` + `mood` from `SelfStateStore`. Cost is negligible at Groq;
  the milestone is "Consciousness & Autonomy" — judgment with evolving self is
  the point.
- **D-05:** **No hard floor on `hours_since_contact`.** It's passed raw to the
  triage prompt; tick-brain decides what counts as "long" given context. Aligned
  with "trust Klaus's judgment."

### Repeat-suppression (informative, not blocking)

- **D-06:** Per-topic dedup is the **default**, but suppression is
  **informative** (the triage prompt is *told* what was already raised today),
  not blocking. Klaus can re-raise a topic if a deadline brings it back into
  urgency, or for an EOD check-in.
- **D-07:** **Klaus generates the `topic_key`** as part of the triage JSON
  output. The tick-brain output schema (currently
  `{should_act, reason, draft}`) gains a fourth field `topic_key` (short slug
  Klaus chooses — examples: `"overdue:reply-to-maya"`, `"silence:afternoon"`,
  `"gap:lunch-window"`, `"followup:<id>"`). `outreach_log/{date}` records
  `{topic_key, time, draft}`; the next triage call receives the day's list so
  Klaus can compare semantically.
- **D-08:** The triage prompt receives **current time + window position**
  (`"now: 19:40 Asia/Jerusalem, tick 39 of ~42, last tick at 20:40"`) so Klaus
  knows when EOD is approaching and can naturally do EOD check-ins.
- **D-09:** **Daily reset** — `outreach_log` keyed by date; each new day is a
  fresh slate. Cross-day continuity comes through `journal_digest` (Phase 17 D-14),
  not the outreach log.
- **D-10:** **Log on success only** — only write to `outreach_log/{date}` after
  the Telegram send succeeds. Mirrors `proactive_alerts._mark_processed(alert_sent=True)`.
- **D-11:** **Layer 0 gate** — if `gather_situation()` produces no salient
  signals (no overdue tasks, no due follow-ups, no calendar gap/overload, plus
  no recent outreach to consider), skip the tick-brain call entirely. This is
  the mechanism behind SC-3 ("quiet situation → silent + near-zero cost") and
  the primary cost control.

### Follow-up behavior

- **D-12:** `schedule_followup(when, note)`'s `when` accepts **ISO 8601
  preferred, natural-language accepted as fallback**. The handler tries
  `datetime.fromisoformat()` first; on parse failure, falls through to a
  `dateutil.parser.parse()` (or `dateparser`) call. Stored as ISO-8601 UTC.
- **D-13:** **Hybrid fire** on due follow-ups: every tick checks
  `FollowupStore` for entries with `due_at <= now AND status != 'done'`. Each
  due follow-up triggers a **dedicated Layer-2 compose** (skips tick-brain —
  the user/Klaus already decided this matters). Klaus polishes the wording to
  the current moment; he may also **defer** if the situation's wrong now.
- **D-14:** **Defer mechanism** — Layer-2's structured output for a follow-up
  may return `{"action": "defer"}`. The handler sets `due_at += 1h` and
  increments `defer_count`. After `defer_count >= 3`, force-fire on the next
  due tick (Klaus can't punt forever).
- **D-15:** **Three direct tools** (all 5 registration sites each):
  - `schedule_followup(when: str, note: str) -> {id, due_at}` — schedules a check-back
  - `list_followups() -> [{id, due_at, note, defer_count}]` — returns pending follow-ups (status != 'done')
  - `cancel_followup(id: str) -> {ok: bool}` — marks a follow-up cancelled (status = 'cancelled')

  This stretches AUTO-05's letter ("schedule_followup direct tool") — listing
  and cancellation aren't named in the requirement — but the requirement's
  intent is "Klaus manages his own check-backs," which needs all three.

### Escalation & compose

- **D-16:** Layer 2 sees: **situation_snapshot + tick-brain draft + journal_digest
  + self_state** (`current_focus`, `mood`). Not full SELF.md text — the
  smart_system prompt machinery (Phase 16 D-04 / D-03) already includes
  SELF.md when the Layer-2 call goes through `_run_smart_loop`.
- **D-17:** **No second veto.** Tick-brain is the gate; if it escalated, Layer 2
  ships. Cleaner mental model: judgment happens once. The follow-up
  polish-or-defer path (D-13/D-14) is the only documented exception, and that's
  a *separate* compose path (no tick-brain in front of it to begin with).
- **D-18:** Klaus's proactive messages **inject into conversation history** —
  `send_and_inject(bot, msg, inject_into_conversation=True)`. The user's reply
  has the natural context: Klaus's outreach is the previous assistant turn.
  Diverges from `proactive_alerts` (which uses `False`) — the rationale is
  that autonomous outreach is conversational by intent.
- **D-19:** On Layer-2 failure (LLM error or unparseable output even after the
  Gemini → Claude-Haiku fallback chain), **fall back to tick-brain's `draft`
  text** and send it as-is. The message ships, less polished but in the right
  voice. `outreach_log` records as normal. Mirrors Phase 17 D-13 (write the
  minimal entry rather than skipping).
- **D-20:** **Layer 2 runs the full smart_agent tool-loop**, not a one-shot
  generation. Mechanism: feed `situation_snapshot + tick-brain draft` as a
  synthetic user message into the existing `_run_smart_loop`
  (`core/main.py:241`) with `prompts/autonomous.md` as the system prompt.
  SELF.md + self_state + journal_digest all inject normally via the per-message
  render step. Tool iterations are bounded by `MAX_TOOL_ITERATIONS = 8`
  (`core/main.py:43`). Klaus can fetch extra detail mid-compose (recall, get_self_status,
  calendar lookups) but most ticks won't need to.

### Judgment eval harness

- **D-21:** **Fixtures captured from live ticks**, not hand-written or synthetic.
  Phase 18 ships with **~5 hand-written seed fixtures** so `eval_tick_brain.py`
  has something to run on day 1. Every live tick logs its `situation_snapshot`
  to Firestore (`tick_logs/{date}/{tick_time}`) — over a week of use, ~25 are
  retroactively labeled (a small CLI or hand-edit of JSON files) to grow the
  set to AUTO-08's 20-30 target.
- **D-22:** `scripts/eval_tick_brain.py` prints **overall precision/recall/F1**
  for `should_speak` **plus a per-trigger-type breakdown table** (overdue, gap,
  silence, followup). Tiny extra implementation cost; right diagnostic for
  tuning the triage prompt.

### Claude's Discretion

- Exact Firestore schemas: `outreach_log/{date}` doc shape, `followups`
  collection doc shape (`defer_count`, status enum vs `done` bool), `tick_logs/{date}/{tick_time}`
  TTL.
- `topic_key` length cap / validation regex.
- Eval fixture JSON schema details (single file with array vs file-per-fixture).
- `prompts/autonomous_triage.md` and `prompts/autonomous.md` exact wording —
  Klaus's persona (informed by `docs/AGENT.md`), wide-latitude framing per
  AUTO-07, structured JSON output enforcement.
- Layer 2 model fallback chain — use the established
  `SMART_AGENT_*` → `SMART_AGENT_FALLBACK_*` pattern from `core/main.py:260–291`
  and Phase 17 D-13.
- INFRA-01: documenting the 2 new crons (reflect + autonomous-tick),
  the Groq secret, and the Five Fingers job-id quirk in `docs/DEPLOYMENT.md`.
- Whether `list_followups` returns also cancelled ones (probably not — only
  pending) and whether `cancel_followup` is idempotent (it should be).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` §"Autonomous Engine (Phase 18)" — AUTO-01 through AUTO-09 (acceptance criteria)
- `.planning/REQUIREMENTS.md` §"Infrastructure & Docs" — INFRA-01 (DEPLOYMENT.md update)
- `.planning/ROADMAP.md` §"Phase 18 — The Autonomous Engine (Capstone)" — key files + 5 success criteria

### Architecture & Persona
- `docs/TECHNICAL_PLAN.md` — LLM-per-purpose model map (informs Layer 1 vs Layer 2 model selection)
- `docs/AGENT.md` — Klaus persona and behavioral directives (informs both `prompts/autonomous_triage.md` and `prompts/autonomous.md` tone)
- `docs/USER.md` — Amit's routines and hardcoded scheduling rules (informs what counts as "actionable" in the situation snapshot)
- `docs/SELF.md` — capability manifest (auto-regenerated by CI; will pick up new tools and `/cron/autonomous-tick` automatically per Phase 16 D-01)

### Prior Phase Context (decisions carried forward)
- `.planning/phases/16-self-model-state-awareness/16-CONTEXT.md` §decisions — D-03 (smart-only injection + stable-first ordering), D-04 (SelfStateStore bootstrap pattern), D-05 (blank-field omission), D-07 (direct-tool registration pattern at 5 sites)
- `.planning/phases/17-reflection-journal/17-CONTEXT.md` §decisions — D-13 (LLM-fail minimal-fallback pattern reused in D-19), D-14/D-15 (journal_digest injection + smart-only ordering — Layer 2 inherits this), D-08 (extending existing tool with new param — analog for tick-brain's new `topic_key` output field)
- `.planning/phases/15-codebase-self-knowledge/15-CONTEXT.md` — direct-tool registration pattern (5 sites in `core/tools.py`)

### Code Integration Points
- `core/tick_brain.py:30` (`_TICK_SYSTEM_PROMPT`) and `core/tick_brain.py:101` (`TickBrain.think()`) — existing interface; Phase 18 extends the JSON output schema with `topic_key` (D-07). The `_parse_response` static method (`:158`) must be updated to accept and pass through `topic_key`.
- `core/heartbeat.py:679–716` (`_run_tick_brain_pass`) — reference for how tick-brain is invoked over a structured prompt.
- `core/proactive_alerts.py:91–140` (`run_proactive_alerts`) — full cron+detect+compose+send pattern; `_already_sent` (`:147–155`) is the dedup-gate template for outreach_log.
- `core/proactive_alerts.py:158–168` (`_mark_processed`) — Firestore dedup-write template.
- `core/reflection.py:123–193` (`_gather_day`) — best-effort per-source isolation pattern (each gather step in its own try/except, failures logged and omitted, never raise) — Layer 0's `gather_situation()` follows this exactly.
- `core/reflection.py:252–268` (`_minimal_fallback_entry`) — fallback-to-minimal pattern for D-19.
- `core/main.py:43` (`MAX_TOOL_ITERATIONS = 8`) — bounds Layer 2's tool-loop iterations.
- `core/main.py:205–257` — per-message prompt render step (SELF.md + self_state + journal_digest injection happens here; Layer 2 inherits this when invoked through `_run_smart_loop`).
- `core/main.py:241` (`AgentOrchestrator._run_smart_loop`) — Layer 2 enters here (D-20).
- `core/main.py:260–291` — inline brain → Haiku fallback shape; Layer 2 inherits this through `_run_smart_loop`.
- `core/tools.py:39` (`SMART_AGENT_DIRECT_TOOLS` frozenset) — `schedule_followup`, `list_followups`, `cancel_followup` register here.
- `core/tools.py:45+` (`TOOL_SCHEMAS`) — 3 new schemas appended.
- `core/tools.py:600–603` (`WORKER_TOOL_SCHEMAS`) — all 3 new tools excluded from worker.
- `core/tools.py:995+` (`_HANDLERS` dict) — 3 new handler lambdas.
- `core/scheduled_message.py:22` (`send_and_inject`) — `inject_into_conversation=True` for D-18.
- `interfaces/web_server.py:227` (`_verify_cron_request`) — OIDC auth (copy for `/cron/autonomous-tick`).
- `interfaces/web_server.py:273–279` (`_log_cron_run`) — liveness ledger (job-id `"autonomous-tick"`).
- `interfaces/web_server.py:310–331` (`cron_proactive_alerts`) **and** `:334–356` (`cron_reflect`) — cron route templates; `cron_reflect` is the most recent and closest in shape.
- `memory/firestore_db.py` — `JournalStore` (Phase 17) is the closest existing analog for `FollowupStore` (date-keyed collection writes) and `OutreachLogStore` (date-keyed collection writes). `SelfStateStore` (`:601`) is the analog for any singleton state.
- `memory/firestore_db.py:519` (`LLMUsageStore.summary`) — Layer 0 cost-context gather (today's running cost is part of the situation snapshot if useful for cost-aware judgment — Claude's discretion).
- `memory/pinecone_db.py:96` (`recall`) — already accepts `kinds` param; Layer 2 tool-loop can recall journal memories via `kind="self"` (Phase 17 D-08).
- `prompts/smart_agent.md` — Phase 18 adds mentions of `schedule_followup` / `list_followups` / `cancel_followup` so Klaus knows he can manage his own check-backs mid-chat.
- `prompts/proactive_alert.md` — tone/structure reference for `prompts/autonomous.md`.
- `prompts/reflection.md` — first-person voice reference (D-03's mixed-register echoes this).
- `docs/DEPLOYMENT.md` — INFRA-01 update target (document all 9 Cloud Scheduler jobs including the 2 new ones, the Groq secret, and the Five Fingers job-id-collision quirk noted in STATE.md).
- `.env.example` — no new env vars required (TICK_BRAIN_* already in from Phase 14, SMART_AGENT_FALLBACK_* already in from Phase 17).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TickBrain` (`core/tick_brain.py`) — already returns `{should_act, reason, draft}` with safe-mode fallback. Extend the JSON contract to include `topic_key` (D-07).
- `_run_tick_brain_pass` (`core/heartbeat.py:679`) — reference for "build a prompt, call `.think()`, interpret result." `gather_situation()` + `run_autonomous_tick()` follow this shape.
- `_gather_day` (`core/reflection.py:123`) — exact template for `gather_situation()` (best-effort per source, each in its own try/except, never raise).
- `JournalStore` and `SelfStateStore` (Phase 17/16) — already give Layer 2 the journal_digest and self_state context for free via the existing per-message render step (Phase 17 D-14, Phase 16 D-04).
- `_run_smart_loop` (`core/main.py:241`) — Layer 2 calls this with a synthetic user message; the prompt machinery handles SELF.md/self_state/journal_digest injection automatically.
- `send_and_inject` (`core/scheduled_message.py:22`) — Telegram send + history append; flip `inject_into_conversation=True` (D-18).
- `_verify_cron_request` / `_log_cron_run` (`interfaces/web_server.py`) — OIDC + ledger; copy directly into the new `/cron/autonomous-tick` route.
- `_already_sent` / `_mark_processed` (`core/proactive_alerts.py`) — dedup-gate pattern for `outreach_log`.

### Established Patterns
- **3-tool direct-registration** (5 sites each in `core/tools.py` per Phase 15 / 16): `TOOL_SCHEMAS`, `SMART_AGENT_DIRECT_TOOLS`, `WORKER_TOOL_SCHEMAS` exclusion, `_HANDLERS`, `_handle_<name>()` function. With 3 new tools (`schedule_followup`, `list_followups`, `cancel_followup`), that's **15 edit points** in `core/tools.py` — bulk but mechanical.
- **Store pattern**: `__init__(project_id, database)` → `_make_firestore_client` → `.get()` / `.set()` / collection writes; never raise (return `{}`, `None`, or empty list on Firestore error). `FollowupStore` and `OutreachLogStore` follow this.
- **Cron route** (`/cron/<name>`): `await _verify_cron_request(request)` → run logic in `try` → `_log_cron_run(job_id, ok=True)` in `finally`, `ok=False` on exception. Always returns `JSONResponse({"ok": True})`.
- **Two-step LLM fallback**: primary backend → secondary backend on `LLMError` or parse failure. Layer 1 already has this (Groq → Gemini in `tick_brain.py`); Layer 2 inherits the Gemini → Claude-Haiku fallback through `_run_smart_loop` (which sits behind `core/main.py:260–291`).
- **Cost metering**: every `LLMClient.chat()` call gets a `purpose=` param (`"tick_autonomous"`, `"autonomous_compose"`, `"autonomous_compose_fallback"`); `LLMUsageStore` records automatically (Phase 14).

### Integration Points
- Cloud Scheduler — **2 new jobs** to create via documented `gcloud` commands in DEPLOYMENT.md (consistent with Phase 17 D-11): `autonomous-tick` (`*/20 7-21 * * *` Jerusalem) and the existing `reflect` job already created in Phase 17. INFRA-01 documents all 9.
- `core/self_manifest.py` (Phase 16) — picks up the 3 new tools + new cron route + new prompts automatically on next CI deploy; `docs/SELF.md` regenerates correctly.
- `prompts/smart_agent.md` — small addition: tell Klaus he can `schedule_followup` / `list_followups` / `cancel_followup` and that the autonomous tick may speak proactively (so Klaus's chat persona expects to share the channel with proactive sends).
- `core/heartbeat.py` — `_CRON_MAX_STALENESS_HOURS` gains an entry `"autonomous-tick"` (≤ ~1h staleness threshold, mirrors the Phase 17 reflect entry). Heartbeat stale-cron check flags if autonomous ticks stop firing.

</code_context>

<specifics>
## Specific Ideas

- **The headline philosophy of this phase** is *trust Klaus's judgment, don't
  install governors.* No cadence cap (D-02), no hard `hours_since_contact`
  floor (D-05), informative-not-blocking repeat-suppression (D-06), no second
  veto (D-17). Cost discipline lives in Layer 0's gate (D-11), not in throttles
  downstream.
- **Triage with self-state** (D-04) is what makes Phase 18 the capstone of the
  Consciousness & Autonomy milestone — tick-brain reasons about a situation
  with Klaus's evolving self (journal entries + current_focus + mood), not over
  raw signals alone.
- **The follow-up tools are a small CRUD** (D-15) — `schedule_followup` per
  the letter of AUTO-05, `list_followups` and `cancel_followup` per the
  spirit. Worth flagging during the requirements-coverage check that these
  three tools collectively satisfy AUTO-05.
- **Layer 2 is a synthetic chat turn** (D-20) — feeding `situation_snapshot +
  draft` into `_run_smart_loop` reuses every persona/state injection the chat
  path already has. This is the elegant payoff for the Phase 16/17
  infrastructure: Phase 18 didn't need new injection machinery.
- **Eval is bootstrapped from real ticks** (D-21) — the Phase 18 launch
  doesn't depend on having 25 perfect fixtures. Ship with ~5 seeds, label
  ~20 retroactively over a week, the eval grows with real-world data.

</specifics>

<deferred>
## Deferred Ideas

- **Per-trigger inject-into-conversation logic** — considered (inject only for
  triggers where a reply is expected), rejected in favor of D-18 (always inject).
  Revisit if the conversation history becomes cluttered.
- **Layer 2 second veto** — considered (Layer 2 can decline based on
  self_state), rejected in favor of D-17 (no second veto, tick-brain is the gate).
  Could revisit if tick-brain proves over-aggressive in the eval.
- **Layer 2 deferral for non-follow-up sends** — defer-to-next-tick was
  considered for general outreach; rejected in favor of "fire or don't, no
  half-state." Only follow-ups defer (D-14).
- **Cancel-via-natural-language** — out of scope. Klaus may use
  `cancel_followup(id)` programmatically when the user says "forget that
  reminder"; no extra NL-cancel pipeline.
- **Cost-aware judgment** — passing today's running cost to the triage prompt
  so Klaus can self-throttle on expensive days. The cost data is already
  in `LLMUsageStore`; whether to surface it to the triage is Claude's discretion
  during planning.
- **Tick-log retention** — `tick_logs/{date}/{tick_time}` could fill Firestore
  fast (≈42 docs/day × 365 = 15k/year). A retention TTL is Claude's discretion;
  not a Phase 18 requirement.
- **Web/Notion UI for managing followups** — out of scope; the 3 brain-direct
  tools cover the loop.

</deferred>

---

*Phase: 18-autonomous-engine*
*Context gathered: 2026-05-20*
