# Phase 24: Strict Coaching Integration + Nutrition Accountability - Research

**Researched:** 2026-06-06
**Domain:** Integration — coaching crons, nutrition, training-log quality, cross-cron dedup gate
**Confidence:** HIGH (all findings verified against live source code; no external API dependencies)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Topic-key granularity = `category:subject` (e.g. `protein-miss`, `skipped-session:threshold-run`)
- D-02: Hard-suppress on dedup; one escalation allowed on materially-worsened state
- D-03: Gate on proactive crons only; reactive chat never suppressed and does NOT burn the topic
- D-04: Daily reset keyed to Asia/Jerusalem day; reuse OutreachLogStore per-day pattern
- D-05: Consequence framing = directional + blueprint-anchored; no dated projection (PROG-02 scope)
- D-06: Strictness escalates on repeated misses across days
- D-07: Recovery-vs-plan = exactly one ranked recommendation; never a menu
- D-08: Skip pushback primary in 21:30; morning briefing recaps unresolved prior-day miss
- D-09: Macro adherence = meaningful-gap threshold only (no daily micro-optimization)
- D-10: Fueling slots anchored to actual training event times from calendar/Garmin; flag slots #2, #5, #6
- D-11: Supplements ride on their carrier fueling slot; #6 pre-bed Mg/Zn/Cu is standalone
- D-12: Structural target critique is pattern-triggered and distinct from daily behavior flags
- D-13: Session quality is DERIVED (Garmin Feel + PE + RPE + notes); no new tap
- D-14: Use Garmin, not Strava (researched and rejected — D-19)
- D-15: Quality available on both interactive and silently-synced sessions; null handled gracefully
- D-16: Research/ingest sub-task — confirm Garmin self-eval field names in live code
- D-17: Sunday weekly review = within-block status + trend only; no deadline projection
- D-18: Morning briefing = one integrated block (session + recovery + fueling)
- D-19: Strava rejected — official MCP is read-only/subscription-gated/end-user-chat-only

### Claude's Discretion
- Exact macro-shortfall thresholds (D-09)
- Slot-window widths and anchor time resolution strategy (D-10)
- Whether dedup gate reuses OutreachLogStore directly or adds a thin parallel store (D-04)
- The exact `category:subject` vocabulary/enum for topic keys
- Where dedup check sits in each cron's compose path
- Session-quality derivation heuristic and stored field shape
- Precise prompt wording for strict pushback, recovery rec format, structural-critique escalation
- "One integrated block" morning-briefing framing in `prompts/morning_briefing.md`

### Deferred Ideas (OUT OF SCOPE)
- PROG-02: Pace-to-deadline trend projection / per-facet improvement trajectory → Phase 25
- Strava integration (D-14/D-19)
- 3k / 400m maximal-sprint benchmarks near November deadline (Phase 23 carry-forward)
- WR-03 + IN-01/02/03 from phase-22-code-review-advisory

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COACH-03 | Strict skip/off-plan pushback with named deficit + consequence, no softening | D-05/D-06 wording pinned; `training_log` completed=False entries + calendar comparison is the trigger source |
| COACH-04 | Recovery-vs-plan conflict: cite data, exactly one ranked recommendation, "your call, Sir" | `compute_recovery_concern()` already exists; D-07 format pinned |
| COACH-05 | Cross-cron dedup — same coaching topic at most once per day across crons | `OutreachLogStore` reuse pattern confirmed; topic-key vocabulary defined in this research |
| NUTR-01 | Macro adherence check against 150g protein / 350g carbs; flag structural shortfall; structural target critique | `MealStore.get_day_aggregate()` totals are the source; thresholds defined in this research |
| NUTR-02 | Meal→fueling-slot mapping; flag missed post-AM-run reload, PM post-lift rebuild, pre-bed | `MealStore.get_day()` timestamps confirmed; anchor strategy defined in this research |
| NUTR-03 | Supplement timing against blueprint schedule; inference/advisory; tied to fueling-slot misses | Supplement carrier-slot mapping pinned from `docs/hybrid_athlete_blueprint.md` §6 |
| PROG-01 | Sunday weekly review: per-facet within-block status + session-quality trend | `_gather_week_data()` in `weekly_training_review.py` is the hook; quality field design pinned |
| PROG-03 | Morning briefing: named session + recovery + fueling reminder in one integrated block | `_gather_data()` in `morning_briefing.py` is the hook; D-18 framing design pinned |
| PROG-04 | Session-quality annotation at log time (derived, not tapped) | Derivation heuristic using existing `rpe` + `feel` fields pinned; `quality` field added to `log_session` |

</phase_requirements>

---

## Summary

Phase 24 is an integration capstone with no new packages, no new crons, and no new external APIs. All work is folding new behavior into existing code paths. The research confirms all 18 decisions from CONTEXT.md are buildable directly against the live codebase with minimal structural additions.

**Highest priority finding (D-14/D-16):** The CONTEXT.md guessed `directWorkoutFeel` / `directWorkoutRpe` as the Garmin self-eval field names. This is WRONG for the Postgres backfill. The ingest script (`ingest_garmin_zip.py`) reads `workoutRpe` / `workoutFeel` from the export JSON and stores them in the `activities` table columns `perceived_exertion` / `feel`. The Live API call (`garmin_tool.fetch_garmin_activities`) reads `directWorkoutRpe` / `directWorkoutFeel` from the live API. Both land in the same normalized output dict keys: `perceived_exertion` and `feel`. The D-16 sub-task is already complete — both paths are wired and surface the same output key names. The planner does NOT need to add a new ingest field.

**Second highest priority finding (cross-cron dedup, D-04):** `OutreachLogStore` is the right substrate but has a semantic mismatch: its `append()` is gated on `send_and_inject` success (D-10 from Phase 18), and its `topics_today()` is informative-only to the tick-brain triage (does not block). For Phase 24 we need a HARD-BLOCK gate that fires before LLM composition across three crons. Recommendation: add a thin `CoachingTopicStore` with the same per-day/Asia/Jerusalem-keyed pattern, mirroring `OutreachLogStore`'s collection shape exactly but with a strict has-topic/add-topic API. This avoids contaminating the autonomous tick's outreach log semantics while giving the planner a clean new store.

