# Phase 23: Block + Benchmark Tracking — Research

**Researched:** 2026-06-05
**Domain:** Firestore store design, brain-direct tool pattern, cron integration, week/block math, biometric validity gating
**Confidence:** HIGH — all claims verified against live codebase or locked planning artifacts

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 — Auto-seed all 4 mesocycle blocks at cycle start.**
When the cycle anchor (`plan_start_date` = 2026-06-21) arrives, Klaus auto-creates the four 4-week blocks:
- Block 1: W1–4 **Aerobic Base**, end 2026-07-18 (deload W4)
- Block 2: W5–8 **Capacity Build**, end 2026-08-15 (deload W8)
- Block 3: W9–12 **Deep Waters → Peak Engine**, end 2026-09-12 (deload W12)
- Block 4: W13–16 **Race Specificity → Taper → Race Week**, end 2026-10-10 (race W16)

`get_current()` always resolves the active block by date. No manual `start_block` needed for normal flow.

**D-02 — Benchmarks fire at W4 / W8 / W12 deloads only; W16 is the race.**
`benchmark_due` is only ever set on Blocks 1–3. Block 4's terminal test is the actual half-marathon.

**D-03 — Week number is always derived, never stored as truth.**
`week_num = (today - plan_start_date).days // 7 + 1`. Phase name per week comes from blueprint §4.
The block doc holds `start_date`/`end_date`/`label`/`focus_facets`/`benchmark_due`; current week is computed at read time.

**D-04 — Pre-cycle behavior = light countdown note.**
Before 2026-06-21, `get_current()` returns `None` and no benchmark logic runs. Crons surface:
*"Pre-cycle, Sir — your 16-week build begins in N days (Sun 2026-06-21)."*

**D-05 — Mixed capture method by facet:**
- Push-ups / pull-ups → fresh max-rep set (logged via `log_benchmark`, unit `reps`)
- Bench / squat → Epley estimate from heaviest top-set that block (`1RM ≈ w × (1 + reps/30)`)
- Threshold pace → average of last 3 threshold sessions from Garmin (Postgres), unit `sec/km`

**D-06 — Five facets benchmarked at each deload:** bench, squat, push-ups, pull-ups, threshold pace. 3k/400m speed tests deferred to November-deadline window.

**D-07 — Gate thresholds:** Defer benchmark when HRV < 70% of 7-day baseline OR ACWR > 1.2. Garmin recovery treated as always-fresh (Phase 22 D-06).

**D-08 — On gate failure: defer + auto-re-prompt when biometrics clear.** Klaus keeps `benchmark_due = True` and the 21:30 cron re-checks each evening. Re-prompts the moment HRV ≥ 70% baseline AND ACWR ≤ 1.2.

**D-09 — Stale-window fallback.** If deload week ends still red, Klaus prompts once with explicit stale-conditions caveat so the result can still be recorded.

### Claude's Discretion

- Exact `BlockStore` / `BenchmarkStore` schema field names and lazy-singleton + never-raises read discipline (mirror existing stores per ARCHITECTURE §IP4).
- Whether auto-seed (D-01) runs as a one-time idempotent script (like `scripts/ingest_blueprint.py`) or lazily on first `get_current()` after the anchor — as long as it is idempotent and derives dates from `plan_start_date`.
- Exact "Week N of 16, [phase]" wording and placement in each cron message.
- Whether to additionally apply the optional "not preceded by a heavy training day" validity criterion on top of the two ROADMAP gate thresholds (D-07).
- Epley vs. Brzycki for the strength estimate; rounding for displayed benchmark numbers.
- `get_block_status` payload shape (current block + its benchmarks + raw delta vs prior block) and `_HANDLERS` wiring for all 7 tools.
- How the re-prompt cadence (D-08) is expressed in `proactive_alert.md` without spamming.

### Deferred Ideas (OUT OF SCOPE)

- 3k / 400m maximal-sprint benchmarks — prompted only near the November deadline, not at deloads.
- Pace-to-deadline trend projection + per-facet improvement trajectory in the Sunday review → Phase 25 (PROG-02).
- Session-quality annotation at log time → Phase 24 (PROG-04).
- Cross-cron coaching dedup / strict skip pushback / nutrition accountability → Phase 24.
- Any new crons, backends, or dependencies.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BLOCK-01 | Klaus tracks the current training block (start date 2026-06-21, week number, phase name) and surfaces block context in coaching messages. | BlockStore + `get_current()` + week-math formula + cron gather hooks in morning briefing, proactive alerts, weekly review |
| BLOCK-02 | At block ends (deload weeks) Klaus prompts a benchmark test session with a standardized protocol and conditions — no periodic mid-block testing. | `benchmark_due` flag state machine in proactive_alerts + HRV/ACWR validity gate + D-08/D-09 defer/stale-window logic |
| BLOCK-03 | Klaus records benchmark results and compares them across blocks to show per-facet improvement over time. | BenchmarkStore with `{date}_{facet}` doc IDs + `log_benchmark` + `get_benchmark_history` + `get_block_status` tools |
</phase_requirements>

---

## Summary

Phase 23 gives Klaus a persistent notion of where Amit is in his 16-week training cycle by adding two new Firestore stores (`BlockStore` and `BenchmarkStore`) to `memory/firestore_db.py`, seven brain-direct tools to `core/tools.py`, and best-effort block-state gather steps to three existing crons. No new scheduler job is created — the `benchmark_due` flag on the block doc acts as a state machine that the existing 21:30 proactive-alerts cron checks and re-checks each evening until the benchmark fires (D-08) or the stale-window fallback fires (D-09).

