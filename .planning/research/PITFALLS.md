# Pitfalls Research

**Domain:** Adding expert data-grounded hybrid-athlete coaching to an existing LLM personal agent (Klaus v4.0)
**Researched:** 2026-06-03
**Confidence:** HIGH — analysis drawn directly from the live codebase, shipped v3.0 artifacts, and the blueprint document

---

## Critical Pitfalls

### Pitfall 1: Fabrication Regression — Releasing D-13 Without a Data-Presence Gate

**What goes wrong:**
The D-13 "no invented numbers" guard in `prompts/smart_agent.md` currently blocks Klaus from citing any personalized thresholds when `UserProfileStore` is empty. Releasing it at v4.0 removes that backstop. Without an explicit replacement contract, Klaus defaults to what LLMs do naturally: filling silence with plausible-sounding numbers. He will say "you're about 80% to your 100kg bench goal" when no recent bench press data exists in `TrainingLogStore`, or cite "your typical threshold pace of 3:52/km" when the Garmin history contains only easy runs that week. The original sin is subtle: the guard was binary (empty profile = no numbers), but the v4.0 replacement must be data-presence conditional, not just profile-presence conditional.

**Why it happens:**
The prompt instruction "use real data-grounded numbers" sounds like a constraint but reads to the brain as permission. Without an explicit list of which numbers require which data sources to be non-null, the model pattern-matches from training data ("a typical threshold pace for a 1:25 HM runner is...") and presents it as personalized fact. The blueprint itself provides numeric targets (3:55/km threshold, 100kg bench), which will be ingested into `UserProfileStore` — this makes the problem worse, because the model confuses "goal stated in blueprint" with "current measured performance."

**How to avoid:**
Define a `CoachingDataContract` at the prompt level with two tiers:
- Tier A (blueprint-derived): numbers from `UserProfileStore` (goals, plan targets). Klaus may cite these explicitly as "your stated goal" or "your plan target" — never as current performance.
- Tier B (measurement-derived): numbers from `TrainingLogStore`, Garmin Postgres, or `MealStore`. Klaus cites these only when the relevant record exists within a defined recency window (e.g., lift data ≤ 14 days old, pace data ≤ 7 days old, nutrition data ≤ 2 days old).

When Tier B data is missing or stale, Klaus must name the gap: "I don't have a recent bench press logged, Sir — the last recorded lift was [date]." This is the strict replacement for D-13, not its removal.

Implement a `_validate_coaching_claim(metric, value, source, age_days)` utility that the gather step runs before building the coaching prompt context, so the brain never sees a number without provenance metadata attached.

**Warning signs:**
- Klaus uses a pace or load number without citing a specific date ("your threshold pace is typically around...").
- Klaus states progress percentages toward goals without a benchmark test in `TrainingLogStore`.
- The morning briefing or weekly review cites a target macro split without a recent `MealStore` entry.
- In chat, Klaus answers "how close am I to 100kg bench?" without first calling `get_training_history`.

**Phase to address:**
The blueprint ingestion phase (earliest v4.0 phase). The data-presence contract must be defined and tested before any coaching prompt uses `UserProfileStore` data. The D-13 guard should be REPLACED in the same commit it is removed — not removed and then replaced later.

---

### Pitfall 2: Generic-Advice Regression Despite Curated Knowledge

**What goes wrong:**
The curated expert knowledge (interference effect, periodization, fueling windows) gets injected into the system prompt or coaching context, but coaching output still collapses to generic advice: "make sure you're eating enough protein before heavy lifts, Sir." The knowledge is present but not triggered by specific data. The result is advice that sounds informed but could apply to any hybrid athlete anywhere — not to Amit who had a 7.2-hour sleep, HRV of 58, ran 18km on Friday, and has Upper Body A today with bench press targeting 100kg.

**Why it happens:**
There are two sub-causes. First, the coaching prompt uses the expert knowledge as background context rather than as decision logic — the brain reads it as flavor, not as conditional rules. Second, the gather step assembles data but doesn't distill it into per-session-specific signals before handing to the brain. The brain receives a wall of data and defaults to general commentary rather than connecting "today's session + today's body state → specific actionable coaching point."

