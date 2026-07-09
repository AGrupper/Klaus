---
phase: 30-health-pages
plan: 08
subsystem: frontend
tags: [react, typescript, health-pages, routing, integration, uat]

# Dependency graph
requires:
  - phase: 30-health-pages
    plan: 05
    provides: "TrainingHistoryPage root"
  - phase: 30-health-pages
    plan: 06
    provides: "NutritionDetailPage root"
  - phase: 30-health-pages
    plan: 07
    provides: "SleepRecoveryPage root"
  - phase: 30-health-pages
    plan: 04
    provides: "SubTabs (persisted health-tab) + RangeToggle"
provides:
  - "frontend/src/components/health/HealthPage.tsx — /health root: SubTabs + active sub-page switch"
  - "frontend/src/App.tsx — /health route wired to the real HealthPage (ComingSoon removed)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "HealthPage holds active-tab state; SubTabs owns localStorage['health-tab'] persistence and notifies via onChange (fired on mount with the restored value + on each change). Default Training."
    - "Renders inside the standard center column (16px padding, matches TasksPage) — no full-width exception (D-03); Sidebar/BottomTabs untouched."
    - "ComingSoon placeholder fully removed once Health was its last consumer — tsc -b (production build) flags unused declarations, so dead code cannot linger."

key-files:
  created:
    - frontend/src/components/health/HealthPage.tsx
    - frontend/src/components/health/HealthPage.test.tsx
  modified:
    - frontend/src/App.tsx

key-decisions:
  - "Task 3 was a blocking human-verify checkpoint (device UAT on the deployed iPhone PWA — SPA/auth paths have no CI coverage). Tasks 1-2 executed inline on Opus 4.8 after the wave-4 executors hit provider usage limits; the checkpoint was carried through real device testing over several deploy cycles."

requirements-completed: [HLTH-01, HLTH-02, HLTH-03]

# Device UAT outcome (Task 3 — blocking human-verify)
uat: approved
uat-notes: |
  Device UAT surfaced and closed several defects on the live deployment (all
  fixed + regression-tested, committed on main, deployed to rev
  klaus-agent-00149-27w):
    - Sleep tab 500 → Decimal-not-JSON-serializable from Postgres daily_biometrics
      NUMERIC columns; coerced Decimal→float in fetch_biometric_range + _jsonsafe_value
      (commit 227f055).
    - Chart tooltips showed raw unitless values + clipped at the right edge;
      added a formatValue prop (pace → m:ss/km, volume/mileage → units) and a
      containerWidth clamp on ChartTooltip (commit 1a51fcf).
    - Training "Weekly Volume" (strength kg) replaced with "Weekly Mileage"
      (run km); Run Pace Y-axis inverted (faster = higher via LineChart invertY);
      Sleep chart gained a legend (score line vs duration bars) (598b22e, caa440a).
    - Weekly Mileage buckets daily at 7d, weekly at 30d+ (commit f6e7f76).
  Final on-device verification approved 2026-07-09.
---

## What shipped

The `/health` route now renders the real **HealthPage** — a `SubTabs` control
switching between the Training, Nutrition, and Sleep sub-pages on pure client
state (persisted tab, default Training), inside the standard center column. This
is the integration seam that turned three independently-built sub-pages into the
shipped Health tab, closing HLTH-01/02/03 at the route level. The `ComingSoon`
placeholder was removed (Health was its last consumer).

## Phase gate (Task 2)

- `npx vitest run` — full frontend suite green (159 tests at close)
- `npm run build` — production build clean (health tree + charts bundled)
- Backend health test files pass per-file (training/nutrition/sleep/benchmark/reads)

## Device UAT (Task 3 — blocking human-verify)

Verified on the deployed iPhone PWA + desktop. See `uat-notes` above for the
defects found and fixed during UAT (Sleep 500, tooltip formatting/clipping,
mileage-vs-volume, pace orientation, sleep legend, mileage bucketing). All were
fixed at the source with regression tests and redeployed. Final state approved
on 2026-07-09 (serving revision klaus-agent-00149-27w).

## Commits (route wiring)

- `c194ed8` feat(30-08): wire /health route to real HealthPage (SubTabs + 3 sub-pages)
- `c1421d7` refactor(30-08): remove dead ComingSoon placeholder after Health wiring

(UAT gap-closure commits: 227f055, 1a51fcf, 598b22e, caa440a, f6e7f76.)

## Self-Check: PASSED

/health renders the real HealthPage with persisted sub-tabs; ComingSoon removed;
full frontend suite + build green; backend health tests green; device UAT approved.
