# Phase 31: Standing Directives - Context

**Gathered:** 2026-07-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Amit can state a lasting wish about Klaus's behavior once in chat and have it honored
everywhere — `StandingDirectiveStore` (modeled on `FollowupStore`) captures directives
verbatim with origin + triggering-context quote; active directives are injected into EVERY
reasoning path (chat system prompt, tick triage as a Step-0 STANDING ORDERS veto, Layer-2
compose, follow-up compose, interim legacy-cron composers); directives are listable and
cancellable from chat; end conditions expire them; persona conflicts are flagged once; and a
new `get_recent_window()` on `FirestoreConversationStore` powers a nightly reflection
learning loop that pairs each Klaus-initiated outreach with Amit's reaction and may propose
self-directives (`origin="klaus_self"`) with a one-line veto. Requirements DIR-01..07.
Ambient memory, occasion cascade, and write-backs belong to Phases 32–34.

</domain>

<decisions>
## Implementation Decisions

### Locked upstream (approved plan + review + research + user decisions — do not re-litigate)
- `StandingDirectiveStore` modeled on `FollowupStore` (`memory/firestore_db.py:1569`); verbatim text + origin + triggering-context quote; never hard-delete; `superseded_by` chains
- **No automatic TTL / no default expiry** — user decision 2026-07-17 (REQUIREMENTS Out of Scope)
- Step-0 STANDING ORDERS veto sits above all other triage logic; shared `render_standing_directives_block()` formatter consumed by all 5 call sites
- `get_recent_window()` lands THIS phase (reflection's 6h session read is empty most nights — the learning loop needs it immediately)
- Veto must be topic-scoped, not blanket (Pitfall 5): a directive suppresses only what its stated scope plausibly covers; triage reasoning names the directive it applied
- `set_standing_directive` / `list_standing_directives` / `cancel_standing_directive` are brain-direct tools (`SMART_AGENT_DIRECT_TOOLS`)

### Capture judgment
- **D-01:** **Liberal capture** — Klaus captures whenever a remark plausibly reads as a lasting wish; no gating question. The visible ack is the correction surface. ("I already told you…" is a named trigger per DIR-01.)
- **D-02:** Ack = **echo + expiry read-back** in Klaus's voice — one line restating the wish AND the understood duration (e.g. "Standing order, Sir: no training nudges until you're back from France."). Misreads are correctable on the spot.
- **D-03:** For "I already told you…" triggers, store the **current restatement** verbatim; the triggering-context quote records this exchange. No history/Pinecone digging for the original.
- **D-04:** Accumulation guard = **reflection prune-flag**: the nightly learning loop sanity-checks active directives against the 24h window and flags stale/contradicted ones in the nightly message. No periodic digest, no auto-decay.

### Expiry mechanics
- **D-05:** **Hybrid expiry** — explicit timeframes parse to a hard `expires_at` date at capture; event-based conditions ("while I'm in France") store the condition text, and nightly reflection judges (against calendar + conversation) whether the condition has ended, expiring the directive.
- **D-06:** Conditionless captures: **capture first, ask in the ack** — the directive is stored immediately as persist-until-cancelled (DIR-02 storage semantics intact); the ack appends a soft duration question ("Until further notice, or is there an end to this?"). Ignoring it leaves the directive indefinite. Never block storage on an answer.
- **D-07:** Expiry (dated or judged) is **noted once in the nightly message** ("France directive expired — training nudges resume tomorrow"). No silent resumption, no dedicated ping.
- **D-08:** When reflection can't tell whether a judged condition ended: **stay active** (honoring the wish is the safe default); if uncertainty persists well past the plausible window, ask in the nightly ("still in France, Sir?"). Never expire on a guess.

### Self-directive lifecycle (DIR-06/07)
- **D-09:** Self-directives are **active on proposal** — they take effect immediately; the nightly message announces each with the one-line veto. No pending-approval state, no grace day.
- **D-10:** Proposal threshold = **single strong signal** — one clear pushback/frustration reaction is enough. User explicitly chose adaptation speed over the repeated-pattern guard.
- **D-11:** **Ignore = strong signal too** — "ignored" is deterministic: no reply from Amit by reflection-window read time. A topic-engaging reply = replied; a subject-changing reply = ignored-topic. A single ignored outreach may ground a proposal.
- **D-12:** Ignore-only proposals may go as far as a **full stop** — no forced softening — but the form (ease off vs stop entirely) is Klaus's per-case judgment from context and what the outreach actually was. Explicit chat asks always override loop inferences.
- **D-13:** **Veto = durable anti-lesson** — vetoed proposals are kept (status `vetoed`, never hard-deleted) and reflection must not re-propose the same or near-same directive. The veto is itself training signal.
- **D-14:** **No cap** on proposals per nightly — everything qualifying is proposed and activated the same night. User accepts changelog-style nightly messages on busy days.

### Veto scope, conflicts, list/cancel
- **D-15:** When triage is genuinely uncertain whether a directive's scope covers a candidate outreach: **suppress now AND queue a scope-clarification question for the nightly**. Triage records which directive it applied and why (feeds Phase 33's `get_recent_decisions`).
- **D-16:** Persona conflicts (DIR-05) are detected and flagged **at capture** — the capture turn asks "which wins, Sir?" in the same exchange and records the answer immediately as the refined directive with `superseded_by` on the old one. No live-and-ambiguous window.
- **D-17:** List UX = **numbered list in Klaus's voice** (text, expiry/condition, origin — self-directives marked); cancel by number ("drop 2") or NL description ("cancel the France one"), brain resolves it, one-line confirm. No command syntax.
- **D-18:** List shows **active by default; history on ask** — "show me everything" surfaces expired/vetoed/superseded entries (all retained in the store).

