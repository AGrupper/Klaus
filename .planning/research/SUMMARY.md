# Project Research Summary

**Project:** Klaus v6.0 "Klaus Becomes an Agent"
**Domain:** Self-governance rework of an existing deployed personal AI agent — brain-model migration, standing directives, ambient memory, and judgment-driven proactivity, layered onto a live Cloud Run / Firestore / Pinecone system with 5 shipped milestones behind it
**Researched:** 2026-07-17
**Confidence:** HIGH

## Executive Summary

Klaus v6.0 is not a greenfield build — it's a targeted rework of a proven proactive-agent architecture, moving the smart brain from `gemini-3.5-flash` to `claude-sonnet-5` (with Anthropic prompt caching), and adding three new capability layers (standing directives, ambient auto-recall memory, and a judgment-driven "occasion cascade" that replaces template-composed nightly/morning messages). All four research passes converge on the same core insight: the risk in this milestone is almost entirely in wiring discipline and sequencing, not in unknowns. The stack is well-documented (official Anthropic docs for Sonnet 5's API behavior, official Groq docs for the already-shipped tick-brain), the feature patterns are well-precedented (ChatGPT/Claude memory, MemGPT/Letta, Zep/Graphiti, Stanford Generative Agents all provide directly-applicable reference architectures), and the architecture reuses Klaus's existing store-per-collection, gather-isolation, and singleton-orchestrator patterns rather than inventing new ones. Nothing here requires a new library, a new datastore, or a new hosting primitive.

The recommended approach is to treat this as six tightly-ordered phases (30.5 → 31 → 32 → 33 → 34 → 35), each gated on specific plumbing from the prior phase: the tick-brain's fallback must be decoupled from the brain's env vars before the brain flips to Sonnet (or a Groq hiccup silently bills Anthropic pricing); `get_recent_window()` must exist before the reflection learning loop reads a day's conversation (the current 6h session-window read is empty at reflection time on most nights — a live bug, not a hypothetical); the context-only invariant on every new autonomous.py gather must be audited before Phase 33 routes nightly/morning traffic through triage (or routine chat activity defeats the free-tier cost gate that is Klaus's entire cost model); and the `OCCASION_CASCADE` flag must run old and new composers in parallel for an observation window before the legacy code is deleted in Phase 35.

The dominant risk category, confirmed independently by both the pitfalls and stack research, is cost/metering correctness during the brain swap: Sonnet 5's new tokenizer produces ~30% more tokens for the same text than Gemini's, adaptive thinking is on by default and consumes the same `max_tokens` budget as the visible response, sampling parameters (`temperature`/`top_p`/`top_k`) now hard-reject with HTTP 400 instead of silently ignoring, and prompt-caching's billing fields (`cache_read_input_tokens`/`cache_creation_input_tokens`) must be extracted and priced correctly or the new daily-spend tripwire — the safety net for this exact risk — alerts on wrong numbers. The second dominant risk category is judgment regression from directives/memory features that look done but aren't: coarse-grained directive vetoes that over-suppress unrelated topics, casual venting captured as permanent directives, ambient memory silently poisoning judgment with stale facts, and judged silence being indistinguishable from infra failure without explicit status tracking. All of these have concrete, cheap mitigations identified in the pitfalls research and should become explicit phase acceptance criteria, not just implementation notes.

## Key Findings

### Recommended Stack

No new libraries or infrastructure are needed for v6.0 — this is a version-floor bump (`anthropic>=0.40` → `anthropic>=0.99,<1.0`) plus disciplined use of already-integrated SDKs (Anthropic, Groq via OpenAI-compat, Gemini for embeddings). The actual engineering work is in `core/llm_client.py`/`core/pricing.py` integration points: restructuring `system` from a plain string to a content-block list carrying `cache_control`, extracting new usage fields from Anthropic responses, and auditing every Anthropic-backend call site for parameters that now hard-reject (temperature/top_p/top_k, manual `thinking.budget_tokens`). Streaming is explicitly not needed — Klaus's Cloud-Tasks-backed async architecture already avoids the idle-connection-timeout problem streaming exists to solve.

