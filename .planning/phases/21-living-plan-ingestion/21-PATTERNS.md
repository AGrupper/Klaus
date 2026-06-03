# Phase 21: Living Plan Ingestion - Pattern Map

**Mapped:** 2026-06-03
**Files analyzed:** 5 (1 schema expansion, 1 new script, 1 tool extension, 1 prompt reframe, 1 render function)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `memory/firestore_db.py` — `UserProfileStore` schema expansion | store | CRUD | `memory/firestore_db.py` — `SelfStateStore` + `TrainingLogStore` | exact (same file, sibling stores) |
| `scripts/ingest_blueprint.py` (new) | utility/seed script | batch, file-I/O | `scripts/backfill_notion_titles.py` + `scripts/ingest_garmin_zip.py` | role-match |
| `core/tools.py` — `update_training_profile` schema + handler extension | tool-handler | request-response | `core/tools.py` — `_handle_update_training_profile` (lines 1296–1307) | exact |
| `core/main.py` — `render_smart_system` training_profile rendering (lines 287–298) | utility/renderer | transform | `core/main.py` — same function, `self_state` + `journal_digest` rendering (lines 248–282) | exact |
| `prompts/smart_agent.md` — TRAINING & ATHLETIC COACHING section (lines 77–99) | prompt | transform | `prompts/smart_agent.md` — same file, existing TRAINING section (lines 77–99) | exact |

---

## Pattern Assignments

### `memory/firestore_db.py` — `UserProfileStore` schema expansion (lines 93–168)

**Analog:** `memory/firestore_db.py` — `SelfStateStore` (lines 377–444) for the bootstrap/read/write discipline; `TrainingLogStore` (lines 721–878) for structured-field schema shape.

**Class discipline pattern** (lines 93–118 — `UserProfileStore`):
```python
class UserProfileStore:
    """...
    Mirrors SelfStateStore discipline:
      - Reads NEVER raise — return {} on any error.
      - Writes (update) re-raise after logger.error, caller decides.
      - bootstrap_if_empty is a startup safety call — NEVER raises.
      - Every merge write stamps `updated_at: firestore.SERVER_TIMESTAMP`.
    Singleton document at collection='users', document='amit'.
    """
    _COLLECTION = "users"
    _DOCUMENT_ID = "amit"
    _SCAFFOLD = {
        "athletic_goals": [],
        "training_constraints": [],
        "recovery_preferences": {},
        "schema_version": 1,
    }
```

**The `_SCAFFOLD` dict is the exact target of the schema expansion.** Replace/extend the four current keys with the v4.0 structured fields. New `_SCAFFOLD` must include:
- `dated_goals` (list of dicts with target_date, goal_label, metric)
- `weekly_split` (dict keyed by day — AM/PM session objects with label, modality, priority)
- `nutrition_targets` (dict — daily protein_g, carbs_g, and the 6-slot fueling architecture)
- `supplement_schedule` (list of supplement dicts with slot and items)
- `fueling_timeline` (list of 6 slot dicts ordered by timing)
- `plan_start_date` (str — ISO date "2026-06-21")
- `schema_version` (bump from 1 to 2)

**Read pattern — never raises** (lines 126–135):
```python
def load(self) -> dict:
    """PROFILE-01: return the user profile dict. Returns {} on any error — never raises."""
    try:
        snap = self._doc_ref.get()
        if snap.exists:
            return snap.to_dict() or {}
        return {}
    except Exception:
        logger.warning("UserProfileStore.load() failed — returning empty", exc_info=True)
        return {}
```

**Write pattern — re-raises with SERVER_TIMESTAMP** (lines 137–146):
```python
def update(self, patch: dict) -> None:
    """PROFILE-02: merge patch and stamp updated_at SERVER_TIMESTAMP. Re-raises on failure."""
    try:
        self._doc_ref.set(
            {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
    except Exception:
        logger.error("UserProfileStore.update() failed", exc_info=True)
        raise
```

