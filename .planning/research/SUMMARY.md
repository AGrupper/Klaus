# Project Research Summary

**Project:** Klaus v4.0 — Specific Training & Nutrition Coaching
**Domain:** Expert hybrid-athlete coaching layer added to a live personal AI agent
**Researched:** 2026-06-03
**Confidence:** HIGH

## Executive Summary

Klaus v4.0 transforms an existing, working accountability system (evidence-first check-ins, Garmin/HRV/ACWR data, inline-keyboard session logging, macros via HealthKit/Lifesum) into a genuinely expert hybrid-athlete coach. The milestone is not greenfield: every data source, every cron, and every Firestore store already exists. The research converges on a single insight: three infrastructure additions unlock everything. First, populating `UserProfileStore` from the blueprint (structured fields, not raw markdown) gives the brain citable plan targets and creates a living guide it reasons from. Second, injecting curated expert coaching knowledge as a prompt-level doc (the `docs/COACHING_GUIDE.md` → `{coaching_guide}` pattern, identical to how `SELF.md` is handled today) eliminates generic advice without adding retrieval plumbing. Third, two new Firestore stores (`BlockStore`, `BenchmarkStore`) give the brain block-state awareness and facet-level improvement history. D-13 guard release follows from the first addition as a conditional prompt change, not a code toggle.

The recommended build order is dependency-ordered and strictly additive: (A) blueprint ingestion + schema extension → (B) coaching knowledge doc + system prompt wiring → (C) D-13 guard replacement (requires A) → (D) block and benchmark stores + cron surface points (requires A and C) → (E) strict proactive and reactive coaching as the behavioral outcome of A–D working together. No new cron jobs, no new Python packages, no new API backends. The only net-new infrastructure is the `docs/COACHING_GUIDE.md` file and two Firestore store classes. Everything else is schema extension and prompt engineering on existing wired components.

The critical risk is fabrication regression: releasing D-13 without a data-presence contract (Tier A = blueprint goals, citable as "your target"; Tier B = measured results, citable only when the relevant record is within a defined recency window) will cause Klaus to fill silent gaps with plausible-sounding invented numbers. The second risk is cross-cron nagging — each cron independently identifies coaching opportunities, and without a shared dedup gate (extending `OutreachLogStore` beyond the autonomous tick scope), the same topic fires in the morning briefing, the evening check-in, and the weekly review on the same day. Both risks must be addressed in the same commit as the features that introduce them, not retrofitted later.

## Key Findings

### Recommended Stack

All four researchers converge: v4.0 requires no new core frameworks, no new Python packages, and no new API backends. The guiding constraint is explicit: every decision must reuse existing infra unless a genuinely new capability is needed. The existing stack (Firestore, Postgres, Pinecone, gemini-3.5-flash brain, TrainingLogStore, MealStore, UserProfileStore scaffold, all crons) is already wired and verified. The only structural additions are a `docs/COACHING_GUIDE.md` flat file and two new Firestore store classes.

**Core technologies:**
- **Firestore `users/amit` (UserProfileStore extended):** Schema v2 adds `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, `current_block_id`, `current_state`, `plan_start_date`. Existing merge-patch discipline; no new collection.
- **Firestore `training_blocks` (BlockStore, new):** Tracks block lifecycle (start/end dates, phase, `benchmark_due` flag). New class, TrainingLogStore pattern. Six to ten lifetime blocks — not a collection-scale problem.
- **Firestore `benchmarks` (BenchmarkStore, new):** Per-facet per-date benchmark results. Doc ID `{date}_{facet}` makes re-logging idempotent. `get_facet_history(facet, n)` feeds trend commentary.
- **`docs/COACHING_GUIDE.md` (new flat file):** ~600-token curated expert knowledge loaded once at startup by `_load_coaching_guide()` and injected as `{coaching_guide}` in `render_smart_system`. Same `_load_self_md()` pattern. Not Pinecone RAG — the corpus is small, always relevant, and must never have a retrieval-miss failure mode.
- **7 new brain-direct tools in `core/tools.py`:** `get_plan`, `get_block_status`, `update_plan`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block`. All follow existing `_HANDLERS` dispatch + `SMART_AGENT_DIRECT_TOOLS` registration pattern.

