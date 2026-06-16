# Phase 26 — Klaus Hub: Going-Live Setup Checklist

Everything required to take the hub from "complete in code" to "usable on your
iPhone." Do these after `/gsd:secure-phase 26`. None of the code work remains —
this is configuration + deploy.

**Live facts:** Cloud Run service `klaus-agent` · region `me-west1` · project
`klaus-agent` · Firestore `klaus-firestore` · deploys via GitHub Actions
(`.github/workflows/deploy.yml`, push to `main`). Secrets via Secret Manager
(`--set-secrets`); non-sensitive config via `--set-env-vars`.

---

## 1. Create the Google OAuth client (one-time)

Google Cloud Console → **APIs & Services → Credentials → Create Credentials →
OAuth client ID → Web application**.

- **Authorized JavaScript origins:** your Cloud Run URL
  (`https://klaus-agent-<hash>-<region>.a.run.app`). Add `http://localhost:5173`
  too if you want to run the hub locally against the dev server.
- No redirect URI is needed — the hub uses Google Identity Services (GIS) one-tap /
  token flow, not the redirect flow.
- Copy the **Client ID** (looks like `…apps.googleusercontent.com`). This single
  value is used in **two** places below (backend verify + frontend build). It is
  **public**, not a secret.

---

## 2. Backend env / secrets (Cloud Run)

| Variable | Where | Value | Required? |
|----------|-------|-------|-----------|
| `HUB_SESSION_SECRET` | Secret Manager → `--set-secrets` | random ≥32 bytes (signs the session cookie; the auth layer **refuses all requests** if unset) | **Required** |
| `GOOGLE_OAUTH_CLIENT_ID` | `--set-env-vars` (public) | the Client ID from step 1 (backend verifies the GIS token's audience against it) | **Required** |
| `HUB_ALLOWED_EMAIL` | `--set-env-vars` | your Google email | Optional — defaults to `amit.grupper@gmail.com` |

Create the session secret:
```bash
gcloud secrets create klaus-hub-session-secret --replication-policy=automatic   # one-time
python3 -c "import secrets; print(secrets.token_urlsafe(48))" \
  | gcloud secrets versions add klaus-hub-session-secret --data-file=-
```
Then wire it into the deploy manifest / workflow alongside the existing secrets:
```
--set-secrets=HUB_SESSION_SECRET=klaus-hub-session-secret:latest
--set-env-vars=GOOGLE_OAUTH_CLIENT_ID=<client-id>.apps.googleusercontent.com
```

`itsdangerous` is already pinned in `requirements.txt` — no extra install step.

---

## 3. Frontend build-time client ID (do not skip — sign-in fails silently otherwise)

The frontend reads `import.meta.env.VITE_GOOGLE_CLIENT_ID` **at build time** and
bakes it into the bundle. The multi-stage `Dockerfile` now accepts it as a build
arg (`ARG VITE_GOOGLE_CLIENT_ID`), but the **deploy workflow must pass it** to the
docker build:

- If the deploy builds with `docker build` / `gcloud builds submit`, add:
  `--build-arg VITE_GOOGLE_CLIENT_ID=<same client-id from step 1>`
- Because it's public, store it as a **GitHub repository variable** (not a secret)
  and reference it in `.github/workflows/deploy.yml`'s build step.

> Symptom if missed: the page loads, but the Google button does nothing / GIS
> errors with an invalid client — because the bundle shipped an empty `client_id`.

---

## 4. Cloud Tasks — already configured (no action)

The hub chat reuses the **existing** Cloud Tasks setup that the Telegram full-CPU
path uses (`CLOUD_TASKS_QUEUE`, `CLOUD_TASKS_LOCATION=me-central1`, `CLOUD_RUN_URL`,
`CLOUD_SCHEDULER_SA_EMAIL`). It only adds a new target route,
`/internal/process-hub-message`, on the same queue + OIDC service account. Since
Telegram replies already work, nothing new is needed here.

---

## 5. telegram_user_id bridge — optional

The hub keys the shared conversation on `telegram_user_id`. It defaults to `None`,
and `_resolve_hub_user_id` **falls back to the first id in
`TELEGRAM_ALLOWED_USER_IDS`** — which is already your Telegram id. So for your
single-account setup the hub↔Telegram conversation is bridged **without any
action**. Only set it explicitly if your hub identity ever diverges:
```python
# one-off, against the live Firestore:
from memory.firestore_db import UserProfileStore
UserProfileStore(project_id="klaus-agent", database="klaus-firestore").update(
    {"telegram_user_id": <your_telegram_user_id>}
)
```

---

## 6. Deploy

Push to `main` (or trigger the deploy workflow) once steps 2–3 are wired. Confirm
the multi-stage build runs the Node `frontend-builder` stage and that the runtime
CMD keeps **`--workers 1`** (ConversationManager is an in-process singleton —
non-negotiable).

---

## 7. Post-deploy smoke + UAT

1. Open the Cloud Run URL in a browser → Google sign-in → lands on the hub.
2. `curl https://<url>/api/today` with no cookie → **401** (auth boundary holds).
3. `curl https://<url>/health` → **200** (existing routes survive the SPA mount).
4. Send a hub chat message → reply arrives via polling → confirm the **same
   exchange appears in Telegram** (shared conversation).
5. Then walk the 5 device/live items in **`26-HUMAN-UAT.md`** (`/gsd:verify-work 26`)
   on a physical iPhone: PWA install banner + Add-to-Home-Screen, home-screen icon,
   responsive breakpoints, and live traffic-aware leave-by chips.

---

*Generated 2026-06-16 at the close of Phase 26. Sources: `interfaces/hub_auth.py`,
`interfaces/web_server.py`, `core/task_dispatch.py`, `frontend/src/components/auth/SignInPage.tsx`,
`Dockerfile`, `docs/DEPLOYMENT.md`.*
