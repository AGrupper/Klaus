# Klaus — Security Audit (WS4)

Audit date: 2026-06-10. Scope: auth on all inbound endpoints, Telegram access control,
the analytical DB tool's SQL surface, secret handling/logging, and prompt-injection from
ingested content. Klaus is a **single-user** agent (one allow-listed Telegram account),
which bounds most threats.

## Findings

| # | Severity | Area | Status |
|---|----------|------|--------|
| 1 | MEDIUM | DB tool read-only enforcement was string-parse only (bypassable) | **Fixed** |
| 2 | LOW | Prompt injection from ingested email/chat content | Accepted (mitigated) |
| 3 | INFO | `CRON_DEV_BYPASS` must never be set in prod env | Ops invariant |

### 1. DB tool read-only enforcement — FIXED
`mcp_tools/database_tool.py::query_health_database` gated writes only by string parsing
(must start with `SELECT`/`WITH`; block `"delete "` etc.). Two bypasses existed:
- **Whitespace evasion:** the keyword check matched `"delete "` *with a trailing space*,
  so `delete\tfrom …` (tab) slipped through.
- **Multi-statement:** `cur.execute()` runs `;`-chained statements, so
  `SELECT 1; delete …` passed the prefix check.
If the Postgres role had write perms, either could mutate/drop data.

**Fix:** defense-in-depth — (a) the connection now runs `conn.set_session(readonly=True,
autocommit=True)`, so any write is rejected by Postgres itself ("cannot execute … in a
read-only transaction") regardless of parsing; (b) keyword matching is now word-boundary
regex (whitespace-evasion proof); (c) multi-statement input is rejected. Covered by
`tests/test_database_tool.py`. **Ops follow-up (belt-and-suspenders):** ensure the DB role
Klaus connects as is itself read-only (`GRANT SELECT` only).

### 2. Prompt injection from ingested content — ACCEPTED (mitigated)
Untrusted text (emails, chat-export logs, Notion) can reach the brain, which acts with
tool access. Residual risk a crafted email could nudge an action. Mitigations already in
place make this low-likelihood for a personal agent:
- Only the allow-listed user can converse with Klaus (no external prompt surface).
- The autonomous tick ingests the unread-email **count only**, never email bodies.
- `mcp_tools/self_inspect.py` blocks reading `.env`/secrets, so injection can't exfiltrate
  credentials via the self-inspection tools. **This block is intentionally kept** (it is a
  security control, distinct from the privacy guardrails that were removed).
No code change — adding heavy input-sanitization guardrails would conflict with the
intended autonomy and is disproportionate to the single-user threat model.

### 3. `CRON_DEV_BYPASS` — ops invariant
All `/cron/*` and `/trigger/*` endpoints skip auth **only** when `CRON_DEV_BYPASS == "true"`
(unset → auth enforced). This is correct, but the Cloud Run service env must **never** set
`CRON_DEV_BYPASS`. Verify on each deploy.

## Verified clean (no change needed)

- **Endpoint auth.** `/cron/*` use OIDC bearer verification (audience + SA-email check).
  `/cron/healthkit-sync` and the new `/trigger/nightly` use shared-secret bearers with
  **constant-time** `hmac.compare_digest`, **refuse-all (500) when the token env is unset**
  (fail-closed), and redacted-prefix logging on failure. The Telegram webhook validates
  `X-Telegram-Bot-Api-Secret-Token` in constant time.
- **Telegram access control.** `interfaces/_router.py` silently drops any update whose
  `effective_user.id` is not in `TELEGRAM_ALLOWED_USER_IDS` (both message and callback
  paths). `parse_allowed_user_ids()` raises if the env is unset — fail-closed at startup.
- **Secret handling/logging.** Logs reference secret *names* and statuses, never values
  (`core/auth_google.py`, `mcp_tools/garmin_tool.py`, `mcp_tools/ticktick_auth.py`). The
  nightly/HealthKit token verifiers log only a redacted 4+4 prefix on auth failure.
- **Least privilege (new).** `/trigger/nightly` uses its own `NIGHTLY_TRIGGER_TOKEN`, not
  the HealthKit token, so a leak of one cannot drive the other endpoint.