**How to avoid:**
Structure the coaching prompt as a decision tree, not a knowledge dump. For each cron (morning briefing, evening check-in, weekly review), the gather step should produce a `coaching_signal` object that pre-joins: today's scheduled session from the blueprint, the relevant biometric state (HRV, sleep, ACWR, body battery), and the most recent performance data for that session's primary lift or pace. The brain's instruction is then: "Given this specific session and this specific body state, give one directive coaching point and one recovery/nutrition action." Forbid introductory summaries — start with the coaching point.

For "strict" to mean something, the prompt must explicitly instruct Klaus to name numbers: "Amit, your bench target for today's working sets is [X]kg. Your last logged set was [Y]kg on [date]. Hit 5 reps at [X]kg before dropping to back-off sets." Generic advice is a coaching failure, not a coaching style.

**Warning signs:**
- Output contains phrases like "make sure to," "it's important to," or "consider" without a specific number or session context.
- The coaching doesn't mention today's specific scheduled session by name.
- Recovery commentary does not cite actual HRV or sleep numbers from today's Garmin data.
- The weekly review gives a verdict ("good week") without referencing specific sessions that were completed or missed.

**Phase to address:**
The coaching prompt engineering phase. Must be validated before any cron is shipped — a dry-run test with real data should produce output that a coach would recognize as session-specific.

---

### Pitfall 3: Rigidity Drift — Blueprint Becomes a Daily Prescription

**What goes wrong:**
The blueprint is ingested and represented such that Klaus treats every session as mandatory and every deviation as a failure. Amit misses Lower Body A on Monday due to a work shift. Klaus flags it in Tuesday's morning briefing, again in the evening check-in, again in the weekly review, and considers it a "missed session" that needs make-up. This turns the guide into a rigid contract and erodes trust, because Amit's stated philosophy is facet-mastery — the blueprint is a framework, not a prison.

The converse failure is equally common: the blueprint is stored as loose guidelines with no weekly structure, and Klaus has no concept of what "on plan" means for a given week, making all coaching vague.

**Why it happens:**
The representation problem: if sessions are stored as scheduled events with a boolean `completed` field, any missed session is structurally a failure. If sessions are stored as a general "weekly template," there is no per-week accountability. Both are wrong.

**How to avoid:**
Represent the blueprint in `UserProfileStore` as a **weekly template** with session priorities (primary/optional) and a **block-level volume target** (e.g., "3 of 4 strength sessions per week, both threshold runs"). Klaus coaches against volume completion and trend, not against day-specific attendance. "You hit 2 of 3 strength sessions this week, Sir — the Lower Body A slot was missed. Worth fitting it before Sunday's mixed session if recovery allows" is the correct register. "You missed Lower Body A on Monday" repeated three times is nagging.

The block-level target also serves as the benchmark: at block end, Klaus measures whether the volume targets were met on average, not whether each individual session was hit.

**Warning signs:**
- Klaus mentions a specific missed session more than once in a 24-hour window across different crons.
- The weekly review counts missed sessions as failures rather than looking at weekly volume completion.
- Klaus proposes a "make-up session" that conflicts with the recovery schedule or Amit's stated schedule.
- The morning briefing says "you have Lower Body A today" when Amit has a work shift from 11:00.

**Phase to address:**
Blueprint schema design phase. The data model for `UserProfileStore.training_template` must encode session priority and block-level targets before any coaching prompt reads it. This is a schema decision that is hard to retrofit.

---

### Pitfall 4: Interference-Effect Overreach — Ignoring the Concurrent Training Stack

**What goes wrong:**
Klaus pushes volume or intensity in one domain (endurance) without accounting for the concurrent load from the other domain (strength). The blueprint's 16-week aerobic progression already prescribes significant long run and threshold volumes. If Klaus's coaching commentary independently recommends "you should add more easy mileage" or "consider a second threshold session," he creates interference-effect violations that the blueprint was specifically designed to avoid. The harder version: Klaus sees low running mileage this week (from Garmin) and recommends additional runs without knowing that a heavy strength block is also in progress.