**Core technologies:**
- `anthropic>=0.99,<1.0` (verified latest 0.117.0): Brain backend SDK — bump the floor to get typed `OutputConfigParam`/`ThinkingConfigAdaptiveParam` support; no breaking call-shape changes
- `claude-sonnet-5` (API model ID): Smart-agent brain model — 1M context, 128K max output, $3/$15 per MTok standard ($2/$10 intro pricing through 2026-08-31 — cost dashboards need a dated note, not a static number)
- Prompt caching (`cache_control: {"type": "ephemeral", "ttl": "1h"}`): The actual cost lever for the milestone — use the 1-hour TTL, not the 5-minute default, because Klaus's call cadence (20-min autonomous tick, bursty interactive chat) mostly exceeds 5 minutes between calls
- `openai/gpt-oss-120b` on Groq (already shipped): Free tick-brain, 30 RPM/1,000 RPD/8,000 TPM/200,000 TPD — confirmed no deprecation notice, but keep the Gemini fallback wired and tested since Groq gave the prior model (qwen3-32b) a hard decommission with limited notice

### Expected Features

Klaus's planned three new capability areas (standing directives, ambient auto-recall, judgment-driven proactivity) map cleanly onto well-established patterns from ChatGPT memory, Claude memory, MemGPT/Letta, and Zep/Graphiti — but the milestone's specific combination (agent-proposed directives from observed reactions, self-explainable silence as a first-class outcome) goes beyond every reviewed consumer reference system. That novelty is exactly where the highest implementation risk concentrates.

**Must have (table stakes):**
- Explicit directive capture with immediate confirmation, provenance tagging (Amit-stated vs. Klaus-proposed), and recency-wins conflict resolution (not LLM-adjudicated freshness)
- Directive expiry/TTL by default — every reviewed memory system treats unbounded retention as a bug, and this directly addresses the milestone's own motivating example (a stale "stop nagging about training while I'm in France" directive silently outliving the trip)
- Ambient ("hidden system note") auto-injection of relevant memory, gated by relevance + recency + importance — not pure cosine similarity, which is the known-inferior baseline every reviewed system improves on
- Absolute quiet-hours/suppression honoring and notification-budget discipline (already implemented in spirit; must not regress under the new occasion cascade)

**Should have (differentiators — genuinely rare in the reviewed literature):**
- Agent-proposed directives from observed reactions (reflection learning loop) — no reviewed consumer system self-proposes behavioral rules; the one-line human veto is the correct, literature-consistent mitigation for this being the riskiest, most novel piece
- Self-explainable proactive decisions (`get_recent_decisions`) that explain silence, not just action — almost no consumer proactive-AI product surfaces this
- Judgment-gated, fully skippable scheduled occasions (nightly/morning stop being always-fire templates) — the core differentiator matching the milestone's "silence as a valid choice" value statement

**Defer (v2+/fast-follow, not this milestone):**
- Deeper bitemporal-style directive history (queryable supersession chains) — the lightweight version (never hard-delete, `superseded_by` field) is sufficient at Klaus's single-user data volume
- Full knowledge-graph memory backend (Zep/Graphiti-style) — not warranted at this scale; the existing Firestore store pattern covers the useful subset
- Hub-surfaced directive/decision visibility — flagged as a natural v6.1 follow-up, not required for v6.0's backend-first scope

### Architecture Approach

The target architecture is explicitly a collapse, not an addition: four independent proactive pipelines (tick, nightly, morning, weekly) become one judgment cascade (`core/autonomous.py::run_autonomous_tick`) parameterized by an `occasion` argument, with the existing state-machine wrappers (`nightly_review.py`, `morning_briefing.py`) staying as thin callers that keep their idempotency/dedup/cutoff logic but delegate composition to the shared cascade. New context (standing directives, conversation tail, reconciled training reality, location) is added via the existing sentinel-on-failure gather-isolation pattern already used for 14 sources in `gather_situation()`, and rendered once per call site through shared formatter functions backed by the existing `_READ_CACHE` mechanism — avoiding the "five independent formatters drift" failure mode this codebase has already hit once.

