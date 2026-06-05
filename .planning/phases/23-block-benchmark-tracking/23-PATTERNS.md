# Phase 23: Block + Benchmark Tracking - Pattern Map

**Mapped:** 2026-06-05
**Files analyzed:** 12 (2 new store classes, 1 modified store class, 6 new tool handlers, 3 modified cron gather steps, 3 modified prompt files, 1 new seed script, 2 new test files)
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `memory/firestore_db.py` — `BlockStore` (new class) | store | CRUD | `memory/firestore_db.py` `TrainingLogStore` (line 764) | exact |
| `memory/firestore_db.py` — `BenchmarkStore` (new class) | store | CRUD | `memory/firestore_db.py` `TrainingLogStore` (line 764) | exact |
| `memory/firestore_db.py` — `UserProfileStore._SCAFFOLD` (modify) | store | CRUD | `memory/firestore_db.py` `UserProfileStore` (line 138) | exact |
| `core/tools.py` — 6 new brain-direct tool schemas + handlers (modify) | tool-handler | request-response | `core/tools.py` `_handle_get_training_profile` / `_handle_read_coaching_guide` (lines 1353, 1368) | exact |
| `core/proactive_alerts.py` — `run_proactive_alerts()` block check (modify) | cron | event-driven | `core/proactive_alerts.py` training check-in + recovery_concern pattern (lines 99–168) | exact |
| `core/morning_briefing.py` — `_gather_data()` block state (modify) | cron | request-response | `core/morning_briefing.py` MealStore gather step (lines 256–272) | exact |
| `core/weekly_training_review.py` — `_gather_week_data()` block+benchmarks (modify) | cron | request-response | `core/weekly_training_review.py` TrainingLogStore + UserProfileStore gather steps (lines 75–191) | exact |
| `prompts/proactive_alert.md` (modify) | prompt | — | `prompts/proactive_alert.md` `recovery_concern` conditional section (line 20) | exact |
| `prompts/morning_briefing.md` (modify) | prompt | — | `prompts/morning_briefing.md` `nutrition` conditional section (line 68) | exact |
| `prompts/weekly_training_review.md` (modify) | prompt | — | `prompts/weekly_training_review.md` data-key rendering convention (lines 12–53) | exact |
| `scripts/seed_training_blocks.py` (new) | script | batch | `scripts/ingest_blueprint.py` (lines 1–343) | exact |
| `tests/test_block_benchmark_store.py` (new) | test | — | `tests/test_training_log_store.py` (lines 1–299) | exact |

---

## Pattern Assignments

### `memory/firestore_db.py` — `BlockStore` (new class)

**Analog:** `memory/firestore_db.py` `TrainingLogStore` (lines 764–919)

**Class declaration + constructor pattern** (lines 789–793):
```python
class TrainingLogStore:
    _COLLECTION = "training_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```
For `BlockStore`: use `_COLLECTION = "training_blocks"`.

**Write method — idempotent merge=True + SERVER_TIMESTAMP** (lines 838–842):
```python
        try:
            self._col.document(doc_id).set(payload, merge=True)   # merge=True — idempotent
        except Exception:
            logger.error("TrainingLogStore.log_session(%r) failed", doc_id, exc_info=True)
            raise
```
Writes re-raise. `doc_id` for blocks is `{YYYY-MM-DD}_{label_slug}` e.g. `"2026-06-21_aerobic_base"`.

**Read method — never raises, _jsonsafe_doc on every snap** (lines 856–870):
```python
    def get_recent(self, days: int) -> list[dict]:
        try:
            snaps = list(self._col.stream())
            results = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})  # MANDATORY — DatetimeWithNanoseconds
                d["doc_id"] = snap.id
                if d.get("date", "") >= cutoff:
                    results.append(d)
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results
        except Exception:
            logger.warning("TrainingLogStore.get_recent failed", exc_info=True)
            return []  # NEVER raises
```
`BlockStore.get_current()` uses a Firestore server-side filter instead of streaming all and filtering in Python:
```python
    def get_current(self) -> dict | None:
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
            return None  # NEVER raises
```

