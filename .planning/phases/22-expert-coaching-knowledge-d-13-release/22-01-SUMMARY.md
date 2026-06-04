---
phase: 22-expert-coaching-knowledge-d-13-release
plan: "01"
subsystem: coaching-guide
tags: [coaching, knowledge-base, hybrid-athlete, file-authoring, COACH-01]
dependency_graph:
  requires: []
  provides:
    - docs/COACHING_GUIDE.md with SLIM_CORE_START/END markers and 10 SECTION slug anchors
  affects:
    - Plan 22-02 (wires _load_coaching_guide_slim() and read_coaching_guide tool)
    - Plan 22-03 (prompt injection in smart_agent.md)
tech_stack:
  added: []
  patterns:
    - Markdown knowledge file with HTML comment delimiters for slim-core extraction and section-slug lookup
key_files:
  created:
    - docs/COACHING_GUIDE.md
  modified: []
decisions:
  - One-file design: slim core delimited by SLIM_CORE_START/END, deep sections by SECTION slug anchors
  - Slim core kept to 143 lines / 7709 chars (well within 350-line / 15000-char budget)
  - All 10 section anchors authored in same file creation (not separate commits) for correctness
metrics:
  duration: "7 minutes"
  completed: "2026-06-04T17:08:39Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 22 Plan 01: Coaching Guide Authoring Summary

## One-Liner

Rich 1139-line hybrid-athlete coaching knowledge base authored in `docs/COACHING_GUIDE.md` with extractable slim core (143 lines) and ten correctly-slugged deep sections ready for Plan 02 tool wiring.

## What Was Built

`docs/COACHING_GUIDE.md` — the foundational coaching knowledge artifact for Phase 22 (COACH-01). The file has two parts:

**Part 1: Slim Core Digest** (between `<!-- SLIM_CORE_START -->` / `<!-- SLIM_CORE_END -->` markers)
- 143 lines / 7709 chars — well within the 350-line / 15000-char budget Plan 02 enforces
- Five H3 subsections authored with Amit-specific targets:
  1. AM/PM Split — The Interference Mitigation Rule (≥6h separation, ≈8h window, red flags)
  2. Session-by-Session Execution Cues (one paragraph per session: Wed threshold 3:50–3:55/km → 4:01/km, Mon/Thu easy 4:50–5:30/km, Fri long run Zone-2, Mon PM squats toward 120kg, Tue PM bench toward 100kg, Thu PM Upper-B weighted dips/pull-ups)
  3. Fueling Slot Map (6 slots as one-liners with mechanisms)
  4. Key Critique Flags (protein floor, deload compliance, threshold pace discipline, AM/PM ordering, long-run Zone-2)
  5. Tier A/B Quick Reference (recency windows: lifts ≤14d, pace ≤7d, nutrition ≤2d, Garmin always fresh)
- No `<!-- SECTION: -->` anchors inside the slim-core block (verified)

**Part 2: Ten Deep Sections** (after `<!-- SLIM_CORE_END -->`)
All ten section slugs exactly match the Plan 02 `read_coaching_guide` tool enum:

| Slug | Section Title | Key Content |
|------|--------------|-------------|
| `interference-effect` | Concurrent Training & The Interference Effect | AMPK/mTOR mechanism, ≥6h separation, session order, modality table, red flags |
| `block-periodization` | Block Periodization | 16-week arc (Aerobic Base / Capacity / Deep Waters / Race-Specific / Taper), deload weeks 4/8/12, benchmark timing |
| `threshold-runs` | Threshold Runs | LT2 definition, 3:50–3:55/km → 4:01/km lock-in, Wed volume table, over/unders, easy run + long run cues |
| `top-set-strength` | Top-Set Strength | 85–95% 1RM top set, bench 4×3–5 toward 100kg, drop set rationale, double progression model, red flags |
| `calisthenics-progressions` | Calisthenics Progressions | 125 push-up / 35 pull-up Nov targets, dual-stimulus architecture, 1–2.5kg/wk loading cap, tendon caution |
| `intervals-vo2max` | Intervals & VO2 Max | ≥90% VO2max stimulus, 4–6×3min protocol, 20s sprint neuromuscular purpose, Sunday mixed practice intent |
| `peri-workout-fueling` | Peri-Workout Fueling | All 6 slots in depth: glycogen resynthesis rates, quantities for ~75–80kg, fat-soluble vitamin timing |
| `protein-timing` | Protein Timing | 1.6–2.0g/kg evidence range, applied 150g critique (1.875g/kg @~80kg ASSUMED, flag), 20–40g/meal, leucine |
| `carb-periodization` | Carbohydrate Periodization | Fuel-for-work principle, day-by-day table for Amit's split, intra-run carbs for runs >90min |
| `supplements` | Supplement Rationale | Creatine/beta-alanine/Mg-glycinate/Zn/Cu/D3K2/Omega-3 — mechanism + evidence tier + dose + slot |

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author slim core digest block | 73845e5 | docs/COACHING_GUIDE.md (created, 1139 lines) |
| 2 | Author ten deep sections with anchors | 73845e5 | (same commit — see deviations) |

## Verification Results

```
SLIM_CORE_START markers: 1 ✓
SLIM_CORE_END markers: 1 ✓
Slim core size: 143 lines, 7709 chars ✓ (budget: <350 lines / <15000 chars)
Section anchors found: 10/10 ✓
Total file lines: 1139 ✓ (>=600 required)
[PEER]: 48 occurrences ✓
[CONSENSUS]: 16 occurrences ✓
[HEURISTIC]: 1 occurrence ✓
protein-timing: 150g present ✓, ~80kg present ✓, ASSUMED flagged ✓
No SECTION anchors inside slim core ✓
```

## Deviations from Plan

### Process Deviation (No Functional Impact)

**Task 1 and Task 2 committed in a single commit (73845e5)**

The plan specifies two sequential tasks (slim core first, then deep sections). Since I had complete research material (RESEARCH.md §Domain Science + §COACHING_GUIDE.md Structure) available before writing, and the content naturally forms a single coherent document, both the slim core and the ten deep sections were written in a single `Write` operation and committed together. The output is functionally identical to two sequential commits — both verifications pass, all acceptance criteria are met. Documented as a process-only deviation.

## Known Stubs

None. The guide is fully authored with real content. No placeholder text, "coming soon," or TODO markers.

## Threat Flags

None. Content is author-controlled prose (committed to repo, no runtime user input interpolated). T-22-01 mitigation (marker enforcement) and T-22-03 mitigation (closed enum, no filesystem path traversal) are in place by design — the markers verified present, and the section slugs are all valid lower-case identifiers.

## Self-Check: PASSED

- `docs/COACHING_GUIDE.md` exists: CONFIRMED
- Commit 73845e5 exists: CONFIRMED
- All 10 section slugs present: CONFIRMED
- Slim core within budget (143 lines / 7709 chars): CONFIRMED
- Total file ≥600 lines (1139): CONFIRMED
- Source-tier tags present: CONFIRMED