**Major components:**
1. `core/llm_client.py::_AnthropicBackend` + `core/pricing.py` — Sonnet-5 compatibility audit, cache_control wiring, cache-token extraction and pricing (Phase 30.5)
2. `memory/firestore_db.py::StandingDirectiveStore` (new, modeled on `FollowupStore`) + a shared `render_standing_directives_block()` formatter consumed by 5 call sites (chat, triage, compose, follow-up compose, interim legacy-cron injection) (Phase 31)
3. `memory/firestore_conversation.py::get_recent_window()` (new, per-message `ts` field) — a genuine shared dependency consumed across Phase 31's learning-loop fix, Phase 32's ambient-recall tail-prepend, and Phase 32's `conversation_tail` gather job; must land in Phase 31 per an explicit sequencing amendment (B3)
4. `core/autonomous.py::gather_situation()` extended with `standing_directives`, `conversation_tail`, `training_reality`, `location` — all must be context-only in `_is_empty_signals`, never triggers, to protect the free-tier cost gate (Phase 32)
5. `core/autonomous.py::run_autonomous_tick(occasion=...)` — occasion parameter bypasses the empty-gate and selects prompt/routing, reused by nightly/morning behind an `OCCASION_CASCADE` flag for a parallel-run observation window before legacy composer deletion (Phase 33)
6. `core/tools.py` calendar handlers gain mechanical write-back hooks to `TrainingLogStore` — fires from the tool handler itself, not a prompt instruction, because a prompt instruction is exactly the failure mode this milestone exists to fix (Phase 34)

A hard, explicitly-verified constraint threads through the whole build: `core/autonomous.py` must never import `core/nightly_review.py`. The one piece of logic both need (`planned_sessions_for`) moves into the already-neutral `core/training_checkin.py`, reusing a proven acyclic import direction rather than introducing a new dependency edge.

### Critical Pitfalls

1. **Tick-brain fallback silently inherits the new (expensive) brain model** — `core/tick_brain.py`'s Groq-failure fallback currently reads `SMART_AGENT_*`; the instant Phase 30.5 repoints those to `claude-sonnet-5`, every Groq hiccup lands on Sonnet pricing invisibly. Must ship decoupled `TICK_BRAIN_FALLBACK_*` env vars in the same deploy as the model flip, verified by forcing a Groq error in staging and confirming the fallback logs `gemini-3.5-flash`.
2. **Prompt-caching billing fields aren't captured, so the new cost tripwire alerts on wrong numbers** — `cache_read_input_tokens`/`cache_creation_input_tokens` must be extracted and priced correctly (reads at ~0.1x, writes at ~1.25x base input) in the same change that ships `cache_control`, verified against the real Anthropic console within ~10%.
3. **Sonnet's literal instruction-following turns Gemini-era prescriptive prompt rules into over-application bugs** — `smart_agent.md`/`autonomous_triage.md` were empirically tuned against a flash-tier model's weaker instruction-following; a smarter model executes the same `ALWAYS`/`NEVER` imperatives more aggressively, which is the opposite of the milestone's "judgment replacing scripts" goal. Requires a light de-prescription pass before cutover and a deep rewrite across Phases 31-33, verified by eval-harness parity plus a canary comparison on real conversation snippets.
4. **New gathers silently defeat the free-tier cost gate if not marked context-only** — any new field in `gather_situation()` (conversation tail, standing directives, training_reality, location) that becomes truthy on an ordinary day (chat activity is nearly always true) flips `_is_empty_signals` and spends Groq/Sonnet budget on what used to be free no-ops. Every new gather needs an explicit, documented context-only exclusion, plus a token-budget guard test against Groq's verified per-request ceiling.
5. **Judgment-driven silence is indistinguishable from infra failure without explicit status tracking** — the milestone's core deliverable is "trust the silences," but an LLM error, Groq outage, or assembler bug also produces silence. Without `status: sent|skipped_by_judgment` actively wired and monitored (not just present in Firestore), a real outage looks identical to healthy autonomy and can run for days unnoticed — the same shape as a known past incident (weeks of silent Groq→paid fallback), but now invisible by design.

## Implications for Roadmap

Based on combined research, the milestone's already-approved phase structure (30.5 → 31 → 32 → 33 → 34 → 35) is correct and should not be reordered — all four research passes independently converge on the same dependency chain. The value of this synthesis is less "propose new phases" and more "harden the acceptance criteria within each approved phase" using the specific pitfalls, stack facts, and feature patterns surfaced above.

