# Scripts

Split by whether it is still expected to run.

## `active/`

Operational tooling with a reason to be run again — CI gates, production audits,
recovery procedures, build steps.

| Script | Purpose |
|---|---|
| `check_claude_first_runtime.py` | CI gate. Fails the build if deployable source regains a retired runtime dependency. Invoked by `.github/workflows/deploy.yml`. |
| `audit_production_drift.py` | Read-only comparison of live Cloud Run against `ops/desired-production.json`. |
| `audit_quarantine.py` | Validates quarantine evidence against `ops/policies/quarantine.json`. |
| `gather_quarantine_evidence.py` | Collects the observation-window evidence that audit reads. |
| `manage_secret_versions.py` | Plan/apply bounded Secret Manager version retention. |
| `package_claude_skills.py` | Builds and verifies the Claude skill upload ZIPs. |
| `reauth_google.sh` | Re-runs Google OAuth consent and pushes the token to Secret Manager. |
| `reset_cron_streak.py` | Clears a stale `consecutive_failures` counter after a fixed cron failure. |
| `task_health.py` | Reports Things task-health figures against the baseline targets. |
| `test_healthkit_push.py` | Operator smoke test for `/cron/healthkit-sync`. |
| `bootstrap_shifu_crons.sh` | Re-runnable Cloud Scheduler bootstrap. |

## `archive/`

One-time migrations, seeds and exploration spikes. Kept because they document
how existing data got its shape, and because a few are the stated source of a
document in `docs/`. **Not expected to run again** — several would be actively
wrong to re-run against current data.

Nothing here is referenced by CI or by application code. Some are still imported
by tests that lock in the behaviour of the migration they performed.
