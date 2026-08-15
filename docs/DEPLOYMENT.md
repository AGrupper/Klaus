# Deployment Runbook

Deploy the Cloud Run service from `.github/workflows/deploy.yml`. The runtime
requires `KLAUS_USER_ID`, Firestore, Pinecone, and the embedding credential;
`KLAUS_USER_ID` must retain the established numeric namespace value.

The only Google OAuth scope is Calendar. Cached credentials that contain any
other scope are discarded and require explicit re-consent.

The retained public surfaces are the Hub, scoped MCP endpoints, routine
callbacks, deterministic alerts, and Web Push. Run
`python scripts/check_claude_first_runtime.py` before deployment.

## Desired production state and drift audit

[`ops/desired-production.json`](../ops/desired-production.json) is the checked-in
contract for the Cloud Run service, retained scheduler categories, environment
flags, Secret Manager bindings, per-secret IAM, routes, connectors, Firestore,
Artifact Registry, and the quarantined retirement set. Run the read-only audit:

```bash
python scripts/audit_production_drift.py
```

The command uses only `gcloud ... describe`, `list`, and `get-iam-policy`
operations and returns non-zero on drift. Use `--write-snapshot PATH` to retain
the normalized evidence. Application routes/connectors come from the checked-in
contract because GCP cannot enumerate them; Cloud Run, Scheduler, Secret
Manager/IAM, Firestore deletion protection/TTL, Artifact Registry cleanup, and
archive-bucket state are captured live.

The dedicated embedding project is `klaus-embeddings-838733`. It permits only
`gemini-embedding-2`; its restricted credential is
`klaus-gemini-embedding-key`, and the budget `Klaus Embeddings approx USD 5
Monthly` is 15 ILS with alerts at 50%, 90%, and 100%. Never bind the retired
general `klaus-gemini-key` to Cloud Run.

## Static Calendar OAuth credential

Secret Manager holds one long-lived, Calendar-only refresh credential. Google
access tokens are renewed in process memory and are never written back to
Secret Manager. The Cloud Run runtime service account therefore needs only the
per-secret `secretAccessor` role on `klaus-google-oauth-token`; granting it
`secretVersionAdder` or `secretVersionManager` is production drift.

Only the operator reauthorization flow may add a version. After an explicit new
grant, retention keeps the newest working version plus one rollback. Old enabled
versions are disabled; only versions already disabled before that operator run
can be destroyed.

The operator can inspect the exact plan without changing anything:

```bash
python scripts/manage_secret_versions.py \
  --project klaus-agent \
  --secret klaus-google-oauth-token
```

Applying it is deliberately explicit and identity-bound:

```bash
python scripts/manage_secret_versions.py \
  --project klaus-agent \
  --secret klaus-google-oauth-token \
  --destroy-grace-days 7 \
  --apply \
  --confirm-secret klaus-google-oauth-token
```

After deploying the static-token code, remove the obsolete runtime write roles
without changing the accessor grant:

```bash
gcloud secrets remove-iam-policy-binding klaus-google-oauth-token \
  --project klaus-agent \
  --member serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com \
  --role roles/secretmanager.secretVersionAdder
gcloud secrets remove-iam-policy-binding klaus-google-oauth-token \
  --project klaus-agent \
  --member serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com \
  --role roles/secretmanager.secretVersionManager
```

## Infrastructure hygiene policies

- `ops/policies/artifact-cleanup.json` keeps deployment-tagged images, the ten
  most recent images, and deletes eligible images older than 30 days. Import it
  only after tagging every currently deployed digest with `deployed-...`.
  Apply it first with
  `gcloud artifacts repositories set-cleanup-policies klaus --policy=ops/policies/artifact-cleanup.json --location=me-west1 --project=klaus-agent --dry-run`,
  observe candidates, and remove `--dry-run` only after the deployed-image and
  ten-most-recent keeps are proven.
- `ops/policies/firestore-hygiene.json` requires deletion protection and TTL on
  operational records only. Before enabling TTL, migrate each numeric/string
  `expires_at` field to a Firestore timestamp in the policy's `expire_at` field.
  Journals, reviews, memories, conversations, imported history, health, and
  training data are excluded.
- `ops/policies/chat-archive.json` moves the historical chat bucket to Archive
  storage and removes runtime access while preserving objects.
- `ops/policies/quarantine.json` requires seven complete days with zero access
  before any paused job, retired service account, secret, or storage binding is
  permanently removed. Gather the evidence by measurement rather than by hand:

  ```bash
  python scripts/gather_quarantine_evidence.py \
    --observation-start 2026-08-13T00:00:00Z \
    --out ops/evidence/quarantine-$(date +%F).json
  python scripts/audit_quarantine.py --evidence ops/evidence/quarantine-$(date +%F).json
  ```

  The gatherer is read-only (`describe`, `list`, `logging read`, Firestore
  reads). It measures secret access, scheduler executions, and service-account
  authentications separately, checks each quarantined resource is still inert,
  and reads `routine_runs` for routines Claude itself published — a
  `published_fallback` is the deterministic backstop, not a Claude success.

  A measurement that fails writes `-1` and names itself in
  `measurement_errors`, which closes the gate. Never hand-edit a count into an
  evidence file: the audit cannot tell an observed zero from an asserted one,
  and that distinction is the entire value of the seven-day gate.

  Note that administrative `DisableSecretVersion` / `DestroySecretVersion`
  calls are deliberately excluded from the access count — retiring a secret is
  not accessing it.

  Audit first; deletion is a separate operator action.