**Why it happens:**
The Garmin data pipeline and `TrainingLogStore` are separate. The morning briefing gather currently reads them independently. Without a unified weekly load view that sums both strength and endurance stress, Klaus has no signal that total load is already high when looking at either domain in isolation.

**How to avoid:**
Add a `compute_weekly_total_stress(week_start, week_end)` function that combines Garmin ACWR (endurance) with `TrainingLogStore` session count and RPE (if logged) into a single "weekly load tier" (LOW / MODERATE / HIGH / VERY_HIGH). Klaus's coaching recommendations are gated by this tier: at HIGH or above, the recommendation is recovery and quality execution of scheduled sessions, not adding volume. Curated coaching knowledge about interference effect (block the brain from recommending concurrent additions at high load) should be in the expert knowledge layer as explicit decision rules, not just as background context.

**Warning signs:**
- Klaus recommends an additional run or session on a week where ACWR is already above 1.3.
- Klaus comments on "low running volume" without checking whether a heavy strength session was completed that day.
- The evening check-in recommends "easy active recovery run" on a day after a threshold run + upper body session.
- The weekly review suggests increasing threshold volume without accounting for the concurrent strength block phase.

**Phase to address:**
The load aggregation phase, implemented before any recommendation logic. The `compute_weekly_total_stress` function should be a shared utility used by morning briefing, evening check-in, and weekly review gather steps.

---

### Pitfall 5: Over-Coaching / Nagging That Erodes Trust

**What goes wrong:**
Multiple crons each identify a coaching opportunity and all fire independently. Amit receives: a morning briefing with a protein reminder, an autonomous tick at 14:00 noting he hasn't logged lunch macros, an evening check-in repeating the protein point, and a weekly review that opens with nutrition failure. Four touches on the same issue in one day. Klaus becomes noise. Amit starts ignoring him, which is the worst possible outcome for an agent whose value depends on being listened to.

The timing dimension compounds this: Klaus fires a pre-workout nutrition reminder when Amit is already at the gym (20:30 check-in when the PM session starts at 19:30).

**Why it happens:**
The existing `OutreachLogStore` repeat-suppression (D-06) works at the topic_key level for the autonomous tick but does not span crons. Morning briefing, proactive alerts, and weekly review are independent paths that have no shared dedup gate for coaching topics. Each cron sees a valid coaching signal and fires independently.

**How to avoid:**
Extend `OutreachLogStore` (or create a `CoachingTouchStore`) to track per-day coaching topic coverage across all crons. Before any cron adds a coaching point, it checks whether that topic (protein, recovery, session completion) was already addressed in the last N hours. The rule: each major coaching topic gets one primary touch per day, with a single follow-up allowed only if Amit explicitly responded to the first.

For timing: the coaching prompt for each cron must receive the current time and the scheduled session times from the blueprint, and must not surface pre-workout fueling advice after the session start time. This is a data-dependency the gather step must supply.

**Warning signs:**
- The same coaching topic appears in both morning briefing and evening check-in on the same day.
- An autonomous tick fires a coaching nudge on a day already covered by a scheduled cron.
- Amit stops responding to training check-in confirmations — likely over-touch saturation.
- The weekly review opens with a topic already flagged in Monday's check-in without new information.

**Phase to address:**
The cross-cron coaching coordination phase. Should be implemented as part of folding expert coaching into the existing crons, before shipping any proactive coaching behavior. The `OutreachLogStore` extension is a concrete implementation task.

---

### Pitfall 6: Conflict UX — Getting Advise-Don't-Override Wrong in Both Directions

**What goes wrong:**
**Dictating direction:** Klaus sees recovery concern (low HRV) and says "I've moved today's threshold run to tomorrow's slot, Sir." Or: "I'm flagging today's Lower Body A as a skip." Klaus takes a decision that is explicitly Amit's to make.