### Phase 1 (30.5): Brain migration — Sonnet 5 + prompt caching
**Rationale:** Everything downstream (directive injection, ambient recall, occasion cascade) assumes a working, correctly-metered, non-over-literal brain. Must land first and in the specific internal order the architecture research lays out: decouple tick-brain fallback env → Anthropic backend compatibility audit + cache-token extraction (same change as the cost tripwire) → pricing/LLMUsage field additions → flip `SMART_AGENT_*` env → SELF.md/prompt slimming pass → heartbeat daily-spend tripwire.
**Delivers:** `claude-sonnet-5` as the live brain with truthful cost metering, prompt caching active on the stable prefix, and a decoupled Gemini fallback for both the smart agent and the tick-brain.
**Addresses:** Stack research's core recommendation (1h TTL caching, typed SDK support); Pitfalls 1, 2, 3.
**Avoids:** Silent fallback-cost-inversion (Pitfall 1), wrong-tripwire-numbers (Pitfall 3), sampling-parameter 400 errors and adaptive-thinking truncation (Stack integration points 1-2).

### Phase 2 (31): Standing directives
**Rationale:** Directives are the first new judgment-input layer and the most self-contained new store — no dependency on ambient memory or the cascade. Must include `get_recent_window()` on `FirestoreConversationStore`, sequenced here (not Phase 32) because the reflection learning-loop fix needs it immediately (the current 6h session read is empty at reflection time on most nights).
**Delivers:** `StandingDirectiveStore` + capture/list/cancel tools, Step-0 triage veto, reflection learning loop with provenance-gated one-line veto, interim direct injection into legacy nightly/morning composers.
**Addresses:** Features research's P1 items (directive capture, provenance, TTL, reflection learning loop); Architecture's shared-formatter pattern.
**Avoids:** Coarse-topic-match over-suppression (Pitfall 5) and vent-captured-as-permanent-directive (Pitfall 6) — both need negative-case eval fixtures and default-bounded expiry, not just the happy path.

### Phase 3 (32): Unified situation — ambient memory, conversation tail, training reality
**Rationale:** Depends on Phase 31's `get_recent_window()` primitive. This phase carries the highest reliability risk in the milestone (new chat-critical-path network call) and the highest cost-model risk (prompt growth toward Groq's per-request ceiling), so its acceptance criteria must be the most rigorous.
**Delivers:** Ambient auto-recall (timeout-guarded, best-effort, off the chat critical path), `conversation_tail`/`training_reality`/`location` gather jobs (all context-only in the empty gate), `forget_memory` hygiene tool shipped alongside auto-recall (not deferred), Groq daily token ledger, token-budget guard test.
**Uses:** Features research's relevance/recency/importance-weighted retrieval pattern (not pure similarity); Stack research's confirmation that no header exposes Groq's daily cap (must build a local ledger).
**Implements:** Architecture's gather-isolation and render-once-reuse patterns extended to four new sources.
**Avoids:** Chat-turn latency regression from an unguarded network call (Pitfall 7 — literally the same incident class, worse blast radius, as a known past 500-error incident); ambient memory poisoning judgment with stale facts (Pitfall 8 — hygiene must ship in the same phase as retrieval); Groq silent-fallback recurrence via token growth rather than a code bug (Pitfall 11).

### Phase 4 (33): Occasion cascade
**Rationale:** Depends on Phase 32's context-only invariant and Groq ledger being in place before nightly/morning traffic routes through triage — otherwise the volume increase silently breaks the free-tier cost model on day one.
**Delivers:** `occasion` parameter on `run_autonomous_tick`, `OCCASION_CASCADE` flag running legacy and cascade composers in parallel for an observation window, `get_recent_decisions` introspection tool, differentiated failure semantics per surface (tick=silence, nightly=deterministic plain-text fallback, morning=silent skip).
**Addresses:** Features research's core differentiator (silence as a first-class judged outcome); Architecture's Pattern 3 (occasion as a cascade parameter, not a new pipeline).
**Avoids:** A fifth independent proactive pipeline (Architecture Anti-Pattern 1); judged-silence-vs-infra-failure ambiguity (Pitfall 9 — needs active status-field monitoring, not just a schema field); flag-and-delete-in-one-PR (Architecture Anti-Pattern 4 / Pitfall's technical-debt table).

### Phase 5 (34): Write-backs
**Rationale:** Write-back hooks only depend on stable `core/tools.py` calendar handlers and `TrainingLogStore`, but the idempotency check for directive-gated proactive writes needs Phase 33's occasion machinery and produces the natural dedup key (date+slot) — hence sequenced right after 33.
**Delivers:** Mechanical, tool-handler-level write-backs on calendar create/move/delete (fires unconditionally on success, never a prompt instruction), idempotency guard against duplicate events/rows on compose-succeeds/delivery-fails retries.
**Addresses:** The milestone's own root-cause finding (Klaus was told things and didn't durably act) — Architecture Anti-Pattern 5 names this explicitly.
**Avoids:** Non-idempotent proactive side effects under retry (Pitfall 10) — the write-back layer must double as its own dedup guard, not a separate concern bolted on later.

