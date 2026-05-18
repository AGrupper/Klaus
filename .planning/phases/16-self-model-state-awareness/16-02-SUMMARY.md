---
phase: 16-self-model-state-awareness
plan: "02"
subsystem: self-model
tags: [self-manifest, prompt-injection, self-state, gemini-caching]
dependency_graph:
  requires:
    - core/self_manifest.py::generate_manifest  # Plan 01
    - memory/firestore_db.py::SelfStateStore     # Plan 01
    - docs/SELF.md                               # Plan 01
  provides:
    - core/main.py::AgentOrchestrator._self_md_content
    - core/main.py::AgentOrchestrator._self_state_store
    - core/main.py::_load_self_md
    - core/main.py::_extract_intro_paragraph
    - core/main.py::_build_self_state_store
    - prompts/smart_agent.md::{self_md} placeholder
    - prompts/smart_agent.md::{self_state} placeholder
  affects:
    - Every smart_system prompt assembled in handle_message
    - Gemini prompt caching (stable SELF.md prefix)
tech_stack:
  added: []
  patterns:
    - Stable-first prompt assembly for Gemini prompt caching (D-03)
    - Blank-field omission in self_state snippet (D-05)
    - SelfStateStore.get() degrading gracefully to empty string on failure (T-16-07)
key_files:
  created: []
  modified:
    - core/main.py
    - prompts/smart_agent.md
decisions:
  - "self_state_snippet uses variable name 'lines' locally inside handle_message — shadows the module-level None but is scoped to the if-block; no conflict."
  - "SelfStateStore disabled (returns None) when GCP_PROJECT_ID not set — self_state_snippet stays empty string, conversation proceeds normally."
  - "SELF.md loaded at __init__ time (not per-message) — file is written at deploy time and stable for the lifetime of the container instance."
  - "bootstrap_if_empty called at __init__ (not lazily) — ensures Firestore doc is seeded before the first message arrives, avoiding a write on the hot path."
metrics:
  duration_minutes: 7
  completed_date: "2026-05-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 2
---

# Phase 16 Plan 02: Prompt Injection Summary

**One-liner:** SELF.md content and compact self_state fields injected into every smart_system prompt via stable-first chained `.replace()` calls, with `{self_md}` and `{self_state}` placeholders added to `prompts/smart_agent.md`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add SELF.md + SelfStateStore loading to AgentOrchestrator.__init__ | 2780453 | core/main.py |
| 2 | Inject SELF.md + self_state into smart_system at render step; update prompts/smart_agent.md | a3d4907 | core/main.py, prompts/smart_agent.md |

## What Was Built

### Task 1: AgentOrchestrator.__init__ extensions

Three module-level helpers added to `core/main.py` after `_load_prompt()`:

- **`_load_self_md()`** — reads `docs/SELF.md` at startup relative to `__file__`. Returns empty string on `OSError` so a missing SELF.md degrades gracefully (logs a warning, disables injection).
- **`_extract_intro_paragraph(self_md_content)`** — parses the Identity paragraph from SELF.md for use as `identity_summary` when bootstrapping SelfStateStore. Skips front-matter (`--- ... ---`), H1 heading, `<!-- sha: ... -->` comment, and blockquotes. Returns the first prose paragraph, or a fallback string if none found.
- **`_build_self_state_store()`** — constructs `SelfStateStore` from `GCP_PROJECT_ID` + `FIRESTORE_DATABASE` env vars. Returns `None` if `GCP_PROJECT_ID` is unset (local dev without Firestore).

`AgentOrchestrator.__init__` extended after `self.conversation_manager`:
- `self._self_md_content = _load_self_md()` — loads once at startup, no per-message file I/O
- `self._self_state_store = _build_self_state_store()` — None-safe; disabled in local dev
- `bootstrap_if_empty(identity_summary=...)` called on startup — idempotent, never raises

Also added: `from memory.firestore_db import SelfStateStore` import.

`Path` was already imported (`from pathlib import Path`) — no change needed.

### Task 2: handle_message render step + prompts/smart_agent.md

