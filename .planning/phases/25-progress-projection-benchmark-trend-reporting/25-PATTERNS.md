# Phase 25: Progress Projection + Benchmark Trend Reporting — Pattern Map

**Mapped:** 2026-06-07
**Files analyzed:** 7 (2 new, 5 modified)
**Analogs found:** 7 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/projection.py` | utility (pure-function helper) | transform | `core/pricing.py` + `mcp_tools/garmin_tool.py::compute_acwr` | role-match (pure-fn, no I/O) |
| `core/tools.py` (add `get_goal_projection`) | tool registry | request-response | `core/tools.py` lines 963–985 (`get_benchmark_history` schema/handler/HANDLERS entry) | exact |
| `core/weekly_training_review.py` (extend `_gather_week_data` + `_derive_structural_topics` + `run_weekly_review`) | service (cron) | batch | `core/weekly_training_review.py` blocks 6–7 (lines 200–250) + post-send dedup write (lines 375–391) | exact |
| `prompts/weekly_training_review.md` (fence lift, lines 37/47/147) | config/prompt | — | `prompts/weekly_training_review.md` lines 37/47/147 (the three fence points) | exact (in-place edit) |
| `prompts/smart_agent.md` (update line 181, add `get_goal_projection` description) | config/prompt | — | `prompts/smart_agent.md` lines 107–134 (Tier A/B contract) + line 181 (directional-only restriction) | exact (in-place edit) |
| `tests/test_projection.py` | test | — | `tests/test_pricing.py` + `tests/test_compute_acwr.py` | role-match (pure-fn unit tests) |
| `tests/test_tool_registration_phase25.py` | test | — | `tests/test_tool_registration_phase23.py` | exact |

---

## Pattern Assignments

### `core/projection.py` (utility, transform — NEW FILE)

**Analog 1:** `core/pricing.py` — pure-function module, no I/O, no class, imports only stdlib, returns a computed value from arguments, never raises.

**Module-level structure pattern** (`core/pricing.py` lines 1–51):
```python
"""LLM cost computation.

MODEL_PRICING maps model ID → {input, output} USD per 1M tokens.
...
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Module-level constant dict (lookup table)
MODEL_PRICING: dict[str, dict[str, float]] = { ... }

# Module-level mutable state for dedup (only for side-effect-free logging guard)
_logged_unknown: set[str] = set()


def compute_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """Return the USD cost for one LLM call.

    Args: ...
    Returns: Computed cost in USD. Returns 0.0 ... — never raises.
    """
    ...
    return cost
```

**Key pattern:** The function signature takes all inputs as parameters (no globals read at call time). Returns a concrete value. Never raises — fails open.

**Analog 2:** `mcp_tools/garmin_tool.py::compute_acwr` — pure-function accepting a pre-fetched data list + a `today` date parameter (not `date.today()` internally). Returns a typed result dict.

The `compute_acwr(activities, today=today)` calling convention is the exact model for `project_goal_progress(facet, history, dated_goals, today_iso)` — caller supplies the date, helper does not call `date.today()`. This is the Phase-24 CR-01 timezone safety lesson applied.

**Imports pattern to copy** (from `core/pricing.py` lines 1–11 and `mcp_tools/garmin_tool.py` date usage):
```python
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)
```

**Module-level lookup tables** (copy shape from `core/pricing.py` MODEL_PRICING + adapt):
```python
# Facet → direction: True = higher-is-better, False = lower-is-better (sec/km lower = faster)
FACET_DIRECTION: dict[str, bool] = {
    "bench_press_1rm": True,
    "squat_1rm":       True,
    "push_ups":        True,
    "pull_ups":        True,
    "threshold_pace":  False,
}

# BenchmarkStore facet names → dated_goals.metrics key + target value extractor
# (half_marathon_time is a string requiring conversion to sec/km)
GOAL_METRIC_TO_FACET: dict[str, str] = {
    "bench_press_kg": "bench_press_1rm",
    "squat_kg":       "squat_1rm",
    "push_ups":       "push_ups",
    "pull_ups":       "pull_ups",
    # half_marathon_time handled separately via _hm_to_sec_per_km()
}
```

**Return shape:** A plain `dict` (use `dataclass` + `asdict()` for construction, return the dict — this keeps it JSON-serializable without extra conversion steps in the handler). Fields: `facet`, `confidence` (`"high"|"medium"|"low"|"baseline_only"|"no_data"`), `data_point_count`, `projected_value` (float or None), `target_value` (float or None), `target_date` (ISO string or None), `gap` (signed float or None), `on_track` (bool or None), `unit` (str), `confidence_label` (human-readable string).

**Error handling pattern** (copy from `compute_acwr` / `compute_cost`): wrap the entire body in try/except and return a safe `no_data` result rather than raising:
```python
def project_goal_progress(facet, history, dated_goals, today_iso):
    try:
        ...
    except Exception:
        logger.warning("projection: unexpected error for facet %s", facet, exc_info=True)
        return {"facet": facet, "confidence": "no_data", "data_point_count": 0,
                "projected_value": None, "target_value": None, "target_date": None,
                "gap": None, "on_track": None, "unit": "", "confidence_label": "projection error"}
```

---

### `core/tools.py` — add `get_goal_projection` (tool registry, request-response — MODIFIED)

**Analog:** The `get_benchmark_history` schema + handler + HANDLERS entry, lines 963–985 / 1790–1793 / 1868.

**Four insertion sites** (mirror `get_benchmark_history` at each):

**Site 1 — `SMART_AGENT_DIRECT_TOOLS` frozenset** (lines 40–69). Insert after `"get_benchmark_history"` (line 66):
```python
    # Phase 25 — progress projection toward dated goals (PROG-02)
    "get_goal_projection",
```

**Site 2 — `TOOL_SCHEMAS` list** (after `get_benchmark_history` schema ending at line 985). Copy schema shape from lines 962–985:
```python
    {
        "name": "get_goal_projection",
        "description": (
            "Compute a deterministic linear-trend projection for one benchmark facet "
            "toward its dated goal. Brain-direct. Call when Sir asks 'am I on track "
            "for my October bench target?' or similar. Returns a ProjectionResult dict "
            "with projected_value, gap, on_track, confidence, and confidence_label."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
            },
            "required": ["facet"],
        },
    },
```

**Site 3 — `WORKER_TOOL_SCHEMAS` exclusion set** (lines 1019–1051). Add inside the `if s["name"] not in {...}` set, after the Phase 23 entries (line 1049):
```python
        # Phase 25 — projection is brain-direct only (PROG-02)
        "get_goal_projection",
```

**Site 4 — `_HANDLERS` dict** (lines 1822–1871). Insert after the `get_benchmark_history` entry (line 1868):
```python
    # Phase 25 — progress projection (PROG-02), brain-direct
    "get_goal_projection":     lambda args: _handle_get_goal_projection(**args),
```

**Handler function pattern** (copy `_handle_get_benchmark_history` at lines 1790–1793 and `_block_stores()` at lines 1708–1717):
```python
def _handle_get_goal_projection(facet: str) -> str:
    """PROG-02 brain-direct: project one facet toward its dated goal.

    Validates facet against _BENCHMARK_FACETS (V5 / T-23-01 pattern).
    Returns a JSON ProjectionResult dict. Never raises — errors surface as
    a no_data confidence result.
    """
    # V5 input validation — mirror BenchmarkStore facet guard (T-23-01)
    from memory.firestore_db import _BENCHMARK_FACETS
    if facet not in _BENCHMARK_FACETS:
        return json.dumps({"error": f"Unknown facet: {facet!r}. Valid: {sorted(_BENCHMARK_FACETS)}"})

    _blocks, benchmarks, profiles = _block_stores()
    from memory.firestore_db import _jsonsafe_doc
    from datetime import date as _date
    from zoneinfo import ZoneInfo
    from core.projection import project_goal_progress

    today_iso = _date.today().isoformat()  # UTC date — fine for date-only arithmetic
    history = benchmarks.get_facet_history(facet, n=10)
    profile = _jsonsafe_doc(profiles.load())
    dated_goals = profile.get("dated_goals") or []
    result = project_goal_progress(facet, history, dated_goals, today_iso)
    return json.dumps(result)
```

Note: `_jsonsafe_doc` strips `DatetimeWithNanoseconds` from Firestore docs — required per the project memory feedback on Firestore SERVER_TIMESTAMP → JSON serialization.

---

### `core/weekly_training_review.py` — three extension points (service/cron, batch — MODIFIED)

**Analog:** The existing blocks 6 and 7 in `_gather_week_data` (lines 200–250) and the post-send dedup write in `run_weekly_review` (lines 375–391). Copy the try/except/logger.warning/fail-open structure verbatim.

**Extension point A — new gather block #8 in `_gather_week_data`** (insert after block 7, after line 250). Copy try/except/fail-open shape from block 6 (lines 200–222):
```python
    # ------------------------------------------------------------------ #
    # 8. Progress projections — PROG-02 (Phase 25)                       #
    #    Computed server-side for each dated-goal facet. Fail-open to    #
    #    {} on any error so the cron always sends.                       #
    # ------------------------------------------------------------------ #
    try:
        from core.projection import project_goal_progress
        from memory.firestore_db import BenchmarkStore as _BS, UserProfileStore as _UPS
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        _benchmarks = _BS(project_id, database)
        _profile = _UPS(project_id, database).load()
        dated_goals = _profile.get("dated_goals") or []
        projections: dict = {}
        for facet in ["bench_press_1rm", "squat_1rm", "threshold_pace", "push_ups", "pull_ups"]:
            history = _benchmarks.get_facet_history(facet, n=10)
            projections[facet] = project_goal_progress(facet, history, dated_goals, today_iso)
        data["projections"] = projections
    except Exception:
        logger.warning("weekly_review: projection gather failed", exc_info=True)
        data["projections"] = {}
```

**Extension point B — `_derive_structural_topics`** (lines 255–272). Extend the function to also derive `structural-critique:projection:<facet>` keys. Copy the existing `topics.append` + dedup-while-preserving-order pattern:
```python
def _derive_structural_topics(week_data: dict) -> list[str]:
    topics: list[str] = []
    # ... existing session-quality derivation (lines 267–269) ...
    training_log = week_data.get("training_log") or []
    if any((entry or {}).get("quality") == "grind" for entry in training_log):
        topics.append("structural-critique:session-quality")
    # Phase 25: projection topics — one per facet with >=1 data point
    projections = week_data.get("projections") or {}
    for facet, result in projections.items():
        if isinstance(result, dict) and result.get("confidence") != "no_data":
            topics.append(f"structural-critique:projection:{facet}")
    # De-duplicate while preserving first-seen order (existing pattern).
    seen: set[str] = set()
    return [t for t in topics if not (t in seen or seen.add(t))]
```

**Extension point C — `run_weekly_review` post-send dedup write** (lines 375–391). The existing loop already iterates `coaching_topics_included` and calls `_cts.add_topic(today_iso, _topic)`. Because the projection topic keys are now emitted by `_derive_structural_topics` and stored in `data["coaching_topics_included"]`, the existing post-send loop at lines 380–389 handles them with **no new code**. No structural change needed here — just verify the keys flow through.

**Existing post-send pattern to preserve exactly** (lines 375–391):
```python
    try:
        _topics_included = week_data.get("coaching_topics_included") or []
        if _topics_included:
            from memory.firestore_db import CoachingTopicStore
            _cts = CoachingTopicStore(
                project_id=os.environ["GCP_PROJECT_ID"],
                database=os.getenv("FIRESTORE_DATABASE", "(default)"),
            )
            for _topic in _topics_included:
                _cts.add_topic(today_iso, _topic)
    except Exception:
        logger.warning("weekly_review: coaching topic record failed", exc_info=True)
```

---

### `prompts/weekly_training_review.md` — fence lift (config/prompt — MODIFIED)

**Three in-place edit points** (verified line numbers from RESEARCH.md):

**Line 37 (full replacement):** Remove the "PHASE 25 FENCE — ABSOLUTELY FORBIDDEN" paragraph. Replace with the projection instruction block. The "Week N of 16" framing at line 35 is a separate sentence — **do not remove it**.

Current line 37:
```
**PHASE 25 FENCE — ABSOLUTELY FORBIDDEN:** Do NOT compute, state, or imply any dated projection, pace-to-deadline, "on track for October", "N weeks behind", or any "at this rate you will achieve X by date Y" framing. That is Phase 25 work (PROG-02) and is NOT in scope here. Phase 24 reports current/within-block movement only. Never write "weeks behind" or "on track for" as a coaching assessment.
```

Replace with (D-01/D-02 framing, mirrors `prompts/proactive_alert.md` lines 103–117 "one ranked rec" pattern):
```
**Pace-to-deadline projection (PROG-02):** When `projections` is present in the data, include one consolidated "progress toward goals" block after the per-facet scorecard. For each facet in `projections`:
- ≥2 data points: state projected value + target date + gap. On-track: "trend → 106kg by Oct 10, ahead of the 105kg target." Behind: "trend → 98kg by Oct 10, ~7kg behind. Closer: [one ranked structural recommendation]. Your call, Sir." Attach the confidence label naming the count (e.g. "from only 2 benchmarks — low confidence").
- 1 data point: "baseline only, no trend yet — need another benchmark to project."
- 0 data points: "no measured data for this facet — log a benchmark."
On-track does not prescribe. Behind triggers exactly ONE ranked recommendation. Tier A target (blueprint) is always distinguished from Tier B measured trend.
```

**Line 47 (clause removal):** Change `— never a dated projection:` to `(within-block) and pace-to-deadline projection (dated goals):`. Full heading becomes: `When \`current_block\` is present, report the following per-facet status for this block week using data from \`training_log\`, \`activities\`, and \`block_benchmarks\`. Use block-relative language throughout ("Week {N} of 16", "this block", "last block") for within-block status; the dated projection block follows separately:`

**Line 147 (full replacement):**
Current: `- Never project to a deadline — report current/within-block movement only (Phase 25 fence)`
Replace with: `- Project to deadline per D-01 confidence tiers when \`projections\` data is present; on-track does not prescribe; behind = one ranked recommendation + "your call, Sir"`

---

### `prompts/smart_agent.md` — reactive path update (config/prompt — MODIFIED)

**Analog:** Lines 107–134 (Tier A/B contract — preserve entirely) and line 181 (directional-only restriction — update).

**Line 181 (partial update):**
Current: `projection — directional only ("Oct pace slips", "bench target gap widens").`
Replace the clause with: `projection — when \`get_goal_projection\` data is available, cite the computed number and gap (e.g. "trend → 98kg by Oct 10, ~7kg behind"). When no projection data is available, directional language only ("Oct pace slips", "bench target gap widens").`

**Tool description to add** (in the TRAINING & ATHLETIC COACHING section, near the existing `get_benchmark_history` usage description). Add one bullet:
```
- `get_goal_projection(facet)` — call to project one facet toward its dated goal.
  Returns projected_value, gap, on_track, confidence, and confidence_label computed
  server-side (numbers are never LLM-invented). Use when Sir asks "am I on track for
  my [goal]?" for any of: bench_press_1rm, squat_1rm, push_ups, pull_ups, threshold_pace.
```

---

### `tests/test_projection.py` (test — NEW FILE)

**Analog 1:** `tests/test_pricing.py` — pure-function unit tests, direct import, no mocks, parametric coverage of edge cases, no pytest fixtures needed.

**Import and structure pattern** (`tests/test_pricing.py` lines 1–3):
```python
"""Tests for core/projection.py — project_goal_progress() pure-function helper."""
from core.projection import project_goal_progress, FACET_DIRECTION, GOAL_METRIC_TO_FACET
```

**Analog 2:** `tests/test_compute_acwr.py` — pure-function tests with a shared helper that builds synthetic data lists, parametric assertions on edge cases, `today` date passed as parameter:
```python
def _build_history(n: int, values: list[float], start_date: str = "2026-06-21") -> list[dict]:
    """Build synthetic benchmark history entries from oldest to newest."""
    ...
```

**Test names to implement** (from RESEARCH.md validation table PROG-02-A through PROG-02-N):
```python
def test_project_0_points():     # confidence="no_data", projected_value=None
def test_project_1_point():      # confidence="baseline_only", projected_value=None
def test_project_2_points():     # confidence="low", projected_value=float, on_track present
def test_project_3_points():     # confidence reflects 3 points, LSQ fit
def test_lower_is_better():      # threshold_pace: on_track when projected <= target
def test_higher_is_better():     # bench: on_track when projected >= target
def test_hm_time_conversion():   # "1:25:00" → ~241.7 sec/km target
def test_dedup_same_date():      # two entries same date are collapsed before LSQ fit
```

**No Firestore mock needed** — `project_goal_progress` is pure-function, receives pre-built dicts as arguments.

---

### `tests/test_tool_registration_phase25.py` (test — NEW FILE)

**Analog:** `tests/test_tool_registration_phase23.py` — full file is the exact template. Copy structure verbatim, change `NEW_TOOLS`, test class name, and docstring.

**Imports and mock installation pattern** (lines 1–120 of `tests/test_tool_registration_phase23.py`):
```python
"""Tests for Phase 25 tool registration in core/tools.py — PROG-02.