### Phase 6 (35): Evals, hardening, subtraction
**Rationale:** Purely additive/subtractive with no new integration surface — must come last so fixtures can be written against a stable system, and legacy-composer deletion can only happen after the Phase 33 flag has been observed stable across a multi-day window.
**Delivers:** ≥6 new judgment eval fixtures (including required negative cases per Pitfall 5/9), token-budget guard test, deletion of `_compose_nightly`/`_compose_briefing` legacy branches + `OCCASION_CASCADE` flag + dead code (`proactive_alerts.py`, TickTick/worktree residue), updated `CLAUDE.md` invariants.
**Addresses:** Features research's anti-feature warning (eval harness must score judgment quality and silence-as-win, not raw tick-to-message conversion — a documented "vanity metric" trap).

### Phase Ordering Rationale

- Brain migration (30.5) must precede any prompt-philosophy rewrite (31-33) because the de-prescription pass assumes Sonnet's more literal instruction-following — reordering would mean rewriting prompts twice.
- `get_recent_window()` must land in Phase 31, not 32, because the Phase 31 reflection learning-loop bug fix needs it immediately — this is a hard dependency surfaced by direct codebase inspection (`core/reflection.py:159` reads an empty 6h window at reflection time), not a preference.
- The context-only invariant and Groq token ledger (32) must be complete before Phase 33 routes nightly/morning traffic through triage — this is the single highest-leverage cost-safety gate in the whole milestone, since it protects against the free-tier budget being silently defeated by ordinary chat volume.
- The `OCCASION_CASCADE` flag introduction (33) and legacy composer deletion (35) must be two separate phases/PRs, never collapsed — this is independently confirmed by both the architecture anti-patterns and the pitfalls technical-debt table as a rollback-safety requirement.

### Research Flags

Phases likely needing deeper research during planning (`--research-phase`):
- **Phase 31 (standing directives):** The directive-scoping veto logic (avoiding both under- and over-suppression) and the venting-vs-genuine-directive classification are genuinely hard LLM-judgment problems without a deterministic solution — worth a focused pass on prompt design and eval fixture construction before implementation.
- **Phase 32 (unified situation):** The token-budget arithmetic (current triage ≈3.2-3.7K tokens against an admission ceiling that leaves as little as ~0.3K headroom once all Phase 32 additions land) is tight enough that implementation should re-verify the actual combined prompt size empirically, not from the estimates in this research, before shipping.

Phases with standard, well-documented patterns (skip research-phase):
- **Phase 30.5 (brain migration):** Stack research is HIGH confidence and directly actionable — official Anthropic docs cover every integration point (sampling parameters, adaptive thinking, caching, usage fields) with no ambiguity.
- **Phase 34 (write-backs):** Mechanical, well-scoped, reuses existing `TrainingLogStore` patterns with no new architectural questions.
- **Phase 35 (evals/hardening):** Additive/subtractive work against an already-understood system; the main task is fixture-writing, not design.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All Anthropic facts verified against official `platform.claude.com` docs published for the Sonnet 5 launch; Groq limits verified against official docs and cross-checked by an independent tracker; direct codebase inspection confirms current call-site behavior |
| Features | MEDIUM-HIGH | Patterns cross-verified across 3+ independent named systems (ChatGPT, Claude, MemGPT/Letta, Zep/Graphiti, Stanford Generative Agents) per finding; Klaus-specific complexity estimates are HIGH confidence (direct codebase knowledge), but the "agent-proposed directives from reactions" differentiator has no directly comparable production reference system, so its risk/complexity estimate is inherently more speculative |
| Architecture | HIGH | All findings verified against live source with file:line citations; the two approved planning documents were treated as primary sources and cross-checked against the actual files they reference, not inferred |
| Pitfalls | HIGH | Grounded in the live codebase, the approved plan and review, four known past incidents in this exact system, and external sources on prompt caching, memory poisoning, Groq limits, and idempotent agent side effects |

