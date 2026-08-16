# Klaus Capability Manifest

Klaus is a subscription-first personal operating system. Claude Project
handles conversation and reasoning through scoped MCP; Cloud Run remains the
authorization, data, and action boundary.

## Runtime

- Calendar-only Google OAuth
- Things, Garmin, Hevy, HealthKit, weather, Postgres, and Pinecone
- Notion is reached through Claude's own connector, not through Klaus
- Departure windows use a configured travel time, not a live traffic API
- `gemini-embedding-2` is used only for embeddings
- Hub dashboards, reviews, settings, authentication, and Web Push

## Identity

All persistent namespaces use `KLAUS_USER_ID`.
