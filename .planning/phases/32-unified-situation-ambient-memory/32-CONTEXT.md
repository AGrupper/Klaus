# Phase 32: Unified Situation (Ambient Memory) - Context

**Gathered:** 2026-07-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Klaus perceives his full situation on EVERY reasoning path — relevant Pinecone
memories, conversation continuity, a reconciled `training_reality` window, and a
derived `current_location` — all delivered as **context-only** signals that never
flip an otherwise-empty tick to non-empty. The free-tier cost gate
(`_is_empty_signals` in `core/autonomous.py`) is Klaus's entire cost model and
must remain untouched by all four new gathers. A local Groq daily-token ledger
(Firestore counter) guards the 200K TPD cap via heartbeat, and a token-budget
guard test proves the maximal rendered triage prompt + `max_tokens` fits Groq's
verified per-request ceiling. Requirements MEM-01..07. Occasion cascade (Phase 33)
and write-backs (Phase 34) are out of scope — this phase only READS and assembles
the unified situation; it does not route occasions through the cascade or mutate
the training source of truth.

</domain>

<decisions>
## Implementation Decisions

The mechanics are already locked in REQUIREMENTS (k≈5 score-thresholded recency-
weighted recall; triage tail 24h/≤15 msgs/hard char cap; paid compose tail
48h/≤40 msgs; today-3d..tomorrow reconciliation window; context-only invariant;
budget-guard test). These decisions cover the JUDGMENT/BEHAVIOR gray areas.

### training_reality reconciliation (MEM-04)
- **D-01: Evidence wins.** When the 4 sources disagree about whether/when a
  session happened, precedence is **Garmin/Hevy actual-activity evidence → your
  own `training_log` self-report → calendar/planned-split (intent only)**. A
  logged run satisfies the day's planned slot even at a different time of day.
  Rationale: matches how Amit actually trains — the sensor data is ground truth
  for "did it happen."
- **D-02: Same-day + type matching.** A real activity satisfies a planned slot
  when it is the **right modality (run/lift) on the planned day** — do NOT demand
  the pace/distance/duration match the prescription. A run is a run: mark the slot
  done, coach on quality separately. A completed-but-imperfect session is "done"
  and **never re-asked about** (the SC-4 invariant). Quality/intensity commentary
  is a separate concern from slot-satisfaction.
- The reconciled window is **context-only**: it must NOT be added to
  `_is_empty_signals` (mirrors the existing training_status/acwr/standing_directives
  precedent — a single reconciliation fact must never wake the free tier).

### Recall, forget & continuity (MEM-01/02/03)
- **D-03: Auto-block AND manual `recall` coexist.** The auto-injected "Things you
  remember" block gives ambient background every chat turn (best-effort, short
  timeout, k≈5 on the live message); the manual `recall` tool stays for deep,
  targeted mid-conversation lookups on a topic not in the current message. Two
  different needs — keep both. `recall` prompt guidance stays as-is.
- **D-04: Contradicted memories are flagged in the nightly, Amit confirms delete.**
  Reflection surfaces a memory contradicted by newer facts as a woven nightly note
  ("I still have you down as marathon-training — drop that?"); Klaus deletes ONLY
  on Amit's confirmation. This honors "deliberate-only forgetting, no auto-decay"
  (MEM-03) — the flag is a suggestion, Amit pulls the trigger. `forget_memory`
  (Pinecone delete by id) is the deliberate path, callable by Amit ("forget that")
  and executed on confirmation of a nightly flag. Reflection never auto-deletes.