The critical implementation pattern is already established in the codebase. `TrainingLogStore` (added Phase 20) and `MealStore` (Phase 19) are the direct templates: lazy-singleton constructor, never-raises reads, `_jsonsafe_doc()` on all read paths, `merge=True` writes that stamp `updated_at: firestore.SERVER_TIMESTAMP`. Every read path in this phase must apply `_jsonsafe_doc()` because `updated_at` and `created_at` SERVER_TIMESTAMP fields read back as `DatetimeWithNanoseconds`, which breaks `json.dumps` — this has bitten Phase 19 and Phase 20 and is a project-wide invariant.

The auto-seed decision (D-01) produces the cleanest design as an idempotent script following the exact pattern of `scripts/ingest_blueprint.py` — it can be run once at cycle start (2026-06-21) and is safe to re-run. The alternative (lazy-seed inside `get_current()`) requires write logic inside a read path, which violates the never-raises read discipline.

**Primary recommendation:** Mirror `TrainingLogStore` exactly for `BlockStore` and `BenchmarkStore`. Auto-seed via a script on the cycle anchor date. Use `benchmark_due` flag state machine inside the existing 21:30 cron. All 7 tools are brain-direct, excluded from worker.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Block tracking / week-number math | API / Backend (Firestore + Python) | — | Derived from `plan_start_date`; computed server-side at read time |
| Benchmark trigger detection | API / Backend (proactive_alerts cron) | — | The 21:30 cron checks `benchmark_due` flag; no client or new scheduler needed |
| Benchmark validity gate (HRV/ACWR) | API / Backend (proactive_alerts cron) | — | Gate reads Garmin via `compute_recovery_concern` already imported in that cron |
| Benchmark recording | API / Backend (BenchmarkStore + brain-direct tool) | — | `log_benchmark` tool writes to BenchmarkStore; brain judges when to call it |
| Cross-block comparison | API / Backend (BenchmarkStore read) | — | `get_facet_history` + `get_block_benchmarks` serve data; brain composes the delta |
| Block state surfacing in crons | API / Backend (gather steps) | Prompt Layer | Python gather hooks assemble data; prompt instructions render it in correct Klaus voice |
| Brain-direct tool dispatch | Tools Layer (core/tools.py) | — | SMART_AGENT_DIRECT_TOOLS; excluded from WORKER_TOOL_SCHEMAS |

---

## Standard Stack

### Core (all existing — no new external dependencies)

| Component | Current Version in Codebase | Purpose | Why Standard |
|-----------|--------------------------|---------|--------------|
| `google-cloud-firestore` | Already installed (production) | `BlockStore` + `BenchmarkStore` persistence | Matches all other stores; same auth, same `_make_firestore_client` helper |
| `memory/firestore_db.py` | Live in repo | House both new store classes | Module-level discipline (`_jsonsafe_doc`, `_jsonsafe_value`, lazy singletons) established and tested |
| `core/tools.py` | Live in repo | 7 brain-direct tool schemas + handlers + `_HANDLERS` dispatch | Established pattern from Phases 19–22 |
| `core/proactive_alerts.py` | Live in repo | `benchmark_due` state machine + re-prompt logic | Already runs nightly, has `send_and_inject` infrastructure |
| `core/morning_briefing.py` | Live in repo | Block state in gather dict | Best-effort gather pattern established |
| `core/weekly_training_review.py` | Live in repo | Block benchmarks in gather dict | Same pattern as MealStore and UserProfileStore gather steps |

**No new packages to install.** [VERIFIED: live codebase]

### Supporting

| Component | Purpose | When to Use |
|-----------|---------|-------------|
| `scripts/ingest_blueprint.py` (existing) | Template for the auto-seed script | The Phase 23 `scripts/seed_training_blocks.py` script follows this exact pattern: pure builder function + dry-run + force flags + idempotency check |
| `compute_recovery_concern` in `core/training_checkin.py` | HRV/ACWR validity gate reads | Called in `run_proactive_alerts()` already; benchmark gate reads same dict |
| `_jsonsafe_doc()` in `memory/firestore_db.py` | Serialize Firestore docs for JSON | Must be applied to every `snap.to_dict()` result in BlockStore and BenchmarkStore read paths |

---

## Package Legitimacy Audit

> No new external packages are introduced in this phase. All dependencies are already installed in the production environment.

| Package | Registry | Status | Disposition |
|---------|----------|--------|-------------|
| google-cloud-firestore | PyPI | Already in prod Dockerfile | Approved — no new install |
| (no others) | — | — | — |

**Packages removed due to slopcheck:** none
**Packages flagged as suspicious:** none

---

## Architecture Patterns

### System Architecture Diagram

```
Cycle anchor arrives (2026-06-21)
    ↓
scripts/seed_training_blocks.py  [one-time idempotent]
    → BlockStore.seed_blocks()
    → Creates 4 docs in training_blocks/{block_id}
    → Sets UserProfileStore.current_block_id = "block_1"

─────────────────────────────────────────

CHAT PATH (reactive)
User message → AgentOrchestrator
    ↓
Brain calls get_plan  → UserProfileStore.load() + BlockStore.get_current()
Brain calls get_block_status  → BlockStore.get_current() + BenchmarkStore.get_block_benchmarks()
Brain calls log_benchmark  → BenchmarkStore.log_benchmark()   [after Amit reports result]
Brain calls end_block  → BlockStore.end_block() + clear current_block_id

─────────────────────────────────────────

CRON PATH — 21:30 proactive alerts
Cloud Scheduler → POST /cron/proactive-alerts
    ↓
run_proactive_alerts():
  1. run_training_checkin()  [existing]
  2. dedup gate check  [_already_sent()]  — SKIP block logic if already processed
  3. BlockStore.get_current()  [best-effort]
       ↓ active block found?
       Yes: check block.end_date proximity (within 3 days)
             → set benchmark_due = True if not already set
            check benchmark_due == True?
             → read Garmin HRV 7-day baseline + ACWR
             → validity gate: HRV >= 70% baseline AND ACWR <= 1.2?
                  PASS: include "benchmark_window_open" in alerts_context
                  FAIL: include "benchmark_deferred" + reason in alerts_context (D-08)
                  STALE (deload week ended, gate never cleared): include "benchmark_stale" (D-09)
       No (pre-cycle, or block complete): include countdown note (D-04) if pre-cycle
  4. compose + send + mark_processed

─────────────────────────────────────────

CRON PATH — morning briefing (*/10 6-10)
_gather_data():
  ...existing gather...
  + BlockStore.get_current()  [best-effort, silent omit on None]
    → if block: data["block"] = {label, week_num, benchmark_due, days_to_end}
    → if pre-cycle: data["pre_cycle_countdown"] = N_days

─────────────────────────────────────────

CRON PATH — Sunday weekly review (10:00)
_gather_week_data():
  ...existing gather...
  + BlockStore.get_current()
  + BenchmarkStore.get_block_benchmarks(block_id)
    → data["current_block"] = block dict
    → data["block_benchmarks"] = [list of benchmark dicts for this block]
```

