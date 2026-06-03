# Architecture Research

**Domain:** Klaus v4.0 — Specific Training & Nutrition Coaching integration
**Researched:** 2026-06-03
**Confidence:** HIGH (all integration points verified from live source code)

---

## System Overview

The v4.0 features integrate across four horizontal layers of the existing architecture:

```
┌─────────────────────────────────────────────────────────────────────┐
│                       PROMPT LAYER                                   │
│  smart_agent.md  morning_briefing.md  proactive_alert.md            │
│  weekly_training_review.md  autonomous.md  autonomous_triage.md     │
│  {training_profile} → expanded to {training_profile} + {plan}       │
├─────────────────────────────────────────────────────────────────────┤
│                       ORCHESTRATION LAYER                            │
│  core/main.py: render_smart_system()  ← add _load_coaching_guide()  │
│  core/weekly_training_review.py  ← add block/benchmark gather       │
│  core/morning_briefing.py        ← add block state surface          │
│  core/proactive_alerts.py        ← add benchmark trigger check      │
│  core/training_checkin.py        ← remove D-13 qualitative guard    │
├─────────────────────────────────────────────────────────────────────┤
│                        TOOLS LAYER                                   │
│  core/tools.py                                                       │
│  NEW brain-direct: get_plan, get_block_status, update_plan          │
│  NEW brain-direct: log_benchmark, get_benchmark_history             │
│  Extend: update_training_profile (already exists)                    │
├─────────────────────────────────────────────────────────────────────┤
│                       PERSISTENCE LAYER                              │
│  memory/firestore_db.py                                              │
│  UserProfileStore (users/amit) — expand scaffold with v4.0 fields   │
│  NEW BlockStore   (training_blocks/{block_id})                       │
│  NEW BenchmarkStore (benchmarks/{YYYY-MM-DD}_{facet})               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Integration Point 1: Living Plan in UserProfileStore

### Current state

`UserProfileStore` (`memory/firestore_db.py`, lines 93–168) holds a single Firestore doc at `users/amit`. The current scaffold (`_SCAFFOLD`, line 113) has three fields: `athletic_goals: []`, `training_constraints: []`, `recovery_preferences: {}`. The doc is bootstrapped on startup by `AgentOrchestrator.__init__` (line 233–235 of `core/main.py`) via `bootstrap_if_empty()`.

`render_smart_system` (`core/main.py`, lines 239–307) already renders a `{training_profile}` placeholder that reads from `UserProfileStore.load()` and omits the block when the profile is empty. The substitution happens at line 305: `.replace("{training_profile}", training_profile_snippet)`.

`prompts/smart_agent.md` already contains the `{training_profile}` placeholder at line 8.

### What v4.0 needs

Expand the `UserProfileStore` document to carry the full blueprint fields. Extend `_SCAFFOLD` in `firestore_db.py` — do not create a new collection. The existing store, tool, and prompt placeholder wire is already in place.

**New scaffold fields to add:**

```python
_SCAFFOLD = {
    # existing
    "athletic_goals": [],
    "training_constraints": [],
    "recovery_preferences": {},
    "schema_version": 1,
    # v4.0 additions
    "dated_goals": {},        # {"oct_bench_1rm_kg": 100, "oct_squat_1rm_kg": 120,
                              #  "oct_half_marathon_min": 85, "nov_pushups": 125,
                              #  "nov_pullups": 35, "nov_3k_pace_sec": 570,
                              #  "nov_400m_sec": 55}
    "weekly_split": {},       # {"mon": "lower_strength", "tue": "run_easy", ...}
    "nutrition_targets": {},  # {"protein_g": 150, "carbs_g": 350, ...}
    "supplement_schedule": [],# [{"name": "creatine", "timing": "post_workout", ...}]
    "facet_priorities": [],   # ordered list: ["strength", "endurance", "power", ...]
    "fueling_timeline": {},   # {"pre_workout_min": 60, "post_workout_min": 30, ...}
    "current_block_id": None, # FK → BlockStore doc id
}
```

**How to keep it a flexible guide, not a rigid prescription:**

The `{training_profile}` block in `render_smart_system` becomes the context Klaus reasons _from_, not a ruleset he enforces. Achieve this in two places:

1. In `render_smart_system` (`core/main.py`): keep the current "non-empty fields only" rendering but relabel the header to `**Coaching blueprint:**` instead of `**Training profile:**`. This signals to the brain that this is reference material, not a binding schedule.

2. In `prompts/smart_agent.md`: replace the existing "If the training profile is empty..." block (lines 85–100) with a v4.0 coaching posture paragraph that explicitly frames the blueprint as a guide. State that the brain should use targets as intent anchors, name them when giving feedback, and flag when current data diverges — but that Amit decides on plan changes. One new sentence on recovery-vs-plan conflicts: "When recovery data conflicts with the plan, advise the deviation and offer both paths; Amit decides."

### Modified files

- `memory/firestore_db.py`: expand `UserProfileStore._SCAFFOLD`
- `core/main.py`: rename `training_profile_snippet` header string to `Coaching blueprint:`
- `prompts/smart_agent.md`: replace training coaching section (lines 77–100)

---

## Integration Point 2: Curated Coaching Knowledge

### Options analysis

**Option A — Prompt-embedded principles doc (static string in smart_agent.md):**
Pre-render a concise (~400-token) coaching principles block directly in `prompts/smart_agent.md`. Covers: concurrent strength/endurance interference, periodization logic (blocks vs linear), fueling science summary, how to read ACWR for hybrid athletes.

**Option B — Pinecone "coaching" namespace recalled per-turn:**
Store coaching principles as `kind="coaching"` vectors in `memory/pinecone_db.py`. The brain calls `recall(query, kind="coaching")` before formulating advice.

**Option C — Brain-direct retrieval tool `get_coaching_knowledge(topic)`:**
A new brain-direct tool that reads a static file or a Firestore doc keyed by topic.

**Recommendation: Option A.** The coaching principles are stable, compact, and always relevant when Klaus is in a training coaching context. Pinecone retrieval (Option B) adds latency and a recall-or-miss risk on every coaching turn. A separate tool (Option C) adds a tool-use round-trip when the principles should simply be in context. The existing codebase already includes the `{self_md}` pattern (stable content injected once at startup, placed before dynamic content for Gemini prompt caching) — coaching knowledge follows the same pattern.

### Integration path

Add a new placeholder `{coaching_guide}` to `prompts/smart_agent.md` immediately before the `TRAINING & ATHLETIC COACHING` section. In `core/main.py`:

1. Add `self._coaching_guide = _load_coaching_guide()` to `AgentOrchestrator.__init__`, where `_load_coaching_guide()` reads `docs/COACHING_GUIDE.md` at startup (same pattern as `_load_self_md()`).
2. In `render_smart_system`, add `.replace("{coaching_guide}", self._coaching_guide)` alongside the other replacements. Place it after `{self_md}` but before `{training_profile}` in the stable-content prefix.

**For cron compose prompts** (morning_briefing, proactive_alert, weekly_training_review): these compose functions instantiate their own `LLMClient` and pass a system prompt without going through `render_smart_system`. Append a condensed version of the coaching guide directly into those prompt files in a clearly delimited section. The weekly_training_review already appends `meal_audit.md` this way (line 233 of `core/weekly_training_review.py`); use the same pattern.

### New file

`docs/COACHING_GUIDE.md` — the authoritative coaching knowledge doc. Single source of truth. Section headers: Hybrid Athlete Principles, Interference Effect Management, Periodization & Block Structure, Fueling Science, How to Read Recovery Signals. Target ~600 tokens — substantial enough to be genuinely expert, short enough to not degrade prompt caching.

### Modified files

- `core/main.py`: `AgentOrchestrator.__init__` + `render_smart_system` (add `{coaching_guide}` rendering)
- `prompts/smart_agent.md`: add `{coaching_guide}` placeholder before training section
- `prompts/morning_briefing.md`: append condensed coaching context section
- `prompts/proactive_alert.md`: append condensed coaching context section
- `prompts/weekly_training_review.md`: append full coaching guide (same pattern as meal_audit append in `weekly_training_review.py`)

---

## Integration Point 3: Releasing the D-13 Guard

### Where the guard lives today

The D-13 "no invented numbers" guard is implemented in four places:

**1. `core/training_checkin.py`, `compute_recovery_concern()` (line 161):**
The function returns `None` rather than fabricated metrics. The guard here is correct and stays. This is not D-13 — it's the right behavior (don't emit a concern when there's no concern). D-13 release does not touch this function.

**2. `core/morning_briefing.py` (line 246):**
`recovery_concern` key is silently omitted when `compute_recovery_concern` returns `None`. This logic also stays — it prevents a phantom "all clear" section. The guard is about omitting the section, not about qualitative-only language. This is not the target of D-13 release.

**3. `prompts/morning_briefing.md` (lines 138–143):**
```
**Empty training profile guardrail (D-13):** When the `UserProfileStore` profile is
empty or the user has no configured targets, suggest only qualitative modifications:
"keep today's session submaximal", "favour aerobic over anaerobic", "drop a set or two".
**Never invent** a specific weight, HR zone, HR cap, pace target, or rep count.
```
**This is the primary D-13 prompt guard.** Once the profile is populated with real targets, this paragraph should be replaced with: "When profile targets are available, name them. Compare current data to targets directly. On recovery conflicts, offer both the plan target and the adjusted approach; Amit decides."

**4. `prompts/proactive_alert.md` (lines 22–23):**
```
**Empty training profile guardrail (D-13):** With no configured targets, suggest
qualitative modifications only: "keep it submaximal", "favour aerobic over anaerobic",
"drop a set or two". Never invent a specific weight, HR zone, or pace.
```
**Same release pattern** — replace the guard with a "use named targets from profile" instruction.

**5. `prompts/smart_agent.md` (lines 85–100):**
The `TRAINING & ATHLETIC COACHING` section contains the per-conversation version of D-13 (lines 87–93: "If the training profile is empty... do NOT invent thresholds, targets, or scheduling buffers"). This block is replaced entirely as part of Integration Point 1 above.

**6. `prompts/weekly_training_review.md` (line 51):**
```
"grounded in this week's actual data... JARVIS voice, direct, no fabricated numeric targets (no specific weights, HR zones, pace targets)."
```
The phrase "no specific weights, HR zones, pace targets" stays as a fabrication guard — the brain should not invent numbers it doesn't have. But it should be amended: "Name targets from the coaching blueprint when comparing actual performance to plan." This is a refinement, not a removal.

### What D-13 release means in practice

D-13 release is not a blanket "you can say any number now" toggle. It means:

- Numbers from `UserProfileStore.dated_goals` (e.g., 100 kg bench target) can be named when comparing against current TrainingLogStore or benchmark data.
- Current lift estimates from `BenchmarkStore` (see Integration Point 4) can be named.
- Pace targets from `nutrition_targets` can be named when critiquing meals.
- Numbers still cannot be invented. The guard shifts from "no numbers at all" to "only data-grounded numbers" — a refinement, not a removal.

### Modified files

- `prompts/morning_briefing.md`: replace D-13 guard paragraph (lines 138–143) with data-grounded-targets instruction
- `prompts/proactive_alert.md`: replace D-13 guard paragraph (lines 22–23) similarly
- `prompts/smart_agent.md`: training section replaced as per Integration Point 1
- `prompts/weekly_training_review.md`: amend line 51 to add "name blueprint targets when comparing"

**No Python code changes required for D-13 release.** The guard is purely prompt-level. `compute_recovery_concern` in `training_checkin.py` returns `None` when appropriate — that discipline is unchanged and correct.

---

## Integration Point 4: Block and Benchmark Tracking

### Store design

**Use two new Firestore stores, separate from TrainingLogStore.** Do not extend TrainingLogStore for blocks or benchmarks — they have different schemas, retention needs, and query patterns.

**BlockStore** (`memory/firestore_db.py`):
- Collection: `training_blocks`
- Document ID: `{YYYY-MM-DD}_{label}` e.g. `2026-06-03_strength_phase1`
- Fields: `block_id` (str), `label` (str), `start_date` (YYYY-MM-DD), `end_date` (YYYY-MM-DD or None), `focus_facets` (list), `weekly_split_override` (dict or None), `status` (active / complete / abandoned), `notes` (str), `benchmark_due` (bool), `created_at`, `updated_at`
- Operations: `start_block(label, start_date, focus_facets)`, `end_block(block_id, end_date)`, `get_current()` (returns the active block or None), `get_all()` (for trend view)
- `get_current()` queries where `status == "active"`; `filter=FieldFilter("status", "==", "active")` (same composite-index pattern as `FollowupStore.list_due`)

**BenchmarkStore** (`memory/firestore_db.py`):
- Collection: `benchmarks`
- Document ID: `{YYYY-MM-DD}_{facet}` e.g. `2026-06-15_bench_press_1rm`
- Fields: `date` (YYYY-MM-DD), `facet` (str), `value` (float), `unit` (str: kg / reps / sec / min), `block_id` (str, FK to BlockStore), `notes` (str), `updated_at`
- Operations: `log_benchmark(date, facet, value, unit, block_id, notes)`, `get_facet_history(facet, n)` (last n results for trend), `get_block_benchmarks(block_id)` (all benchmarks for a block)
- Idempotent: `{date}_{facet}` doc ID means re-logging the same facet on the same day overwrites with `merge=True`

**Why not extend TrainingLogStore?**
TrainingLogStore is keyed `{date}_{slot}` for session-level entries. Benchmarks are per-facet per-date, not per-session slot. Blocks are entirely different entities. Mixing them in one collection would require `doc.type` filtering on full collection scans (all reads currently stream the whole collection). Two dedicated stores keep each store's scan cheap and readable.

**Why not Postgres?**
The 3-year Garmin history lives in Postgres because it was a bulk historical import. Blocks and benchmarks are small, user-created, and need the same lazy-singleton + never-raises read discipline as the other Firestore stores. Consistency with existing stores matters more than raw query flexibility here.

### New tools in core/tools.py

All new tools follow the existing `_HANDLERS` dispatch pattern. They are added to `TOOL_SCHEMAS`, registered in `SMART_AGENT_DIRECT_TOOLS`, excluded from `WORKER_TOOL_SCHEMAS`, and dispatched in `_HANDLERS`.

| Tool | Type | Handler | Purpose |
|------|------|---------|---------|
| `get_plan` | brain-direct | `_handle_get_plan` | Full `UserProfileStore.load()` + `BlockStore.get_current()` in one call |
| `get_block_status` | brain-direct | `_handle_get_block_status` | Current block + its benchmarks + trend vs prior block |
| `update_plan` | brain-direct | `_handle_update_plan` | Merge patch into `UserProfileStore` (new fields only; wraps existing `update_training_profile`) |
| `log_benchmark` | brain-direct | `_handle_log_benchmark` | Write to `BenchmarkStore` |
| `get_benchmark_history` | brain-direct | `_handle_get_benchmark_history` | `BenchmarkStore.get_facet_history(facet, n)` |
| `start_block` | brain-direct | `_handle_start_block` | `BlockStore.start_block(...)` + sets `UserProfileStore.current_block_id` |
| `end_block` | brain-direct | `_handle_end_block` | `BlockStore.end_block(...)` + clears `UserProfileStore.current_block_id` |

Note: `update_plan` can coexist with `update_training_profile` — they operate on the same document. `update_plan` targets v4.0 fields (`dated_goals`, `weekly_split`, etc.) while `update_training_profile` targets v3.0 fields (`athletic_goals`, `training_constraints`, `recovery_preferences`). Either tool calls `UserProfileStore.update(patch)` with `merge=True`, so they are safe to use interchangeably.

### Surfacing block state in the crons

**morning_briefing.py — `_gather_data()`:**
Add a best-effort block state gather alongside the existing nutrition and recovery gather. Read `BlockStore.get_current()`. If a block is active and `benchmark_due == True`, include a `"block"` key in the briefing data dict with `{label, days_elapsed, benchmark_due: true}`. The `morning_briefing.md` prompt picks this up and can add a brief note ("Block {label} is at its benchmark window, sir").

**proactive_alerts.py — `run_proactive_alerts()`:**
After the training check-in call (line 103), add a best-effort block-end check: if `BlockStore.get_current()` returns a block with `end_date <= tomorrow` and `benchmark_due == False`, set `benchmark_due = True` in the BlockStore and include a `"benchmark_reminder"` key in `alerts_context`. The `proactive_alert.md` prompt surfaces it as an alert.

**weekly_training_review.py — `_gather_week_data()`:**
Add `BlockStore.get_current()` and `BenchmarkStore.get_block_benchmarks(block_id)` to the gather dict. Pass as `current_block` and `block_benchmarks` keys. The `weekly_training_review.md` prompt uses these to surface per-facet improvement trends across blocks.

### End-of-block benchmark trigger

No new cron required. Use a state machine embedded in `BlockStore`: the `benchmark_due` field on a block doc is the trigger state. The existing `proactive_alerts` cron (21:30) checks the flag and sends the reminder. Amit logs the benchmark through a brain-direct conversation (`log_benchmark` tool). No separate scheduler job needed — this reuses the existing cron infrastructure.

The trigger logic:
1. Block is created with `benchmark_due: False`
2. At end_date or at user request, `benchmark_due` is set to `True` (either by the proactive alert cron or the brain)
3. `proactive_alert.md` surfaces the benchmark reminder when the flag is set
4. Brain calls `log_benchmark` after Amit does the test session
5. Brain calls `end_block` to close the block

---

## Integration Point 5: Proactive and Reactive Strictness

### Changed cron behaviors

**morning_briefing.py:**
The `compute_recovery_concern` call (line 237) already surfaces recovery data. Post-D-13 release, the morning briefing prompt can name the plan's target session from `weekly_split[today_weekday]` and compare it to the recovery concern level. Add `block_state` to the briefing data dict (from Integration Point 4). No Python logic changes needed beyond the data gather.

**proactive_alerts.py:**
After D-13 release, the `recovery_concern` dict already has `level`, `acwr`, `hrv_status`, `sleep_score`, `intensity`. The prompt change in `proactive_alert.md` (Integration Point 3) is sufficient to allow named targets. Add the `benchmark_reminder` check (Integration Point 4). No new cron logic.

**weekly_training_review.py:**
Add `block_benchmarks` and `current_block` to `_gather_week_data()`. The prompt already has the right structure for trend commentary. Post-D-13 release, the prompt can reference dated goals by name.

**core/training_checkin.py:**
`compute_recovery_concern` stays unchanged. The function already provides `level`, `acwr`, `hrv_status`, `sleep_score`, `intensity` — this is data-grounded. The qualitative guard in the prompt is what changes, not this function.

### New brain behaviors in chat

Post-D-13 release, in `prompts/smart_agent.md`:
- The brain calls `get_plan` when starting any training-related conversation to get full context in one call (profile + current block)
- The brain calls `get_block_status` when asked about progress or trends
- The brain critiques off-plan training by comparing `TrainingLogStore` history to `weekly_split` from the profile
- The brain names supplement adherence gaps when nutrition data is available

---

## Component Boundaries (New vs Modified)

| Component | Status | Changes |
|-----------|--------|---------|
| `memory/firestore_db.py::UserProfileStore` | Modified | Expand `_SCAFFOLD` with v4.0 fields; no interface change |
| `memory/firestore_db.py::BlockStore` | New | New class, same pattern as TrainingLogStore |
| `memory/firestore_db.py::BenchmarkStore` | New | New class, same pattern as TrainingLogStore |
| `core/main.py::AgentOrchestrator` | Modified | Add `_coaching_guide` field; add `{coaching_guide}` rendering in `render_smart_system` |
| `core/main.py::_load_coaching_guide` | New | Module-level helper, same shape as `_load_self_md()` |
| `core/tools.py::TOOL_SCHEMAS` | Modified | Add 7 new schemas: `get_plan`, `get_block_status`, `update_plan`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block` |
| `core/tools.py::SMART_AGENT_DIRECT_TOOLS` | Modified | Add the 7 new tools |
| `core/tools.py::_HANDLERS` | Modified | Add 7 new handler lambdas |
| `core/tools.py` | Modified | Add 7 handler functions `_handle_get_plan`, etc. |
| `core/weekly_training_review.py::_gather_week_data` | Modified | Add block + benchmark gather |
| `core/morning_briefing.py::_gather_data` | Modified | Add block state gather |
| `core/proactive_alerts.py::run_proactive_alerts` | Modified | Add block-end benchmark trigger check |
| `docs/COACHING_GUIDE.md` | New | Coaching knowledge doc; read at startup by `_load_coaching_guide()` |
| `prompts/smart_agent.md` | Modified | Replace training section; add `{coaching_guide}` placeholder |
| `prompts/morning_briefing.md` | Modified | Replace D-13 guard; add block state rendering; append coaching context |
| `prompts/proactive_alert.md` | Modified | Replace D-13 guard; add benchmark reminder rendering; append coaching context |
| `prompts/weekly_training_review.md` | Modified | Amend target-naming instruction; add block/benchmark trend rendering |

