---
phase: 16-self-model-state-awareness
plan: "03"
subsystem: self-model
tags: [get_self_status, tools, brain-direct, llm-usage, uptime]
dependency_graph:
  requires:
    - "16-01"  # SelfStateStore + LLMUsageStore in memory/firestore_db.py
  provides:
    - core/tools.py::get_self_status (SMART_AGENT_DIRECT_TOOLS, TOOL_SCHEMAS, _HANDLERS)
    - core/tools.py::_handle_get_self_status
  affects:
    - core/main.py (orchestrator direct-call routing — picks up new frozenset member automatically)
tech_stack:
  added: []
  patterns:
    - brain-direct tool pattern (SMART_AGENT_DIRECT_TOOLS frozenset + WORKER_TOOL_SCHEMAS exclusion)
    - graceful degradation: try/except on both /proc/uptime and LLMUsageStore; returns partial data, never raises
key_files:
  created: []
  modified:
    - core/tools.py
decisions:
  - "smart_calls used as message count proxy: one smart call ≈ one user message turn (matches D-06 in phase context)"
  - "/proc/uptime for container uptime on Cloud Run (Linux); OSError caught gracefully on macOS local dev"
  - "GCP_PROJECT_ID env var gates LLMUsageStore construction — no project_id returns 'unavailable' strings, not an exception"
  - "journal field seeded as None (not omitted) so Phase 17 can detect the field reliably and populate it"
metrics:
  duration_minutes: 5
  completed_date: "2026-05-18"
  tasks_completed: 1
  tasks_total: 1
  files_created: 0
  files_modified: 1
---

# Phase 16 Plan 03: get_self_status Tool Registration Summary

**One-liner:** `get_self_status` brain-direct tool registered at all 5 sites in `core/tools.py` — returns uptime (via `/proc/uptime`), today/month LLM cost, smart_calls-proxied message count, and a null journal stub for Phase 17.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Register get_self_status at all 5 sites in core/tools.py | 3710fea | core/tools.py |

## What Was Built

### Task 1: core/tools.py — get_self_status at all 5 registration sites

**Site 1 — SMART_AGENT_DIRECT_TOOLS frozenset (line 47):**
`"get_self_status"` added to the frozenset. The orchestrator's direct-call routing in `core/main.py` uses frozenset membership to detect brain-direct tools — no changes needed in `main.py`.

**Site 2 — TOOL_SCHEMAS entry (lines 643-657):**
Schema inserted after `search_own_source` and before `delegate_to_worker`. Description explicitly instructs the brain to call directly and not delegate. No input parameters — the tool is zero-argument.

**Site 3 — WORKER_TOOL_SCHEMAS exclusion set (line 702):**
`"get_self_status"` added to the exclusion set. The worker agent (Gemini 2.5 Flash) cannot see or call this tool — mitigates T-16-12 (operational data exposure to worker).

**Site 4 — `_handle_get_self_status()` function (lines 1115-1161):**

Handler logic in three sections:

1. **Uptime** — reads `/proc/uptime` (available on Linux/Cloud Run); catches `OSError`/`ValueError` and returns `"unavailable (local dev or non-Linux)"` on macOS. Computes hours+minutes string and also exposes raw `uptime_seconds` for programmatic use.

2. **LLM usage** — checks `GCP_PROJECT_ID` env var; if set, instantiates `LLMUsageStore` and calls `summary("today")` and `summary("month")`. Extracts:
   - `today_messages`: `smart_calls` count (one smart call ≈ one user message turn)
   - `today_cost_usd`: rounded to 6 decimal places
   - `month_cost_usd`: rounded to 4 decimal places
   - `today_llm_calls`: total `call_count` (includes worker + smart calls)
   
   If `GCP_PROJECT_ID` is absent, fields are set to `"unavailable (GCP_PROJECT_ID not set)"`. Any exception sets `cost_error` key — never raises.

3. **Metadata** — `status_at` UTC ISO timestamp, `journal: null` (Phase 17 placeholder).

Returns `json.dumps(result)` — never a raw dict.

**Site 5 — `_HANDLERS` dict (line 1185):**
`"get_self_status": lambda args: _handle_get_self_status()` — zero-argument dispatch (args dict ignored).

## Verification Results

```
grep -n "get_self_status" core/tools.py
  → line 47:   "get_self_status",                    (SMART_AGENT_DIRECT_TOOLS)
  → line 643:      "name": "get_self_status",         (TOOL_SCHEMAS schema)
  → line 702:      "get_self_status",                 (WORKER_TOOL_SCHEMAS exclusion)
  → line 1115: def _handle_get_self_status() -> str:  (handler function)
  → line 1185:     "get_self_status":  lambda ...     (_HANDLERS dispatch)

grep -n "smart_calls\|/proc/uptime\|journal.*None" core/tools.py
  → line 1124: with open("/proc/uptime", "r") as f:
  → line 1144: result["today_messages"] = today_data.get("smart_calls", 0)
  → line 1159: result["journal"] = None  # Phase 17 will populate
  → line 1161: return json.dumps(result)
```

All 5 sites confirmed. Import blocked by missing `googleapiclient` in local dev (no pip install in worktree) — consistent with behavior documented in 16-01-SUMMARY.md. Cloud Run has all deps; the tool will import cleanly there.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

**`result["journal"] = None`** in `_handle_get_self_status()` (core/tools.py line 1159) — intentional forward-reference. Phase 17 (`run_reflection()`) will populate this field with the latest journal entry from Firestore. The null value is explicit so Phase 17 can detect presence of the key. This does not prevent Plan 03's goal from being achieved — uptime, cost, and message count are all live data.

## Threat Flags

No new security surface beyond the plan's threat model:

- T-16-11 mitigated: `_handle_get_self_status` wraps both the `/proc/uptime` read and the `LLMUsageStore` calls in `try/except` blocks. Handler never raises — returns partial data with error keys on failure.
- T-16-12 mitigated: `"get_self_status"` is in the `WORKER_TOOL_SCHEMAS` exclusion set — worker agent cannot call or see this tool.
- T-16-10 accepted: Cost and uptime exposure to LLM context is intentional (single-user system, data is about Klaus's own operation).

## Self-Check: PASSED

- [x] `core/tools.py` contains `"get_self_status"` in SMART_AGENT_DIRECT_TOOLS — FOUND (line 47)
- [x] `core/tools.py` contains `"name": "get_self_status"` in TOOL_SCHEMAS — FOUND (line 643)
- [x] `core/tools.py` contains `"get_self_status"` in WORKER_TOOL_SCHEMAS exclusion set — FOUND (line 702)
- [x] `core/tools.py` contains `def _handle_get_self_status():` — FOUND (line 1115)
- [x] `core/tools.py` contains `"get_self_status":` in `_HANDLERS` dict — FOUND (line 1185)
- [x] Handler contains `result["journal"] = None` — FOUND (line 1159)
- [x] Handler contains `smart_calls` — FOUND (line 1144)
- [x] Handler contains `/proc/uptime` — FOUND (line 1124)
- [x] Handler returns `json.dumps(result)` — FOUND (line 1161)
- [x] Commit 3710fea exists in git log — VERIFIED