**Bootstrap pattern — idempotent, never raises** (lines 148–168):
```python
def bootstrap_if_empty(self) -> None:
    try:
        snap = self._doc_ref.get()
        if snap.exists:
            return          # already seeded — idempotent gate
        self._doc_ref.set({
            **self._SCAFFOLD,
            "bootstrapped_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        logger.info("UserProfileStore: bootstrapped users/amit")
    except Exception:
        logger.warning(
            "UserProfileStore.bootstrap_if_empty() failed — skipping",
            exc_info=True,
        )
```

**Critical serialization caveat** (from `MealStore.get_day`, lines 622–628):
```python
# Phase 19.3 live-UAT fix: drop the Firestore server-write stamp.
# It round-trips as a DatetimeWithNanoseconds, which is NOT
# json-serializable and breaks downstream json.dumps.
d.pop("updated_at", None)
```
Any new read path in the profile that serializes to JSON (e.g. via `_handle_get_training_profile`) must strip `updated_at` and `bootstrapped_at`. The existing `render_smart_system` already filters them at line 291:
```python
non_empty = {
    k: v for k, v in profile.items()
    if k not in ("updated_at", "bootstrapped_at", "schema_version") and v
}
```
The `_handle_get_training_profile` handler at line 1293 returns `json.dumps(store.load())` raw — it will break if `updated_at` (a `DatetimeWithNanoseconds`) is present. The handler must strip timestamp fields before serializing, matching the `_jsonsafe_doc` helper pattern (lines 699–718) or the `MealStore.get_day` pop approach.

**`_jsonsafe_doc` helper for reference** (lines 699–718):
```python
def _jsonsafe_doc(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        iso = getattr(v, "isoformat", None)
        if callable(iso):
            try:
                out[k] = iso()
            except Exception:
                out[k] = str(v)
        else:
            out[k] = v
    return out
```

---

### `scripts/ingest_blueprint.py` (new seed script)

**Analog:** `scripts/backfill_notion_titles.py` (lines 1–164) for the overall script structure (sys.path bootstrap, `load_dotenv(override=True)`, argparse, `main()` entry point, dry-run flag). Also `scripts/ingest_garmin_zip.py` for the idempotent write pattern (`ON CONFLICT DO UPDATE` / `merge=True`).

**Script boilerplate pattern** (backfill_notion_titles.py lines 17–31):
```python
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)          # INVARIANT: override=True always

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)
```

**Argparse + dry-run pattern** (backfill_notion_titles.py lines 85–91):
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Notion 'Klaus Chat Logs' titles")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N rows")
    args = parser.parse_args()
```

**Idempotent ingest main() pattern** (ingest_garmin_zip.py lines 444–475):
```python
def main():
    try:
        conn = get_db_connection()
        setup_schema(conn)
        parse_and_ingest_wellness(conn, extract_dir)
        conn.close()
        logger.info("Ingestion completed successfully!")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

**For `ingest_blueprint.py`, the analogous shape is:**
1. Parse `docs/hybrid_athlete_blueprint.md` from the repo (source of truth).
2. Build the structured dict matching the new `_SCAFFOLD` fields.
3. Call `UserProfileStore.update(patch)` with `merge=True` (idempotent — re-running is safe).
4. Support `--dry-run` to print the payload without writing.
5. Support `--force` to overwrite even if the document already has v4.0 fields (for re-ingesting after blueprint edits).

**Env setup pattern** (ingest_garmin_zip.py lines 1–16):
```python
import os, sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)
```

---

### `core/tools.py` — tool schema + handler extension

**Analog:** existing `update_training_profile` schema (lines 665–685) and handler (lines 1296–1307). The extension adds new recognized keys to the description and optionally introduces an `update_plan` alias.

**Existing schema to extend** (lines 665–685):
```python
{
    "name": "update_training_profile",
    "description": (
        "Merge new fields into Sir's stored training profile. Brain-direct. "
        "Always confirm with Sir before recording. Recognized top-level keys: "
        "athletic_goals (list), training_constraints (list), recovery_preferences (object)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "patch": {
                "type": "object",
                "description": (
                    "Dict of fields to merge into users/amit. Top-level keys: "
                    "athletic_goals, training_constraints, recovery_preferences."
                ),
            },
        },
        "required": ["patch"],
    },
},
```

Phase 21 must extend the description strings to add: `dated_goals (list), weekly_split (object), nutrition_targets (object), supplement_schedule (list), fueling_timeline (list), plan_start_date (string)`.