**Wishy-washy direction:** Klaus sees the same low HRV and says "You might want to consider possibly adjusting today's session if you feel that recovery might not be optimal, though of course that's entirely up to you." This is not coaching; it is noise that Amit will tune out.

The correct register is strict advisory: "Sir, your HRV is 51 — that is below your 7-day baseline of 63. The plan has a threshold run today. My recommendation is to drop it to easy Zone 2 or rest. You call it." One clear recommendation, one explicit acknowledgment of who decides.

**Why it happens:**
LLMs default to either mimicking authority (dictating) or hedging to avoid being wrong (wishy-washy). Without an explicit prompt contract that separates "Klaus recommends" from "Amit decides," the model alternates between the two failure modes depending on phrasing. The recovery-vs-plan conflict case is the highest-stakes scenario because it has real injury implications.

**How to avoid:**
Write a recovery-conflict prompt template with a fixed structure:
1. State the biometric fact with the number and the baseline.
2. State the plan conflict (what is scheduled and why it conflicts).
3. Give a single tiered recommendation (modify / substitute / rest), ranked by severity of the recovery signal.
4. Explicitly close with "Your call, Sir" or equivalent.

This template must be invoked by name in the coaching prompt: "When HRV or ACWR triggers a recovery conflict, use the RECOVERY-CONFLICT template." The template should be in `prompts/` as a standalone include, not embedded in the main coaching system prompt where it gets diluted.

**Warning signs:**
- Klaus uses the word "I've" before a scheduling action during a recovery flag scenario.
- The recovery flag message does not contain a specific number (HRV value, ACWR value).
- The message hedges with "might" or "consider" without a single clear recommendation at the end.
- Klaus provides two equally-weighted options without ranking them ("you could do the threshold run or you could rest").

**Phase to address:**
The conflict UX is a prompt contract that must be drafted in the coaching prompt engineering phase and validated with recovery-scenario dry runs before any coaching cron ships.

---

### Pitfall 7: Block and Benchmark Ambiguity

**What goes wrong:**
**Ambiguous block boundaries:** The block concept is introduced but the system has no explicit block start/end date in `UserProfileStore`. Klaus gives coaching commentary that references "this block" without knowing when the block started or ends. End-of-block benchmark prompts fire at the wrong time (too early, too late, or never).

**Non-comparable benchmark tests:** Amit does a bench press test on a day where he had a threshold run that morning and poor sleep. Klaus records the result and compares it to the previous block's result from a rested day. The comparison is meaningless and potentially demoralizing.

**Demanding periodic testing:** The 16-week aerobic table has specific weekly targets. Klaus interprets the week numbers as testing prompts and asks Amit to "test his 3k pace" in Week 6 because the plan says "Capacity Build." Testing is only at block ends and at the Oct/Nov deadlines — not mid-plan.

**Why it happens:**
Block tracking requires a data model that isn't in `UserProfileStore` yet. Without it, the brain infers blocks from the 16-week table, which contains intermediate targets (threshold paces, long run distances) that look like test benchmarks but are training prescriptions.

**How to avoid:**
Add explicit `block_start_date`, `block_end_date`, and `benchmark_session_type` fields to `UserProfileStore`. Benchmark prompts are triggered only when today's date is within 3 days of `block_end_date` or within 7 days of the Oct/Nov deadline dates. The benchmark prompt must include a "test validity" checklist in the gather step: session was not preceded by a heavy training day, HRV is above 70% of 7-day baseline, ACWR is below 1.2. If the checklist fails, Klaus defers and explains why.

For the 16-week table: store it as a training prescription lookup, not a benchmark schedule. The weekly threshold volumes and long run distances are coaching targets, not test events. Distinguish in the data model.

**Warning signs:**
- Klaus asks Amit to test his 1:25 HM pace in Week 3 of the plan.
- The weekly review compares benchmark results without noting biometric state at time of test.
- Klaus references "this block" without being able to state the block start date when asked.
- A block-end benchmark fires on a day where Garmin shows poor sleep or high ACWR.

