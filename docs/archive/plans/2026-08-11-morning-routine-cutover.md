# Morning Routine Production Cutover Plan

**Goal:** Enable the Claude morning routine in production, keep nightly enabled and weekly disabled, install the missing 10:30 Asia/Jerusalem backstop, and verify one end-to-end morning delivery without changing unrelated production state.

**Architecture:** The deploy workflow owns the three independent Claude routine cutover flags. The Cloud Scheduler backstop calls the existing authenticated `POST /cron/morning-backstop` endpoint. Claude remains the routine execution surface; Klaus persists the authoritative review and provides the Hub/notification/continuation surfaces.

**Constraints:** Preserve `KLAUS_ROUTINE_NIGHTLY_CUTOVER=true` and `KLAUS_ROUTINE_WEEKLY_CUTOVER=false`. Do not change secrets, other environment variables, legacy jobs, tasks, calendar records, or user-owned working-tree files.

---

## Task 1: Enable the morning deploy cutover with a regression guard

**Files:**
- Modify: `tests/test_deploy_workflow_cutovers.py`
- Modify: `.github/workflows/deploy.yml`

1. Change the regression test to require morning and nightly `true`, with weekly still `false`, and give the test a name/docstring that describes the approved morning-plus-nightly state.
2. Run `tests/test_deploy_workflow_cutovers.py` and confirm it fails because the workflow still has morning `false`.
3. Change only `KLAUS_ROUTINE_MORNING_CUTOVER` in the deploy workflow from `false` to `true`.
4. Re-run the focused test and confirm it passes.
5. Run a broader focused routine/deploy suite and `git diff --check`.
6. Commit the tested change atomically.

## Task 2: Roll out and verify production

**External state:** GitHub Actions, Cloud Run, Cloud Scheduler, Firestore, Claude routine session, Klaus Hub.

1. Fast-forward the reviewed branch into local `main`, preserving unrelated user-owned changes, and push `main`.
2. Wait for the exact-head deploy workflow to succeed; verify Cloud Run health and the independent flag state: morning `true`, nightly `true`, weekly `false`.
3. Read the existing nightly backstop job configuration, then create or update `klaus-morning-backstop` with:
   - schedule: `30 10 * * *`
   - timezone: `Asia/Jerusalem`
   - method: `POST`
   - URI: the canonical Cloud Run service URL plus `/cron/morning-backstop`
   - scheduler OIDC service account/audience matching the existing authenticated Klaus scheduler jobs.
4. Trigger the morning route exactly once when a fresh target-date slot is available.
5. Verify the correlated run reaches a terminal success state, exactly one review is persisted/published, push delivery is recorded, the Hub shows the full review, and the exact Claude routine session is available for follow-up.
6. Confirm no unrelated task/calendar/action state changed and no new Cloud Run errors appeared.