---

## Data Flow

### Chat path (reactive coaching)

```
User message (Telegram)
    ↓
interfaces/_router.py → AgentOrchestrator.handle_message()
    ↓
render_smart_system() injects:
  {self_md}, {coaching_guide}, {training_profile}, {self_state},
  {journal_digest}, {today_date}
    ↓
Brain (gemini-3.5-flash) sees full coaching context in system prompt
    ↓
Brain calls get_plan (brain-direct) → UserProfileStore.load() + BlockStore.get_current()
    ↓
Brain formulates data-grounded coaching response
  (names targets from dated_goals, compares to TrainingLogStore / BenchmarkStore)
    ↓
Brain optionally calls log_benchmark / start_block / end_block
```

### Cron path (proactive coaching)

```
Cloud Scheduler → POST /cron/proactive-alerts (21:30)
    ↓
run_proactive_alerts():
  1. run_training_checkin()  [existing]
  2. compute_recovery_concern() [existing, returns data-grounded dict]
  3. BlockStore.get_current() → check benchmark_due flag  [new]
  4. Compose alerts_context with recovery_concern + benchmark_reminder
    ↓
_compose_alert() → brain with proactive_alert.md
  (names plan targets post-D-13 release)
    ↓
send_and_inject()
```

### Block lifecycle

