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

To have the poller start on login and restart after crashes:

1. Copy the template plist to your LaunchAgents folder:
   ```bash
   cp local_mac/launchd/com.klaus.thingspoller.plist.template \
      ~/Library/LaunchAgents/com.klaus.thingspoller.plist
   ```

2. Open the copied file and replace every `/PATH/TO/...` placeholder with
   your actual absolute paths (project root, venv python, service-account JSON).

3. Load the agent:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.klaus.thingspoller.plist
   ```

4. Verify it's running:
   ```bash
   launchctl list | grep klaus
   ```

5. View logs:
   ```bash
   tail -f /tmp/klaus-thingspoller.out.log
   tail -f /tmp/klaus-thingspoller.err.log
   ```

6. To stop / unload:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.klaus.thingspoller.plist
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