### Recommended Project Structure

```
memory/
└── firestore_db.py          # Add BlockStore + BenchmarkStore classes here
                              # (same file as all other stores — do NOT create new file)
scripts/
└── seed_training_blocks.py  # New idempotent auto-seed script (mirror ingest_blueprint.py)
core/
├── tools.py                 # 7 new brain-direct tools: get_plan, get_block_status,
│                            # update_plan (already exists), log_benchmark,
│                            # get_benchmark_history, start_block, end_block
├── proactive_alerts.py      # Add block-end + benchmark_due check before dedup gate
├── morning_briefing.py      # Add BlockStore.get_current() to _gather_data()
└── weekly_training_review.py # Add block/benchmark gather to _gather_week_data()
prompts/
├── proactive_alert.md       # Add benchmark reminder rendering section
├── morning_briefing.md      # Add block-state rendering section
└── weekly_training_review.md # Add current_block + block_benchmarks rendering section
tests/
└── test_block_benchmark_store.py  # New test file (RED-first, mirror test_training_log_store.py)
```

### Pattern 1: Firestore Store (mirror TrainingLogStore exactly)

**What:** Lazy-singleton constructor, never-raises reads (return `[]` or `None`), re-raising writes, `_jsonsafe_doc()` on all read paths, `merge=True` + `updated_at: SERVER_TIMESTAMP` on all writes.

**When to use:** All `BlockStore` and `BenchmarkStore` read methods.

**Example (from live code at `memory/firestore_db.py:844`):**
```python
# Source: memory/firestore_db.py TrainingLogStore.get_recent [VERIFIED: live codebase]
def get_recent(self, days: int) -> list[dict]:
    try:
        snaps = list(self._col.stream())
        results = []
        for snap in snaps:
            d = _jsonsafe_doc(snap.to_dict() or {})  # <-- MANDATORY
            d["doc_id"] = snap.id
            ...
        return results
    except Exception:
        logger.warning("TrainingLogStore.get_recent failed", exc_info=True)
        return []  # <-- NEVER raises
```

**BlockStore.get_current() equivalent:**
```python
# Source: pattern from ARCHITECTURE.md §IP4 [VERIFIED: live planning artifact]
def get_current(self) -> dict | None:
    """Return the active block or None. Never raises."""
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        snaps = list(
            self._col.where(filter=FieldFilter("status", "==", "active")).stream()
        )
        if not snaps:
            return None
        d = _jsonsafe_doc(snaps[0].to_dict() or {})
        d["doc_id"] = snaps[0].id
        return d
    except Exception:
        logger.warning("BlockStore.get_current() failed", exc_info=True)
        return None
```

### Pattern 2: Brain-Direct Tool Handler (mirror `_handle_get_training_profile`)

**What:** Handler reads store, returns JSON string. Never raises to the caller. Registered in `SMART_AGENT_DIRECT_TOOLS`, excluded from `WORKER_TOOL_SCHEMAS`.

**Example (from live code at `core/tools.py`):**
```python
# Source: core/tools.py _handle_get_training_profile [VERIFIED: live codebase]
def _handle_get_training_profile() -> str:
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    profile = store.load()
    return json.dumps(_jsonsafe_doc(profile) if profile else {})
```

**`update_plan` coexistence note:** `update_plan` already exists in `_HANDLERS` (line 1576) as an alias for `_handle_update_training_profile`. The 7 Phase 23 tools include `start_block`, `end_block`, `get_plan`, `get_block_status`, `log_benchmark`, `get_benchmark_history` — `update_plan` is already registered and does NOT need to be re-added. [VERIFIED: live codebase]

### Pattern 3: Best-Effort Gather with Silent Omit

**What:** Each cron gather step wraps every data source in `try/except`. On exception: set key to `None` and `logger.warning`. The prompt omits the section when the key is absent or `None`.

**Example (from live code at `core/morning_briefing.py:174`):**
```python
# Source: core/morning_briefing.py _gather_data() [VERIFIED: live codebase]
try:
    from memory.firestore_db import MealStore
    agg = ms.get_day_aggregate(yesterday)
    if agg:  # silent-omit gate
        data["nutrition"] = agg
except Exception:
    logger.warning("morning_briefing: meals aggregate failed", exc_info=True)
    # no data["nutrition"] key set → prompt omits silently
```

**Block state gather equivalent:**
```python
try:
    from memory.firestore_db import BlockStore
    block_store = BlockStore(project_id, database)
    block = block_store.get_current()
    if block:
        from datetime import date as _date
        plan_start = _date.fromisoformat("2026-06-21")  # from UserProfileStore
        week_num = (today - plan_start).days // 7 + 1
        data["block"] = {
            "label": block.get("label"),
            "week_num": week_num,
            "benchmark_due": block.get("benchmark_due", False),
            "end_date": block.get("end_date"),
        }
    else:
        # Pre-cycle: compute countdown
        days_until = (_date.fromisoformat("2026-06-21") - today).days
        if days_until > 0:
            data["pre_cycle_countdown"] = days_until
except Exception:
    logger.warning("morning_briefing: block state fetch failed", exc_info=True)
    # silent omit
```