```
Amit: "Start a new strength block"
  → Brain calls start_block(label, start_date, focus_facets)
  → BlockStore creates doc, sets UserProfileStore.current_block_id
  → Brain calls update_plan with weekly_split for the block

[During block: daily sessions logged to TrainingLogStore as before]

At end_date (detected by proactive_alerts 21:30 cron):
  → BlockStore.benchmark_due set to True
  → Evening alert surfaces benchmark reminder

Amit does benchmark sessions → Brain calls log_benchmark(date, facet, value, unit, block_id)
  → BenchmarkStore records result

Amit: "End the block"
  → Brain calls end_block(block_id, end_date)
  → BlockStore.status = "complete", benchmark_due = False
  → UserProfileStore.current_block_id = None
```

---

## Build Order (Dependency-Respecting Sequence)

Dependencies flow: plan ingestion unlocks D-13 release; D-13 release unlocks named-number coaching; block/benchmark tracking unlocks trend coaching; all of the above together unlock strict proactive+reactive coaching.

### Phase A: Living Plan ingestion

1. Expand `UserProfileStore._SCAFFOLD` (`memory/firestore_db.py`)
2. Update `render_smart_system` header string (`core/main.py`)
3. Update `prompts/smart_agent.md` training section — remove D-13 empty-profile guard, add v4.0 coaching posture
4. Add `update_plan` tool schema + handler + SMART_AGENT_DIRECT_TOOLS entry (`core/tools.py`) — extends the existing `update_training_profile` pattern
5. Ingest Amit's blueprint via `update_plan` (or direct Firestore write + bootstrap verification)

