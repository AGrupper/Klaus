# Phase 22: Expert Coaching Knowledge + D-13 Release - Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

**What this phase delivers (COACH-01, COACH-02, COACH-06, COACH-07):**

Klaus stops being a *qualitative* coach and becomes an *expert, specific* one. Three concrete deliverables:

1. **Author `docs/COACHING_GUIDE.md`** — curated, source-tier-tagged hybrid-athlete coaching knowledge (concurrent strength/endurance + interference effect, block periodization, session execution, fueling science), written **applied to Amit's blueprint** (the science taught *around* his sessions/goals/split). Wire it into the coaching reasoning substrate.
2. **Release the D-13 guard** — replace the blanket "don't invent numbers" rule with a **two-tier data-presence contract**: Tier A (blueprint targets) always citable as *targets*; Tier B (measured lifts/paces/macros/recovery) citable only within a recency window, never invented. Ships in the same commit as the guard removal. **Prompt-only.**
3. **Specific + critiqueing coaching** — every coaching message names the specific session + load/pace + rationale (never "do your strength session"); Klaus volunteers structural critique of suboptimal plan/habit elements (recommends, never silently rewrites).

**Out of scope (later v4.0 phases — do NOT build here):**
- `BlockStore` / `BenchmarkStore`, block-state surfacing, week-number computation, end-of-block benchmark triggers → Phase 23 (BLOCK/PROG).
- Macro-adherence checking against `MealStore`, fueling-slot miss detection → Phase 24 (NUTR). *(COACH-07-style structural critique of the nutrition targets themselves is in scope here as prompt behavior; the data-driven macro-adherence engine is Phase 24.)*
- Cross-cron coaching-message dedup / repeat-suppression → Phase 24. (Phase 22 only needs basic don't-repeat-within-a-conversation discipline.)
- Progress projection / trend reporting toward dated goals → Phase 25.
- Any new crons, backends, or dependencies.

</domain>

<decisions>
## Implementation Decisions

### Coaching guide content (COACH-01)
- **D-01 — Framing:** Guide is written **applied to Amit's plan** — knowledge framed around his actual sessions, goals, and AM/PM split (e.g. "how to execute your AM threshold run," "why your bench needs X"), with the underlying science behind each. Not pure generic reference.
- **D-02 — Size:** Rich / comprehensive on disk (1000+ lines acceptable). Depth lives on disk, not in every prompt (see D-04).
- **D-03 — Topics (all four required):** concurrent training & interference effect; block periodization; session execution (threshold runs, top-set strength, calisthenics progressions, intervals); fueling science (peri-workout fueling, protein timing, carb periodization, supplement rationale).

### Guide delivery / cost mechanism (COACH-01) — **OVERRIDES a locked v4.0 research decision**
- **D-04 — Slim core + on-demand lookup (REPLACES "inject the whole guide every call"):** v4.0 research locked `COACHING_GUIDE.md` as full prompt-injection via `_load_coaching_guide()` (mirroring `_load_self_md()`). Amit explicitly overrode this for cost reasons. New mechanism:
  - A **slim always-injected core digest (~200–300 lines)** — the principles Klaus needs constantly (AM/PM ordering rule, fueling-slot map, key red-flags, headline session-execution cues). This is what `_load_coaching_guide()` loads and injects as a stable cached prefix.
  - A **brain-direct tool `read_coaching_guide(topic)`** that loads a full deep section from the rich guide **only when a query needs it**. Rich content costs tokens only when actually used.
  - Rationale (Amit's words): "rich and comprehensive guide, but make it efficient so not every tool call costs a lot — when I ask something specific on Telegram he looks up just that thing."
- **D-05 — Crons:** Proactive crons (morning briefing, 21:30 check-in, Sunday weekly review, autonomous tick) always carry the slim core digest. They **may** call `read_coaching_guide()` but the prompt biases toward only-when-needed: high-frequency low-stakes crons (morning briefing, autonomous tick) stay on the cheap core; the Sunday weekly review may go deep. Amit's steer: "best quality + cost efficiency + speed; a coaching call can cost more than a normal tool call but must not get expensive." Keep cost sane while still meeting SC-2 (briefing/alert names the specific session + load — that comes from the **profile + core**, not a deep guide lookup).

### Tier B recency windows / D-13 release (COACH-06)
- **D-06 — Windows (confirmed from v4.0 research):** A measured (Tier B) number is citable as "current" only if logged within: **lifts ≤ 14 days**, **running pace ≤ 7 days**, **nutrition/macros ≤ 2 days**. **Garmin recovery (HRV / sleep / body battery / resting HR) is always treated as fresh** (daily-updating). Outside the window = stale.
- **D-07 — Just-past-window behavior = cite with staleness caveat:** When the only data is past its window, Klaus **names the number but flags its age** ("Your last logged bench was 92.5kg — though that was 18 days ago, Sir, so take it as a stale reference, not your current number"). Honest but still useful — does NOT refuse outright.
- **D-08 — No-data behavior (SC-1, distinct from D-07):** When there is **no logged data at all**, Klaus says "I don't have a recent X logged, Sir" and cites the blueprint goal explicitly as **"your target,"** never as current performance, never an invented number.
- **D-09 — Tier A always citable:** blueprint `dated_goals`, `weekly_split` targets, `nutrition_targets`, `plan_start_date` are always citable as targets / "your plan calls for." (Framing already seeded in `prompts/smart_agent.md:105–112` by Phase 21 — this phase hardens it into the contract and adds the recency windows.)

### Critique posture (COACH-07)
- **D-10 — Proactivity:** Klaus **volunteers** structural critique unprompted (in chat or crons) when his knowledge + Amit's data clearly show something suboptimal — **structural only** (design-level: target/architecture/timing/sequencing), never daily micro-tweaks, and not repeated hammering.
- **D-11 — Tone:** **Blunt expert.** JARVIS register, names the flaw and the fix directly, minimal C-3PO hedging. (Consistent with the "sharper edge" already in `smart_agent.md:132–136`.)
- **D-12 — Boundary (honors locked PLAN-03):** Klaus states the critique + a **specific alternative**, then waits. He calls `update_plan` / `update_training_profile` **only on Amit's explicit confirmation** ("yes" / "do it" / "update that"). Never silently rewrites the plan.

### Specificity bar (COACH-02)
- **D-13 — Minimum bar:** Every coaching point names the **session type + target load/pace + a one-line rationale**. Never "do your strength session" as a complete message. (SC-3.) e.g. "Today: top-set bench, work to a heavy triple ~92kg — it's your main strength stimulus this block toward the 100kg October target."
- **D-14 — Rationale depth:** **One-liner rationale by default.** Expand to a mini-lesson (3–4 sentences) only when Amit asks "why?" or the topic genuinely warrants it — and that expansion pulls the deep section via `read_coaching_guide()` (ties to D-04). Keeps messages tight, depth on demand.

### Claude's Discretion
- Exact line-count and section structure of the slim core digest vs. the deep guide; how `read_coaching_guide(topic)` enumerates/keys its sections (topic enum vs. free-text match).
- Whether `read_coaching_guide` is a standalone brain-direct tool or folded into an existing self-inspect-style accessor; tool schema shape and `_HANDLERS` wiring.
- A sane **upper bound** beyond which very old Tier B data stops being cited even with a caveat (degrades to D-08 "no recent data") — e.g. ~2–3× the window.
- Exact prompt wording for the Tier A/B contract, the recency thresholds, and the staleness-caveat phrasing in `prompts/smart_agent.md`.
- How the slim-core vs. deep-lookup bias is expressed to the crons without a hard prohibition.
- Whether the rich guide is one file with section anchors or a small set of section files behind the lookup tool.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The knowledge to author / inject
- `docs/COACHING_GUIDE.md` — **to be authored this phase.** Rich, applied-to-Amit hybrid-athlete coaching knowledge; source-tier-tagged. Slim core injected; deep sections behind `read_coaching_guide()`.
- `docs/hybrid_athlete_blueprint.md` — the source of Amit's specifics the guide is written *around* (Oct/Nov dated goals §1, AM/PM split §2, strength protocol §3, aerobic table §4 [loose reference only], mobility §5, 6-slot fueling + supplements §6).

### Existing code to modify
- `prompts/smart_agent.md:80–136` — current TRAINING & ATHLETIC COACHING section. Phase 21 already seeded Tier A/B framing (lines 105–112) and the no-fabrication discipline (121–130) and the "sharper edge" voice (132–136). **This phase:** add the `{coaching_guide}` (slim core) placeholder, harden Tier A/B into the recency-windowed data-presence contract (D-06/07/08), and the critique posture (D-10/11/12). The D-13 guard removal happens here.
- `core/main.py` — `_load_self_md()` at line 757 and its startup-cache + `render_smart_system` injection at ~line 418 (`{self_md}` "stable — benefits from cache") are the pattern to mirror for `_load_coaching_guide()` injecting the **slim core** as a stable cached prefix. `render_smart_system` (~287–305) already injects `{training_profile}`.
- `core/tools.py` — add the brain-direct `read_coaching_guide(topic)` tool (schema near the other brain-direct tools ~653–666; handler ~1286–1307; `_HANDLERS` dispatch ~1455). It is brain-direct (like `get_training_profile` / self-inspect), NOT worker-delegated.
- `core/tools.py` `update_training_profile` / `update_plan` handler — the COACH-07 adoption path (D-12) reuses this; recognized keys already expanded in Phase 21.

### Coaching consumers that must keep rendering cleanly (regression gate)
- `core/morning_briefing.py`, `core/proactive_alerts.py` (21:30 check-in), the Sunday weekly training review cron, `core/autonomous.py` — all compose coaching and read the prompt substrate. The slim-core injection + `read_coaching_guide` availability must not break any of them, and they must satisfy SC-2 (name the specific session + load).

### Phase governance
- `.planning/REQUIREMENTS.md` — COACH-01/02/06/07 full text + the "Out of Scope" rows (silent plan modification; daily macro micro-optimization is out, structural critique is in).
- `.planning/ROADMAP.md` — Phase 22 section + the 4 success criteria.
- `.planning/phases/21-living-plan-ingestion/21-CONTEXT.md` — locked profile/Tier-A-only decisions this phase builds on (profile holds targets only; Tier B always derived live).
- `.planning/STATE.md` § Accumulated Context — the v4.0 research decisions (note: D-04 here **overrides** the "inject the whole guide every call" research decision).
- `.planning/research/` — `ARCHITECTURE.md`, `FEATURES.md`, `PITFALLS.md`, `STACK.md`, `SUMMARY.md` (v4.0 kickoff research).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_load_self_md()` + startup-cache + stable-prefix injection in `core/main.py` — direct template for `_load_coaching_guide()` injecting the slim core digest (benefits from Gemini context caching).
- Brain-direct tool pattern (`get_training_profile`, self-inspect `read_own_source`) in `core/tools.py` — template for `read_coaching_guide(topic)`.
- `update_training_profile` / `update_plan` tool — already the COACH-07 adoption path (Phase 21 expanded its recognized keys).

### Established Patterns
- Tier A/B framing + no-fabrication discipline already live in `prompts/smart_agent.md` (Phase 21). This phase hardens, not invents, that framing.
- Profile is re-read every turn in `render_smart_system` (no cache invalidation needed); slim-core guide is a stable prefix loaded once at startup.
- **Recalled feedback:** Firestore `SERVER_TIMESTAMP` → `DatetimeWithNanoseconds` breaks `json.dumps` in read tools — relevant if any new read path serializes store data (not expected here; guide is file-based, prompt-only phase).

### Integration Points
- New: `{coaching_guide}` placeholder in `prompts/smart_agent.md` + `_load_coaching_guide()` in `core/main.py` → `render_smart_system`.
- New: `read_coaching_guide(topic)` brain-direct tool in `core/tools.py`.
- Modified: the Tier A/B contract block + critique posture in `prompts/smart_agent.md` (D-13 guard removal).

</code_context>

<specifics>
## Specific Ideas

- Cost is the explicit design driver for D-04/D-05: Amit wants a genuinely rich guide but refuses to pay full guide cost on every one of ~40 daily coaching calls. Slim-core-always + deep-lookup-on-demand is the resolution he reached.
- Example specificity bar (Amit-endorsed preview): *"Today: top-set bench, work to a heavy triple ~92kg. It's your main strength stimulus this block toward the 100kg October target."*
- Example blunt-expert critique (Amit-endorsed preview): *"Sir, your protein target (150g) is low for your training volume — ~1.6g/kg. For concurrent strength I'd argue 180–190g. Worth reconsidering."* (then offers to update via D-12).
- Example staleness caveat (Amit-endorsed preview): *"Your last logged bench was 92.5kg, logged 18 days ago — stale, so treat it as a rough reference rather than your current number."*

</specifics>

<deferred>
## Deferred Ideas

- Data-driven macro-adherence engine against `MealStore` + fueling-slot-miss detection → Phase 24 (NUTR). (Structural critique of the *targets* is in scope here; the per-meal adherence checking is not.)
- Cross-cron coaching-message dedup / repeat-suppression → Phase 24.
- `BlockStore` / `BenchmarkStore`, block-state surfacing, week-number computation, benchmark triggers → Phase 23.
- Progress projection / pace-to-deadline trend reporting → Phase 25.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 22-expert-coaching-knowledge-d-13-release*
*Context gathered: 2026-06-04*
