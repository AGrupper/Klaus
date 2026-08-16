# Klaus Architecture

Klaus is a personal operating system for one person. It is split across two
runtimes that own strictly different things.

| | Claude Project | Cloud Run (this repository) |
|---|---|---|
| Owns | conversation, reasoning, judgement, prose | data, authorization, deterministic rules, scheduling |
| Holds | the skills in `claude/skills/` | Firestore, Postgres, Pinecone, Things, Google Calendar |
| Fails by | being unavailable or slow | returning stale or empty data |

**The dividing line:** Python returns normalized facts and makes deterministic
decisions. Claude decides what matters and writes the sentences. When you are
unsure which side a piece of logic belongs on, ask whether it would still be
correct if written down as a rule. Buffer arithmetic and adherence
reconciliation are rules. "Which of these three things should he hear about
first" is not.

Nothing in the deployed backend calls a generative model. The only AI Studio
capability in production is the embedding model (`gemini-embedding-2`), used to
write and read Pinecone vectors.

## The three ways in

Every request into Cloud Run arrives on one of three paths.

```
Claude Project ──MCP/OAuth──▶  /mcp/interactive   ─┐
                               /mcp/routine       ─┤
                                                   ├──▶  tool dispatch ──▶ stores
Web Hub (React) ──session cookie──▶  /api/*       ─┤
                                                   │
Cloud Scheduler ──OIDC──▶  /cron/*, /trigger/*   ─┘
```

1. **MCP** — Claude calls tools. Two scoped endpoints: `interactive` (live
   chat, may request approval) and `routine` (scheduled reviews, can never
   approve). OAuth 2.1 + PKCE; the token verifier and scope sets live with the
   MCP server.
2. **Hub API** — the React dashboard reads and writes through `/api/*`, gated by
   a signed session cookie tied to a single allowed Google account.
3. **Cron and triggers** — Cloud Scheduler drives ingestion (Garmin, Hevy,
   HealthKit, Things), deterministic alerts, and the routine backstops. iOS
   Shortcuts hit `/trigger/*` for the real wake and sleep moments.

Routines are coordinated, not executed, here: Cloud Run fires a Remote Routine
at Claude, waits, and publishes whatever comes back. If Claude misses the
deadline, a deterministic fallback review is published instead so a routine
never produces silence.

## Where the code lives

| Directory | Responsibility |
|---|---|
| `interfaces/` | HTTP and MCP surface. `web_server.py` is the entry point (`uvicorn interfaces.web_server:app`); `mcp_*.py` hold the MCP server, OAuth, runtime wiring and custom schemas; `hub_auth.py` the Hub session. |
| `core/` | Business logic and pure transformations. `tools.py` is the deterministic tool catalog and dispatcher; the rest is ingestion, routines, training maths and alerts. |
| `mcp_tools/` | Clients for outside systems — Google Calendar, Garmin, Hevy, Things, HealthKit, weather, the health database, vector memory. |
| `memory/` | Persistence. `firestore_db.py` (the stores), `pinecone_db.py` (vectors + embeddings), `things_store.py` (the Things mirror). |
| `frontend/` | The Web Hub: React + TypeScript + Vite, served as static files from the same origin. |
| `claude/` | Claude Project assets — the four skills, their build artifacts and evals. |
| `ops/` | Declared desired production state and retirement policies. |
| `scripts/` | Operational tooling and archived one-off migrations. |
| `docs/` | Living documentation. Shipped in the image: `COACHING_GUIDE.md` is read at runtime. |

## Invariants

- `KLAUS_USER_ID` is the canonical persistent namespace. It never changes.
- Google OAuth requests **Calendar scope only**.
- Gemini is permitted solely as the embedding credential and embedding model.
- Historical Firestore documents, vectors, logs and reviews are preserved.
- Production is never deployed or mutated without explicit authorization.
- The SPA is mounted at `/` and must remain the **last** route registered —
  anything after it is unreachable.

## Retired surfaces

Routes for the removed cloud-agent and Hub-chat runtimes still exist and return
**410 Gone**. They are deliberate tombstones, asserted by tests: they prove the
runtime was subtracted rather than merely disconnected. Do not delete or
repurpose them. See `ops/policies/quarantine.json`.
