---
phase: 21-living-plan-ingestion
reviewed: 2026-06-04T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - core/main.py
  - core/tools.py
  - memory/firestore_db.py
  - prompts/smart_agent.md
  - scripts/ingest_blueprint.py
  - tests/test_ingest_blueprint.py
  - tests/test_main_render_smart_system.py
  - tests/test_tools.py
  - tests/test_user_profile_store.py
  - tests/test_user_profile_store_v4_scaffold.py
  - tests/test_weekly_training_review.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 21: Code Review Report

**Reviewed:** 2026-06-04
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 21 (Living Plan Ingestion) adds a v4.0 structured profile contract: an
idempotent blueprint seed script (`scripts/ingest_blueprint.py`), an expanded
`UserProfileStore._SCAFFOLD`, an `update_plan` tool alias, a JSON-safe
`get_training_profile` handler, and a coaching-reference renderer in
`render_smart_system`.

The store, tool-alias, and JSON-safety changes are sound and well-tested. The
critical defect is a **data-shape contract mismatch** between the ingest script
and the renderer: `dated_goals[].metrics` is produced as a **dict** by
`build_profile_dict()` (and asserted as a dict by `test_ingest_blueprint.py`),
but `render_smart_system` iterates it as a **list**. The result is that the
real, ingested goal data renders with all target *values* stripped — Klaus
would present Amit's October peak as "bench_press_kg, squat_kg,
half_marathon_time" with no numbers. The render tests pass only because they
feed list-shaped fixtures that never occur in production. This is the kind of
green-tests-hide-a-real-bug failure the renderer's own test suite should have
caught.

## Critical Issues

### CR-01: `dated_goals` metrics render as dict keys, silently dropping all target values

**File:** `core/main.py:308-320` (renderer) vs `scripts/ingest_blueprint.py:62-82` (data producer)

**Issue:**
`build_profile_dict()` produces each goal's `metrics` as a **dict**:

```python
"metrics": {"bench_press_kg": 100, "squat_kg": 120, "half_marathon_time": "1:25:00"}
```

and `tests/test_ingest_blueprint.py:79-110` asserts exactly this shape
(`for k, v in metrics.items()`). But the renderer treats `metrics` as a list:

```python
metrics = g.get("metrics") or []
metric_str = ", ".join(str(m) for m in metrics) if metrics else ""
```

Iterating a dict yields only its **keys**, so the rendered coaching reference
for the real ingested profile becomes:

```
  - October Peak — Absolute Strength + Half Marathon (2026-10-31): bench_press_kg, squat_kg, half_marathon_time
```

Every numeric target (100, 120, "1:25:00", 125, 35, "9:30", "55s") is dropped
from the prompt context. Klaus cannot cite the actual targets — the entire
point of the coaching-reference block. Verified empirically:
`", ".join(str(m) for m in {"bench_press_kg": 100, ...})` →
`"bench_press_kg, squat_kg, half_marathon_time"`.

The render tests (`test_dated_goals_renders_metric_bullets`,
`test_main_render_smart_system.py:321-334`) pass only because they pass
list-shaped fixtures (`"metrics": ["100kg bench", "120kg squat"]`) that
contradict the dict contract the ingest script and its own tests enforce. No
test exercises the renderer with the actual `build_profile_dict()` output.

**Fix:** Render dict-shaped metrics as `key: value` pairs (and keep
list-tolerance for forward-compat):

```python
metrics = g.get("metrics") or {}
if isinstance(metrics, dict):
    metric_str = ", ".join(f"{k}: {v}" for k, v in metrics.items())
elif isinstance(metrics, list):
    metric_str = ", ".join(str(m) for m in metrics)
else:
    metric_str = str(metrics)
```

Then add a renderer test that feeds `build_profile_dict()` output directly so
the data producer and consumer can never drift again.

## Warnings

### WR-01: `nutrition_targets.aerobic_reference_note` is silently dropped by the renderer

**File:** `core/main.py:347-362` vs `scripts/ingest_blueprint.py:254-260`

