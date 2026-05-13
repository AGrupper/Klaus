# config/

This directory holds Google Cloud OAuth credentials and the cached refresh
token. **Everything here is gitignored** except this README.

## Files you need to drop in here

### `credentials.json` (you provide)
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Pick (or create) the project referenced by `GCP_PROJECT_ID` in your `.env`.
3. Configure the **OAuth consent screen** with **User Type = Internal**
   (this is what makes refresh tokens persist indefinitely — see
   `docs/TECHNICAL_PLAN.md` §3.1).
4. Enable the **Gmail API** and **Google Calendar API**.
5. Create an OAuth 2.0 Client ID of type **Desktop app**.
6. Download the JSON and save it here as `credentials.json`.

### `token.json` (auto-generated)
Created automatically the first time you run `python -m core.auth_google`.
It stores the long-lived refresh token. Delete it to force re-auth.