### Pattern 4: Idempotent Seed Script (mirror `scripts/ingest_blueprint.py`)

**What:** Pure builder function + CLI flags `--dry-run` / `--force` + idempotency check on existing data. Never overwrites unless `--force`.

**Idempotency check for auto-seed:**
```python
# Source: scripts/ingest_blueprint.py pattern [VERIFIED: live codebase]
def seed_if_absent(store: BlockStore, *, force: bool = False) -> bool:
    """Return True if seeding happened. Never raises."""
    existing = store.get_all()
    if existing and not force:
        logger.info("Blocks already seeded (%d blocks) — skipping. Use --force to re-seed.", len(existing))
        return False
    # ... build and write the 4 blocks
    return True
```

### Anti-Patterns to Avoid

- **Storing week number as ground truth:** Week number must always be derived from `(today - plan_start_date).days // 7 + 1`. Storing it as a field means it drifts if the plan start date changes (Pitfall 7 in PITFALLS.md).
- **benchmark_due trigger as a new Cloud Scheduler job:** The 21:30 cron already runs daily with `send_and_inject` infrastructure. A new job is over-engineering (ARCHITECTURE.md Anti-Pattern 1).
- **Storing block benchmarks in TrainingLogStore:** `TrainingLogStore` is keyed `{date}_{slot}` for session-level entries. Benchmarks are per-facet measurement events, not sessions. Dedicated `BenchmarkStore` keeps both collections cheap to scan (ARCHITECTURE.md Anti-Pattern 3).
- **Applying the validity gate in the wrong cron:** The gate logic (HRV/ACWR check) belongs in `run_proactive_alerts()` — the same function that already calls `compute_recovery_concern()`. Do not duplicate gate logic in morning_briefing.
- **Silently skipping benchmark if gate never clears (missing D-09):** The stale-window fallback (D-09) is a contract — Amit must get one final prompt with the caveat, not a silent drop.
- **Calling `BlockStore` write methods in a read path (lazy-seed anti-pattern):** `get_current()` must never write. Seed logic belongs in the seed script, not inside the store's read methods.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Firestore timestamp serialization | Custom datetime→string converter | `_jsonsafe_doc()` + `_jsonsafe_value()` already in `memory/firestore_db.py` | These helpers handle nested dicts/lists recursively; shallow converter misses timestamps buried inside block `focus_facets` list |
| Week number from date | Hardcode week numbers or store them | `(today - plan_start_date).days // 7 + 1` — always derived at read time (D-03) | Stored week numbers drift if plan start shifts; the formula is 1 line |
| Epley 1RM formula | Custom strength-estimation logic | `1RM ≈ weight × (1 + reps / 30)` — one expression in the handler, no library needed | This is a single arithmetic formula; importing a library would be overkill |
| HRV/ACWR validity check | Re-reading Garmin raw data in the alert cron | `compute_recovery_concern()` from `core/training_checkin.py` already returns `{level, acwr, hrv_status, ...}` | Reuse the same function already called in `run_proactive_alerts()` |
| Active block query | Python-side filter of all blocks | Firestore `FieldFilter("status", "==", "active")` — server-side filter | One-item result set; scanning all blocks in Python is wasteful |

**Key insight:** Almost all complexity in this phase is wiring pattern, not algorithm. The week-math is one line, the Epley formula is one line, the validity gate already exists. The work is correctly mirroring the established store/tool/cron discipline.

---

## Runtime State Inventory

> This phase seeds NEW Firestore state and adds FK fields to an existing doc — not a rename/refactor. The relevant inventory is what must exist BEFORE this phase and what this phase creates.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data (pre-existing) | `users/amit` doc in Firestore — `plan_start_date = "2026-06-21"` already populated by Phase 21 `ingest_blueprint.py` | Read in seed script and all compute paths; no migration needed |
| Stored data (new — this phase) | `training_blocks` collection (4 docs) + `benchmarks` collection (empty until Amit logs) | Created by `scripts/seed_training_blocks.py` on 2026-06-21 |
| Stored data (modified) | `users/amit.current_block_id` FK field | Added to UserProfileStore scaffold; `start_block` + `end_block` tools set/clear it |
| Live service config | No external service configuration changes — no new Cloud Scheduler jobs, no new Cloud Run routes | None |
| OS-registered state | None — no scheduler registrations | None |
| Secrets/env vars | No new secrets or env vars required | None |
| Build artifacts | No new packages; `tests/test_block_benchmark_store.py` is a new test file only | None |

**Timing note:** The seed script should be run on 2026-06-21 or via `--dry-run` for testing before that date. Before the anchor date, `get_current()` returns `None` and all crons surface the pre-cycle countdown (D-04) — no blocks exist yet, which is correct.

---

## Common Pitfalls

### Pitfall 1: SERVER_TIMESTAMP → DatetimeWithNanoseconds breaks json.dumps

**What goes wrong:** `BlockStore.get_current()` or `BenchmarkStore.get_facet_history()` returns a doc containing `updated_at` or `created_at` that was written as `firestore.SERVER_TIMESTAMP`. When that doc is passed to `json.dumps()` (e.g., inside a tool handler), `json.dumps` raises `TypeError: Object of type DatetimeWithNanoseconds is not JSON serializable`.

**Why it happens:** `firestore.SERVER_TIMESTAMP` is a write sentinel that Firestore resolves server-side to a `DatetimeWithNanoseconds` object on read. `json.dumps` does not know how to serialize it.

