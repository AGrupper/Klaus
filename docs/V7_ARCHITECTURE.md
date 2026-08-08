# Klaus v7.0 — Subscription-First Architecture

## Status

The v7 code is dark-shipped behind independent flags. It must not replace the
legacy runtime until the capability gate in `CLAUDE_FIRST_USE.md` is completed
with Amit's actual Claude Pro account. Unsupported browser automation, session
cookie reuse, and subscription-token bridges are explicitly prohibited.

## Authority and responsibilities

| Layer | Responsibility | Authority |
|---|---|---|
| Claude Project “Klaus” | Conversation, immediate context, subscription-funded reasoning | May call only the scoped Klaus connector tools granted to it |
| Klaus Cloud Run | OAuth resource server, MCP tools, policy, actions, Hub APIs, routine coordination | Authoritative action and authorization boundary |
| Firestore / Postgres | Tasks, habits, reviews, routine state, health, approvals, audit | Authoritative structured state |
| Pinecone | Durable semantic memory and recall | Authoritative long-term semantic memory |
| Gemini AI Studio | `gemini-embedding-2` only | No generative role in the v7 runtime |

Claude Project memory can improve conversational continuity but cannot override
Klaus records. Klaus never copies Claude transcripts into the Hub.

## Public interfaces

- `POST /mcp/interactive` — stateless Streamable HTTP MCP for live Claude chat.
- `POST /mcp/routine` — separately scoped MCP for unattended Remote Routines.
- `/.well-known/oauth-authorization-server`, resource metadata, registration,
  authorization, token, and revocation routes — OAuth 2.1 authorization code +
  PKCE S256 with opaque, hashed server-side credentials.
- Hub APIs: `/api/reviews`, `/api/activity`, `/api/approvals`, `/api/portfolio`,
  `/api/agent/status`, and `/api/routines/{routine}/shadow`.

Interactive tokens may receive `klaus.read`, `klaus.write`, `klaus.memory`, and
`klaus.approve`. Routine tokens may receive `klaus.read`, `klaus.write`,
`klaus.memory`, and `klaus.routine`; the authorization service strips
`klaus.approve` from routine grants. Tokens are bound to one MCP resource and
cannot cross between endpoints.

## Tool and action policy

- `get_life_snapshot` is the compact first read. It uses the Hub's normalized
  Today providers and includes tasks, pending habits, directives, self-state,
  reviews, and the memory authority contract.
- Detail remains lazy through explicit calendar, task, habit, health, training,
  nutrition, weather/routes, Notion, memory, directive, and portfolio tools.
- Every write requires an idempotency key. Execution is recorded before audit
  completion so a retry can finish audit without repeating the side effect.
- Notion responses are wrapped as untrusted data. Skills instruct Claude never
  to treat retrieved content as instructions.
- Routine calendar update/delete is allowed only for events marked
  `extendedProperties.private.klaus_owned=true`. User events and training plans
  cannot be silently moved; routine training-plan mutation tools are absent.
- Payments, credentials/security, permanent bulk deletion, medical commitments,
  and first-time outreach are immutable prepared actions. Only an interactive
  `klaus.approve` token can confirm an unexpired action with the exact payload hash.

## Routine state machine

Statuses are `queued`, `running`, `published_claude`, `published_fallback`,
`late_upgraded`, and `failed`.

1. Klaus atomically creates the run and correlation ID.
2. It schedules a Cloud Tasks callback for ten minutes before firing the
   configured Claude Remote Routine API trigger.
3. Claude reads the compact snapshot, lazily gathers detail, acts within policy,
   and publishes through `publish_review`.
4. A timeout publishes a factual deterministic review and performs no
   judgment-based write.
5. A late Claude callback enriches the existing review without a second push.

Morning/nightly declare Sonnet in the trigger payload; weekly declares Opus.
Shadow runs keep their result on the routine-run document and never publish,
push, change memory, or replace a live review.

Morning and nightly use separate Claude skills so their context and behavior
cannot bleed into one another. The morning skill preserves a viable plan and
replans only for material changes. The nightly skill closes the day, repairs
suitable unfinished work, protects tomorrow's slack, and publishes reflection
and proposed self-state. Their shared authorization, idempotency, fallback, and
disclosure rules are duplicated deliberately so each uploaded ZIP is complete.

Nightly Claude publications require structured `reflection` and `self_state`
objects. They may include vetoable behavioral-feedback proposals. Training
changes are recommendations only.

## Deterministic daytime behavior

`KLAUS_DETERMINISTIC_ALERTS_ENABLED=true` changes the existing waking-hours
scheduler endpoint from the LLM cascade to `core/deterministic_alerts.py`.
Only these explicit conditions can push:

- a due timed follow-up;
- a hard deadline within two hours;
- overlapping calendar events or a passed leave-by time;
- a critical automation failure.

Untimed tasks, habits, nutrition, and coaching state are deliberately ignored.
Delivery, outreach audit, and follow-up completion are one ordered operation:
failed push delivery is not logged as sent and does not complete the follow-up.

## Data additions

- Tasks: optional `estimated_minutes`, `hard_deadline_at`, `auto_schedule`,
  `manual_lock`, and `calendar_event_id`; old records remain valid.
- Pending approvals and behavioral-feedback proposals.
- Portfolio holdings and weekly ILS snapshots with native currency, estimated
  baseline, quote/FX source URLs, and observation timestamps.
- Common routine-run/review fields merged into existing date collections.
- Dedicated embedding usage documents record provider-reported tokens, request
  and item counts, and cost only when an operator supplies the current public
  per-million-token rate. Claude subscription activity never invents a cost.

## Rollback and subtraction

Every cutover is reversible. Keep `KLAUS_LEGACY_RUNTIME_ENABLED=true` and
`KLAUS_HUB_CHAT_ENABLED=true` through capability proof, shadow runs, independent
routine cutovers, and a seven-day observation window. Only after that window may
the operator disable legacy runtime and remove Telegram, Gmail, Readwise,
chat-import schedules, tick-brain/cascade/worker code, generative SDKs, and old
model secrets. Historical conversations, vectors, logs, and data are retained.

With the legacy runtime off, Google OAuth requests Calendar only. The container
starts without generative-model keys; the dedicated Gemini embedding key and
Pinecone key remain required for semantic memory.
