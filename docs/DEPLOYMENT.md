# Deployment Runbook

Deploy the Cloud Run service from `.github/workflows/deploy.yml`. The runtime
requires `KLAUS_USER_ID`, Firestore, Pinecone, and the embedding credential;
`KLAUS_USER_ID` must retain the established numeric namespace value.

The only Google OAuth scope is Calendar. Cached credentials that contain any
other scope are discarded and require explicit re-consent.

The retained public surfaces are the Hub, scoped MCP endpoints, routine
callbacks, deterministic alerts, and Web Push. Run
`python scripts/check_claude_first_runtime.py` before deployment.