**`core/main.py` handle_message** — replaced the single-line `smart_system = ...` with a stable-first assembly block:

1. `self_state_snippet` built from `SelfStateStore.get()`: filters out blank fields and timestamp keys (`updated_at`, `bootstrapped_at`). Produces a `**Self-state:**` markdown list, or empty string if nothing non-empty.
2. `smart_system` assembled via chained `.replace()` in cache-friendly order: `{self_md}` (stable SELF.md content) → `{self_state}` (compact volatile state) → `{today_date}` (always-dynamic). This ordering means the SELF.md prefix is shared across messages and can be cached by Gemini.
3. `worker_system` unchanged — only `{today_date}` injected there.

**`prompts/smart_agent.md`** — two changes:
- Lines 1–5: `{self_md}` + blank line + `{self_state}` + blank line + `---` divider prepended before the existing persona text. This positions the stable manifest content at the very start of the rendered prompt.
- Bottom: `CAPABILITY MANIFEST` paragraph appended after the CODEBASE SELF-INSPECTION section, directing Klaus to refer to the injected SELF.md manifest when asked about his capabilities, limits, or unimplemented features.

## Verification Results

```
grep -n "{self_md}|{self_state}|{today_date}" prompts/smart_agent.md
  1: {self_md}
  3: {self_state}
  7: Today is {today_date}
  → Correct stable-first ordering confirmed

grep -n "replace.*self_md" core/main.py
  253: .replace("{self_md}", self._self_md_content)
  → Present

python3 -c "import ast; ast.parse(open('core/main.py').read()); print('OK')"
  → Syntax OK

git diff --diff-filter=D --name-only HEAD~1 HEAD
  → (empty — no file deletions)
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The injection is live: SELF.md content is read from disk at startup and rendered into every prompt. If `docs/SELF.md` exists (written by `core/self_manifest.py` at deploy time), the full 7-section manifest is injected. If missing (local dev without running self_manifest.py), injection is disabled with a warning — this is intentional degraded-mode behavior, not a stub.

## Threat Flags

No new security surface beyond the plan's threat model. The two relevant accepted threats (T-16-08: SELF.md content in every prompt; T-16-09: adversarial SELF.md) and the mitigated threat (T-16-07: SelfStateStore.get() blocking) are all covered by existing implementation: `get()` catches all exceptions and returns `{}`, so a Firestore failure produces an empty `self_state_snippet` and the conversation proceeds normally.

## Self-Check: PASSED

- [x] `core/main.py` contains `from memory.firestore_db import SelfStateStore` — FOUND (line 35)
- [x] `core/main.py` contains `def _load_self_md():` — FOUND (line 500)
- [x] `core/main.py` contains `def _extract_intro_paragraph(` — FOUND (line 515)
- [x] `core/main.py` contains `def _build_self_state_store():` — FOUND (line 553)
- [x] `core/main.py` contains `self._self_md_content = _load_self_md()` — FOUND (line 207)
- [x] `core/main.py` contains `self._self_state_store = _build_self_state_store()` — FOUND (line 212)
- [x] `core/main.py` contains `bootstrap_if_empty(` — FOUND (line 214)
- [x] `core/main.py` contains `.replace("{self_md}", self._self_md_content)` — FOUND (line 253)
- [x] `core/main.py` contains `.replace("{self_state}", self_state_snippet)` — FOUND (line 254)
- [x] `core/main.py` contains `non_empty = {k: v for k, v in state.items()` — FOUND (line 243)
- [x] `core/main.py` contains `k not in ("updated_at", "bootstrapped_at") and v` — FOUND (line 244)
- [x] `prompts/smart_agent.md` contains `{self_md}` on its own line — FOUND (line 1)
- [x] `prompts/smart_agent.md` contains `{self_state}` on its own line — FOUND (line 3)
- [x] `{self_md}` appears at line 1, `{today_date}` at line 7 — correct ordering confirmed
- [x] Commits 2780453 and a3d4907 exist in git log — VERIFIED
- [x] main.py syntax check passes (ast.parse) — VERIFIED
