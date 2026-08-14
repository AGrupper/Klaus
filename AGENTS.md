# Klaus

Klaus is a Cloud Run personal operating system. Claude Project owns
conversation and reasoning; this repository owns MCP authorization, data,
actions, Hub APIs, Remote Routine coordination, and Web Push.

Before changing code, read `docs/PRD.md`, `docs/TECHNICAL_PLAN.md`,
`docs/USER.md`, `docs/AGENT.md`, `docs/CODING_STANDARDS.md`,
`docs/SELF.md`, and `docs/DEPLOYMENT.md`.

## Invariants

- Use `KLAUS_USER_ID` for the canonical persistent namespace.
- Google OAuth requests Calendar scope only; stale broader grants require consent.
- Gemini is permitted solely through the embedding credential and embedding model.
- Preserve historical Firestore documents, vectors, logs, and reviews.
- Do not deploy or mutate production without explicit authorization.
