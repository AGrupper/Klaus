#!/usr/bin/env bash
# bootstrap_shifu_crons.sh — Phase 20 (Shifu)
# Re-runnable: describe → update if exists, create if absent.
# Creates: klaus-weekly-training-review
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-me-west1}"
SERVICE_URL="${SERVICE_URL:?set SERVICE_URL}"
CLOUD_SCHEDULER_SA_EMAIL="${CLOUD_SCHEDULER_SA_EMAIL:?set CLOUD_SCHEDULER_SA_EMAIL}"

if gcloud scheduler jobs describe "klaus-weekly-training-review" \
     --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud scheduler jobs update http "klaus-weekly-training-review" \
    --schedule="0 10 * * 0" \
    --time-zone="Asia/Jerusalem" \
    --uri="${SERVICE_URL}/cron/weekly-training-review" \
    --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
else
  gcloud scheduler jobs create http "klaus-weekly-training-review" \
    --schedule="0 10 * * 0" \
    --time-zone="Asia/Jerusalem" \
    --uri="${SERVICE_URL}/cron/weekly-training-review" \
    --http-method=POST \
    --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
fi
echo "Done."