RED tests — written before implementation. ...
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

NEW_TOOLS = ["get_goal_projection"]
```

**Mock installation function:** Copy `_install_tools_mocks()` from `tests/test_tool_registration_phase23.py` lines 35–117 verbatim. The stub list must include `"core.projection"` (the new module) in the `sys.modules.setdefault(m, MagicMock())` block so the import inside `_handle_get_goal_projection` doesn't fail.

**autouse fixture pattern** (lines 127–132) — copy exactly:
```python
@pytest.fixture(autouse=True)
def _tools(isolated_modules):
    global tools
    import importlib
    _install_tools_mocks()
    tools = importlib.import_module("core.tools")
```

**Test class** (mirror `TestPhase23ToolRegistration` from lines 135–202):
```python
class TestPhase25ToolRegistration:
    def test_tool_in_direct(self):
        assert "get_goal_projection" in tools.SMART_AGENT_DIRECT_TOOLS

    def test_tool_excluded_from_worker(self):
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "get_goal_projection" not in worker_names

    def test_tool_in_handlers(self):
        assert "get_goal_projection" in tools._HANDLERS

    def test_tool_has_schema(self):
        schemas = {s["name"]: s for s in tools.TOOL_SCHEMAS}
        assert "get_goal_projection" in schemas
        schema = schemas["get_goal_projection"]
        assert set(schema.keys()) >= {"name", "description", "input_schema"}
        assert "facet" in schema["input_schema"]["properties"]
        assert schema["input_schema"].get("required") == ["facet"]

    def test_handler_callable(self):
        assert callable(getattr(tools, "_handle_get_goal_projection", None))
