# Phase 24: Strict Coaching Integration + Nutrition Accountability - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

**What this phase delivers (COACH-03, COACH-04, COACH-05, NUTR-01, NUTR-02, NUTR-03, PROG-01, PROG-03, PROG-04):**

The v4.0 integration capstone. The expert/specific coaching substrate (Phase 22) and the block/benchmark state (Phase 23) are now *folded into every existing coaching touchpoint* so coaching is **strict, specific, proactive AND reactive, and non-repetitive**. Six concrete deliverables:

1. **Strict skip/off-plan pushback (COACH-03)** — names the session, the deficit in concrete units (km/sets), and a directional consequence to the goal timeline; no softening/hedging; escalates on repeated misses.
2. **Recovery-vs-plan option framing (COACH-04)** — biometric fact + number → plan conflict → exactly one ranked recommendation → explicit "your call, Sir". Advise, never override; never hedge with a menu.
3. **Cross-cron dedup gate (COACH-05)** — the same coaching topic fires at most once per day across morning briefing + 21:30 check-in + Sunday weekly review. The new shared primitive of this phase.
4. **Nutrition + supplement accountability in the 21:30 check-in (NUTR-01/02/03)** — macro adherence (150g protein / 350g carb) on a meaningful-gap threshold; 6-slot fueling-timeline structural-miss detection from `MealStore` timestamps; supplement-timing gaps inferred via the carrier fueling slots.
5. **Session-quality annotation at log time (PROG-04)** — captured by *deriving* quality from existing signals (Garmin self-eval + RPE + notes), not a new input.
6. **Per-facet progress + integrated framing (PROG-01, PROG-03)** — Sunday weekly review reports per-facet within-block status + session-quality trend; morning briefing weaves named session + recovery + fueling reminder into one integrated block.

**Out of scope (do NOT build here):**
- **Pace-to-deadline trend *projection* against Oct/Nov goals → Phase 25 (PROG-02).** Phase 24 reports current/within-block status and directional consequences only; it never computes a dated "on track / N weeks behind" projection.
- **Per-facet improvement *trajectory* / deadline framing in the weekly review → Phase 25.** Phase 24 reports raw within-block trend + quality trend, not a projection to the dated goal.
- **A new Strava integration** — researched and explicitly rejected this phase (see D-19/canonical refs). No new OAuth/ingest pipeline.
- **Daily macro micro-optimization / CICO calorie math** (out-of-scope per REQUIREMENTS) — structural critique of the *targets* is in scope (COACH-07 overlap), per-day "add 12g carbs" swaps are not.
- **Silent/autonomous plan modification** — Klaus recommends, Amit adopts via `update_plan` (locked PLAN-03 / Phase 22 D-12).
- **A new explicit session-quality keyboard/tap** — quality is derived, not collected via a new UI step.
- Any new cron jobs, backends, or dependencies.

</domain>

<decisions>
## Implementation Decisions

### Cross-cron dedup gate (COACH-05)
- **D-01 — Topic-key granularity = `category:subject`.** e.g. `protein-miss`, `skipped-session:threshold-run`, `recovery-conflict:bench`, `fueling-miss:post-am-run`. Two genuinely distinct issues (a missed run AND a missed lift) can both fire; the same issue can't fire twice. Avoids both over-suppression (coarse) and under-suppression (fully specific).
- **D-02 — Hard-suppress, with one escalation only on materially-worsened state.** Once a topic was raised today, the later cron skips it (literal SC-3). Exception: if the underlying condition persists/worsens with *new* data (e.g. still un-fueled hours after the morning reminder), allow **one** escalation that references the earlier flag. No nagging, but not silent on a real worsening problem.
- **D-03 — Gate applies to proactive crons ONLY.** Morning briefing / 21:30 / weekly review are gated. **Reactive chat always answers fully** and is never suppressed by "already said it in a cron". A reactive answer also does NOT burn the topic for later crons (chat and cron dedup are independent). Matches SC-3, which names only the crons.
- **D-04 — Daily reset + condition-driven clear.** Per-day doc keyed to Asia/Jerusalem calendar day (reuse the existing `OutreachLogStore` per-day pattern) → resets at midnight. A topic naturally stops firing mid-day when its underlying condition resolves (session logged → no longer a skip; meal logged → no longer a miss), because the gather step no longer detects it. No explicit "mark resolved" write needed.