**Issue:** The ingest script deliberately stores the 16-week aerobic
progression as a single directional note string under
`nutrition_targets["aerobic_reference_note"]` (the locked-narrowing from
21-CONTEXT.md — it is the *only* place that aerobic context survives). The
renderer only emits `protein_g`, `carbs_g`, and `fueling_slots`; it never reads
`aerobic_reference_note`, so the deliberately-preserved aerobic guidance never
reaches the prompt. The information was ingested specifically to be available,
then dropped at render time.

**Fix:** Emit the note when present:

```python
aerobic_note = nutrition_targets.get("aerobic_reference_note")
if aerobic_note:
    lines.append(f"  Aerobic reference: {aerobic_note}")
```

### WR-02: Renderer tests assert a `metrics` shape that contradicts the ingest contract

**File:** `tests/test_main_render_smart_system.py:313-334`

**Issue:** The Phase 21 renderer tests model `dated_goals[].metrics` as a list
of pre-formatted strings, while `tests/test_ingest_blueprint.py` and
`build_profile_dict()` model it as a dict of typed values. The two test suites
encode mutually incompatible contracts for the same field, and the renderer
suite's choice is the one that does not match production. This is what allowed
CR-01 to ship green. Even after CR-01's code fix, this test must be updated to
use the real (dict) shape or it will continue to validate a non-existent data
layout.

**Fix:** Replace the list fixtures with the dict shape that
`build_profile_dict()` emits, e.g.
`"metrics": {"bench_press_kg": 100, "squat_kg": 120}`, and assert that both the
keys and the values (`100`, `120`) appear in the rendered output.

### WR-03: `_jsonsafe_doc` is shallow — nested datetime values in the profile would still break `get_training_profile`

**File:** `core/tools.py:1318-1330`, `memory/firestore_db.py:733-752`

**Issue:** The T-21-04 mitigation wraps `store.load()` in `_jsonsafe_doc`, but
that helper only ISO-converts **top-level** values. The v4.0 profile is deeply
nested (`dated_goals` list of dicts, `weekly_split` dict of dicts). If any
future write places a Firestore timestamp or other non-JSON value *inside* a
nested structure (e.g. a per-goal `updated_at`, or a SERVER_TIMESTAMP leaking
through a partial `update_plan` patch), `json.dumps` in the handler would raise
`TypeError` and the brain-direct tool would fail. Today's data happens to keep
timestamps top-level, so this is latent rather than active, but the mitigation
claims to make the handler "never raise a TypeError on a real Firestore doc,"
which is only true for the current flat-timestamp layout.

**Fix:** Make the serialization recursive, or use a `json.dumps(..., default=str)`
fallback in the handler so any stray non-serializable value degrades to its
string form instead of raising:

```python
return json.dumps(_jsonsafe_doc(store.load()), default=str)
```

## Info

### IN-01: `update_plan` / `update_training_profile` handlers raise `TypeError` on extra arg keys

**File:** `core/tools.py:1492-1494`

**Issue:** Both aliases dispatch via `lambda args: _handle_update_training_profile(**args)`.
If the LLM emits a tool call with any key besides `patch` (e.g.
`{"patch": {...}, "confirm": true}`), `**args` raises `TypeError: unexpected
keyword argument` rather than degrading gracefully. This is pre-existing
behavior (inherited from the Phase 19 `update_training_profile` wiring, not
introduced in Phase 21), so it is informational, but the new `update_plan`
alias doubles the surface area.

**Fix:** Have the handler accept `patch: dict` and ignore extras, or normalize
in the lambda: `lambda args: _handle_update_training_profile(patch=args.get("patch", {}))`.

### IN-02: Idempotency gate keys solely on `plan_start_date` truthiness

**File:** `scripts/ingest_blueprint.py:317-325`

**Issue:** The non-`--force` re-ingest guard skips when
`existing.get("plan_start_date")` is truthy. If a prior partial/aborted write
populated the other five v4.0 fields but `plan_start_date` ended up empty (the
scaffold default is `""`), a re-run without `--force` would re-write all fields
— effectively a silent force. Low impact for a single-operator seed script, but
the guard's chosen sentinel is the one field most likely to be blank-by-default.

**Fix:** Gate on a more robust signal (e.g. presence of `dated_goals` non-empty,
or `schema_version == 2`), or document that `plan_start_date` must be the last
field written so the gate is meaningful.

---

_Reviewed: 2026-06-04_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
