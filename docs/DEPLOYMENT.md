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

set in `.github/workflows/deploy.yml`. Collections used: `conversations`
(per-user chat history), and `morning_briefings/{date}` (Phase 10
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
# On your Mac — should start the FastAPI app (Telegram webhook + /cron/* routes)
uvicorn interfaces.web_server:app --host 0.0.0.0 --port 8080
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

---

## 16. Phase 11 — Notion Integration Setup

### 16a. Create a Notion Internal Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations) and click **New integration**.
2. Name it **Klaus**, select your workspace, and set capabilities to **Read content**, **Insert content**, and **Update content** (no delete required).
3. Click **Submit**. On the next screen, copy the **Internal Integration Token** — this is your `NOTION_API_TOKEN`.

### 16b. Share Your PARA Databases with the Integration

Notion requires each database to be explicitly shared with the integration. For each of your PARA databases (Projects, Areas, Resources, Archives — and optionally your Journal/Daily Log):

1. Open the database page in Notion.
2. Click the **`...`** menu (top-right) → **Add connections**.
3. Search for **Klaus** and select it.

Repeat for every database you want Klaus to be able to read or write.

### 16c. Add `NOTION_API_TOKEN` to Secret Manager

```bash
echo -n "your_token_here" | gcloud secrets create NOTION_API_TOKEN \
  --data-file=- --project=${PROJECT_ID}
```

If the secret already exists and you are rotating the token:

```bash
echo -n "your_token_here" | gcloud secrets versions add NOTION_API_TOKEN \
  --data-file=- --project=${PROJECT_ID}
```

### 16d. Wire the Secret into Cloud Run

Add `NOTION_API_TOKEN` to the `--update-secrets` flag in `.github/workflows/deploy.yml`:

```
NOTION_API_TOKEN=NOTION_API_TOKEN:latest
```

The next CI/CD deploy will inject the token as an environment variable inside the container.

### 16e. Optional — Set `NOTION_JOURNAL_DB_ID` as a Plain Env Var

If you want Klaus to append journal entries reliably without searching for the database each time, set the journal database ID as a plain env var in Cloud Run:

```bash
gcloud run services update klaus-agent \
  --update-env-vars NOTION_JOURNAL_DB_ID=your_journal_db_id \
  --region=${REGION} \
  --project=${PROJECT_ID}
```

Or add it to `--set-env-vars` in the deploy workflow alongside other non-sensitive config.

### 16f. No Bootstrap Script Needed

Unlike Google OAuth or TickTick, the Notion internal integration token is issued directly in the Notion UI and **does not expire**. There is no refresh flow and no bootstrap script to run. Simply create the secret once (Step 16c) and it remains valid indefinitely.

### 16g. Verify

After the next deployment completes, send Klaus a message like:

> "Search Notion for project ideas"

Confirm that he returns results with page titles and URLs. If he returns an empty list or an error, check:

1. The `NOTION_API_TOKEN` secret value in Secret Manager (no leading/trailing whitespace).
2. That the target databases were shared with the Klaus integration (Step 16b) — Notion returns an empty result set, not an error, for unshared content.
3. Cloud Logging for any `401 Unauthorized` or `403 Forbidden` responses from the Notion API.

---

## 17. Phase 12 — Chat-Log Ingestion Setup

### 17a. Create the GCS Bucket

```bash
PROJECT_ID=$(gcloud config get-value project)
BUCKET_NAME="klaus-chat-logs-${PROJECT_ID}"

gcloud storage buckets create "gs://${BUCKET_NAME}" \
  --location=europe-west1 \
  --uniform-bucket-level-access \
  --project=${PROJECT_ID}

echo "CHAT_LOGS_BUCKET=${BUCKET_NAME}"
```

### 17b. Create the Log-Uploader Service Account

```bash
gcloud iam service-accounts create klaus-log-uploader \
  --display-name="Klaus Chat Log Uploader" \
  --project=${PROJECT_ID}

# Grant objectCreator on the bucket only (minimal scope)
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:klaus-log-uploader@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator"

# Grant objectViewer to the Cloud Run runtime SA
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:klaus-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

### 17c. Download the Uploader Key to Both Machines

```bash
# Create and download the key (do this once — keep the JSON secure)
gcloud iam service-accounts keys create /tmp/log-uploader-key.json \
  --iam-account="klaus-log-uploader@${PROJECT_ID}.iam.gserviceaccount.com"

# Copy the key to each machine at ~/.config/klaus/log-uploader-key.json
mkdir -p ~/.config/klaus
cp /tmp/log-uploader-key.json ~/.config/klaus/log-uploader-key.json
chmod 600 ~/.config/klaus/log-uploader-key.json
```

**Security note:** This key can only write objects to this bucket. It has no access to Pinecone, Gemini, Notion, or any other Klaus credential.

### 17d. Create the Notion Chat-Log Database

1. In Notion, create a new **full-page database** (not inline) called **"Klaus Chat Logs"**.
2. Add these exact properties (type matters):
   - `Name` (Title) — already exists by default
   - `Date` (Date)
   - `Project` (Select)
   - `Summary` (Text / Rich Text)
   - `Topics` (Multi-select)
   - `Machine` (Select)
   - `Session ID` (Text / Rich Text)
3. Share the database with your Klaus integration (**... → Add connections → Klaus**).
4. Copy the database ID from the URL and set it as `NOTION_CHAT_LOG_DB_ID`.

### 17e. Set the Cloud Run Environment Variables

```bash
gcloud run services update klaus-agent \
  --update-env-vars "CHAT_LOGS_BUCKET=${BUCKET_NAME},NOTION_CHAT_LOG_DB_ID=your-db-id" \
  --region=europe-west1 \
  --project=${PROJECT_ID}
```

Or add them to `.github/workflows/deploy.yml` under `--set-env-vars` for the next CI deploy.

### 17f. Create the Cloud Scheduler Job

```bash
gcloud scheduler jobs create http klaus-chat-ingest \
  --schedule="0 4 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="https://your-cloud-run-url/cron/ingest-chats" \
  --http-method=POST \
  --oidc-service-account-email="$(gcloud config get-value account)" \
  --oidc-token-audience="https://your-cloud-run-url" \
  --project=${PROJECT_ID}
```

Replace `your-cloud-run-url` with your Cloud Run service URL (same as `CLOUD_RUN_URL`).

Use the same `CLOUD_SCHEDULER_SA_EMAIL` service account that already runs the other cron jobs.

### 17g. Set Up the Local Upload Cron (Mac)

Test the script first:
```bash
CHAT_LOGS_BUCKET="${BUCKET_NAME}" ./scripts/upload_claude_logs.sh
```

Then add to crontab (edit with `crontab -e`):
```
0 3 * * * CHAT_LOGS_BUCKET=your-bucket-name /path/to/Klaus/scripts/upload_claude_logs.sh >> /tmp/claude-log-upload.log 2>&1
```

### 17h. Set Up the Upload Task (Windows)

1. Open **Task Scheduler** → **Create Basic Task**.
2. Name: "Klaus Log Uploader"
3. Trigger: Daily (e.g., at 03:00, with no repetition).
4. Action: Start a program → `powershell.exe`
5. Arguments: `-File C:\path\to\Klaus\scripts\upload_claude_logs.ps1`
6. Set `CHAT_LOGS_BUCKET` as a system environment variable (Control Panel → System → Advanced → Environment Variables).

### 17i. Backfill

After the first successful upload run, drain the backlog manually:

```bash
# Run until you see "done": true in the output
gcloud scheduler jobs run klaus-chat-ingest \
  --project=${PROJECT_ID} \
  --location=europe-west1

# Check Cloud Logging for the response:
gcloud logging read 'resource.type="cloud_run_revision" textPayload=~"chat_ingest"' \
  --project=${PROJECT_ID} --limit=10 --format=json
```

**Cost note:** A months-long backfill embeds thousands of chunks + one Flash call per conversation. At personal scale (~hundreds of sessions) this is a one-time cost of a few dollars at most.

### 17j. Verify

After the first successful scheduler run:

1. **Pinecone:** query your index for vectors with `source="claude_code"` and `kind="chat"`
2. **Notion:** the Chat Logs database should have one row per conversation
3. **Idempotency:** re-run the scheduler job — row count in Notion should not increase
4. **Agent:** ask Klaus "What did I work on this week?" — he should query the Notion DB by Date
5. **Agent:** ask Klaus "What did I decide about X in Claude Code?" — `search_chat_history` should return semantic hits
6. **Default recall isolation:** ask Klaus about your gym schedule — confirm chat chunks do NOT appear in the result

---

## 18. Phase 13 — Multi-Source AI Chat Export Ingestion

### 18a. Create the "Klaus AI Chat Imports" Notion Database

Create a new database manually in Notion with these exact properties:

| Property name    | Type        | Notes                        |
|-----------------|-------------|------------------------------|
| Name            | Title       | Conversation title           |
| Date            | Date        | Conversation start date      |
| Source          | Select      | Options: claude_ai, chatgpt, gemini |
| Summary         | Rich text   | 2-3 sentence Flash summary   |
| Topics          | Multi-select| Kebab-case labels            |
| Message Count   | Number      | Total turns in conversation  |
| Conversation ID | Rich text   | Upsert key — must be unique  |
| Last Updated    | Date        | Conversation updated_at      |

Share the database with your Notion integration token. Copy the database ID from the URL and set:
- `NOTION_AI_CHAT_DB_ID=<id>` in `.env` (local) and `NOTION_AI_CHAT_DB_ID` GitHub secret (Cloud Run).

### 18b. Add GitHub Secret

In GitHub → Settings → Secrets and variables → Actions, add:

```
NOTION_AI_CHAT_DB_ID = <your new Notion DB ID>
```

Deploy to Cloud Run (push to main or trigger `workflow_dispatch`) — the deploy workflow now injects `NOTION_AI_CHAT_DB_ID` via `--set-env-vars`.

### 18c. Create Cloud Scheduler Job

```bash
gcloud scheduler jobs create http klaus-chat-export-ingest \
  --project=${PROJECT_ID} \
  --location=europe-west1 \
  --schedule="30 4 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="https://${CLOUD_RUN_URL}/cron/ingest-chat-exports" \
  --http-method=POST \
  --oidc-service-account-email=klaus-heartbeat@${PROJECT_ID}.iam.gserviceaccount.com \
  --oidc-token-audience="https://${CLOUD_RUN_URL}"
```

### 18d. Upload Export Zips

```bash
# Claude.ai: Settings → Privacy → Export data
./scripts/upload_chat_export.sh claude_ai ~/Downloads/claude-export-batch-0000.zip

# Gemini: Google Takeout → My Activity → Gemini Apps → JSON
./scripts/upload_chat_export.sh gemini ~/Downloads/takeout-YYYYMMDD.zip

# ChatGPT: Settings → Data controls → Export data
./scripts/upload_chat_export.sh chatgpt ~/Downloads/chatgpt-export.zip
```

### 18e. Backfill

Trigger the scheduler job manually and run until `done: true`:

```bash
gcloud scheduler jobs run klaus-chat-export-ingest \
  --project=${PROJECT_ID} \
  --location=europe-west1
```

### 18f. Verify

1. **Pinecone:** vector count rises; metadata shows `source` in `{claude_ai, chatgpt, gemini}`
2. **Notion:** "Klaus AI Chat Imports" DB has rows (≈37 Gemini + 49+ Claude.ai + ChatGPT)
3. **Idempotency:** re-run scheduler — row count does NOT increase
4. **Agent:** ask Klaus `search_chat_history` about a topic only in a Gemini/ChatGPT chat — confirm it surfaces with correct `source`

### 18g. Monthly Export Reminder

Create a recurring monthly TickTick task: "Export ChatGPT + Claude + Gemini chats → run `upload_chat_export.sh`".

Note: Google Takeout supports scheduled automatic exports for Gemini (takeout.google.com → Schedule exports → Every 2 months).

---

## 19. Cloud Scheduler — Full Job Inventory

The following 9 Cloud Scheduler HTTP jobs invoke Klaus's Cloud Run cron endpoints. All
use OIDC bearer-token authentication via `${CLOUD_SCHEDULER_SA_EMAIL}`. All schedules
are in `Asia/Jerusalem`.

| # | Job ID                       | Schedule              | Endpoint                          | Phase          |
|---|------------------------------|-----------------------|-----------------------------------|----------------|
| 1 | klaus-morning-briefing       | `*/10 6-10 * * *`     | `/cron/morning-briefing-tick`     | Earlier        |
| 3 | klaus-heartbeat              | `0 * * * *`           | `/cron/heartbeat`                 | Earlier        |
| 4 | klaus-ingest-chats           | `0 4 * * *`           | `/cron/ingest-chats`              | 12             |
| 5 | klaus-ingest-chat-exports    | `30 4 * * *`          | `/cron/ingest-chat-exports`       | 13             |
| 7 | klaus-autonomous-tick        | `*/20 7-21 * * *`     | `/cron/autonomous-tick`           | 18             |
| 8 | klaus-weekly-training-review | `0 10 * * 0`          | `/cron/weekly-training-review`    | 20 (Shifu)     |
| 9 | klaus-strength-sync          | `0 5 * * *`           | `/cron/strength-sync`             | Hevy           |
| 10 | klaus-run-sync              | `15 5 * * *`          | `/cron/run-sync`                  | Run-detail     |
| 11 | klaus-nightly-backstop      | `0 1 * * *`           | `/cron/nightly-backstop`          | Nightly (WS2)  |

Nightly review (WS2): there is intentionally **no fixed-time send job** — the nightly
review fires organically from the iOS Sleep-Focus automation hitting `/trigger/nightly`
(shared-secret, see §22). `klaus-nightly-backstop` (01:00) is the safety net: it sends
the nightly review only if the Sleep-Focus trigger never fired that evening (idempotent),
so Klaus's journal/self_state never skip a day. The nightly flow (`_ensure_reflection`)
writes the private journal/self_state itself, so there is no separate reflect job.

**Retired:** `klaus-proactive-alerts` (`30 21 * * *`) and `klaus-reflect` (`0 22 * * *`).
The proactive weather/overload/recovery signals fold into the nightly review (one clean
night message); and the nightly review + 01:00 backstop now own the journal/self_state
write, making the standalone 22:00 reflect redundant (it also raced/overwrote the
nightly's journal on early-wind-down nights). Delete both jobs on deploy:
`gcloud scheduler jobs delete klaus-proactive-alerts --location="${REGION}"` and
`gcloud scheduler jobs delete klaus-reflect --location="${REGION}"`. The
`/cron/reflect` route is removed; `/cron/proactive-alerts` remains in code but unscheduled.

Note: There is no `klaus-training-checkin` scheduler job — the 21:30 training
check-in folded into the (now retired) `proactive-alerts` cron historically; that
content is part of the nightly review going forward.

Notes:
- Schedules in column 2 are illustrative — verify against the live `gcloud scheduler
  jobs list --project="${PROJECT_ID}" --location="${REGION}"` output before deploys.
- Klaus's heartbeat picks up each job-id's last-run timestamp and alerts on staleness
  per `core/heartbeat.py:_CRON_MAX_STALENESS_HOURS`. The `autonomous-tick` threshold
  is 1 hour (3 missed 20-minute ticks) — see Phase 18 Pitfall 5.
- **Ghost "failed Nx in a row" alerts after a fix.** `check_cron_health` raises the
  CRITICAL `cron:<job>:failing` signal purely on `heartbeat_runs/<job>.consecutive_failures
  >= 3`, and that counter only resets on a *successful* run. So after you deploy a fix
  for a low-frequency cron (e.g. `weekly-training-review`, Sundays only), the heartbeat
  keeps re-pinging the same message every 24h until the next scheduled run actually
  succeeds — the system can't tell you already fixed it. Clear the stale streak yourself:
  ```bash
  python scripts/reset_cron_streak.py --list                 # show streaks
  python scripts/reset_cron_streak.py weekly-training-review  # clear one (+ resolve incident)
  ```
  Safe: if the fix were wrong, the next real run re-raises the alert legitimately. This
  is intentionally manual — auto-resetting on deploy would silence a genuinely-still-broken
  weekly cron for up to 3 weeks while it re-accrues 3 failures.

### §14d. klaus-reflect (Phase 17)

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

### §14e. klaus-autonomous-tick (Phase 18)

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

### §19a. klaus-strength-sync (Hevy)

Daily Hevy pull — runs `core/strength_ingest.py:run_one_batch()`, which on first run
backfills full workout history over several ticks (each tick is page+time bounded) and
thereafter applies incremental `/v1/workouts/events`. Pull-only; no orchestrator/LLM/Telegram.

```bash
gcloud scheduler jobs create http klaus-strength-sync \
  --schedule="0 5 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${SERVICE_URL}/cron/strength-sync" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

First-run backfill: re-invoke until the response shows `done: true`
(`gcloud scheduler jobs run klaus-strength-sync --location="${REGION}"`), or just let the
daily ticks drain it. Requires the `HEVY_API_KEY` secret bound (see §20a).

### §19b. klaus-run-sync (Garmin per-run detail)

Daily Garmin run-detail pull — runs `core/run_ingest.py:run_one_batch()`. Lists recent
running activities (one cheap summary call) and fetches the per-run DETAIL
(`get_activity_details` + typed splits + HR-in-timezones) only for runs not yet in
`RunDetailStore`, bounded by `RUN_INGEST_MAX_ACTIVITIES` (8) and `RUN_INGEST_TIME_BUDGET_SEC`
(50). On first run it backfills `RUN_INGEST_BACKFILL_DAYS` (120) of history over several
ticks; thereafter it diffs a `RUN_INGEST_DELTA_DAYS` (14) window. Pull-only; no
orchestrator/LLM/Telegram. Uses the same `GARMIN_EMAIL`/`GARMIN_PASSWORD` creds as the
daily briefing (no new secret). Staggered to 05:15 — after strength-sync — to spread
Garmin login load, and kept a SEPARATE job so a Garmin rate-limit never fails the Hevy sync.

```bash
gcloud scheduler jobs create http klaus-run-sync \
  --schedule="15 5 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${SERVICE_URL}/cron/run-sync" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

First-run backfill: re-invoke until the response shows `done: true`
(`gcloud scheduler jobs run klaus-run-sync --location="${REGION}"`), or just let the daily
ticks drain it (a year of runs drains over a few weeks; recent runs are picked up on day one).

---

## 20. TICK_BRAIN_API_KEY (Groq) Secret

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
2. Add a new secret version:
   ```bash
   gcloud secrets versions add klaus-tick-brain-api-key \
     --data-file=- --project="${PROJECT_ID}"
   ```
   (paste new key, then Ctrl-D)
3. Redeploy Cloud Run (it reads `:latest` by default).
4. After confirming the new key works, disable the previous version:
   ```bash
   gcloud secrets versions disable <prev-version> --secret=klaus-tick-brain-api-key
   ```

Fallback behavior: if Groq is unavailable, `TickBrain.think()` falls back to Gemini
3 Flash automatically (TICK-02 / Phase 14). The autonomous tick continues to operate
on the fallback chain.

### §20a. HEVY_API_KEY (Hevy) Secret

The Hevy strength integration reads `HEVY_API_KEY` (a UUID from
https://hevy.com/settings?developer — **Hevy Pro only**), sent as the `api-key` header.
Used by `mcp_tools/hevy_tool.py` for the daily `/cron/strength-sync` pull and (indirectly)
the `get_strength_progress` / `get_training_context` brain tools.

```bash
# Mint the secret (paste the UUID, then Ctrl-D):
gcloud secrets create klaus-hevy-api-key --data-file=- --project="${PROJECT_ID}"

# Bind to Cloud Run:
gcloud run services update klaus-agent \
  --set-secrets=HEVY_API_KEY=klaus-hevy-api-key:latest \
  --region="${REGION}" --project="${PROJECT_ID}"
```

Lowercase `klaus-` naming per the GCP casing invariant. Rotation mirrors the tick-brain
procedure above (`gcloud secrets versions add klaus-hevy-api-key`). If the key is unset
or Hevy rejects it, `/cron/strength-sync` returns `{"ok": false, "error": ...}` and the
read tools degrade to `{"error": ...}` — no crash.

---

## 21. Firestore Composite Indexes

Klaus uses a small number of compound queries that require composite indexes:

| Collection  | Fields                       | Created by | Notes |
|-------------|------------------------------|------------|-------|
| followups   | `status` ASC, `due_at` ASC   | Phase 18   | Required by `FollowupStore.list_due()`. On first production query, Firestore returns a `FAILED_PRECONDITION` error with a link to create the index — follow it once, or run `gcloud firestore indexes composite create --collection-group=followups --field-config=field-path=status,order=ascending --field-config=field-path=due_at,order=ascending` ahead of first cron-tick deploy. |
| journal     | `__name__` DESC              | 2026-06-12 | Required by `JournalStore.get_recent()` (`order_by("__name__", DESCENDING)`). **Descending `__name__` order is NOT covered by Firestore's automatic indexes** — without this index every conversation turn logged a `FAILED_PRECONDITION` and silently dropped the journal digest from the brain's system prompt (regression shipped in 44443af, caught 2026-06-12). Create with: `gcloud firestore indexes composite create --project=klaus-agent --database=klaus-firestore --collection-group=journal --query-scope=COLLECTION --field-config=field-path=__name__,order=descending` |
| tasks       | `status` ASC, `due_date` ASC | Phase 27   | Required by `TaskStore.get_overdue()` + `TaskStore.get_summary()` (filters `status==active, due_date < today`). Without this index Firestore returns `FAILED_PRECONDITION` on the first overdue gather or summary call. Create: `gcloud firestore indexes composite create --project=klaus-agent --database=klaus-firestore --collection-group=tasks --query-scope=COLLECTION --field-config=field-path=status,order=ascending --field-config=field-path=due_date,order=ascending` |
| tasks       | `list_id` ASC, `status` ASC, `due_date` ASC | Phase 27 | Required by `TaskStore.list(list_id=...)` (filters `status==active, list_id==<id>`, optionally sorted by `due_date`). Without this index Firestore returns `FAILED_PRECONDITION` on the first list-scoped task query. Create: `gcloud firestore indexes composite create --project=klaus-agent --database=klaus-firestore --collection-group=tasks --query-scope=COLLECTION --field-config=field-path=list_id,order=ascending --field-config=field-path=status,order=ascending --field-config=field-path=due_date,order=ascending` |
| records (habit_completions/{date}/records) | `habit_id` ASC — **COLLECTION_GROUP scope** | Phase 28 | Required by `HabitStore.get_history()` + `HabitStore.delete()` which run a `collection_group("records")` equality query on `habit_id` (completions live under per-date subcollections). **Collection-group single-field equality is NOT covered by the automatic single-field index** (that only covers the parent collection scope) — without it every `get_history` throws `FAILED_PRECONDITION`, which `get_history` swallows into `streak 0` + an empty contribution grid for every habit (shipped Phase 28, caught 2026-07-02 on first real use). Create: `gcloud firestore indexes composite create --project=klaus-agent --database=klaus-firestore --collection-group=records --query-scope=COLLECTION_GROUP --field-config=field-path=habit_id,order=ascending` (or click the link in the `FAILED_PRECONDITION` log). |

The date-windowed read paths (`training_log`, `strength_sessions`,
`run_details` range/recent queries) use single-field range/equality filters
with an `order_by` on the **same** field, which are covered by Firestore's
automatic single-field indexes — no composite index needed for those.
**Gotcha:** that coverage does NOT extend to `order_by("__name__",
DESCENDING)` — any future "latest N docs by doc-ID" query needs its own
explicit index like the journal one above.

---

## 22. Push-driven endpoints

Endpoints driven by a verified external client (NOT Cloud Scheduler) — distinct
from §19 because the trigger lives off-platform and auth differs (shared-secret
bearer instead of OIDC JWT). Heartbeat staleness (`_CRON_MAX_STALENESS_HOURS`
in `core/heartbeat.py`) still monitors these via `_log_cron_run`.

| Endpoint | Driver | Auth | Phase |
|----------|--------|------|-------|
| `/cron/healthkit-sync` | iPhone Shortcut (Personal Automation) | shared-secret bearer (`HEALTHKIT_WEBHOOK_TOKEN`) | 19.1 |
| `/trigger/nightly` | iPhone Personal Automation ("When Sleep Focus turns On") | shared-secret bearer (`NIGHTLY_TRIGGER_TOKEN`) | Nightly (WS2) |

**iOS setup for `/trigger/nightly`:** Shortcuts → Automation → new Personal Automation →
"When [Sleep Focus] turns On" → Run a Shortcut that does a `Get Contents of URL`:
POST `${SERVICE_URL}/trigger/nightly`, header `Authorization: Bearer <NIGHTLY_TRIGGER_TOKEN>`.
A dedicated token (not the HealthKit one) so a leak of either credential can't be used to
drive the other endpoint (least privilege).

---

## 23. HEALTHKIT_WEBHOOK_TOKEN Secret

Static shared-secret bearer for `/cron/healthkit-sync` (§22). Mirrors §20
(TICK_BRAIN_API_KEY) shape.

**Secret name (lowercase per CLAUDE.md invariant):** `klaus-healthkit-webhook-token`

**Cloud Run binding:**

```
--set-secrets=HEALTHKIT_WEBHOOK_TOKEN=klaus-healthkit-webhook-token:latest
```

**Token mint (≥32-byte entropy per ASVS V2; RESEARCH.md Q5):**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Rotation (4 steps):**

1. `printf '%s' "$NEW_TOKEN" | gcloud secrets versions add klaus-healthkit-webhook-token --data-file=-`
2. `gcloud run services update klaus-agent --region=me-west1 --update-secrets=HEALTHKIT_WEBHOOK_TOKEN=klaus-healthkit-webhook-token:latest`
3. Paste new token into the iOS Shortcut's `Authorization: Bearer …` header.
4. `gcloud secrets versions disable klaus-healthkit-webhook-token --version=<OLD_N>`

**Kill-switch (emergency disable, no redeploy — D-08):**

```bash
gcloud secrets versions disable klaus-healthkit-webhook-token --version=<CURRENT_N>
```

All inbound HealthKit pushes fail auth immediately. Re-enable by adding a new version.

### NIGHTLY_TRIGGER_TOKEN Secret (WS2)

Static shared-secret bearer for `/trigger/nightly` (§22) — same shape as
HEALTHKIT_WEBHOOK_TOKEN, separate value (least privilege).

**Secret name:** `klaus-nightly-trigger-token`

**Cloud Run binding:** `--set-secrets=NIGHTLY_TRIGGER_TOKEN=klaus-nightly-trigger-token:latest`

**Mint / rotate / kill-switch:** identical commands to HEALTHKIT_WEBHOOK_TOKEN above,
substituting the secret name and pasting the new token into the iOS Sleep-Focus
Shortcut's `Authorization: Bearer …` header. The route refuses all requests (500) when
the env is unset, so a missing mount fails closed rather than open.

---

## 24. Phase Shifu (Phase 20) — Accountability Crons

### New Cloud Scheduler job

One new scheduler job is added in Phase 20 (Shifu): `klaus-weekly-training-review`.
Run `scripts/bootstrap_shifu_crons.sh` idempotently to create or update it.

```bash
# Prerequisites: export PROJECT_ID, SERVICE_URL, CLOUD_SCHEDULER_SA_EMAIL
# REGION defaults to me-west1 if not set.

bash scripts/bootstrap_shifu_crons.sh
```

The script is re-runnable (describe-or-create/update per D-25). It creates exactly
one job using the existing OIDC service account (same SA as all other cron jobs):

```bash
gcloud scheduler jobs create http "klaus-weekly-training-review" \
  --schedule="0 10 * * 0" \
  --time-zone="Asia/Jerusalem" \
  --uri="${SERVICE_URL}/cron/weekly-training-review" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

### Training check-in — no separate scheduler job (D-09)

The training check-in at 21:30 (checking whether today's expected session was
logged) folds into the existing `proactive-alerts` cron. No `klaus-training-checkin`
scheduler job is needed or registered.

### Webhook re-registration — REQUIRED after deploy (Pitfall 1)

**WARNING: If you do not run this step, all inline-keyboard button taps (callback_query
updates) will be silently dropped by Telegram. Users see the buttons but nothing happens.**

After deploying Phase 20, re-register the Telegram webhook to include `callback_query`
in `allowed_updates`. Currently the webhook was registered with `["message"]` only
(see initial setWebhook in this runbook). Phase 20 adds inline keyboard buttons whose
taps arrive as `callback_query` updates — Telegram will not deliver them unless
explicitly listed.

Run once after deploy (one-time operator step):

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  -d "url=${SERVICE_URL}/telegram-webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "allowed_updates=[\"message\",\"callback_query\"]"
```

Verify the update was accepted:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
```

The response `allowed_updates` field should show `["message","callback_query"]`.

Note: Telegram's allow-list on `callback_query` is for delivery only — the router
(`interfaces/_router.py`) still enforces the user allow-list on every callback,
so no additional spoofing surface is opened (T-20-17 accepted).

---

## 25. Cloud Tasks — Telegram update dispatch (full-CPU turns)

**Why this exists (2026-06-12 incident):** the Telegram webhook ACKs with 200
immediately and used to process the update in a Starlette BackgroundTask.
Background tasks run AFTER the response is sent, and with Cloud Run's default
request-based billing the container CPU is throttled to a sliver once no
request is in flight — an agent turn that should take ~1 minute took 18
(including a 6.5-minute stall on a single worker-LLM call). `--no-cpu-throttling`
would fix it but bills the instance ~24/7 (~$30+/month at 1 vCPU).

**Architecture:** webhook → `core/task_dispatch.enqueue_update(raw_update_json)`
→ Cloud Tasks queue `klaus-updates` (me-central1 — Cloud Tasks is NOT offered
in me-west1) → OIDC-authenticated POST back to `/internal/process-update` →
the agent turn runs INSIDE that tracked request with full CPU. If enqueueing
fails for any reason the webhook falls back to the old in-process background
path, so updates are never dropped (slow beats dropped).

One-time setup:

```bash
gcloud services enable cloudtasks.googleapis.com --project=klaus-agent

gcloud tasks queues create klaus-updates \
  --location=me-central1 --project=klaus-agent \
  --max-attempts=2 --min-backoff=5s

# Runtime SA must be able to enqueue...
gcloud tasks queues add-iam-policy-binding klaus-updates \
  --location=me-central1 --project=klaus-agent \
  --member="serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com" \
  --role="roles/cloudtasks.enqueuer"

# ...and to mint OIDC tokens as the scheduler SA (which already holds
# run.invoker on the service — same identity the crons use).
gcloud iam service-accounts add-iam-policy-binding \
  klaus-heartbeat@klaus-agent.iam.gserviceaccount.com \
  --project=klaus-agent \
  --member="serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

Env vars (set by deploy.yml): `CLOUD_TASKS_QUEUE=klaus-updates`,
`CLOUD_TASKS_LOCATION=me-central1`. Unsetting `CLOUD_TASKS_QUEUE` disables
dispatch entirely (clean rollback to the background path).

Timeout chain (each layer must exceed the next):
Cloud Run `--timeout 600` > task `dispatch_deadline` 540s > per-LLM-call
timeout `LLM_TIMEOUT_SECONDS` (default 120s, `core/llm_client.py`).

## 26. TickTick Retirement (Phase 27, v5.0)

Phase 27 (D-09) replaced TickTick with the native `TaskStore` (Klaus Hub). The
agent tool (`task_*`), the autonomous overdue gather, and the morning-briefing /
nightly-review / reflection crons all read the native store now. `mcp_tools/
ticktick_tool.py` and `mcp_tools/ticktick_auth.py` were **deleted**.

Migration was **manual** (D-08): no importer or reconciliation report — the open
TickTick tasks were re-created by hand in the hub during UAT before the code was
removed. Native tasks live in Firestore collections `tasks` / `task_lists` with
the two composite indexes from §21.

**Operator cleanup — do these AFTER this cutover is deployed (Open Question 2):**

1. **Cancel the TickTick subscription** (developer app + account). Do this first.
2. **After** the subscription is cancelled, remove the four now-unused secrets
   from the `klaus-agent` Cloud Run config and Secret Manager:

   ```bash
   # 1) Drop them from the running service's env/secret bindings (deploy.yml no
   #    longer references them; this clears any lingering binding):
   gcloud run services update klaus-agent --region me-west1 --project klaus-agent \
     --remove-secrets=TICKTICK_ACCESS_TOKEN,TICKTICK_REFRESH_TOKEN,TICKTICK_CLIENT_ID,TICKTICK_CLIENT_SECRET

   # 2) Delete the secrets themselves:
   for s in TICKTICK_ACCESS_TOKEN TICKTICK_REFRESH_TOKEN TICKTICK_CLIENT_ID TICKTICK_CLIENT_SECRET; do
     gcloud secrets delete "$s" --project=klaus-agent --quiet
   done
   ```

   (Run step 1 only for secrets actually bound to the service; harmless if a name
   isn't bound. Verify current bindings first with
   `gcloud run services describe klaus-agent --region me-west1 --format=yaml | grep -i ticktick`.)

The standalone `scripts/ticktick_oauth_bootstrap.py` is now dead but left in
place as historical reference; it imports nothing from the deleted modules.
