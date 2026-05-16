#!/usr/bin/env bash
# scripts/upload_chat_export.sh
# Upload a chat export zip to GCS so the ingest pipeline can process it.
#
# Usage:
#   ./scripts/upload_chat_export.sh <chatgpt|claude_ai|gemini> <path-to-zip>
#
# Requires:
#   - gcloud CLI authenticated (application-default credentials or service account)
#   - CHAT_LOGS_BUCKET env var set (or exported in your shell profile)
#   - The zip file to exist at the given path

set -euo pipefail

VALID_PROVIDERS="chatgpt claude_ai gemini"

usage() {
    echo "Usage: $0 <provider> <zip-file>"
    echo "  provider: one of chatgpt, claude_ai, gemini"
    echo "  zip-file: local path to the export zip"
    exit 1
}

# ---- Argument validation ----
if [[ $# -ne 2 ]]; then
    usage
fi

PROVIDER="$1"
ZIP_PATH="$2"

if ! echo "$VALID_PROVIDERS" | grep -qw "$PROVIDER"; then
    echo "Error: unknown provider '$PROVIDER'. Must be one of: $VALID_PROVIDERS"
    usage
fi

if [[ ! -f "$ZIP_PATH" ]]; then
    echo "Error: file not found: $ZIP_PATH"
    exit 1
fi

# ---- Resolve bucket ----
if [[ -z "${CHAT_LOGS_BUCKET:-}" ]]; then
    # Try to load from .env in the repo root
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    ENV_FILE="$SCRIPT_DIR/../.env"
    if [[ -f "$ENV_FILE" ]]; then
        # shellcheck disable=SC1090
        source <(grep -E '^CHAT_LOGS_BUCKET=' "$ENV_FILE" | head -1)
    fi
fi

if [[ -z "${CHAT_LOGS_BUCKET:-}" ]]; then
    echo "Error: CHAT_LOGS_BUCKET is not set. Export it or add it to .env"
    exit 1
fi

BASENAME="$(basename "$ZIP_PATH")"
DEST="gs://${CHAT_LOGS_BUCKET}/chat-exports/${PROVIDER}/${BASENAME}"

echo "Uploading $ZIP_PATH → $DEST"
gcloud storage cp "$ZIP_PATH" "$DEST"
echo "Done. Trigger /cron/ingest-chat-exports (or wait for the daily 04:30 Asia/Jerusalem run)."