**Existing handler to extend** (lines 1296–1307):
```python
def _handle_update_training_profile(patch: dict) -> str:
    """PROFILE-04 brain-direct: merge a patch into users/amit profile."""
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    try:
        store.update(patch)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})
```

The handler body needs no logic change — `UserProfileStore.update` uses `merge=True` so any recognized key in `patch` is accepted. The schema description string is the only change needed for the brain to know the new keys are valid.

**_HANDLERS dispatch pattern** (lines 1455–1456):
```python
"get_training_profile":    lambda args: _handle_get_training_profile(),
"update_training_profile": lambda args: _handle_update_training_profile(**args),
```

If an `update_plan` alias is added, its `_HANDLERS` entry follows the same lambda pattern and calls the same underlying handler, or a thin wrapper that normalizes the alias.

---

### `core/main.py` — `render_smart_system` training profile rendering (lines 287–298)

**Analog:** The same function, rendering `self_state` (lines 248–268) and `journal_digest` (lines 270–282) — both show the same emit-prose-not-raw-dump pattern.

**Current raw-dump pattern to REPLACE** (lines 287–298):
```python
training_profile_snippet = ""
if getattr(self, "_user_profile_store", None) is not None:
    profile = self._user_profile_store.load()
    non_empty = {
        k: v for k, v in profile.items()
        if k not in ("updated_at", "bootstrapped_at", "schema_version") and v
    }
    if non_empty:
        lines = ["**Training profile:**"]
        for k, v in non_empty.items():
            lines.append(f"- {k}: {v}")
        training_profile_snippet = "\n".join(lines)
```

**Target pattern — coaching-reference prose rendering.** The new rendering must:
- Emit a header like `**Coaching reference — Amit's training plan:**`
- Format `dated_goals` as a bulleted list with target date and metric (e.g., "Oct peak: 100kg bench, 120kg squat, 1:25 HM")
- Format `weekly_split` as a day-by-day AM/PM summary (session label + modality + priority, never attendance flags)
- Format `nutrition_targets` as target macros + fueling slot sequence
- Format `supplement_schedule` and `fueling_timeline` as ordered slot lists
- Include `plan_start_date` as "Block anchor: YYYY-MM-DD (Block Week 1)"
- Preserve the existing `non_empty` guard and `if k not in ("updated_at", "bootstrapped_at", "schema_version")` exclusion filter
- Fall back to the existing generic `k: v` dump for any unknown keys (forward-compat)

**Prose rendering pattern to copy from** (`self_state` rendering, lines 248–268):
```python
self_state_snippet = ""
self_state = self._self_state_store.get() if self._self_state_store else {}
if self_state:
    parts = []
    if s := self_state.get("identity_summary"):
        parts.append(s)
    if s := self_state.get("current_focus"):
        parts.append(f"Current focus: {s}")
    if s := self_state.get("mood"):
        parts.append(f"Mood/energy: {s}")
    if s := self_state.get("recent_context"):
        parts.append(f"Recent context: {s}")
    if parts:
        self_state_snippet = "\n".join(parts)
```

The v4.0 training_profile rendering must follow this field-by-field conditional-append pattern — one section per structured key, each section conditionally included only when the key is non-empty.

---

### `prompts/smart_agent.md` — TRAINING & ATHLETIC COACHING section (lines 77–99)

**Analog:** Same file, same section — this is an in-place reframe, not a new section.

**Current section to reframe** (lines 77–99):
```
TRAINING & ATHLETIC COACHING

You read Amit's training data (Garmin training status, recent activities,
ACWR) and nutrition data (Google Fit, Lifesum-sourced) on demand via worker-
delegated tools (`fetch_training_status`, `fetch_recent_activities`,
`fetch_recent_meals`), and read his training profile (goals, constraints,
recovery preferences) via the brain-direct `get_training_profile` tool.

If the training profile is empty (no goals or constraints recorded), do NOT
invent thresholds, targets, or scheduling buffers. Instead:
1. Answer questions using just the metric ...
2. When commentary would benefit from a personalized rule ..., politely ask Sir to state his preference, then call `update_training_profile` to record it.
3. Never make up a personalized rule.

Sharper edge: training and nutrition are areas where Sir asked for direct
coaching. The JARVIS register holds, but pull less of the C-3PO hedging.
```