### Nightly directive traffic
- **D-19:** Directive items (proposals, expiries, prune-flags, scope questions, "still in France?" asks) are **woven into the nightly narrative** — reflection hands them to the compose as context; no fixed "Directives:" section, no separate message.
- **D-20:** Heavy nights are triaged by **Klaus's judgment**: activations and expiries must always be stated (behavior is changing); prune-flags and scope questions may wait a night if the message runs long.

### Legacy-cron veto power (interim, until Phase 33)
- **D-21:** Directives have **full veto power over legacy crons** (morning briefing, weekly review) — a directive whose scope covers a cron skips that send. **The nightly is exempt** (minimal carve-out): it is the veto/announcement channel, so directive housekeeping still delivers even when review content is suppressed.
- **D-22:** The veto is evaluated by **the legacy composer's own compose call** — the directives block is injected with instructions that it may output a skip verdict instead of a message. No new LLM call, no early cascade machinery. Skips are logged distinctly (`skipped_by_directive`) so silence stays distinguishable from failure.

### Claude's Discretion
- `StandingDirectiveStore` schema details (status enum, condition vs date fields, provenance shape) — follow the `FollowupStore` pattern and the decisions above.
- `get_recent_window()` signature/pagination and per-message `ts` handling on `FirestoreConversationStore`.
- Exact Step-0 veto prompt wording (must satisfy D-15 + Pitfall 5 topic-scoping; negative-case fixtures arrive in Phase 35).
- How a directive-skipped legacy morning briefing interacts with the `structured` snapshot / `daily_note` hub contract (not discussed; keep the hub `/api/today` contract unbroken).
- `{standing_directives}` placeholder position in `smart_agent.md` — must sit AFTER the stable cached prefix (30.5 prompt-caching landmine: volatile content before the cache breakpoint silently kills cache reads).
- Veto-phrase recognition in next-morning chat (NL via brain; no rigid syntax).
- Dedup behavior when Amit restates an existing directive (refresh vs duplicate).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone plan & review (source of locked decisions)
- `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` — approved v6.0 implementation plan; Phase 31's directive design lives here
- `~/.claude/plans/mellow-puzzling-nest.md` — approved review amendments (learning-loop 24h-window fix is one of them)

### v6.0 research (HIGH confidence for this phase)
- `.planning/research/SUMMARY.md` §Phase 2 (31) — delivery list + the two hard judgment problems (veto scoping, venting-vs-directive)
- `.planning/research/ARCHITECTURE.md` §2 "Standing directives (Phase 31)" — `StandingDirectiveStore` on the `FollowupStore` pattern (firestore_db.py:1569+), 3 injection sites, `render_standing_directives_block()` shared-formatter design, tools.py wiring (`TOOL_SCHEMAS` ~:88, `SMART_AGENT_DIRECT_TOOLS` ~:40-82)
- `.planning/research/PITFALLS.md` Pitfall 5 (coarse veto over-suppression) + Pitfall 6 (venting captured as permanent) — both directly shaped D-01/D-04/D-15; Pitfall on cache-prefix ordering shapes the `{standing_directives}` placement

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §Standing Directives — DIR-01..07 verbatim; §Out of Scope — no default TTL (locked user decision)
- `.planning/ROADMAP.md` §Phase 31 — goal + 6 success criteria

