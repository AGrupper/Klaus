---
phase: 16-self-model-state-awareness
plan: "04"
subsystem: self-model
tags: [heartbeat, self-manifest, ci-cd, sha-staleness, deploy]
dependency_graph:
  requires:
    - core/self_manifest.py::_compute_schema_hash (Plan 01 — SHA algorithm)
    - docs/SELF.md (Plan 01 — generated manifest with <!-- sha: --> comment)
  provides:
    - core/heartbeat.py::check_code() extended with SELF.md SHA staleness signal
    - .github/workflows/deploy.yml::Generate SELF.md step before docker build
  affects:
    - core/heartbeat.py (weekly check_code() run now includes self-md-sha check)
    - .github/workflows/deploy.yml (SELF.md always regenerated on push to main)
tech_stack:
  added:
    - hashlib.sha1 (stdlib — inline in check_code() for fresh SHA computation)
    - re (stdlib — inline regex for <!-- sha: --> extraction and tool name scanning)
  patterns:
    - Same try/except Exception + logger.warning pattern as all other check_code() blocks
    - SHA computation identical to core/self_manifest._compute_schema_hash (reads core/tools.py + interfaces/web_server.py)
    - CI step follows 2-key format (name: + run:) matching adjacent deploy.yml steps
key_files:
  created: []
  modified:
    - core/heartbeat.py
    - .github/workflows/deploy.yml
decisions:
  - "SHA recomputation in heartbeat.py is a verbatim replication of _compute_schema_hash logic (not an import of self_manifest.py) to keep heartbeat self-contained and CI-safe — importing self_manifest.py from heartbeat would create a circular dependency risk and require all manifest deps to be present at heartbeat import time."
  - "deploy.yml uses 'python core/self_manifest.py' (not 'python3') — ubuntu-latest GitHub Actions runners have python3 as default python; the plan specified python which maps to python3 on that runner."
  - "No setup-python action added — ubuntu-latest ships Python 3 pre-installed; self_manifest.py is stdlib-only so no pip install needed."
metrics:
  duration_minutes: 8
  completed_date: "2026-05-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 2
---

# Phase 16 Plan 04: Heartbeat SHA Check & CI Manifest Generation Summary

**One-liner:** check_code() extended with weekly SELF.md SHA staleness signal using identical hash logic as self_manifest.py, plus a Generate SELF.md CI step in deploy.yml that runs before docker build on every push to main.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend check_code() with SELF.md SHA staleness check | d18ee43 | core/heartbeat.py |
| 2 | Add Generate SELF.md step to deploy.yml | 5e43267 | .github/workflows/deploy.yml |

## What Was Built

### Task 1: core/heartbeat.py — SELF.md SHA staleness block

Inserted a new check block inside `check_code()` immediately before `return signals` (after the existing "Repeated-fix clusters" block). The block:

1. Reads `docs/SELF.md` from disk using `root / "docs" / "SELF.md"`
2. Extracts the stored SHA from the `<!-- sha: <hex> -->` comment line using regex `<!--\s*sha:\s*([0-9a-f]{40})\s*-->`
3. Recomputes a fresh SHA using the exact same algorithm as `_compute_schema_hash` in `core/self_manifest.py`:
   - Reads `"name": "..."` tool names from `core/tools.py` (sorted)
   - Reads `"/cron/..."` route strings from `interfaces/web_server.py` (sorted)
   - SHA-1 of the joined fragments
4. If `stored_sha != fresh_sha`, appends a `SEVERITY_FYI` signal with fingerprint `code:self-md-stale`
5. If `docs/SELF.md` is absent (fresh deploy before first run): silently skips — not an error condition
6. Wrapped in `try/except Exception` with `logger.warning("heartbeat: self-md-sha check failed", exc_info=True)`

The check lives inside `check_code()` which is already gated at `weekly=True` in `_collect_signals()` — so this check only fires on weekly heartbeat runs, satisfying the T-16-15 threat mitigation.

### Task 2: .github/workflows/deploy.yml — Generate SELF.md step

Inserted a new step between "Configure Docker for Artifact Registry" and "Build Docker image":

```yaml
      - name: Generate SELF.md capability manifest
        run: python core/self_manifest.py
```

The step order is now:
1. Checkout source
2. Authenticate to Google Cloud (WIF)
3. Set up Cloud SDK
4. Configure Docker for Artifact Registry
5. **Generate SELF.md capability manifest** (NEW)
6. Build Docker image
7. Push Docker image to Artifact Registry
8. Deploy to Cloud Run
9. Smoke-test health endpoint

The generated `docs/SELF.md` is written to the runner's workspace checkout and is then COPY'd into the Docker image by the subsequent `docker build` step. If `core/self_manifest.py` exits non-zero, the workflow fails and the deploy is aborted — this is the intended safety gate (T-16-14).

## Verification Results

```
# Task 1: check_code() works, SEVERITY_FYI signal for fresh SELF.md is absent
python3 -c "from core.heartbeat import check_code; signals = check_code(); print([s.fingerprint for s in signals])"
  → ['code:docs-drift']
  (self-md-stale absent — SELF.md SHA matches fresh computation, correct)

# Task 2: step order confirmed
grep -n "Generate SELF\|Build Docker" .github/workflows/deploy.yml
  → 46: - name: Generate SELF.md capability manifest
  → 49: - name: Build Docker image
  (line 46 < line 49 — order correct)
```

## Deviations from Plan

### Auto-fixed Issues

None.

### Design Adjustments (within Claude's discretion)

None — plan was executed exactly as written. The SHA replication block matches the plan's code block verbatim. The deploy.yml step matches the plan's step verbatim.

## Known Stubs

None — both files are fully wired. The heartbeat SHA check fires on real data (docs/SELF.md, core/tools.py, interfaces/web_server.py). The deploy.yml step runs on every push to main.

## Threat Flags

No new security surface beyond the plan's threat model. The `heartbeat.py` change reads only local filesystem files (docs/SELF.md, core/tools.py, interfaces/web_server.py) — same trust level as existing check_code() blocks. The deploy.yml change runs `core/self_manifest.py` which is an existing repo file at the same trust level as all other CI steps.

## Self-Check: PASSED

- [x] `core/heartbeat.py` contains `fingerprint="code:self-md-stale"` inside `check_code()` — FOUND (line 504)
- [x] `core/heartbeat.py` contains `SEVERITY_FYI` in the new block — FOUND (line 505)
- [x] `core/heartbeat.py` contains `<!--\s*sha:\s*([0-9a-f]{40})\s*-->` regex — FOUND (line 484)
- [x] `core/heartbeat.py` contains `_hashlib.sha1` — FOUND (line 500)
- [x] New block is inside `check_code()` before `return signals` — VERIFIED (line ordering)
- [x] `python3 -c "from core.heartbeat import check_code; check_code()"` exits 0 — VERIFIED
- [x] Fresh SELF.md does NOT trigger self-md-stale signal — VERIFIED
- [x] `.github/workflows/deploy.yml` contains `Generate SELF.md capability manifest` — FOUND (line 46)
- [x] `.github/workflows/deploy.yml` contains `python core/self_manifest.py` — FOUND (line 47)
- [x] Line 46 (Generate SELF.md) < line 49 (Build Docker image) — ORDER CORRECT
- [x] Commits d18ee43 and 5e43267 exist in git log — VERIFIED
