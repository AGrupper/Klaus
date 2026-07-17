# Pitfalls Research

**Domain:** Adding standing-directive / ambient-memory / judgment-driven-proactivity layers to an
existing proactive personal agent (Klaus v6.0 "Becomes an Agent"), plus a mid-life brain-model
swap (`gemini-3.5-flash` → `claude-sonnet-5`) and a free-tier LLM (Groq) dependency for the
always-on triage layer.
**Researched:** 2026-07-17
**Confidence:** HIGH — grounded in the live codebase, the approved v6.0 plan
(`~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md`), the verified critical review
(`~/.claude/plans/mellow-puzzling-nest.md`), four known shipped incidents in this exact system,
and external sources on Anthropic prompt caching, agent memory poisoning, Groq rate limits, and
idempotent agent side effects (see Sources).

**Known past incidents in this system (do not re-derive — extended below where relevant):**
1. Background-task CPU throttling caused an 18-minute reply (agent turns must run inside a
   tracked Cloud Tasks request, never a Starlette `BackgroundTask`).
2. Blocking gather on the event loop starved a Telegram send → weekly-review 500s (fixed via
   `run_in_executor` + one retry).
3. A Groq request-shape bug silently routed every triage call to paid Gemini for weeks —
   cost-gating defeat with zero alerting.
4. A hardcoded fallback `user_id` nulled 823 autonomous ticks silently.

---

## Critical Pitfalls

### Pitfall 1: The Brain Swap Moves the Primary Model but Leaves the Fallback Wired to the New (Expensive) One

**What goes wrong:**
`core/tick_brain.py` builds its Groq-failure fallback client from `SMART_AGENT_BACKEND/MODEL/API_KEY`. The instant Phase 30.5 repoints those env vars to `claude-sonnet-5`, every Groq hiccup — not just the qwen-decommission class of failure, but everyday transient 429s/500s — silently lands on Sonnet pricing. This is the exact same *shape* of bug as known incident #3 (silent Groq→paid-model fallback defeating cost gating), except now the paid model is 10-30x more expensive per token than Gemini Flash was, and the failure is invisible because fallback is by design "it just works."

**Why it happens:**
Model-swap PRs change the primary pointer and treat the fallback as "still fine, it's just a rare path." Nobody re-derives what the fallback *becomes* after the swap, because the fallback logic wasn't touched — only the variable it reads was.

**How to avoid:**
Decouple the tick-brain fallback from `SMART_AGENT_*` entirely: introduce explicit `TICK_BRAIN_FALLBACK_BACKEND/MODEL/API_KEY/BASE_URL` env vars defaulting to `gemini`/`gemini-3.5-flash`, with `SMART_AGENT_*` only as a last-resort legacy fallback if the new vars are unset. Ship this in the *same* Phase 30.5 deploy that flips `SMART_AGENT_*` to Sonnet — never as a follow-up.

**Warning signs:**
- `TickLogStore`/LLMUsage shows `tick_fallback` purpose entries with model string `claude-sonnet-5` instead of `gemini-3.5-flash`.
- Daily cost jumps on a day with no unusual chat volume, correlated with Groq error-rate spikes.
- A forced-Groq-error staging test records the wrong model string.

**Phase to address:**
Phase 30.5 (ship the decoupled env vars in the same deploy as the model flip). Verify: force a Groq error in staging → fallback purpose logs `gemini-3.5-flash`, not `claude-sonnet-5`.

---

### Pitfall 2: Sonnet's Literal Instruction-Following Turns Gemini-Era Prescriptive Rules Into Over-Application Bugs

**What goes wrong:**
`smart_agent.md` (and `autonomous_triage.md`, `nightly_review.md`) were tuned against `gemini-3.5-flash` and lean on `ALWAYS`/`NEVER` imperatives, worked examples, and defensive guardrails to keep a flash-tier model on-rails. Frontier models with stronger instruction-following (documented pattern across Claude/GPT generations) apply blanket imperatives more literally and more aggressively than the weaker model the rule was written for — a `NEVER narrate noise` rule tuned to suppress flash-tier chattiness can, on a smarter model, suppress genuinely worth-saying observations; a `log_training before replying` mandate can trigger a tool call on ambiguous mentions that a human would read as small talk, not a report.
This directly threatens the milestone's stated core value: judgment replacing scripts. If the prompt still reads as a script, a smarter model just executes the script more faithfully — the opposite of the intended effect.

**Why it happens:**
Migrating the model is treated as an infra change (env vars, API compatibility) rather than a prompt-semantics change. The existing prompt corpus (27KB `smart_agent.md`, 11KB `autonomous_triage.md`) was empirically tuned turn-by-turn against Gemini's behavior; nobody re-validates each imperative against the new model before shipping.

**How to avoid:**
- Land the "de-prescription pass" explicitly (already scoped in the plan): light pass in Phase 30.5 lands before Sonnet takes live traffic, deep rewrite happens as Phase 31-33 add the standing-directives/ambient-memory context that lets Klaus reason instead of following checklists.
- Treat every `ALWAYS`/`NEVER` survivor as a hard invariant that genuinely must never vary (delivery idempotency, cost gating, secret denylist) — not a behavioral preference. Behavioral preferences move to standing directives / values framing per the milestone's own three-layer design.
- Add a canary comparison: run the same 5-10 real conversation snippets through both models pre-cutover and diff the judgment, not just the JSON shape.

