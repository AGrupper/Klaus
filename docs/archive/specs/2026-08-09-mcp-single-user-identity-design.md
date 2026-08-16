# MCP Single-User Identity Propagation

## Problem

Klaus's existing Pinecone memories are scoped by Amit's historical numeric
user ID. Agent turns set that ID in `core.tools` thread-local state before
dispatching memory tools. Remote MCP calls currently invoke the same dispatcher
inside a worker thread without setting the thread-local value, so `remember`
and `recall` silently use the default ID `0`.

The production UAT exposed the failure: Claude stored and recalled the test
memory successfully, but the Pinecone vector metadata contained
`user_id: "0"`. That creates a second memory namespace and prevents Claude from
reliably sharing Klaus's authoritative historical memory.

## Decision

Add an identity-aware production MCP dispatcher. It will resolve Klaus's one
canonical numeric user ID and call `set_current_user_id()` immediately before
calling the existing tool dispatcher. Because the wrapper itself runs inside
the `asyncio.to_thread` worker used by `KlausMCPGateway`, the thread-local value
is set in the same thread that executes `remember`, `recall`, and any future
user-scoped tool.

Identity resolution order:

1. `KLAUS_USER_ID`, the provider-neutral canonical setting.
2. The first valid value in `TELEGRAM_ALLOWED_USER_IDS`, retained only as a
   migration fallback for the current deployment.
3. In production, raise a clear configuration error rather than using `0`.
4. Outside production, retain `0` only when neither setting is present so
   isolated tests and local development remain backward-compatible.

`create_production_mcp_bundle()` will pass this wrapper as the bundle's
dispatcher. Both `/mcp/interactive` and `/mcp/routine` therefore share the
same identity behavior without duplicating memory handlers.

## Configuration and Compatibility

- Document `KLAUS_USER_ID` in `.env.example`.
- Add `KLAUS_USER_ID` to the deploy workflow using the existing single-user
  secret value during the migration period.
- Set `KLAUS_USER_ID` explicitly on the live Cloud Run service during rollout.
- Do not migrate or rewrite existing Pinecone vectors; the fix restores access
  to their current namespace.
- Do not alter embedding model, vector dimension, index, metadata shape, or
  recall ranking.
- Leave the current `user_id=0` UAT vector in place until the corrected build
  is deployed, then delete it by its exact vector ID and repeat the UAT.

## Alternatives Rejected

### Custom handlers for memory tools only

Explicit MCP handlers for `remember`, `recall`, and `forget_memory` would avoid
thread-local state but duplicate existing tool behavior and leave future
user-scoped tools exposed to the same bug.

### Derive identity from the Google OAuth email

Using an email or its hash would be provider-neutral at the interface, but it
would create a new Pinecone namespace and require a destructive or error-prone
metadata migration. Preserving the existing numeric namespace is safer.

## Error Handling and Security

- Production MCP calls must never silently fall back to user ID `0`.
- `KLAUS_USER_ID` and fallback values must parse as positive integers.
- Invalid explicit configuration raises an actionable error; it must not fall
  through to another identity and hide a deployment mistake.
- The dispatcher changes identity context only. OAuth resource validation,
  scopes, write approval, idempotency, auditing, and endpoint catalogs remain
  unchanged.
- Single-user identity resolution must not expose the numeric ID in normal
  Claude responses or add it to tool payloads.

## Testing

Use test-driven development with a regression test that fails against the
current code because the dispatcher observes user ID `0`.

Required coverage:

- Explicit `KLAUS_USER_ID` is set in the worker thread before dispatch.
- The first valid `TELEGRAM_ALLOWED_USER_IDS` value preserves the historical
  namespace when the explicit variable is absent.
- Invalid explicit `KLAUS_USER_ID` fails clearly.
- Missing identity fails closed when `ENVIRONMENT=production`.
- Missing identity retains test/local compatibility outside production.
- The production MCP bundle uses the identity-aware dispatcher for both
  interactive and routine endpoints.
- Existing MCP OAuth, scope, idempotency, approval, and routine tests remain
  green.

## Rollout and Verification

1. Deploy the corrected image with `KLAUS_USER_ID` set to Amit's existing
   numeric namespace.
2. Confirm health, traffic, feature flags, and no revision errors.
3. Delete the temporary `user_id=0` vector by exact ID through the existing
   approved `forget_memory` path.
4. Repeat remember and recall with a new UAT marker.
5. Independently fetch the new Pinecone vector and verify its metadata uses
   the canonical user ID, not `0`.
6. Delete the corrected UAT vector and verify its audit/idempotency records.
7. Resume high-risk approval and Remote Routine capability testing only after
   memory namespace verification passes.