**What must change for Phase 21:**
- `{training_profile}` placeholder (line 7) already exists — no change needed.
- The section description must reference the new structured keys so the brain knows what each field means when it reads them from the rendered snippet: `dated_goals` = Tier A peak targets; `weekly_split` = flexible template (not attendance contract); `nutrition_targets` = daily macro targets; `plan_start_date` = block anchor.
- Add explicit discipline: "The `weekly_split` is a **template**, not a contract. Never nag about a single missed session. Use it to understand the intended training modality mix."
- Extend the recognized keys listed in the `update_training_profile` / `update_plan` tool reference.
- The "if profile empty" fallback discipline (lines 84–93) must stay intact — extend it to apply to the new structured fields.

**Prompt pattern for Tier A vs Tier B discipline** (from CONTEXT.md specifics):
```
Tier A data (targets — in the profile): dated_goals, weekly_split targets,
nutrition_targets. Use these as coaching anchors.
Tier B data (measured actuals — from Garmin/TrainingLogStore): current pace,
current lifts, recent RPE. Derive at read time — never hand-seed in the profile.
```

---

## Shared Patterns

### Firestore write discipline — SERVER_TIMESTAMP + merge=True
**Source:** `memory/firestore_db.py` lines 137–146 (`UserProfileStore.update`)
**Apply to:** `UserProfileStore.update`, `UserProfileStore.bootstrap_if_empty`, `ingest_blueprint.py` Firestore write call
```python
self._doc_ref.set(
    {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
    merge=True,
)
```

### JSON serialization safety — strip DatetimeWithNanoseconds
**Source:** `memory/firestore_db.py` lines 699–718 (`_jsonsafe_doc`) and lines 622–628 (`MealStore.get_day` pop)
**Apply to:** `_handle_get_training_profile` (tools.py line 1293), any new profile read path that calls `json.dumps`
```python
# Option A: use _jsonsafe_doc (already in firestore_db.py)
from memory.firestore_db import _jsonsafe_doc
return json.dumps(_jsonsafe_doc(store.load()))

# Option B: filter in render_smart_system (already done — lines 291–293)
non_empty = {
    k: v for k, v in profile.items()
    if k not in ("updated_at", "bootstrapped_at", "schema_version") and v
}
```

### load_dotenv invariant
**Source:** `scripts/backfill_notion_titles.py` line 29 / `scripts/ingest_garmin_zip.py` line 16
**Apply to:** `scripts/ingest_blueprint.py`
```python
load_dotenv(override=True)   # INVARIANT: override=True — default silently ignores .env when shell already exported
```

### Bootstrap idempotency gate
**Source:** `memory/firestore_db.py` lines 148–168 (`UserProfileStore.bootstrap_if_empty`)
**Apply to:** `scripts/ingest_blueprint.py` — check `schema_version` before writing to make re-runs safe
```python
snap = self._doc_ref.get()
if snap.exists:
    return   # already seeded — do not overwrite unless --force flag passed
```

### sys.path bootstrap for scripts
**Source:** `scripts/backfill_notion_titles.py` lines 24–26
**Apply to:** `scripts/ingest_blueprint.py`
```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```

---

## No Analog Found

All five target files have close analogs in the codebase. No files lack a match.

| File | Note |
|---|---|
| `scripts/ingest_blueprint.py` | Closest analog is `backfill_notion_titles.py` (script structure) + `ingest_garmin_zip.py` (idempotent parse-and-write). No exact analog exists for "parse markdown → structured Firestore dict" but the boilerplate and write patterns transfer directly. |

---

## Metadata

**Analog search scope:** `memory/`, `core/`, `scripts/`, `prompts/`
**Files read:** `memory/firestore_db.py` (full), `core/tools.py` (lines 640–740, 1280–1471), `core/main.py` (lines 248–307), `prompts/smart_agent.md` (lines 1–110), `scripts/ingest_garmin_zip.py` (lines 1–160, 390–475), `scripts/backfill_notion_titles.py` (full), `docs/hybrid_athlete_blueprint.md` (full)
**Pattern extraction date:** 2026-06-03