**Warning signs:**
- Live canary turns feel "stiffer" or more rule-quoting than the Gemini baseline.
- Eval harness (`scripts/eval_tick_brain.py`) fixtures that passed under Gemini regress under Sonnet on the *same* judgment calls (not just token/format differences).
- Amit reports Klaus asking permission or reciting a rule instead of just acting/observing.

**Phase to address:**
Phase 30.5 (light pass, before cutover) → Phases 31-33 (deep rewrite, as directives/memory/occasion machinery replaces the checklists). Verify: eval harness score parity or improvement on existing fixtures post-cutover, plus a qualitative live-canary read.

---

### Pitfall 3: Prompt-Caching Token Fields Aren't Captured, So the New Cost Tripwire Is Built on Wrong Numbers

**What goes wrong:**
`core/llm_client.py` currently reads only `input_tokens`/`output_tokens` from the Anthropic response. Once `cache_control` ships, Anthropic reports `cache_read_input_tokens`/`cache_creation_input_tokens` as *separate* fields — cache reads are billed at ~10% of input price, cache writes at a ~1.25x premium. If these fields aren't extracted, `compute_cost` either double-counts (treating cached tokens as full-price input) or under-counts (dropping them entirely), and the Phase 30.5 daily-spend tripwire — the safety net meant to catch a prompt bug before it becomes a surprise bill — alerts on numbers that don't match the actual Anthropic invoice.

**Why it happens:**
Prompt caching is usually added purely for cost/latency and its billing-field implications on existing metering code get missed — "add `cache_control`, ship it" without touching the usage-parsing layer that was written before caching existed.

**How to avoid:**
Extract `cache_read_input_tokens`/`cache_creation_input_tokens` in the Anthropic backend response handling; extend `compute_cost(model, in, out, cache_read=0, cache_write=0)` and `MODEL_PRICING` with cache rates; add the two counters as additive Firestore fields on `LLMUsageStore.record`/`summary`. Verify against the real Anthropic console, not just unit-test the arithmetic.

**Warning signs:**
- `LLMUsage` cost sum diverges from the Anthropic billing console by more than ~10%.
- `cache_read_input_tokens` stays 0 on turn 2 of a multi-turn conversation where the system prompt should be cache-stable.
- Daily-spend tripwire fires (or fails to fire) inconsistently with actual observed spend.

**Phase to address:**
Phase 30.5, same deploy as caching itself — never ship `cache_control` without the metering extraction in the same change. Verify: after deploy, a real two-turn Telegram exchange shows `cache_read_input_tokens > 0` on turn 2 and LLMUsage cost matches the console within ~10%.

---

### Pitfall 4: Evolving the System Prompt Across Phases 31-33 Silently Kills the Cache Hit Rate

**What goes wrong:**
Anthropic's cache prefix hierarchy is tools → system → messages, and a cache breakpoint looks back at most 20 blocks from where it's set. Phases 31-33 each add new brain-direct tools (`set_standing_directive`, `list_standing_directives`, `cancel_standing_directive`, `forget_memory`, `get_recent_decisions`) and new always-injected prompt blocks (`{standing_directives}`, ambient-recall block, conversation tail, `training_reality`). Any tool-schema change invalidates the *entire* downstream cache (tools sit at the bottom of the hierarchy), and any volatile content placed before the stable prefix (rather than after it, as the existing `{today_date}`/`{current_time}` ordering already respects) turns every call into a fresh cache write with no read — silently paying the 1.25x write premium on every single turn while believing caching is "on."

**Why it happens:**
Each phase ships its own prompt/tool addition in isolation and the ordering discipline (volatile-content-last, tools-append-only) that Phase 30.5 established gets forgotten by Phase 33 unless it's an explicit, re-checked invariant — not a one-time decision.

**How to avoid:**
Treat "new tools are appended, never reordered or renamed; volatile content stays after the stable prefix" as a standing invariant checked at every phase, not a Phase 30.5-only concern. Add a lightweight assertion/test that renders the system prompt with a maximal fixture and checks byte-stability of the prefix across two consecutive calls with only the volatile suffix changing.

**Warning signs:**
- `cache_read_input_tokens` drops toward 0 after a phase deploy that touched prompts or tool schemas.
- Per-turn latency/cost creeps up phase-over-phase without a corresponding feature-value increase.

**Phase to address:**
Phases 31, 32, 33 (each phase that touches the always-on prompt or tool registration must re-verify cache stability, not just Phase 30.5). Verify: cache-hit rate metric (from the new counters in Pitfall 3) stays flat or improves phase-over-phase.

---

### Pitfall 5: Standing Directives Veto by Coarse Topic Match, Over-Suppressing Unrelated Proactive Speech

