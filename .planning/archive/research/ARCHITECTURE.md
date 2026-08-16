# Architecture Research — v6.0 "Klaus Becomes an Agent"

**Domain:** Integration architecture for self-governance rework on an existing deployed
cloud-native personal agent (Klaus / Cloud Run / FastAPI / Firestore / Pinecone)
**Researched:** 2026-07-17
**Confidence:** HIGH — all findings verified against live source (file:line citations
throughout), not inferred from training data. This is a codebase-integration question,
not an ecosystem-discovery question, so Context7/WebSearch were not the right tool;
the two approved planning documents
(`~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` and its review
`~/.claude/plans/mellow-puzzling-nest.md`) were treated as primary sources and
cross-checked against the actual files they reference.

## Standard Architecture

### System Overview (current, pre-v6.0)

```
┌───────────────────────────────────────────────────────────────────────┐
│                         Entry points (FastAPI)                         │
│  interfaces/web_server.py                                              │
│   /webhook (Telegram)        /api/* (Hub, session-auth)                │
│   /cron/autonomous-tick      /trigger/nightly  /cron/nightly-backstop  │
│   /cron/morning-briefing-tick  /cron/heartbeat  /cron/*-sync           │
└───────────────┬───────────────────────────┬────────────────────────────┘
                │                            │
                ▼                            ▼
┌───────────────────────────┐   ┌─────────────────────────────────────┐
│  Chat path                │   │  Cron/proactive paths (siloed today) │
│  core/main.py               │   │  core/autonomous.py   (3-layer)     │
│  AgentOrchestrator            │   │  core/nightly_review.py (template)  │
│   .handle_message()           │   │  core/morning_briefing.py (template)│
│   .render_smart_system()      │   │  core/weekly_training_review.py     │
│   ._run_smart_loop()          │   │  core/heartbeat.py (ops watchdog)   │
│   ._run_worker_loop()         │   │                                     │
└───────────────┬────────────┘   └───────────────┬─────────────────────┘
                │  each cron re-implements its     │
                │  own gather + its own LLM call ──┘  (no shared assembler)
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│  memory/ store layer (Firestore + Pinecone)                            │
│  firestore_conversation.py (6h session windows, no per-msg ts)         │
│  firestore_db.py (30+ stores: Journal, SelfState, Followup, TickLog,   │
│    UserProfile, TrainingLog, Block, Benchmark, Task, Habit, ...)        │
│  pinecone_db.py (kind={"fact","chunk","chat","self"}, discretionary)   │
└───────────────────────────────────────────────────────────────────────┘
```

**Confirmed gap (root cause driving v6.0):** `core/autonomous.py` (the only cascade)
gathers 14 sources in `gather_situation()` but has NO standing-directives concept, no
conversation *content* (only a last-message timestamp via
`_gather_hours_since_contact`, autonomous.py:331-361), and no reconciled
"what actually happened" vs "what the weekly template says" view. `nightly_review.py`
and `morning_briefing.py` are template composers — one blocking gather function +
one direct `LLMClient(...).chat(...)` call each (nightly_review.py:223-269,
morning_briefing.py:471-528) — they do NOT go through `AgentOrchestrator` or the
3-layer cascade at all. This is the central integration problem v6.0 solves.

### Target System Overview (post-v6.0)