**Phase to address:**
Block data model phase, implemented before benchmark prompt logic. The `UserProfileStore` schema extension for block tracking must precede any block-aware coaching logic.

---

### Pitfall 8: Knowledge Staleness and Hallucinated Sports Science

**What goes wrong:**
The curated coaching knowledge layer contains claims that are either wrong, contested, or outdated. Examples: specific HRV thresholds ("HRV below 50 means rest"), exact interference-effect recovery windows ("48 hours between strength and endurance"), or optimal protein timing windows ("within 30 minutes post-workout is critical"). The brain injects these as authoritative coaching points. Because they are in the system prompt as "expert knowledge," they feel more authoritative than spontaneous generation, but they are equally subject to training-data errors.

The harder case: the brain extends the curated knowledge via in-context reasoning and generates derivative claims that were never in the curated layer. "Since you're in Week 9 (Deep Waters), your lactate threshold should be approaching 3:48/km" — plausible-sounding, not verified, never stated in the blueprint.

**Why it happens:**
LLMs are trained to be helpful and authoritative. When given coaching knowledge as system context, the model treats it as a permission slip to make strong claims in that domain. The curated layer provides the domain framing; the model fills in specifics from training data.

**How to avoid:**
Three-part defense:
1. Source every claim in the curated knowledge layer with a confidence tier (HIGH = from the blueprint directly, MEDIUM = well-established sports science consensus, LOW = specific thresholds from research that may not apply to Amit). LOW-confidence claims are prefaced with "research suggests" not stated as fact.
2. Explicitly forbid derivative reasoning beyond the curated layer: "Do not extrapolate expected physiological adaptations that are not directly stated in the user's blueprint or coaching knowledge layer."
3. Separate the blueprint's prescribed targets (3:52/km threshold in Weeks 5-8) from "what Amit's body will actually do" — Klaus can report the plan target but must not claim the body will achieve it on schedule.

**Warning signs:**
- Klaus cites a specific HRV threshold (e.g., "below 55") without referencing a source — this is a fabricated personalized rule.
- Klaus predicts fitness improvement rates ("by Week 10 your VO2max should be...") — these are derivative claims.
- Klaus quotes research statistics ("athletes who follow concurrent training show 15% higher...") without a source in the curated layer.
- The curated knowledge layer contains threshold numbers that don't appear in the blueprint.

**Phase to address:**
Knowledge curation phase. Every claim in the curated layer must be tagged with its source before it enters the system prompt. This is a one-time authoring discipline that protects against ongoing hallucination.

---

### Pitfall 9: Scope Creep Toward a Full Periodized Training App

**What goes wrong:**
The v4.0 feature list is already at the edge of scope: blueprint ingestion, expert knowledge, D-13 release, block tracking, benchmark management, strict coaching across all crons. The scope creep version adds: auto-generating modified weekly plans, weekly volume prescription adjustments, automatic session rescheduling, injury risk scoring, HRV-triggered plan modifications. These are features of a training app, not a coaching agent. Each one requires its own data model, logic, and UX contract. They pull implementation away from what actually matters: making the existing crons say something specific and useful.

**Why it happens:**
The milestone goal ("transform Klaus from qualitative to expert coaching") is open-ended enough that "what would an expert do?" naturally expands toward what a full training app does. The planning process includes phrases like "progress toward dated goals" and "per-facet improvement" that can rationalize increasingly complex tracking features.

**How to avoid:**
The v4.0 test: "Does Klaus tell Amit what to do today and hold him to it?" If yes, the feature ships. "Does Klaus compute a derived training metric that Amit would never directly act on?" If yes, it does not ship in v4.0. Specifically: no auto-rescheduling, no volume prescription adjustments, no injury risk scoring. Klaus coaches the blueprint as given, does not modify it. Plan modifications are Amit's decision, documented via `update_training_profile`.

The benchmark for scope is the morning briefing and evening check-in — those are the two moments where coaching is most valuable. If a feature does not make either cron more specific, it is not v4.0 scope.

