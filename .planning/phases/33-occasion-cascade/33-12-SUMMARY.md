---
phase: 33-occasion-cascade
plan: 12
subsystem: infra
tags: [deploy-config, secret-manager, ios-shortcuts, cron-retirement, documentation]

# Dependency graph
requires:
  - phase: 33-occasion-cascade
    provides: "33-10 POST /trigger/morning, POST /internal/process-occasion, _verify_morning_trigger_request, enqueue_occasion — the code surfaces this plan makes deployable"
provides:
  - "deploy.yml — OCCASION_CASCADE=false in --set-env-vars, MORNING_TRIGGER_TOKEN=klaus-morning-trigger-token:latest in --update-secrets, so neither is clobbered by a future deploy"
  - ".env.example — MORNING_TRIGGER_TOKEN and OCCASION_CASCADE local-dev template entries"
  - "docs/DEPLOYMENT.md — MORNING_TRIGGER_TOKEN Secret subsection (create/rotate/kill-switch), OCCASION_CASCADE flag section, §22 /trigger/morning row + iOS setup note, §19 klaus-morning-briefing retirement note naming plan 33-13"
  - "docs/sleep_focus_off_shortcut.md — operator runbook for the Sleep-Focus-off iOS Personal Automation, mirroring docs/healthkit_shortcut.md's 8-section structure"
  - "CLAUDE.md § 5 — live-infrastructure note that morning-briefing-tick is in transition to a push trigger, retiring at plan 33-13"
affects: [33-13]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Both new deploy-config values (OCCASION_CASCADE, MORNING_TRIGGER_TOKEN secret mount) are declared inline in deploy.yml's existing single-line --set-env-vars/--update-secrets strings, never set out-of-band via gcloud — this is what prevents the documented Phase 29 web-push --set-env-vars clobber incident from recurring."
    - "MORNING_TRIGGER_TOKEN Secret and OCCASION_CASCADE flag documented as subsections inside the existing DEPLOYMENT.md §23, not new top-level numbered sections — avoids renumbering §22/§23, which tests/test_docs.py asserts by literal heading string ('## 22. Push-driven endpoints', '## 23. HEALTHKIT_WEBHOOK_TOKEN Secret')."
    - "docs/sleep_focus_off_shortcut.md mirrors docs/healthkit_shortcut.md's exact 8-heading skeleton (Overview / permissions / Build / expected-response / share-link / Security / Testing / Troubleshooting) even though the tests file has no assertions on this new runbook yet — matching the established pattern makes it trivial to add matching test_docs.py coverage later without a rewrite."

key-files:
  created:
    - docs/sleep_focus_off_shortcut.md
  modified:
    - .github/workflows/deploy.yml
    - .env.example
    - docs/DEPLOYMENT.md
    - CLAUDE.md

key-decisions:
  - "MORNING_TRIGGER_TOKEN secret documentation added as a new '### MORNING_TRIGGER_TOKEN Secret' subsection immediately after the existing '### NIGHTLY_TRIGGER_TOKEN Secret (WS2)' subsection inside §23, rather than a new top-level '## 24' section — the plan's read_first pointed at §23's HEALTHKIT_WEBHOOK_TOKEN shape as the model to mirror, and tests/test_docs.py literal-asserts '## 23. HEALTHKIT_WEBHOOK_TOKEN Secret' and '## 22. Push-driven endpoints' as exact heading strings; inserting a same-numbered subsection satisfies the plan's 'modelled on the HEALTHKIT_WEBHOOK_TOKEN section' instruction without any renumbering risk."
  - "OCCASION_CASCADE documented as its own subsection within §23 rather than a separate section — it is conceptually a deploy-flag alongside the secret it gates observation for, and keeping both in one place matches the plan's single-task file_modified scope (docs/DEPLOYMENT.md, one task)."

requirements-completed: []
requirements-partial: [OCC-02, OCC-06]

# Metrics
duration: ~25min
completed: 2026-07-30
---

# Phase 33 Plan 12: Deploy Config, Docs and Morning-Trigger Live Prerequisites Summary