**Confirmed anti-additions:**
- No Pinecone RAG for the coaching knowledge doc (always-needed ~600-token content; retrieval adds latency with no benefit at single-user bounded-corpus scale)
- No new `CoachingKnowledgeStore` Firestore collection (static doc belongs in flat file)
- No new cron job for benchmark triggers (flag-check in existing 21:30 proactive_alerts cron is sufficient)
- No new Python ORM or new LLM model backend

### Expected Features

**Must have (table stakes — without these Klaus stays generic):**
- **UserProfileStore populated from blueprint** — master gate; all specificity downstream is blocked without it. Structured fields for dated goals (Oct/Nov), AM/PM weekly split, 16-week aerobic progression, fueling timeline (6 slots), supplement schedule (7 items), `plan_start_date`.
- **Expert coaching knowledge in system prompt** — `docs/COACHING_GUIDE.md` injected as `{coaching_guide}`. Covers concurrent training interference effect, block periodization, session execution cues, fueling science, how to read recovery signals. Reasoning substrate for all other coaching quality.
- **D-13 guard released with data-presence contract** — Tier A (blueprint goals, citable as targets) + Tier B (measured data, citable only within recency window). Must ship in same commit as guard removal.
- **Session naming in every coaching message** — "Tuesday Upper Body A — Bench 4x3-5, top-set target 82.5kg" not "your strength session."
- **Block tracking (`BlockStore`)** — provides "Week 7 of 16, Capacity Build phase" context to all crons.
- **Recovery-vs-plan advice with named trade-off** — fact + plan conflict + ranked options + explicit "your call, Sir." Never dictating; never hedging.

