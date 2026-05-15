# Upload Claude Code session logs to GCS for Klaus ingestion.
#
# Usage: .\scripts\upload_claude_logs.ps1
#
# Prerequisites:
#   1. gcloud SDK installed (https://cloud.google.com/sdk/docs/install)
#   2. Service account key at $HOME\.config\klaus\log-uploader-key.json
#      (see docs/DEPLOYMENT.md §17 for IAM setup)
#   3. $env:CHAT_LOGS_BUCKET set, OR edit $Bucket below.
#
# Scheduling: use Task Scheduler with:
#   Action: powershell.exe -File C:\path\to\Klaus\scripts\upload_claude_logs.ps1
#   Trigger: Daily, repeat every 1 hour

param()

$MachineId = "pc"
$Bucket    = $env:CHAT_LOGS_BUCKET
$KeyFile   = Join-Path $HOME ".config\klaus\log-uploader-key.json"
$SourceDir = Join-Path $HOME ".claude\projects"

if (-not $Bucket) {
    Write-Error "CHAT_LOGS_BUCKET is not set. Set the env var or edit this script."
    exit 1
}

if (-not (Test-Path $KeyFile)) {
    Write-Error "Service account key not found at $KeyFile`nSee docs/DEPLOYMENT.md §17 for setup."
    exit 1
}

if (-not (Test-Path $SourceDir)) {
    Write-Error "Claude Code projects directory not found at $SourceDir"
    exit 1
}

$Dest = "gs://$Bucket/claude-code/$MachineId"
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Write-Host "[$Timestamp] Uploading Claude Code logs to $Dest ..."

$env:GOOGLE_APPLICATION_CREDENTIALS = $KeyFile
gcloud storage rsync `
    --recursive `
    --no-delete-unmatched-destination-objects `
    $SourceDir `
    $Dest

if ($LASTEXITCODE -ne 0) {
    Write-Error "gcloud storage rsync failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Write-Host "[$Timestamp] Upload complete."
