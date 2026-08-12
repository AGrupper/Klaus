# Subscription-First Architecture

Claude Project is the conversational surface. Cloud Run exposes scoped MCP,
OAuth, deterministic notifications, routine coordination, Web Push, and Hub
APIs. Firestore, Postgres, Things, and Pinecone remain authoritative stores.

The only AI Studio capability in the deployed backend is the embedding model.
All old user-facing processing has been removed; historical data remains
readable under the unchanged `KLAUS_USER_ID` namespace.