**All non-human deploy/doc work for the D-31 morning-trigger rollout is committed — `OCCASION_CASCADE` and the `klaus-morning-trigger-token` secret mount are declared in `deploy.yml` so they survive the next `--set-env-vars` deploy, and a full operator runbook exists for the Sleep-Focus-off iOS automation — but the plan cannot complete: Task 2 is a human-only checkpoint (create the GCP secret, deploy, build the iOS automation, confirm a live trigger) that only Amit can perform.**

## Performance

- **Duration:** ~25 min (worktree base-correction from `e407dd3` to `fdde40e` — the worktree had landed one merge behind wave 4's tip — through Task 1's final commit)
- **Started:** 2026-07-30 (session start)
- **Completed (Task 1 only):** 2026-07-30
- **Tasks:** 1/2 (Task 2 is `checkpoint:human-action`, `gate="blocking"` — cannot be executed by an agent)

## Accomplishments

- **`.github/workflows/deploy.yml`** — appended `,OCCASION_CASCADE=false` to the `--set-env-vars` string (ships `false`; plan 33-13's operator step flips it to `true`) and `,MORNING_TRIGGER_TOKEN=klaus-morning-trigger-token:latest` to `--update-secrets`, immediately after the existing `NIGHTLY_TRIGGER_TOKEN=klaus-nightly-trigger-token:latest` entry. Verified the modified single-line strings still parse as valid YAML.
- **`.env.example`** — added `MORNING_TRIGGER_TOKEN=` next to `NIGHTLY_TRIGGER_TOKEN=` with a comment stating it is a distinct secret (D-13), and `OCCASION_CASCADE=false` with a comment naming its scope (nightly + weekly cascade only; morning is cascade-only per D-30).
- **`docs/DEPLOYMENT.md`** — four additions: (1) a new `### MORNING_TRIGGER_TOKEN Secret (Phase 33 / D-08 / D-13 / D-31)` subsection in §23 with the full create/populate/bind/rotate/kill-switch runbook, modelled on the existing HEALTHKIT_WEBHOOK_TOKEN section; (2) a new `### OCCASION_CASCADE flag (Phase 33 / D-30)` subsection documenting the flag's scope, default, and the flip command; (3) §22's endpoint table extended with the `/trigger/morning` row plus an "iOS setup for `/trigger/morning`" paragraph describing the enqueue-then-202/503 contract and dark-ship sequencing; (4) a retirement note on §19's `klaus-morning-briefing` row inventory, naming plan 33-13 as the retirement point and explicitly instructing not to remove the row yet.
- **`docs/sleep_focus_off_shortcut.md`** (new, 8 sections) — operator runbook mirroring `docs/healthkit_shortcut.md`'s structure: Overview, required permissions (none — no HealthKit prompts), the exact Shortcuts build steps (Focus → Sleep → Is Turned Off → Get Contents of URL → POST with `Authorization: Bearer <MORNING_TRIGGER_TOKEN>`, Run Immediately ON, Notify OFF), expected `202 {"accepted": true}` response, iCloud share-link placeholder, Security Considerations (header-only token, TLS-only, distinct-secret D-13, lowercase secret name, kill-switch, no-replay-protection rationale), a curl-based Testing section mirroring the plan's own checkpoint verification steps, and an 8-row Troubleshooting table covering 401/403/500/503 plus the "two briefings" and "automation didn't fire" cases. States explicitly this is the mirror of the Sleep-Focus-ON automation and that there is no backstop (D-09).
- **`CLAUDE.md` § 5** — extended the live-infrastructure Cloud Scheduler sentence with an "In transition (Phase 33, D-08/D-31)" clause: the morning briefing is moving from `morning-briefing-tick`'s poll to `POST /trigger/morning` (mirror of the nightly's Sleep-Focus-on trigger), ships dark, and `morning-briefing-tick` retires at plan 33-13. Kept factual/inventory-only per the plan's instruction not to restate design decisions in CLAUDE.md.

## Task Commits

1. **Task 1: Deploy config, env template and documentation** — `5668566` (docs) — `.github/workflows/deploy.yml`, `.env.example`, `docs/DEPLOYMENT.md`, `docs/sleep_focus_off_shortcut.md` (new), `CLAUDE.md`

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md centrally after merge. This SUMMARY.md itself is committed separately per the worktree protocol._

## Files Created/Modified

