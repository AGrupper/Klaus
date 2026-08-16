## Publication contract

`publish_review` is final and one-shot. Never call a write tool to discover its schema, and never send test, placeholder, or probe content. The real 2026-08-09 Claude run showed why: write-based schema discovery persisted a placeholder. Finish the review and check every field locally before the single call. Use the connector's published schema as authoritative.

Pass `correlation_id`, `routine`, `target_date`, `text`, `structured`, `action_ids`, and `partial_actions` inside `arguments`, plus one unique outer `idempotency_key`. This is the only `publish_review` call for this invocation.

## Shadow mode

When `delivery_mode` is `shadow`, do not call any mutating tool except the single
`publish_review` required by the publication contract. Do not create, edit,
complete, reschedule, or delete tasks; do not mutate calendars, memories,
directives, follow-ups, plans, training data, habits, or portfolio snapshots.
Record proposed actions only in `partial_actions`, with no live action IDs, and
make clear in the review that they were not performed.

## Final routine response

After `publish_review` returns success, the final assistant response must consist
solely of the exact published review text. Do not add a preamble, status line,
acknowledgement, or postscript. Do not replace it with an acknowledgement, short
summary, or "published successfully" message.

Rendering the already-published text is not another write: do not call `publish_review` again and do not request or send another push. If `publish_review` fails, report the failure honestly and do not describe the unpublished review as canonical.