**What goes wrong:**
A directive like "stop nagging about training while I'm in France" is meant to suppress *training-scheduling* nudges, not every proactive message. If the Step-0 "STANDING ORDERS" veto in `autonomous_triage.md` is evaluated as a blanket "does an active directive exist that's vaguely related to this occasion" check rather than a topic-scoped one, Klaus can go silent on genuinely unrelated things — a supplement-adherence nudge, a calendar conflict, a health-page anomaly — for the full duration of a directive that was never meant to cover them. This is the inverse failure of the bug the milestone is fixing (the France case was *under*-suppression; a sloppy fix trades it for *over*-suppression), and it's harder to notice because silence looks like correct judgment.

**Why it happens:**
The cheapest implementation of "inject directives, let the model veto" is a single coarse gate rather than a scoped one, especially under Groq's tight per-request token budget (Pitfall 11) which pressures the triage prompt to stay terse — terseness pushes toward blunter instructions ("if any active directive might apply, skip") rather than precise scoping.

**How to avoid:**
Write the Step-0 veto instruction to require the directive's *stated scope* to plausibly cover the *specific occasion content*, not just co-occur temporally — e.g. "only suppress topics the directive's text actually addresses; an unrelated occasion (supplement reminder, calendar conflict) is not covered by a training-specific directive." Cover this explicitly in eval fixtures: not just "directive present → suppress" but "directive present, unrelated topic → do NOT suppress."

**Warning signs:**
- A multi-day stretch of zero autonomous outreach that correlates with an active directive whose text is topically narrower than the silence suggests.
- Eval harness only has positive-suppression fixtures, no negative (non-suppression) fixtures for the same directive.
- Amit says "why didn't you mention X" about something outside what he thought he'd muted.

**Phase to address:**
Phase 31 (veto instruction design) with negative-case eval fixtures added in Phase 35. Verify: `get_recent_decisions` (Pitfall 9's trust tool) shows triage reasoning that names the specific directive scope it applied, not a blanket "directive active."

---

### Pitfall 6: Casual Venting Gets Captured as a Permanent Standing Directive

**What goes wrong:**
`smart_agent.md`'s capture rule fires `set_standing_directive` on "a lasting wish about Klaus's behavior," triggered in part by phrases like "I already told you…". Conversational venting ("ugh, don't ask me about running today") is linguistically identical to a genuine standing order but semantically a one-off mood, not a policy. Without a default expiry or a distinction between "durable preference" and "today only," these get captured as indefinite directives (`expires_at: null`), permanently narrowing Klaus's proactive range based on a single bad day — and because directives are injected verbatim into every reasoning path, one over-captured directive from a bad Tuesday quietly reshapes months of behavior.

**Why it happens:**
The capture instruction optimizes for recall (never missing a real directive, since Amit explicitly complained about *under*-capture in the France case) without a symmetric cost model for false-positive capture. LLM-based classification of "durable vs. momentary" from a single utterance is genuinely hard, and the fast path (dateutil-parsed `expires_at` from explicit phrases) only helps when Amit states a timeframe explicitly.

**How to avoid:**
- Default new directives with no explicit timeframe to a bounded default expiry (e.g. a few days) rather than indefinite, unless the utterance clearly signals permanence ("always", "from now on", "every time").
- One-line ack on capture (already planned) doubles as a correction surface — but also add a `list_standing_directives` nudge in the reflection digest so Amit periodically sees what's accumulated and can prune stale ones, not just discover them by their effects.
- Track directive count over time; flag unusually rapid accumulation as a signal to tighten the capture prompt.

**Warning signs:**
- Directive store grows a document per emotionally charged message rather than per deliberate instruction.
- `expires_at: null` directives dominate the store after a few weeks.
- A directive's `context` quote (the triggering message) reads like a complaint, not an instruction.

**Phase to address:**
Phase 31. Verify: eval fixture pairing a vent-style message against a genuine-directive message, asserting different capture behavior (or same capture but with a short default expiry on the vent-style one).

---

### Pitfall 7: Ambient Recall Puts a Network Call on the Chat Critical Path, Recreating the Blocking-Gather Incident Class

**What goes wrong:**
Phase 32's "auto-recall on every chat turn" adds an embedding call + Pinecone query in front of *every* message, on the same request path that known incident #2 already broke once (blocking gather starving a Telegram send → 500s). If the embedding call is issued synchronously inside the async handler (the Gemini SDK's known sync-call quirk in this codebase), or if the Pinecone query has no timeout, a single slow/degraded call now stalls every chat turn, not just a weekly cron — a strictly worse blast radius than the incident it rhymes with, because this path fires on every single message instead of once a week.

**Why it happens:**
"Best-effort, timeout-guarded" is stated as a design intent in the plan/review (B1), but intent isn't enforcement — the actual failure mode requires an explicit `asyncio.wait_for`-style timeout wrapper and a verified-empty fallback, and it's easy to wire the happy path (recall succeeds, inject block) without ever exercising or testing the timeout/failure path before it ships.