**`updated_at` payload stamp** (line 836):
```python
        payload = {
            ...
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
```

**BlockStore schema fields** (from ARCHITECTURE.md §IP4, verified against CONTEXT.md D-03):
```python
BLOCK_FIELDS = {
    "block_id":               str,    # same as doc id: "{YYYY-MM-DD}_{label_slug}"
    "label":                  str,    # "Aerobic Base"
    "start_date":             str,    # YYYY-MM-DD — stored as string (not timestamp)
    "end_date":               str,    # YYYY-MM-DD — stored as string (not timestamp)
    "focus_facets":           list,   # ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"]
    "weekly_split_override":  dict,   # None for auto-seeded blocks
    "status":                 str,    # "active" | "complete" | "abandoned"
    "notes":                  str,    # ""
    "benchmark_due":          bool,   # False until deload week triggers it
    "created_at":             ...,    # firestore.SERVER_TIMESTAMP on creation
    "updated_at":             ...,    # firestore.SERVER_TIMESTAMP on every write
}
```

---

### `memory/firestore_db.py` — `BenchmarkStore` (new class)

**Analog:** `memory/firestore_db.py` `TrainingLogStore` (lines 764–919) — same discipline

**Class + constructor:** Mirror exactly; use `_COLLECTION = "benchmarks"`. `doc_id` = `{YYYY-MM-DD}_{facet}` e.g. `"2026-07-18_bench_press_1rm"`.

**Write method (idempotent by date+facet)** — copy `log_session` pattern:
```python
    def log_benchmark(self, date: str, facet: str, value: float,
                      unit: str, block_id: str, notes: str = "") -> None:
        doc_id = f"{date}_{facet}"
        payload = {
            "date": date, "facet": facet, "value": value,
            "unit": unit, "block_id": block_id, "notes": notes,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(doc_id).set(payload, merge=True)
        except Exception:
            logger.error("BenchmarkStore.log_benchmark(%r) failed", doc_id, exc_info=True)
            raise
```

**Read method for facet history** — mirror `get_range` pattern (lines 894–919):
```python
    def get_facet_history(self, facet: str, n: int = 10) -> list[dict]:
        try:
            snaps = list(self._col.stream())
            results = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})   # MANDATORY
                d["doc_id"] = snap.id
                if d.get("facet") == facet:
                    results.append(d)
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results[:n]
        except Exception:
            logger.warning("BenchmarkStore.get_facet_history(%r) failed", facet, exc_info=True)
            return []
```

**Read method for block benchmarks** (same pattern, filter by block_id):
```python
    def get_block_benchmarks(self, block_id: str) -> list[dict]:
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            snaps = list(
                self._col.where(filter=FieldFilter("block_id", "==", block_id)).stream()
            )
            results = [
                {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
                for snap in snaps
            ]
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results
        except Exception:
            logger.warning("BenchmarkStore.get_block_benchmarks(%r) failed", block_id, exc_info=True)
            return []
```

**BenchmarkStore schema fields:**
```python
BENCHMARK_FIELDS = {
    "date":       str,    # YYYY-MM-DD
    "facet":      str,    # "bench_press_1rm" | "squat_1rm" | "push_ups" | "pull_ups" | "threshold_pace"
    "value":      float,
    "unit":       str,    # "kg" | "reps" | "sec_per_km"
    "block_id":   str,    # FK → training_blocks doc id
    "notes":      str,    # e.g. "Epley estimate from 85kg×5" or "tested-under-fatigue"
    "updated_at": ...,    # SERVER_TIMESTAMP
}
```

---

### `memory/firestore_db.py` — `UserProfileStore._SCAFFOLD` (modify)

**Analog:** `memory/firestore_db.py` `UserProfileStore._SCAFFOLD` (lines 138–152)

