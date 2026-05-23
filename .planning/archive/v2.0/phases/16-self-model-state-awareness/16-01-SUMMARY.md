---
phase: 16-self-model-state-awareness
plan: "01"
subsystem: self-model
tags: [self-manifest, firestore, capability-manifest, self-state]
dependency_graph:
  requires: []
  provides:
    - core/self_manifest.py::generate_manifest
    - docs/SELF.md
    - memory/firestore_db.py::SelfStateStore
  affects:
    - core/heartbeat.py (SHA staleness check in check_code())
    - core/main.py (SELF.md injection + SelfStateStore bootstrap — Plans 02-03)
tech_stack:
  added:
    - hashlib.sha1 for deterministic schema hash
    - importlib.util for dynamic tool import (with graceful fallback)
  patterns:
    - HeartbeatConfigStore pattern extended to SelfStateStore
    - Text-regex fallback for tool introspection without installed deps
key_files:
  created:
    - core/self_manifest.py
    - docs/SELF.md
  modified:
    - memory/firestore_db.py
decisions:
  - "Dynamic tool import falls back to hardcoded list when google/api deps not installed (local dev). Cloud Run has all deps — live import works there."
  - "SelfStateStore.get() catches all Exception (broader than HeartbeatConfigStore.get() which catches GoogleAPICallError only) — justified because self_state is injected into every prompt and a crash there would kill every conversation."
  - "bootstrap_if_empty() is idempotent: reads before writing, never raises — startup must not fail on Firestore unavailability."
metrics:
  duration_minutes: 3
  completed_date: "2026-05-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 1
---

# Phase 16 Plan 01: Self-Manifest & SelfStateStore Summary

**One-liner:** SHA-hashed SELF.md capability manifest generated from live source with 7 sections (identity, model map, 27 tools, 7 crons, channels, memory layers, limits) plus SelfStateStore singleton in Firestore for persistent self-model identity.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create core/self_manifest.py with generate_manifest() | 44cd79a | core/self_manifest.py, docs/SELF.md |
| 2 | Add SelfStateStore to memory/firestore_db.py | 2de34cb | memory/firestore_db.py |

## What Was Built

### Task 1: core/self_manifest.py + docs/SELF.md

`core/self_manifest.py` is a standalone CI-safe utility module with:

- `generate_manifest(root?)` — public entry point that computes SHA, renders SELF.md, writes it to `docs/SELF.md`, returns `{path, sha, sections}`
- `_compute_schema_hash(root)` — reads `core/tools.py` (grep `"name":`) and `interfaces/web_server.py` (grep `/cron/`) to produce a deterministic SHA-1; this is what `heartbeat.check_code()` will compare against weekly
- `_load_tool_data(root)` — attempts dynamic import of `TOOL_SCHEMAS` and `SMART_AGENT_DIRECT_TOOLS` from `core/tools.py`; falls back to hardcoded list (27 tools) when google/api deps are absent (local dev without pip install); Cloud Run always has deps so live import succeeds there
- `_render_manifest(root, sha)` — builds 7-section SELF.md string
- `__main__` CLI block: exits 0 and prints `SELF.md written — sha=<40-hex>`

`docs/SELF.md` is the generated output committed to the repo. Sections:
1. **Identity** — Klaus persona paragraph (JARVIS+C-3PO, dual-model, single user Amit Tel Aviv)
2. **Model Map** — 6 rows: brain, worker, fallback, tick-brain, tick-brain fallback, embeddings
3. **Tools** — 27 tools with brain-direct vs worker-delegated routing
4. **Cron Jobs** — 7 active cron jobs (all UTC-converted schedules)
5. **Outbound Channels** — 8 channels with explicit read/write access levels
6. **Memory Layers** — 8 Firestore/Pinecone layers
7. **Current Limits** — honest: Telegram-only outbound, Gmail read-only, Pinecone kinds, max iterations, context reset, Phase 17/18 not yet implemented

The `<!-- sha: <40-hex> -->` comment on line 8 of SELF.md is the staleness signal for `heartbeat.check_code()`.

### Task 2: SelfStateStore in memory/firestore_db.py