**Warning signs:**
- A feature requires modifying the blueprint programmatically rather than reading it.
- A feature requires a new Postgres table or schema beyond `UserProfileStore` and `BenchmarkStore`.
- The implementation discussion uses the phrase "auto-adjust the plan."
- A phase in the roadmap is titled "plan management" or "training prescriptions."

**Phase to address:**
Scope control is a milestone-level decision, not a phase. The v4.0 kickoff requirements document must explicitly list what is NOT in scope with the same specificity as what is.

---

### Pitfall 10: V3.0 Cron Regression — Existing Flows Break When Coaching Context Expands

**What goes wrong:**
The morning briefing, proactive alerts, and weekly review prompts are expanded to include blueprint context, expert knowledge, and coaching directives. The additions push the effective prompt length past what the gather step was designed to supply. Missing data keys that were previously benign (empty `UserProfileStore`) now cause prompt template failures or the brain silently falls back to generic text because the expected context is absent.

The `{training_profile}` placeholder in `prompts/smart_agent.md` is already there (line 4 of the live file) but is currently populated with empty profile data. When v4.0 populates it with a full blueprint, existing v3.0 tests that assert specific response patterns may break because the system prompt content changes.

The 21:30 cron (`proactive_alerts.py`) currently handles training check-in as a folded behavior. Adding expert coaching to this path without regression testing the existing weather/overload/travel-time logic risks breaking the non-coaching alerts.

**Why it happens:**
The v3.0 crons were designed with a specific gather+compose contract. Each one was tested with the empty profile as a known state. V4.0 changes the profile state without revisiting the gather contracts or test coverage.

**How to avoid:**
Before shipping any v4.0 coaching feature to a live cron:
1. Run the cron's dry-run path with the fully-populated `UserProfileStore` and assert that non-coaching output (weather alerts, schedule conflicts) is unchanged.
2. Add a `coaching_available: bool` flag to each cron's gather output — when False (data missing), the cron falls back to v3.0 qualitative behavior, not a broken template.
3. Pin the existing 630+ test suite and require zero new failures before any v4.0 cron goes live.
4. The `{training_profile}` injection in `smart_agent.md` should be reviewed for token budget impact — a full blueprint plus expert knowledge layer may push individual cron prompts over efficient context windows for `gemini-3.5-flash`.

**Warning signs:**
- A dry-run of the morning briefing with populated profile raises a `KeyError` or produces `None` in a template field.
- The 21:30 cron's weather alert disappears when training coaching is added to the same prompt.
- The weekly review's gather step times out because additional `UserProfileStore` reads add latency.
- Test suite failures in `tests/` after blueprint ingestion code is introduced.

