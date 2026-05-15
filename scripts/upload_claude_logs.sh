#!/usr/bin/env bash
# Upload Claude Code session logs to GCS for Klaus ingestion.
#
# Usage: ./scripts/upload_claude_logs.sh
#
# Prerequisites:
#   1. gcloud SDK installed (https://cloud.google.com/sdk/docs/install)
#   2. Service account key at ~/.config/klaus/log-uploader-key.json
#      (see docs/DEPLOYMENT.md §17 for IAM setup)
#   3. CHAT_LOGS_BUCKET env var set, OR hardcode BUCKET below.
#
# Scheduling: add to crontab for hourly runs:
#   0 * * * * CHAT_LOGS_BUCKET=your-bucket /path/to/Klaus/scripts/upload_claude_logs.sh >> /tmp/claude-log-upload.log 2>&1

set -euo pipefail

MACHINE_ID="mac"
BUCKET="${CHAT_LOGS_BUCKET:-}"
KEY_FILE="${HOME}/.config/klaus/log-uploader-key.json"
SOURCE_DIR="${HOME}/.claude/projects"

if [[ -z "$BUCKET" ]]; then
  echo "ERROR: CHAT_LOGS_BUCKET is not set. Export it or edit this script." >&2
  exit 1
fi

if [[ ! -f "$KEY_FILE" ]]; then
  echo "ERROR: Service account key not found at ${KEY_FILE}" >&2
  echo "See docs/DEPLOYMENT.md §17 for setup instructions." >&2
  exit 1
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "ERROR: Claude Code projects directory not found at ${SOURCE_DIR}" >&2
  exit 1
fi

DEST="gs://${BUCKET}/claude-code/${MACHINE_ID}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Uploading Claude Code logs to ${DEST} ..."

GOOGLE_APPLICATION_CREDENTIALS="${KEY_FILE}" \
  gcloud storage rsync \
    --recursive \
    --no-delete-unmatched-destination-objects \
    "${SOURCE_DIR}" \
    "${DEST}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Upload complete."