**Should have (differentiators that make Klaus genuinely expert):**
- Macro adherence vs fueling timeline (map `MealStore` timestamps to 6 blueprint slots, flag structural misses)
- Morning briefing session-context framing (recovery state + today's named session + fueling reminder in one specific block)
- Per-facet weekly progress in Sunday review (block-relative framing, volume vs target, lift trajectory)
- Skip/off-plan pushback with deficit calculation (volume gap in km or sets, named consequence for goal timeline)
- Session quality rating via 21:30 follow-up (strong / neutral / grind, stored for trend annotation)
- End-of-block benchmark prompts (triggered by `benchmark_due` flag, biometric validity gate)
- Supplement timing accountability (cross-reference `MealStore` windows against supplement schedule)
- Interference-effect-aware commentary (when ACWR >1.3 or HRV suppressed, name session-type interaction)

**Anti-features (explicitly out of scope — do not build):**
- Mid-cycle / periodic testing (blueprint is explicit: test only at block ends + Oct/Nov deadlines, not weekly)
- Coach-override on recovery decisions (Klaus advises, Amit decides — always)
- Daily micro-macro optimization (flag structural slot misses; do not optimize marginal adjustments)
- Autonomous plan modification (Klaus coaches the blueprint; Amit modifies it)
- Real-time session monitoring (architecturally fake in a cron + Telegram system)
- Injury diagnosis or injury management language (flag warning patterns; never diagnose)
- Parallel Telegram meal logging (MealStore pipeline via HealthKit already works; a parser creates divergence)
- Caloric surplus/deficit framing (blueprint uses 6-slot fueling architecture, not CICO)

### Architecture Approach

The v4.0 architecture is a horizontal extension across four existing layers: prompt layer (four prompt files), orchestration layer (main.py render_smart_system + three cron compose functions), tools layer (7 new brain-direct tools), and persistence layer (UserProfileStore schema extension + two new Firestore stores). All four layers have established patterns that v4.0 follows exactly. No new architectural concepts are introduced.

**Major components and their v4.0 roles:**
1. **`docs/COACHING_GUIDE.md` + `{coaching_guide}` injection** — startup-cached expert knowledge. Single source of truth for interference effect rules, periodization logic, fueling science, benchmark testing protocol. Edited in text, versioned in git, picked up on next deploy.
2. **`UserProfileStore` (extended schema)** — the living blueprint guide. Brain reads it for dated goals, today's weekly split session, nutrition targets, and `current_block_id`. Framed as a reference guide ("Coaching blueprint:") in `render_smart_system`, not a binding schedule.
3. **`BlockStore` + `BenchmarkStore` (new Firestore stores)** — block lifecycle and per-facet measurement history. `BlockStore.get_current()` surfaces in all three crons via best-effort gather wrapping. `BenchmarkStore.get_facet_history()` powers per-facet trend commentary in the weekly review.
4. **D-13 guard replacement** — prompt-only change across four prompt files. No Python code changes required.
5. **7 new brain-direct tools** — judgment-requiring tools in `SMART_AGENT_DIRECT_TOOLS`; none delegated to the worker.
6. **Cross-cron coaching topic dedup gate** — `OutreachLogStore` extension (or thin `CoachingTouchStore`) covering all coaching crons, not just the autonomous tick. Per-day per-topic check.

**Key patterns to follow (all existing):**
- Omit-empty discipline: missing data keys are absent from the prompt context dict, never `None` placeholders
- Best-effort gather wrapping: all new gather calls wrapped in try/except, failures log at WARNING
- Brain-direct for judgment / worker for execution: block lifecycle and benchmark decisions are brain-direct
- Startup-cached stable content: `_load_coaching_guide()` reads once at startup, no per-message file I/O

### Critical Pitfalls

1. **Fabrication regression (D-13 release without data-presence gate)** — Without a Tier A / Tier B contract, the brain conflates blueprint goal numbers with current performance facts. Mitigation: define the two-tier contract in the same commit that removes the guard. Test: coaching query when `TrainingLogStore` has no recent bench data must return "I don't have a recent bench logged, Sir" — not an invented number.

2. **Cross-cron nagging (four independent coaching paths, no shared dedup)** — Morning briefing, proactive alerts, weekly review, and autonomous tick each fire independently on valid coaching signals. Without a shared per-day per-topic gate, the same protein miss or skipped session fires four times in one day, eroding trust. Mitigation: extend `OutreachLogStore` dedup to all coaching crons before any proactive coaching ships.

3. **Rigidity drift (blueprint stored as prescription, not guide)** — If the weekly split is stored with per-session `completed` booleans, any missed session is structurally a failure and Klaus nags repeatedly. Mitigation: store as a weekly template with session priorities and block-level volume targets. Coach against volume completion and trend, not day-specific attendance. This schema decision is hard to retrofit — get it right at ingest time.

4. **v3.0 cron regression** — Adding blueprint context and expert knowledge to existing cron prompts can cause non-coaching outputs (weather alerts, travel time) to disappear from the proactive alerts path. Mitigation: dry-run every modified cron with a fully populated profile; verify non-coaching outputs are unchanged; pin the 630+ test baseline with zero new failures required before any cron change deploys.

5. **Block and benchmark ambiguity (periodic testing, non-comparable benchmarks)** — Without `block_start_date` / `block_end_date` in `UserProfileStore` and a biometric validity gate, Klaus may prompt a 1RM test in Week 3 or compare a tired benchmark to a rested one. Mitigation: benchmark prompts fire only within 3 days of stored `block_end_date`; validity gate checks HRV >= 70% of 7-day baseline and ACWR < 1.2 before allowing the prompt.

## Implications for Roadmap

All four researchers independently derived the same dependency-ordered build sequence. The phase structure is unambiguous.

### Phase A: Blueprint Ingestion + Living Plan

**Rationale:** Master gate — all downstream coaching specificity is blocked without this. Must come first.

**Delivers:** `UserProfileStore` with dated goals (Oct/Nov), weekly split, fueling timeline (6 slots), supplement schedule (7 items), `plan_start_date`, block boundary fields. `update_plan` brain-direct tool. One-shot `scripts/ingest_blueprint.py` CLI ingest script.

**Addresses:** UserProfileStore populated from blueprint (table stakes master gate); plan_start_date stored explicitly (prevents block boundary ambiguity pitfall).

**Avoids:** Blueprint-as-raw-markdown technical debt; rigidity drift (weekly template + volume targets, not per-session booleans); block boundary ambiguity (explicit date fields from day one).

**Gate:** `UserProfileStore.load()` returns non-empty `dated_goals`, `weekly_split`, `nutrition_targets`, `plan_start_date`.

### Phase B: Coaching Knowledge Layer

**Rationale:** No runtime dependency on Phase A data. Can be built concurrently with Phase A. Must complete before Phase C so the brain has coaching context when it starts naming numbers.

**Delivers:** `docs/COACHING_GUIDE.md` (hybrid-athlete principles, interference effect rules, periodization, session execution, fueling science, benchmark protocols — ~600 tokens, source-tier tagged). Wired into `render_smart_system` as `{coaching_guide}`. Condensed versions appended to three cron-specific prompts.

**Addresses:** Expert coaching knowledge in system prompt (reasoning substrate for all other coaching quality); hallucinated sports science prevention (claim tagging, no derivative physiological predictions).

**Avoids:** Generic-advice regression despite curated knowledge (prompt structured as decision tree, not knowledge dump; dry-run must name specific session, specific numbers, specific recovery trade-off before this phase is done).

**Gate:** Brain demonstrates expert coaching reasoning in dry-run chat: specific session named, specific load named, recovery trade-off framed with numbers.

### Phase C: D-13 Guard Replacement

**Rationale:** Requires Phase A (profile must have real targets before the guard releases). Prompt-only change — no Python code. Must ship the data-presence contract in the same commit as the guard removal.

**Delivers:** Two-tier data-presence contract live in all four coaching prompts. Tier A (blueprint goals) citable as "your target." Tier B (measured data) citable only within recency window (lift <= 14 days, pace <= 7 days, nutrition <= 2 days). Explicit "no recent data" fallback when Tier B is absent or stale.

**Addresses:** D-13 guard released (unblocks session naming with load numbers, load prescription with personal numbers, all number-citing coaching behavior).

**Avoids:** Fabrication regression (Tier A vs Tier B distinction; test with empty TrainingLogStore before shipping); conflict UX failure (recovery-conflict template: fact + conflict + ranked recommendation + "your call").

**Gate:** Coaching query with empty `TrainingLogStore` returns "no recent data" not an invented number. Morning briefing names plan targets when recovery concern fires.

### Phase D: Block and Benchmark Tracking

**Rationale:** Requires Phase A (profile needs `current_block_id` field; `block_end_date` drives benchmark triggers). Phase C should be complete so the brain can name targets when surfacing benchmark trends. Unlocks all progress-tracking and end-of-block behaviors.

**Delivers:** `BlockStore` + `BenchmarkStore` Firestore store classes. Six additional brain-direct tools (`get_plan`, `get_block_status`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block`). Block state surfaced in morning briefing, weekly review, and proactive alerts (benchmark trigger check). First training block created.

**Addresses:** Block tracking (unlocks per-facet progress, end-of-block benchmark prompts, skip/off-plan deficit calculation, block-relative weekly review framing); end-of-block benchmark prompts with biometric validity gate.

**Avoids:** New cron anti-pattern (reuse existing 21:30 `benchmark_due` flag check — no 8th scheduler job); non-comparable benchmark results (validity gate defers on poor biometric state); block ambiguity (explicit `block_end_date` drives all triggers, not week-number inference from the 16-week table).

**Gate:** `BlockStore.get_current()` returns active block with correct week number. Benchmark prompt fires within 3 days of `block_end_date`. Weekly review surfaces per-facet benchmark trend.

### Phase E: Strict Proactive + Reactive Coaching (Integration Validation)

**Rationale:** Behavioral outcome of Phases A–D working together. No new Python logic for the coaching behaviors themselves. This phase adds the cross-cron coordination layer and validates the full coaching stack end-to-end.

**Delivers:** Cross-cron coaching topic dedup gate (extend `OutreachLogStore` per-day per-topic across all coaching crons). Macro adherence vs fueling timeline slot mapping. Morning briefing session-context framing with named session + recovery state + fueling reminder. Skip/off-plan pushback with deficit calculation. Session quality rating in 21:30 flow. End-to-end validation across all four coaching touchpoints.

**Addresses:** Cross-cron nagging prevention (shared per-day per-topic dedup); macro adherence vs fueling timeline (slot-to-timestamp window mapping); skip/off-plan strict pushback; morning briefing session-context framing; interference-effect-aware commentary (total weekly load tier gates volume recommendations).

**Avoids:** Over-coaching / nagging (dedup gate covers all paths, not just autonomous tick); interference-effect overreach (total weekly stress computation gates volume recommendations at HIGH load tier); v3.0 cron regression (dry-run all modified crons; non-coaching outputs verified unchanged; 630+ test suite zero new failures).

**Validation scenarios (required before phase closes):** Recovery conflict with threshold run scheduled; off-plan nutrition critique; mid-block progress question; end-of-block benchmark trigger on good biometric state; end-of-block benchmark trigger on poor biometric state (should defer); supplement miss at evening check-in; same topic appears in morning briefing (should be suppressed at evening check-in).

### Phase Ordering Rationale

- Phases A → C are strictly sequential: the profile must be populated before the guard releases, because the guard exists to prevent citing numbers that don't exist yet.
- Phase B can overlap Phase A: coaching knowledge is a static doc with no runtime dependency on profile data. Draft COACHING_GUIDE.md and wire the injection while Phase A ingest script is being built.
- Phase D requires Phase A for the `current_block_id` field and block date fields, but the Firestore store classes and tools can be scaffolded before Phase A completes. The first `start_block` call happens after the profile is populated.
- Phase E is the integration and coordination step — validates emergent behavior, adds the cross-cron dedup gate, and closes the milestone.

### Research Flags

Phases requiring careful validation during planning (domain is understood, execution details need verification):
- **Phase C (D-13 replacement):** The Tier A / Tier B contract is conceptually clear but easy to miscalibrate. Test with three scenarios: fresh data present, stale data (should note staleness), no data at all (should name the gap). Both over-restrictive and over-permissive outcomes are failure modes.
- **Phase E (cross-cron dedup):** The `OutreachLogStore` scope extension needs an explicit taxonomy of coaching topic keys before implementation. Define the topic list at Phase E planning time to avoid ambiguous suppression decisions during coding.
- **Phase B (COACHING_GUIDE.md content):** Writing the coaching knowledge doc requires time and care. Every claim needs a source-tier tag. LOW-confidence claims (specific thresholds not in the blueprint) must be prefaced with "research suggests" in coaching output. Allocate explicit authoring time.

Phases with standard patterns (skip additional research):
- **Phase A:** Firestore merge-patch schema extension is established practice in this codebase. The CLI ingest script follows `scripts/ingest_garmin_zip.py` pattern.
- **Phase B (wiring):** `_load_self_md()` / `{self_md}` pattern is live and proven. Appending coaching context to cron prompts follows the `meal_audit.md` append pattern in `weekly_training_review.py`.
- **Phase D:** `BlockStore` and `BenchmarkStore` follow the `TrainingLogStore` pattern exactly. The 7 new tools follow the `_HANDLERS` dispatch pattern exactly.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All extension points verified from live source code; zero new dependencies; every primitive already imported and used |
| Features | HIGH | Grounded in Amit's actual blueprint (primary source) + sports-science literature; anti-features explicit from the blueprint philosophy |
| Architecture | HIGH | All integration points verified with line numbers from live source; `render_smart_system` pattern, `_HANDLERS` pattern, TrainingLogStore pattern all confirmed live |
| Pitfalls | HIGH | Drawn from live codebase analysis, shipped v3.0 artifacts, and blueprint document; not speculative |

**Overall confidence:** HIGH

### Gaps to Address

- **COACHING_GUIDE.md content authoring:** The injection mechanism is clear, but the actual coaching knowledge (interference-effect rules as applied to Amit's specific AM/PM split, exact benchmark protocols, fueling science with source tiers) must be authored carefully. This is a writing task, not an engineering task — allocate explicit time in Phase B.
- **Fueling timeline slot-to-timestamp mapping:** The six fueling slots have approximate time windows ("post-AM run" = 06:30–09:00 approximately). The slot-to-window mapping table `(slot_name, start_time, end_time)` needs to be defined before the macro adherence feature in Phase E can be implemented correctly.
- **Cross-cron dedup topic taxonomy:** The list of coaching topic keys (what counts as one dedup-able "topic") needs to be defined at Phase E planning time, not discovered during coding.
- **Firestore vs Postgres for benchmark results:** STACK.md and ARCHITECTURE.md reached slightly different conclusions. Recommendation: start with Firestore `BenchmarkStore` (consistent with existing patterns, lower friction) and add the Postgres table only if multi-block trend queries become unwieldy after 3+ blocks of data.

## Sources

### Primary (HIGH confidence)

- `memory/firestore_db.py` — `UserProfileStore` scaffold (lines 93–168), `TrainingLogStore`, `MealStore` patterns — live code read
- `core/main.py` — `AgentOrchestrator.__init__`, `render_smart_system` (lines 239–307), `_load_self_md()` pattern — live code read
- `core/tools.py` — `TOOL_SCHEMAS`, `SMART_AGENT_DIRECT_TOOLS`, `_HANDLERS` dispatch (lines 39–57, 651–827, 1433–1471) — live code read
- `core/weekly_training_review.py` — `_gather_week_data`, meal_audit append pattern (lines 42–266) — live code read
- `core/training_checkin.py` — `compute_recovery_concern`, D-13 guard location — live code read
- `prompts/smart_agent.md` — `{training_profile}` placeholder, D-13 training section (lines 85–100) — live code read
- `prompts/morning_briefing.md` — D-13 guard (lines 138–143) — live code read
- `prompts/proactive_alert.md` — D-13 guard (lines 22–23) — live code read
- Hybrid Athlete Master Blueprint: Oct/Nov Peak V2 — dated goals, weekly split, fueling architecture, supplement schedule, 16-week aerobic progression — primary source for all blueprint-specific details
- `.planning/PROJECT.md` — v4.0 goal statement, D-13 context, facet-mastery philosophy, advise-not-override invariant

### Secondary (MEDIUM confidence)

- Barbell Medicine: Concurrent Training and the Interference Effect — interference effect management rules
- TrainingPeaks: Implementing Block Periodization — block phase structure and benchmark cadence
- ACWR optimal zone research (PMC:8138569) — 0.8–1.3 zone, injury risk at >1.3
- Block periodization research (PMC:7693826) — accumulation/transmutation/realization structure
- Concurrent training meta-analysis (PMC:11688070) — conditions for manageable interference effect
- Fathom Nutrition: Hybrid Training Blueprint — fueling science for concurrent athletes
- Lift Living: Nutrition Guide for Hybrid Athletes — fueling timeline principles

### Tertiary (LOW confidence — background only, do not cite specific statistics in coaching output)

- Creatine + Beta-Alanine co-supplementation (MDPI:2072-6643/17/13/2074) — individual evidence strong; combined advantage contested
- TrainHeroic: How to Build a Culture of Athlete Accountability — skip/off-plan communication framing

---
*Research completed: 2026-06-03*
*Ready for roadmap: yes*
