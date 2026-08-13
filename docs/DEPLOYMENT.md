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

## OAuth token version retention

`SecretManagerTokenStorage.save()` writes the refreshed Calendar-only token,
then best-effort keeps the newest working version plus one rollback. Old enabled
versions are disabled; only versions already disabled before that refresh can
be destroyed. Cleanup failures are logged but never turn a persisted refresh
into a failed Calendar call. The runtime service account needs per-secret
`secretVersionAdder` and `secretVersionManager` roles on
`klaus-google-oauth-token`, in addition to per-secret `secretAccessor`.

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
  permanently removed. Record the observation start, log-derived access and
  provider-usage counts, disabled-state check, and three routine results in a
  JSON evidence file, then run
  `python scripts/audit_quarantine.py --evidence PATH`. Audit first; deletion is
  a separate operator action.
