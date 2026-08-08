# Claude Project “Klaus” — First-Use and Cutover Checklist

This is an operator/UAT checklist, not an automatic migration. Stop and leave
the legacy flags enabled if any Claude Pro capability is absent. Do not replace
it with browser automation, a copied subscription cookie, or an unofficial
subscription-token bridge.

Official references: [custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp),
[custom skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills),
and [Remote Routines](https://code.claude.com/docs/en/routines).

## 1. Deploy the read-only capability probe

- [ ] Deploy with legacy behavior unchanged:
  `KLAUS_LEGACY_RUNTIME_ENABLED=true`, `KLAUS_HUB_CHAT_ENABLED=true`, all
  routine cutover flags `false`, and deterministic alerts `false`.
- [ ] Set `KLAUS_PUBLIC_URL` to the canonical HTTPS Cloud Run URL.
- [ ] Set `KLAUS_USER_ID` to the numeric `user_id` already present on Amit's
  Pinecone memories. Do not choose a new value during cutover.
- [ ] Set `KLAUS_MCP_ENABLED=true`, `KLAUS_CLAUDE_LIVE_ENABLED=true`, and
  `KLAUS_MCP_READ_ONLY_MODE=true`.
- [ ] Confirm OAuth discovery and protected-resource metadata return the
  canonical issuer/resource URLs.
- [ ] In Claude, add the custom connector at `<KLAUS_PUBLIC_URL>/mcp/interactive`,
  sign in with the allowed Google account, and verify `get_life_snapshot`.
- [ ] Confirm the connector exposes reads but no task/calendar/memory writes.
- [ ] Set `KLAUS_CAPABILITY_MCP_VERIFIED=true` only after that real test passes.

## 2. Create the private Claude Project and skills

- [ ] Create a private Claude Project named **Klaus**.
- [ ] Use `docs/AGENT.md` for the JARVIS/C-3PO “Sir” voice and explicitly state
  that Klaus backend data and Pinecone memory are authoritative.
- [ ] Upload the four ZIP files from `claude/dist/`:
  `klaus-live-agent-7.0.0.zip`, `klaus-morning-review-7.0.0.zip`,
  `klaus-nightly-review-7.0.0.zip`, and `klaus-weekly-review-7.0.0.zip`.
- [ ] Run `python scripts/package_claude_skills.py --check` and confirm the
  uploaded version matches MCP metadata `7.0.0`.
- [ ] Test proactive recall, durable-only remember, one reversible task write
  in a test environment, and the high-risk prepared-action flow.
- [ ] Set `KLAUS_CAPABILITY_SKILL_VERIFIED=true` after the private skill loads
  and follows its policy tests.

## 3. Prove unattended Remote Routines

- [ ] Enable `KLAUS_CLAUDE_ROUTINES_ENABLED=true` and configure the routine
  connector at `<KLAUS_PUBLIC_URL>/mcp/routine`.
- [ ] Create a morning Sonnet routine using `klaus-morning-review`, a nightly
  Sonnet routine using `klaus-nightly-review`, and a Sunday Opus routine using
  `klaus-weekly-review`.
- [ ] Configure their supported API trigger URLs as
  `CLAUDE_ROUTINE_TRIGGER_URL_MORNING`, `_NIGHTLY`, and `_WEEKLY`. Store each
  one-time bearer separately in Secret Manager as
  `CLAUDE_ROUTINE_TRIGGER_TOKEN_MORNING`, `_NIGHTLY`, and `_WEEKLY`.
- [ ] With the computer off, trigger one routine and verify it reads Klaus MCP.
- [ ] Verify it calls `publish_review`, correlates to the queued run, and never
  receives `klaus.approve` or training-plan mutation tools.
- [ ] Set `KLAUS_CAPABILITY_ROUTINE_VERIFIED=true` and
  `KLAUS_CAPABILITY_PUBLISH_VERIFIED=true` only after both proofs pass.

## 4. Shadow and independent cutover

- [ ] Invoke `POST /api/routines/morning/shadow`, then nightly and weekly.
  Confirm each stores a `shadow_review` on its routine run and sends no push,
  writes no reflection/self-state, and does not replace the live review.
- [ ] Turn off read-only mode only after MCP security, idempotency, memory, and
  action tests pass: `KLAUS_MCP_READ_ONLY_MODE=false`.
- [ ] Cut over one routine at a time using
  `KLAUS_ROUTINE_MORNING_CUTOVER`, `_NIGHTLY_CUTOVER`, and `_WEEKLY_CUTOVER`.
- [ ] Create the 10:30 Asia/Jerusalem Scheduler backstop for
  `POST /cron/morning-backstop`; retain the existing nightly 01:00 and Sunday
  jobs, which route by flag.
- [ ] Configure iOS Wake → `POST /trigger/morning` and Sleep Focus →
  `POST /trigger/nightly`; confirm full lock-screen push text is acceptable.
- [ ] Verify timeout fallback, late silent upgrade, partial-action disclosure,
  and daily review deduplication.
- [ ] Configure `CLAUDE_PROJECT_URL`, verify the Hub “Ask Claude” action, then
  set `KLAUS_HUB_CHAT_ENABLED=false` to retire the old Hub chat endpoints.
- [ ] Set `KLAUS_DETERMINISTIC_ALERTS_ENABLED=true` and confirm the waking-hours
  scheduler makes no model call and never emits an untimed reminder.

## 5. Portfolio and behavior onboarding

- [ ] Review active standing directives and test one temporary directive.
- [ ] Through Claude, enter each holding with ticker/exchange, quantity or
  position value, native currency, and current brokerage return.
- [ ] Verify source URLs, timestamps, estimated baseline labeling, USD/ILS
  conversion, conflicting-source disclosure, and last-valid fallback.
- [ ] Verify nightly reflection/self-state write and veto one behavioral
  preference proposal end-to-end.

## 6. Seven-day observation and subtraction

- [ ] Observe live chat and all three routines for seven full days. Review
  `/api/agent/status`, `/api/reviews`, `/api/activity`, pending approvals,
  routine timeouts, action audit, Web Push, and embedding metering daily.
- [ ] Keep rollback flags and the old secrets/runtime intact during observation.
- [ ] After the seven-day sign-off, set `KLAUS_LEGACY_RUNTIME_ENABLED=false`.
  Re-consent Google OAuth with Calendar-only scope.
- [ ] In a separate cleanup change, remove the now-unused Telegram/Gmail/
  Readwise/chat-ingest/tick-brain/cascade/worker code, schedulers, generative
  SDKs, and model secrets. Do not delete historical conversations, vectors,
  logs, reviews, or data.
