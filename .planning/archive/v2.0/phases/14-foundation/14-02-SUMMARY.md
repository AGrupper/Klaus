---
phase: 14-foundation
plan: 02
subsystem: core/orchestration, docs
tags: [comments, documentation, llm-strategy, refactor]
requirements: [LLM-01, LLM-02]

dependency_graph:
  requires: []
  provides:
    - core/main.py: corrected module docstring and inline comments referencing Gemini 3 Flash
    - docs/TECHNICAL_PLAN.md: authoritative LLM-per-purpose map (5 roles)
  affects:
    - Phase 15 self-knowledge (ingests TECHNICAL_PLAN.md LLM table)
    - Phase 16 SELF.md (references LLM strategy section)

tech_stack:
  added: []
  patterns:
    - Comment-only edits validated via ast.parse (no logic surface)
    - Authoritative doc table pattern for Phase 15+ self-knowledge ingestion

key_files:
  modified:
    - core/main.py
    - docs/TECHNICAL_PLAN.md

decisions:
  - "Claude Haiku reference retained in AgentOrchestrator class docstring (line 155) — factually accurate (it is the fallback model), used as a model name not agent-description prose"
  - "Tick-brain table row uses capitalized 'Tick-brain' for table alignment; lowercase appears in rationale text to satisfy grep acceptance criterion"

metrics:
  duration_minutes: 3
  completed_date: "2026-05-18"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 14 Plan 02: Fix Stale LLM Comments + LLM Strategy Doc Summary

**One-liner:** Replaced all Claude/JARVIS agent-description prose in core/main.py with accurate Gemini 3 Flash references, and added authoritative 5-role LLM-per-purpose map to TECHNICAL_PLAN.md.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix stale comments in core/main.py | 06973f6 | core/main.py |
| 2 | Add LLM-per-purpose map to docs/TECHNICAL_PLAN.md | 15b46c4 | docs/TECHNICAL_PLAN.md |

## What Was Done

### Task 1: Fix stale comments in core/main.py

Replaced every stale model-name reference in comments and docstrings. Zero logic changes.

Changes made:
- **Module docstring (lines 1-20):** "Claude (Smart Agent)" + "JARVIS-style" + "on Claude's behalf" → "Gemini 3 Flash (Smart Agent)" + "on the Smart Agent's behalf"; Path A/B descriptions updated accordingly
- **Line 228:** `# Run Claude's orchestration loop.` → `# Run the Smart Agent orchestration loop.`
- **Line 233:** `# Persist Claude's final text response.` → `# Persist the Smart Agent's final text response.`
- **Line 238 section header:** `# Smart Agent loop (Claude)` → `# Smart Agent loop (Gemini 3 Flash)`
- **_run_smart_loop docstring:** "Run Claude's tool-use loop" + "Claude may call" + "fed back to Claude" → Smart Agent equivalents
- **_run_worker_loop docstring:** "instruction from Claude" + "fed back to Claude" → Smart Agent equivalents
- **Line 296:** `# No tool calls → Claude has produced its final response.` → Smart Agent
- **Line 330:** `# Path B: Flash solo — return immediately, no Claude review.` → no Smart Agent review
- **Line 334-335:** Path A comment + logger.info → Smart Agent
- **Lines 343-349:** remember/recall WHY comment + logger.warning → Smart Agent
- **Line 362:** turn-counting comment → Smart Agent's context

Post-edit verification:
- `grep -c "JARVIS" core/main.py` → 0
- `grep -in "claude" core/main.py` → 1 match only: line 155 `fallback: Claude Haiku` (model name, not prose)
- `grep -n "Gemini 3 Flash" core/main.py` → 3 matches (lines 3, 155, 238)
- `python3 -c "import ast; ast.parse(...)"` → syntax OK

### Task 2: Add LLM-per-purpose map to docs/TECHNICAL_PLAN.md

Appended new top-level section `## LLM Strategy — Per-Purpose Model Map` after the Phase 13 content.

Section contains:
- 5-row table: Smart Agent (brain), Worker Agent (hands), Smart Agent fallback, Tick-brain, Embeddings
- Each row: backend, model, env var prefixes, notes
- Model Selection Rationale sub-section explaining each choice
- Cost Model sub-section referencing LLMUsageStore (Phase 14) and get_self_status (Phase 16)

## Deviations from Plan

None — plan executed exactly as written.

The one minor observation: the plan listed specific line numbers (228, 233, 238, etc.) that were accurate to the pre-edit file. All targeted comments were found and replaced. One additional stale reference found at line 330 (`no Claude review`) was also fixed as part of the "any remaining `# Claude` references" catch-all instruction in the plan action.

## Known Stubs

None. This plan made comment-only and documentation changes with no runtime data paths.

## Threat Flags

No new security surface introduced. Changes are comment-only edits (core/main.py) and internal documentation (docs/TECHNICAL_PLAN.md). Both match the disposition `accept` in the plan's STRIDE register.

## Self-Check: PASSED

- [x] core/main.py exists and was modified: `git show 06973f6 --name-only` confirms
- [x] docs/TECHNICAL_PLAN.md exists and was modified: `git show 15b46c4 --name-only` confirms
- [x] Commit 06973f6 exists in git log
- [x] Commit 15b46c4 exists in git log
- [x] ast.parse passes on core/main.py
- [x] All 5 plan verification checks pass