**Gate:** UserProfileStore.load() returns non-empty `dated_goals`, `weekly_split`, `nutrition_targets`.

### Phase B: Coaching knowledge layer

6. Create `docs/COACHING_GUIDE.md`
7. Add `_load_coaching_guide()` helper to `core/main.py`
8. Add `{coaching_guide}` field + rendering to `AgentOrchestrator.__init__` and `render_smart_system` (`core/main.py`)
9. Add `{coaching_guide}` placeholder to `prompts/smart_agent.md`
10. Append condensed coaching context to `prompts/morning_briefing.md`, `prompts/proactive_alert.md`, `prompts/weekly_training_review.md`

**Gate:** Brain demonstrates expert coaching reasoning in chat (no generic platitudes).

### Phase C: D-13 release

11. Replace D-13 guard in `prompts/morning_briefing.md` with data-grounded-targets instruction
12. Replace D-13 guard in `prompts/proactive_alert.md` similarly
13. Amend `prompts/weekly_training_review.md` to add blueprint target naming

**Dependency:** Phase A must complete first. D-13 can only release after the profile has real targets — otherwise the prompt instruction "name targets from profile" produces empty or fabricated output.

**Gate:** Morning briefing and evening alert name specific targets from the profile when recovery concern fires. Weekly review references dated goals.

