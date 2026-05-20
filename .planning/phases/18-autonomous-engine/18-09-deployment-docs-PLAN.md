---
phase: 18-autonomous-engine
plan: 09
type: execute
wave: 3
depends_on: [07]
files_modified:
  - docs/DEPLOYMENT.md
  - tests/test_docs.py
autonomous: true
requirements: [INFRA-01]
requirements_addressed: [INFRA-01]

must_haves:
  truths:
    - "docs/DEPLOYMENT.md contains a single table listing ALL 9 Cloud Scheduler job-ids with schedule, endpoint, phase columns"
    - "docs/DEPLOYMENT.md contains gcloud scheduler jobs create http templates for both klaus-reflect (Phase 17, previously undocumented) and klaus-autonomous-tick (Phase 18)"
    - "docs/DEPLOYMENT.md documents the Groq TICK_BRAIN_API_KEY secret access path and rotation procedure"
    - "docs/DEPLOYMENT.md documents the Five Fingers job-id quirk (morning/evening share infrastructure historically caused ID-collision confusion) AND includes a migration paragraph telling operators how to drop the legacy single-id 'five-fingers' Cloud Scheduler job (bonus WARNING fix)"
    - "docs/DEPLOYMENT.md documents the Firestore composite index requirement on (status, due_at) for the followups collection"
    - "tests/test_docs.py asserts presence of all 9 job-id strings, Groq secret name, Five Fingers quirk header, composite index reference, AND the migration paragraph (gcloud scheduler jobs delete five-fingers)"
  artifacts:
    - path: "docs/DEPLOYMENT.md"
      provides: "9-cron table + 2 new gcloud blocks + Groq secret docs + Five Fingers quirk WITH migration + Firestore index"
    - path: "tests/test_docs.py"
      provides: "Completeness-grep tests for DEPLOYMENT.md"
      contains: "test_deployment_completeness"
  key_links:
    - from: "docs/DEPLOYMENT.md autonomous-tick block"
      to: "interfaces/web_server.py /cron/autonomous-tick (Plan 07)"
      via: "endpoint path + schedule string match"
      pattern: "/cron/autonomous-tick"
    - from: "docs/DEPLOYMENT.md composite index"
      to: "memory/firestore_db.py FollowupStore.list_due (Plan 01 NOTE comment)"
      via: "composite index on (status, due_at)"
      pattern: "composite index"
---

<objective>
Update `docs/DEPLOYMENT.md` to satisfy INFRA-01 — document every Cloud Scheduler
job in the project, the Groq secret access path, the Five Fingers job-id quirk
(noted in STATE.md), and the new Firestore composite index requirement for the
`followups` collection (flagged by Plan 01).

Purpose: INFRA-01 is the cross-cutting deployment doc requirement. With Phase 18
shipping 2 new crons (reflect from Phase 17, autonomous-tick from Phase 18),
the project's full cron count is 9 — and the deployment doc must now exhaustively
list all of them so production deploys don't have to reconstruct them from grep.

**Bonus WARNING fix:** the previous round documented the canonical Five Fingers
job-ids going forward but did NOT tell operators of older deployments how to
migrate from the historical single `five-fingers` Cloud Scheduler job. Add a
migration paragraph so deploys predating 2026-05 don't end up with three Five
Fingers jobs (one legacy + two new).

Output: ~90-130 lines added to `docs/DEPLOYMENT.md` + a new docs-grep test file.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/18-autonomous-engine/18-CONTEXT.md
@.planning/phases/18-autonomous-engine/18-RESEARCH.md
@.planning/phases/18-autonomous-engine/18-PATTERNS.md
@.planning/phases/18-autonomous-engine/18-01-SUMMARY.md
@.planning/phases/18-autonomous-engine/18-07-SUMMARY.md
@.planning/STATE.md
@docs/DEPLOYMENT.md

<interfaces>
<!-- Existing gcloud scheduler block to mirror — verbatim copy with field swaps. -->

From docs/DEPLOYMENT.md §14c lines 615-625 (klaus-proactive-alerts template):