**Phase to address:**
Every v4.0 phase that modifies an existing cron must include an explicit regression step with dry-run validation before deployment.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Storing blueprint as raw markdown in `UserProfileStore` | Fast to implement, no schema work | Brain must parse structure at inference time — inconsistent results, context bloat | Never — parse to structured fields at ingest time |
| Reusing the same coaching context blob across all crons | Single source of truth for blueprint data | Morning briefing, evening check-in, and weekly review need different coaching context subsets; a monolithic blob makes each prompt unfocused | Never for the final architecture; acceptable for a first-pass spike only |
| Skipping data-presence validation and trusting the prompt to "handle" missing data | Faster prompt authoring | Brain hallucinates when context fields are None — this is exactly the fabrication-regression failure | Never — validate data presence in the gather step, not in the prompt |
| No cross-cron coaching topic dedup (each cron is independent) | No coordination logic to build | Nagging / over-touch — degrades trust | Never after v4.0 coaching goes live |
| Hardcoding benchmark dates from the 16-week table | Simple to implement | Table is week-relative; if Amit's plan start date shifts, all benchmark triggers are wrong | Never — store plan_start_date and compute block boundaries dynamically |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `UserProfileStore` + `TrainingLogStore` | Reading them in separate tool calls and letting the brain join them in the response | Pre-join in the gather step: produce a `coaching_context` object that already associates the scheduled session with the most recent performance for that session type |
| Garmin Postgres + `TrainingLogStore` | Using Garmin activity data as a proxy for session completion | Garmin records the GPS activity; `TrainingLogStore` records the logged check-in. They can disagree (Amit runs without logging, or logs without syncing Garmin). Treat as two independent signals with explicit precedence rules |
| Blueprint weekly table (16-week) + current week number | Computing week number from today's date without a stored plan start date | Store `plan_start_date` in `UserProfileStore` at blueprint ingestion time; always derive week number from `(today - plan_start_date).days // 7 + 1` |
| `MealStore` + coaching timing | Coaching on nutrition data that is from the day before because HealthKit sync runs on push | Always stamp nutrition coaching with the data's `updated_at` timestamp; if data is >18 hours old, note "based on yesterday's log" |
| `OutreachLogStore` dedup gate | Assuming the existing D-06 gate prevents coaching over-touch | D-06 uses `topic_key` for the autonomous tick only. Morning briefing, proactive alerts, and weekly review are separate code paths that bypass this gate entirely |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Injecting the full blueprint + expert knowledge into every smart agent turn (not just coaching crons) | Higher latency per turn, higher token cost for non-coaching requests | Only inject `{training_profile}` into cron prompts and explicit coaching queries; use `get_training_profile` tool for on-demand access | From the first deploy of the expanded system prompt |
| Running all data sources in sequence in the coaching gather step | Morning briefing latency spikes to 8-12 seconds | Use `asyncio.gather` for independent sources (Garmin, MealStore, TrainingLogStore, UserProfileStore) — they are already isolated by try/except in `weekly_training_review.py` | On the first live cron tick with full coaching context |
| Storing benchmark history with full activity payloads | Firestore document size creep | Store only the relevant metrics per benchmark (date, session_type, key_metric, biometric_state) — not the full Garmin activity JSON | After 3-4 blocks of data accumulate |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Recovery-conflict message without a single clear recommendation | Amit re-reads it looking for the answer, can't find it, ignores it | Structure: fact → plan conflict → ranked recommendation → "your call" — always one clear recommendation ranked first |
| Benchmark prompt on a day Amit is clearly tired (HRV + sleep both poor) | Amit attempts the benchmark in a bad state, gets a demoralizing number | Gate benchmark prompts on biometric validity check; if state is poor, defer to next valid day and explain why |
| Coaching commentary that opens with a summary of what Klaus observed | Amit reads past the preamble and misses the action | Lead with the action or the number, not the observation: "3 reps at 90kg today, Sir — you're 10kg behind plan target" not "I noticed your last bench session..." |
| Weekly review that scores the week before acknowledging what went well | Framing effect — negative scoring sticks even when performance was good | Lead with facts, then trajectory, then the one area to adjust — no "score" framing |
| Using the blueprint's goal dates (Oct/Nov) as deadlines in coaching messages | Creates anxiety / pressure-framing that conflicts with facet-mastery philosophy | Frame goals as "dated north-stars" not contracts: "Your October target is 100kg bench — current trend puts you at [X] by that date" not "You have 6 weeks to hit 100kg" |

---

## "Looks Done But Isn't" Checklist