- `.github/workflows/deploy.yml` — one-line additions to `--set-env-vars` (`OCCASION_CASCADE=false`) and `--update-secrets` (`MORNING_TRIGGER_TOKEN=klaus-morning-trigger-token:latest`, placed immediately after `NIGHTLY_TRIGGER_TOKEN`).
- `.env.example` — two new template entries (`MORNING_TRIGGER_TOKEN=`, `OCCASION_CASCADE=false`) with explanatory comments, inserted after the existing `NIGHTLY_TRIGGER_TOKEN=` entry.
- `docs/DEPLOYMENT.md` — §19 retirement note, §22 `/trigger/morning` row + iOS setup paragraph, new §23 `MORNING_TRIGGER_TOKEN Secret` and `OCCASION_CASCADE flag` subsections.
- `docs/sleep_focus_off_shortcut.md` — new file, 8 sections, ~150 lines.
- `CLAUDE.md` — one sentence appended to the § 5 Cloud Scheduler jobs bullet.

## Decisions Made

See `key-decisions` in the frontmatter. Summarized: (1) the new secret's documentation lives as a subsection inside the existing numbered §23 rather than a new top-level section, to satisfy the plan's "modelled on HEALTHKIT_WEBHOOK_TOKEN" instruction while not disturbing `tests/test_docs.py`'s literal `## 22.`/`## 23.` heading assertions; (2) `OCCASION_CASCADE` is documented alongside the secret in the same §23 area rather than a separate section, matching the plan's single docs-file task scope.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing critical functionality, or blocking issues were found in the codebase this plan builds on.

### Documented Interpretive Extensions (not Rule 1/2/3 fixes)

**1. New secret/flag documentation placed as subsections, not new top-level DEPLOYMENT.md sections.**
- **Why:** The plan's action text says "New section documenting the `klaus-morning-trigger-token` secret... modelled on the HEALTHKIT_WEBHOOK_TOKEN section," which could be read as requiring a new `## 24.` heading. `tests/test_docs.py::test_deployment_md_section_23_healthkit_secret` asserts the literal string `"## 23. HEALTHKIT_WEBHOOK_TOKEN Secret"` is present — inserting new content *within* §23 (as `###` subsections, exactly where the existing `NIGHTLY_TRIGGER_TOKEN Secret (WS2)` subsection already lives) satisfies both the plan's structural intent and the test's literal assertion with zero renumbering risk to any downstream section.
- **Verification:** `pytest tests/test_docs.py -x -q` — 17/17 passed.

## Issues Encountered

