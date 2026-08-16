# Claude Routine Publication Recovery Design

## Status

Approved direction: contain the failed nightly cutover, repair the exact damaged
records, publish complete schemas for every Klaus-specific MCP tool, harden the
one-shot review callback, and prove the flow in shadow mode before any cutover is
re-enabled.

## Incident

The live nightly Claude routine for `2026-08-09` received an unrestricted MCP
schema for `publish_review`. Claude attempted schema discovery with several
placeholder payloads. One payload satisfied the backend's minimal validation,
atomically transitioned the run to `published_claude`, overwrote the journal,
patched self-state, and stored `test text eighteen` as the review. The one-shot
state transition correctly rejected later attempts, but that also prevented the
real review from replacing the placeholder.

The morning report was a separate observation. Morning Claude cutover remained
disabled, so no Claude Routine run was expected. The legacy morning pipeline did
run at 06:15 Asia/Jerusalem, recorded status `sent`, and injected its message into
Klaus conversation history. Notification visibility is therefore a delivery/UI
issue, not evidence that the morning backend run was absent.

## Goals

1. Prevent another live Claude routine publication until the contract is proven.
2. Give Claude exact JSON schemas for every custom routine tool, especially
   `get_routine_status`, `publish_review`, and `publish_portfolio_snapshot`.
3. Reject incomplete nightly reflection/self-state payloads before any routine
   transition or durable write.
4. Make the one-shot/destructive nature of `publish_review` explicit to Claude.
5. Remove only the known placeholder contamination from `2026-08-09`, while
   preserving unrelated and legitimate morning/self-state data.
6. Require a successful shadow canary before nightly cutover can be enabled again.

## Non-goals

- Do not enable morning or weekly Claude cutover.
- Do not redesign the routine state machine or add an amend endpoint in this fix.
- Do not fabricate a replacement nightly reflection from incomplete session prose.
- Do not change legacy morning generation or push delivery behavior in this fix.
- Do not alter unrelated tasks, calendar events, memories, portfolio records, or
  behavioral feedback.

## Selected approach

Use a single canonical custom-tool schema registry consumed by MCP publication and
runtime validation. This is the smallest fix that addresses the root cause and
keeps the current one-shot state machine.

Two alternatives were rejected:

- **Documentation-only:** adding prose to the skill would still leave clients with
  an unrestricted object and would not protect the backend from malformed writes.
- **Two-phase prepare/commit:** stronger in theory, but it changes the public tool
  protocol, uploaded skills, and routine behavior. It is disproportionate for this
  incident and can be reconsidered if strict schemas plus shadow proof are not
  reliable.

## Schema architecture

Create a focused custom schema registry in the MCP layer. Each custom tool entry
contains an exact JSON Schema for the inner `arguments` object. `_register_tool`
must use this registry when a tool is absent from the legacy `core.tools` schema
metadata.

At minimum the registry covers all custom tools currently published by Klaus:

- `get_life_snapshot`
- `query_health_database`
- `list_portfolio_holdings`
- `get_routine_status`
- `upsert_portfolio_holding`
- `prepare_high_risk_action`
- `confirm_prepared_action`
- `list_pending_approvals`
- `publish_review`
- `publish_portfolio_snapshot`

Schemas use `additionalProperties: false` at the top level so misspelled fields do
not disappear silently. `publish_review` requires `correlation_id`, `routine`,
`target_date`, `text`, `structured`, `action_ids`, and `partial_actions`. Routine is
an enum of `morning`, `nightly`, and `weekly`; target date uses ISO `date` format.
The tool description identifies publication as final and one-shot and forbids
schema probes, placeholders, and test content.

The schema for `structured` remains routine-neutral at MCP publication time, but
the runtime applies stricter conditional validation for nightly reviews.

## Nightly runtime validation

Before `transition_claude_publication` or any Firestore write, a nightly payload
must contain:

- non-empty review text;
- `structured.reflection` as an object with non-empty `summary`, `mood`,
  `current_focus`, `recent_context`, and a list-valued `highlights`;
- `structured.self_state` as an object with non-empty `mood`, `current_focus`, and
  `recent_context`;
- list-valued `action_ids` and `partial_actions`.

Validation errors leave the routine in `running`, allowing Claude to correct the
payload and make its single actual publication call. No journal, self-state,
review, push, or state-transition side effect occurs before validation succeeds.

The validator rejects the known probe class through structural completeness, not
through a brittle banned-word list. A legitimate review may discuss a test; it
must not be rejected merely for containing that word.

## Skill contract

Update the three routine skills without changing their version:

- State that the connector exposes the authoritative schema and Claude must never
  discover it by calling a write tool.
- State that `publish_review` is final and one-shot.
- Spell out the canonical top-level fields.
- For nightly, spell out the required reflection and self-state fields.
- Require all composition and local checking to finish before the one call.

Repackage the skill ZIP files and update the manifest checksums. The user will
need to replace the uploaded skills before a future cutover, because Claude's
hosted skill copies are not changed by a repository deployment.

## Production data repair

Repair only correlation ID `a485e1a9914893c100eb2dce1d25b53e` and target date
`2026-08-09`:

1. Replace the invalid review text/structure with an explicit invalidation record
   that says the review was not authoritative because a schema-probe placeholder
   was published. Preserve the correlation ID and publication timestamps for
   auditability.
2. Delete `journal/2026-08-09`, because its entire content is the placeholder
   reflection and no authoritative replacement exists.
3. Remove only `source`, `reflection_date`, and `proposed_mood` from
   `config/self_state` when they still match the incident values. Preserve
   identity, mood, focus, recent context, and the legitimate `2026-08-10` morning
   daily note.
4. Add incident/invalidation metadata to the routine run rather than deleting the
   run or rewriting its historical state transition.

The repair script performs precondition checks and aborts if any targeted field no
longer matches the observed placeholder. It prints a redacted before/after summary
and is safe to rerun.

## Rollout and verification

1. Keep all Claude routine cutovers disabled during implementation.
2. Prove tests fail against the unrestricted schema and permissive validator.
3. Implement the schema registry and strict pre-transition validation.
4. Run focused MCP/runtime/skill tests, then the full offline suite.
5. Deploy with cutovers still disabled.
6. Reconnect or refresh the Klaus Routines connector if Claude caches tool schemas.
7. Run a nightly shadow canary and inspect that:
   - Claude calls `publish_review` once;
   - the stored shadow review is complete and non-placeholder;
   - no push, journal, self-state, or live review is changed.
8. Re-enable nightly cutover only after the shadow evidence passes. Morning and
   weekly remain disabled until their own canaries.

## Testing

- MCP catalog tests assert exact schemas and required fields for every custom tool.
- Runtime tests prove the `2026-08-09` placeholder shape is rejected before the
  transition/store/push functions are called.
- Runtime tests prove a complete nightly payload publishes normally.
- Skill tests assert the no-probe, one-shot, and canonical payload rules.
- Repair-script tests cover exact-match repair, precondition abort, idempotent
  rerun, and preservation of legitimate self-state fields.

## Success criteria

- Production cutovers remain off until explicit post-shadow approval.
- Claude sees exact field names instead of `additionalProperties: true` for custom
  routine tools.
- The observed placeholder cannot transition or write any durable state.
- The three contaminated production records are repaired without touching other
  user data.
- A nightly shadow run publishes one complete structured review with zero live
  side effects.
