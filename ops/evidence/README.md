# Quarantine deletion evidence

Machine-gathered records from `scripts/active/gather_quarantine_evidence.py`,
kept because each one justifies an irreversible deletion.

- `quarantine-2026-08-21.json` — the full quarantine set. Gate **closed**:
  `klaus-notion-api-token` and `klaus-home-address` were still enabled. Those
  two joined the quarantine list on 2026-08-16 when the Notion and Google
  Routes connectors were retired, so the 2026-08-13 observation start does not
  apply to them and they need their own window.
- `quarantine-original-set-2026-08-21.json` — the original 2026-08-13
  retirement set, audited in isolation. Gate **satisfied**: zero access, zero
  generative usage, every resource inert, all three Claude routines published.

Acting on the second record, on 2026-08-21 and on Amit's explicit instruction,
these seven secrets were permanently deleted:

    klaus-anthropic-key   klaus-deepseek-key   klaus-tick-brain-key
    klaus-gemini-key      klaus-telegram-token klaus-telegram-webhook-secret
    klaus-github-token

`klaus-readwise-token` was already absent. Five of the seven had destroyed
versions; the two Telegram secrets held disabled versions whose material is now
gone for good.

Still quarantined and NOT deleted: scheduler jobs `klaus-autonomous-tick` and
`klaus-reflect` (both PAUSED; the other three no longer exist), the disabled
service account `klaus-log-uploader@`, and the two connector secrets above.

After deletion: `/health` 200 and `audit_production_drift.py` reported a clean
match. The embedding credential and every runtime secret were untouched.