### Prior phase context
- `.planning/phases/30.5-brain-upgrade-sonnet-5/30.5-CONTEXT.md` — Sonnet-5 brain, prompt-caching decisions (cache breakpoint placement constrains where the directives block renders), D-06 de-prescription boundaries (behavior-shaping rewrite is deferred to 31–33)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `memory/firestore_db.py::FollowupStore` (line 1569) — the explicit model for `StandingDirectiveStore` (collection-per-store, status lifecycle, jsonsafe reads)
- `memory/firestore_db.py` module TTL `_READ_CACHE` (~lines 61–86) — cache the directives read per request; the block itself is rendered fresh per call site (architecture's "render once per call site" rule)
- `memory/firestore_conversation.py::FirestoreConversationStore` (line 70) — gains `get_recent_window()` + per-message `ts`; `_txn_append` (line 33) is where the timestamp lands
- `core/reflection.py::_gather_day` (line 123) + `_summarize_conversation` (line 204) — currently best-effort on the empty 6h window (comment at line 152/207); the learning loop replaces this read with `get_recent_window()`
- `core/tools.py` — `TOOL_SCHEMAS` + `_HANDLERS` dispatch + `SMART_AGENT_DIRECT_TOOLS` frozenset; the 3 directive tools follow the existing brain-direct pattern
- `memory/firestore_db.py::OutreachLogStore` (line 1754) + `TickLogStore` (line 2034) — the outreach records the learning loop pairs reactions against; append is send-gated (D-10 invariant)
- `prompts/autonomous_triage.md` — Step-0 STANDING ORDERS veto is prepended here; tuned version deployed per STATE.md pending todo (verify it shipped before editing)

### Established Patterns
- Firestore store-per-collection with `_jsonsafe_doc` ISO conversion (SERVER_TIMESTAMP → JSON gotcha bit MealStore + TrainingLogStore)
- Sentinel-on-failure gather isolation in `core/autonomous.py::gather_situation()` — the interim `_gather_standing_directives` job follows it; full context-only enforcement is Phase 32's MEM-05, but do not let the directives gather flip `_is_empty_signals` from day one
- Every new env var must go into `deploy.yml` (`--set-env-vars` clobbers out-of-band Cloud Run vars) — likely no new env vars this phase, but check
- Test env: full pytest segfaults in one process (grpc/protobuf) — verify per-file; 1775-backend baseline must hold

### Integration Points
- `core/main.py::render_smart_system` — new `{standing_directives}` placeholder (after the stable cached prefix — see 30.5 caching decisions)
- `core/tick_brain.py` / `prompts/autonomous_triage.md` — Step-0 veto injection; mind Groq's 8K TPM/request admission budget (Phase 32 adds the formal guard test, but don't blow the budget now)
- `core/autonomous.py` — Layer-2 compose + follow-up compose render the directives block
- `core/nightly_review.py` + `core/morning_briefing.py` — interim injection with full veto power (D-21/D-22); nightly exempt from veto
- `core/reflection.py` — learning loop: `get_recent_window()` read, outreach-reaction pairing, self-directive proposals, prune-flags, judged-condition expiry
- Nightly send path (`core/scheduled_message.py`) — nightly message carries proposals/expiries/questions woven into the narrative

</code_context>

<specifics>
## Specific Ideas

- The capture ack must read as JARVIS-register Klaus, not a system confirmation — "Standing order, Sir: …" with the duration read back naturally.
- Amit's philosophy for the learning loop is explicitly aggressive: he wants Klaus to genuinely self-correct fast (single signal, ignore counts, active immediately, no cap) and relies on the nightly announcement + veto + list/cancel as the control surface — do not quietly re-introduce conservative guards the discussion removed.
- "It depends on what I ask" — the form of an ignore-grounded self-directive should reflect what the original outreach actually was; Klaus judges per case, full stop permitted.
- Directive-vs-persona conflict question happens in the same breath as capture — one exchange, resolved while context is fresh.

</specifics>

<deferred>
## Deferred Ideas

- Hub page for directives (list + cancel buttons) — already tracked as v6.1 VIS-01.
- "Whether a directive-skipped morning briefing still writes its structured snapshot" — flagged during discussion, not decided; Phase 33's OCC-02 makes snapshot-on-send the rule. For Phase 31, Claude's discretion with the hub contract unbroken.

</deferred>

---

*Phase: 31-Standing Directives*
*Context gathered: 2026-07-18*