- **Worktree base drift.** Initial `git merge-base HEAD <expected-base>` returned `e407dd3` instead of the expected `fdde40e...` — the worktree's `HEAD` was one merge commit behind wave 4's tip (`fdde40e`, which itself is `.planning/phases/33-occasion-cascade/33-PATTERNS.md`'s companion tracking-update commit). Corrected via `git reset --hard fdde40efcfd539d72f2af9ec5d03a21473f7392b` on a clean tree before any file reads or edits began, per the `<worktree_branch_check>` protocol.

## User Setup Required

**Task 2 of this plan is entirely human-only and was NOT executed — returned as a checkpoint instead of simulated.** See the checkpoint block in the executor's final response for the full step-by-step (create `klaus-morning-trigger-token` in Secret Manager, deploy, smoke-test the route, build the iOS Sleep-Focus-off automation per `docs/sleep_focus_off_shortcut.md`, confirm one real live trigger produces exactly one briefing). Plan 33-13 (retiring `morning-briefing-tick`) must not run until Amit confirms this succeeded — retiring the legacy cron before the Shortcut is live is exactly the silent-morning gap D-31 exists to prevent.

## Next Phase Readiness

- All deploy-config and documentation prerequisites for a safe `/trigger/morning` go-live are in place and will survive the next CI deploy without being clobbered.
- `docs/sleep_focus_off_shortcut.md` gives Amit a complete, self-contained build guide — no further doc work is needed before he can build the automation.
- Plan 33-13 is blocked on Task 2's human confirmation ("trigger confirmed" resume-signal) — do not start 33-13 until that is received.
- `requirements-completed` is empty in this SUMMARY's frontmatter and OCC-02/OCC-06 are listed as `requirements-partial`: the plan's `<success_criteria>` explicitly requires "a real wake-up has been observed producing exactly one briefing," which is unreachable without the human checkpoint. The orchestrator should not mark OCC-02/OCC-06 complete from this plan alone.

## Self-Check: PASSED

- FOUND: `.github/workflows/deploy.yml`
- FOUND: `.env.example`
- FOUND: `docs/DEPLOYMENT.md`
- FOUND: `docs/sleep_focus_off_shortcut.md`
- FOUND: `CLAUDE.md`
- FOUND commit: `5668566` (Task 1)
- `grep -c "OCCASION_CASCADE=false" .github/workflows/deploy.yml` → 1
- `grep -c "klaus-morning-trigger-token:latest" .github/workflows/deploy.yml` → 1
- `grep -c "MORNING_TRIGGER_TOKEN" .env.example` → 1
- `grep -c "OCCASION_CASCADE" .env.example` → 1
- `ls docs/sleep_focus_off_shortcut.md` → exists; contains `/trigger/morning`, `Authorization: Bearer`, `Sleep Focus`, `202`
- `grep -c "trigger/morning" docs/DEPLOYMENT.md` → 7 (≥1 required)
- `grep -n "klaus-morning-briefing" docs/DEPLOYMENT.md` → row present + retirement note naming plan 33-13
- `grep -c "MORNING_TRIGGER_TOKEN" docs/DEPLOYMENT.md` → 7 (≥1 required)
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"` → ok
- `pytest tests/test_docs.py -x -q` → 17 passed
- `git diff --diff-filter=D --name-only HEAD~1 HEAD` → empty (no unintended deletions)
- `git status --short` → clean (no leftover untracked files)

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-30 (Task 1 of 2 — Task 2 blocked on human action)*

## Task 2 — Operator checkpoint RESOLVED (2026-08-01)

Human-action checkpoint closed. Evidence from production:

| Step | Result |
|------|--------|
| `klaus-morning-trigger-token` secret | Created; v1 held the literal string `<value>` (paste error) and was replaced by v2 + disabled. Final token length 44. |
| IAM grant to `klaus-runtime@` | Applied |
| Deploy | Revision above `klaus-agent-00173` serving |
| `POST /trigger/morning` no header | **401** `Missing or malformed Authorization header` |
| `POST /trigger/morning` bad bearer | **403** `Invalid token` |
| `POST /trigger/morning` valid bearer | **202** `{"accepted": true}` |
| iOS automation | Built on the **Wake Up** trigger (see below) |
| Live wake-up (2026-08-01) | `07:00:23Z /trigger/morning 202` → `07:00:24Z /internal/process-occasion 200` → `morning_briefing: skipped_by_judgment for 2026-08-01 (focus, cause=)` |

### Deviation from the planned trigger (D-08)

The plan and runbook specified **Focus → Sleep → Is Turned Off**. That trigger does not
exist on current public iOS: Apple excludes Sleep from the Focus automation list, and
the parity reported online shipped only in an iOS 26 developer beta — it landed in
iOS 27. Verified absent on the device (iOS 26.5.2). The automation uses the **Wake Up**
trigger instead; `docs/sleep_focus_off_shortcut.md` §3.0 now selects by iOS version and
records the device evidence.

Coverage consequence: Wake Up is tied to the Sleep Schedule, so it may not fire on a
night with no schedule set or an unusually early wake. **Alarm → Is Stopped** was
offered as a redundant second trigger and declined — Amit has daytime alarms, and with
the per-day dedupe an afternoon alarm on a no-alarm morning would fire the briefing at
the wrong time. Sound reasoning; single trigger accepted.

Amit chose **option one** for 33-13: retire `morning-briefing-tick` outright, no
backstop, per D-09.

### Observations carried forward

1. **Empty `skip_cause`** — both observed cascade runs (2026-07-31, 2026-08-01) logged
   `cause=` empty. `verdict.get("skip_cause", "")` is not being populated by the
   tick-brain. Non-breaking (heartbeat skip-streak counts statuses), but it degrades
   the audit trail the observation window depends on. → Phase 35.
2. **Legacy cron was already not delivering** — on 2026-07-31 `morning-briefing-tick`
   ran 24 times without passing its Garmin gate; on 2026-08-01 it produced no briefing
   either. The backstop being retired has not been delivering, which makes option one
   low-cost but suggests a pre-existing morning-briefing gap worth separate review.
