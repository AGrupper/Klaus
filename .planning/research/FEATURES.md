# Feature Research

**Domain:** Expert hybrid-athlete coaching embedded in a personal AI agent (v4.0 upgrade to Klaus)
**Researched:** 2026-06-03
**Confidence:** HIGH (grounded in Amit's actual blueprint + established sports-science literature)

---

## Context: What Already Exists (v3.0)

Before categorizing what to build, the baseline matters because every feature below is an
**upgrade**, not greenfield:

| Capability | Status | Gap to v4.0 |
|------------|--------|------------|
| Garmin data (sleep, HRV, body battery, resting HR) | Live | Needs threshold-based coaching interpretation |
| ACWR computed daily | Live | Needs explicit coaching language when outside 0.8–1.3 |
| `MealStore` (HealthKit/Lifesum, fiber, macros per day) | Live | Needs fueling-timeline checking, not just daily totals |
| `TrainingLogStore` (inline-keyboard logging per session) | Live | Needs block context (which week, which phase) |
| 21:30 evidence-first training check-in | Live | Needs to name the session, the load, and cite the reason |
| Morning briefing (Garmin-anchored) | Live | Needs to frame recovery in terms of today's session impact |
| Sunday weekly review | Live | Needs block-relative framing and progress-toward-goal |
| D-13 no-fabrication guard (no made-up numbers) | Active | Must be released once `UserProfileStore` is populated |
| `UserProfileStore` scaffold | Empty | Core of v4.0 — must be populated from blueprint |

---

## Feature Landscape

### Table Stakes (Without These Klaus Stays Generic)

Features Amit explicitly needs — their absence is the precise reason coaching feels generic today.

| Feature | Why Expected | Complexity | v3.0 Dependency | Notes |
|---------|--------------|------------|-----------------|-------|
| **UserProfileStore populated from blueprint** | All specificity downstream depends on it. Goals (Oct/Nov deadlines + lifts/paces), the AM/PM weekly split, the 16-week aerobic progression, fueling architecture, supplement schedule | MEDIUM | `UserProfileStore` scaffold exists, needs populated | One-time structured ingest of the blueprint document. Becomes the "living guide" all coaching reads from. |
| **Session naming in every coaching message** | "Today is Tuesday Upper Body A — Bench 4x3-5 (current top-set ~X kg), weighted pull-ups 3 sets, fatigue-squeeze after final set" vs "do your upper body workout". Amit's explicit complaint | LOW | `TrainingLogStore` + `UserProfileStore` | Brain reads the day's slot from the blueprint and names it explicitly |
| **Load prescription with personal numbers** | A real coach says "hit 87.5kg for 3 this week — you hit 85 last block." Generic LLM says "increase progressive overload." Requires `TrainingLogStore` history + D-13 release | MEDIUM | `TrainingLogStore`, `UserProfileStore`, D-13 guard release | Must compute from actual logged sets, not from blueprint targets alone |
| **D-13 guard released** | Klaus must be allowed to cite real numbers: last logged top-set, current threshold pace from Garmin, 7-day macro compliance %, HRV trend. Without this release everything else is moot | LOW (guard removal) | Populating `UserProfileStore` is the gate | Release is conditional on blueprint being ingested — not unconditional |
| **Recovery-vs-plan advice with named trade-off** | Real coaches don't say "consider rest." They say: "HRV is 15% below baseline for 3rd day, ACWR at 1.4 — today's threshold run carries injury risk. Options: (1) swap to easy 8km, (2) full rest. You decide." | LOW | `compute_recovery_concern` exists, Garmin live | Needs explicit option framing and data citation, not just a concern flag |
| **Macro adherence accountability tied to fueling timeline** | Coach checks: did you hit the post-AM-run reload? Did you take Vitamin D+K2 this morning? Did Beta-Alanine go in pre-lift? Not just "you hit 140g protein today" | MEDIUM | `MealStore` (day totals exist), no timeline data | Fueling timeline has 6 named slots from blueprint. MealStore has timestamps — map meal timestamps to slot windows. Flag gaps specifically |
| **Block tracking + current week context** | Every cron message should know "this is Week 7 of 16, Capacity Build phase, threshold volume target 10km this week." Without block context Klaus coaches in a vacuum | MEDIUM | `UserProfileStore`, `TrainingLogStore` | Block start date + 16-week progression table need to be stored and queryable. Needs a `BlockStore` or similar |
| **Sunday weekly review with per-facet progress** | Not just "good week." "Squat top set: 82.5kg (+2.5 since last block). Threshold volume this week: 9.2km vs 10km target — 92%. ACWR: 1.1. Trend: on track for Oct deadline." | MEDIUM | Sunday cron, `TrainingLogStore`, block tracking | Depends on block tracking being live. Per-facet trend math is new |

### Differentiators (What Makes Klaus Genuinely Expert)

Features that transform Klaus from "accountable" to "coach-grade."

| Feature | Value Proposition | Complexity | v3.0 Dependency | Notes |
|---------|-------------------|------------|-----------------|-------|
| **Interference-effect-aware session scheduling commentary** | When ACWR is high or HRV suppressed, Klaus knows that endurance before strength is contraindicated and says so explicitly with the science. "Strength before endurance today — fatigue from the threshold session would blunt power output. Your AM run was 10km, adequate recovery window is 6h minimum." | MEDIUM | Garmin, ACWR, `UserProfileStore` for the AM/PM split | Requires Klaus to reason about session type + timing, not just flag recovery. Baked into coaching knowledge via system prompt enrichment |
| **Curated expert coaching knowledge in the system prompt** | Block periodization logic (accumulation/transmutation/realization), interference effect rules, 16-week HM aerobic engine, sprint/VO2 concurrent programming, benchmark testing cadence — all baked into `smart_agent.md` as expert knowledge so reasoning is grounded, not hallucinated | HIGH | `smart_agent.md` enrichment | This is not a feature users see directly — it's the substrate that makes everything else expert-grade. Must be maintained as facts, not personality. The blueprint itself becomes a source of truth |
| **End-of-block benchmark prompts** | At week 4 (first deload), week 8 (second deload), week 12 (third deload), Klaus prompts: "This is your block-end benchmark week. Here is what to test, conditions, and how to run it — then log the result so I can compare against last block." Tests: squat 1RM (estimated from top-set volume), bench 1RM (same), max-rep push-ups/pull-ups (strict conditions, fatigue-free), 5km time trial for threshold pace. HM and November speed goals are the terminal tests, not mid-cycle | HIGH | `TrainingLogStore`, block tracking, `UserProfileStore` | Benchmark protocol must specify: fresh day (48h post heavy session), warm-up protocol, rep/load criteria, what counts as valid. Results go into `TrainingLogStore` with type=`benchmark` |
| **Pace-to-deadline progress tracking** | "You need to reach 4:01/km threshold pace by Week 13 (Race Specificity). Current Garmin threshold effort averages 4:09/km over last 4 sessions. Trend: -1.5s/km per 4 weeks. Projected arrival: Week 11. On track." | HIGH | Garmin run data, `TrainingLogStore`, block tracking, Postgres | Requires computing pace trends from Garmin run history, mapping to block week, projecting against dated deadlines |
| **Supplement timing accountability (not just daily totals)** | "Beta-Alanine: listed as PM pre-lift supplement. I see your PM meal window has carbs logged but no Beta-Alanine note. Are you taking it? Creatine goes post-lift — your post-PM window looks light on carbs this week, which reduces creatine uptake." | MEDIUM | `MealStore` timestamps, `UserProfileStore` supplement plan | Klaus cannot verify supplement intake directly — it's an inference + prompt. Needs dedicated supplement check-in mechanism or relies on user confirmation at 21:30 |
| **Session quality rating + coach annotation** | After logging via inline-keyboard, Klaus asks one follow-up: "Rate the top-set quality: strong / neutral / grind." This annotates the log entry so the weekly review can note trend changes ("You've rated squat top-sets as 'grind' for 3 straight weeks — this is a form/weight management flag before the deload") | MEDIUM | `TrainingLogStore`, 21:30 check-in flow | Requires one additional prompt step in the 21:30 inline keyboard flow. Low overhead, high signal |
| **Strict skip/off-plan pushback (named, specific, no hedging)** | Real coach response to skipped session: "You skipped Wednesday Threshold Run — Week 7, target 10km threshold volume. You logged 0. This is the second missed threshold session in 4 weeks. Your aerobic progression is running 18km behind schedule. You need to make up at least 6km of threshold work this week, ideally added to Friday's long run as a 3km threshold segment at the end." No "life happens, just try harder" | HIGH | `TrainingLogStore`, block tracking, per-facet trend | Requires detecting skipped sessions (planned vs logged) and computing real deficit. `UserProfileStore` provides the plan; `TrainingLogStore` provides actuals. Gap = deficit |
| **Morning briefing session-context framing** | "Today: Monday Lower Body A — heavy squat day. Your sleep was 7h2m, HRV 62 (baseline 68, -9%). Body battery 72. This is a moderate recovery day. Heavy squats are not contraindicated but don't push to failure on your top set — back off to an RPE 8 triple. Pre-lift: electrofuel + Beta-Alanine 60min before." | MEDIUM | Morning briefing cron, Garmin, `UserProfileStore` | Merges recovery state, today's session from blueprint, and fueling reminder into one block. Replaces the current generic recovery flag |

### Anti-Features (Seem Good, Are Wrong)

Features that could be built but would violate Amit's explicit philosophy or create noise over signal.

| Feature | Why Requested | Why Problematic | Correct Alternative |
|---------|---------------|-----------------|---------------------|
| **Periodic in-cycle goal testing (mid-block 1RM checks)** | Feels like measurable progress | Blueprint explicitly: testing is at block ends + the Oct/Nov deadlines, not periodic. Mid-cycle testing fatigues the athlete, disrupts the progression, and creates false readouts because the athlete isn't peaked | Test only at deload weeks (Weeks 4, 8, 12) and at terminal deadlines. Log top-set trends as proxy for progress |
| **Coach-override on recovery-vs-plan** | Seems like what a coach does | Amit's explicit rule: "Klaus advises, Amit decides." Overriding removes agency and would be annoying when Amit has context Klaus doesn't (slept badly but has a meet). Making the decision for Amit defeats the purpose | Always frame as "Options: (1) X, (2) Y — you decide." Never "you should not train today" as a command |
| **Daily macro-by-macro micro-optimization** | Seems expert | Creates noise. Amit's blueprint has a simple architecture: 150g protein / 350g carbs across 6 named slots. Coaching daily micro-swaps ("add 12g carbs to lunch") is CrowdStrike-level over-engineering for diminishing returns | Flag structural misses (skipped post-run reload, pre-lift window missed, pre-bed supplements absent) — not marginal adjustments |
| **Automated training plan modification** | Coach "adjusting the plan" feels premium | Klaus does not own the plan — Amit and his blueprint do. Autonomously rewriting the 16-week progression would introduce drift and break Amit's intent. Also: the blueprint is fixed by design | When conditions call for modification (illness, travel), Klaus flags the trade-off and proposes an option, but never silently changes what the plan says |
| **Real-time heart rate zone monitoring during sessions** | Feels like live coaching | Klaus is not a real-time system (Telegram, cron-driven). Trying to simulate live zone feedback would be architecturally fake and misleading | Surface zone quality data post-session via Garmin history. Comment on the session that was completed, not the one happening |
| **Injury diagnosis or explicit injury management** | Seems like a natural coaching role | Crosses into medical territory. Klaus has no qualification and no imaging/clinical data. Injury language creates liability and trust risk | Flag "this pattern (skipped sessions + low body battery + HRV suppression) is a warning sign — you know your body; consider a rest day or physio consult." Never diagnose |
| **Nutrition logging by Klaus (auto-parsing meals from chat)** | Removes friction | MealStore is already populated by HealthKit/Lifesum — that pipeline works end-to-end. Building a parallel Telegram-text meal parser would create duplicate data and divergence | Coach against what HealthKit/Lifesum already captured. The logging pipeline is solved; don't rebuild it |
| **Caloric surplus/deficit calculation** | Feels like macro coaching | Amit's blueprint does not use caloric targets — it uses a fueling architecture (6 named slots with food types). Imposing CICO framing would conflict with the blueprint's philosophy and add complexity for no gain | Validate the 6-slot architecture adherence, not caloric math |

---

## Feature Dependencies

```
[UserProfileStore populated from blueprint]
    └──unlocks──> [D-13 guard released]
                      └──unlocks──> [Load prescription with personal numbers]
                      └──unlocks──> [Macro adherence vs fueling timeline]
                      └──unlocks──> [Supplement timing accountability]
                      └──unlocks──> [Session naming in every message]

[Block tracking (BlockStore)]
    └──unlocks──> [Current week/phase context in all crons]
                      └──unlocks──> [End-of-block benchmark prompts]
                      └──unlocks──> [Skip/off-plan deficit calculation]
                      └──unlocks──> [Per-facet progress in weekly review]
                      └──unlocks──> [Pace-to-deadline projection]

[Expert coaching knowledge in system prompt]
    └──enriches──> [Session naming]
    └──enriches──> [Interference-effect-aware commentary]
    └──enriches──> [Recovery-vs-plan advice with named trade-off]

[TrainingLogStore history]
    ──feeds──> [Load prescription with personal numbers]
    ──feeds──> [Per-facet progress tracking]
    ──feeds──> [End-of-block benchmark recording]

[Garmin (HRV, sleep, body battery, pace data)]
    ──feeds──> [Recovery-vs-plan advice]
    ──feeds──> [Interference-effect-aware commentary]
    ──feeds──> [Pace-to-deadline projection]
    ──feeds──> [Morning briefing session-context framing]
```

### Dependency Notes

- **UserProfileStore populated is the master gate.** Nothing specific happens until the blueprint is ingested. This must be Phase 1 of v4.0.
- **D-13 guard release is conditional on UserProfileStore population**, not unconditional. The guard exists to prevent fabricated numbers — it can only be released when real numbers exist to replace the fabrications.
- **Block tracking is the second gate.** Load prescription and progress tracking both need to know what week/block it is. A `BlockStore` (or a field in `UserProfileStore`) tracking block start date + week number is necessary before deficit calculations or benchmark prompts can fire.
- **Expert coaching knowledge enrichment** is a prerequisite for all coaching quality — but it has no runtime dependencies. It can be built in parallel with UserProfileStore population and done as a prompt engineering pass on `smart_agent.md` and cron-specific prompts.
- **Benchmark testing** depends on both block tracking (to know when to prompt) and the D-13 release (to compare results against history). It's a Phase 3+ feature.
- **Pace-to-deadline projection** depends on Garmin pace history (already live via Postgres), block tracking (new), and the `UserProfileStore` deadlines — HIGH dependency chain, appropriate as a later phase.

---

## MVP Definition

This is a subsequent milestone (v4.0) on an existing working system, so "launch" means the first phase deployed.

### Phase 1: Foundation (Must Deploy First)

- [ ] **UserProfileStore populated from blueprint** — All of v4.0 is blocked on this. Structured ingest of: dated goals, AM/PM weekly split, 16-week aerobic progression table, fueling architecture (6 slots), supplement schedule (6 items).
- [ ] **Expert coaching knowledge in system prompt** — Enrich `smart_agent.md` and the 3 coaching-cron prompts with curated hybrid-athlete coaching knowledge. Session names, block logic, interference rules, fueling science. This is the reasoning substrate.
- [ ] **D-13 guard released (conditionally)** — Once `UserProfileStore` is populated, allow Klaus to cite real numbers from `TrainingLogStore`, Garmin, and `MealStore`.

### Phase 2: Specific Coaching (Core Value Delivery)

- [ ] **Block tracking (`BlockStore`)** — Store block start date, current week number, current phase name. Query function used by all crons.
- [ ] **Session naming in all coaching messages** — Cron prompts updated to: (1) read today's session from `UserProfileStore` AM/PM split, (2) name it explicitly, (3) name the load from `TrainingLogStore` top-set history.
- [ ] **Recovery-vs-plan advice with named options** — `compute_recovery_concern` output upgraded from flag to "Options: X, Y — you decide" framing with cited numbers.
- [ ] **Macro adherence vs fueling timeline** — Map `MealStore` timestamps to the 6 blueprint fueling slots. Flag structural gaps (missed post-run reload, missing pre-bed supplements) at 21:30 check-in.

### Phase 3: Progress Tracking and Strict Accountability

- [ ] **Per-facet weekly progress in Sunday review** — Squat/bench top-set trend, threshold volume vs target, ACWR, supplement gaps. Block-relative framing.
- [ ] **Skip/off-plan pushback with deficit calculation** — Detect planned-vs-logged gaps, compute deficit, name it specifically.
- [ ] **Session quality rating** — One follow-up prompt in the 21:30 flow: "Top-set quality: strong / neutral / grind." Annotation stored in `TrainingLogStore`.
- [ ] **Morning briefing session-context framing** — Merge recovery state + today's session name + fueling reminder into the briefing.

### Phase 4: Expert Features (Differentiators)

- [ ] **End-of-block benchmark prompts** — At deload weeks (4, 8, 12), Klaus prompts a benchmark session protocol and records results in `TrainingLogStore` as type=`benchmark`.
- [ ] **Pace-to-deadline projection** — Trend threshold pace from Garmin history, project against Week 13 4:01/km target, surface in weekly review.
- [ ] **Interference-effect-aware session commentary** — When ACWR >1.3 or HRV suppressed, explicitly name the session-type interaction and recommend ordering/modification.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| UserProfileStore populated | HIGH | MEDIUM | P1 |
| Expert coaching knowledge in prompts | HIGH | MEDIUM | P1 |
| D-13 guard release | HIGH | LOW | P1 (gated on above) |
| Block tracking | HIGH | MEDIUM | P1 |
| Session naming with load numbers | HIGH | LOW | P1 |
| Recovery-vs-plan options framing | HIGH | LOW | P1 |
| Macro adherence vs fueling timeline | MEDIUM | MEDIUM | P2 |
| Morning briefing session-context framing | HIGH | LOW | P2 |
| Per-facet weekly progress | HIGH | MEDIUM | P2 |
| Skip/off-plan strict pushback | HIGH | MEDIUM | P2 |
| Session quality rating | MEDIUM | LOW | P2 |
| End-of-block benchmark prompts | HIGH | HIGH | P3 |
| Pace-to-deadline projection | MEDIUM | HIGH | P3 |
| Supplement timing accountability | MEDIUM | MEDIUM | P3 |
| Interference-effect-aware commentary | MEDIUM | MEDIUM | P3 |

---

## What "Good" Looks Like Per Coaching Domain

### Periodization / Block Management

Real coaches know: accumulation (high volume, moderate intensity, 3-4 weeks) → transmutation (moderate volume, high intensity, 3-4 weeks) → realization/deload (low volume, peak). For Amit's 16-week HM plan this is pre-mapped. Klaus should express the current block phase contextually: "Week 7 — Capacity Build. Threshold sessions this week are your primary aerobic stimulus. Do not skip them for gym sessions."

The interference effect is real but manageable: Barbell Medicine meta-analyses show concurrent training does not compromise strength gains when (1) endurance follows strength on same-day doubles, (2) there is ≥6h between sessions, and (3) endurance intensity is moderate. Amit's blueprint already applies these rules. Klaus should name them when deviating would compromise either goal.

### Recovery-vs-Plan Decision Communication

Professional coaches cite specific numbers and offer explicit options. They do not soften the analysis to avoid friction. Template:

"HRV: 54 (baseline 68, -21% — 3rd consecutive suppressed day). ACWR: 1.41 (orange zone, >1.3 = elevated injury risk). Today's plan: Wednesday Lower Body B + Threshold Run.

Recommendation: Threshold run carries a non-trivial injury-risk premium today. Options:
1. Swap threshold for easy 8km, keep Lower Body B — preserves strength stimulus
2. Full rest day — move threshold to Saturday slot (light flush movement originally)
3. Proceed as planned — you may be tolerating accumulated load fine

You decide. What's it going to be?"

### Benchmark Testing Protocols

Testing only at block ends (Weeks 4, 8, 12) and terminal deadlines — not periodic. Conditions must be standardized:

- **Strength (squat/bench 1RM estimate):** Top-set from last heavy session of the block works as a proxy (Epley formula from last logged set × reps). Actual 1RM test on deload week Day 1 — fresh, no prior heavy session that day, full warm-up.
- **Max-rep calisthenics (push-ups/pull-ups):** ≥48h post last upper body session, strict form (dead hang to chin-over-bar, chest-to-floor on push-ups), no kipping, video preferred. Single max-effort set counted, annotated in `TrainingLogStore` as type=`benchmark`.
- **Threshold pace:** Take average pace over the last 3 threshold sessions. Do not run a fresh 5km test mid-block. Terminal HM is the actual race test.
- **Speed (400m/3km):** November goals; tested at the November deadline. Sunday mixed-practice sprint sessions give pace data but are not formal tests.

Comparing across blocks: simple absolute improvement vs prior block benchmark. Trend over 3+ blocks gives trajectory.

### Specific, Strict Communication

What separates professional coaching from generic AI feedback is five behaviors:

1. **Name the session:** "Tuesday Upper Body A" not "your strength session"
2. **Name the load:** "Bench top-set should be 3x82.5kg this week" not "increase the weight"
3. **Name the why:** "Because Week 6 is your last accumulation week before the first deload — this is the volume peak, not the intensity peak"
4. **Name the deficit when a session is skipped:** "You have logged 6.2km of threshold volume this week vs 9km target — you're 2.8km short with Thursday and Friday still to go"
5. **Name the consequence:** "If the threshold deficit persists past Week 8, your projected HM finishing time shifts from 1:23 to 1:27 based on current pace trend" — not generic "you need to do more cardio"

Strict does not mean harsh. It means: specific numbers, direct consequence, no softening language, clear options.

### Nutrition / Fueling Coaching

Amit's target is 150g protein / 350g carbs. The blueprint specifies a 6-slot fueling timeline:
1. Pre-AM Run: 30-50g simple carbs + coffee
2. Post-AM Run (Reload): Large carb hit + 3-4 eggs + Vitamin D3+K2 + Omega 3
3. Mid-Day: Lean protein + complex carbs + greens
4. PM Pre-Lift (60min prior): Electrofuel or fruit + Beta-Alanine
5. PM Post-Lift: High protein + easily digestible carbs + Creatine
6. Pre-Bed: Magnesium Glycinate + Zinc + Copper (30-60min before sleep)

Klaus's job is not to optimize these numbers — they are already set. Klaus's job is to flag structural misses: "Post-AM Reload: I see a small meal in the 7-8am window but protein looks light (estimate <20g). Your muscle protein synthesis window from the run closes within 2h. The reload should be your biggest carb hit of the day."

For supplement timing the same principle applies: name the slot, check the window, flag the miss.

Research note (MEDIUM confidence): creatine + beta-alanine co-supplementation does not universally boost concurrent performance beyond either alone, but both have strong individual evidence at Amit's targets — creatine 5g/day post-lift (uptake enhanced by carbs), beta-alanine 3.2-6g/day split dose requires 4-6 weeks to saturate carnosine. Klaus should know these mechanism details to explain why the timing rules matter, not just what they are.

---

## Sources

- Barbell Medicine: Concurrent Training and the Interference Effect — https://www.barbellmedicine.com/blog/concurrent-training-and-the-interference-effect/
- TrainingPeaks: Implementing Block Periodization in Endurance Training — https://www.trainingpeaks.com/blog/implementing-block-periodization/
- TrainingPeaks Coach Blog: Why Athletes Skip Workouts — https://www.trainingpeaks.com/coach-blog/athletes-skip-workouts-improve-compliance/
- Fathom Nutrition: The Hybrid Training Blueprint — https://www.fathomnutrition.com/blogs/all-articles/the-hybrid-training-blueprint-how-to-build-strength-endurance-and-repeatable-performance-without-burning-out
- Lift Living: Nutrition Guide for Hybrid Athletes — https://www.liftlivingofficial.com/post/nutrition-guide-for-hybrid-athletes-fueling-strength-and-endurance
- ACWR optimal zone research (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC8138569/
- Block periodization research (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC7693826/
- Concurrent training meta-analysis (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC11688070/
- Hybrid Athlete Master Blueprint: Oct/Nov Peak V2 — Amit's actual blueprint document (primary source for all facet-specific details)
- TrainHeroic: How to Build a Culture of Athlete Accountability — https://www.trainheroic.com/blog/how-to-build-a-culture-of-athlete-accountability/
- Creatine + Beta-Alanine co-supplementation: https://www.mdpi.com/2072-6643/17/13/2074

---

*Feature research for: Klaus v4.0 — Expert Hybrid-Athlete Coaching*
*Researched: 2026-06-03*
