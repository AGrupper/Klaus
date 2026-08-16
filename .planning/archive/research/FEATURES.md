# Feature Research

**Domain:** Agentic self-governance for a personal AI assistant — standing directives, ambient memory, judgment-driven proactivity
**Researched:** 2026-07-17
**Confidence:** MEDIUM-HIGH (patterns cross-verified across 3+ independent sources per finding; Klaus-specific complexity estimates are HIGH confidence from direct codebase knowledge)

---

## Context

This research covers only the three NEW capability areas in v6.0 Phases 31–33: standing
directives, ambient/auto-recall memory, and judgment-driven proactivity (occasion cascade).
Existing capabilities (Pinecone RAG via explicit `recall` tool, autonomous tick engine with
repeat-suppression, template-composed briefings, cost metering) are assumed and not
re-researched. Findings are grounded in named, verifiable systems: OpenAI ChatGPT memory,
Anthropic Claude memory + memory tool, MemGPT/Letta, Zep/Graphiti, LangGraph/LangMem, and the
Stanford "Generative Agents" (Park et al.) memory-stream architecture, plus arXiv literature on
memory conflict resolution, forgetting, provenance, and notification-budget design. This
document replaces the prior (v5.0 Klaus Hub) FEATURES.md, which is superseded — see git history
if that research is still needed.

## Feature Landscape

### Table Stakes (Users Expect These)

Features any credible "agent with memory and proactivity" is expected to have. Missing these
makes v6.0 feel like a half-built version of what ChatGPT/Claude already ship for free.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Explicit directive capture from natural language ("remember to stop nagging about X") | ChatGPT ("remember that...") and Claude ("add to memory that...") both support instant, user-triggered memory writes with immediate confirmation — this is the baseline UX for any memory feature | LOW | Klaus already has the pattern (tool-calling agent); `StandingDirectiveStore` + a `set_directive` tool is a straightforward Firestore-store addition mirroring `TaskStore`/`HabitStore` |
| Preference/directive vs. fact distinction | Universally modeled: MemGPT/Letta separates "core memory" (persona/user facts, pinned) from "archival memory" (retrieved history); the broader literature explicitly frames preferences as "durable assertions about how the user wants the agent to behave... standing instructions the agent applies to shape action," distinct from facts the agent merely reasons over | LOW-MEDIUM | Klaus's split maps cleanly: `StandingDirectiveStore` (behavioral orders) is architecturally distinct from Pinecone `fact`/`chat` kinds (evidence) — the milestone plan already gets this right by design |
| Provenance/source tagging on every memory write | Zep tracks full transaction lineage (ingestion time vs. valid time); the personal-agent memory literature is explicit that "a user explicitly saying 'remember X' is straightforward, while an agent inferring X from repeated conversations is far more sensitive" — production systems tag source type, timestamp, authoring agent, confidence | LOW | Directives Klaus proposes himself (learning loop) MUST be flagged distinctly from directives Amit stated verbatim — this is the difference between "Amit said" and "Klaus inferred," and it directly gates the one-line veto step already locked into the plan |
| Recency-wins as the default conflict-resolution rule | "The convention in most modern memory systems is that the most recent fact wins... replacing an old preference with a conflicting new one is correct conflict resolution, not a deletion error" (arXiv 2606.01435, "Don't Ask the LLM to Track Freshness") | LOW | Applies directly to directive supersession — no need for the brain to "judge" which of two contradictory directives is right; last-write-wins with the old one archived (not silently deleted) for audit |
| Directive expiry / TTL, not permanent-forever | Every reviewed memory system (Letta, Zep, the aging-policy literature) treats unbounded retention as a bug: "retention windows (TTL) should expire memory unless it's still useful," with importance/criticality determining whether something ages out or persists | LOW-MEDIUM | Directly addresses the stated milestone example — "stop nagging about training while I'm in France" needs either an explicit end condition or a default TTL + renewal nudge, or it silently outlives its purpose and Klaus starts under-serving Amit for no reason |
| Ambient auto-injection of relevant memory without an explicit tool call | Both ChatGPT ("reference chat history": "the system selects memory relevant to your prompt and injects it into the model's context, like a hidden system note") and Claude.ai memory work this way by default — this is the literal definition of "ambient" vs. Klaus's current explicit `recall` tool | MEDIUM | Requires wiring the existing Pinecone recall path into every brain turn as a best-effort, timeout-guarded gather step (per plan) rather than waiting for the brain to decide to call a tool |
| Relevance/recency/importance-weighted retrieval, not pure similarity | The canonical reference (Stanford Generative Agents, Park et al. 2023) explicitly combines all three: recency (exponential decay since last access), importance (score at creation time), relevance (embedding similarity) — pure cosine-similarity retrieval is the known-inferior baseline every subsequent system improves on | MEDIUM | Klaus's existing Pinecone recall is similarity-only; ambient auto-recall for v6.0 needs at minimum a recency/importance boost on top, or it will surface stale-but-similar memories over fresh-but-differently-worded ones |
| Absolute quiet-hours / suppression honoring | Consistently framed as non-negotiable in the proactive-agent literature: "respect over reach means proactive agents must prioritize user context over their own assessments of importance... honoring quiet hours absolutely" | LOW | Already implemented (7-21 cron window); directives extend this to per-topic suppression, same principle |
| Notification/outreach budget discipline | Cross-source finding: proactive agents "collide with a hard daily ceiling of three to five notifications per user"; treating each notification as "a withdrawal from a finite account" forces honest upstream prioritization | LOW (already exists) | Klaus's repeat-suppression + tick-brain gating already implements this in spirit; occasion cascade must not regress it by turning skippable nightly/morning slots into always-send slots |