**How to avoid:** Apply `_jsonsafe_doc()` to every `snap.to_dict()` result in every read method. This is mandatory — `_jsonsafe_value()` recurses into nested dicts/lists. **This pattern is already established in `TrainingLogStore.get_recent()` (line 862) and must be copied verbatim.** [VERIFIED: live codebase — bitten Phase 19 MealStore + Phase 20 TrainingLogStore]

**Warning signs:** `TypeError: Object of type DatetimeWithNanoseconds` in any block/benchmark tool handler or cron gather step.

### Pitfall 2: `update_plan` already registered — do not re-add

**What goes wrong:** The implementation adds `update_plan` to `SMART_AGENT_DIRECT_TOOLS` and `_HANDLERS`, producing a `KeyError` or duplicate key at module load time.

**Why it happens:** `update_plan` was added in Phase 21 (line 1576 of `core/tools.py`) as an alias for `_handle_update_training_profile`. It is already in both `SMART_AGENT_DIRECT_TOOLS` (line 57) and `_HANDLERS`. Phase 23 adds 6 new tools: `get_plan`, `get_block_status`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block`. [VERIFIED: live codebase]

**How to avoid:** Read `SMART_AGENT_DIRECT_TOOLS` and `_HANDLERS` in `core/tools.py` before adding. `update_plan` is already there. Only add the 6 genuinely new tools.

### Pitfall 3: `benchmark_due` flag set BEFORE the dedup gate in proactive_alerts

**What goes wrong:** The benchmark_due state mutation (setting the flag to `True`) happens inside the `_already_sent()` guard, meaning it never runs on days the cron already processed.

**Why it happens:** `_already_sent()` at line 110 of `proactive_alerts.py` exits early. The training check-in (line 102) runs BEFORE the gate. The block-end check must also run BEFORE the gate — otherwise the first nightly check that finds `block.end_date ≈ today` never sets `benchmark_due`.

**How to avoid:** Place the block-end check + `benchmark_due` setter BEFORE the `_already_sent()` check, following the same pattern as `run_training_checkin()` at line 102. The re-prompt logic (reading `benchmark_due` and composing the reminder) can happen INSIDE the gate (it feeds into `alerts_context` which only matters when an alert actually sends). [VERIFIED: live codebase structure]

**Clarification on the pattern:**
```
run_training_checkin()   [BEFORE gate — idempotent, always runs]
block_end_check()        [BEFORE gate — sets benchmark_due flag, idempotent]
if _already_sent(): return
[benchmark_due re-prompt logic goes here, inside guard]
```

### Pitfall 4: Pre-cycle behavior silently breaks cron gather steps

**What goes wrong:** Before 2026-06-21, `BlockStore.get_current()` returns `None`. Code that unconditionally accesses `block["label"]` or `block["week_num"]` raises `TypeError: 'NoneType' is not subscriptable`.

**Why it happens:** The gather step adds block state without checking for None.

**How to avoid:** Always guard with `if block:` before accessing any field. Use the silent-omit pattern: if `block` is `None`, either don't set the key at all, or set `data["pre_cycle_countdown"]` (D-04). The prompt section for block state must also handle the absent key cleanly. [VERIFIED: D-04 decision, CONTEXT.md]

### Pitfall 5: Benchmark validity gate double-reading Garmin

**What goes wrong:** The block-end check in `run_proactive_alerts()` fetches Garmin independently to compute HRV/ACWR, after `compute_recovery_concern()` already fetched Garmin data for the recovery concern. Two separate Garmin API calls in the same cron execution.

**Why it happens:** The block-end check naively calls `fetch_garmin_today()` without reusing the data already gathered.

**How to avoid:** The `compute_recovery_concern()` call (lines 154–167 of `proactive_alerts.py`) already produces `rc["acwr"]` and `rc["hrv_status"]`. Pass the `garmin_data` from that call into the benchmark validity check, or use the `rc` dict directly (it already has `level`, `acwr`, `hrv_status`). No second Garmin fetch needed. [VERIFIED: live proactive_alerts.py]

### Pitfall 6: `block_id` FK on UserProfileStore gets stale

**What goes wrong:** `current_block_id` on `users/amit` points to Block 1, but Block 1 has `status = "complete"`. A future `get_current()` call returns Block 1 (if queried by FK) rather than the active block.

**Why it happens:** The FK is a convenience cache. If `end_block()` doesn't clear it, it stays stale.

**How to avoid:** `end_block()` must atomically set `BlockStore.status = "complete"` AND clear `UserProfileStore.current_block_id = None`. `get_current()` should query by `status == "active"` (Firestore FieldFilter), NOT by FK lookup. The FK is context metadata for the brain, not the query key. [VERIFIED: ARCHITECTURE.md §IP4]

---

## Code Examples

### BlockStore schema (from ARCHITECTURE.md §IP4 + live code patterns)
```python
# Source: .planning/research/ARCHITECTURE.md §Integration Point 4 [VERIFIED: locked artifact]
# Collection: training_blocks
# Document ID: {YYYY-MM-DD}_{label}  e.g. "2026-06-21_aerobic_base"
BLOCK_FIELDS = {
    "block_id":               str,    # same as doc id
    "label":                  str,    # "Aerobic Base"
    "start_date":             str,    # YYYY-MM-DD
    "end_date":               str,    # YYYY-MM-DD
    "focus_facets":           list,   # ["bench_press", "squat", "push_ups", "pull_ups", "threshold_pace"]
    "weekly_split_override":  dict,   # None for auto-seeded blocks (use UserProfileStore.weekly_split)
    "status":                 str,    # "active" | "complete" | "abandoned"
    "notes":                  str,    # ""
    "benchmark_due":          bool,   # False until deload week triggers it
    "created_at":             ...,    # SERVER_TIMESTAMP
    "updated_at":             ...,    # SERVER_TIMESTAMP
}
```

### BenchmarkStore schema
```python
# Source: .planning/research/ARCHITECTURE.md §Integration Point 4 [VERIFIED: locked artifact]
# Collection: benchmarks
# Document ID: {YYYY-MM-DD}_{facet}  e.g. "2026-07-18_bench_press_1rm"
BENCHMARK_FIELDS = {
    "date":      str,    # YYYY-MM-DD
    "facet":     str,    # "bench_press_1rm" | "squat_1rm" | "push_ups" | "pull_ups" | "threshold_pace"
    "value":     float,  # the number
    "unit":      str,    # "kg" | "reps" | "sec_per_km"
    "block_id":  str,    # FK → training_blocks doc id
    "notes":     str,    # optional e.g. "Epley estimate from 85kg×5" or "tested-under-fatigue"
    "updated_at": ...,   # SERVER_TIMESTAMP
}
```

### Week-number math formula
```python
# Source: .planning/STATE.md Accumulated Context + D-03 CONTEXT.md [VERIFIED: locked decisions]
from datetime import date as _date

