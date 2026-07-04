---
phase: 29-web-push-transition
plan: 02
subsystem: frontend-build / phase-tracking
tags: [workbox, service-worker, devDependencies, uat, mirror-week]
requires: []
provides:
  - "workbox-precaching/routing/strategies/expiration/core as direct devDependencies at ^7.4.1 (importable by the Plan 07 custom SW)"
  - "29-HUMAN-UAT.md with the D-20 device checklist and D-21 mirror-week tracking"
affects: [29-07 (custom sw.ts imports workbox modules), phase-close verification]
tech-stack:
  added:
    - workbox-precaching@^7.4.1 (devDependency)
    - workbox-routing@^7.4.1 (devDependency)
    - workbox-strategies@^7.4.1 (devDependency)
    - workbox-expiration@^7.4.1 (devDependency)
    - workbox-core@^7.4.1 (devDependency)
  patterns:
    - "Promote lockfile-transitive deps to direct devDeps at the pinned version (no version drift)"
    - "Package-legitimacy human gate before any new declared install"
key-files:
  created:
    - .planning/phases/29-web-push-transition/29-HUMAN-UAT.md
  modified:
    - frontend/package.json
    - frontend/package-lock.json
key-decisions:
  - "workbox-* 7.4.1 install approved via blocking-human package-legitimacy checkpoint (googlechrome publisher, github.com/googlechrome/workbox, no postinstall scripts)"
  - "idb package NOT added — Plan 07 uses raw IndexedDB for the SW badge counter (avoids a new dependency)"
duration: ~4 min (execution resumed post-checkpoint 2026-07-03T16:05:30Z)
completed: 2026-07-03
---

# Phase 29 Plan 02: Workbox devDeps + Human-UAT Tracking Doc Summary

Workbox 7.4.1 modules promoted from vite-plugin-pwa transitive deps to direct devDependencies (behind a human package-legitimacy gate) so Plan 07's custom injectManifest service worker can import them; 29-HUMAN-UAT.md created with the D-20 phase-close device checklist and D-21 mirror-week tracking items.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Verify workbox package legitimacy before install | (checkpoint — human approved) | — |
| 2 | Install workbox devDependencies | e9dcdbf | frontend/package.json, frontend/package-lock.json |
| 3 | Create 29-HUMAN-UAT.md device + mirror-week checklist | 58fbe92 | .planning/phases/29-web-push-transition/29-HUMAN-UAT.md |

## What Was Built

- **Task 1 (checkpoint):** The plan gated the install behind a `blocking-human`
  package-legitimacy checkpoint (research tagged workbox `[ASSUMED]` because
  slopcheck was unavailable). The user verified npmjs.com: publisher googlechrome,
  repo github.com/googlechrome/workbox, version 7.4.1 matching the lockfile, no
  postinstall scripts — and approved.
- **Task 2:** `npm install -D workbox-precaching@^7.4.1 workbox-routing@^7.4.1
  workbox-strategies@^7.4.1 workbox-expiration@^7.4.1 workbox-core@^7.4.1` from
  `frontend/`. All five resolve to the exact 7.4.1 already in the lockfile as
  vite-plugin-pwa transitive deps — no version drift, lockfile delta is
  declaration-only. `idb` was deliberately NOT added (Plan 07 uses raw IndexedDB).
- **Task 3:** `29-HUMAN-UAT.md` modeled on the Phase 26 on-device checklist
  pattern. Section 1 (D-20, phase-blocking): enable-push flow, chat-reply push
  with app closed, real proactive push with app closed, icon unread badge +
  clear-on-chat-view — each a checkbox row with a notes column. Section 2 (D-21,
  explicitly post-phase / non-blocking): mirror flag ON, daily double-buzz audit,
  ≥1-week observation window, mirror-off decision, plus a mirror-week log table.

## Verification

- `node -e "const p=require('./package.json');[...5 workbox modules...].forEach(...)"` → ok (all declared, `idb` absent)
- `node -e "require('workbox-precaching/package.json')"` → resolves (installed)
- `grep -q workbox-precaching frontend/package.json` → pass
- `test -f 29-HUMAN-UAT.md` + grep "Mirror" / "badge" / "D-20" / "D-21" → pass

## Deviations from Plan

None - plan executed exactly as written. (Task 1's checkpoint pause + resume-on-approval is the plan's designed flow, not a deviation.)

## Known Stubs

None — no code stubs; the UAT checkboxes are intentionally unchecked pending the
physical-device verification that Plan 10/phase close performs.

## Threat Flags

None — the only new surface is the declared devDependencies, which were the
subject of this plan's own threat register (T-29-SC) and were mitigated by the
blocking human-verify checkpoint before install.

## Self-Check: PASSED

- FOUND: frontend/package.json (contains workbox-precaching)
- FOUND: frontend/package-lock.json
- FOUND: .planning/phases/29-web-push-transition/29-HUMAN-UAT.md
- FOUND: commit e9dcdbf
- FOUND: commit 58fbe92