### Differentiators (Competitive Advantage)

Features that go beyond what ChatGPT/Claude/mainstream personal-agent products ship today —
genuinely rare in the surveyed literature, and where Klaus's judgment-driven design earns its
name.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Agent-proposed directives from observed reactions (reflection learning loop) | Neither ChatGPT nor Claude memory self-proposes standing behavioral rules from user reaction patterns — memory writes there are always user-initiated or extracted-from-explicit-statement. An agent that reads a 24h window, notices "Amit went quiet/annoyed after two nagging outreach attempts," and proposes its own directive is a step past every reviewed consumer system | HIGH | This is the riskiest and most novel piece — closest analog is "procedural memory" in LangMem (system-prompt-level learned routines), but no reviewed system does it via reaction-inference + human veto for a single user. The one-line veto step is the correct mitigation (matches literature's universal insistence that inferred memory needs more scrutiny than stated memory) |
| Self-explainable proactive decisions (`get_recent_decisions` introspection tool) | The explainability literature is unanimous that this matters ("as AI agents gain independent decision-making ability, the need for transparency becomes critical... real-time interpretability enables humans to understand and intervene") but is rarely implemented for consumer proactive agents — most background/notification agents are black boxes even when they stay silent | MEDIUM | Differentiator specifically because it also explains *silence* — "why didn't Klaus say anything this morning" is answerable, which almost no consumer proactive-AI product surfaces |
| Judgment-gated, fully skippable scheduled occasions (nightly/morning as "wake-ups," not scripted sends) | Nearly all personal-assistant products (ChatGPT, Claude, morning-briefing apps) treat scheduled compose slots as always-fire, template-filled. Making silence a first-class valid outcome of a real judgment cascade — not a fallback for missing data — is a genuine architectural differentiator matching the "graceful presence... silent competence" ideal described in the proactive-agent literature | MEDIUM-HIGH | Directly addresses the core value statement ("silence being a valid choice"); complexity is in Layer 2 needing a bounded tool budget so "should I speak" reasoning doesn't itself become an expensive, unbounded agentic loop |
| Bitemporal-style provenance on directive supersession (created-at vs. superseded-at, not delete-and-overwrite) | Zep/Graphiti's bitemporal model (`t'created`/`t'expired` vs. `tvalid`/`tinvalid`) is the SOTA reference for non-destructive fact evolution | LOW-MEDIUM (lightweight version only) | Full bitemporal knowledge-graph is overkill for Klaus's directive volume (single user, low cardinality) — the useful subset is: never hard-delete a superseded directive, keep it with a `superseded_by`/`superseded_at` field for the "why did you stop respecting X" question |
| Conversation continuity across the 6h Firestore reset boundary | Most consumer chat products treat "session" as a UI construct only, not a hard backend reset — Klaus's existing 6h purge is the odd one out here, so restoring continuity is closing a gap rather than a true SOTA-beating differentiator, but it's rare enough among *self-hosted* single-user agents to note | MEDIUM | Depends on ambient memory (Phase 32) carrying enough of the prior session's gist forward that the reset is invisible to Amit |

### Anti-Features (Commonly Requested, Often Problematic)

Patterns that look like reasonable extensions of directives/memory/proactivity but are
documented failure modes in the literature.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Unbounded ambient recall (inject "everything relevant-ish" every turn) | Feels safer — more context should mean fewer misses | Documented as "context window poisoning": overlapping/redundant chunks, stale-but-similar memories crowding out fresh ones, and directly inflates every brain call's token cost — conflicts with the milestone's own token-budget philosophy (SELF.md/prompt slimming, TTL caches) | Score-thresholded, recency/importance-weighted retrieval with a hard cap on injected items, timeout-guarded so a slow Pinecone call never blocks the turn (already the plan's stated design) |
| Permanent, never-expiring directives by default | Simpler to implement — "just remember it forever" | Directly causes the exact failure the milestone example warns about: a France-trip suppression directive that silently outlives the trip and starts hiding real problems (e.g., missed training) indefinitely | Default TTL or explicit end-condition capture at directive-creation time; heartbeat-style periodic re-surfacing of near-expiry directives for renewal, not silent auto-persistence |
| Silent, unflagged conflict resolution between directives or between a directive and Klaus's persona/values | Feels smoother — no friction, no "Klaus asking permission" | Loses the provenance trail the whole memory-provenance literature insists on; if Amit never sees the conflict, he can't correct a bad inference before it compounds | Flag once, then record (this is already the locked decision in PROJECT.md) — matches the "provenance metadata... calibrate confidence" pattern from the literature |
| Memory-driven validation/agreement (using stored preferences to always side with or flatter the user) | Feels warmer, more "personal," more in line with a companion persona | Directly measured: memory-enabled personalization raises LLM sycophancy from ~19.3% to 37.5–44.9% (Penn State study) — for a coaching-focused agent this is actively dangerous (Klaus's whole v4.0 value is "volunteers structural critique," not validation) | Use stored preferences for style/logistics/scheduling, never as license to suppress independent judgment — matches Klaus's existing "no fabrication," "recommend-not-rewrite" coaching philosophy directly |
| Optimizing for outreach volume / treating "ticks that produced a message" as the success metric | Natural instinct when building an eval harness — more proactive touches feels like more value delivered | Named explicitly as a "vanity metric": "notifications sent... unconsciously optimizes for the exact behavior (dismissals) that predicts churn three weeks later"; a hard 3–5/day attention ceiling exists regardless of how good the content is | Eval harness (Phase 35) should score judgment quality and acted-on/positive-reaction rate, not raw tick-to-message conversion — silence on a correctly-judged quiet day should score as a *win*, not a null result |
| Full LLM-managed freshness/conflict tracking (asking the brain "which of these two memories is current?" at read time) | Seems like the "smart" solution — let the reasoning model sort it out | Explicitly shown to be unreliable and wasteful compared to a deterministic recency-wins rule ("Don't Ask the LLM to Track Freshness," arXiv 2606.01435) — burns tokens and judgment budget on a solved problem | Deterministic supersession logic in the store layer (same pattern Klaus already uses for `core/projection.py` — deterministic pure functions, brain frames but never computes) |

## Feature Dependencies

```
StandingDirectiveStore (durable behavioral orders, Phase 31)
    └──requires──> Step-0 triage veto wired into every reasoning path (Phase 31)
                       └──enhances──> Occasion cascade judgment (Phase 33)
                                          (directives are load-bearing input to "should I speak")

Reflection learning loop / self-proposed directives (Phase 31)
    └──requires──> StandingDirectiveStore
    └──requires──> 24h conversation-window read + reaction pairing (existing reflection cron, extended)
    └──requires──> Provenance flag distinguishing "Amit-stated" vs "Klaus-proposed" directives
                       └──requires──> One-line human veto step before a proposed directive activates

Ambient auto-recall (Phase 32)
    └──requires──> Existing Pinecone recall infra (already built, v1.0)
    └──requires──> Relevance + recency/importance scoring (new — current recall is similarity-only)
    └──requires──> Timeout guard (best-effort; must never block the turn)
    └──enhances──> Conversation continuity across the 6h Firestore purge boundary

Conversation continuity past 6h reset (Phase 32)
    └──requires──> Ambient auto-recall (carries prior-session gist forward)

Memory hygiene / forget_memory (Phase 32)
    └──requires──> Provenance + timestamp metadata on Pinecone writes (partially exists; may need extension)
    └──conflicts-with──> Unbounded ambient recall (hygiene is the release valve that keeps ambient
                          recall from silently accumulating stale/poisoned context over months)

Occasion cascade — judgment-driven proactivity (Phase 33)
    └──requires──> StandingDirectiveStore + Step-0 veto (Phase 31)
    └──requires──> Ambient/unified situation — conversation tail + training_reality (Phase 32)
    └──enhances──> get_recent_decisions introspection tool (self-explainability)
                       └──requires──> Occasion cascade decisions being logged with rationale, not just outcome

Self-proposed directives (learning loop) ──enhances──> Step-0 veto precision over time
    (each accepted proposal sharpens future suppression judgment without new code)
```

### Dependency Notes

- **Occasion cascade requires both directives (31) and unified situation (32):** the research is
  consistent that judgment about *whether to speak* needs both a durable behavioral constraint
  layer (directives) and enough situational memory to apply it correctly — this matches the
  milestone's own phase ordering (31 → 32 → 33) and is not something to reorder.
- **Reflection learning loop requires provenance before it requires anything else:** every
  reviewed system treats inferred/agent-generated memory as needing more scrutiny than
  user-stated memory. If the "Klaus-proposed" flag isn't in place from day one of Phase 31, the
  veto step has nothing reliable to gate.
- **Memory hygiene conflicts with (i.e., is the necessary counterweight to) unbounded ambient
  recall:** these aren't sequential dependencies but a design tension — shipping ambient
  auto-recall (32) without `forget_memory` in the same phase risks exactly the stale-memory
  poisoning failure mode documented in the RAG-poisoning and context-window-poisoning
  literature. They should land together, not be split across phases.
- **Self-explainability depends on the cascade logging rationale, not just firing/not-firing:**
  `get_recent_decisions` is only useful if a "decided not to speak" event is logged with a
  reason string, same shape as a "decided to speak" event — this is a data-model requirement on
  Phase 33, not a Phase 33.5 nice-to-have.

## This Milestone vs. Defer

Adapted from standard MVP framing to fit a subsequent-milestone, phase-scoped project (v6.0 is
already phase-mapped in PROJECT.md; this maps the *researched* patterns onto that structure
rather than proposing new phase ordering).

### In Scope This Milestone (Phases 31–33)

- [ ] Directive capture (verbatim, user-stated) with provenance tag — table stakes, low complexity, no reason to defer
- [ ] Step-0 triage veto reading directives on every reasoning path — the entire point of Phase 31
- [ ] Directive expiry/TTL (at minimum: explicit end-condition capture; ideally + renewal nudge) — prevents the exact stale-suppression failure the milestone is named for
- [ ] Reflection learning loop proposing directives with one-line veto — differentiator, explicitly planned, but MUST ship with the provenance distinction from day one
- [ ] Ambient auto-recall with relevance/recency/importance gating (not pure similarity) — table stakes for calling it "ambient," but the gating logic is the differentiator vs. a naive always-inject implementation
- [ ] Timeout guard on ambient gather — non-negotiable given the existing "18-minute reply" incident class (CLAUDE.md invariant)
- [ ] `forget_memory` hygiene tool — must ship alongside ambient recall, not deferred to Phase 35
- [ ] Occasion cascade with silence as a first-class outcome — the core differentiator of this milestone
- [ ] `get_recent_decisions` introspection tool — required for the "explain his own decisions" goal in PROJECT.md

### Add After Validation (Phase 34–35, or explicit fast-follow)

- [ ] Deeper bitemporal-style directive history (superseded-by chains queryable, not just logged) — useful once directive volume/conflict frequency is observed in production
- [ ] Learning-loop tuning based on real veto-accept/reject ratio (Phase 35 eval fixtures should measure this)
- [ ] Location-awareness feeding into ambient situation — planned in Phase 32 already, listed here only to flag it's lower urgency than directive/recall gating if Phase 32 needs to be trimmed

### Explicitly Out of Scope (per PROJECT.md, reaffirmed by this research)

- Multi-user directive/preference conflict resolution — single-user system, not applicable
- Full knowledge-graph memory backend (Zep/Graphiti-style) — the useful subset (non-destructive
  supersession) is achievable inside the existing Firestore store pattern; a graph DB migration
  is not warranted at this data volume
- Memory-driven sycophancy/validation behavior of any kind — actively rejected per the
  anti-features section above, consistent with existing "recommend-not-rewrite" coaching values

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| Directive capture + Step-0 veto | HIGH | LOW-MEDIUM | P1 |
| Directive provenance (stated vs. proposed) | HIGH | LOW | P1 |
| Directive expiry/TTL | HIGH | LOW-MEDIUM | P1 |
| Reflection learning loop (self-proposed directives) | MEDIUM-HIGH | HIGH | P1 (explicitly planned, but highest-risk item — needs the tightest veto discipline) |
| Ambient auto-recall with relevance/recency/importance gating | HIGH | MEDIUM | P1 |
| Timeout guard on ambient gather | HIGH (prevents regression) | LOW | P1 |
| `forget_memory` hygiene | MEDIUM-HIGH | LOW-MEDIUM | P1 (should not be deferred — see dependency note) |
| Conversation continuity past 6h reset | MEDIUM | MEDIUM | P2 |
| Occasion cascade with silence-as-choice | HIGH | MEDIUM-HIGH | P1 |
| `get_recent_decisions` introspection | MEDIUM | MEDIUM | P1 (small standalone cost, required for stated goal) |
| Bitemporal-style supersession history (beyond simple flag) | LOW-MEDIUM | MEDIUM | P3 |
| Location awareness in ambient situation | LOW-MEDIUM | MEDIUM | P2 |

## Reference-System Comparison

| Capability | ChatGPT Memory | Claude.ai Memory | MemGPT/Letta | Zep/Graphiti | Klaus v6.0 Approach |
|------------|-----------------|-------------------|--------------|---------------|----------------------|
| Directive vs. fact distinction | Implicit ("saved memories" list is mostly preference-like) | Implicit (synthesized running summary of preferences + facts) | Explicit: core memory (pinned preferences/persona) vs. archival (facts/history) | Explicit via typed edges + bitemporal validity | Explicit: `StandingDirectiveStore` (behavioral orders, gates proactive speech) vs. Pinecone `fact`/`chat` kinds (evidence) |
| Conflict resolution | Newest chat-history insight supersedes; saved memories are user-managed | Running summary updates in place, no visible history | Agent-managed via function calls into core memory blocks | Deterministic bitemporal invalidation (LLM detects contradiction, sets `tinvalid`) | Recency-wins default + flag-once-then-record for directive/persona conflicts (per locked decision) |
| Who can write memory | User only (explicit or implicit from chat) | User only (explicit or implicit) | Agent itself, autonomously, via tool calls | Any source (user, tool, agent) with provenance metadata | Both: user-stated (verbatim) and agent-proposed (reflection loop) — this is the differentiator, with provenance as the safety rail |
| Retrieval gating | Opaque ("system selects memory relevant to your prompt") | Opaque (synthesized summary always present, not scored per-turn) | Agent decides what to page in/out of core memory; archival is similarity search | Hybrid graph + semantic + BM25 search | Relevance + recency/importance weighted, timeout-guarded, capped injection (per this research) |
| Proactive silence as a decision | N/A (not a proactive system) | N/A (not a proactive system) | N/A (not a proactive system) | N/A (memory layer only, not a proactivity engine) | Core differentiator: occasion cascade treats silence as a valid, logged, explainable outcome — no comparable consumer reference system does this |
| Self-explainability of decisions | None surfaced to user | None surfaced to user | Agent memory operations are visible in traces but not user-facing explanations | Provenance is queryable but not framed as end-user explanation | `get_recent_decisions` — explicit differentiator goal |

## Sources

- [ChatGPT Memory FAQ (OpenAI)](https://help.openai.com/en/articles/8590148-memory-faq)
- [How does "Reference saved memories" work? (OpenAI)](https://help.openai.com/en/articles/11146739-how-does-reference-saved-memories-work)
- [Memory and new controls for ChatGPT (OpenAI)](https://openai.com/index/memory-and-new-controls-for-chatgpt/)
- [Claude memory tool (Anthropic Platform Docs)](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- [Exploring Anthropic's Memory Tool — Leonie Monigatti](https://www.leoniemonigatti.com/blog/claude-memory-tool.html)
- [Agent Memory: How to Build Agents That Learn and Remember — Letta](https://www.letta.com/blog/agent-memory/)
- [Virtual context management with MemGPT and Letta — Leonie Monigatti](https://www.leoniemonigatti.com/blog/memgpt.html)
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv 2501.13956)](https://arxiv.org/abs/2501.13956)
- [How Zep tracks provenance in agent memory](https://blog.getzep.com/how-zep-tracks-provenance-in-agent-memory/)
- [Generative Agents: Interactive Simulacra of Human Behavior, Park et al. (arXiv 2304.03442)](https://ar5iv.labs.arxiv.org/html/2304.03442)
- [Generative Agents Memory Stream — Subodh Jena](https://www.subodhjena.com/blog/generative-agents-memory-stanford)
- [LangGraph memory overview (LangChain Docs)](https://docs.langchain.com/oss/python/concepts/memory)
- [LangMem SDK for agent long-term memory (LangChain)](https://www.langchain.com/blog/langmem-sdk-launch)
- [Don't Ask the LLM to Track Freshness: A Deterministic Recipe for Memory Conflict Resolution (arXiv 2606.01435)](https://arxiv.org/pdf/2606.01435)
- [Agent Memory Systems: A Complete Engineering Guide — Tejpal Kumawat](https://medium.com/@tejpal.abhyuday/a-framework-agnostic-reference-for-designing-memory-in-any-ai-agent-not-just-travel-bots-0554fe803f59)
- [Novel Memory Forgetting Techniques for Autonomous AI Agents (arXiv 2604.02280)](https://arxiv.org/html/2604.02280.pdf)
- [Access-Weighted Memory Decay, Geometric Stickiness, and True Forgetting — Clawd Daily](https://clawddaily.com/papers/memory-decay)
- [RAG Data Poisoning: Key Concepts Explained — Promptfoo](https://www.promptfoo.dev/blog/rag-poisoning/)
- [Context poisoning in LLMs: How to defend your RAG system — Elastic](https://www.elastic.co/search-labs/blog/context-poisoning-llm)
- [Retrieval as a Decision: Training-Free Adaptive Gating for Efficient RAG (arXiv 2511.09803)](https://arxiv.org/abs/2511.09803)
- [Background Agents and the Notification Budget — TianPan.co](https://tianpan.co/blog/2026-05-13-background-agents-notification-budget-attention-economy)
- [Proactive AI Agents — Lyzr](https://www.lyzr.ai/glossaries/proactive-ai-agents/)
- [AI-powered chatbots can become too agreeable over time — Penn State University](https://www.psu.edu/news/information-sciences-and-technology/story/ai-powered-chatbots-can-become-too-agreeable-over-time)
- [OP-Bench: Benchmarking Over-Personalization for Memory-Augmented Personalized Conversational Agents (arXiv 2601.13722)](https://arxiv.org/pdf/2601.13722)
- [Beyond Similarity: Trustworthy Memory Search for Personal AI Agents (arXiv 2606.06054)](https://arxiv.org/pdf/2606.06054)
- [Explainability and transparency in autonomous agents — AI Accelerator Institute](https://www.aiacceleratorinstitute.com/explainability-and-transparency-in-autonomous-agents/)
- Klaus repo: `.planning/PROJECT.md` (v6.0 phase plan, locked decisions, existing architecture)

---
*Feature research for: Klaus v6.0 "Klaus Becomes an Agent" — standing directives, ambient memory, judgment-driven proactivity*
*Researched: 2026-07-17*