def get_week_num(plan_start_date: str, today: str) -> int | None:
    """Return 1-based week number, or None if today is before the cycle start."""
    start = _date.fromisoformat(plan_start_date)
    today_dt = _date.fromisoformat(today)
    if today_dt < start:
        return None
    return (today_dt - start).days // 7 + 1
```

### Epley 1RM estimate
```python
# Source: D-05 CONTEXT.md [ASSUMED — standard sports science formula, no library needed]
def epley_1rm(weight_kg: float, reps: int) -> float:
    """Estimate 1-rep max from a heavy top-set using Epley formula."""
    return round(weight_kg * (1 + reps / 30), 1)
```

### 7 new tools in SMART_AGENT_DIRECT_TOOLS (incremental addition)
```python
# Source: core/tools.py lines 40-62 [VERIFIED: live codebase]
# Current SMART_AGENT_DIRECT_TOOLS contains: remember, recall, run_morning_briefing,
# search_chat_history, list_own_files, read_own_source, search_own_source,
# get_self_status, schedule_followup, list_followups, cancel_followup,
# get_training_profile, update_training_profile, update_plan (Phase 21),
# log_training, read_coaching_guide.
#
# Phase 23 adds (update_plan ALREADY EXISTS — do not re-add):
NEW_DIRECT_TOOLS = {
    "get_plan",              # UserProfileStore.load() + BlockStore.get_current()
    "get_block_status",      # current block + benchmarks + delta vs prior block
    "log_benchmark",         # BenchmarkStore.log_benchmark()
    "get_benchmark_history", # BenchmarkStore.get_facet_history(facet, n)
    "start_block",           # BlockStore.start_block() + set current_block_id
    "end_block",             # BlockStore.end_block() + clear current_block_id
}
```

### Threshold pace computation from Postgres
```python
# Source: D-05 CONTEXT.md [ASSUMED — pattern follows existing database_tool.py usage]
# Average of last 3 threshold sessions from Garmin activities in Postgres.
# Executed via query_health_database() in mcp_tools/database_tool.py.
SQL = """
SELECT AVG(avg_pace_sec_per_km) as threshold_pace_avg
FROM (
  SELECT duration_seconds / (distance_km * 60.0) as avg_pace_sec_per_km
  FROM activities
  WHERE activity_type ILIKE '%threshold%'
    AND date >= CURRENT_DATE - INTERVAL '28 days'
  ORDER BY date DESC
  LIMIT 3
) sub
"""
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Block tracking via manual "this block" references in prompts | Persistent `BlockStore` with `get_current()` + derived week math | Phase 23 (this phase) | Brain always knows exact block dates; benchmark trigger is deterministic |
| D-13 guard (no numbers at all) | Tier A (blueprint targets) + Tier B (measured data within recency window) | Phase 22 | Brain can now cite benchmark results from `BenchmarkStore` as named numbers |
| No benchmark history | `BenchmarkStore` with `{date}_{facet}` doc IDs | Phase 23 (this phase) | Cross-block comparison becomes possible after Block 1 benchmarks are logged |

**Deprecated/outdated patterns to avoid:**
- `benchmark_due` logic in a new Cloud Scheduler job — the 21:30 cron is the standard slot (ARCHITECTURE.md Anti-Pattern 1).
- Mixing block metadata with `TrainingLogStore` via a `benchmark: true` flag — dedicated store is the established pattern (ARCHITECTURE.md Anti-Pattern 3).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Epley formula `1RM ≈ w × (1 + reps/30)` — sports science formula, not verified against an official reference | Code Examples: Epley 1RM | Low — this is one of two standard formulas (Epley vs Brzycki); Claude's Discretion says either is acceptable. The difference at 5 reps is < 2%. |
| A2 | Threshold pace SQL uses `activity_type ILIKE '%threshold%'` — assumes Garmin activities table has a string activity_type column | Code Examples: threshold pace SQL | Medium — if the column name or type label differs in the live Postgres schema, the query returns no rows. Planner should verify column name against `mcp_tools/database_tool.py` and the existing Garmin SQL patterns in `core/weekly_training_review.py`. |
| A3 | `compute_recovery_concern()` return dict includes `acwr` and `hrv_baseline` fields reusable for benchmark validity gate | Pitfall 5 / proactive_alerts integration | Low — the function signature and return shape are verified in live code; the `acwr` key is confirmed. The HRV 7-day baseline comparison may need to be computed separately if `compute_recovery_concern` returns a pass/fail level rather than the raw baseline. Planner should verify `rc` dict keys in `core/training_checkin.py`. |
| A4 | Stale-window fallback (D-09) trigger: "deload week ended" = `block.end_date < today` and `benchmark_due == True` | Architecture: benchmark_due state machine | Low — the trigger condition is clear from D-09. Edge case: if `end_block()` is called before the benchmark fires, `benchmark_due` would be cleared — but `end_block` should not be callable before benchmarks are logged (brain judgment). |