**Existing scaffold** (lines 138–152):
```python
    _SCAFFOLD = {
        "dated_goals": [],
        "weekly_split": {},
        "nutrition_targets": {},
        "supplement_schedule": [],
        "fueling_timeline": [],
        "plan_start_date": "",
        "schema_version": 2,
        # Legacy fields
        "athletic_goals": [],
        "training_constraints": [],
        "recovery_preferences": {},
    }
```
Add `"current_block_id": None` to `_SCAFFOLD`. The `start_block` and `end_block` tool handlers write/clear this via `UserProfileStore.update({"current_block_id": block_id})` — reusing the existing `update()` method (line 171–180). No other changes to the store class.

---

### `core/tools.py` — 6 new brain-direct tool schemas + handlers (modify)

**Analog:** `core/tools.py` `get_training_profile` schema (lines 657–669) + `_handle_get_training_profile` handler (lines 1353–1365)

**SMART_AGENT_DIRECT_TOOLS — add 6 names** (after line 61):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    ...existing names...
    # Phase 23 — block + benchmark tracking (BLOCK-01/02/03)
    "get_plan",
    "get_block_status",
    "log_benchmark",
    "get_benchmark_history",
    "start_block",
    "end_block",
    # NOTE: "update_plan" already at line 57 — DO NOT re-add
})
```

**WORKER_TOOL_SCHEMAS exclusion set — add 6 names** (after line 917):
```python
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        ...existing exclusions...
        # Phase 23 — block/benchmark tools are brain-direct only
        "get_plan",
        "get_block_status",
        "log_benchmark",
        "get_benchmark_history",
        "start_block",
        "end_block",
    }
]
```

**Tool schema pattern** — copy `get_training_profile` (lines 657–669):
```python
{
    "name": "get_training_profile",
    "description": (
        "Read Sir's stored training profile (...). Brain-direct — call this when "
        "you need to know Sir's coaching context before answering or planning."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
},
```
`get_plan` and `get_block_status` follow the zero-argument schema above. `log_benchmark` and `get_benchmark_history` take arguments — follow `read_coaching_guide` schema (lines 672–696) with `"required": ["facet"]` / `"required": ["date", "facet", "value", "unit", "block_id"]`.

**Handler pattern** — copy `_handle_get_training_profile` (lines 1353–1365):
```python
def _handle_get_training_profile() -> str:
    from memory.firestore_db import UserProfileStore, _jsonsafe_doc
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(_jsonsafe_doc(store.load()))
```
All 6 new handlers follow this exact shape: import store inside function, construct with env vars, call store method, return `json.dumps(...)`. For write tools (`log_benchmark`, `start_block`, `end_block`) mirror `_handle_update_training_profile` (lines 1414–1425) — catch exceptions and return `{"error": str(exc)}` instead of raising.

**_HANDLERS dispatch entries** (add after line 1578, mirroring existing lines 1573–1578):
```python
    # Phase 23 — block + benchmark tracking (BLOCK-01/02/03)
    "get_plan":              lambda args: _handle_get_plan(),
    "get_block_status":      lambda args: _handle_get_block_status(),
    "log_benchmark":         lambda args: _handle_log_benchmark(**args),
    "get_benchmark_history": lambda args: _handle_get_benchmark_history(**args),
    "start_block":           lambda args: _handle_start_block(**args),
    "end_block":             lambda args: _handle_end_block(**args),
```

---

### `core/proactive_alerts.py` — benchmark_due block check (modify)

**Analog:** `core/proactive_alerts.py` training check-in before dedup gate (lines 98–112) + recovery_concern gather (lines 154–168)

**Pre-dedup-gate slot** — the block-end check must go here (lines 98–112 structure):
```python
async def run_proactive_alerts(bot: Bot, target_date: str) -> None:
    # Phase 20 — training check-in BEFORE dedup gate (idempotent)
    try:
        from core.training_checkin import run_training_checkin
        today = datetime.now(_TZ).date().isoformat()
        await run_training_checkin(bot, today)
    except Exception:
        logger.warning("proactive_alerts: training check-in failed", exc_info=True)

    # Phase 23 — block-end check + benchmark_due setter BEFORE dedup gate
    # (Pitfall 3: must run before _already_sent() or it never fires on first check)
    benchmark_context: dict | None = None
    try:
        from memory.firestore_db import BlockStore
        ...
        block = block_store.get_current()
        if block:
            # set benchmark_due flag if within 3 days of block.end_date
            ...
            # result fed into alerts_context below (inside dedup gate)
    except Exception:
        logger.warning("proactive_alerts: block-end check failed", exc_info=True)

    if _already_sent(target_date):
        logger.info("Proactive alerts: already processed for %s — skipping", target_date)
        return
    ...
```

**Recovery concern reuse pattern** (lines 154–168) — the `garmin_data` and `rc` dict already fetched for recovery concern carry the HRV/ACWR values the benchmark validity gate needs. Do NOT fetch Garmin a second time:
```python
    try:
        from core.training_checkin import compute_recovery_concern
        garmin_data = None
        try:
            from mcp_tools.garmin_tool import fetch_garmin_today
            garmin_data = fetch_garmin_today()
        except Exception:
            logger.warning("proactive_alerts: Garmin fetch for recovery_concern failed", exc_info=True)
        today_iso = datetime.now(_TZ).date().isoformat()
        rc = compute_recovery_concern(garmin_data=garmin_data, today_iso=today_iso)
        if rc:
            alerts_context["recovery_concern"] = rc
    except Exception:
        logger.warning("proactive_alerts: recovery_concern computation failed", exc_info=True)
```
The benchmark validity gate reads `rc["acwr"]` and `rc["hrv_status"]` (or computes HRV baseline separately if `rc` does not expose raw baseline) from the same `rc` dict. Pass `rc` and `garmin_data` into the benchmark check rather than re-fetching.

**alerts_context injection** — add benchmark result key after weather/overload/travel (line 141–146 pattern):
```python
    alerts_context = {
        "target_date": target_date,
        "weather_alerts": weather_alerts,
        "overload_alert": overload_alert,
        "travel_alerts": travel_alerts,
        # Phase 23: one of: "benchmark_window_open" | "benchmark_deferred" | "benchmark_stale"
        # Key absent if no benchmark logic fired (pre-cycle, no active block, not near end)
    }
```

---

### `core/morning_briefing.py` — `_gather_data()` block state (modify)

**Analog:** `core/morning_briefing.py` MealStore gather step (lines 256–272)

**Exact pattern to copy and adapt:**
```python
    # PHASE 19 — NUTR-05: yesterday's nutrition recap. NUTR-07 silent-omit
    try:
        from memory.firestore_db import MealStore
        yesterday = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
        ms = MealStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        agg = ms.get_day_aggregate(yesterday)
        if agg:  # NUTR-07: silent omit on empty
            data["nutrition"] = agg
    except Exception:
        logger.warning("morning_briefing: meals aggregate failed", exc_info=True)
```

**Block state gather to insert** (insert after the nutrition block, before `return data`):
```python
    # Phase 23 — BLOCK-01: current block state + pre-cycle countdown
    try:
        from memory.firestore_db import BlockStore
        block_store = BlockStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        block = block_store.get_current()
        if block:
            plan_start = date.fromisoformat("2026-06-21")
            today_dt = date.fromisoformat(today_iso)
            week_num = (today_dt - plan_start).days // 7 + 1
            data["block"] = {
                "label": block.get("label"),
                "week_num": week_num,
                "benchmark_due": block.get("benchmark_due", False),
                "end_date": block.get("end_date"),
                "block_id": block.get("block_id") or block.get("doc_id"),
            }
        else:
            days_until = (date.fromisoformat("2026-06-21") - date.fromisoformat(today_iso)).days
            if days_until > 0:
                data["pre_cycle_countdown"] = days_until
            # if days_until <= 0 and no active block: cycle ended or not yet seeded — silent omit
    except Exception:
        logger.warning("morning_briefing: block state fetch failed", exc_info=True)
        # silent omit — Pitfall 4: never crash the briefing over missing block state
```
Note the `if block:` guard before any field access — Pitfall 4.

---

### `core/weekly_training_review.py` — `_gather_week_data()` (modify)

**Analog:** `core/weekly_training_review.py` `UserProfileStore` gather step (lines 183–191) + `MealStore` gather step (lines 154–178)

**UserProfileStore pattern** (lines 183–191):
```python
    try:
        from memory.firestore_db import UserProfileStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        profile = UserProfileStore(project_id, database).load()
        data["athletic_goals"] = profile.get("athletic_goals") or []
    except Exception:
        logger.warning("weekly_review: UserProfileStore fetch failed", exc_info=True)
        data["athletic_goals"] = []
```

**Block + benchmark gather to insert** (add as a new numbered section after UserProfileStore):
```python
    # ------------------------------------------------------------------ #
    # 6. BlockStore + BenchmarkStore — current block + this-block benchmarks
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import BlockStore, BenchmarkStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        block_store = BlockStore(project_id, database)
        block = block_store.get_current()
        if block:
            plan_start = date.fromisoformat("2026-06-21")
            week_num = (today - plan_start).days // 7 + 1
            data["current_block"] = {**block, "week_num": week_num}
            bench_store = BenchmarkStore(project_id, database)
            block_id = block.get("block_id") or block.get("doc_id")
            data["block_benchmarks"] = bench_store.get_block_benchmarks(block_id) if block_id else []
        else:
            days_until = (date.fromisoformat("2026-06-21") - today).days
            if days_until > 0:
                data["pre_cycle_countdown"] = days_until
    except Exception:
        logger.warning("weekly_review: BlockStore/BenchmarkStore fetch failed", exc_info=True)
        data["current_block"] = None
        data["block_benchmarks"] = []
```

---

### Prompt files (3 modified)

**Analog for all three:** `prompts/morning_briefing.md` `nutrition` conditional section (line 68) + `recovery_concern` conditional section (line 125).

**The conditional-key pattern used in existing prompts:**
```markdown
## Recovery Concern (when `recovery_concern` key is present in data — D-16)

When the alert data contains a `recovery_concern` key, include it with **equal weight**
...
**When `recovery_concern` is absent:** Add **no** recovery framing. No "all clear",
```

**For `prompts/morning_briefing.md`** — add a new section:
```markdown
## Current Training Block (when `block` key is present in data)

When `data["block"]` is present, open the briefing with one line:
*"Week {block.week_num} of 16 — {block.label}, Sir."*
If `benchmark_due` is True, add a brief note that a benchmark is due this week.
If `pre_cycle_countdown` key is present instead (no active block yet):
*"Pre-cycle, Sir — your 16-week build begins in {pre_cycle_countdown} days (Sun 2026-06-21)."*
When both `block` and `pre_cycle_countdown` are absent: omit block framing entirely.
```

**For `prompts/proactive_alert.md`** — add a new conditional section mirroring the `recovery_concern` section:
```markdown
## Benchmark Reminder (when `benchmark_window_open`, `benchmark_deferred`, or `benchmark_stale` key present)

benchmark_window_open: prompt the standardized benchmark session (all 5 facets).
benchmark_deferred: explain the hold with the HRV/ACWR number ("HRV 61 — 78% of baseline, Sir...").
benchmark_stale: one prompt with explicit tested-under-fatigue caveat.
When none of these keys are present: omit benchmark framing entirely.
```

**For `prompts/weekly_training_review.md`** — add a new data key line in the data-key list and a rendering instruction:
```markdown
- `current_block` — active BlockStore doc with `label`, `week_num`, `benchmark_due`, `end_date` (None pre-cycle)
- `block_benchmarks` — list of BenchmarkStore docs for this block (may be empty)
```
And add a rendering rule: if `current_block` is present, include "Week N of 16, {label}" in the review framing. If `block_benchmarks` is non-empty, include a brief per-facet delta vs prior block where available.

---

### `scripts/seed_training_blocks.py` (new)

**Analog:** `scripts/ingest_blueprint.py` (lines 1–343) — exact structural template

**Header + imports pattern** (lines 1–39 of ingest_blueprint.py):
```python
"""Idempotent seed script: create 4 training block docs in Firestore training_blocks/.

Usage:
    python scripts/seed_training_blocks.py [--dry-run] [--force]

Flags:
    --dry-run   Print the JSON payload without writing to Firestore.
    --force     Re-seed over existing blocks (e.g. after date corrections).

Re-running without --force is safe: the script declines to overwrite when blocks
already exist in the collection.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)   # INVARIANT: override=True always
```

**Pure builder function pattern** (lines 46–82 of ingest_blueprint.py):
```python
def build_profile_dict() -> dict:
    """Build and return the v4.0 structured profile dict from the blueprint.
    ...
    Returns a dict with exactly these six keys: ...
    """
```
Mirror as `build_blocks_list() -> list[dict]` — returns the 4 block dicts derived from blueprint §4. No env deps, no Firestore imports.

**Idempotency gate pattern** (lines 317–325 of ingest_blueprint.py):
```python
        if not args.force:
            existing = store.load()
            if existing.get("plan_start_date"):
                logger.warning(
                    "v4.0 fields already present (...). Pass --force to re-ingest.",
                    ...
                )
                return
```
Mirror as: check `BlockStore.get_all()` (or `list(col.stream())`); if collection non-empty and not `--force`, log and return.

**main() CLI pattern** (lines 277–343 of ingest_blueprint.py):
```python
def main() -> None:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--dry-run", action="store_true", ...)
    parser.add_argument("--force", action="store_true", ...)
    args = parser.parse_args()
    payload = build_profile_dict()
    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    try:
        store = UserProfileStore(...)
        if not args.force:
            ...idempotency check...
        store.update({...})
        logger.info("Blueprint ingested successfully...")
    except Exception:
        logger.error("Ingest failed", exc_info=True)
        sys.exit(1)
```

Also set `UserProfileStore.update({"current_block_id": blocks[0]["block_id"]})` at the end to prime the FK for Block 1.

---

### `tests/test_block_benchmark_store.py` (new)

**Analog:** `tests/test_training_log_store.py` (lines 1–299) — exact test structure

**Module-level mock installer** (lines 26–80 of test_training_log_store.py):
```python
def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db."""
    # ... google.cloud.firestore mock setup ...
    firestore_mock.SERVER_TIMESTAMP = object()  # distinguishable sentinel
    sys.modules["google.cloud.firestore"] = firestore_mock
    # Force re-import
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]
    return firestore_mock
