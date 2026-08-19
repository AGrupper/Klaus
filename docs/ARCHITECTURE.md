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
Cloud Scheduler ──OIDC──▶  /cron/*                ─┤
Cloud Tasks ─────OIDC──▶  /internal/*             ─┤
iOS Shortcuts ───token──▶  /trigger/*             ─┘
```

1. **MCP** — Claude calls tools. Two scoped endpoints: `interactive` (live
   chat, may request approval) and `routine` (scheduled reviews, can never
   approve). OAuth 2.1 + PKCE; the token verifier and scope sets live with the
   MCP server.
2. **Hub API** — the React dashboard reads and writes through `/api/*`, gated by
   a signed session cookie tied to a single allowed Google account. The Hub
   itself is two screens (Today and Routines) plus a notification bell and a
   Customize sheet; tasks, health charts and the Claude launcher tab were
   retired from the UI in v8.0, though their read APIs remain for Claude and
   for the day view.
3. **Scheduled and triggered** — three machine callers, each with its own
   verifier in `interfaces/routes/_verify.py`.
   - *Cloud Scheduler* (`/cron/*`) drives ingestion (Garmin, Hevy, HealthKit,
     Things), the routine backstops, the daily reminder re-arm, and the
     deterministic alert pass.
   - *Cloud Tasks* (`/internal/*`) delivers work that has to happen at one
     exact moment: a routine's reminder at the minute it was set, and a
     routine's fallback review when Claude misses its deadline.
   - *iOS Shortcuts* (`/trigger/*`) report the real wake and Sleep-Focus
     moments. These do double duty: they start the morning and nightly
     routines, **and** they are what opens and closes the alert window (see
     below), so Amit's actual day — not a cron expression — decides when
     Klaus may interrupt him.

Routines are coordinated, not executed, here: Cloud Run fires a Remote Routine
at Claude, waits, and publishes whatever comes back. If Claude misses the
deadline, a deterministic fallback review is published instead so a routine
never produces silence.

## When Klaus may interrupt

Two unrelated mechanisms put a notification on Amit's phone, and the difference
between them is the difference between a known moment and an unknown one.

**Reminders are scheduled.** A Hub routine armed with `remind` has a fire time
the instant it is set, so `core/routines/reminders.py` enqueues one Cloud Task
for that exact minute. Editing the time cancels and re-creates; the routine's
own id keys the single record of what is queued, and the delivery handler drops
any task whose baked-in `anchor_time` no longer matches the routine — so a
changed time cannot produce two notifications even if the cancel fails.

**Everything else is polled**, because a calendar collision or an approaching
deadline cannot be known in advance. `core/routines/alerts.py` runs every 30
minutes and evaluates only explicit, time-bound conditions. It is gated by
`alert_window_open`, which reads the existing morning/nightly routine runs:
open from the wake trigger, closed by Sleep Focus, opening by 10:30 regardless
if the wake trigger missed and closing itself 20 hours after opening if the
sleep trigger did. An unreadable window opens rather than closes — silence is
the worse failure. Reminders ignore the window entirely.

## Where the code lives

| Directory | Responsibility |
|---|---|
| `interfaces/` | HTTP and MCP surface. `web_server.py` is the entry point (`uvicorn interfaces.web_server:app`); `mcp_*.py` hold the MCP server, OAuth, runtime wiring and custom schemas; `hub_auth.py` the Hub session. |
| `core/` | Business logic and pure transformations. `tools.py` is the deterministic tool catalog and dispatcher; the rest is ingestion, routines, training maths and alerts. |
| `mcp_tools/` | Clients for outside systems — Google Calendar, Garmin, Hevy, Things, HealthKit, weather, the health database, vector memory. |
| `memory/` | Persistence. `firestore_db.py` (the stores), `pinecone_db.py` (vectors + embeddings), `things_store.py` (the Things mirror). |
| `frontend/` | The Web Hub: React + TypeScript + Vite, served as static files from the same origin. Theming is CSS custom properties written at runtime by `src/tokens.ts` from the account's saved appearance, so the Customize sheet re-skins the app without a rebuild. |
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
- A moment known in advance is **scheduled**, never polled. Polling exists only
  for conditions that cannot be known ahead of time.
- The SPA is mounted at `/` and must remain the **last** route registered —
  anything after it is unreachable.

## Retired surfaces

Routes for the removed cloud-agent and Hub-chat runtimes still exist and return
**410 Gone**. They are deliberate tombstones, asserted by tests: they prove the
runtime was subtracted rather than merely disconnected. Do not delete or
repurpose them. See `ops/policies/quarantine.json`.
