# Klaus — GCP Bootstrap Runbook

This document walks you through taking Klaus from "nothing on GCP" to "fully
running in Cloud Run with CI/CD." Every command is copy-pasteable. Read each
section heading before running commands — the **why** is included so you
understand what you are doing, not just what to type.

---

## 1. Prerequisites

Complete every item on this checklist before running any commands below.

- **GCP project created and billing enabled.** You need billing even for
  free-tier services like Cloud Run (billing unlocks the APIs). Create a
  project at [console.cloud.google.com](https://console.cloud.google.com) and
  attach a billing account.

- **`gcloud` CLI installed and authenticated.**
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
  The second command sets up Application Default Credentials (ADC) on your Mac
  for local testing. Both commands open a browser for Google sign-in.

- **Docker installed and running.** Required only if you want to build and
  test the container locally before pushing. The CI/CD pipeline builds in the
  cloud, so Docker on your Mac is optional after initial setup.

- **GitHub repository exists and Klaus code is pushed to `main`.** The CI/CD
  workflow triggers on `push` to `main` and on manual dispatch.

- **GitHub repository secrets to be configured** (you will set these in
  Step 10 after the GCP resources are created):
  | Secret name | Value |
  |---|---|
  | `GCP_PROJECT_ID` | Your GCP project ID |
  | `GCP_REGION` | e.g. `me-west1` |
  | `GCP_WORKLOAD_IDENTITY_PROVIDER` | Printed at end of Step 9 |
  | `GCP_DEPLOYER_SA` | `klaus-deployer@<project>.iam.gserviceaccount.com` |
  | `TELEGRAM_ALLOWED_USER_IDS` | Your numeric Telegram user ID |

---

## 2. Shell Variables

Set these once in your terminal session. Every command in this runbook
references them, so if you open a new terminal tab you will need to re-export
them.

```bash
export PROJECT_ID=<your-gcp-project-id>
export REGION=me-west1          # Tel Aviv — lowest latency for you
export RUNTIME_SA=klaus-runtime@${PROJECT_ID}.iam.gserviceaccount.com
export DEPLOYER_SA=klaus-deployer@${PROJECT_ID}.iam.gserviceaccount.com
export GH_OWNER=<your-github-username>
export GH_REPO=Klaus
```

**Why `me-west1`?** It is the Tel Aviv region — lowest latency to you and the
closest to Google's Israeli data residency zone.

---

## 3. Enable GCP APIs

GCP services are disabled by default in every project. This command enables
exactly the APIs Klaus needs. Running it again on an already-enabled API is a
no-op, so it is safe to re-run.

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  iam.googleapis.com \
  --project ${PROJECT_ID}
```

| API | Why it is needed |
|---|---|
| `run.googleapis.com` | Deploy and serve the Klaus container |
| `artifactregistry.googleapis.com` | Store Docker images before deploying |
| `secretmanager.googleapis.com` | Store API keys and the OAuth token |
| `firestore.googleapis.com` | Conversation history, roster, attendance, and morning briefing state |
| `iamcredentials.googleapis.com` | Service account impersonation (WIF) |
| `sts.googleapis.com` | Token exchange for Workload Identity Federation |
| `iam.googleapis.com` | Create and manage service accounts |

---

## 4. Artifact Registry

Artifact Registry is where Docker images live before they are deployed to
Cloud Run. Think of it as a private Docker Hub that lives in your GCP project.

```bash
gcloud artifacts repositories create klaus \
  --repository-format=docker \
  --location=${REGION} \
  --project=${PROJECT_ID}
```

After this, the full image path will be:
`me-west1-docker.pkg.dev/<PROJECT_ID>/klaus/agent:<git-sha>`

The CI/CD workflow in `.github/workflows/deploy.yml` builds and pushes to
this exact path automatically on every push to `main`.

---

## 5. Runtime Service Account and IAM Grants

The runtime service account is the identity that the running Klaus container
uses to call GCP APIs (Firestore, Secret Manager, Cloud Logging). It is
attached to the Cloud Run service — the container never needs API keys for
these GCP services because Cloud Run injects credentials automatically via the
metadata server.

```bash
# Create the runtime service account
gcloud iam service-accounts create klaus-runtime \
  --display-name="Klaus Cloud Run runtime" \
  --project=${PROJECT_ID}

# Grant the three roles it needs
for role in roles/datastore.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="$role"
done
```

| Role | Why it is needed |
|---|---|
| `roles/datastore.user` | Read and write Firestore (conversation history, roster, attendance, morning briefing state) |
| `roles/secretmanager.secretAccessor` | Read secret versions (API keys, OAuth token) |
| `roles/logging.logWriter` | Write structured logs to Cloud Logging |

**Important:** `secretAccessor` lets the SA *read* secrets. Step 6 grants an
additional role to *write new token versions*. Both are required.

---

## 6. Secret Manager — Create and Populate Secrets

Secret Manager stores sensitive values outside the container image and
environment variables visible in the GCP console. Secrets are referenced by
name in the Cloud Run deployment; Cloud Run injects them as environment
variables at runtime.

### 6a. Create the secret resources

```bash
for secret in klaus-anthropic-key klaus-gemini-key klaus-telegram-token \
              klaus-telegram-webhook-secret klaus-google-oauth-token; do
  gcloud secrets create $secret \
    --replication-policy=automatic \
    --project=${PROJECT_ID}
done
```

This creates five empty secret containers. The next steps populate them.

### 6b. Populate API keys from your local environment

Make sure you have the actual values exported in your shell before running
these commands. `printf '%s'` is used instead of `echo` because `echo` appends
a newline that would corrupt the secret value.

```bash
printf '%s' "$ANTHROPIC_API_KEY" | gcloud secrets versions add klaus-anthropic-key \
  --data-file=- --project=${PROJECT_ID}

printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add klaus-gemini-key \
  --data-file=- --project=${PROJECT_ID}

printf '%s' "$TELEGRAM_TOKEN" | gcloud secrets versions add klaus-telegram-token \
  --data-file=- --project=${PROJECT_ID}
```

### 6c. Generate and store the Telegram webhook secret

This secret is sent by Telegram on every webhook POST as the
`X-Telegram-Bot-Api-Secret-Token` header. Klaus validates it using
constant-time comparison to reject any request not originating from Telegram.

```bash
WEBHOOK_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
printf '%s' "$WEBHOOK_SECRET" | gcloud secrets versions add klaus-telegram-webhook-secret \
  --data-file=- --project=${PROJECT_ID}

# SAVE THIS — you will need it in Step 12 to register the webhook with Telegram
echo "Save this: WEBHOOK_SECRET=${WEBHOOK_SECRET}"
```

The `klaus-google-oauth-token` secret is populated in Step 7 after the OAuth
consent flow runs.

### 6d. Grant the runtime SA permission to write new token versions

> **WARNING — THIS IS THE #1 CAUSE OF Klaus BREAKING AFTER ONE DAY.**
>
> Google OAuth access tokens expire every hour. When they do, `auth_google.py`
> silently refreshes the token using the refresh token — and then writes the
> new access token back to Secret Manager as a new version. This requires the
> `secretVersionAdder` role, which is *separate* from `secretAccessor`.
>
> If this role is missing, Klaus will work perfectly for the first hour after
> deployment (reading the bootstrapped token from Step 7), then silently break
> on the next calendar or Gmail call. You will see `PERMISSION_DENIED` errors
> in Cloud Logging for `add_secret_version` calls.
>
> After any calendar or Gmail query, verify that a new version appears in:
> GCP Console → Secret Manager → `klaus-google-oauth-token` → Versions.

```bash
gcloud secrets add-iam-policy-binding klaus-google-oauth-token \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretVersionAdder" \
  --project=${PROJECT_ID}
```

---

## 7. OAuth Token Bootstrap

This is a one-time step that runs the browser-based Google consent flow on
your Mac, then pushes the resulting token to Secret Manager. After this, the
cloud agent automatically refreshes the token and writes new versions back —
no manual intervention needed.

**Prerequisite:** `config/credentials.json` must exist (the OAuth client
secrets file downloaded from GCP Console → APIs & Services → Credentials →
OAuth 2.0 Client IDs). See `config/README.md` for how to get it.

```bash
# Run on your Mac — this opens a browser window for the Google consent screen.
# Sign in as amit.grupper@gmail.com and grant the requested scopes.
python -m core.auth_google
```

This produces `config/token.json`. Now push it to Secret Manager:

```bash
gcloud secrets versions add klaus-google-oauth-token \
  --data-file=./config/token.json \
  --project=${PROJECT_ID}
```

**Why is this a one-time step?** The consent screen is configured as
*Internal* (Google Workspace), which means the refresh token never expires.
Every subsequent token refresh is handled silently in the background by
`SecretManagerTokenStorage.save()` in `core/auth_google.py`.

---

## 7b. TickTick OAuth Bootstrap

Klaus writes tasks directly to the TickTick Open API — no Mac daemon required.
This one-time step obtains the initial token pair and uploads it to Secret Manager.

**Prerequisite:** Register a developer app at
[developer.ticktick.com](https://developer.ticktick.com/). Set the redirect
URI to `http://localhost:8765/callback`. Copy the `client_id` and
`client_secret` into `.env`.

### Create the TickTick secrets in Secret Manager

```bash
for secret in TICKTICK_CLIENT_ID TICKTICK_CLIENT_SECRET \
              TICKTICK_ACCESS_TOKEN TICKTICK_REFRESH_TOKEN; do
  gcloud secrets create $secret \
    --replication-policy=automatic \
    --project=${PROJECT_ID}
done
```

### Grant the runtime SA permission to write refreshed tokens

When the access token expires (~180 days), `ticktick_auth.py` silently
refreshes it and writes the new token back to Secret Manager. This requires
`secretVersionAdder` on both token secrets.

```bash
for secret in TICKTICK_ACCESS_TOKEN TICKTICK_REFRESH_TOKEN; do
  gcloud secrets add-iam-policy-binding $secret \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretVersionAdder" \
    --project=${PROJECT_ID}
done
```

### Run the bootstrap script

```bash
# Run on your Mac — opens a browser for the TickTick consent screen.
python scripts/ticktick_oauth_bootstrap.py
```

The script saves tokens to `config/ticktick_tokens.json` and prints the
exact `gcloud` commands to upload them to Secret Manager. Run those commands.
If TickTick does not return a refresh token, upload `none` as a placeholder:

```bash
echo -n "none" | gcloud secrets versions add TICKTICK_REFRESH_TOKEN \
  --data-file=- --project=${PROJECT_ID}
```

Upload the client credentials (source `.env` first so the vars are in scope):

```bash
source .env
echo -n "$TICKTICK_CLIENT_ID" | gcloud secrets versions add TICKTICK_CLIENT_ID \
  --data-file=- --project=${PROJECT_ID}
echo -n "$TICKTICK_CLIENT_SECRET" | gcloud secrets versions add TICKTICK_CLIENT_SECRET \
  --data-file=- --project=${PROJECT_ID}
```

**Note:** TickTick access tokens last approximately 180 days. If a token
expires, re-run `python scripts/ticktick_oauth_bootstrap.py` and re-upload
`TICKTICK_ACCESS_TOKEN` to Secret Manager.

---

## 8. Firestore Database

Skip this step if you already created the Firestore database during Phase 4.
Running it again on an existing database will fail with an error — that is
expected and safe.

```bash
gcloud firestore databases create \
  --database=klaus-firestore \
  --location=${REGION} \
  --type=firestore-native \
  --project=${PROJECT_ID}
```

The database name `klaus-firestore` matches the `FIRESTORE_DATABASE` env var
set in `.github/workflows/deploy.yml`. Collections used: `conversations`
(per-user chat history), `five_fingers_roster`, `five_fingers_practices`
(Phase 8 basketball helper), and `morning_briefings/{date}` (Phase 10
morning briefing state machine).

---

## 9. Deployer Service Account and Workload Identity Federation

The deployer service account is the identity GitHub Actions uses to push
Docker images and deploy to Cloud Run. Workload Identity Federation (WIF)
lets GitHub Actions *impersonate* this service account using a short-lived
OIDC token — **no JSON key files are ever created or stored in the repo**.

### 9a. Create the deployer service account

```bash
gcloud iam service-accounts create klaus-deployer \
  --display-name="Klaus GitHub Actions deployer" \
  --project=${PROJECT_ID}

for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${DEPLOYER_SA}" \
    --role="$role"
done
```

| Role | Why it is needed |
|---|---|
| `roles/run.admin` | Create and update Cloud Run services |
| `roles/artifactregistry.writer` | Push Docker images to Artifact Registry |
| `roles/iam.serviceAccountUser` | Allow the deployer to attach the runtime SA to the Cloud Run service |

### 9b. Create the Workload Identity pool and OIDC provider

```bash
# Create the pool — a namespace for WIF providers
gcloud iam workload-identity-pools create github-pool \
  --location=global \
  --display-name="GitHub Actions pool" \
  --project=${PROJECT_ID}

# Create the OIDC provider — only tokens from GitHub Actions are accepted,
# and the attribute-condition restricts it further to this exact repo.
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --workload-identity-pool=github-pool \
  --location=global \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GH_OWNER}/${GH_REPO}'" \
  --project=${PROJECT_ID}
```

**Why `attribute-condition`?** Without it, *any* GitHub repository that knows
your project number could impersonate the deployer SA. The condition pins the
trust to `<GH_OWNER>/<GH_REPO>` only.

### 9c. Bind the GitHub repo to the deployer SA

```bash
# Project number (different from project ID) is required for the principalSet URI
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')

gcloud iam service-accounts add-iam-policy-binding ${DEPLOYER_SA} \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GH_OWNER}/${GH_REPO}" \
  --project=${PROJECT_ID}
```

### 9d. Print the WIF provider string for GitHub secrets

```bash
echo "Copy the value below into GitHub secret GCP_WORKLOAD_IDENTITY_PROVIDER:"
echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
```

---

## 10. GitHub Repository Secrets

Go to your GitHub repository → **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**. Add all five secrets:

| Secret name | Value to enter |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID (e.g. `my-project-123`) |
| `GCP_REGION` | `me-west1` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | The string printed in Step 9d |
| `GCP_DEPLOYER_SA` | `klaus-deployer@<PROJECT_ID>.iam.gserviceaccount.com` |
| `TELEGRAM_ALLOWED_USER_IDS` | Your numeric Telegram user ID (find it by messaging `@userinfobot`) |

**No JSON key files.** WIF replaces long-lived credentials entirely. There is
no key file to rotate, leak, or accidentally commit.

---

## 11. First Deploy

The CI/CD pipeline triggers automatically on every push to `main`. To trigger
the first deployment:

```bash
git push origin main
```

Or trigger it manually without a code change:

```bash
gh workflow run deploy.yml
```

Open the **Actions** tab in your GitHub repository to watch the workflow run.
The steps are:

1. Checkout source
2. Authenticate to GCP via WIF (no JSON key)
3. Configure Docker for Artifact Registry
4. Build Docker image
5. Push image to Artifact Registry
6. Deploy to Cloud Run (`gcloud run deploy`)
7. Smoke-test `/health`

The full workflow takes approximately 3 minutes. When it finishes, the
**Deploy to Cloud Run** step prints the service URL in its output.

---

## 12. Register the Telegram Webhook

Telegram needs to know where to send updates. This one-time registration
tells Telegram to POST every incoming message to your Cloud Run service URL.

```bash
# Get the stable service URL
SERVICE_URL=$(gcloud run services describe klaus-agent \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format='value(status.url)')

echo "Service URL: ${SERVICE_URL}"

# Register the webhook — use the WEBHOOK_SECRET value saved in Step 6c
curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  -d "url=${SERVICE_URL}/telegram-webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "allowed_updates=[\"message\"]"
```

Verify the registration was accepted:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
```

A successful response looks like:

```json
{
  "ok": true,
  "result": {
    "url": "https://klaus-agent-xxxx-xx.a.run.app/telegram-webhook",
    "has_custom_certificate": false,
    "pending_update_count": 0,
    "last_error_message": ""
  }
}
```

**Critical:** Always use the **stable service URL** (the one printed by
`gcloud run services describe`), never a revision URL. Revision URLs contain
a hash suffix like `--abc123` and change with every deployment — Telegram
would stop receiving updates after the next deploy. The stable URL is
permanent and always routes to the active revision.

**Note:** Telegram's `setWebhook` returns HTTP 200 even if the URL is wrong or
unreachable. Always check `last_error_message` in `getWebhookInfo` output to
confirm there are no delivery errors.

---

## 13. Verification Checklist

Run these checks in order after the first deployment. Do not skip steps — each
one verifies a different layer of the stack.

1. **Health endpoint returns 200**
   ```bash
   curl --fail --silent --show-error "${SERVICE_URL}/health"
   # Expected: {"status":"ok"}
   ```

2. **Webhook secret enforcement**
   ```bash
   curl -X POST "${SERVICE_URL}/telegram-webhook" \
     -H "Content-Type: application/json" \
     -d '{"test": true}'
   # Expected: HTTP 401 Unauthorized
   ```
   A request without the `X-Telegram-Bot-Api-Secret-Token` header must be
   rejected. If it returns 200, the webhook is open to the internet.

3. **Telegram `/start` command**
   Send `/start` to your bot in Telegram.
   Expected reply: `"Klaus online, Sir."`

4. **Text message → Claude reply**
   Send any plain text message (e.g. `"What time is it?"`).
   Expected: a coherent reply from the agent with no error messages.

5. **Calendar query exercises OAuth token refresh**
   Ask Klaus about your schedule (e.g. `"What do I have tomorrow?"`).
   After the response, open GCP Console → **Secret Manager** →
   `klaus-google-oauth-token` → **Versions** and confirm that a new version
   was added (timestamp should be within the last minute). If no new version
   appears, the `secretVersionAdder` IAM binding from Step 6d is missing.

6. **TickTick task creation**
   Ask Klaus to add a task (e.g. `"Add a task: test the deployment"`).
   Verify it appears in TickTick immediately across all your devices (no Mac
   required — tasks are written directly to the TickTick Open API).

7. **Cold start latency**
   Wait at least 15 minutes with no messages (so the Cloud Run instance scales
   to zero). Then send a message. First response should arrive within 5–8
   seconds. If it takes longer, check `--timeout` in the deploy workflow and
   the Cloud Run logs for startup errors.

8. **Webhook info shows no errors**
   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
   ```
   Confirm `last_error_message` is empty or absent in the response.

---

## 14. Phase 9 — Proactive Alerts Setup

### 14a. Enable Routes API

```bash
gcloud services enable routes.googleapis.com --project=${PROJECT_ID}
```

No additional IAM role is needed — the runtime SA uses ADC (OAuth2 access token)
which is accepted by the Routes API.

### 14b. Store Home Address in Secret Manager

```bash
# Create the secret (one-time)
gcloud secrets create klaus-home-address \
  --replication-policy=automatic \
  --project=${PROJECT_ID}

# Populate it
printf '%s' "YOUR_HOME_ADDRESS" | gcloud secrets versions add klaus-home-address \
  --data-file=- --project=${PROJECT_ID}

# Grant the runtime SA read access
gcloud secrets add-iam-policy-binding klaus-home-address \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project=${PROJECT_ID}
```

The `deploy.yml` workflow injects this as `HOME_ADDRESS` via `--update-secrets`.

### 14c. Create the Cloud Scheduler Job

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

### 14d. Verify

```bash
# Trigger manually from GCP Console or:
gcloud scheduler jobs run klaus-proactive-alerts \
  --location="${REGION}" --project="${PROJECT_ID}"
```

Check Telegram for the alert message and Cloud Logging for clean execution.
Run a second time to confirm deduplication (no duplicate message sent).

---

## 15. Common Gotchas

### 1. Missing `secretVersionAdder` IAM (most common)

**Symptom:** Klaus works perfectly for the first hour, then all calendar and
Gmail calls silently fail. Cloud Logging shows `PERMISSION_DENIED` on
`add_secret_version`.

**Cause:** The `secretAccessor` role lets the runtime SA *read* secrets but
not write new versions. OAuth access tokens expire every hour; the agent
writes a refreshed token as a new Secret Manager version — this requires
`secretVersionAdder` separately.

**Fix:** Re-run the command from Step 6d.

**Prevention:** After any calendar query, immediately check Secret Manager for
a new `klaus-google-oauth-token` version. If none appears, fix this before
going further.

---

### 2. Revision URL used for `setWebhook`

**Symptom:** Telegram webhook stops working after the next deployment.

**Cause:** Cloud Run generates a new revision URL (containing a hash like
`--abc123`) on every deploy. If you used a revision URL for `setWebhook`,
traffic stops being routed to the new revision.

**Fix:** Always use `gcloud run services describe ... --format='value(status.url)'`
to get the stable service URL and re-register the webhook.

---

### 3. `GOOGLE_APPLICATION_CREDENTIALS` collision

**Symptom:** Cloud Run starts fine but all Google API calls fail with auth
errors, despite correct IAM bindings.

**Cause:** Setting `GOOGLE_APPLICATION_CREDENTIALS` as a Cloud Run env var
overrides Application Default Credentials (ADC). When a runtime SA is
attached to a Cloud Run service, ADC is injected automatically via the
metadata server — no env var is needed. Setting the variable to a path that
does not exist in the container breaks authentication entirely.

**Fix:** Do not set `GOOGLE_APPLICATION_CREDENTIALS` in Cloud Run. The deploy
workflow in `.github/workflows/deploy.yml` intentionally omits it from
`--set-env-vars` for this reason.

---

### 4. WIF "Permission denied" binding error

**Symptom:** GitHub Actions workflow fails at the **Authenticate to Google
Cloud (WIF)** step with `Permission denied` or `Unable to generate token`.

**Cause:** Usually a typo in the `principalSet://` member string when binding
the deployer SA. The project *number* (not the project *ID*) must be used,
and `attribute.repository` must exactly match `<owner>/<repo>`.

**Fix:** Re-run Step 9c carefully. Double-check `PROJECT_NUMBER` with:
```bash
gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)'
```
and verify `GH_OWNER` and `GH_REPO` match the GitHub repository exactly
(case-sensitive).

---

### 5. `setWebhook` returns 200 for bad URLs

**Symptom:** `setWebhook` call succeeds but no messages arrive in Telegram.

**Cause:** Telegram's Bot API always returns HTTP 200 for `setWebhook` calls,
even if the URL is unreachable, returns errors, or uses an invalid certificate.

**Fix:** Always run `getWebhookInfo` after registration and inspect
`last_error_message`. A non-empty `last_error_message` means Telegram is
trying to deliver updates but your endpoint is failing — check Cloud Run logs
for the actual error.

---

### 6. Local development still works after cloud setup

After completing all cloud setup, your local environment must continue to
work. Verify:

```bash
# On your Mac — should start the bot in polling mode
python -m interfaces.telegram_bot
```

Local dev uses `GOOGLE_TOKEN_STORAGE=file` and reads `config/token.json`
from disk. Cloud Run uses `GOOGLE_TOKEN_STORAGE=secret_manager`. These are
separate code paths in `core/auth_google.py` controlled by the env var — they
do not interfere with each other.

---

### 7. `.env` file is not loaded in Cloud Run

**Symptom:** An env var is set in `.env` but the cloud container does not see
it.

**Cause:** There is no `.env` file inside the container (it is excluded by
`.dockerignore`). `load_dotenv(override=True)` in `interfaces/web_server.py`
is a no-op in the cloud because there is no file to load.

**Fix:** All cloud env vars come from two places, both set in the deploy
workflow:
- `--set-env-vars` for non-sensitive configuration (region, model names, etc.)
- `--update-secrets` for sensitive values (API keys, tokens)

If an env var is missing in Cloud Run, add it to the appropriate flag in
`.github/workflows/deploy.yml`.