**If this table were empty:** All claims verified or cited — no user confirmation needed. Three items require planner verification against live code.

---

## Open Questions

1. **HRV 7-day baseline: is it in `compute_recovery_concern()` return dict or must it be computed separately?**
   - What we know: `compute_recovery_concern()` in `core/training_checkin.py` returns a dict with `level`, `acwr`, `hrv_status`, `sleep_score`, `intensity`. `hrv_status` is likely a pass/fail string, not the raw baseline number.
   - What's unclear: Whether the dict exposes the raw 7-day HRV baseline needed to compute "HRV < 70% of baseline" numerically for the D-08 message ("HRV 61 — 78% of baseline, Sir").
   - Recommendation: Planner should read `core/training_checkin.py` `compute_recovery_concern()` return payload. If the baseline is not exposed, add it to the return dict (or compute it inline in the alert cron). The D-08 message template requires the numeric comparison.

2. **Threshold pace SQL schema: column names in Postgres `activities` table**
   - What we know: `mcp_tools/database_tool.py` provides `query_health_database(sql)`. Garmin activities are in Postgres. The weekly review already queries `daily_biometrics`.
   - What's unclear: The exact column names for activity type and pace in the `activities` table.
   - Recommendation: Planner should grep existing SQL in `core/weekly_training_review.py` and `mcp_tools/garmin_tool.py` for table/column references, or run a `SHOW COLUMNS FROM activities` query in the dry-run test.

3. **Auto-seed script vs. lazy-seed inside `get_current()`**
   - What we know: Claude's Discretion says either approach is acceptable as long as it's idempotent.
   - Recommendation: Script approach is strongly preferred. Writing inside a read path (`get_current()`) violates the never-raises read discipline — if the seed write fails, `get_current()` would need to either raise or return a half-valid state. The script pattern (like `ingest_blueprint.py`) is clean, testable, and the correct Klaus convention.

---

## Environment Availability