### Phase D: Block and benchmark tracking

14. Add `BlockStore` class to `memory/firestore_db.py` (same pattern as `TrainingLogStore`)
15. Add `BenchmarkStore` class to `memory/firestore_db.py`
16. Add 5 new tool schemas + handlers + direct-tool registrations (`core/tools.py`): `get_plan`, `get_block_status`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block`
17. Add block state gather to `core/morning_briefing.py::_gather_data()`
18. Add block benchmark gather to `core/weekly_training_review.py::_gather_week_data()`
19. Add benchmark trigger check to `core/proactive_alerts.py::run_proactive_alerts()`
20. Update `prompts/morning_briefing.md` with block state rendering section
21. Update `prompts/weekly_training_review.md` with block/benchmark trend section
22. Update `prompts/proactive_alert.md` with benchmark reminder section
23. Create the first training block via `start_block` tool

**Dependency:** Phase A must complete (profile needs `current_block_id` field). Phase C should complete first so the brain can name targets when surfacing benchmark trends.

### Phase E: Strict proactive + reactive coaching (emerges from Phases A–D)

No new Python logic needed. This phase is the behavioral outcome of Phases A–D working together:
- Chat coaching: smart_agent.md + get_plan + get_block_status
- Morning briefing: data-grounded recovery with named targets
- Evening alert: benchmark reminders + named plan targets
- Weekly review: per-facet improvement trends across blocks

Validate by running through representative scenarios: recovery conflict, off-plan nutrition critique, mid-block progress question, end-of-block benchmark trigger.

---

## Architectural Patterns to Follow

### Pattern 1: Omit-empty discipline (existing — extend)

**What:** Stores read with `.load()` / `.get()` return `{}` or `[]` on failure; prompts silently omit sections when data keys are absent. No placeholder text.
**Apply to:** All new block/benchmark data in morning briefing, weekly review, proactive alerts. If `BlockStore.get_current()` returns None, the block section is absent from the briefing data dict. The prompt is never called with a `"block": None` key — it simply doesn't have the key.

### Pattern 2: Best-effort gather wrapping (existing — extend)

**What:** In `_gather_week_data` (weekly_training_review.py), every data source is wrapped in `try/except`; failures set the key to `None` and log at WARNING. The brain handles error copy.
**Apply to:** All new gather calls in morning_briefing.py, weekly_training_review.py, proactive_alerts.py.

### Pattern 3: Brain-direct tools for judgment, worker for execution (existing — extend)

**What:** Tools requiring coaching judgment (`get_plan`, `get_block_status`, `log_benchmark`, `start_block`, `end_block`) are brain-direct. They go in `SMART_AGENT_DIRECT_TOOLS` and are excluded from `WORKER_TOOL_SCHEMAS`.
**Rationale:** Block lifecycle decisions (when to start/end a block, whether a benchmark result is valid) require the brain's judgment, not just data execution.

### Pattern 4: Startup-cached stable content (existing — extend)

**What:** `_load_self_md()` reads `docs/SELF.md` once at startup; the result is stored on the orchestrator and injected into every prompt without further file I/O.
**Apply to:** `_load_coaching_guide()` reads `docs/COACHING_GUIDE.md` the same way. Coaching knowledge is stable; no per-message I/O.

---

## Anti-Patterns

### Anti-Pattern 1: Adding a new cron job for block-end benchmark triggers

**What people do:** Create a new Cloud Scheduler job that fires at block end to prompt a benchmark.
**Why it's wrong:** The proactive_alerts cron at 21:30 already runs daily and has the send_and_inject infrastructure. Adding a new scheduler job (8th job) for a state that can be detected by a flag check in the existing 21:30 cron is over-engineering.
**Do this instead:** Set `benchmark_due = True` on the block doc when the end condition is met; the 21:30 cron reads the flag and includes a benchmark reminder in the alert.

### Anti-Pattern 2: Embedding D-13 release as a Python feature flag

**What people do:** Add an `if profile.dated_goals: release_d13 = True` code branch that selects between two prompt strings or two code paths.
**Why it's wrong:** The guard is purely prompt-level. Adding Python branching introduces a dual-path complexity that has no behavioral benefit — the prompt already handles the empty-profile case gracefully with "ask the user to state their preference".
**Do this instead:** Replace the D-13 guard paragraphs in the prompts with data-grounded-targets instructions. The brain naturally applies qualitative language when no targets exist and named targets when they do.

### Anti-Pattern 3: Storing benchmark history in TrainingLogStore

**What people do:** Add a `benchmark: true` flag to TrainingLogStore sessions and query by that flag.
**Why it's wrong:** TrainingLogStore scans the whole collection (no Firestore index on `benchmark`) and returns all sessions sorted by date. Filtering by a flag in Python on every benchmark query is inefficient and makes the schema ambiguous. Benchmarks are not sessions — they are per-facet measurement events.
**Do this instead:** Dedicated `BenchmarkStore` with doc IDs keyed `{date}_{facet}`. Single-purpose collection, clean schema, no scan overhead.

### Anti-Pattern 4: Pinecone for coaching knowledge retrieval

**What people do:** Embed coaching principles in Pinecone and recall them per turn.
**Why it's wrong:** Coaching principles are ~600 tokens, always relevant, and change infrequently. Pinecone retrieval adds ~200ms latency per turn, has a recall-or-miss failure mode, and splits authoritative coaching context across an embedding store that cannot be easily reviewed or updated.
**Do this instead:** Inject coaching knowledge as stable prompt context at startup (same as SELF.md). Edit `docs/COACHING_GUIDE.md` when knowledge needs updating; the next deploy picks it up.

---

## Scaling Considerations

This is a single-user system. Scaling is not the concern. The relevant constraint is **prompt token budget**:

| Addition | Token cost | Mitigation |
|----------|------------|------------|
| `{coaching_guide}` in smart_agent.md | ~600 tokens (stable, cached) | Gemini prompt caching on shared prefix — paid once |
| `{training_profile}` expanded fields | ~200–400 tokens (stable, cached) | Same caching prefix benefit |
| `block_state` in morning_briefing data | ~100 tokens | Per-cron; briefing is already ~1000 tokens |
| `block_benchmarks` in weekly_review data | ~300–600 tokens | Weekly, not daily; acceptable |

Total smart_agent.md prompt grows by ~800–1000 tokens. Well within Gemini 3.5 Flash's context window and prompt caching benefit.

---

## Sources

- `core/main.py` — `AgentOrchestrator.__init__`, `render_smart_system` (lines 239–307)
- `core/tools.py` — `TOOL_SCHEMAS`, `SMART_AGENT_DIRECT_TOOLS`, `_HANDLERS` (lines 39–57, 651–827, 1433–1471)
- `core/weekly_training_review.py` — `_gather_week_data`, `_compose_review` (lines 42–266)
- `core/training_checkin.py` — `compute_recovery_concern`, `RECOVERY_THRESHOLDS` (lines 65–232)
- `core/proactive_alerts.py` — `run_proactive_alerts`, D-13 guard comments (lines 91–175)
- `memory/firestore_db.py` — `UserProfileStore`, `TrainingLogStore`, `MealStore` (lines 93–879)
- `prompts/smart_agent.md` — `{training_profile}` placeholder, D-13 training section (lines 1–164)
- `prompts/morning_briefing.md` — D-13 guard (lines 138–143), section structure
- `prompts/proactive_alert.md` — D-13 guard (lines 22–23)
- `prompts/weekly_training_review.md` — qualitative-only coaching instruction (line 51)
- `.planning/PROJECT.md` — v4.0 goal statement and feature targets

---
*Architecture research for: Klaus v4.0 Specific Training & Nutrition Coaching*
*Researched: 2026-06-03*