```
┌───────────────────────────────────────────────────────────────────────┐
│  Entry points — UNCHANGED externally (web_server.py routes same URLs)  │
└───────────────┬───────────────────────────┬────────────────────────────┘
                │ chat turn                  │ occasion="tick"|"nightly"|"morning"
                ▼                            ▼
┌───────────────────────────┐   ┌─────────────────────────────────────┐
│  core/main.py               │   │  core/autonomous.py                 │
│  AgentOrchestrator            │   │  run_autonomous_tick(bot, now,       │
│   handle_message()             │   │    occasion="tick")  ◄── NEW param  │
│    ├─ ambient auto-recall NEW  │   │   Layer 0: gather_situation()        │
│    ├─ session-tail prepend NEW │   │     +standing_directives NEW         │
│    ├─ render_smart_system()    │   │     +conversation_tail NEW           │
│    │   +{standing_directives}  │   │     +training_reality NEW            │
│    │    NEW placeholder        │   │     +location NEW                    │
│    └─ _run_smart_loop()        │   │   Layer 1: TickBrain.think()         │
│         (unchanged shape)      │   │     (occasion-aware triage prompt)   │
└───────────────┬───────────────┘   │   Layer 2: _compose_layer2()         │
                │                    │     (agentic, bounded tool budget)   │
                │                    └───────────────┬───────────────────────┘
                │                                    │ occasion dispatch
                │                    ┌───────────────┴────────────────────┐
                │                    ▼                                    ▼
                │        core/nightly_review.py            core/morning_briefing.py
                │        (state machine + gather KEPT;      (Garmin-detector KEPT;
                │         _compose_nightly → cascade call)   _compose_briefing → cascade)
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│  memory/ store layer — extended, not replaced                          │
│  firestore_db.py  + StandingDirectiveStore (NEW, FollowupStore pattern)│
│  firestore_conversation.py + get_recent_window() NEW, per-msg ts NEW   │
│  core/training_checkin.py + planned_sessions_for() NEW (pure fn)       │
└───────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | New/Modified in v6.0 |
|-----------|----------------|------------------------|
| `core/tick_brain.py` | Free triage (Groq) | MODIFIED — decoupled fallback env (A1) |
| `core/main.py::AgentOrchestrator` | Brain loop, prompt rendering, chat path | MODIFIED — brain model swap, `{standing_directives}` placeholder, ambient recall, session-tail prepend |
| `core/autonomous.py` | 3-layer cascade, now the ONE cascade for all proactive surfaces | MODIFIED — occasion param, new gather jobs, occasion-routed triage/compose |
| `core/nightly_review.py` | Nightly state machine + tomorrow-gather (kept), compose delegated to cascade | MODIFIED (compose swap only) |
| `core/morning_briefing.py` | Garmin-sync detector state machine (kept), compose delegated to cascade | MODIFIED (compose swap only) |
| `core/training_checkin.py` | Recovery concern, session-quality; gains reconciliation primitive | MODIFIED — `planned_sessions_for()` added (moved from nightly_review) |
| `core/reflection.py` | Nightly journal write; gains learning loop | MODIFIED — reads 24h window, proposes directives |
| `memory/firestore_db.py::StandingDirectiveStore` | Durable free-text directives | NEW — modeled on `FollowupStore` (firestore_db.py:1524-1698) |
| `memory/firestore_conversation.py` | Per-user history, session windows | MODIFIED — per-message `ts`, `get_recent_window()` |
| `core/tools.py` | Tool schemas + `_HANDLERS` dispatch | MODIFIED — 3 new directive tools, 1 new introspection tool, write-back hooks on calendar handlers |
| `core/heartbeat.py` | Hourly ops watchdog | MODIFIED — daily-spend tripwire, Groq token ledger |

## Integration Points (file:function specificity)

### 1. Brain migration (Phase 30.5) — must land first, everything else assumes it

- `core/main.py::AgentOrchestrator.__init__` (main.py:183-256) reads
  `SMART_AGENT_BACKEND/MODEL/API_KEY` from env — no code change needed here, only
  `.github/workflows/deploy.yml` env values flip (`anthropic`/`claude-sonnet-5`).
  Fallback becomes `gemini-3.5-flash` via `SMART_AGENT_FALLBACK_*`.
- `core/tick_brain.py` — currently its internal fallback client is built from
  `SMART_AGENT_*` (per the plan review, tick_brain.py:117-119). **Must decouple**
  to a new `TICK_BRAIN_FALLBACK_BACKEND/MODEL/API_KEY/BASE_URL` env set BEFORE the
  brain swap ships, or every Groq degradation lands ~43 calls/day on Sonnet pricing.
  This ordering constraint (decouple-before-swap) is the single highest-priority
  sequencing fact in the whole milestone.
- `core/llm_client.py::_AnthropicBackend` (llm_client.py:171-254) — needs a
  Sonnet-5 compatibility audit (no `temperature`/`top_p`/`top_k` non-defaults, no
  explicit `thinking:` block) and new `cache_control: {"type":"ephemeral"}` on the
  last system block, plus extraction of `cache_read_input_tokens` /
  `cache_creation_input_tokens` from the Anthropic response (today only
  `response.usage.input_tokens` is read, llm_client.py:245).
- `core/pricing.py::compute_cost` gains `cache_read=0, cache_write=0` params and a
  `claude-sonnet-5` price entry; `memory/firestore_db.py` LLMUsage record/summary
  gains the two counter fields (additive Firestore fields, no migration needed —
  Firestore is schemaless).
- `core/main.py::render_smart_system` (main.py:258-446) already orders stable
  content before volatile (`{today_date}`, `{current_time}` last) for Gemini
  caching — this ordering is REUSED unchanged for Anthropic's prefix cache; the
  new `{standing_directives}` placeholder (Phase 31) must be inserted **after**
  `{training_profile}` and **before** `{today_date}` to preserve that property
  (explicitly specified in the plan).
- `core/heartbeat.py` gains the daily-spend tripwire (sum yesterday's LLMUsage,
  compare to `KLAUS_DAILY_COST_ALERT` env, default $5) — this is the FIRST
  consumer of the new cache-token fields, so A3 (cache metering) must ship in the
  same phase as the tripwire, not after.

### 2. Standing directives (Phase 31) — new store + 3 injection sites

- NEW `memory/firestore_db.py::StandingDirectiveStore` — collection
  `standing_directives/{uuid4hex}`, modeled directly on `FollowupStore`
  (firestore_db.py:1524-1698: same `_make_firestore_client` pattern, same
  never-raise-on-read / re-raise-on-write discipline). Must use the existing
  `_READ_CACHE` prefix-invalidation helper (firestore_db.py:61-86,
  `_cache_get`/`_cache_set`/`_invalidate_prefix`) because this store is read on
  EVERY chat turn (`render_smart_system`) plus 43 ticks/day — uncached reads here
  would be the single highest-QPS Firestore path in the app.
- `core/tools.py` — add `set_standing_directive`, `list_standing_directives`,
  `cancel_standing_directive` to `TOOL_SCHEMAS` (list starting tools.py:88) and to
  `_HANDLERS` (dict starting tools.py:2827, pattern: `"schedule_followup":
  lambda args: _handle_schedule_followup(**args)` at tools.py:2852). Add the three
  names to `SMART_AGENT_DIRECT_TOOLS` (frozenset at tools.py:40-82) — directives
  must be brain-direct like `schedule_followup`, never worker-delegated, because
  capturing "lasting wishes" requires the smart brain's judgment, not the worker's
  mechanical execution.
- A shared `render_standing_directives_block()` helper (new, likely in
  `core/tools.py` next to `_block_stores()` at tools.py:2632, or in
  `firestore_db.py` next to the store) is the render-once-reuse point: it must be
  callable from THREE call sites without re-implementing the formatting:
  1. `core/main.py::render_smart_system` — new `.replace("{standing_directives}",
     ...)` line (mirrors the existing `{training_profile}` replace pattern at
     main.py:443)
  2. `core/autonomous.py::_build_triage_prompt` (autonomous.py:686-737) — new
     `_gather_standing_directives` job added to the `jobs` dict in
     `gather_situation` (autonomous.py:588-615), consumed in the snapshot dict
  3. `core/autonomous.py::_compose_layer2` / `_compose_followup_layer2`
     (autonomous.py:839-940) — same snapshot dict pattern already used for
     `training_evidence`/`recovery`/`habit_pending` parity between triage and compose
- **This is the "render once, reuse" answer**: the directives block is rendered
  ONE time per call site (not globally cached as text, since directive content
  changes), but the *store read* is cached via `_READ_CACHE` and the *formatting
  logic* lives in one shared function — avoiding the drift risk of three
  independent format strings.
- Interim (until Phase 33 unifies): also inject into
  `core/nightly_review.py::_gather_tomorrow` (nightly_review.py:165-216) and
  `core/morning_briefing.py::_gather_data` (morning_briefing.py:265-464) directly,
  since those crons don't go through the cascade yet in Phase 31.
- Prompts: `prompts/smart_agent.md` (capture rule), `prompts/autonomous_triage.md`
  (Step-0 veto ABOVE existing decision logic — this is a structural prompt change,
  not additive, since it must short-circuit every trigger below it).
- **Learning loop bug fix (B3, folded into this phase):** `core/reflection.py`
  (reflection.py:159, `conv_store.get(user_id)`) reads the ACTIVE 6h session
  window, which is empty at the 22:00/01:00 reflection time on most nights. The
  learning loop that proposes self-directives from the day's conversation MUST
  read a 24h window instead — this makes `get_recent_window()` (originally
  planned for Phase 32's `firestore_conversation.py`) a **Phase 31 dependency**,
  not a Phase 32 one. Sequencing note below expands on this.

### 3. Unified situation — ambient memory, conversation tail, training reality (Phase 32)

- **`get_recent_window(user_id, hours, max_messages)`** — NEW method on
  `memory/firestore_conversation.py::FirestoreConversationStore`, built over the
  existing `get_full()` method (firestore_conversation.py:146-166) which already
  ignores the 6h timeout and returns the whole capped array. `get_recent_window`
  adds an `hours` cutoff filtered against a NEW per-message `ts` field. That `ts`
  field must be stamped in `_txn_append` (firestore_conversation.py:33-67,
  specifically the `messages.append({"role": role, "content": content})` line at
  :54) — additive field, legacy messages without `ts` must be tolerated (treat as
  "no timestamp, keep or drop by array position" not a KeyError).
- **This one store method is a genuine shared dependency**: it's consumed by (a)
  the Phase 31 learning-loop fix in `core/reflection.py`, (b) the Phase 32
  ambient-recall session-tail prepend in `core/main.py::handle_message`, and (c)
  the Phase 32 `conversation_tail` gather job in `core/autonomous.py`. Building it
  once in Phase 31 (per the B3 amendment) and having all three later consumers
  import it avoids three divergent truncation/formatting implementations.
- **Ambient auto-recall** — new code path inside
  `core/main.py::AgentOrchestrator.handle_message` (main.py:448-523), BEFORE
  `_run_smart_loop` is called: embed the incoming message, query
  `memory/pinecone_db.py`'s existing query path (kind=`fact`, top-k≈5,
  score-thresholded), inject as a context block. Must be best-effort
  (timeout ~2-3s, empty block on failure/timeout — matches the existing
  gather-isolation pattern already used in `autonomous.py:227-230`'s per-source
  try/except discipline). This is a NEW cross-cutting concern in the chat path
  that has no cron equivalent — it's chat-only, unlike the other three additions.
- **`training_reality`** — reconciliation dict built from THREE existing sources:
  `core/autonomous.py::_gather_training_evidence` (autonomous.py:477-553, already
  exists), a NEW pure function `planned_sessions_for(date_iso)` moved out of
  `core/nightly_review.py::_planned_workouts_for` (nightly_review.py:130-162) INTO
  `core/training_checkin.py`, and `TrainingLogStore.get_range`. **Critical circular
  import constraint** (explicit in the plan and the quality gate): `nightly_review`
  must re-import `planned_sessions_for` from `training_checkin`, NOT the reverse —
  `core/autonomous.py` must never import `core/nightly_review.py` (autonomous.py
  already imports from `core/training_checkin.py` freely — e.g.
  `compute_recovery_concern` is imported by both `nightly_review.py:207` and
  `morning_briefing.py:336` from `core.training_checkin`, establishing
  `training_checkin.py` as the neutral shared module both cascade and legacy
  composers already depend on without cycling). This is WHY `planned_sessions_for`
  lands in `training_checkin.py` and not, say, a new module — it reuses an
  already-proven acyclic import direction: `autonomous.py` → `training_checkin.py`
  ← `nightly_review.py` / `morning_briefing.py` (both leaves import the shared
  neutral module; the shared module imports neither).
- New gather jobs added to the `jobs` dict in
  `core/autonomous.py::gather_situation` (autonomous.py:588-615, same
  `ThreadPoolExecutor` fan-out pattern as the 14 existing sources):
  `conversation_tail`, `training_reality`, `standing_directives` (if not already
  landed in Phase 31), `location`.
- **Cost-control invariant (from the plan review, non-negotiable):** every one of
  these new gathers must be **context-only** in
  `core/autonomous.py::_is_empty_signals` (autonomous.py:175-220) — i.e. their
  presence must NEVER flip `empty=False` on their own. This mirrors the existing
  treatment of `training_status`/`acwr` (explicitly excluded, autonomous.py:192-195)
  vs. the treatment of `meals_since_last_tick`/`hours_since_contact`/`habit_pending`/
  `recovery.flags` (explicitly triggers). Getting this wrong means "any chat in the
  last 24h" makes every one of the 43 daily ticks non-empty, defeating the Layer-0
  cost gate (D-11/SC-3) that is Klaus's entire free-first cost model.
- Token budget discipline: triage input is capped (24h/≤15 msgs/240 chars/~4.8K
  char block per the plan) because `core/tick_brain.py`'s Groq free tier has an
  ~8K-token-per-request admission ceiling — this is a hard external constraint,
  not a style choice, and needs a guard test asserting the maximal rendered
  triage prompt stays under budget.
- `location` derivation reads calendar events (multi-day/travel entries, via the
  existing `_get_calendar_tool()` singleton, autonomous.py:236-238) plus the new
  `StandingDirectiveStore` — consumed by the hardcoded-Tel-Aviv weather calls in
  `nightly_review.py:201` (`fetch_weather("Tel Aviv")`) and
  `morning_briefing.py:272` (same hardcode) — both need parameterizing once
  `location` exists.

### 4. Occasion cascade — nightly/morning as wake-ups (Phase 33)

- `core/autonomous.py::run_autonomous_tick(bot, now, occasion="tick")` (currently
  `run_autonomous_tick(bot, now=None)`, autonomous.py:1109-1258) gains an
  `occasion` parameter. Occasion presence bypasses the Layer-0 empty gate
  (`if situation.get("empty")` at autonomous.py:1145) — an occasion always gets a
  Layer-1 judgment even on a quiet day, because "should I say anything for tonight's
  wind-down" is itself the question, unlike a tick where "nothing happened" is a
  valid free exit.
- `core/nightly_review.py::_compose_nightly` (nightly_review.py:223-269, currently
  a direct `LLMClient(...).chat(...)` call) is REPLACED by a call into the cascade
  — but `nightly_target_date`, `was_sent`, `_ensure_reflection`,
  `_gather_tomorrow`, the structured snapshot, and `_plain_text_fallback` are
  explicitly KEPT (the plan is precise about this: state-machine idempotency and
  the deterministic fallback survive; only the LLM-call function is swapped for a
  cascade call). `run_nightly` (nightly_review.py:329-363) is the caller that
  needs the swap — it currently calls `_build_nightly` → `_compose_nightly`
  synchronously in an executor (nightly_review.py:313-327, 348-349).
- `core/morning_briefing.py::_compose_briefing` (morning_briefing.py:471-528,
  same direct-`LLMClient` pattern) gets the equivalent swap; the Garmin-sync
  detector state machine in `handle_tick` (morning_briefing.py:58-116) and the
  10:15 cutoff are explicitly KEPT.
- **Failure semantics differ per surface and must not be unified accidentally:**
  tick → LLM failure = silence (today's existing behavior, unchanged). Nightly →
  total cascade failure still falls through to the existing deterministic
  `_plain_text_fallback` (nightly_review.py:272-306) — "failure-skip ≠
  judgment-skip" is an explicit design invariant from the plan; a judgment-skip
  writes `status: skipped_by_judgment`, an infra failure still sends the
  plain-text fallback and writes `status: sent`. Morning failure → silent skip
  (no fallback text sent) per the plan's Phase 33 section.
- Rollout is flag-gated: `OCCASION_CASCADE` env var selects cascade vs. legacy
  composer inside `run_nightly`/`run_morning_briefing` for the observation window
  — **no Cloud Scheduler changes**, the cron endpoints in
  `interfaces/web_server.py` (`/trigger/nightly` at web_server.py:539,
  `/cron/nightly-backstop` at :567, `/cron/morning-briefing-tick` at :732,
  `/cron/autonomous-tick` at :592) keep their existing signatures and just pass
  the occasion tag through.
- NEW brain-direct `get_recent_decisions(days=2)` tool (C1 amendment) —
  `core/tools.py`: reads `TickLogStore` + `OutreachLogStore` (both already
  written every tick, `_write_tick_log` at autonomous.py:1083-1101 and the
  `OutreachLogStore.append` calls at autonomous.py:1237-1249) and surfaces recent
  verdicts + reasoning + topics. Add to `TOOL_SCHEMAS` + `_HANDLERS` +
  `SMART_AGENT_DIRECT_TOOLS` following the exact same three-site pattern as the
  Phase 31 directive tools.
- **Idempotency for proactive calendar writes (B2 amendment):** before an
  agentic Layer-2 compose creates a calendar event (directive-gated), check for
  an existing planned row for that date+slot — this dedup key becomes available
  once Phase 34's write-backs exist, which is why B2 is explicitly sequenced
  as "Phase 33/34" in the review, not purely 33.

### 5. Write-backs (Phase 34)

- `core/tools.py::_handle_create_calendar_event` (tools.py:1549-1568) already
  receives `is_workout` as a parameter. On success + `is_workout=True`, add a
  best-effort call to `TrainingLogStore.log_session(date, slot=<event_id>,
  session_type=<title>, planned=True, source="calendar")` — `log_session` already
  supports `planned=True` and `merge=True` per the plan (no new store; this reuses
  the existing `TrainingLogStore`, sibling pattern to `BlockStore`/`BenchmarkStore`
  via `_block_stores()` at tools.py:2632). The write-back must never fail the
  calendar create itself (wrap in try/except, log-and-continue — matches the
  gather-isolation discipline used everywhere else in this codebase).
- Symmetric hooks needed on `_handle_update_calendar_event`
  (tools.py:1583-1600, "move" → merge-write the new date, mark the old row
  `skipped_reason="moved"`) and `_handle_delete_calendar_event`
  (tools.py:1577-1580, remove/mark the planned row).
- `core/weekly_training_review.py` is repointed to read the shared
  `training_reality` window (from Phase 32) instead of its own
  split-vs-log guesswork — this is the phase where the weekly review's data
  layer catches up even if (per the E1 open decision) its own compose stays a
  legacy path rather than folding into the occasion cascade.

### 6. Evals, hardening, subtraction (Phase 35)

- Purely additive/subtractive — no new integration surface. Notable deletions
  with real coupling to check before removal: `core/proactive_alerts.py` (route
  in `interfaces/web_server.py:488-507` per the review — confirm dormant before
  deleting), `prompts/nightly_review.md`/`morning_briefing.md` (only after the
  `OCCASION_CASCADE` flag is confirmed stable and removed), TickTick residue.

## Architectural Patterns

### Pattern 1: Sentinel-on-failure gather isolation

**What:** Every `_gather_*` function in `core/autonomous.py` (14 of them,
autonomous.py:233-553) owns its own try/except and returns a typed sentinel
(`[]`, `0`, `""`, `{}`, `None`) on failure — never raises. `gather_situation`
fans them out via `ThreadPoolExecutor(max_workers=8)` and `fut.result()` is
therefore always safe.
**When to use:** Every new gather added in v6.0 (standing_directives,
conversation_tail, training_reality, location) MUST follow this exact shape —
it's the reason a single Firestore blip never masks the D-11 empty-signals gate.
**Trade-offs:** Verbose (14+ near-identical try/except blocks) but the isolation
guarantee is load-bearing for the cost-gating invariant.

### Pattern 2: Render-once via a shared formatter, cache via `_READ_CACHE`

**What:** `render_smart_system` (main.py:258-446) demonstrates the target
shape for `{standing_directives}`: a store read (cached via
`memory/firestore_db.py`'s `_READ_CACHE` / `_cache_get` / `_invalidate_prefix`,
firestore_db.py:61-86) feeds a formatting function whose OUTPUT differs per
call site's needs (main.py needs prose injected into a template string;
`autonomous.py::_build_triage_prompt` needs a JSON-embeddable snippet) but whose
INPUT (the directive list) is fetched once per request via the cache, not
per-render.
**When to use:** Any new context block consumed by more than one LLM surface
(directives, training_reality, conversation_tail all qualify in v6.0).
**Trade-offs:** Requires discipline to keep the store-read cached AND the
downstream formatting logic centralized — the plan explicitly calls out
"one helper, three call sites, no drift" for the existing `_format_now_block`
(autonomous.py:669-683) as the model to replicate.

### Pattern 3: Occasion as a cascade parameter, not a new pipeline

**What:** Rather than building a fourth (or fifth) proactive pipeline for
nightly/morning, `run_autonomous_tick` gains a keyword parameter that changes
gate behavior (skip empty-gate) and prompt selection (occasion guidance appended
at runtime) while reusing the identical Layer 0/1/2 machinery.
**When to use:** This is the core v6.0 architectural move — collapsing four
independent proactive code paths (tick, nightly, morning, [weekly — deferred])
into one judgment engine.
**Trade-offs:** The state-machine/idempotency logic in `nightly_review.py` and
`morning_briefing.py` (Firestore doc per day, `was_sent`, retry counters) is
KEPT as a thin wrapper around the cascade call, not deleted — those concerns
(dedup, cutoff windows, Garmin-sync detection) are orthogonal to "what should
Klaus say" and don't belong inside the cascade.

### Pattern 4: Mechanical invariants for obedience, judgment for everything else

**What:** The plan's three-layer guidance model — hard code invariants
(write-backs, D-10 outreach-log-only-after-send, cost gating, LLM timeouts) vs.
ambient memory (involuntary) vs. values/directives (judgment). Write-backs
(Phase 34) are explicitly the "survives model disobedience" mechanism — they
fire from the TOOL HANDLER (`_handle_create_calendar_event`), not from a prompt
instruction, precisely because the whole milestone exists to fix cases where
Klaus was told something and didn't durably act on it.
**When to use:** Anything that must be true regardless of model judgment quality
(a training log row existing) goes in code; anything that's a matter of taste
or timing (whether to mention it) stays in the prompt/judgment layer.

## Data Flow

### Where the directives block is rendered once and reused

```
StandingDirectiveStore.list_active()  ── cached via _READ_CACHE (10 min TTL,
      │                                     firestore_db.py:61-86)
      ▼