```bash
gcloud scheduler jobs create http klaus-proactive-alerts \
  --schedule="30 21 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${SERVICE_URL}/cron/proactive-alerts" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

From STATE.md (Five Fingers job-id quirk reference):
> Note: Five Fingers morning + evening log the same `_log_cron_run` job-id `five-fingers` — known quirk, document in DEPLOYMENT.md in Phase 18.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add 9-cron master table + 2 new gcloud blocks + Groq secret + Five Fingers quirk WITH migration + composite-index note to docs/DEPLOYMENT.md, plus tests/test_docs.py</name>
  <files>docs/DEPLOYMENT.md, tests/test_docs.py</files>
  <read_first>
    - docs/DEPLOYMENT.md (read fully — confirm existing structure; find existing §14c klaus-proactive-alerts block; note section numbers and existing job documentation depth)
    - .planning/STATE.md "Existing cron jobs" section (the 7 existing jobs and their schedules, including the Five Fingers quirk)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "docs/DEPLOYMENT.md" lines 635-657 — exact additions required)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "docs/DEPLOYMENT.md (INFRA-01)" lines 304-323)
    - tests/test_docs.py (if exists; if not, create new file)
    - .planning/phases/18-autonomous-engine/18-01-SUMMARY.md (composite-index flag from Plan 01)
  </read_first>
  <action>
    Step A — Update `docs/DEPLOYMENT.md`. The file already has existing job documentation (the `klaus-proactive-alerts` block at §14c). Read it fully first; the additions land in 6 places (find the right sections in the existing structure):

    **Addition 1 — 9-cron master table.** Add a new top-level subsection. Insert this table verbatim:

    ```markdown
    ## Cloud Scheduler — Full Job Inventory

    The following 9 Cloud Scheduler HTTP jobs invoke Klaus's Cloud Run cron endpoints. All
    use OIDC bearer-token authentication via `${CLOUD_SCHEDULER_SA_EMAIL}`. All schedules
    are in `Asia/Jerusalem`.

    | # | Job ID                   | Schedule                | Endpoint                    | Phase   |
    |---|--------------------------|-------------------------|-----------------------------|---------|
    | 1 | klaus-five-fingers-morning | `30 10 * * 0,1,3,4`   | `/cron/five-fingers-morning` | Earlier |
    | 2 | klaus-five-fingers-evening | `15 21 * * 0,3`       | `/cron/five-fingers-evening` | Earlier |
    | 3 | klaus-morning-briefing   | `*/10 6-10 * * *`       | `/cron/morning-briefing`    | Earlier |
    | 4 | klaus-proactive-alerts   | `30 21 * * *`           | `/cron/proactive-alerts`    | Earlier |
    | 5 | klaus-heartbeat          | `0 * * * *`             | `/cron/heartbeat`           | Earlier |
    | 6 | klaus-ingest-chats       | `0 4 * * *`             | `/cron/ingest-chats`        | 12      |
    | 7 | klaus-ingest-chat-exports| `30 4 * * *`            | `/cron/ingest-chat-exports` | 13      |
    | 8 | klaus-reflect            | `0 22 * * *`            | `/cron/reflect`             | 17      |
    | 9 | klaus-autonomous-tick    | `*/20 7-21 * * *`       | `/cron/autonomous-tick`     | 18      |

    Notes:
    - Schedules in column 2 are illustrative — verify against the live `gcloud scheduler
      jobs list --project="${PROJECT_ID}" --location="${REGION}"` output before deploys.
    - Klaus's heartbeat picks up each job-id's last-run timestamp and alerts on staleness
      per `core/heartbeat.py:_CRON_MAX_STALENESS_HOURS`. The `autonomous-tick` threshold
      is 1 hour (3 missed 20-minute ticks) — see Phase 18 Pitfall 5.
    ```

    **Addition 2 — `klaus-reflect` gcloud block.** Phase 17's reflect job:

    ```markdown
    ### §14d — klaus-reflect (Phase 17)

    Daily reflection cron — runs `core/reflection.py:run_reflection()` at 22:00 Jerusalem.

    ```bash
    gcloud scheduler jobs create http klaus-reflect \
      --schedule="0 22 * * *" \
      --time-zone="Asia/Jerusalem" \
      --uri="${SERVICE_URL}/cron/reflect" \
      --http-method=POST \
      --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --location="${REGION}" \
      --project="${PROJECT_ID}"
    ```
    ```

    **Addition 3 — `klaus-autonomous-tick` gcloud block.** Phase 18's new cron:

    ```markdown
    ### §14e — klaus-autonomous-tick (Phase 18)

    Autonomous outreach tick — runs `core/autonomous.py:run_autonomous_tick()` every
    20 minutes between 07:00 and 21:00 Jerusalem time. Layer-0 gate keeps quiet ticks
    near-zero-cost (SC-3).

    ```bash
    gcloud scheduler jobs create http klaus-autonomous-tick \
      --schedule="*/20 7-21 * * *" \
      --time-zone="Asia/Jerusalem" \
      --uri="${SERVICE_URL}/cron/autonomous-tick" \
      --http-method=POST \
      --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --location="${REGION}" \
      --project="${PROJECT_ID}"
    ```

    Pre-flight check before first deploy: `gcloud scheduler jobs list --project="${PROJECT_ID}"
    --location="${REGION}" --filter="name~autonomous-tick"` — confirm the job does not
    already exist (no historical/staging collisions).
    ```

    **Addition 4 — Groq secret docs.**

    ```markdown
    ## TICK_BRAIN_API_KEY (Groq) Secret

    The tick-brain layer (Phase 14, used by both heartbeat reasoning and Phase 18's
    autonomous tick) calls Groq's free Qwen3-32B endpoint. Access is gated by a Groq
    API key stored in GCP Secret Manager.

    ### Secret location

    - Secret name: `klaus-tick-brain-api-key`
    - Project: `${PROJECT_ID}`
    - Access by: the Cloud Run runtime service account

    Cloud Run reads the secret via the deploy manifest's `--set-secrets`:

    ```bash
    gcloud run services update klaus-service \
      --set-secrets=TICK_BRAIN_API_KEY=klaus-tick-brain-api-key:latest \
      --region="${REGION}" --project="${PROJECT_ID}"
    ```

    ### Rotation procedure

    1. Generate a new API key at https://console.groq.com/keys
    2. Add a new secret version: `gcloud secrets versions add klaus-tick-brain-api-key
       --data-file=- --project="${PROJECT_ID}"` (paste new key, then Ctrl-D)
    3. Redeploy Cloud Run (it reads `:latest` by default).
    4. After confirming the new key works, disable the previous version:
       `gcloud secrets versions disable <prev-version> --secret=klaus-tick-brain-api-key`

    Fallback behavior: if Groq is unavailable, `TickBrain.think()` falls back to Gemini
    3 Flash automatically (TICK-02 / Phase 14). The autonomous tick continues to operate
    on the fallback chain.
    ```

    **Addition 5 — Five Fingers job-id quirk WITH MIGRATION (bonus WARNING fix).**

    ```markdown
    ## Known Quirks

    ### Five Fingers job-id collision

    Historically the Five Fingers morning and evening jobs both logged to `_log_cron_run`
    under the same job-id string (`"five-fingers"`), which led to confusion when reading
    heartbeat staleness output. The canonical Cloud Scheduler job IDs are now:

    - `klaus-five-fingers-morning` (Wed/Sun 10:30)
    - `klaus-five-fingers-evening` (Wed/Sun 21:15)

    Both still hit different endpoints, but readers of `cron_runs` Firestore docs should
    expect the morning + evening to appear under distinct job-ids going forward. When
    creating a new scheduler job, run a pre-flight `gcloud scheduler jobs list` to
    confirm the chosen name does not collide.

    #### Migration from the legacy single `five-fingers` job (bonus WARNING fix)

    If your deployment predates 2026-05 and has a single `five-fingers` job in Cloud
    Scheduler (rather than the two canonical jobs above), perform a one-time migration:

    1. **Confirm the legacy job exists:**
       ```bash
       gcloud scheduler jobs list --project="${PROJECT_ID}" \
         --location="${REGION}" --filter="name~five-fingers"
       ```
       If you see exactly one job named `five-fingers` (or `klaus-five-fingers` with no
       `-morning`/`-evening` suffix), proceed.

    2. **Create the two new canonical jobs first** (so there's no coverage gap):
       run the §14a / §14b gcloud blocks for `klaus-five-fingers-morning` and
       `klaus-five-fingers-evening`.

    3. **Delete the legacy single job:**
       ```bash
       gcloud scheduler jobs delete five-fingers \
         --location="${REGION}" --project="${PROJECT_ID}"
       ```
       (Substitute the actual legacy job name if it differs.)

    4. **Verify** the heartbeat staleness check picks up the new job-ids by waiting one
       hour and reading `cron_runs/{job_id}` for both new IDs — the switchover happens
       automatically once the new IDs are observed in Firestore.
    ```

    **Addition 6 — Firestore composite index note.**

    ```markdown
    ## Firestore Composite Indexes

    Klaus uses a small number of compound queries that require composite indexes:

    | Collection  | Fields                          | Created by | Notes |
    |-------------|---------------------------------|------------|-------|
    | followups   | `status` ASC, `due_at` ASC      | Phase 18   | Required by `FollowupStore.list_due()`. On first production query, Firestore returns a `FAILED_PRECONDITION` error with a link to create the index — follow it once, or run `gcloud firestore indexes composite create --collection-group=followups --field-config=field-path=status,order=ascending --field-config=field-path=due_at,order=ascending` ahead of first cron-tick deploy. |
    ```

    **Step B — Create `tests/test_docs.py`** (or extend existing) with a `TestDeploymentCompleteness` class:

    ```python
    """INFRA-01 — docs/DEPLOYMENT.md completeness assertions."""
    from __future__ import annotations

    import os

    DEPLOYMENT_PATH = os.path.join(
        os.path.dirname(__file__), os.pardir, "docs", "DEPLOYMENT.md"
    )


    def _content() -> str:
        with open(DEPLOYMENT_PATH, encoding="utf-8") as f:
            return f.read()


    class TestDeploymentCompleteness:

        # All 9 job-ids must appear
        ALL_JOB_IDS = [
            "klaus-five-fingers-morning",
            "klaus-five-fingers-evening",
            "klaus-morning-briefing",
            "klaus-proactive-alerts",
            "klaus-heartbeat",
            "klaus-ingest-chats",
            "klaus-ingest-chat-exports",
            "klaus-reflect",
            "klaus-autonomous-tick",
        ]

        def test_all_nine_job_ids_present(self):
            content = _content()
            for job_id in self.ALL_JOB_IDS:
                assert job_id in content, f"DEPLOYMENT.md missing job-id {job_id!r}"

        def test_autonomous_tick_schedule_present(self):
            content = _content()
            assert "*/20 7-21 * * *" in content
            assert "/cron/autonomous-tick" in content

        def test_reflect_schedule_present(self):
            content = _content()
            assert "/cron/reflect" in content

        def test_gcloud_create_block_present_for_autonomous_tick(self):
            content = _content()
            idx = content.find("klaus-autonomous-tick")
            assert idx >= 0
            window = content[max(0, idx-200):idx+1000]
            assert "gcloud scheduler jobs create" in window

        def test_groq_secret_documented(self):
            content = _content()
            assert "TICK_BRAIN_API_KEY" in content
            assert "klaus-tick-brain-api-key" in content
            # Rotation steps
            assert "gcloud secrets versions add" in content

        def test_five_fingers_quirk_documented(self):
            content = _content()
            assert "Five Fingers" in content
            assert "job-id" in content.lower() or "job id" in content.lower()

        def test_five_fingers_migration_paragraph_present(self):
            """Bonus WARNING — operators of older deploys need an explicit migration step."""
            content = _content()
            # The migration block instructs deleting the legacy single five-fingers job.
            assert "gcloud scheduler jobs delete five-fingers" in content, (
                "Bonus WARNING regression: migration paragraph for legacy single "
                "'five-fingers' Cloud Scheduler job missing from DEPLOYMENT.md"
            )
            # Migration must mention either "migration" or "predates 2026-05" for context.
            assert ("Migration" in content or "migration" in content), (
                "Migration paragraph should explicitly label itself as a migration step"
            )

        def test_followups_composite_index_documented(self):
            content = _content()
            assert "composite index" in content.lower()
            assert "followups" in content
            assert "status" in content
            assert "due_at" in content
    ```

    Step C — Run tests: `pytest tests/test_docs.py::TestDeploymentCompleteness -x`. All 8 tests must pass.

    Step D — Quick visual sanity check: `wc -l docs/DEPLOYMENT.md` should be at least 90 lines longer than before (the 6 additions plus the migration paragraph).
  </action>
  <verify>
    <automated>grep -c "klaus-autonomous-tick" docs/DEPLOYMENT.md && grep -c "klaus-reflect" docs/DEPLOYMENT.md && grep -c "TICK_BRAIN_API_KEY" docs/DEPLOYMENT.md && grep -ic "composite index" docs/DEPLOYMENT.md && grep -c "gcloud scheduler jobs delete five-fingers" docs/DEPLOYMENT.md && pytest tests/test_docs.py::TestDeploymentCompleteness -x</automated>
  </verify>
  <done>
    - `grep -c "klaus-autonomous-tick" docs/DEPLOYMENT.md` >= 2 (table row + gcloud block)
    - `grep -c "klaus-reflect" docs/DEPLOYMENT.md` >= 2 (table row + gcloud block)
    - `grep -c "TICK_BRAIN_API_KEY" docs/DEPLOYMENT.md` >= 1
    - `grep -ic "composite index" docs/DEPLOYMENT.md` >= 1
    - `grep -c "Five Fingers" docs/DEPLOYMENT.md` >= 1 in the quirk-doc area
    - `grep -c "gcloud scheduler jobs delete five-fingers" docs/DEPLOYMENT.md` >= 1 (bonus WARNING — migration paragraph)
    - All 8 tests in `TestDeploymentCompleteness` pass (includes `test_five_fingers_migration_paragraph_present`)
    - All 9 job-ids appear in the file (per `test_all_nine_job_ids_present`)
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_docs.py -x` — all 8 assertions pass
2. `grep -E "klaus-(five-fingers-morning|five-fingers-evening|morning-briefing|proactive-alerts|heartbeat|ingest-chats|ingest-chat-exports|reflect|autonomous-tick)" docs/DEPLOYMENT.md | sort -u | wc -l` returns 9 (one unique match per job-id)
3. Manual visual review: the 9-cron table renders cleanly in a markdown previewer
4. `grep -c "gcloud scheduler jobs delete five-fingers" docs/DEPLOYMENT.md` returns 1 (bonus WARNING)
</verification>

<success_criteria>
- All 9 Cloud Scheduler job-ids documented in a master table (INFRA-01).
- 2 new gcloud blocks (klaus-reflect, klaus-autonomous-tick) follow the existing template format.
- Groq secret access path + rotation procedure documented.
- Five Fingers job-id quirk documented as a "Known Quirks" subsection WITH a migration paragraph telling operators how to drop the legacy single `five-fingers` job (bonus WARNING).
- Firestore composite index requirement on `(status, due_at)` for the `followups` collection documented.
- Tests prove all of the above via grep assertions.
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-09-SUMMARY.md` with:
- Line count delta on `docs/DEPLOYMENT.md` (before vs after)
- List of sections added
- Test results (8/8 pass; explicitly call out `test_five_fingers_migration_paragraph_present` — bonus WARNING regression guard)
- Final phase wrap-up checklist: SC-1..SC-5 manual smoke procedures from 18-VALIDATION.md ready to run against staging
</output>
