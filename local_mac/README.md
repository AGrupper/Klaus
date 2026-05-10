# Klaus — Local Mac Poller

The `things_poller.py` script runs on your MacBook Air M4 and bridges the
cloud agent to Things 3. The cloud agent (running on Cloud Run) writes tasks
to a Firestore queue; this script polls that queue and injects each task into
Things 3 via AppleScript.

---

## Prerequisites

- macOS with Things 3 installed and at least one launch (so Things 3 has been
  granted Automation access at some point).
- Python 3.11+ and the project dependencies installed (`pip install -r requirements.txt`).
- The Klaus project cloned on this Mac.

---

## 1. Service-account setup (one-time)

The poller authenticates to Firestore with a **dedicated service account** —
it does NOT reuse the OAuth `credentials.json` / `token.json` from the cloud
side. This keeps Firestore auth separate from Gmail/Calendar scopes.

1. Go to the [GCP Console → IAM → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
   for your `GCP_PROJECT_ID` project.
2. Create a new service account (e.g. `things-poller@<project>.iam.gserviceaccount.com`).
3. Grant it the role **Datastore User** (`roles/datastore.user`).
4. Create a JSON key and download it to `config/firestore-service-account.json`
   inside the project directory.
5. Set the env var (or add it to `.env`):
   ```
   GOOGLE_APPLICATION_CREDENTIALS=./config/firestore-service-account.json
   ```

> **Note:** `config/firestore-service-account.json` is git-ignored. Never commit credentials.

---

## 2. Environment variables

Copy `.env.example` to `.env` if you haven't already, then ensure these are set:

```
GCP_PROJECT_ID=your_gcp_project_id
GOOGLE_APPLICATION_CREDENTIALS=./config/firestore-service-account.json
FIRESTORE_COLLECTION_THINGS_QUEUE=things_queue
THINGS_POLLER_INTERVAL_SECONDS=30
```

---

## 3. Firestore composite index (first-run only)

The poller queries Firestore on `status == "pending"` ordered by `created_at`.
This requires a **composite index**. The first time `fetch_pending` runs without
the index, Firestore returns an error whose message contains a direct console URL.
Click that URL once to auto-create the index, then re-run the poller.

---

## 4. Running interactively

```bash
# From the Klaus project root:

# Drain all pending tasks once, then exit — good for testing
python -m local_mac.things_poller --once

# Long-running daemon (Ctrl-C to stop)
python -m local_mac.things_poller
```

**First run:** macOS will prompt you to grant Terminal (or your Python binary)
Automation access to control Things 3. Click **OK**. This prompt appears only once.

---

## 5. Running automatically with launchd

The tracked plist is at `local_mac/launchd/com.amitgrupper.klaus.things-poller.plist`.
It is already configured for this machine and relies on `.env` in the project root for
all GCP and Firestore credentials (loaded via `load_dotenv(override=True)` at daemon start).

### Install (one-time)

```bash
# Copy plist to LaunchAgents
cp /Users/amitgrupper/Desktop/Klaus/local_mac/launchd/com.amitgrupper.klaus.things-poller.plist \
   ~/Library/LaunchAgents/com.amitgrupper.klaus.things-poller.plist

# Load it into launchd (modern syntax)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.amitgrupper.klaus.things-poller.plist
```

The first time `osascript` runs, macOS will prompt for Automation permission to control
Things 3. Approve it in the dialog.

### Verify

```bash
# Should print a line with com.amitgrupper.klaus.things-poller and a PID
launchctl list | grep klaus

# Watch live logs
tail -f ~/Library/Logs/klaus-things-poller.log
```

You should see: `Things poller starting (poll_interval=30s)` within a few seconds.

### Stop / unload

```bash
launchctl bootout gui/$(id -u)/com.amitgrupper.klaus.things-poller
```

### Update plist after code changes

If you edit the plist, copy it to `~/Library/LaunchAgents/` again, then:
```bash
launchctl bootout gui/$(id -u)/com.amitgrupper.klaus.things-poller
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.amitgrupper.klaus.things-poller.plist
```

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `GCP_PROJECT_ID is not set` | Add it to `.env` or the launchd plist `EnvironmentVariables`. |
| `GoogleAPICallError` with a console URL on first run | Click the URL to create the Firestore composite index. |
| macOS blocks AppleScript | System Settings → Privacy & Security → Automation → allow Terminal (or your python). |
| Task appears twice in Things 3 | The `mark_consumed` Firestore update failed after injection. Check `err.log` for the error; manually update the doc status in the Firestore console. |
| `FileNotFoundError: osascript` | You're running the poller on a non-macOS host. It must run on your Mac. |