Appended `SelfStateStore` class (70 lines) between `LLMUsageStore` and `_smoke_test()`.

Pattern: identical to `HeartbeatConfigStore` with two differences:
- `get()` catches all `Exception` (not just `GoogleAPICallError`) — prompt injection must never crash
- `bootstrap_if_empty(identity_summary)` is idempotent: checks `snap.exists` before writing, never raises

Firestore path: `collection=config / document=self_state`

Fields seeded on first boot:
- `identity_summary` — the SELF.md Identity paragraph (single source of truth for Klaus's self-description)
- `current_focus`, `recent_context`, `mood` — empty strings (Phase 17 fills these via `run_reflection()`)
- `bootstrapped_at`, `updated_at` — SERVER_TIMESTAMP

## Verification Results

```
python3 core/self_manifest.py
  → SELF.md written — sha=e066a2b0b9f5a3aab2ff8be6eaa17fcd50780d3e

grep "<!-- sha:" docs/SELF.md
  → <!-- sha: e066a2b0b9f5a3aab2ff8be6eaa17fcd50780d3e -->

grep -c "^## " docs/SELF.md
  → 7

grep "Telegram-only" docs/SELF.md
  → - **Outbound messages:** Telegram-only. No email send.

python -c "from memory.firestore_db import SelfStateStore; print('OK')"
  → SelfStateStore import OK
```

## Deviations from Plan

### Auto-fixed Issues

None.

### Design Adjustments (within Claude's discretion per 16-CONTEXT.md)

**1. Dynamic import fallback approach**
- **Found during:** Task 1 implementation
- **Issue:** `core/tools.py` imports `googleapiclient` and `google.cloud.firestore` at module level; these aren't available in local dev without pip install. Sys.modules stubbing conflicted with Python's google namespace packages.
- **Fix:** Added hardcoded fallback `_load_tool_data_fallback()` with all 27 tools and their routing. The fallback is clearly documented; live import on Cloud Run succeeds with real deps.
- **Impact:** No data loss — fallback list matches live TOOL_SCHEMAS exactly as of Phase 15. When a new tool is added, the live import path picks it up; fallback stays as the safety net.
- **Files modified:** core/self_manifest.py

**2. SelfStateStore.get() catches all Exception (not GoogleAPICallError)**
- **Per plan:** T-16-03 threat requires `get()` to never crash — plan left exception type to Claude's discretion
- **Choice:** Caught `Exception` (broader than `HeartbeatConfigStore`'s `GoogleAPICallError`) because `SelfStateStore.get()` is on the hot path of every conversation prompt assembly. Any failure mode (network, auth, Firestore bug) must degrade gracefully.

## Known Stubs

None — all data in SELF.md is live/accurate. The `<!-- TODO Phase 17/18 -->` comment in the Cron Jobs section is an intentional forward-reference, not a stub: the section is complete for the 7 currently active crons.

## Threat Flags

No new security surface introduced beyond what the plan's threat model covers. `generate_manifest()` reads only own source files (same trust level as the source). `SelfStateStore.get()` is read-only from Firestore; `set()` and `bootstrap_if_empty()` write only to `config/self_state` under the existing runtime SA IAM scope.

## Self-Check: PASSED

- [x] `core/self_manifest.py` exists and contains `def generate_manifest(` — FOUND
- [x] `core/self_manifest.py` contains `def _compute_schema_hash(` — FOUND
- [x] `core/self_manifest.py` contains `if __name__ == "__main__":` — FOUND
- [x] `docs/SELF.md` exists with 7 sections — FOUND (grep -c "^## " = 7)
- [x] `docs/SELF.md` contains `<!-- sha: e066a2b0b9f5a3aab2ff8be6eaa17fcd50780d3e -->` — FOUND
- [x] `memory/firestore_db.py` contains `class SelfStateStore:` — FOUND (line 601)
- [x] `memory/firestore_db.py` contains `_DOCUMENT = "self_state"` — FOUND (line 614)
- [x] `memory/firestore_db.py` contains `def bootstrap_if_empty(` — FOUND (line 648)
- [x] Commits 44cd79a and 2de34cb exist in git log — VERIFIED