render_standing_directives_block()  ── ONE shared formatter (new helper)
      │
      ├──► core/main.py::render_smart_system()          [chat path, every turn]
      ├──► core/autonomous.py::_build_triage_prompt()    [Layer 1, every tick]
      ├──► core/autonomous.py::_compose_layer2()          [Layer 2, on speak]
      ├──► core/autonomous.py::_compose_followup_layer2() [Layer 2, follow-ups]
      └──► (interim, Phase 31 only) nightly_review._gather_tomorrow()
           and morning_briefing._gather_data() — retired once Phase 33 lands
```

The cache lives at the STORE layer (Firestore read), not at the text layer —
each call site still calls the formatter fresh (directive text is cheap to
format; the expensive part is the Firestore round-trip, which `_READ_CACHE`
already eliminates for repeat reads within 10 minutes).

### Where the situation assembler lives so chat + cascade + crons share it without circular imports

```
                 core/training_checkin.py   (NEUTRAL — imports nothing from
                       ▲        ▲             autonomous/nightly/morning)
                       │        │
     imports           │        │  imports
  ┌────────────────────┘        └───────────────────────┐
  │                                                       │
core/autonomous.py                          core/nightly_review.py
  gather_situation()                          _gather_tomorrow()
  (cascade — Layer 0)                         (legacy compose input,
  imports training_checkin.                    kept post-Phase-33)
  planned_sessions_for()                       imports training_checkin.
  + _gather_training_evidence                   planned_sessions_for()
    (already local)                             (re-imported, not owned)