- **D-05: Continuity = rehydrate the tail as history + a time-gap boundary marker.**
  After a 6h+ idle gap into a fresh/empty session, prepend the recent conversation
  tail as real message history (natural continuity — no amnesia), but insert a
  synthetic boundary marker at the seam (e.g. "[~8h elapsed since the messages
  above — a new session begins here]") so the brain reads it as memory of a prior
  thread and does NOT re-act on the last stale message as if it were just said.
  This is the both-worlds answer (Amit: "whatever you think is better regardless
  of the work"). Best-effort; a failed tail read yields no block, never blocks the
  turn.

### current_location derivation (MEM-07)
- **D-06: Default home silently; ASK when ambiguous.** With no active travel
  signal, assume Tel Aviv and say nothing (the 99% case; the bug being fixed is
  Paris-getting-TLV-weather, not TLV-getting-uncertainty). Travel overrides only
  when a calendar travel event or a standing directive positively places Amit
  elsewhere. When signals **conflict or a trip window is unclear**, Klaus asks
  before serving weather/travel for a possibly-wrong location — reuse Phase 31's
  "still in France, Sir?" nightly-ask pattern rather than inventing a new prompt
  surface. Weather (`fetch_weather`, currently hardcoded default "Tel Aviv") and
  travel-time (`routes_tool`) both consume the derived `current_location`.
- The location gather is **context-only** — deriving a location must never wake
  the free tier.

### Groq token ledger + cap behavior (MEM-05/06)
- **D-07: Warn at 80% (160K of 200K TPD).** Heartbeat flags when the day's Groq
  usage crosses ~80% of the cap — early enough to react before ticks fail, not so
  early it cries wolf on a busy day. Also alert when `tick_fallback` purposes
  spike (per MEM-06).
- **D-08: At the cap, fall to the Gemini tick-brain fallback.** When the daily
  Groq budget is exhausted, route tick-brain reasoning to the existing
  `TICK_BRAIN_FALLBACK` (Gemini) for the rest of the day — ticks keep judging,
  just not free. The ledger + the 80% heartbeat warning make the (small) cost
  visible. This reuses the existing fallback path rather than silencing Klaus.
- The ledger is a **local Firestore counter** (Groq exposes no daily-remaining
  header) incremented per tick-brain call, reset daily.

### Context-only invariant + budget guard (MEM-05) — non-negotiable
- All four new gathers (`conversation_tail`, `standing_directives` [already],
  `training_reality`, `location`) are context-only in `_is_empty_signals`. A
  token-budget guard test asserts the MAXIMAL rendered triage prompt + `max_tokens`
  fits Groq's verified per-request ceiling (8K TPM for gpt-oss-120b). This test is
  a hard requirement of the phase, not optional.

### Claude's Discretion
- Auto-recall relevance/score threshold and recency-weighting formula (REQUIREMENTS
  says score-thresholded + recency-weighted, k≈5 — pick the concrete numbers).
- Exact rendering/labels of the "Things you remember" block and the
  `training_reality` block in chat vs triage vs paid-compose prompts (windows
  differ per MEM-04; keep the triage version within the char cap).
- Boundary-marker wording for D-05 continuity.
- Ledger schema (counter doc shape, reset mechanism, per-purpose breakdown) and
  the exact heartbeat alert phrasing.
- How `current_location` derivation reads calendar travel events (what shape marks
  a "travel event") and how it composes with a standing directive's location text.
- Placeholder positions for the new blocks in `smart_agent.md` — MUST sit AFTER
  the stable cached prefix (30.5 prompt-caching landmine: volatile content before
  the cache breakpoint silently kills cache reads).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone plan & review (source of locked decisions)
- `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` — approved v6.0
  implementation plan; Phase 32's ambient-memory / unified-situation design lives here
- `~/.claude/plans/mellow-puzzling-nest.md` — approved review amendments

### v6.0 research (HIGH confidence for this phase)
- `.planning/research/SUMMARY.md` §Phase 3 (32) — ambient memory + unified situation delivery list
- `.planning/research/ARCHITECTURE.md` — situation assembler, gather isolation, context-only invariant
- `.planning/research/PITFALLS.md` — cost-gate / over-fire pitfalls + cache-prefix ordering (constrains new prompt-block placement)

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §MEM-01..07 verbatim (mechanics locked there: k≈5,
  char caps, 24h/48h windows, context-only invariant, budget-guard test) — read
  before planning, decisions here do NOT restate the locked mechanics
- `.planning/ROADMAP.md` §Phase 32 — goal + 6 success criteria

### Prior phase context (directly upstream)
- `.planning/phases/31-standing-directives/31-CONTEXT.md` — `get_recent_window()`
  primitive (this phase depends on it), the context-only-gather pattern
  (`_gather_standing_directives` excluded from `_is_empty_signals`), and the
  nightly-ask pattern reused for D-06 location ambiguity
- `.planning/phases/30.5-brain-upgrade-sonnet-5/30.5-CONTEXT.md` — Sonnet-5 brain
  + prompt-caching cache-breakpoint placement (constrains where new blocks render)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/autonomous.py::_is_empty_signals` (line 175) — the cost gate. New gathers
  land as sibling `_gather_*` functions but are deliberately NOT checked here
  (D-01/D-06 context-only). Existing exclusion comments (training_status/acwr line
  193-195, standing_directives line 220-226) are the exact model.
- `core/autonomous.py::gather_situation` (line 582) — thread-pooled, sentinel-on-
  failure isolation; new gathers (`conversation_tail`, `training_reality`,
  `location`) follow the same never-raise contract.
- `memory/firestore_conversation.py::FirestoreConversationStore.get_recent_window`
  — landed in Phase 31; powers both the chat continuity tail (MEM-02) and the
  cascade tails (MEM-04). Already used in `core/reflection.py` (line 178).
- `mcp_tools/memory.py::MemoryStore.recall` (line 49, k=5 default) — the auto-recall
  block reuses this; `forget_memory` is a new deliberate-delete tool (Pinecone
  delete by id) alongside it.
- `mcp_tools/weather_tool.py::fetch_weather` (line 19, hardcoded default "Tel Aviv")
  and `mcp_tools/routes_tool.py` — both repointed to consume `current_location`.
- `core/tick_brain.py` — `TICK_BRAIN_MAX_TOKENS` (default 2048), Groq 8K TPM/request
  budget documented at line 16-22; the budget-guard test asserts against this
  ceiling. `TICK_BRAIN_FALLBACK` (Gemini) is the D-08 at-cap route.
- `memory/firestore_db.py` — home for the new Groq token-ledger store (follow the
  LLMUsage / counter patterns; `increment_fallback_counter` referenced in main.py:734).
- `core/reflection.py` — learning loop already reads `get_recent_window`; the D-04
  contradicted-memory flag is woven into the nightly narrative here (mirrors Phase 31
  prune-flag pattern).

### Established Patterns
- Firestore store-per-collection with `_jsonsafe_doc` ISO conversion (SERVER_TIMESTAMP
  → JSON gotcha — bit MealStore + TrainingLogStore). The token ledger inherits this.
- Context-only gather = new `_gather_*` returns a sentinel on failure and is NOT
  referenced in `_is_empty_signals`. This is a HARD invariant (MEM-05 / SC-5).
- Every new env var must go into `deploy.yml` (`--set-env-vars` clobbers out-of-band
  Cloud Run vars). Likely thresholds (80%, cap) are constants/env — check.
- Test env: full pytest segfaults in one process (grpc/protobuf) — verify per-file;
  the ~1775-backend baseline must hold. Python 3.13 venv (never 3.14).
- Prompt-cache landmine (30.5): volatile blocks MUST sit after the stable cached
  prefix in `smart_agent.md` or cache reads silently die.

### Integration Points
- `core/main.py::render_smart_system` — new `{things_you_remember}` +
  `{training_reality}` (+ continuity tail) placeholders, all after the cache prefix.
- `core/autonomous.py` gather layer — new context-only gathers; Layer-1 triage
  (`prompts/autonomous_triage.md`) and Layer-2 compose (`prompts/autonomous.md`)
  both render `training_reality` (different windows per MEM-04).
- `core/tick_brain.py` — token-ledger increment per call; at-cap fallback to Gemini.
- `core/heartbeat.py` — reads the ledger, emits the 80% / fallback-spike warning.
- Weather + routes tools — consume derived `current_location`.
- `core/reflection.py` — contradicted-memory nightly flag (D-04).

</code_context>

<specifics>
## Specific Ideas

- Amit wants the CORRECT location answer over a quiet one — "ask when ambiguous"
  was chosen over silent-default-home for conflict cases. Weather delivered to the
  wrong city is a real, felt bug (Paris getting Tel Aviv). But the common case
  (home, no travel) stays silent — no location chatter on a normal day.
- Continuity should FEEL seamless — Amit explicitly said "whatever you think is
  better regardless of the amount of work." So the tail rehydrates as real history
  (natural), with the time-gap marker doing the work of preventing stale re-action.
  Don't take the cheap labeled-recap-block shortcut.
- "Evidence wins" reflects that Amit's sensors (Garmin/Hevy) capture reality even
  when he doesn't self-log — a real workout must never read as "not done" just
  because the training_log is empty.
- The whole phase's north star: Klaus gets SMARTER context on every path WITHOUT
  spending a cent more — the context-only invariant and the budget guard are the
  point, not an afterthought.

</specifics>

<deferred>
## Deferred Ideas

- Routing occasions (nightly/morning/weekly) through the shared cascade so
  `training_reality` and the tails drive proactive judgment — that's Phase 33
  (Occasion Cascade), which explicitly depends on this phase's context-only
  invariant + Groq ledger being safe first.
- Mechanically updating the training source of truth from calendar workout actions
  or chat-reported changes — Phase 34 (Write-Backs). This phase only READS/reconciles.
- A Hub surface for browsing/forgetting memories — not in scope; deliberate
  `forget_memory` is chat/nightly-driven for now.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 32-Unified Situation (Ambient Memory)*
*Context gathered: 2026-07-22*
