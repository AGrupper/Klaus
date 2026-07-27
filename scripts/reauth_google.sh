#!/usr/bin/env bash
# Re-run the Google OAuth consent flow and push the new token to Secret Manager.
#
# Needed whenever Cloud Run logs show:
#   google.auth.exceptions.RefreshError: invalid_grant: Token has been expired or revoked.
#
# Google revokes the refresh token whenever the account password changes, because
# the grant includes Gmail scopes — this is a Google security policy, not a Klaus
# bug, and it cannot be disabled. See docs/DEPLOYMENT.md section 7.
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

echo "Done. Klaus's next Calendar/Gmail call will pick up the new token."