```

`core/autonomous.py` must NEVER `import core.nightly_review` — this is stated
as a hard constraint in both the plan and the quality gate for this research.
The resolution is that the one piece of logic both sides need
(`planned_sessions_for`, originally `nightly_review._planned_workouts_for`)
moves to the already-neutral `core/training_checkin.py`, which both
`autonomous.py` and `nightly_review.py`/`morning_briefing.py` already import
from for `compute_recovery_concern` — so this is not a new dependency edge,
it's reusing a proven one. There is no single "situation assembler" MODULE in
this codebase (unlike a green-field design); the assembly happens inline in
`gather_situation()`'s `jobs` dict via the `ThreadPoolExecutor` fan-out
pattern, and the NEW gather jobs added for v6.0 follow that existing shape
rather than introducing a separate assembler abstraction.

### Ambient recall data flow (chat-only, no cron equivalent)

```
Telegram/Hub message ──► core/main.py::handle_message()
                              │
                              ├─ (NEW, best-effort, timeout-guarded)
                              │   embed(user_message) ──► pinecone_db query
                              │   kind="fact", top-k≈5, score-threshold
                              │   ──► "Things you remember" context block
                              │
                              ├─ (NEW) if session empty/fresh:
                              │   get_recent_window() ──► prepend tail
                              │
                              └─► render_smart_system() ──► _run_smart_loop()