**Overall confidence:** HIGH

### Gaps to Address

- **Actual Sonnet-5 tokenized size of `smart_agent.md`/`autonomous_triage.md`:** The milestone's "~4.5K tokens off every call" slimming target was sized against the old (Gemini) token count; Sonnet 5's new tokenizer produces ~30% more tokens for the same text. Re-run `client.messages.count_tokens(...)` against the actual model before treating any slimming number as a phase acceptance criterion — flag this for Phase 30.5 requirements, not just as an FYI.
- **Combined triage prompt size under Phase 32's full gather load:** Research estimates ~7-8K tokens/call against Groq's ~6-8K TPM per-request admission window, leaving thin headroom — this needs empirical re-verification during Phase 32 implementation with a guard test that encodes the actually-verified ceiling, not the estimate in this document.
- **Weekly-review fold-in decision (E1):** Explicitly left as an open decision in the approved plan/review — whether `weekly_training_review.py` gets a compose swap into the occasion cascade or stays a legacy path. Must be resolved as an explicit checkpoint before Phase 35 cleanup, not left ambiguous (per both the architecture research and the pitfalls technical-debt table).
- **Directive-scoping veto precision in production:** The research identifies the over/under-suppression risk and a design mitigation (require stated scope to plausibly cover the specific occasion), but real precision can only be validated against production directive text once Amit starts using the feature — budget for iteration after initial ship, informed by the Phase 35 eval fixtures.

## Sources

### Primary (HIGH confidence)
- [What's new in Claude Sonnet 5](https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5) — sampling-parameter 400 behavior, adaptive thinking, tokenizer change, pricing
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — cache prefix minimums, TTL/pricing multipliers, usage fields
- [Adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking) — effort levels, max_tokens interaction, cache-breakpoint interaction
- [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits) and [model card](https://console.groq.com/docs/model/openai/gpt-oss-120b) — Groq free-tier limits, header semantics
- PyPI `anthropic` package JSON API — current SDK version verification
- `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` (approved v6.0 plan) and `~/.claude/plans/mellow-puzzling-nest.md` (approved review/amendments) — primary sources, cross-checked against code
- Klaus codebase direct inspection (`core/main.py`, `core/autonomous.py`, `core/tick_brain.py`, `core/llm_client.py`, `core/nightly_review.py`, `core/morning_briefing.py`, `memory/firestore_db.py`, `memory/firestore_conversation.py`, `core/tools.py`, `interfaces/web_server.py`) — file:line verified integration points and known incident precedent
- `.planning/PROJECT.md` — milestone scope, locked decisions, phase target features

### Secondary (MEDIUM confidence)
- OpenAI/Anthropic memory product documentation (ChatGPT Memory FAQ, Claude memory tool docs) — reference-system comparison
- Letta/MemGPT, Zep/Graphiti architecture docs and blog posts — directive-vs-fact distinction, provenance, bitemporal supersession patterns
- [grizzlypeaksoftware.com — Groq API Free Tier Limits](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb) — third-party cross-check, matches official docs exactly
- Idempotent agent side-effect pattern articles (Chanl, tianpan.co) — check-before-act pattern for proactive calendar writes

### Tertiary (LOW-MEDIUM confidence, used as directional signal)
- arXiv papers on memory conflict resolution, forgetting, and over-personalization (2606.01435, 2604.02280, 2601.13722, 2606.06054) — recency-wins default, sycophancy risk, retrieval-as-decision framing; single-paper findings, not yet production-proven at Klaus's scale
- Stanford Generative Agents (Park et al., arXiv 2304.03442) — recency/importance/relevance retrieval scoring, foundational but a research simulation, not a production system

---
*Research completed: 2026-07-17*
*Ready for roadmap: yes*