### Strict pushback & recovery conflict (COACH-03, COACH-04)
- **D-05 — Consequence framing = directional, blueprint-anchored, NO dated projection.** Skip pushback names the real-unit deficit + a qualitative-but-grounded consequence tied to the block goal, e.g. *"2nd threshold run skipped this week — ~12km off your Week-3 aerobic target. Miss the volume now and the Oct half-marathon pace slips."* Real numbers from blueprint/logs; the dated "N weeks behind" projection is **Phase 25 (PROG-02)**, not here.
- **D-06 — Strictness escalates on repeated misses (across days).** First miss = firm flag. Repeat misses sharpen tone + name the pattern and compounding cost (*"3rd skipped lift in 10 days — this is a block-level problem, not a bad day"*). Plays with the dedup escalation rule (D-02).
- **D-07 — Recovery-vs-plan = always exactly one ranked recommendation.** Even in a toss-up Klaus commits to a single ranked rec (the expert's job), then hands the decision back: *"HRV 58, 71% of baseline, against a top-set bench day. I'd swap to technique work at 70% and push the heavy triple to Thursday — but your call, Sir."* Never a menu (that's the hedging SC-2 kills), never dictating.
- **D-08 — Trigger surface.** Skip/off-plan pushback fires **primary in the 21:30 training check-in** (where the day's sessions resolve); the **morning briefing recaps an unresolved prior-day miss** if still relevant (subject to dedup). Recovery-vs-plan conflict fires **wherever first detected** (morning briefing for today's session, 21:30 for tonight's). **Reactive chat always.**

### Nutrition & supplement accountability (NUTR-01/02/03)
- **D-09 — Macro adherence = meaningful-gap threshold only (NUTR-01).** Flag today's `MealStore` totals only on a structurally meaningful shortfall (e.g. protein < ~80% of 150g, or carbs badly short on a long-run day) — never marginal swaps. Stays out of the out-of-scope daily micro-optimization. May note when a shortfall is part of a multi-day pattern. (Exact thresholds → Claude's discretion / research.)
- **D-10 — Fueling slots anchored to actual training events; flag key structural slots (NUTR-02).** Map `MealStore` meal timestamps to slot windows defined **relative to the day's real AM-run/PM-lift times** (from calendar/Garmin), not fixed clock times. Flag the performance-critical structural slots — **#2 post-AM-run reload, #5 PM post-lift rebuild**, plus **#6 pre-bed** (for supplements). Soft slots (pre-run snack #1, lunch #3, pre-lift #4) are not nagged. Matches SC-4's "missed post-AM-run reload" example.
- **D-11 — Supplements ride on their carrier fueling slot (NUTR-03, inference/advisory).** No supplement log exists. A supplement gap is surfaced as part of its carrier-slot miss — e.g. post-AM-run reload missing → *"— and that's your D3+K2/Omega-3 gone with it."* Never claims to *know* Amit didn't take them. **Pre-bed Mg/Zn/Cu (#6) is the one standalone reminder** since it has no macro footprint to ride on.
- **D-12 — Structural target-critique is pattern-triggered and kept distinct from daily behavior flags (NUTR-01 × COACH-07).** Daily misses = behavior flag (NUTR). The structural critique of the *target itself* (*"150g protein is low for your volume — I'd argue 180–190g"*) fires only when a persistent pattern or volume/target mismatch shows the target is the problem. Occasional, blunt-expert, advise-never-rewrite (Phase 22 D-10/11/12), subject to dedup so it isn't repeated nightly. The two are different messages with different triggers.

### Session-quality annotation (PROG-04)
- **D-13 — Quality is DERIVED, not collected via a new tap.** No new keyboard step. Klaus derives a session-quality read from signals that already exist: **Garmin self-eval (Feel + Perceived Effort) + the check-in RPE + the session notes.** Honors Amit's intent ("you already have the RPE and how I felt from the Garmin data") with zero added friction.
- **D-14 — Use Garmin, not Strava (research-backed — see D-19).** Garmin already captures per-activity **Feel (5-point: Very Weak→Very Strong)** and **Perceived Effort (0–10)** and is already integrated (`garmin_tool` + Postgres backfill). Strava is rejected this phase: its official MCP is read-only/subscription-gated/end-user-chat-only (unusable server-side), and its REST API doesn't reliably expose the perceived-exertion field.
- **D-15 — Quality available on both interactive and silent-synced sessions.** Because it's derived (partly from Garmin), even silently-synced sessions get a quality read — coverage is broader than just the sessions Amit tapped through. Where no signal exists, quality is null and the weekly-review trend handles missing values gracefully (reports over the sessions that have it). No post-hoc prompt chasing quality.
- **D-16 — Research/ingest sub-task:** confirm whether Garmin's self-eval fields (likely `directWorkoutFeel` / `directWorkoutRpe` in the activity JSON) are already in our `garmin_tool` reads / Postgres backfill; if not, a small ingest add to surface them. Researcher pins exact field names against our real data.

### Progress surfacing (PROG-01, PROG-03)
- **D-17 — Sunday weekly review = within-block status + trend, NO deadline projection (PROG-01).** Reports strength top-set trend, threshold volume vs target, ACWR, and the session-quality trend — all block-relative ("Week 3 of Block 1"). Describes current/within-block movement only. The "on track for the Oct goal" deadline projection is **Phase 25 (PROG-02)**.
- **D-18 — Morning briefing = one integrated block (PROG-03).** Weave today's named session + recovery state + the relevant fueling reminder into a single integrated block, not three separate labeled lines.

### Folded Todos
- **`coaching-query-iteration-cap-double-send` (bug, P22 live verification):** data-verification-heavy coaching queries trip the smart-loop tool-iteration cap → user sees the "more processing steps" fallback AND the correct answer (double-send). Phase 24 makes crons + reactive chat far more data-heavy (macro adherence, fueling-slot mapping, skip-deficit math, benchmark facets), so this regresses further. Fix within this phase's coaching integration (raise the cap, suppress the fallback when a substantive answer was produced, and/or short-circuit the repository sweep once the first authoritative source confirms no log). Acceptance: a data-heavy query returns a single correct message, anti-fabrication (SC-1) still holds. Full context: the todo file.
- **`phase-22-code-review-advisory` → WR-02 (`read_coaching_guide` wrong-section):** the fuzzy fallback substring-matches a single word and returns the first hit with no confidence signal (e.g. `set` matches `top-set-strength`), risking a wrong deep section fed to the brain as authoritative. Phase 24 calls `read_coaching_guide` in more strict-coaching contexts, so harden it: require an unambiguous/specific match, otherwise return the not-found JSON so the brain falls back to the slim core. (WR-03 / IN-01/02/03 from that todo NOT folded — see Reviewed Todos.)

### Claude's Discretion
- Exact macro-shortfall thresholds (D-09: e.g. the protein-<80% line, the long-run-day carb rule) and how "structurally meaningful" is operationalized.
- The exact slot-window widths around the AM-run/PM-lift anchors (D-10) and how the anchor times are resolved (calendar event vs Garmin activity start).
- Whether the cross-cron dedup gate reuses `OutreachLogStore` directly or adds a thin coaching-topic store mirroring its per-day shape (D-04) — as long as it's per-day, never-raises, and Asia/Jerusalem-keyed.
- The exact `category:subject` vocabulary/enum for topic keys (D-01) and where the dedup check sits in each cron's compose path.
- How session-quality is derived from the RPE + Garmin Feel/Perceived-Effort + notes signal mix (D-13) — the mapping/heuristic and the stored field shape on the training-log entry.
- The precise prompt wording for strict pushback, the recovery single-ranked-rec format, and the structural-critique escalation, across the affected prompt files.
- How the "one integrated block" morning-briefing framing (D-18) is expressed in `prompts/morning_briefing.md`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase governance & requirements
- `.planning/ROADMAP.md` § "Phase 24" — the 6 success criteria (strict skip pushback with concrete deficit + consequence; recovery-conflict format; cross-cron dedup; fueling-slot structural-miss flagging; integrated morning briefing; per-facet weekly review + quality trends).
- `.planning/REQUIREMENTS.md` — COACH-03/04/05, NUTR-01/02/03, PROG-01/03/04 full text; the "Out of Scope" rows (periodic/mid-block testing; coach-override; daily macro micro-optimization; silent plan modification; Klaus parsing meals from chat text); "Milestone anchor" Week 1 = Sun 2026-06-21.

### Source-of-truth plan data this phase reads against
- `docs/hybrid_athlete_blueprint.md` §1 (dated Oct/Nov goals), §2 (AM/PM split), §6 (**Fueling Architecture — the 6 named slots + embedded supplements**: 1 Pre-AM Run, 2 Post-AM Run reload [D3+K2/Omega-3], 3 midday, 4 PM Pre-Lift [Beta-Alanine], 5 PM Post-Lift rebuild [Creatine], 6 Pre-Bed [Mg-Glycinate/Zinc/Copper]). Slot mapping (D-10/D-11) is built directly off §6.
- `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`, `.planning/research/FEATURES.md` — v4.0 kickoff research (the locked decisions for coaching integration, the cron-surfacing hooks, and the dedup-via-topic_key pattern).

### Prior-phase context this phase builds on (read for carried-forward decisions)
- `.planning/phases/22-expert-coaching-knowledge-d-13-release/22-CONTEXT.md` — Tier A/B recency contract (D-06/07/08), slim-core + `read_coaching_guide` delivery (D-04/05), blunt-expert critique posture + advise-never-rewrite (D-10/11/12), specificity bar (D-13). All of this is the substrate Phase 24 folds into the crons.
- `.planning/phases/23-block-benchmark-tracking/23-CONTEXT.md` — `BlockStore`/`BenchmarkStore`, `get_current()` week-N-of-16 framing, the `benchmark_due` 21:30 state machine, the HRV<70%/ACWR>1.2 validity gate. The block context Phase 24's coaching messages frame against.
- `.planning/phases/21-living-plan-ingestion/21-CONTEXT.md` — `UserProfileStore` structured schema (`nutrition_targets` 150g/350g, `supplement_schedule`, `fueling_timeline`, `weekly_split`, `plan_start_date`) and `update_plan` (the COACH-07 adoption path).

### Existing code to modify (integration points)
- `core/proactive_alerts.py` — `run_proactive_alerts()` (the 21:30 cron). Add nutrition/supplement accountability gather+flagging and strict-pushback composition; the **cross-cron dedup gate** lives here too (note the existing `_already_sent` per-date dedup and the "runs BEFORE the dedup gate" structure at ~line 197; the new topic-level gate is a finer-grained layer on top).
- `core/training_checkin.py` — the 21:30 check-in skip/RPE/notes flow (`run_training_checkin`, `handle_rpe_callback`, `attach_note`, `_slot_for`). Strict skip pushback + the derived session-quality field (D-13) attach here. NOTE `_slot_for` is for *training* events — mapping *meals* to the 6 fueling slots (D-10) is new work.
- `core/morning_briefing.py` — `_gather_data()` + compose. Integrated session+recovery+fueling block (D-18); prior-day unresolved-miss recap (D-08).
- `core/weekly_training_review.py` — `_gather_week_data()` + compose. Per-facet within-block status + session-quality trend (D-17).
- `memory/firestore_db.py` — `OutreachLogStore` (line 1291, per-day `entries:[{topic_key,...}]` doc + today's-topic_keys reader) is the substrate for the dedup gate (D-04). `MealStore` (line 574, `get_day`) for macro totals + meal timestamps. `TrainingLogStore` (line 764) for the derived session-quality field + session-quality history.
- `mcp_tools/garmin_tool.py` + the Garmin Postgres backfill (`scripts/ingest_garmin_zip.py`) — the source for the Feel/Perceived-Effort self-eval fields (D-14/D-16). Confirm/surface `directWorkoutFeel` / `directWorkoutRpe`.
- `core/tools.py` — `read_coaching_guide` handler (WR-02 hardening, folded todo); `core/main.py` `_run_smart_loop` tool-iteration cap (double-send bug, folded todo).
- `prompts/proactive_alert.md`, `prompts/morning_briefing.md`, `prompts/weekly_training_review.md`, `prompts/smart_agent.md` — surface the new strict-pushback / nutrition / dedup / integrated-framing behavior.

### Folded-todo source files
- `coaching-query-iteration-cap-double-send.md` (capture todo) — double-send bug full symptom/root-cause/fix-options/acceptance.
- `phase-22-code-review-advisory.md` (capture todo) → WR-02 detail; full report at `.planning/phases/22-expert-coaching-knowledge-d-13-release/22-REVIEW.md`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `OutreachLogStore` (`memory/firestore_db.py:1291`) — per-day `outreach_log/{YYYY-MM-DD}` doc with `entries:[{topic_key,time,draft,final,tick_index}]` and a "return today's topic_keys" reader. The autonomous engine already uses `topic_key` per-day repeat-suppression (`core/autonomous.py`, `_synthesize_topic_key`). Direct substrate/template for the cross-cron dedup gate (D-04).
- Existing 21:30 check-in flow (`core/training_checkin.py`): RPE inline-keyboard → log → notes follow-up (`/skip`) → `attach_note` (merge=True). Session-quality derivation (D-13) hooks the existing log path; no new keyboard.
- `MealStore.get_day` (`memory/firestore_db.py:574`) — already powers both meal read paths (server-side HealthKit aggregation, fiber threaded; updated_at stripped for JSON safety). Source for macro totals + per-meal timestamps for slot mapping.
- Garmin integration (`mcp_tools/garmin_tool.py`, Postgres 3-yr backfill) — already wired; the Feel/Perceived-Effort fields are an extension of existing reads, not a new integration.

### Established Patterns
- Crons gather state best-effort and degrade silently when a store is empty (pre-cycle / no data) — mirror for nutrition/supplement/quality gather.
- Block/week math is always derived from `plan_start_date`, never stored (Phase 23 D-03); "Week N of 16" framing already in all three crons.
- Tier A/B recency contract (Phase 22 D-06): macros citable ≤2 days, lifts ≤14, pace ≤7, Garmin recovery always fresh — governs what numbers the strict/nutrition messages may state.
- **Recalled feedback:** Firestore `SERVER_TIMESTAMP` → `DatetimeWithNanoseconds` breaks `json.dumps` in read tools — ISO-convert in any new store read path (`_jsonsafe_doc`).
- **Recalled feedback (HealthKit):** cross-macro grouping is done server-side via `(start_date, food_item)`; do not attempt client-side meal alignment.

### Integration Points
- New: cross-cron dedup gate (topic-key layer) spanning `proactive_alerts.py` / `morning_briefing.py` / `weekly_training_review.py`, backed by an `OutreachLog`-style per-day store.
- New: meal→fueling-slot mapping (training-anchored windows) + macro-gap + supplement-inference flagging in the 21:30 path.
- New: derived session-quality field on the training-log entry + its weekly-review trend.
- Modified: strict-pushback + recovery-single-rec + structural-critique behavior across the four prompt files; integrated morning-briefing framing.
- Fix: `read_coaching_guide` fuzzy-match hardening (WR-02); smart-loop double-send (tool-iteration cap / fallback suppression).

</code_context>

<specifics>
## Specific Ideas

- **Amit's session-quality intent (verbatim steer):** *"you already have the rpe and how I felt from the garmin data or strava data if that's more comfortable for interactive and daily data."* → derive, don't add a tap (D-13). Strava researched and rejected (D-14/D-19); Garmin Feel+Perceived-Effort is the source.
- **Skip-pushback example (target register):** *"2nd threshold run skipped this week — ~12km off your Week-3 aerobic target. Miss the volume now and the Oct half-marathon pace slips."* (directional consequence, no dated projection).
- **Recovery-conflict example (target register):** *"HRV 58, 71% of baseline, against a top-set bench day. I'd swap to technique work at 70% and push the heavy triple to Thursday — but your call, Sir."*
- **Supplement-rider example:** post-AM-run reload missing → *"— and that's your D3+K2/Omega-3 gone with it."*
- **Strava research finding (D-19):** the official Strava MCP is remote/read-only/subscription-gated and works only through end-user AI chat clients (Claude/ChatGPT) — not server-to-server; the Strava REST API doesn't reliably expose `perceived_exertion` (not writable, not dependably readable); Strava tightened third-party API access alongside the MCP launch. Conclusion: Strava cannot deliver server-side feel data to a headless Cloud Run agent; Garmin can. Sources: tredict.com/blog/strava_mcp_server, support.strava.com Perceived Exertion, communityhub.strava.com (update RPE via API), Garmin forums (Perceived Effort field).

</specifics>

<deferred>
## Deferred Ideas

- **Pace-to-deadline trend projection + per-facet improvement trajectory / "on track / N weeks behind" framing → Phase 25 (PROG-02).** Phase 24 deliberately stops at directional consequences and within-block trends.
- **Strava integration** — rejected for Phase 24 (D-14/D-19). If Strava ever opens genuine server-side access to the perceived-exertion/feel field, revisit as its own phase; not currently actionable.
- **3k / 400m maximal-sprint benchmarks near the November deadline** (carried from Phase 23 deferred) — not a Phase 24 item.

### Reviewed Todos (not folded)
- **`phase-22-code-review-advisory` → WR-03 + IN-01/02/03:** the slim-core size-guard code/test mismatch (WR-03) and the info-level items (handler "never raises" leaning on `dispatch()`, per-call `import re`, duplicated compose-time injection helper). Reviewed but NOT folded — they're advisory/cosmetic and don't touch Phase 24's behavior surface. The IN-03 "duplicated compose-time injection across morning_briefing.py and proactive_alerts.py" item may naturally get touched when those files are modified, but it's not a scope commitment.

</deferred>

---

*Phase: 24-strict-coaching-integration-nutrition-accountability*
*Context gathered: 2026-06-06*
