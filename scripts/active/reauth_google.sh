#!/usr/bin/env bash
# Re-run the Google OAuth consent flow and push the new token to Secret Manager.
#
# Needed whenever Cloud Run logs show:
#   google.auth.exceptions.RefreshError: invalid_grant: Token has been expired or revoked.
#
# Run this only after the user revokes access, an admin policy invalidates the
# grant, or Google returns invalid_grant. Ordinary access-token renewal is
# automatic and stays in Cloud Run memory; it never rotates this secret.
set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT_ID="${GCP_PROJECT_ID:-klaus-agent}"
SECRET_NAME="klaus-google-oauth-token"
TOKEN_PATH="config/token.json"

if [ -f "$TOKEN_PATH" ]; then
  BACKUP_PATH="${TOKEN_PATH}.revoked-$(date +%Y-%m-%d).bak"
  mv "$TOKEN_PATH" "$BACKUP_PATH"
  echo "Backed up stale token to ${BACKUP_PATH}"
fi

echo "Opening browser for Google consent (sign in as amit.grupper@gmail.com)..."
source .venv/bin/activate
python -m core.auth_google

echo "Pushing new token to Secret Manager (${SECRET_NAME})..."
gcloud secrets versions add "$SECRET_NAME" \
  --data-file="./${TOKEN_PATH}" \
  --project="$PROJECT_ID"

# Keep the latest working token plus one rollback. The script prints the plan
# by default and applies only because the exact secret name is repeated as a
# confirmation. Newly-disabled versions cannot be destroyed in this same run.
python scripts/manage_secret_versions.py \
  --project "$PROJECT_ID" \
  --secret "$SECRET_NAME" \
  --destroy-grace-days 7 \
  --apply \
  --confirm-secret "$SECRET_NAME"

echo "Done. Deploy or restart Cloud Run so each process loads the new grant."