```

## Suggested Build Order (dependency-respecting)

1. **Phase 0 — tick-brain model migration** (ALREADY SHIPPED pre-milestone,
   commit `b784a1d`, 2026-07-16). Listed here only because everything downstream
   assumes a working free tick-brain.

2. **Phase 30.5 — brain migration, in this internal order:**
   a. Decouple `TICK_BRAIN_FALLBACK_*` env from `SMART_AGENT_*` in
      `core/tick_brain.py` FIRST (A1) — must land before the brain model flips,
      or the first Groq blip after the flip silently bills Sonnet.
   b. Anthropic backend compatibility audit + cache-token extraction in
      `core/llm_client.py` (A3) — must land in the SAME phase as the cost
      tripwire, since the tripwire's numbers are wrong without it.
   c. `core/pricing.py` + LLMUsage cache-field additions.
   d. Flip `SMART_AGENT_*`/`SMART_AGENT_FALLBACK_*` env in deploy.yml.
   e. SELF.md compact-manifest pass (`core/self_manifest.py`) + light
      `smart_agent.md` de-prescription — cheap token wins that should land
      before Sonnet's per-token rate makes the duplication actively expensive.
   f. `core/heartbeat.py` daily-spend tripwire (depends on 30.5b).
   g. `UserProfileStore` TTL cache (independent, can land any time in 30.5/32).

3. **Phase 31 — Standing directives, in this internal order:**
   a. `StandingDirectiveStore` (new store, no dependencies).
   b. **`get_recent_window()` on `FirestoreConversationStore`** — per-message
      `ts` stamping in `_txn_append` + the window method. Sequenced HERE (not
      Phase 32) because the Phase-31 learning-loop fix (B3) needs it — this is
      the "get_recent_window before the reflection learning loop" dependency
      named in the quality gate. Phase 32's ambient-recall tail-prepend and
      `conversation_tail` gather job then simply REUSE this method rather than
      building it.
   c. Directive tools (`set_/list_/cancel_standing_directive`) in `core/tools.py`
      + `render_standing_directives_block()` shared helper.
   d. `{standing_directives}` placeholder in `render_smart_system` +
      `_build_triage_prompt`/`_compose_layer2` gather+injection in
      `core/autonomous.py`.
   e. Prompt changes: Step-0 veto in `autonomous_triage.md`, capture rule in
      `smart_agent.md`.
   f. Interim direct injection into `nightly_review._gather_tomorrow` /
      `morning_briefing._gather_data` (throwaway — removed in Phase 33).
   g. Reflection learning loop in `core/reflection.py` (depends on 31b) +
      reaction-pairing (C2) in `prompts/reflection.md`.
   h. Eval fixtures for vacation-directive suppression.

4. **Phase 32 — Unified situation (depends on 31b for the window primitive):**
   a. `planned_sessions_for()` moved to `core/training_checkin.py` (establishes
      the acyclic import path nightly/morning will keep needing).
   b. `training_reality` reconciliation builder in `core/autonomous.py`.
   c. Ambient auto-recall in `core/main.py::handle_message` (best-effort,
      timeout-guarded — independent of (a)/(b), can parallelize).
   d. `conversation_tail` gather job (reuses 31b's `get_recent_window`).
   e. Location awareness (reads calendar + standing directives — depends on 31).
   f. Context-only invariant audit across ALL new gathers in
      `_is_empty_signals` + Groq daily token ledger in `core/heartbeat.py` +
      triage-prompt shrink in `autonomous_triage.md` — this must happen BEFORE
      Phase 33 flips any occasion traffic through triage, or the empty-gate
      cost model breaks silently on day one of the new load.
   g. Memory hygiene: `forget_memory` tool.
   h. Token-budget guard test (asserts maximal rendered triage prompt fits the
      verified Groq per-request ceiling) — write this LAST in the phase, after
      all additions are in, so it measures the real worst case.

5. **Phase 33 — Occasion cascade (depends on 32f for cost safety):**
   a. `occasion` param on `run_autonomous_tick` + empty-gate bypass logic.
   b. `get_recent_decisions` introspection tool (C1) — can land any time in 33
      or slip to 35 per the plan's own flexibility note; cheap, no dependencies
      beyond the already-written `TickLogStore`/`OutreachLogStore`.
   c. **`OCCASION_CASCADE` flag wiring BEFORE touching the legacy composers** —
      `_compose_nightly`/`_compose_briefing` get a cascade-call branch gated by
      the flag while the old direct-`LLMClient` branch stays live. This is the
      "occasion flag before composer deletion" ordering named in the quality
      gate: never delete `_compose_nightly`/`_compose_briefing` in the same
      change that introduces the flag — the flag exists precisely so both paths
      run in parallel for the multi-day observation window.
   d. New `prompts/occasion_nightly.md` / `occasion_morning.md`.
   e. Agentic Layer-2 tool-budget loosening.
   f. Proactive-calendar idempotency check (B2) — needs Phase 34's planned-row
      dedup key to be fully correct, so land a conservative version here and
      revisit once 34 ships (explicitly sequenced as "33/34" in the review).
   g. Weekly-review fold-in decision (E1) — a DECISION checkpoint, not
      necessarily code; must be resolved before Phase 35 cleanup so the roadmap
      knows whether `weekly_training_review.py` gets a compose swap too.

6. **Phase 34 — Write-backs (depends on 33's occasion machinery existing for
   the idempotency check, but the write-back hooks themselves only depend on
   `core/tools.py` + `TrainingLogStore`, both already stable):**
   a. `_handle_create_calendar_event` write-back hook.
   b. Symmetric update/delete hooks.
   c. `smart_agent.md` `log_training` mandate strengthening.
   d. `core/weekly_training_review.py` repointed at `training_reality`.

7. **Phase 35 — Evals, hardening, subtraction (depends on everything above
   being stable enough to write fixtures against):**
   a. New eval fixtures (≥6).
   b. Only NOW: delete `_compose_nightly`/`_compose_briefing` legacy branches +
      `OCCASION_CASCADE` flag + `prompts/nightly_review.md`/`morning_briefing.md`
      — after the flag has been observed stable for the multi-day window from
      Phase 33.
   c. Dead-code sweep (`proactive_alerts.py`, worktree residue, TickTick
      residue) — verify each is truly unreferenced (e.g. confirm the GCP
      scheduler has no `proactive-alerts` job) before deleting.
   d. Worker-layer measurement + retirement decision note (no deletion in v6.0).
   e. Docs/invariants update in `CLAUDE.md` — add "standing directives are
      injected into every reasoning path" and "triage input must stay under the
      Groq per-request budget" as new invariants (§6 pattern already
      established in CLAUDE.md).

**Ordering rules this build order encodes, stated explicitly (matches the
quality gate):**
- Brain migration (30.5) before any prompt-philosophy rewrite (31-33), because
  the de-prescription pass assumes Sonnet's more literal instruction-following.
- Tick-brain fallback decoupling (A1) before the brain model flip, within 30.5.
- `get_recent_window()` before the reflection learning loop (31b before 31g) —
  named explicitly in the quality gate.
- Cost-tripwire/cache-metering (30.5) before the daily-spend alert has any
  truthful numbers to alert on.
- Context-only invariant + Groq ledger (32f) before Phase 33 routes nightly/
  morning traffic through triage — protects the free-tier budget from the
  volume increase.
- `OCCASION_CASCADE` flag introduction (33) strictly before legacy composer
  deletion (35) — never collapsed into one change, per the quality gate.
- `core/autonomous.py` never imports `core/nightly_review.py` — enforced by
  routing the shared `planned_sessions_for()` through the neutral
  `core/training_checkin.py` module instead (Phase 32a), which both sides
  already import from safely.

## Anti-Patterns to Avoid

### Anti-Pattern 1: A fifth independent proactive pipeline

**What people might do:** Build "occasion" support as a brand-new module
(`core/occasion_engine.py`) that wraps `run_autonomous_tick` from the outside.
**Why it's wrong:** Duplicates the gather/triage/compose machinery a third
time; the whole point of v6.0 is COLLAPSING four pipelines into one.
**Do this instead:** Add `occasion` as a parameter to the existing
`run_autonomous_tick`, exactly as the plan specifies — the state-machine
wrappers (`nightly_review.py`, `morning_briefing.py`) stay thin callers.

### Anti-Pattern 2: Directive/context blocks re-fetched and re-formatted per call site

**What people might do:** Each of the 5 call sites (chat, triage, compose,
follow-up compose, interim cron gathers) writes its own Firestore query +
its own string formatting for standing directives.
**Why it's wrong:** Five independent formatters WILL drift (different field
names surfaced, different truncation, different empty-state handling) — this
codebase has already hit this exact failure mode once (the plan cites
`_format_now_block` at autonomous.py:669-683 being introduced specifically to
fix a "one helper, three call sites, no drift" bug).
**Do this instead:** One shared formatter function, called from every site;
cache the underlying store read via the existing `_READ_CACHE` mechanism.

### Anti-Pattern 3: New gathers treated as triggers by default

**What people might do:** Add `conversation_tail`/`training_reality`/
`standing_directives`/`location` to `gather_situation()` and forget to add the
corresponding "this must not flip `_is_empty_signals`" exclusion.
**Why it's wrong:** `_is_empty_signals` (autonomous.py:175-220) is the entire
cost-control gate (D-11/SC-3) — any new field that becomes truthy on a normal
day (e.g. "there was some chat in the last 24h" is true almost every day) makes
every one of the 43 daily ticks non-empty, spending Groq (and, on Groq
degradation, Sonnet) budget on ticks that used to be free no-ops.
**Do this instead:** Explicitly whitelist which fields are triggers (mirroring
the existing comment block at autonomous.py:192-220 that documents WHY
`training_status`/`acwr` are context-only vs. why `meals_since_last_tick`/
`recovery.flags` are triggers) — treat every new v6.0 field as context-only
unless there's a specific, documented reason it should wake the free tier.

### Anti-Pattern 4: Deleting the legacy composer in the same change as the flag

**What people might do:** Ship `OCCASION_CASCADE=1` and delete
`_compose_nightly`/`_compose_briefing` in one PR to reduce churn.
**Why it's wrong:** Removes the ability to roll back or A/B-compare during the
observation window the plan explicitly calls for ("watch 3-4 days of TickLog +
nightly docs, then delete"); also removes the deterministic
`_plain_text_fallback` safety net before it's been proven the cascade path
handles the failure-skip-vs-judgment-skip distinction correctly in production.
**Do this instead:** Two separate phases/PRs — flag introduction with both
paths live (Phase 33), then deletion after observation (Phase 35).

### Anti-Pattern 5: Mechanical write-backs as prompt instructions instead of code

**What people might do:** Add "remember to log the training session" as
stronger prompt language in `smart_agent.md` and call the write-back problem
solved.
**Why it's wrong:** This is literally the failure mode v6.0 exists to fix —
Amit told Klaus things repeatedly and Klaus didn't durably act (per the
milestone's own root-cause analysis: "Told 'upper body TODAY instead of
tomorrow,' Klaus created the calendar event but days later still asked when to
schedule that slot"). A prompt instruction is exactly as reliable as the
model's judgment on that turn — no better than what already existed.
**Do this instead:** The write-back fires from the TOOL HANDLER itself
(`_handle_create_calendar_event`) on every successful `is_workout=True` call,
unconditionally — "survives model disobedience" per the plan's own framing.

## Integration Points — Summary Table

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `core/main.py` ↔ `core/autonomous.py` | `_get_orchestrator()` singleton (autonomous.py:748-770), direct function calls | Existing pattern reused for occasion routing; `_run_smart_loop` signature (main.py:529) is the shared Layer-2 entry point for BOTH chat and cascade |
| `core/autonomous.py` ↔ `core/training_checkin.py` | Direct import (`planned_sessions_for`, `compute_recovery_concern`) | `training_checkin.py` is the deliberate neutral module preventing the autonomous↔nightly_review cycle |
| `core/autonomous.py` ↔ `core/nightly_review.py` / `core/morning_briefing.py` | Occasion parameter dispatch (Phase 33); NEVER a direct import of nightly_review from autonomous.py | Hard constraint, verified in both plan docs and this research's quality gate |
| `core/tools.py` ↔ `memory/firestore_db.py` | New `StandingDirectiveStore`, existing `TrainingLogStore`/`TickLogStore`/`OutreachLogStore` | Handler dispatch via `_HANDLERS` dict (tools.py:2827+), same pattern for every new tool |
| `core/main.py` ↔ `memory/firestore_conversation.py` | New `get_recent_window()`, new per-message `ts` | Consumed by 3 different call sites across 2 phases (31, 32) |
| `core/main.py` ↔ `memory/pinecone_db.py` | NEW ambient auto-recall query (chat path only) | Best-effort, timeout-guarded, no cron equivalent |
| `core/heartbeat.py` ↔ `memory/firestore_db.py` (LLMUsage) | NEW daily-spend tripwire query + Groq token ledger | Depends on Phase 30.5's cache-token metering being truthful first |

### External Services (unchanged by v6.0)

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Anthropic (new brain) | `core/llm_client.py::_AnthropicBackend` | Needs Sonnet-5 param audit + prompt caching (Phase 30.5) |
| Groq (tick-brain) | `core/tick_brain.py`, OpenAI-compat | Free-tier token ceiling is now the binding constraint on Phase 32 additions |
| Firestore | `memory/firestore_db.py` store-per-collection pattern | `StandingDirectiveStore` is purely additive, no schema migration |
| Pinecone | `memory/pinecone_db.py` | Ambient recall is a NEW consumer of the existing query path, no new kind needed (reuses `kind="fact"`) |

## Sources

- `.planning/PROJECT.md` — milestone context, phase target features (HIGH confidence, primary source)
- `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` — approved v6.0 plan (HIGH confidence, primary source, cross-checked against code)
- `~/.claude/plans/mellow-puzzling-nest.md` — approved review/amendments (HIGH confidence, primary source, cross-checked against code)
- `core/autonomous.py` (read in full, 1259 lines) — verified line numbers for gather pattern, cascade, empty-gate
- `core/main.py` (read in full, 992 lines) — verified `AgentOrchestrator`, `render_smart_system`, `_run_smart_loop`
- `core/nightly_review.py` (read in full, 395 lines) — verified state machine, compose function, gather
- `core/morning_briefing.py` (read in full, 608 lines) — verified Garmin-detector state machine, compose function
- `memory/firestore_db.py` (targeted reads: `FollowupStore` 1524-1698+, `_READ_CACHE` 61-86, `_block_stores` region) — verified store pattern to replicate for `StandingDirectiveStore`
- `memory/firestore_conversation.py` (read in full, 230 lines) — verified session-window mechanics, `get_full`, `_txn_append`
- `core/tools.py` (targeted reads: `SMART_AGENT_DIRECT_TOOLS` 40-82, calendar handlers 1549-1600, `_block_stores` 2632+, `_HANDLERS`/dispatch region) — verified tool registration pattern
- `core/reflection.py`, `core/training_checkin.py` (function inventories via grep) — verified `conv_store.get()` call site for the B3 bug, confirmed `training_checkin.py` has no autonomous/nightly imports
- `interfaces/web_server.py` (targeted grep) — verified cron route names unchanged by v6.0

---
*Architecture research for: Klaus v6.0 "Klaus Becomes an Agent" — self-governance rework integration*
*Researched: 2026-07-17*