- [ ] **D-13 replacement:** The no-fabrication guard is removed AND the data-presence contract is live in the same commit — verify by testing a coaching query when `TrainingLogStore` has no recent bench data.
- [ ] **Blueprint ingestion:** `UserProfileStore` fields are populated AND the plan start date, block boundaries, and goal dates are stored as structured fields, not as raw markdown text.
- [ ] **Cross-cron dedup:** The coaching topic gate covers morning briefing + evening check-in + weekly review + autonomous tick — not just the autonomous tick.
- [ ] **Recovery-conflict template:** The advise-don't-override template is tested with a real recovery scenario (low HRV day with threshold run scheduled) and produces a clear ranked recommendation without dictating or hedging.
- [ ] **Block boundaries:** `block_start_date` and `block_end_date` are in `UserProfileStore` AND benchmark prompts are gated on those dates, not on week number from the 16-week table.
- [ ] **Regression:** All 630+ existing tests pass after blueprint ingestion code ships. Morning briefing and proactive alert dry-runs with full profile produce the same non-coaching outputs as before.
- [ ] **Expert knowledge tier tags:** Every claim in the curated coaching knowledge layer has a confidence tier (HIGH/MEDIUM/LOW) and LOW-confidence claims are prefaced in coaching output.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Fabrication regression discovered post-deploy | MEDIUM | Re-add data-presence validation to gather step; hot-patch the coaching prompt with explicit "ONLY cite numbers when source is provided in context" instruction; audit last 7 days of coaching output for invented numbers |
| Blueprint stored as raw markdown, brain parsing inconsistently | HIGH | Re-ingest blueprint into structured `UserProfileStore` fields; this requires a migration script and redeployment |
| Cross-cron nagging discovered after user complains | LOW | Implement `CoachingTouchStore` dedup gate; requires one new Firestore document structure and gather-step additions to each cron |
| Block boundary ambiguity — blocks never fire | MEDIUM | Add `plan_start_date` to `UserProfileStore` and recompute all block boundaries; requires a backfill if Klaus has already given coaching comments referencing "this block" |
| v3.0 cron regression (weather alerts disappear) | HIGH | Revert the cron prompt change; re-architect as a coaching section appended after the existing alert logic rather than merged into it |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Fabrication regression (D-13 release without data-presence gate) | Blueprint ingestion + UserProfileStore population phase | Dry-run coaching query with empty `TrainingLogStore` returns "no recent data" not an invented number |
| Generic advice despite curated knowledge | Coaching prompt engineering phase | Dry-run morning briefing output names a specific session, specific numbers, and today's biometric state |
| Rigidity drift — blueprint becomes prescription | Blueprint schema design phase | Weekly review treats 3-of-4 sessions completed as success, not failure; no duplicate session-missed mentions in 24h window |
| Interference-effect overreach | Load aggregation phase | `compute_weekly_total_stress` function exists and gates volume recommendations at HIGH load |
| Over-coaching / nagging | Cross-cron coordination phase | Same coaching topic does not appear in both morning briefing and evening check-in on the same day |
| Conflict UX — advise-don't-override wrong | Coaching prompt engineering phase | Recovery conflict test scenario produces: fact + conflict + single ranked recommendation + explicit "your call" |
| Block/benchmark ambiguity | Block data model phase | Benchmark prompt fires only within 3 days of stored `block_end_date`; biometric validity gate defers if HRV or ACWR fail threshold |
| Hallucinated sports science | Knowledge curation phase | Every number in the curated layer traces to either the blueprint or a tagged source; no derivative physiological predictions in coaching output |
| Scope creep | Milestone kickoff requirements | Out-of-scope list explicitly names: no auto-rescheduling, no volume prescription adjustments, no injury risk scoring |
| V3.0 cron regression | Every phase that modifies an existing cron | Dry-run with full profile passes; 630+ test suite shows zero new failures |

---

## Sources

- Live codebase analysis: `prompts/smart_agent.md` (D-13 guard, `{training_profile}` placeholder), `core/autonomous.py` (D-06 dedup gate, `OutreachLogStore`), `core/weekly_training_review.py` (gather pattern), `core/morning_briefing.py`
- `.planning/PROJECT.md` — v4.0 goal definition, D-13 release context, facet-mastery stance, recovery-advise-not-override invariant
- `/Users/amitgrupper/Downloads/Hybrid Athlete Master Blueprint_ Oct_Nov Peak V2.md` — blueprint structure, 16-week aerobic table, fueling architecture, session prescriptions
- `CLAUDE.md` — system invariants, model architecture, cost-gating pattern (Layer 0/1/2), existing cron inventory
- `memory/firestore_db.py` — `UserProfileStore` scaffold (currently stub), store architecture patterns

---
*Pitfalls research for: v4.0 Specific Training & Nutrition Coaching — adding expert data-grounded coaching to Klaus*
*Researched: 2026-06-03*