**Primary recommendation:** Build a thin `CoachingTopicStore` in `memory/firestore_db.py` for the cross-cron gate; add a `quality` field to `TrainingLogStore.log_session`; wire macro/fueling gather into `proactive_alerts._gather_nutrition_data()`; use training-anchored slot windows (±90min for slot #2, ±120min for slot #5, fixed 21:00–23:59 for slot #6 pre-bed).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cross-cron dedup gate | Backend (Firestore store) | All three cron compose paths | Gate is storage-backed; crons check/write it |
| Macro adherence flagging | Backend (`proactive_alerts.py`) | `morning_briefing.py` for prior-day recap | 21:30 is the primary accountability cron (D-08) |
| Fueling-slot mapping | Backend (new helper function) | `proactive_alerts.py` calls it at gather time | Reusable pure function; crons call it |
| Supplement inference | Backend (proactive_alerts.py compose) | Prompt layer for framing | Tied to fueling-slot miss detection |
| Session-quality derivation | Backend (`training_checkin.py` + `log_session`) | `weekly_training_review.py` reads quality trend | Derives at log time from existing signals |
| Skip pushback composition | Prompt (`proactive_alert.md`, `morning_briefing.md`) | Brain LLM | Instructions + data context → LLM composes |
| Recovery-conflict single-rec | Prompt (`proactive_alert.md`, `smart_agent.md`) | Brain LLM | Format constraint is a prompt-level rule |
| Per-facet weekly review | Backend (`_gather_week_data()` extension) + Prompt | `weekly_training_review.md` | Gather surfaces per-facet data; prompt formats it |
| Integrated morning-briefing block | Prompt (`morning_briefing.md`) | `_gather_data()` for context | D-18 framing is a prompt-level instruction; gather surfaces the ingredients |

---

## Standard Stack

### Core (all already installed — no new packages)

| Component | Source | Version/Status | Purpose |
|-----------|--------|----------------|---------|
| `memory.firestore_db` | In-repo | Live | All stores (`OutreachLogStore`, `TrainingLogStore`, `MealStore`, `BlockStore`, `BenchmarkStore`) |
| `mcp_tools.garmin_tool` | In-repo | Live | `fetch_garmin_activities()` — provides `perceived_exertion` + `feel` fields |
| `core.training_checkin` | In-repo | Live | Session log flow; `_slot_for`, `_garmin_covers`, `log_session` hook |
| `core.proactive_alerts` | In-repo | Live | 21:30 cron; integration point for nutrition + dedup gate |
| `core.morning_briefing` | In-repo | Live | Morning cron; integration point for D-18 integrated block |
| `core.weekly_training_review` | In-repo | Live | Sunday cron; integration point for per-facet + quality trend |
| `core.tools` | In-repo | Live | `_handle_read_coaching_guide` — WR-02 hardening target |
| `core.main` | In-repo | Live | `_run_smart_loop` — double-send cap fix target |

**No new packages to install.** This phase is pure integration; all needed libraries are already in the project.

### Package Legitimacy Audit

> Not applicable — no new external packages are introduced in this phase.

---

## Architecture Patterns

### System Architecture Diagram

```
[21:30 cron / proactive_alerts.run_proactive_alerts()]
  │
  ├─► run_training_checkin()           ← existing (unchanged)
  │     └─ log_session(quality=derived) ← NEW: derive quality at log time
  │
  ├─► _gather_nutrition_data()          ← NEW helper
  │     ├─ MealStore.get_day() → meal timestamps
  │     ├─ resolve_anchor_times()       ← NEW: calendar + Garmin start times
  │     └─ map_meals_to_slots() + macro_gap_check()  ← NEW pure fns
  │
  ├─► CoachingTopicStore.has_topic()    ← NEW: per-day dedup gate
  │     └─ if topic already fired → skip
  │
  ├─► _compose_alert() (+ proactive_alert.md)   ← MODIFIED: strict pushback + nutrition
  │     └─ on send: CoachingTopicStore.add_topic()
  │
  └─► _already_sent() dedup gate       ← existing (unchanged)


[Morning briefing / morning_briefing._gather_data()]
  │
  ├─► existing sources (weather, calendar, email, garmin, tasks, nutrition yesterday)
  ├─► CoachingTopicStore.has_topic()   ← check for prior-day unresolved miss
  └─► _compose_briefing() (+ morning_briefing.md)  ← MODIFIED: D-18 integrated block


[Sunday weekly review / weekly_training_review._gather_week_data()]
  │
  ├─► TrainingLogStore.get_range() → sessions with quality field
  ├─► BenchmarkStore.get_block_benchmarks() → per-facet data
  └─► _compose_review() (+ weekly_training_review.md)  ← MODIFIED: per-facet + quality trend


[Chat / _run_smart_loop()]
  ├─► smart_agent.md  ← MODIFIED: strict-pushback + dedup format instructions
  ├─► _handle_read_coaching_guide()  ← MODIFIED: WR-02 fuzzy match hardening
  └─► MAX_TOOL_ITERATIONS  ← RAISED: double-send bug fix
```

### Recommended Project Structure

No structural changes to folders. Additive changes only:

```
memory/
└── firestore_db.py       # + CoachingTopicStore (new class)
                          # + quality param in TrainingLogStore.log_session

core/
├── proactive_alerts.py   # + _gather_nutrition_data(), nutrition flagging, dedup gate calls
├── training_checkin.py   # + quality derivation in _silent_garmin_sync + handle_rpe_callback
├── morning_briefing.py   # + dedup gate check, D-18 integrated block gather
├── weekly_training_review.py  # + per-facet within-block gather, quality trend
├── main.py               # + raised MAX_TOOL_ITERATIONS, fallback suppression fix
└── tools.py              # + WR-02 fuzzy match hardening

prompts/
├── proactive_alert.md    # + strict pushback, nutrition accountability, dedup semantics
├── morning_briefing.md   # + D-18 integrated block framing
├── weekly_training_review.md  # + per-facet + quality trend framing
└── smart_agent.md        # + strict-pushback + dedup format instructions
```

---

## Detailed Research Findings

### Finding 1: Garmin Self-Eval Fields (D-14 / D-16) — VERIFIED, NO INGEST WORK NEEDED

[VERIFIED: live code audit of `mcp_tools/garmin_tool.py` and `scripts/ingest_garmin_zip.py`]

**The CONTEXT.md guessed `directWorkoutFeel` / `directWorkoutRpe`. The reality is a split:**

**Live API path (`fetch_garmin_activities()` line 343–345):**
- Source key in API JSON: `directWorkoutRpe` → normalized to output dict key `perceived_exertion`
- Source key in API JSON: `directWorkoutFeel` → normalized to output dict key `feel`
- Existing output dict for each activity: `{"activity_id", "date", "type", "duration_sec", "distance_m", "perceived_exertion", "feel", "training_load"}`

**Backfill/Postgres ingest path (`parse_and_ingest_activities()`, lines 338–340 with comment):**
- Source key in export JSON: `workoutRpe` → stored in `activities.perceived_exertion` (SMALLINT)
- Source key in export JSON: `workoutFeel` → stored in `activities.feel` (SMALLINT)
- The ingest script's comment (line 332–337) explicitly documents: *"Source keys are `workoutRpe` / `workoutFeel` (NOT the `directWorkoutRpe` / `directWorkoutFeel` names originally assumed in the plan)."*

**Postgres `activities` table schema (lines 56–61):**
```sql
ALTER TABLE activities ADD COLUMN IF NOT EXISTS training_load REAL;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS perceived_exertion SMALLINT;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS feel SMALLINT;
```

**Scale encoding (from ingest comment):**
- `workoutRpe` (live: `directWorkoutRpe`): raw 10..100 in steps of 10. The `TrainingLogStore.log_session` normalizer converts this to 1..10 (line 824: `if rpe > 10 and rpe % 10 == 0: rpe = rpe // 10`).
- `workoutFeel` (live: `directWorkoutFeel`): raw 0/25/50/75/100 for the 5-point Feel scale (Very Weak→Very Strong). Not rescaled by the ingest; stored verbatim.

**The `_silent_garmin_sync()` in `training_checkin.py` (line 462) already reads both fields** from `fetch_garmin_activities()` output and writes them to `TrainingLogStore` via `log_session(rpe=perceived_exertion, feel=feel)`.

**Conclusion for planner:** D-16 is already done. No new ingest work. The quality-derivation task (D-13) uses the fields already landing in `training_log` entries. The only new work is computing `quality` from the existing `rpe` and `feel` fields already stored there.

**Feel→quality mapping (D-13 recommendation):**

| Garmin raw `feel` | Garmin label | Normalized RPE context | Quality label |
|-------------------|--------------|------------------------|---------------|
| 100 (Very Strong) | Very Strong | any | `strong` |
| 75 (Strong) | Strong | ≥6 RPE | `strong` |
| 75 (Strong) | Strong | <6 RPE | `neutral` |
| 50 (Okay) | Okay | any | `neutral` |
| 25 (Weak) | Weak | any | `grind` |
| 0 (Very Weak) | Very Weak | any | `grind` |
| None (no Garmin) | — | ≥8 RPE (Telegram) | `grind` |
| None (no Garmin) | — | ≤5 RPE (Telegram) | `strong` |
| None (no Garmin) | — | 6–7 RPE | `neutral` |
| None + no RPE | — | — | null |

Session notes mentioning "pb", "PR", "personal record", "best", "felt great" → bias toward `strong`. Notes mentioning "struggled", "awful", "terrible", "cut short" → bias toward `grind`.

**Stored field name:** Add `quality: str | None` parameter to `TrainingLogStore.log_session()`. The field is written via the existing `merge=True` pattern so existing entries without quality remain valid.

---

### Finding 2: Cross-Cron Dedup Gate (D-01/D-02/D-03/D-04, COACH-05)

[VERIFIED: live code audit of `memory/firestore_db.py` lines 1291–1403, `core/autonomous.py` line 375]

**Existing `OutreachLogStore` anatomy:**
- Collection: `outreach_log/{YYYY-MM-DD}` (one doc per Asia/Jerusalem calendar day)
- `append(date_str, entry)` — called ONLY after `send_and_inject` succeeds (Phase 18 D-10 invariant, per CLAUDE.md §6)
- `topics_today(date_str)` — returns list of `topic_key` strings in append order; used as *informative* context for the tick-brain triage (not a hard block)
- `get_today(date_str)` — returns full entries list

**Why OutreachLogStore cannot be reused directly for the coaching gate:**

1. `OutreachLogStore.append()` is semantically coupled to "successful autonomous-tick send": it's gated on `send_and_inject` success and its entries carry `draft`, `final`, `tick_index` fields. Injecting coaching-topic keys from morning briefing / proactive_alerts would pollute the autonomous tick's informative-repeat-suppression log with topics that were composed via a different path.

2. The existing `topics_today()` is intentionally informative-only (tick-brain is *told* about it but not hard-blocked). The coaching gate needs to HARD-BLOCK compose. These are different contracts.

**Recommended new store: `CoachingTopicStore`**

```python
class CoachingTopicStore:
    """Per-day coaching topic gate for cross-cron dedup (Phase 24 — COACH-05).

    Collection: coaching_topics/{YYYY-MM-DD}
    Schema: { "date": str, "topics": list[str], "updated_at": SERVER_TIMESTAMP }

    D-04: daily reset via date-keyed doc (same pattern as OutreachLogStore).
    D-02: has_topic() hard-blocks; add_topic() writes only for proactive crons.
    D-03: reactive chat never calls either method.
    """

    _COLLECTION = "coaching_topics"

    def has_topic(self, date_str: str, topic_key: str) -> bool:
        """Return True if topic_key was already raised today. Never raises."""

    def add_topic(self, date_str: str, topic_key: str) -> None:
        """Atomically add topic_key to today's list. Re-raises on write failure.
        Uses firestore.ArrayUnion([topic_key]) with merge=True (same as OutreachLogStore.append)."""

    def topics_today(self, date_str: str) -> list[str]:
        """Return today's raised topic keys. Never raises."""
```

**Gate placement in each cron's compose path:**

```
proactive_alerts.py (21:30):
  Before: compose coaching content (skip pushback, nutrition flags)
  After compose + before send:
    for each topic_key in detected_issues:
      if not store.has_topic(today_israel, topic_key):
          include in compose context
          # after send succeeds:
          store.add_topic(today_israel, topic_key)

morning_briefing.py:
  In _gather_data(): add a "coaching_topics_today" key from store.topics_today()
  In compose: skip any topic whose key is already in coaching_topics_today
              UNLESS escalation condition (D-02: worsened state with new data)
  After send: store.add_topic() for any new topics included

weekly_training_review.py:
  Same pattern as morning_briefing.py — check before include, write after send
  Sunday review is less likely to fire daily topics; primarily checks for
  pattern-level topics like "structural:protein-target-low"
```

**Topic-key vocabulary (D-01, Claude's discretion):**

| Category | Subject examples | When fires |
|----------|-----------------|------------|
| `skipped-session` | `threshold-run`, `lower-body-a`, `upper-body-a` | Training log shows completed=False, no valid skip reason |
| `protein-miss` | (no subject — single-issue) | Daily protein < threshold |
| `carb-miss` | `long-run-day` | Carbs short on a high-volume run day |
| `fueling-miss` | `post-am-run`, `pm-post-lift`, `pre-bed` | Slot window elapsed with no meal in it |
| `recovery-conflict` | `bench-press`, `threshold-run` | compute_recovery_concern fires + session planned |
| `structural-critique` | `protein-target-low` | Multi-day pattern triggers structural COACH-07 comment |

D-01 note: Two distinct session types can both fire in the same day (e.g. `skipped-session:threshold-run` AND `skipped-session:lower-body-a`). They are different topic keys. The dedup gate prevents the SAME key from firing twice — not all keys within a category.

**D-02 escalation condition (worsened state):**
The gather step re-runs at the later cron. If the underlying condition still exists (session still un-logged, fueling slot still empty hours later), the topic gets an escalation: the compose prompt is told "already flagged this morning — still unresolved — short escalation reference only."

---

### Finding 3: MealStore Timestamps + Fueling Slot Mapping (D-10/D-11, NUTR-02/03)

[VERIFIED: live code audit of `memory/firestore_db.py` lines 641–732]

**`MealStore.get_day(date_str)` returns:**
- A list of meal dicts, sorted ascending by `timestamp` field
- Each meal dict has: `timestamp` (ISO-8601 string), `calories`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, `meal_type` (integer), `source_id`, `food_item`
- `updated_at` is stripped before return (Phase 19.3 fix, line 663)

**Anchor time resolution strategy (D-10, Claude's discretion):**

Priority order for AM-run anchor:
1. Garmin activity start from `fetch_garmin_activities(days=1)` — `type` in `{"running", "trail_running", "treadmill_running"}` — `date` field (ISO timestamp)
2. Calendar event start from `_get_todays_training_events(today_iso)` — event with "run" in summary
3. Fallback: use fixed time 07:30 (typical AM run window) with widened slot window

Priority order for PM-lift anchor:
1. Garmin activity start — `type` in `{"strength_training", "fitness_equipment"}`
2. Calendar event start — event with "gym" or "lower body" or "upper body" in summary
3. Fallback: use fixed time 19:00 with widened slot window

**Slot-window definitions (D-10, Claude's discretion):**

| Slot | Name | Window | Structural? | Supplements |
|------|------|---------|-------------|-------------|
| #1 Pre-AM Run | Pre-run fuel | AM_run_anchor − 90min to anchor − 15min | Soft (not nagged) | — |
| #2 Post-AM Run Reload | Reload | AM_run_anchor + 15min to anchor + 90min | **HARD — flag miss** | D3+K2, Omega-3 |
| #3 Mid-Day | Sustained engine | 12:00 − 14:30 (fixed) | Soft | — |
| #4 PM Pre-Lift | Pre-lift fuel | PM_lift_anchor − 90min to anchor − 15min | Soft | Beta-Alanine |
| #5 PM Post-Lift Rebuild | Rebuild | PM_lift_anchor + 15min to anchor + 90min | **HARD — flag miss** | Creatine |
| #6 Pre-Bed | Pre-bed supplements | 21:00 − 23:59 (fixed) | **HARD — flag miss** | Mg-Glycinate, Zinc, Copper |

**Slot miss detection algorithm:**

```python
def _map_meals_to_slots(meals: list[dict], am_anchor: datetime | None, pm_anchor: datetime | None) -> dict:
    """Returns {slot_name: [meals_in_slot]} for all 6 slots."""
    # For each hard slot: if no meal with timestamp in window → slot_miss = True
    # Windows use anchor times when available, fixed fallbacks otherwise

def _detect_slot_misses(slot_map: dict, am_anchor: datetime | None, pm_anchor: datetime | None) -> list[str]:
    """Returns list of missed hard-slot names: ["post-am-run", "pm-post-lift", "pre-bed"]"""
    # Only fires for hard slots (#2, #5, #6)
    # Slot #2 only fires if there WAS an AM run today (anchor resolved)
    # Slot #5 only fires if there WAS a PM lift today (anchor resolved)
    # Slot #6 (#pre-bed) fires after 21:30 if no meal in 21:00–23:59 window
```

**Supplement inference (D-11):**
- Slot #2 miss → append to flag: "— and that's your D3+K2/Omega-3 gone with it."
- Slot #5 miss → append: "— and Creatine timing missed."
- Slot #6 miss → standalone: "Pre-bed Mg-Glycinate/Zinc/Copper window open — take them now."
- Slot #4 miss (soft) → NOT flagged, only carried in supplement context if slot #5 is also missed.

---

### Finding 4: Macro-Adherence Thresholds (D-09, NUTR-01)

[ASSUMED: thresholds are Claude's discretion per CONTEXT.md D-09; based on training knowledge of sports nutrition for a hybrid athlete at 150g protein / 350g carbs]

**Blueprint targets from `docs/hybrid_athlete_blueprint.md` §6:** 150g protein / 350g carbs daily.

**Recommended thresholds (structurally meaningful shortfall):**

| Macro | Flag threshold | Rationale |
|-------|---------------|-----------|
| Protein | < 120g (80% of 150g) | Below this, insufficient amino acids for muscle protein synthesis for the training volume described |
| Carbs on normal day | < 250g (71% of 350g) | Below this, glycogen stores are meaningfully compromised |
| Carbs on long-run day (Friday ≥ 18km) | < 300g (86% of 350g) | Long-run days need higher carb availability pre/post; stricter floor |
| Carbs on deload day | < 200g | Lower volume day; less critical but still structural |

**Pattern-triggered structural critique (D-12, COACH-07):**
Fire `structural-critique:protein-target-low` when:
- ≥3 of the last 7 days have protein < 120g, AND
- Current training week is Week 3+ (enough volume to make the critique meaningful)

**Tiered shortfall classification:**

```python
def _macro_gap_check(totals: dict, day_type: str, targets: dict) -> list[dict]:
    """
    totals: {"protein_g": N, "carbs_g": N, ...}
    day_type: "long_run" | "normal" | "deload" | "rest"
    Returns: list of {topic_key, description, severity}
    """
```

`day_type` determination: check `fetch_garmin_activities(1)` for long-run (distance_m > 16000 or type in running + duration_sec > 4200); check weekly split from `UserProfileStore.load()['weekly_split']` for rest days.

---

### Finding 5: Session-Quality Derivation (D-13/D-15, PROG-04)

[VERIFIED: live code audit of `memory/firestore_db.py` TrainingLogStore, `core/training_checkin.py` `_silent_garmin_sync` + `handle_rpe_callback`]

**Existing fields in `training_log` entries:**
- `rpe`: int 1–10 (Garmin-normalised or Telegram-tapped)
- `feel`: int verbatim from Garmin (0/25/50/75/100 scale) — already stored by `_silent_garmin_sync`
- `notes`: str | None

**New field to add:** `quality: str | None` with values `"strong"` | `"neutral"` | `"grind"` | None

**Where to derive (integration points):**

1. **`_silent_garmin_sync()` in `training_checkin.py`** — already reads `rpe` + `feel` from Garmin activity dict. Add quality derivation here before calling `log_session()`.

2. **`handle_rpe_callback()` in `training_checkin.py`** — Telegram RPE tap. At this point `feel` is not yet known (user just tapped RPE). Quality should be derived from RPE alone here and written via `log_session(quality=..., merge=True)`. If Garmin later syncs (via `_silent_garmin_sync`), the `feel` field will update the log via `merge=True` — but quality won't auto-update unless the silent sync also re-derives it. Simplest approach: always derive quality in `_silent_garmin_sync` using both fields, and in `handle_rpe_callback` derive quality using RPE only as a provisional value.

3. **`attach_note()` in `training_checkin.py`** — notes arrive after RPE. No quality re-derivation needed here (notes bias toward override only for obvious cases like "pb" / "cut short"). Keep simple: quality is derived once at RPE-log time + once at Garmin-sync time.

**`log_session()` change:**
```python
def log_session(
    self,
    date: str,
    slot: str,
    ...,
    quality: str | None = None,    # NEW — "strong" | "neutral" | "grind" | None
) -> None:
```

**Quality derivation function (pure, no I/O):**
```python
def derive_session_quality(
    rpe: int | None,
    feel: int | None,    # Garmin raw: 0/25/50/75/100
    notes: str | None = None,
) -> str | None:
    """Returns "strong" | "neutral" | "grind" | None."""
    if rpe is None and feel is None:
        return None
    # Feel takes precedence when present (more reliable signal)
    if feel is not None:
        if feel >= 75:
            return "strong" if (rpe is None or rpe >= 5) else "neutral"
        if feel == 50:
            return "neutral"
        return "grind"   # feel <= 25
    # RPE-only fallback
    if rpe >= 8: return "grind"
    if rpe <= 4: return "strong"
    return "neutral"
    # Notes override (last — simple keyword scan)
    # pb / PR / personal record / best → "strong"
    # terrible / awful / cut short / struggled → "grind"
```

**Weekly review quality trend (PROG-01):**
`_gather_week_data()` already returns `training_log` list with all session fields. The new `quality` field will be present (or None) in each entry. The weekly review prompt gets the list with quality values and computes the trend.

---

### Finding 6: `proactive_alerts.py` Integration Point Verification

[VERIFIED: live code audit of `core/proactive_alerts.py`]

**Existing `_already_sent()` gate (line 197):** Uses `proactive_alerts/{YYYY-MM-DD}` Firestore collection. This is a COARSER whole-cron dedup (prevents re-running for the same date). The new topic-level coaching gate is FINER (fires per coaching topic, not per cron invocation). They are independent.

**Structure of `run_proactive_alerts()` (lines 151–290):**
```
1. run_training_checkin(bot, today)          ← runs BEFORE _already_sent gate
2. Block-end benchmark state machine         ← runs BEFORE _already_sent gate
3. _already_sent(target_date) gate           ← whole-cron dedup
4. Gather: events, weather, garmin, ACWR, benchmark_state
5. compute_recovery_concern()
6. _compose_alert(alerts_context)            ← LLM compose
7. send_and_inject + _mark_processed
```

**Where Phase 24 integrates:**
- Step 4 extension: add `_gather_nutrition_data(today_iso)` call
- Between steps 3–4: do NOT add the coaching topic gate yet (nutrition gather must happen first to know WHICH topics to check)
- Between steps 5–6: check `CoachingTopicStore.has_topic()` for each detected topic; filter to un-raised topics for compose context
- After step 7 success: `CoachingTopicStore.add_topic()` for each topic included

**Important: `run_training_checkin()` runs before the `_already_sent` gate.** This means even on a "re-run" (same-evening retry), the check-in can fire again. The session-quality derivation in `_silent_garmin_sync` must remain idempotent — `merge=True` in `log_session` already handles this.

---

### Finding 7: Folded Todo — WR-02 `read_coaching_guide` Fuzzy Match (tools.py)

[VERIFIED: live code audit of `core/tools.py` lines 1500–1543]

**Current behavior (lines 1531–1541):**
```python
# Fuzzy fallback: first section whose anchor contains any word of the query
for word in slug.split("-"):
    if not word:
        continue
    fallback = re.compile(
        r"<!-- SECTION: [^>]*" + re.escape(word) + r"[^>]* -->(.*?)(?=<!-- SECTION:|$)",
        re.DOTALL | re.IGNORECASE,
    )
    fm = fallback.search(content)
    if fm:
        return json.dumps({"topic": slug, "content": fm.group(1).strip()})
```

**The bug:** The word `set` from `top-set-strength` will match any section anchor containing the substring "set" — including unrelated sections. No confidence signal is returned.

**Fix shape (per WR-02 + D-01 security):**
Replace the single-match return with a count-of-candidates check:
```python
# Fuzzy fallback: ONLY return if exactly one section matches (unambiguous)
for word in slug.split("-"):
    if not word or len(word) < 4:  # skip short words that over-match
        continue
    fallback = re.compile(
        r"<!-- SECTION: [^>]*" + re.escape(word) + r"[^>]* -->",
        re.IGNORECASE,
    )
    candidate_anchors = fallback.findall(content)
    if len(candidate_anchors) == 1:
        # Exactly one match — unambiguous
        section_pattern = re.compile(
            r"<!-- SECTION: [^>]*" + re.escape(word) + r"[^>]* -->(.*?)(?=<!-- SECTION:|$)",
            re.DOTALL | re.IGNORECASE,
        )
        fm = section_pattern.search(content)
        if fm:
            return json.dumps({"topic": slug, "content": fm.group(1).strip()})

return json.dumps({"error": f"Section '{topic}' not found in COACHING_GUIDE.md"})
```

The brain falls back to the slim core when it gets the not-found JSON, which is correct behavior for Phase 24's strict coaching contexts.

---

### Finding 8: Folded Todo — Double-Send Bug (`core/main.py`)

[VERIFIED: live code audit of `core/main.py` lines 44, 662–668]

**Current cap:** `MAX_TOOL_ITERATIONS = 8` (line 44)

**Fallback text at exhaustion (lines 665–668):**
```python
return (
    "Apologies, Sir. This request required more processing steps than expected. "
    "Please rephrase or break it into smaller parts."
)
```

**The double-send mechanism:**
When the smart loop hits `MAX_TOOL_ITERATIONS`, it returns the fallback string. But the final LLM call's response (which may have produced a `response_text` with a substantive answer + a tool call) gets discarded. However, the system also appears to complete the answer on the NEXT invocation in some Cloud Run concurrency scenarios. The todo file attributes it to the cap being too low, causing a Path B `respond_directly=True` return in the same turn. The exact sequence needs investigation but the symptom is clear.

**Recommended fix (Option 1 + Option 2 combined):**
1. Raise `MAX_TOOL_ITERATIONS` from 8 to **12**. Phase 24 coaching queries legitimately need: (1) read block state, (2) read training log, (3) read benchmarks, (4) read meal data, (5) read garmin, (6) read profile — that's 6 tool calls minimum for a data-heavy coaching message.
2. Add a "substantive answer suppression" flag: if `response_text` is non-empty and substantial (> 100 chars) when `MAX_TOOL_ITERATIONS` is hit, return `response_text` instead of the fallback string:

```python
# In _run_smart_loop, at MAX_TOOL_ITERATIONS exhaustion:
# If the final iteration produced a substantive response_text despite also having
# tool_calls, use it rather than the fallback (suppress the double-send).
last_response_text = ""  # track across iterations
# ... in loop body, after: response_text = response["text"]
if response_text:
    last_response_text = response_text
# ... at end of loop:
if last_response_text and len(last_response_text) > 100:
    logger.warning("Smart loop: returning partial response_text to avoid double-send")
    return last_response_text
return (
    "Apologies, Sir. This request required more processing steps..."
)
```

---

### Finding 9: Morning Briefing Integration Point Verification

[VERIFIED: live code audit of `core/morning_briefing.py` lines 174–302]

`_gather_data()` currently gathers: weather, calendar, email, garmin, biometrics-write, recovery_concern, tasks, yesterday's nutrition (aggregate), current block.

**What Phase 24 adds:**
- `today_training_events`: a reference to today's planned sessions (for the "named session" part of the D-18 integrated block). The calendar events are already fetched (`data["calendar"]`); the training events subset can be extracted inline.
- `coaching_topics_today`: list of already-raised coaching topic keys from `CoachingTopicStore.topics_today(today_iso)`. The morning briefing uses this to skip topics already covered by the 21:30 check-in from the prior evening AND to recap unresolved prior-day misses (D-08).

**The "prior-day unresolved miss" pattern (D-08):**
The morning briefing runs 6:00–10:15. If a `skipped-session:*` topic was fired at 21:30 last night, it's stored in `coaching_topics/{yesterday}`. If the session was never logged, the morning briefing can still recap it. This requires checking YESTERDAY's `CoachingTopicStore` doc, not today's.

Implementation: `_gather_data()` reads `coaching_topics_yesterday = store.topics_today(yesterday_iso)`. The morning briefing prompt is told "these topics were already raised last night" and instructed to surface unresolved ones at reduced priority (no nagging, one contextual line).

---

### Finding 10: weekly_training_review.py Integration Point Verification

[VERIFIED: live code audit of `core/weekly_training_review.py` lines 42–224]

`_gather_week_data()` already fetches: training_log (via `TrainingLogStore.get_range()`), Garmin activities (14-day window), biometrics, 7-day nutrition totals, athletic_goals, `current_block` + `block_benchmarks`.

**What Phase 24 adds:**
- `training_log` entries will now include the `quality` field (after the `TrainingLogStore.log_session` change lands). `_gather_week_data()` returns the raw list — no code change needed here; the quality values are present in the doc.
- Per-facet within-block status: already partially supported via `block_benchmarks` from `BenchmarkStore`. The compose prompt (via `weekly_training_review.md`) needs to be instructed to extract per-facet trends from the benchmark data.
- Quality trend: the compose prompt gets the training_log list with quality values and derives the trend.

**No new gather code needed for PROG-01/PROG-03** beyond the above additions to `morning_briefing._gather_data()`. The prompt changes carry the behavior.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-cron dedup | Custom per-cron flag fields | `CoachingTopicStore` (mirrors `OutreachLogStore`) | Atomic ArrayUnion avoids race conditions between crons |
| Session-quality ML | A scoring model | Simple rule-based mapping from `feel`/`rpe` | Training data doesn't exist; rules are interpretable and debuggable |
| Fueling-slot time math | Manual datetime arithmetic scattered in compose | `_map_meals_to_slots(meals, am_anchor, pm_anchor)` pure function | Testable in isolation without Firestore/Garmin |
| Anchor time resolution | Calendar + Garmin every time inline | `_resolve_anchor_times(today_iso)` helper function returning `(am: datetime|None, pm: datetime|None)` | Reusable across 21:30 and morning briefing paths |
| Macro thresholds | Hardcoded magic numbers | `MACRO_THRESHOLDS` module-level dict | Env-configurable; testable |

**Key insight:** All new logic in this phase is rule-based data transformation that can and should be implemented as pure functions with no I/O, then wired into the cron compose paths. This keeps unit testing simple and prevents I/O failures from masking logic bugs.

---

## Common Pitfalls

### Pitfall 1: Dedup Gate Write Position
**What goes wrong:** Writing the coaching topic key to `CoachingTopicStore` BEFORE the message is sent means a Cloud Run crash after write but before send creates a false-positive dedup block — the topic key is recorded but nothing was actually sent.
**Why it happens:** Eager write to "be safe."
**How to avoid:** Mirror Phase 18 D-10 pattern exactly: write to `CoachingTopicStore` only AFTER `send_and_inject` succeeds (same discipline as `OutreachLogStore.append`).
**Warning signs:** Topics appear in `coaching_topics/{date}` but no corresponding message in Telegram history.

### Pitfall 2: Fueling-Slot Anchor Falls Back to None When No Training Day
**What goes wrong:** `_resolve_anchor_times()` returns `(None, None)` on a rest day. Slot #2 and #5 detection silently flags ALL rest days as "slot miss" if the fallback logic uses fixed times.
**Why it happens:** Forgetting to guard: "only check slot #2 if AM run anchor resolved, only check slot #5 if PM lift anchor resolved."
**How to avoid:** `_detect_slot_misses()` must check anchor is not None before evaluating #2 and #5. Slot #6 (pre-bed) is always checked regardless of training.
**Warning signs:** `fueling-miss:post-am-run` fires on Saturdays (rest day).

### Pitfall 3: `ArrayUnion` with `SERVER_TIMESTAMP` inside the entry
**What goes wrong:** If `CoachingTopicStore.add_topic()` stores the entry as a dict `{topic_key: str, raised_at: SERVER_TIMESTAMP}` (following OutreachLogStore's NOTE 2 anti-pattern), ArrayUnion deep-equality breaks dedup.
**Why it happens:** Copying OutreachLogStore's `append` structure without reading NOTE 2.
**How to avoid:** Store topic keys as a plain list of strings in `CoachingTopicStore`. `ArrayUnion([topic_key])` where `topic_key` is a string, not a dict. The doc-level `updated_at: SERVER_TIMESTAMP` is fine.
**Warning signs:** Same topic fires twice in one day.

### Pitfall 4: Garmin Feel 0 Classified as "Missing" (None confusion)
**What goes wrong:** `feel == 0` (Garmin raw "Very Weak") is falsy in Python. `if not feel: return None` silently drops the worst sessions.
**Why it happens:** Python falsy check on int 0.
**How to avoid:** All quality derivation logic checks `if feel is not None:`, never `if feel:`.
**Warning signs:** Very-weak-feel sessions get quality=null instead of quality="grind".

### Pitfall 5: Cross-Day Timezone in Dedup Gate
**What goes wrong:** `CoachingTopicStore` doc is keyed to `date_str` in UTC, but the cron runs in Asia/Jerusalem. A 21:30 IL cron run is 18:30 UTC — correct same-day key in Jerusalem but potentially maps to a different UTC date.
**Why it happens:** Using `datetime.now(timezone.utc).date().isoformat()` instead of `datetime.now(_TZ).date().isoformat()` for the date key.
**How to avoid:** Always derive the date key as `datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()`. Mirror the existing pattern in every cron (all existing crons already do this).
**Warning signs:** Topics raised at 21:30 not being deduped by the next morning's briefing on dates that cross a UTC midnight boundary.

### Pitfall 6: Quality Field Not Written for Garmin-Only Sessions
**What goes wrong:** `_silent_garmin_sync()` writes RPE + feel to the training log but the quality derivation is only added to the Telegram path (`handle_rpe_callback`). Garmin-only sessions never get a quality value.
**Why it happens:** Adding quality derivation only in the "interactive" code path.
**How to avoid:** Add quality derivation to `_silent_garmin_sync()` as well — it already has both `rpe` (`perceived_exertion`) and `feel` from the Garmin activity dict.
**Warning signs:** Sessions with source="garmin" have quality=null in the weekly review even when feel data is available.

### Pitfall 7: `MealStore.get_day()` Returns [] Not {} on Empty
**What goes wrong:** Slot-miss logic assumes `get_day()` returns `None` on empty and does `if not meals: return` before slot checks. This causes a falsy-empty-list check failure.
**Why it happens:** `get_day()` returns `[]` (empty list) on empty — consistent with LOG-02 contract. The caller must check `if not meals:` not `if meals is None:`.
**How to avoid:** `_gather_nutrition_data()` uses `meals = MealStore.get_day(today_iso)` then `if not meals: return {missing_data context}`.
**Warning signs:** No fueling-slot data in compose context on days with no logged meals.

---

## Code Examples

### CoachingTopicStore (new, to add to `memory/firestore_db.py`)
```python
# Source: Pattern mirrors OutreachLogStore (lines 1291–1403) with simplified entry model
class CoachingTopicStore:
    _COLLECTION = "coaching_topics"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def has_topic(self, date_str: str, topic_key: str) -> bool:
        """Hard-block check. Never raises."""
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return False
            topics = (snap.to_dict() or {}).get("topics") or []
            return topic_key in topics
        except Exception:
            logger.warning("CoachingTopicStore.has_topic failed", exc_info=True)
            return False  # fail-open (let it fire rather than silent-suppress)

    def add_topic(self, date_str: str, topic_key: str) -> None:
        """Atomic add. Re-raises on write failure. Call AFTER send succeeds."""
        try:
            self._col.document(date_str).set(
                {
                    "date": date_str,
                    "topics": firestore.ArrayUnion([topic_key]),  # plain string, not dict
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception:
            logger.error("CoachingTopicStore.add_topic(%r, %r) failed", date_str, topic_key, exc_info=True)
            raise

    def topics_today(self, date_str: str) -> list[str]:
        """Return today's raised topic_keys. Never raises."""
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return []
            return list((snap.to_dict() or {}).get("topics") or [])
        except Exception:
            logger.warning("CoachingTopicStore.topics_today failed", exc_info=True)
            return []
```

### Quality derivation (new pure function, to add to `core/training_checkin.py`)
```python
# Source: design per D-13; validated against Garmin Feel scale documentation
_GARMIN_FEEL_LABELS = {100: "very_strong", 75: "strong", 50: "okay", 25: "weak", 0: "very_weak"}

def derive_session_quality(
    rpe: int | None,
    feel: int | None,       # Garmin raw: 0/25/50/75/100
    notes: str | None = None,
) -> str | None:
    """Return "strong" | "neutral" | "grind" | None (D-13)."""
    # Pitfall 4: use 'is not None' not truthiness for feel (0 = very_weak, not missing)
    if rpe is None and feel is None:
        return None

    quality: str | None = None

    if feel is not None:
        if feel >= 75:
            quality = "strong" if (rpe is None or rpe >= 5) else "neutral"
        elif feel == 50:
            quality = "neutral"
        else:  # 0 or 25
            quality = "grind"
    else:
        # RPE-only (no Garmin feel available)
        if rpe >= 8:
            quality = "grind"
        elif rpe <= 4:
            quality = "strong"
        else:
            quality = "neutral"

    # Notes override (simple keyword scan — applied after signal derivation)
    if notes:
        notes_lower = notes.lower()
        if any(k in notes_lower for k in ("pb", "pr", "personal record", "felt great", "best ever")):
            quality = "strong"
        elif any(k in notes_lower for k in ("terrible", "awful", "cut short", "struggled", "could not")):
            quality = "grind"

    return quality
```

### Slot-miss detection (new pure function)
```python
# Source: design per D-10; blueprint §6 slot definitions
from datetime import datetime, timedelta

HARD_SLOTS = {
    "post-am-run":  {"offset_min": 15, "window_min": 90},   # anchor + 15 to anchor + 90
    "pm-post-lift": {"offset_min": 15, "window_min": 90},
}
PREBED_WINDOW_START_HOUR = 21  # 21:00 to 23:59 fixed

def _slot_window(anchor: datetime, offset_min: int, window_min: int):
    return anchor + timedelta(minutes=offset_min), anchor + timedelta(minutes=offset_min + window_min)

def _detect_slot_misses(
    meals: list[dict],
    am_anchor: datetime | None,
    pm_anchor: datetime | None,
    today_date: str,
) -> list[str]:
    """Return list of missed hard-slot names. Only checks slots with resolved anchors."""
    missed = []
    meal_timestamps = [datetime.fromisoformat(m["timestamp"]) for m in meals if m.get("timestamp")]

    if am_anchor:
        lo, hi = _slot_window(am_anchor, offset_min=15, window_min=90)
        if not any(lo <= t <= hi for t in meal_timestamps):
            missed.append("post-am-run")

    if pm_anchor:
        lo, hi = _slot_window(pm_anchor, offset_min=15, window_min=90)
        if not any(lo <= t <= hi for t in meal_timestamps):
            missed.append("pm-post-lift")

    # Slot #6: fixed 21:00–23:59; only check after 21:30 (when this cron runs)
    from datetime import date as _date
    prebed_start = datetime.fromisoformat(today_date).replace(hour=21, minute=0)
    prebed_end   = datetime.fromisoformat(today_date).replace(hour=23, minute=59)
    if not any(prebed_start <= t <= prebed_end for t in meal_timestamps):
        missed.append("pre-bed")

    return missed
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No cross-cron dedup (each cron speaks independently) | `CoachingTopicStore` per-day gate (new in Phase 24) | Phase 24 | Same coaching topic fires at most once per day across all proactive crons |
| Session quality tracked only as RPE integer | `quality` string label derived from `feel` + `rpe` + notes | Phase 24 | Weekly review can surface quality trend, not just RPE distribution |
| Nutrition section = yesterday's macro summary only | Fueling-slot structural miss + supplement inference added | Phase 24 | From "how much did you eat" to "did you eat at the right time for your training" |
| Coaching messages: hedged, generic phrasing | Strict pushback: named session, real deficit units, directional consequence | Phase 24 | Behavioral contract enforced at prompt level; specificity bar from COACH-02 raised further |
| `read_coaching_guide` fuzzy match returns first-word hit | Unambiguous-only fuzzy match or not-found JSON | Phase 24 (WR-02 fix) | Prevents wrong-section being fed as authoritative source to brain |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Macro thresholds (protein < 120g, carbs < 250g normal day) are "structurally meaningful" for a hybrid athlete at Amit's training volume | Finding 4 | If thresholds are too loose, the flag fires too rarely; if too tight, noise. User can adjust via CLAUDE.md or UserProfileStore later. |
| A2 | Fueling-slot windows (±90min around anchor) are wide enough to be practically useful and narrow enough to be meaningful | Finding 3 | If windows are too narrow, valid meals are missed; too wide, window is meaningless. Claude's discretion per D-10. |
| A3 | `quality` label mapping from Garmin Feel + RPE produces clinically useful signal | Finding 1 | If the heuristic is wrong, the weekly review quality trend is misleading. Worst case: quality is null/neutral for most sessions. |
| A4 | Notes keyword scan for quality override (pb/pr/struggled) is low-noise for Amit's note style | Finding 1 / Code Examples | If Amit's notes are terse/technical, keyword matches may be sparse; quality falls back to feel/RPE which is the correct primary signal anyway. |

---

## Open Questions (RESOLVED)

1. **Pre-bed supplement slot (#6): only after 21:30?**
   - What we know: the 21:30 cron is the only opportunity to flag this same evening.
   - What's unclear: if Amit takes them at 20:00 (before the cron runs), we'd falsely flag.
   - Recommendation: only fire pre-bed slot miss if the 21:30 cron detects NO meal in the 21:00+ window, AND acknowledge it as "just a reminder, you may have already taken them."

2. **`compute_acwr_from_db()` vs fresh `fetch_garmin_activities()` for anchor time**
   - What we know: `proactive_alerts.py` already calls `compute_acwr_from_db()` for the benchmark gate. `fetch_garmin_activities(days=1)` is a fresh live API call.
   - What's unclear: whether there's a Garmin API rate limit concern with adding another `fetch_garmin_activities(1)` call for anchor time resolution.
   - Recommendation: reuse the `garmin_data` already fetched via `fetch_garmin_today()` for the benchmark gate. Add one `fetch_garmin_activities(1)` call in `_gather_nutrition_data()` — this is already done in `_silent_garmin_sync()` at the same cron invocation. Cache it to avoid a second API hit.

3. **Session-quality weekly review trend: rolling window or block window?**
   - What we know: `_gather_week_data()` uses a 7-day Sun–Sat window.
   - What's unclear: for quality trend, should we show "this week's quality distribution" or "this block's quality trend"?
   - Recommendation: both — "this week: 3 strong, 2 neutral, 1 grind" + "block trend: quality improving week-on-week" when block data is available. The prompt handles the framing.

---

## Environment Availability

> Phase 24 has no new external dependencies. All tools are already deployed and wired.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Firestore `coaching_topics` collection | CoachingTopicStore | Will be auto-created on first write | — | — |
| `activities.perceived_exertion` + `activities.feel` columns | Quality derivation | Confirmed present (Phase 19 schema, `ingest_garmin_zip.py` DDL lines 58–61) | — | Null quality |
| `training_log.quality` field | PROG-04 quality trend | Does NOT exist yet (to be added) | — | null until Phase 24 lands |
| `MealStore` timestamps | Fueling-slot mapping | Confirmed present in `get_day()` return | — | Empty slot map |
| Garmin live API (for anchor times) | Fueling-slot anchors | Confirmed available via `fetch_garmin_activities()` | — | Fixed-time fallback |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `training_log.quality` — doesn't exist yet; added in Wave 0 of Phase 24. Weekly review quality trend shows "no quality data yet" until sessions accumulate.
- Garmin activity anchor — fallback to fixed times (07:30 AM, 19:00 PM) when Garmin data is unavailable.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, 911+ tests) |
| Config file | `pytest.ini` or `pyproject.toml` (repo root) |
| Quick run command | `python -m pytest tests/test_proactive_alerts.py tests/test_training_checkin.py tests/test_morning_briefing.py tests/test_weekly_training_review.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` (run per-file to avoid grpc GC issue) |
| Note | Full `pytest tests/` in one process segfaults on Python 3.13 (grpc GC issue — per STATE.md). Run per-file. |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COACH-03 | Skip pushback: strict, names deficit + consequence | unit (prompt content) + integration (alert context key) | `pytest tests/test_proactive_alerts.py -x -q -k "skip_pushback"` | No — Wave 0 |
| COACH-04 | Recovery conflict: exactly one ranked rec in context | unit | `pytest tests/test_training_checkin.py -x -q -k "recovery"` | Partial (existing recovery tests) |
| COACH-05 | Dedup gate: same topic fires ≤1/day across crons | unit (`CoachingTopicStore.has_topic()`) | `pytest tests/test_coaching_topic_store.py -x -q` | No — Wave 0 |
| NUTR-01 | Macro gap check: protein < 120g returns flag | unit (`_macro_gap_check`) | `pytest tests/test_proactive_alerts.py -x -q -k "macro"` | No — Wave 0 |
| NUTR-02 | Fueling slot miss: post-AM-run window elapsed with no meal | unit (`_detect_slot_misses`) | `pytest tests/test_proactive_alerts.py -x -q -k "slot"` | No — Wave 0 |
| NUTR-03 | Supplement inference: slot #2 miss includes D3+K2 copy | unit (compose context key) | `pytest tests/test_proactive_alerts.py -x -q -k "supplement"` | No — Wave 0 |
| PROG-01 | Weekly review: quality field appears in training_log entry | unit (`derive_session_quality`) | `pytest tests/test_training_checkin.py -x -q -k "quality"` | No — Wave 0 |
| PROG-03 | Morning briefing: integrated block key present in gather data | unit (`_gather_data` keys) | `pytest tests/test_morning_briefing.py -x -q -k "integrated"` | No — Wave 0 |
| PROG-04 | log_session accepts quality param; silent Garmin sync derives quality | unit | `pytest tests/test_training_log_store.py tests/test_training_checkin.py -x -q -k "quality"` | No — Wave 0 |
| WR-02 | read_coaching_guide fuzzy match: ambiguous word returns not-found JSON | unit | `pytest tests/test_tools.py -x -q -k "coaching_guide"` | Partial (existing tools tests) |
| Double-send | MAX_TOOL_ITERATIONS=12; partial response returned at exhaustion | unit (`_run_smart_loop`) | `pytest tests/test_main.py -x -q -k "tool_iterations"` | Partial |

### Sampling Rate
- **Per task commit:** Run the per-file test for the modified file (e.g. `pytest tests/test_training_checkin.py -x -q`)
- **Per wave merge:** Run all Phase 24 test files in sequence
- **Phase gate:** Full per-file suite green (911+ baseline must hold) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_coaching_topic_store.py` — covers COACH-05 (has_topic, add_topic, ArrayUnion dedup, timezone key, fail-open semantics)
- [ ] `tests/test_proactive_alerts.py` — add tests for `_macro_gap_check`, `_detect_slot_misses`, `_gather_nutrition_data`, dedup gate integration
- [ ] `tests/test_training_checkin.py` — add tests for `derive_session_quality` (feel=0 Pitfall 4, rpe-only path, notes override), `_silent_garmin_sync` quality derivation, `log_session` quality param
- [ ] `tests/test_training_log_store.py` — add quality param to `log_session` test cases
- [ ] `tests/test_tools.py` — add WR-02 hardened fuzzy match tests (ambiguous word, short word skip, unambiguous match)
- [ ] `tests/test_morning_briefing.py` — add tests for prior-day coaching topics in gather, D-18 integrated block key

---

## Security Domain

> `security_enforcement` not explicitly set to false in `.planning/config.json` → section required.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface |
| V3 Session Management | No | No new session types (PendingPromptStore unchanged) |
| V4 Access Control | No | No new endpoints; existing TELEGRAM_ALLOWED_USER_IDS enforced |
| V5 Input Validation | Yes | `topic_key` in `CoachingTopicStore.add_topic()` must be validated (slug-safe chars only); `quality` field constrained to enum |
| V6 Cryptography | No | No cryptographic operations |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Topic-key injection: attacker sends crafted Telegram message containing control chars to poison `coaching_topics` doc | Tampering | `topic_key` values are always internally derived (never from user input); no user-supplied topic keys |
| `read_coaching_guide` path traversal (T-22-04, already mitigated) | Tampering | WR-02 hardening preserves the existing `slug`-normalization + regex-only matching; no filesystem path concat |
| `MAX_TOOL_ITERATIONS` raise increases LLM cost attack surface | Elevation of Privilege | Brain is already gated by Telegram user allowlist; cost impact of 8→12 iterations is marginal per turn |
| `derive_session_quality` notes scan: keyword injection to force quality override | Tampering | Notes come from Telegram (allowlisted user only); keywords are hardcoded constants, not user-supplied patterns |

---

## Sources

### Primary (HIGH confidence)
- `mcp_tools/garmin_tool.py` — verified `directWorkoutRpe` / `directWorkoutFeel` live API field names; `perceived_exertion` / `feel` output dict keys
- `scripts/ingest_garmin_zip.py` — verified `workoutRpe` / `workoutFeel` export field names + ingest comment; `activities.perceived_exertion` + `activities.feel` schema
- `memory/firestore_db.py` — verified `OutreachLogStore` structure (lines 1291–1403), `MealStore.get_day()` + `get_day_aggregate()` (lines 641–732), `TrainingLogStore.log_session()` (lines 797–843), `BlockStore.get_current()` (lines 1558–1593)
- `core/proactive_alerts.py` — verified `_already_sent` gate, `run_proactive_alerts()` structure, compose path
- `core/training_checkin.py` — verified `_silent_garmin_sync()`, `handle_rpe_callback()`, `_slot_for()`, `compute_recovery_concern()`
- `core/morning_briefing.py` — verified `_gather_data()` structure
- `core/weekly_training_review.py` — verified `_gather_week_data()` structure + current keys
- `core/main.py` — verified `MAX_TOOL_ITERATIONS = 8`, fallback text (lines 44, 662–668)
- `core/tools.py` — verified `_handle_read_coaching_guide()` fuzzy match logic (lines 1500–1543)
- `core/autonomous.py` — verified `_synthesize_topic_key()` (line 375), outreach log informative-only semantics
- `docs/hybrid_athlete_blueprint.md` §6 — verified 6 fueling slots + supplement assignments
- `.planning/todos/pending/coaching-query-iteration-cap-double-send.md` — verified double-send root cause + fix options
- `.planning/todos/pending/phase-22-code-review-advisory.md` — verified WR-02 detail

### Secondary (MEDIUM confidence)
- `.planning/phases/24-strict-coaching-integration-nutrition-accountability/24-CONTEXT.md` — phase decisions (authoritative)
- `.planning/REQUIREMENTS.md` — requirements text + out-of-scope rows (authoritative)
- `CLAUDE.md` §6 Invariants — `OutreachLogStore.append` gated on `send_and_inject` success

### Tertiary (LOW confidence / training data)
- Garmin Feel scale (0/25/50/75/100 → Very Weak/Weak/Okay/Strong/Very Strong) — confirmed by ingest code comment; mapping itself is training knowledge [ASSUMED]
- Macro adherence thresholds (protein <120g, carbs <250g) as "structurally meaningful" — training data judgment [ASSUMED, Claude's discretion per D-09]

---

## Project Constraints (from CLAUDE.md)

- All GCP/Pinecone resource names lowercase `klaus-` (uppercase = silent 404). New Firestore collection name must be: `coaching_topics` (not `CoachingTopics`)
- `load_dotenv` always with `override=True`
- Embeddings via Gemini AI Studio, never Vertex (not relevant to Phase 24)
- `OutreachLogStore.append` is gated on `send_and_inject` success — mirror this in `CoachingTopicStore.add_topic()`
- `_get_orchestrator()` is a process-wide singleton — do not construct a new `AgentOrchestrator` in cron helpers
- `_jsonsafe_doc` / `_jsonsafe_value` must be applied to any new Firestore read that goes through `json.dumps` (SERVER_TIMESTAMP pitfall)
- Test baseline: 911+ tests passing; must hold after every plan

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all findings from live code audit
- Architecture: HIGH — all integration points verified against actual code; line numbers checked
- Pitfalls: HIGH — most derived from existing pitfall patterns in the codebase (OutreachLogStore NOTE 2, Pitfall 4 `feel==0`, `_jsonsafe_doc`, timezone keying)
- Thresholds (macro, slot windows): MEDIUM — Claude's discretion; reasonable defaults for the domain

**Research date:** 2026-06-06
**Valid until:** 2026-07-06 (stable codebase; only changes if Phase 24 implementation changes the integration points before planning completes)