> This phase uses only existing infrastructure. No new external dependencies.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| google-cloud-firestore | BlockStore + BenchmarkStore | ✓ | Already in production | — |
| Garmin Postgres database | Threshold pace SQL, HRV baseline | ✓ | Already in production | Omit threshold pace facet from benchmark if query fails (best-effort) |
| `compute_recovery_concern` in training_checkin.py | Validity gate in proactive_alerts | ✓ | Live in repo | If it raises, gate defaults to PASS (don't block benchmark on unknown state — err toward prompting) |

**Missing dependencies with no fallback:** None.

---

## Validation Architecture

> `workflow.nyquist_validation` is enabled (absent key treated as true in config.json).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none (run from project root) |
| Quick run command | `python -m pytest tests/test_block_benchmark_store.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q --ignore=tests/__pycache__` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BLOCK-01 | `BlockStore.get_current()` returns active block with correct week number derived from plan_start_date | unit | `pytest tests/test_block_benchmark_store.py::test_get_current_returns_active_block -x` | Wave 0 |
| BLOCK-01 | Week number formula: `(today - plan_start_date).days // 7 + 1` is correct for boundary dates | unit | `pytest tests/test_block_benchmark_store.py::test_week_num_formula_boundary -x` | Wave 0 |
| BLOCK-01 | Pre-cycle: `get_current()` returns `None` when today < 2026-06-21 | unit | `pytest tests/test_block_benchmark_store.py::test_get_current_precycle_returns_none -x` | Wave 0 |
| BLOCK-01 | Morning briefing gather: block state in `data["block"]` when active, absent when pre-cycle | unit | `pytest tests/test_morning_briefing.py::test_gather_data_includes_block_state -x` | Wave 0 |
| BLOCK-02 | `benchmark_due` flag: set to `True` when `block.end_date` is within 3 days | unit | `pytest tests/test_block_benchmark_store.py::test_benchmark_due_flag_set_on_end_proximity -x` | Wave 0 |
| BLOCK-02 | Validity gate: gate returns PASS when HRV ≥ 70% baseline AND ACWR ≤ 1.2 | unit | `pytest tests/test_block_benchmark_store.py::test_validity_gate_pass -x` | Wave 0 |
| BLOCK-02 | Validity gate: gate returns FAIL when HRV < 70% baseline | unit | `pytest tests/test_block_benchmark_store.py::test_validity_gate_fail_hrv -x` | Wave 0 |
| BLOCK-02 | Validity gate: gate returns FAIL when ACWR > 1.2 | unit | `pytest tests/test_block_benchmark_store.py::test_validity_gate_fail_acwr -x` | Wave 0 |
| BLOCK-02 | Stale-window: benchmark fires with caveat when deload week ends with gate still red | unit | `pytest tests/test_block_benchmark_store.py::test_stale_window_fallback -x` | Wave 0 |
| BLOCK-02 | `benchmark_due` re-prompt does NOT fire on Block 4 (race week) | unit | `pytest tests/test_block_benchmark_store.py::test_no_benchmark_due_block_4 -x` | Wave 0 |
| BLOCK-03 | `log_benchmark` writes to `benchmarks/{date}_{facet}` with idempotent overwrite on same day | unit | `pytest tests/test_block_benchmark_store.py::test_log_benchmark_idempotent -x` | Wave 0 |
| BLOCK-03 | `get_facet_history` returns last N benchmarks for a facet, sorted date desc | unit | `pytest tests/test_block_benchmark_store.py::test_get_facet_history -x` | Wave 0 |
| BLOCK-03 | `get_block_benchmarks` returns all benchmarks for a given block_id | unit | `pytest tests/test_block_benchmark_store.py::test_get_block_benchmarks_by_block_id -x` | Wave 0 |
| ALL | Never-raises contract: `get_current()` returns None on Firestore exception | unit | `pytest tests/test_block_benchmark_store.py::test_get_current_never_raises -x` | Wave 0 |
| ALL | `_jsonsafe_doc` applied: no DatetimeWithNanoseconds in BlockStore read output | unit | `pytest tests/test_block_benchmark_store.py::test_block_store_jsonsafe_output -x` | Wave 0 |
| ALL | 7 new tools registered in SMART_AGENT_DIRECT_TOOLS (not WORKER_TOOL_SCHEMAS) | unit | `pytest tests/test_tool_registration_phase23.py -x` | Wave 0 |
| ALL | Full suite baseline: 780+ tests pass, no new failures | regression | `python -m pytest tests/ -x -q` | Existing |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_block_benchmark_store.py tests/test_tool_registration_phase23.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (780+ tests) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_block_benchmark_store.py` — covers BLOCK-01/02/03 store behavior (mirror `tests/test_training_log_store.py` mock strategy with sys.modules Firestore mock)
- [ ] `tests/test_tool_registration_phase23.py` — covers 7 new tools in SMART_AGENT_DIRECT_TOOLS, excluded from WORKER_TOOL_SCHEMAS, present in _HANDLERS
- [ ] `tests/test_morning_briefing.py::test_gather_data_includes_block_state` — new test function in existing file
- [ ] `tests/test_proactive_alerts.py::test_benchmark_due_check_before_dedup_gate` — new test function in existing file

*(All other existing test infrastructure covers phase requirements without changes.)*

---

## Security Domain

> `security_enforcement` not explicitly set to false in config.json — treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase adds no new auth paths |
| V3 Session Management | No | BlockStore/BenchmarkStore are persistent stores, not session state |
| V4 Access Control | Yes (low risk) | Brain-direct tools are excluded from WORKER_TOOL_SCHEMAS — worker cannot call `start_block`, `end_block`, `log_benchmark`. Access control is structural. [VERIFIED: existing pattern in tools.py] |
| V5 Input Validation | Yes | `log_benchmark` tool accepts `value` (float), `unit` (str from closed set), `facet` (str from closed set). Handler should validate unit and facet against allowed values to prevent garbage writes. |
| V6 Cryptography | No | No new encryption; Firestore encryption at rest is GCP-managed |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Benchmark value injection (e.g., `value: 999999`) | Tampering | Handler validates `value` is a positive float within a plausible range; or brain judgment rejects implausible inputs |
| Facet name injection creating arbitrary Firestore documents | Tampering | Handler validates `facet` against a closed enum list of allowed facet names (bench_press_1rm, squat_1rm, push_ups, pull_ups, threshold_pace) |
| Block document status manipulation via `start_block` + `end_block` without validation | Tampering | Both tools are brain-direct; worker cannot call them. Brain always checks existing state before writing. |
| `read_coaching_guide` path traversal (existing T-22-04 mitigation) | Information Disclosure | Already mitigated in Phase 22 — slug normalization prevents path escape. No new exposure in Phase 23. |

---

## Sources

### Primary (HIGH confidence)
- `.planning/phases/23-block-benchmark-tracking/23-CONTEXT.md` — All D-01 through D-09 decisions, verbatim
- `.planning/research/ARCHITECTURE.md` §Integration Point 4 — BlockStore/BenchmarkStore schemas, 7-tool table, cron-surfacing plan, benchmark_due trigger state machine
- `.planning/research/PITFALLS.md` §Pitfall 7 — block_start_date/block_end_date, 3-day window, validity checklist
- `memory/firestore_db.py` — live store patterns: TrainingLogStore (line 764), MealStore (line 574), OutreachLogStore (line 1289), `_jsonsafe_doc` (line 733), UserProfileStore scaffold (line 138)
- `core/tools.py` — live SMART_AGENT_DIRECT_TOOLS (line 40), _HANDLERS (line 1551), `update_plan` already registered (line 1576)
- `core/proactive_alerts.py` — live `run_proactive_alerts()` structure, training check-in before dedup gate (lines 91–175)
- `core/morning_briefing.py` — live `_gather_data()` best-effort pattern (lines 174–273)
- `core/weekly_training_review.py` — live `_gather_week_data()` pattern (lines 42–193)
- `scripts/ingest_blueprint.py` — idempotent seed script pattern template
- `docs/hybrid_athlete_blueprint.md` §4 — 16-week progression table, deload weeks 4/8/12, phase names
- `.planning/REQUIREMENTS.md` — BLOCK-01/02/03 full text
- `.planning/STATE.md` — locked v4.0 research decisions

### Secondary (MEDIUM confidence)
- `.planning/config.json` — nyquist_validation enabled, commit_docs: true
- `tests/test_training_log_store.py` — Firestore mock strategy to mirror for new test file
- `tests/test_firestore_db.py` — `_install_firestore_mock()` pattern reference

### Tertiary (LOW confidence / ASSUMED)
- Epley formula `1RM ≈ w × (1 + reps/30)` — standard sports science formula from training knowledge; not verified against a cited academic source [ASSUMED — see A1]
- Threshold pace SQL column names — derived from pattern observation, not run against live Postgres [ASSUMED — see A2]

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — all components are existing production code verified in live files
- Architecture: HIGH — BlockStore/BenchmarkStore schemas and 7-tool table from locked planning artifacts, verified against live code patterns
- Pitfalls: HIGH — drawn from live codebase analysis + PITFALLS.md §Pitfall 7 + v3.0 post-mortems (P19/P20 SERVER_TIMESTAMP incidents)
- Validation Architecture: HIGH — mirrors established test patterns from test_training_log_store.py and test_firestore_db.py

**Research date:** 2026-06-05
**Valid until:** 2026-07-05 (stable architecture, no external API changes — 30-day window is conservative)