```
Copy verbatim — same mock strategy needed for BlockStore and BenchmarkStore.

**autouse fixture pattern** (lines 93–98):
```python
@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global TrainingLogStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    TrainingLogStore = importlib.import_module("memory.firestore_db").TrainingLogStore
```
Adapt to import `BlockStore` and `BenchmarkStore` from the same re-import.

**Store helper pattern** (lines 101–106):
```python
def _store() -> TrainingLogStore:
    """Build a TrainingLogStore with a fully-mocked Firestore client."""
    s = TrainingLogStore.__new__(TrainingLogStore)  # bypass __init__
    s._client = MagicMock()
    s._col = MagicMock()
    return s
```

**Never-raises test pattern** (lines 273–280):
```python
def test_get_recent_returns_empty_on_exception():
    """get_recent returns [] on Firestore exception — never raises."""
    s = _store()
    s._col.stream.side_effect = RuntimeError("firestore down")
    result = s.get_recent(7)
    assert result == []
```
Mirror for `BlockStore.get_current()` → `None`, `BenchmarkStore.get_facet_history()` → `[]`.

**Idempotent write test pattern** (lines 148–157):
```python
def test_log_session_uses_merge_true():
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock
    s.log_session(date="2026-06-01", slot="evt_abc")
    args, kwargs = doc_mock.set.call_args
    assert kwargs.get("merge") is True
