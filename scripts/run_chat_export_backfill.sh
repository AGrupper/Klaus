#!/usr/bin/env bash
# scripts/run_chat_export_backfill.sh
# Autonomous Phase 13 chat-export backfill driver.
# Polls Firestore state, triggers the Cloud Scheduler ingest job in a loop,
# and exits 0 once every GCS zip blob appears in completed_blobs.
#
# Usage:
#   ./scripts/run_chat_export_backfill.sh
#
# Requires:
#   - gcloud CLI authenticated (application-default credentials or service account)
#   - python3 (for Firestore JSON parsing)
#   - curl

set -euo pipefail

# ---- Constants ----
BUCKET="klaus-chat-logs-klaus-agent"
LOCATION="europe-west1"
WAIT_SECONDS=290
MAX_ITERATIONS=20
STALL_LIMIT=3

usage() {
    echo "Usage: $0"
    echo "  Drives Phase 13 chat-export backfill autonomously."
    echo "  Exits 0 when every GCS zip blob is in Firestore completed_blobs."
    exit 1
}

if [[ $# -ne 0 ]]; then
    usage
fi

# ---- Resolve GCP config dynamically ----
echo "[init] Resolving GCP config..."

PROJECT="$(gcloud projects list --format='value(projectId)' | grep '^klaus-' | head -1)"
if [[ -z "${PROJECT}" ]]; then
    echo "Error: could not find a project matching 'klaus-*' in gcloud projects list"
    exit 1
fi
echo "[init] PROJECT=${PROJECT}"

DB="$(gcloud firestore databases list --project="${PROJECT}" --format='value(name)' | awk -F'/' '{print $NF}' | head -1)"
if [[ -z "${DB}" ]]; then
    echo "Error: could not find a Firestore database in project ${PROJECT}"
    exit 1
fi
echo "[init] DB=${DB}"

JOB="$(gcloud scheduler jobs list --location="${LOCATION}" --project="${PROJECT}" --format='value(name)' | grep 'chat-export-ingest' | awk -F'/' '{print $NF}' | head -1)"
if [[ -z "${JOB}" ]]; then
    echo "Error: no Cloud Scheduler job matching 'chat-export-ingest' found in ${LOCATION}"
    exit 1
fi
echo "[init] JOB=${JOB}"

# ---- Count total GCS zip blobs ----
echo "[init] Counting zip blobs under gs://${BUCKET}/chat-exports/..."
TOTAL_BLOBS="$(gcloud storage ls --recursive "gs://${BUCKET}/chat-exports/" 2>/dev/null | grep -c '\.zip$' || true)"
if [[ "${TOTAL_BLOBS}" -eq 0 ]]; then
    echo "Error: no .zip blobs found under gs://${BUCKET}/chat-exports/"
    exit 1
fi
echo "[init] TOTAL_BLOBS=${TOTAL_BLOBS}"

# ---- Firestore state reader ----
# Emits a single line: <processed_conversations_count> <completed_blobs_count>
read_firestore_state() {
    local token
    token="$(gcloud auth print-access-token)"
    local url="https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/${DB}/documents/chat_export_ingest/state"
    curl -s -H "Authorization: Bearer ${token}" "${url}" | python3 -c "
import sys, json
doc = json.load(sys.stdin)
fields = doc.get('fields', {})
conversations = fields.get('conversations', {}).get('mapValue', {}).get('fields', {})
completed_blobs = fields.get('completed_blobs', {}).get('mapValue', {}).get('fields', {})
print(len(conversations), len(completed_blobs))
"
}

# ---- Diagnostics helper ----
print_cloudrun_logs() {
    echo "[diag] Last 20 Cloud Run log lines for service 'klaus-agent':"
    gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=klaus-agent" \
        --limit=20 --order=desc --project="${PROJECT}" \
        --format='value(textPayload)' 2>/dev/null || true
}

# ---- Main loop ----
prev_processed="-1"
stall_count=0
iteration=0

echo ""
echo "Starting backfill loop."
echo "  TOTAL_BLOBS   = ${TOTAL_BLOBS}"
echo "  MAX_ITERATIONS= ${MAX_ITERATIONS}"
echo "  WAIT_SECONDS  = ${WAIT_SECONDS}"
echo "--------------------------------------------------------------------"

while [[ ${iteration} -lt ${MAX_ITERATIONS} ]]; do
    iteration=$(( iteration + 1 ))
    timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    # Read current Firestore state
    state_line="$(read_firestore_state)"
    processed_count="$(echo "${state_line}" | awk '{print $1}')"
    completed_blobs_count="$(echo "${state_line}" | awk '{print $2}')"

    echo "[${timestamp}] iter=${iteration}/${MAX_ITERATIONS}  convs=${processed_count}  completed_blobs=${completed_blobs_count}/${TOTAL_BLOBS}"

    # Done check — every blob name is in completed_blobs
    if [[ "${completed_blobs_count}" -ge "${TOTAL_BLOBS}" ]]; then
        echo ""
        echo "======================================================================"
        echo "  Backfill complete!"
        echo "  Processed conversations : ${processed_count}"
        echo "  Completed blobs         : ${completed_blobs_count}/${TOTAL_BLOBS}"
        echo "======================================================================"
        exit 0
    fi

    # Stall guard — bail if no new conversations processed for STALL_LIMIT iterations
    if [[ "${processed_count}" -eq "${prev_processed}" && "${prev_processed}" -ne "-1" ]]; then
        stall_count=$(( stall_count + 1 ))
        echo "[warn] No progress since last iteration (stall ${stall_count}/${STALL_LIMIT})"
        if [[ ${stall_count} -ge ${STALL_LIMIT} ]]; then
            echo "[error] Stall limit reached — no new conversations after ${STALL_LIMIT} consecutive iterations."
            print_cloudrun_logs
            exit 1
        fi
    else
        stall_count=0
    fi
    prev_processed="${processed_count}"

    # Trigger next batch via Cloud Scheduler
    echo "[trigger] gcloud scheduler jobs run ${JOB} --location=${LOCATION}"
    gcloud scheduler jobs run "${JOB}" --location="${LOCATION}" --project="${PROJECT}"

    echo "[wait] Sleeping ${WAIT_SECONDS}s for batch to complete..."
    sleep "${WAIT_SECONDS}"
done

echo ""
echo "[error] Hit MAX_ITERATIONS=${MAX_ITERATIONS} without finishing."
echo "        completed_blobs=${completed_blobs_count}/${TOTAL_BLOBS}"
exit 1