**How to avoid:**
Wrap the embedding + Pinecone call in a short timeout (2-3s, per the review's own number) with a guaranteed empty-block fallback on any exception or timeout — never let it raise into the turn. Ensure the embedding call itself runs off the event loop (`run_in_executor`) if the SDK path is synchronous, mirroring the existing gather-isolation pattern (`autonomous.py`). Add a test that forces the recall call to hang/error and asserts the turn still completes and replies within the normal latency budget.

**Warning signs:**
- Chat reply latency has a new bimodal distribution (fast when recall hits, slow when it doesn't) instead of a flat best-effort profile.
- Pinecone or embedding errors show up correlated with Telegram `TimedOut` errors, the same signature as the original weekly-review incident.

**Phase to address:**
Phase 32. Verify: chat-turn latency test with a simulated Pinecone timeout/error still completes within the normal SLA; p50/p95 reply latency tracked in the Phase 30.5+32 live-canary checklist against the known ~34s baseline.

---

### Pitfall 8: Ambient Memory Silently Poisons Judgment With Stale or Contradicted Facts

**What goes wrong:**
Once memory is auto-injected rather than deliberately recalled, a stale or superseded fact (a training goal that changed, a plan that's no longer active) surfaces every turn as ambient truth with no mechanism forcing it to be revisited — this is the documented "memory poisoning" failure class for agents with persistent auto-injected memory (OWASP ASI06): a wrong fact gets treated as verified, referenced again, and because it keeps getting re-surfaced by top-k similarity it can reinforce itself rather than fade. Unlike the tool-gated `recall` (where a bad hit is one turn's problem), ambient injection means a bad memory taints *every* turn's context until something explicitly removes it.

**Why it happens:**
The plan already includes score-thresholding, recency-weighting, and a `forget_memory` tool plus a reflection contradiction-flag step — but these are mitigations that must actually run and actually catch things, not just exist. It's easy to ship the retrieval half (auto-inject top-k) and treat the hygiene half (contradiction detection, active pruning) as a nice-to-have that never gets exercised against real stale data because nobody manufactures a stale-fact fixture to test it.

**How to avoid:**
- Ship `forget_memory` and the reflection contradiction-flagging step in the *same* phase as auto-recall, not as a follow-up — an ambient-injection feature without an ambient-correction feature is the poisoning setup.
- Build at least one deliberate stale-fact fixture (a memory that's true-then-false across two dates) and assert the reflection step flags or the recency-weighting demotes it.
- Recency-weight aggressively for facts with a natural shelf life (goals, plans, locations) vs. facts that don't (preferences, persistent traits).

**Warning signs:**
- Klaus references an outdated goal/plan/location in a proactive message after it's been explicitly superseded in conversation.
- `forget_memory` has zero invocations weeks after ship — either nothing's ever stale (unlikely) or the hygiene loop isn't actually surfacing candidates.

**Phase to address:**
Phase 32 (ship retrieval + hygiene together). Verify: stale-fact fixture test; live check that a corrected fact stops surfacing within one reflection cycle (24h) of correction.

---

### Pitfall 9: Judgment-Driven Silence and Infra Failure Are Indistinguishable Without Explicit Status Tracking

**What goes wrong:**
The occasion cascade's entire premise is that silence can be *correct* (Klaus judged nothing worth saying). But a Layer-1/2 LLM error, a Groq outage, or a bug in the situation assembler also produces silence. Without the planned `status: sent|skipped_by_judgment` distinction actually wired through and actively monitored, a real outage looks identical to healthy autonomy — for a milestone whose core deliverable is "trust the silences," an unmonitored failure mode that mimics the intended feature is uniquely dangerous: it can run for days before anyone notices, exactly like known incident #3 (weeks of silent Groq→paid fallback) but now with the failure being *invisible by design* rather than just unmonitored.

**Why it happens:**
"Failure-skip ≠ judgment-skip" is stated as a design principle, but the natural implementation path (nightly's plain-text fallback path already covers total-failure) doesn't automatically extend monitoring/alerting — the state field can exist in Firestore without anything ever reading it to distinguish a healthy quiet week from a broken one.

**How to avoid:**
- Wire the `status` field through nightly/morning/tick consistently, and add a heartbeat check: an anomalous *run* of `skipped_by_judgment` (or missing status entirely) beyond a threshold triggers an alert distinct from the existing consecutive-failure counter.
- Ship the `get_recent_decisions` introspection tool (already planned, C1) early enough that Amit — and Klaus himself — can audit "why no message yesterday" on demand rather than only via Firestore archaeology.
- Never let a caught exception in the cascade silently resolve to the same code path as a genuine "nothing to say" verdict.

**Warning signs:**
- A multi-day quiet stretch with no corresponding entry in `TickLogStore`/`OutreachLogStore` explaining the judgment (as opposed to a quiet stretch where each day has a recorded "considered and skipped" reasoning).
- `get_recent_decisions` returns empty or errors during a quiet stretch instead of showing skip reasoning.

**Phase to address:**
Phase 33 (status wiring + heartbeat anomaly check) with `get_recent_decisions` landing in Phase 33 or 35 per the plan. Verify live canary: ask Klaus "why didn't you message me yesterday?" and confirm he answers from actual logged reasoning, not a generic non-answer.

---

### Pitfall 10: Proactive Side Effects (Calendar Writes, Write-Back Rows) Aren't Idempotent Under Retry

**What goes wrong:**
Phase 33's agentic Layer 2 may create tomorrow's training event when a directive grants it; Phase 34 mechanically write-backs planned rows to `TrainingLogStore` on every calendar create/move/delete. If compose succeeds but delivery fails (push errors, Telegram mirror off, partial dual-channel delivery), `OutreachLogStore.append` correctly doesn't log (per the existing D-10 invariant) — but the *calendar write and the write-back row already happened*, so the next occasion or tick, seeing no outreach log entry, can re-compose and re-create a *second* event and a *second* planned row for the same day. The mechanical write-back (designed specifically to "survive model disobedience") ironically becomes the thing duplicating state if it isn't itself guarded.

**Why it happens:**
D-10's outreach-log-gated-on-delivery-success invariant was designed to prevent double-*messaging*, not double-*acting* — the calendar/write-back side effect happens inside compose, upstream of the delivery gate, so the two systems (delivery idempotency vs. action idempotency) aren't the same guard and it's easy to assume one covers the other.

**How to avoid:**
Before any directive-gated proactive calendar create, check for an existing planned row / Training-calendar event for that date+slot first (check-before-act / "list-before-write"), using Phase 34's write-back rows as the natural dedup key. This makes the mechanical write-back layer double as its own idempotency guard rather than a separate concern bolted on later.

**Warning signs:**
- Two Training-calendar events or two `TrainingLogStore` planned rows for the same `{date}_{slot}` key.
- A delivery failure in `scheduled_message.py` correlated with a duplicate calendar event appearing on the next tick.

**Phase to address:**
Phase 33/34 (the check lands naturally once Phase 34's write-back rows exist as the dedup key; sequence the idempotency check with or immediately after write-backs ship). Verify: integration test — simulate compose-succeeds/delivery-fails, then re-run the next tick, assert only one event/row exists.

---

### Pitfall 11: Prompt Growth From Phases 31-32 Re-Triggers the Groq Silent-Fallback Failure Mode via a New Root Cause

**What goes wrong:**
Known incident #3 was a request-*shape* bug, already understood and presumably fixed. But the *same observable symptom* (triage silently routes to paid fallback, defeating cost gating) can recur through an entirely different root cause: simple token growth. Verified current triage input is ≈3.2-3.7K tokens against a `TICK_BRAIN_MAX_TOKENS=2048` budget (~5-5.7K tokens/call) inside Groq's ~6-8K TPM per-request admission window. Phase 32 adds conversation tail (~1.2K), standing directives, and `training_reality` — pushing typical calls toward ~7-8K tokens/call, leaving as little as ~0.3K headroom before the *same* silent-fallback symptom reappears, this time from prompt bloat rather than a code bug. Groq's free tier also enforces a *separate*, independent daily cap (~200K tokens/day per the reviewed math) that realistic volume already brushes against before Phase 32's additions.

**Why it happens:**
Each phase adds a gather/context block in isolation and reasons about its own token cost, but nobody re-sums the *combined* triage input against Groq's admission ceiling until it's already breached in production — the same "it's just one more field" trap that caused the original per-message hardcoded-user-id and Groq-shape incidents in this codebase.

**How to avoid:**
- Make "context-only in `_is_empty_signals`" a stated invariant for *every* new gather (conversation tail, standing directives, training_reality, location) — not just the one the plan explicitly called out — so routine chat activity doesn't force 43 Groq calls/day regardless of whether anything's actually worth triaging.
- Add a token-budget guard test asserting the maximal rendered triage prompt (all gathers populated) stays under the verified GPT-OSS-120B per-request budget — encode the actual number, don't estimate it.
- Add a daily Groq token ledger in the heartbeat, alerting on approach to the 200K/day cap *and* on any `tick_fallback` purpose volume spike (the direct symptom of admission-cap breach).
- Actively shrink `autonomous_triage.md` (target ≤half its current 11KB) as directive/memory context is added, so total input doesn't monotonically grow phase-over-phase.

**Warning signs:**
- `tick_fallback` purpose entries in LLMUsage increase after a Phase 32 deploy with no corresponding Groq outage.
- Groq daily token ledger approaches 200K on ordinary (not unusually busy) days.
- Rendered triage prompt size creeps upward phase-over-phase without a corresponding deletion.

**Phase to address:**
Phase 32 (context-only invariant, ledger, budget guard test) with continuous vigilance through Phase 35. Verify: token-budget guard test in CI; ledger alert unit test fires at the daily threshold; no `tick_fallback` spike in the 3-4 day post-deploy monitoring window.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Injecting standing directives into 3 legacy composers (nightly/morning/weekly) as an interim step before Phase 33 unifies them into the cascade | Fixes the France case immediately without waiting for the full cascade rework | Three separate injection points to keep in sync until Phase 33 lands; a directive fix applied to one composer and forgotten in another reproduces the exact bug class this milestone fixes | Only for the span between Phase 31 ship and Phase 33 cutover — must not survive past it |
| `OCCASION_CASCADE` flag running legacy and cascade paths in parallel | Safe, reversible rollout with no Cloud Scheduler changes | Two implementations of nightly/morning to maintain; a routine `--set-env-vars` deploy (documented gotcha in this repo) can clobber the flag back to a default state mid-rollout | Only for the explicit 3-4 day monitoring window in the plan; delete the legacy path and the flag immediately after cutover, not "eventually" |
| Tick-brain fallback chain has a two-hop legacy path (`TICK_BRAIN_FALLBACK_*` → last-resort `SMART_AGENT_*`) | Avoids a hard failure if the new fallback env vars are ever unset | A silent third state (Groq fails → new fallback also fails → lands on Sonnet anyway) that looks identical to Pitfall 1 if untested | Acceptable only if the last-resort hop is explicitly tested and alarmed on, never assumed unreachable |
| Weekly review stays a legacy composer (own gather+compose) while everything else cascades (E1, undecided in the plan) | Avoids touching the surface with the only prior 500-incident history mid-milestone | A second judgment implementation with its own drift risk, and an inconsistent mental model ("does Klaus decide, or does the template decide?") that undermines the milestone's own "one cascade" narrative | Acceptable only if explicitly logged as a deferred decision in REQUIREMENTS.md — never silently left ambiguous |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| Anthropic API (`claude-sonnet-5`) | Sending non-default `temperature`/`top_p`/`top_k` or an explicit `thinking: {budget_tokens}` block carried over from the old client config → 400 errors | Omit these entirely for Sonnet 5 (adaptive thinking is default when omitted); audit the Anthropic backend path in `llm_client.py` specifically for these params before cutover |
| Anthropic prompt caching | Placing `cache_control` after volatile content, or below a 1,024-token minimum prefix — cache silently never hits, no error is raised | Cache only the byte-stable prefix (identity/persona/tools), keep volatile content (`{today_date}`, `{current_time}`) strictly after it; verify prefix length exceeds the model minimum |
| Groq (OpenAI-compat) | Using a bare model name (`gpt-oss-120b`) instead of the namespaced id (`openai/gpt-oss-120b`) → 404; assuming the daily cap (RPD) is enforced/visible the same way as TPM — Groq doesn't expose RPD in response headers | Always use the namespaced model id; track daily token/request usage yourself (the planned ledger) rather than relying on provider-side visibility |
| Groq rate limits | Optimizing only for the daily token cap and missing that RPM/TPM-per-request are independent, first-to-trip limits | Test against the tightest of RPM/TPM/RPD, not just the most publicized one (daily cap) |
| Pinecone (ambient recall) | Treating retrieval quality as fixed once tuned — precision silently degrades as the corpus grows and the top-k/score-threshold no longer match the collection's new size/composition | Periodically re-validate score-threshold and k against corpus growth; the plan's "ambient-recall quality eval" (deferred, listed as a v6.1 candidate) should be pulled forward if stale injections show up in practice |
| Cloud Run deploy (`deploy.yml --set-env-vars`) | Adding a new flag/env var (`OCCASION_CASCADE`, `TICK_BRAIN_FALLBACK_*`, `KLAUS_DAILY_COST_ALERT`) without confirming `--set-env-vars` merge-vs-clobber semantics for that specific var | Verify every new env var survives a routine deploy by checking the live Cloud Run revision config post-deploy, not just the workflow YAML |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Ambient recall on every chat turn | Latency becomes bimodal; occasional Telegram `TimedOut` correlated with Pinecone/embedding slowness | Timeout-guarded, off-event-loop, best-effort with empty fallback (Pitfall 7) | The first time Pinecone or the embedding API has a slow day — not a scale threshold, a reliability threshold |
| System-prompt/context growth across Phases 31-33 (directives + tail + memory + training_reality all injected together) | Per-turn cost and latency creep upward phase-over-phase; cache hit rate drops (Pitfall 4); Sonnet's attention to any single instruction degrades as unrelated context grows | Token-budget guard tests per phase; active shrinking of `autonomous_triage.md`/`smart_agent.md` as new blocks are added, not just additive growth | Somewhere past ~15-20K tokens of always-on context, instruction-following reliability and cache economics both degrade — track, don't wait to feel it |
| Standing-directive block growing unbounded over months | Starts free; after months of accumulated directives it's a meaningful, permanent tax on every single call (chat, triage, compose) forever | Bounded default expiry on ambiguous captures (Pitfall 6); periodic surfacing/pruning via reflection digest | Becomes noticeable once directive count reaches roughly a dozen+ simultaneously active — no natural cap exists today |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Conversation tail sent to Groq triage (accepted privacy tradeoff per the plan) with no scrubbing | An accidentally pasted secret/token in chat gets forwarded verbatim to a third-party free-tier provider on every subsequent tick until it ages out of the tail window | Apply the same secret-denylist discipline already used in `self_inspect.py`'s source-reading tools to the conversation-tail renderer, or explicitly document the accepted residual risk |
| `forget_memory` is a brain-direct, no-confirmation destructive tool | A manipulated or misleading memory content (indirect prompt injection via a stored fact) could induce the model to delete *correct* memories, or conversely a false "forget this" instruction embedded in ingested content (chat logs, forwarded emails) could get executed without human review | Log every deletion (what was deleted, why, which turn triggered it) for audit/undo; consider requiring the deletion target to have been explicitly surfaced to Amit in the same turn rather than silently actioned from ambient context |
| `set_standing_directive` captures from any first-person-seeming chat content with no source discrimination | Indirect prompt injection risk: content Klaus reads on Amit's behalf (an email body, a Notion page, a chat-log ingestion) that *contains* imperative-sounding text ("always do X") could theoretically be captured as if Amit said it, if the capture rule isn't scoped to genuine live Telegram/Hub chat turns | Scope directive capture explicitly to direct conversational turns from Amit, never to tool-read content (Gmail, Notion, ingested chat logs) flowing through the same context window |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Silence has no explanation surface outside chat | Amit has to *think to ask* "why didn't you message me" to get `get_recent_decisions` value; the trust feature only works if he remembers it exists | Note in Phase 33/35: at minimum mention the introspection capability once in onboarding/SELF.md; Hub visibility for directives + recent decisions is a natural v6.1 follow-up already flagged in the review |
| Overcorrection after one noisy reaction-pairing signal | Reflection's reaction-pairing (C2) could swing calibration hard from a single ambiguous reaction (e.g., a delayed reply misread as "ignored"), producing visibly different behavior the next day — the opposite of the "no scripted acknowledgments, calibrated gradually" philosophy | Weight reaction-pairing signal by volume/consistency over multiple days before it materially shifts self-proposed directives, not a single-data-point swing |
| Nightly plain-text infra-fallback reads as a different voice than cascade-composed messages | On the rare day it fires, the message looks broken/off-brand precisely because it's exercised so rarely it's never been proofread against current voice | Periodically exercise the fallback path deliberately (not just as dead code) — e.g. as part of the Phase 35 eval sweep — so it doesn't silently drift out of sync with the cascade's voice |

## "Looks Done But Isn't" Checklist

- [ ] **Directive expiry:** Verify directives with a past `expires_at` are actually excluded from *every* injection path (chat, triage, all legacy-composer interim injections, the future unified cascade) — not just the primary chat path that got tested first.
- [ ] **Ambient-memory hygiene:** Verify `forget_memory` and the reflection contradiction-flagging step actually run against a real stale-fact fixture and change behavior — not just that the tool/step exists in code.
- [ ] **Proactive-write idempotency:** Verify a forced compose-succeeds/delivery-fails/retry sequence does NOT produce two calendar events or two `TrainingLogStore` planned rows for the same date+slot.
- [ ] **Prompt-caching metering:** Verify `LLMUsage` shows non-zero `cache_read_input_tokens` on a real second turn and the summed cost matches the Anthropic console within ~10% — not just that the fields exist in the schema.
- [ ] **Fallback chain correctness:** Verify a forced Groq error in staging logs a `gemini-3.5-flash` model string in `tick_fallback` purpose entries, never `claude-sonnet-5`.
- [ ] **Eval fixture coverage:** Verify the new fixtures include negative cases (directive active, but topic unrelated → should NOT suppress; occasion fires, nothing to say → judged skip, not error) alongside the positive-suppression cases — positive-only coverage misses Pitfall 5's exact failure mode.
- [ ] **Groq token-budget guard:** Verify the guard test encodes the *actually verified* GPT-OSS-120B per-request TPM budget from Groq's docs/console, not the qwen-era number carried over by habit.
- [ ] **Occasion status tracking:** Verify `status: sent|skipped_by_judgment` is populated (not left null/missing) on 100% of nightly/morning runs during the monitoring window, including on failure paths.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|------------------|
| Directive over/under-suppression discovered live | LOW | Directives are designed to be reversible by construction — `cancel_standing_directive` tool or direct Firestore doc edit; no historical damage beyond the missed/unwanted messages themselves |
| Ambient memory poisoning discovered | LOW-MEDIUM | `forget_memory` + a manual reflection re-run fixes it going forward; if the bad memory shaped several days of judgment, a retroactive audit via `TickLogStore`/`get_recent_decisions` is needed to assess what it actually influenced |
| Cache-token metering found wrong post-deploy | MEDIUM | Historical `LLMUsage` entries are not retroactively correctable (the raw token split wasn't captured) — fix forward with a code change and add a reconciliation note in the cost-tripwire message rather than trying to backfill exact historical costs |
| Groq daily/per-request cap silently breached | LOW | No data loss; the ledger alert (once shipped) catches it going forward. A single bad day of extra Sonnet-fallback spend is a bounded, one-time cost, not a systemic problem once alerting exists |
| Duplicate calendar event / write-back row from a non-idempotent retry | LOW | `delete_event` handler and manual `TrainingLogStore` doc cleanup already exist; retrofit the check-before-act idempotency guard once discovered — no schema migration needed since the dedup key (date+slot) already exists from Phase 34 |
| Sonnet over-literal instruction-following regresses judgment quality | MEDIUM | Requires an actual prompt rewrite pass (not a config flip) — budget real iteration time against the eval harness fixtures, not a one-line fix |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1. Tick-brain fallback silently becomes Sonnet | Phase 30.5 | Forced Groq error in staging logs `gemini-3.5-flash`, not `claude-sonnet-5` |
| 2. Over-literal instruction-following on Sonnet | Phase 30.5 (light) → 31-33 (deep) | Eval harness parity/improvement post-cutover; qualitative live-canary read |
| 3. Prompt-caching metering gap | Phase 30.5 | `cache_read_input_tokens > 0` on turn 2; LLMUsage cost within ~10% of Anthropic console |
| 4. Cache-breakpoint churn across phases | Phases 31, 32, 33 (ongoing) | Cache-hit-rate metric flat/improving phase-over-phase |
| 5. Directive over-suppression (coarse topic match) | Phase 31 | Negative eval fixtures (directive active, unrelated topic → not suppressed) |
| 6. Directive capture false positives | Phase 31 | Eval fixture: vent-style vs. genuine-directive message → different capture/expiry behavior |
| 7. Ambient recall blocks the chat critical path | Phase 32 | Simulated Pinecone timeout still completes turn within SLA; p50/p95 latency tracked |
| 8. Ambient memory poisoning (stale facts) | Phase 32 | Stale-fact fixture flagged/demoted within one 24h reflection cycle |
| 9. Judged silence vs. infra failure indistinguishable | Phase 33 | Live canary: "why didn't you message me yesterday?" answered from real logged reasoning |
| 10. Non-idempotent proactive side effects | Phase 33/34 | Integration test: compose-succeeds/delivery-fails/retry produces exactly one event/row |
| 11. Prompt growth re-triggers Groq silent-fallback | Phase 32 (with vigilance through 35) | Token-budget guard test in CI; ledger alert unit test; no `tick_fallback` spike in post-deploy monitoring window |

## Sources

- Live codebase (`core/tick_brain.py`, `core/llm_client.py`, `core/autonomous.py`, `memory/firestore_db.py`, `memory/firestore_conversation.py`, `core/nightly_review.py`, `core/morning_briefing.py`, `mcp_tools/calendar_tool.py`, `scheduled_message.py`) as of 2026-07-17.
- Approved milestone plan: `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` (root causes, phase scoping, locked decisions).
- Verified critical review: `~/.claude/plans/mellow-puzzling-nest.md` (cost landmines A1-A4, reliability B1-B3, trust C1-C2, subtraction audit G1-G4 — all amendments cross-checked against file:line evidence).
- Known incidents captured in `CLAUDE.md` § Invariants and project memory (`project_slow_reply_incident`, `project_weekly_review_500_incident`, `feedback_gemini_sdk`).
- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — cache hierarchy, minimum prefix length, 20-block lookback.
- [Anthropic Prompt Caching Deep Dive — gu-log](https://gu-log.vercel.app/en/posts/en-sp-112-20260313-anthropic-prompt-caching-2026-update) — breakpoint invalidation gotchas.
- [I Was Caching Wrong This Whole Time — DEV Community](https://dev.to/yurukusa/i-was-caching-wrong-this-whole-time-anthropic-academy-part-1-1hba) — cache-only-stable-content pitfall.
- [Memory and context poisoning — WorkOS](https://workos.com/blog/ai-agent-memory-poisoning) and [MintMCP](https://www.mintmcp.com/blog/ai-agent-memory-poisoning) — OWASP ASI06 memory/context poisoning pattern, stale-cache-as-fact failure mode.
- [Groq API Free Tier Limits 2026 — Grizzly Peak Software](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb) and [Groq Rate Limits — GroqDocs](https://console.groq.com/docs/rate-limits) — RPM/TPM/RPD independent-cap gotcha, no RPD header exposure.
- [How to Build Idempotent Tool Calls for AI Agents — Chanl](https://www.channel.tel/blog/idempotent-tool-calls-agent-retry-safety) and [The Idempotency Crisis: LLM Agents as Event Stream Consumers](https://tianpan.co/blog/2026-04-19-llm-agents-event-stream-idempotency) — check-before-act / idempotency-key patterns for agent side effects.
- [LLM Prompt Format 2026 — futureagi.com](https://futureagi.com/blog/llm-prompts-best-practices-2025/) and [Claude 3.5 Sonnet Changed — DEV Community](https://dev.to/clawgenesis/claude-35-sonnet-changed-my-system-prompt-stopped-working-heres-what-i-learned-nk) — cross-model instruction-following drift patterns.
- [The Double-Edged Sword of ChatGPT's Memory — Medium](https://medium.com/@nirajkvinit/the-double-edged-sword-of-chatgpts-memory-promise-pitfalls-and-practical-fixes-298359dcb1a5) — ambient memory over-capture / user-instruction-ignored pattern precedent.

---
*Pitfalls research for: Klaus v6.0 "Klaus Becomes an Agent" — standing directives, ambient memory, judgment-driven proactivity, brain-model migration, free-tier LLM dependency*
*Researched: 2026-07-17*