```

---

## Shared Patterns

### Try/Except/Fail-Open (gather blocks)
**Source:** `core/weekly_training_review.py` lines 75–86, 115–150, 200–222, 224–240
**Apply to:** All `_gather_week_data` gather blocks, including the new projection block #8
```python
    try:
        ...gather and set data[key]...
    except Exception:
        logger.warning("weekly_review: <source> fetch failed", exc_info=True)
        data["<key>"] = <fail_open_default>  # {} or [] or None depending on consumer expectation
```
Projection block should fail open to `{}` (empty dict), not `None`, so the prompt can check `if projections`.

### Write-After-Send Dedup (CoachingTopicStore)
**Source:** `core/weekly_training_review.py` lines 375–391
**Apply to:** Projection topic keys (`structural-critique:projection:<facet>`). These flow through the existing loop — no new write path needed. Just ensure `_derive_structural_topics` emits them into `coaching_topics_included`.

Key invariant: `CoachingTopicStore.add_topic` is called **only inside `run_weekly_review` after `await send_and_inject()`** — never in `_gather_week_data` or `_derive_structural_topics`.

### Pure-Function Signature + today_iso Parameter
**Source:** `mcp_tools/garmin_tool.py::compute_acwr(activities, today=today)` (CR-01 lesson)
**Apply to:** `core/projection.py::project_goal_progress(facet, history, dated_goals, today_iso)`
The helper must NEVER call `date.today()` or `datetime.now()` internally. The caller provides `today_iso` as an Asia/Jerusalem date string.

### Facet Validation (V5 / T-23-01)
**Source:** `core/tools.py::_handle_log_benchmark` + `memory/firestore_db.py::BenchmarkStore.log_benchmark` (validates against `_BENCHMARK_FACETS` frozenset)
**Apply to:** `_handle_get_goal_projection(facet)` — validate `facet` against `_BENCHMARK_FACETS` before calling `get_facet_history` or `project_goal_progress`. Return `{"error": "..."}` JSON for unknown facets (same as `_handle_log_benchmark` lines 1781–1787).

### JSON-Safe Firestore Doc Reads
**Source:** `core/tools.py::_handle_get_plan` line 1730: `profile = _jsonsafe_doc(profiles.load())`
**Apply to:** `_handle_get_goal_projection` — wrap `profiles.load()` with `_jsonsafe_doc` before passing to `project_goal_progress`. Without this, `dated_goals` entries may contain `DatetimeWithNanoseconds` that fail `json.dumps`.

### `_block_stores()` Singleton Constructor
**Source:** `core/tools.py` lines 1708–1717
**Apply to:** `_handle_get_goal_projection` — call `_block_stores()` to get `(blocks, benchmarks, profiles)`. Do not construct `BenchmarkStore` or `UserProfileStore` directly inside the handler.

---

## No Analog Found

All files have close matches in the codebase.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | — |

---

## Metadata

**Analog search scope:** `core/`, `tests/`, `prompts/`, `memory/`, `mcp_tools/`
**Files scanned:** 14 (tools.py, pricing.py, weekly_training_review.py, garmin_tool.py, test_pricing.py, test_compute_acwr.py, test_benchmark_store.py, test_tool_registration_phase23.py, test_weekly_training_review.py, test_prompts.py, smart_agent.md, weekly_training_review.md, proactive_alert.md, firestore_db.py selected lines)
**Pattern extraction date:** 2026-06-07