```
Mirror for `BenchmarkStore.log_benchmark()`.

---

## Shared Patterns

### Never-raises read discipline
**Source:** `memory/firestore_db.py` `TrainingLogStore.get_recent` (lines 844–870) + `OutreachLogStore.get_today` (lines 1366–1383)
**Apply to:** `BlockStore.get_current()`, `BlockStore.get_all()`, `BenchmarkStore.get_facet_history()`, `BenchmarkStore.get_block_benchmarks()`
```python
        except Exception:
            logger.warning("XxxStore.method_name failed", exc_info=True)
            return []   # or None — never raises to caller
```

### Re-raise on write failure
**Source:** `memory/firestore_db.py` `TrainingLogStore.log_session` (lines 838–842) + `UserProfileStore.update` (lines 171–180)
**Apply to:** `BlockStore.upsert()`, `BenchmarkStore.log_benchmark()`, `BlockStore.set_benchmark_due()`, `UserProfileStore.update({"current_block_id": ...})`
```python
        except Exception:
            logger.error("XxxStore.write_method(%r) failed", doc_id, exc_info=True)
            raise
```

### `_jsonsafe_doc` on every snap.to_dict() call
**Source:** `memory/firestore_db.py` lines 733–761 (definition) + lines 862, 886, 912 (usage in TrainingLogStore)
**Apply to:** Every `snap.to_dict()` result in BlockStore and BenchmarkStore read paths — no exceptions.
```python
            d = _jsonsafe_doc(snap.to_dict() or {})   # MANDATORY — DatetimeWithNanoseconds
```

### `_make_firestore_client` + env var construction
**Source:** `memory/firestore_db.py` lines 22–38 (function) + lines 791–793 (TrainingLogStore constructor)
**Apply to:** `BlockStore.__init__`, `BenchmarkStore.__init__`
```python
    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```

### Best-effort gather with silent omit
**Source:** `core/morning_briefing.py` MealStore gather step (lines 256–272)
**Apply to:** All three cron gather modifications (morning_briefing, proactive_alerts, weekly_training_review)
```python
    try:
        # ... fetch ...
        if result:
            data["key"] = result   # only set when truthy
    except Exception:
        logger.warning("cron_name: description failed", exc_info=True)
        # no data["key"] set → prompt omits silently
```

### Brain-direct tool handler: env-var store construction + json.dumps return
**Source:** `core/tools.py` `_handle_get_training_profile` (lines 1353–1365)
**Apply to:** All 6 new tool handlers
```python
def _handle_xxx() -> str:
    from memory.firestore_db import XxxStore, _jsonsafe_doc
    store = XxxStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = store.method()
    return json.dumps(_jsonsafe_doc(result) if isinstance(result, dict) else result)
```
For write handlers, wrap in try/except and return `{"error": str(exc)}` on failure.

### `load_dotenv(override=True)` in scripts
**Source:** `scripts/ingest_blueprint.py` line 36
**Apply to:** `scripts/seed_training_blocks.py`
```python
from dotenv import load_dotenv
load_dotenv(override=True)   # INVARIANT — override=True always
```

### Isolated Firestore mock in tests
**Source:** `tests/test_training_log_store.py` `_install_firestore_mock()` + `@pytest.fixture(autouse=True) def _firestore_mock(isolated_modules)` (lines 26–98)
**Apply to:** `tests/test_block_benchmark_store.py`
Key points: use `isolated_modules` fixture (from conftest), evict `memory.firestore_db` from sys.modules, bind `_FS.SERVER_TIMESTAMP = object()` as a distinguishable sentinel.

---

## No Analog Found

All files have close analogs in the codebase. No files require falling back to RESEARCH.md patterns as primary reference.

---

## Metadata

**Analog search scope:** `memory/`, `core/`, `scripts/`, `tests/`, `prompts/`
**Files scanned:** 10 source files read directly; line-number references verified against live code
**Pattern extraction date:** 2026-06-05
