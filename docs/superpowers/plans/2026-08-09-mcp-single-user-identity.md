# MCP Single-User Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Claude interactive and routine MCP tools use Amit's existing canonical user namespace instead of silently storing and recalling Pinecone memories under user ID `0`.

**Architecture:** Add a production MCP dispatcher wrapper in `interfaces/mcp_runtime.py`. The wrapper resolves a provider-neutral `KLAUS_USER_ID`, falls back temporarily to the first valid `TELEGRAM_ALLOWED_USER_IDS` value, sets `core.tools` thread-local identity inside the MCP worker thread, and delegates to the existing dispatcher. Both MCP endpoints already share one gateway, so passing this wrapper into `create_mcp_bundle()` fixes interactive and routine calls without duplicating memory handlers.

**Tech Stack:** Python 3.13, FastAPI/Starlette, MCP Python SDK, pytest, Google Cloud Run, Pinecone, Gemini `gemini-embedding-2`.

## Global Constraints

- Preserve the existing Pinecone index `klaus-memory`, 768 dimensions, cosine metric, metadata shape, embedding model, and recall ranking.
- Production must never silently fall back to user ID `0`.
- `KLAUS_USER_ID` is authoritative when configured; invalid explicit configuration must fail clearly.
- The first valid `TELEGRAM_ALLOWED_USER_IDS` entry is a temporary migration fallback only.
- Local and test environments may retain ID `0` when no identity is configured.
- OAuth scopes, approval policy, idempotency, auditing, and MCP tool catalogs must remain unchanged.
- Preserve the user's unrelated `.claude/scheduled_tasks.lock` and `AGENTS.md` worktree changes.

---

### Task 1: Identity-aware MCP dispatcher

**Files:**
- Modify: `tests/test_mcp_runtime.py`
- Modify: `interfaces/mcp_runtime.py`

**Interfaces:**
- Produces: `_resolve_single_user_id() -> int`
- Produces: `dispatch_for_single_user(tool_name: str, arguments: dict) -> Any`
- Consumes: `core.tools.set_current_user_id(user_id: int) -> None`
- Consumes: `core.tools.dispatch(tool_name: str, arguments: dict) -> str`

- [ ] **Step 1: Add failing identity-resolution tests**

Append tests that define the required precedence and failure behavior:

```python
def test_resolve_single_user_id_prefers_explicit_setting(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.setenv("KLAUS_USER_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111,222")
    assert _resolve_single_user_id() == 123456789


def test_resolve_single_user_id_uses_first_valid_legacy_value(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "invalid, 123456789, 999")
    assert _resolve_single_user_id() == 123456789


@pytest.mark.parametrize("value", ["", "not-a-number", "0", "-1"])
def test_resolve_single_user_id_rejects_invalid_explicit_setting(monkeypatch, value):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.setenv("KLAUS_USER_ID", value)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456789")
    with pytest.raises(RuntimeError, match="KLAUS_USER_ID"):
        _resolve_single_user_id()


def test_resolve_single_user_id_fails_closed_in_production(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="canonical Klaus user ID"):
        _resolve_single_user_id()


def test_resolve_single_user_id_retains_local_default(monkeypatch):
    from interfaces.mcp_runtime import _resolve_single_user_id

    monkeypatch.delenv("KLAUS_USER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert _resolve_single_user_id() == 0
```

- [ ] **Step 2: Add the failing dispatcher test**

The test must prove identity is set before the existing dispatcher runs:

```python
def test_dispatch_for_single_user_sets_identity_before_dispatch(monkeypatch):
    import core.tools
    from interfaces.mcp_runtime import dispatch_for_single_user

    observed = []
    monkeypatch.setenv("KLAUS_USER_ID", "123456789")
    monkeypatch.setattr(
        core.tools,
        "set_current_user_id",
        lambda user_id: observed.append(("identity", user_id)),
    )
    monkeypatch.setattr(
        core.tools,
        "dispatch",
        lambda tool_name, arguments: observed.append(
            ("dispatch", tool_name, arguments)
        ) or "result",
    )

    assert dispatch_for_single_user("recall", {"query": "history"}) == "result"
    assert observed == [
        ("identity", 123456789),
        ("dispatch", "recall", {"query": "history"}),
    ]
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_mcp_runtime.py
```

Expected: FAIL because `_resolve_single_user_id` and
`dispatch_for_single_user` do not exist. Confirm the existing redaction test
still passes within the same run.

- [ ] **Step 4: Implement the minimal resolver and dispatcher**

Add these functions near `_settings()` in `interfaces/mcp_runtime.py`:

```python
def _positive_user_id(value: str, *, setting: str) -> int:
    try:
        user_id = int(value.strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{setting} must be a positive integer") from exc
    if user_id <= 0:
        raise RuntimeError(f"{setting} must be a positive integer")
    return user_id


def _resolve_single_user_id() -> int:
    explicit = os.environ.get("KLAUS_USER_ID")
    if explicit is not None:
        return _positive_user_id(explicit, setting="KLAUS_USER_ID")

    for candidate in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return _positive_user_id(candidate, setting="TELEGRAM_ALLOWED_USER_IDS")
        except RuntimeError:
            continue

    if os.environ.get("ENVIRONMENT", "development").strip().lower() == "production":
        raise RuntimeError(
            "A canonical Klaus user ID is required in production; set KLAUS_USER_ID"
        )
    return 0


def dispatch_for_single_user(tool_name: str, arguments: dict) -> Any:
    from core.tools import dispatch, set_current_user_id

    set_current_user_id(_resolve_single_user_id())
    return dispatch(tool_name, arguments)
```

Update `create_production_mcp_bundle()` to pass the wrapper:

```python
return create_mcp_bundle(
    oauth_service,
    dispatcher=dispatch_for_single_user,
    custom_handlers=build_custom_handlers(),
    idempotency_store=ActionIdempotencyStore(*_settings()),
    auditor=audit_mcp_write,
    calendar_ownership_checker=calendar_is_klaus_owned,
    read_only=read_only,
)
```

- [ ] **Step 5: Add a bundle-wiring regression assertion**

Add a test that replaces `create_mcp_bundle`, calls
`create_production_mcp_bundle()`, and asserts the captured dispatcher:

```python
def test_production_bundle_uses_identity_aware_dispatcher(monkeypatch):
    import interfaces.mcp_runtime as runtime
    import memory.firestore_db

    captured = {}
    monkeypatch.setattr(
        memory.firestore_db,
        "ActionIdempotencyStore",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        runtime,
        "create_mcp_bundle",
        lambda oauth_service, **kwargs: captured.update(kwargs) or "bundle",
    )

    assert runtime.create_production_mcp_bundle(object()) == "bundle"
    assert captured["dispatcher"] is runtime.dispatch_for_single_user
```

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mcp_runtime.py \
  tests/test_mcp_server.py \
  tests/test_mcp_oauth.py \
  tests/test_mcp_mounting.py
```

Expected: all selected tests pass with no warnings or errors.

- [ ] **Step 7: Commit the identity behavior**

```bash
git add interfaces/mcp_runtime.py tests/test_mcp_runtime.py
git commit -m "fix: propagate canonical user identity through MCP"
```

---

### Task 2: Canonical identity deployment configuration

**Files:**
- Modify: `.env.example`
- Modify: `.github/workflows/deploy.yml`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/CLAUDE_FIRST_USE.md`

**Interfaces:**
- Consumes: `KLAUS_USER_ID` parsed by `_resolve_single_user_id()` from Task 1
- Produces: documented operator contract for preserving the existing Pinecone namespace

- [ ] **Step 1: Document the local and production setting**

Add beside the single-user interface configuration in `.env.example`:

```dotenv
# Provider-neutral canonical user namespace. It must match the user_id metadata
# already stored in Pinecone; Telegram ID fallback is migration-only.
KLAUS_USER_ID=123456789
```

Add `KLAUS_USER_ID` to both environment-variable tables in
`docs/DEPLOYMENT.md`, describing it as the canonical numeric namespace shared
by interactive MCP, routines, and Pinecone. Add a first-use checklist item
before enabling MCP in `docs/CLAUDE_FIRST_USE.md`:

```markdown
- [ ] Set `KLAUS_USER_ID` to the numeric `user_id` already present on Amit's
  Pinecone memories. Do not choose a new value during cutover.
```

- [ ] **Step 2: Preserve the namespace in GitHub deployments**

In `.github/workflows/deploy.yml`, add this entry to the existing
`--set-env-vars` string immediately after `TELEGRAM_ALLOWED_USER_IDS`:

```text
KLAUS_USER_ID=${{ secrets.TELEGRAM_ALLOWED_USER_IDS }}
```

This intentionally reuses the existing single-user value during migration;
the runtime setting is provider-neutral and can move to its own secret after
Telegram removal.

- [ ] **Step 3: Verify configuration text and formatting**

Run:

```bash
rg -n "KLAUS_USER_ID" \
  .env.example \
  .github/workflows/deploy.yml \
  docs/DEPLOYMENT.md \
  docs/CLAUDE_FIRST_USE.md
git diff --check
```

Expected: all four files contain the setting and `git diff --check` exits 0.

- [ ] **Step 4: Run focused and full regression suites**

Run the focused suite from Task 1, then:

```bash
.venv/bin/python -m pytest -q \
  --ignore=tests/test_token_budget.py \
  --ignore=tests/memory/test_pinecone_embed.py
```

Expected: all offline tests pass. The two ignored files require live network
services and are covered by the production UAT in Task 3.

- [ ] **Step 5: Commit configuration and documentation**

```bash
git add \
  .env.example \
  .github/workflows/deploy.yml \
  docs/DEPLOYMENT.md \
  docs/CLAUDE_FIRST_USE.md
git commit -m "docs: configure canonical Klaus user identity"
```

---

### Task 3: Production rollout and memory UAT cleanup

**Files:**
- No repository files modified
- Verify: Cloud Run service `klaus-agent`, Pinecone index `klaus-memory`, Firestore database `klaus-firestore`

**Interfaces:**
- Consumes: corrected image and `KLAUS_USER_ID`
- Produces: production evidence that Claude memory uses Amit's historical namespace

- [ ] **Step 1: Push the reviewed commits and wait for deployment**

```bash
git push origin main
```

Confirm the workflow deploys an image containing the identity-fix commit.
Because the workflow currently deploys v7 capability flags dark, do not test
MCP until Step 2 reapplies the verified rollout state.

- [ ] **Step 2: Reapply the verified capability state explicitly**

```bash
KLAUS_CANONICAL_USER_ID="$(
  gcloud run services describe klaus-agent \
    --project klaus-agent \
    --region me-west1 \
    --format=json \
  | jq -r '[.spec.template.spec.containers[0].env[] | select(.name == "TELEGRAM_ALLOWED_USER_IDS") | .value][0] | split(",")[0]'
)"
[[ "$KLAUS_CANONICAL_USER_ID" =~ ^[1-9][0-9]*$ ]]

gcloud run services update klaus-agent \
  --project klaus-agent \
  --region me-west1 \
  --update-env-vars KLAUS_USER_ID="$KLAUS_CANONICAL_USER_ID",KLAUS_MCP_ENABLED=true,KLAUS_CLAUDE_LIVE_ENABLED=true,KLAUS_CLAUDE_ROUTINES_ENABLED=true,KLAUS_MCP_READ_ONLY_MODE=false,KLAUS_CAPABILITY_MCP_VERIFIED=true,KLAUS_CAPABILITY_SKILL_VERIFIED=true
```

Keep `KLAUS_CAPABILITY_ROUTINE_VERIFIED=false`,
`KLAUS_CAPABILITY_PUBLISH_VERIFIED=false`, and all routine cutover flags
`false`.

- [ ] **Step 3: Verify the deployed revision before writes**

Run:

```bash
gcloud run services describe klaus-agent \
  --project klaus-agent \
  --region me-west1 \
  --format=json \
| jq '{revision:.status.latestReadyRevisionName,traffic:.status.traffic,image:.spec.template.spec.containers[0].image,flags:[.spec.template.spec.containers[0].env[] | select(.name|test("^KLAUS_(USER_ID|MCP|CLAUDE|CAPABILITY|ROUTINE_)")) | {name,value}]}'

curl --fail --silent --show-error \
  https://klaus-agent-y2abtypx4q-zf.a.run.app/health

curl --silent --show-error --include \
  --request POST \
  --header 'content-type: application/json' \
  --data '{}' \
  https://klaus-agent-y2abtypx4q-zf.a.run.app/mcp/routine

gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="klaus-agent" AND severity>=ERROR' \
  --project klaus-agent \
  --limit 50 \
  --order=desc
```

Expected: 100% traffic to the newest revision, image tag matching the fix
commit, `KLAUS_USER_ID` present and positive, verified MCP/skill flags true,
routine cutover flags false, health status `ok`, routine endpoint `401` with
its OAuth resource metadata, and no new revision errors. Stop if any check
fails.

- [ ] **Step 4: Remove the original wrong-namespace UAT vector**

Through Claude, call `forget_memory` for exact vector ID
`677d9339-2fa7-4178-8b11-7331d164463e` with idempotency key
`uat-memory-forget-zero-20260809-001`. Approve once, recall the marker to prove
it is no longer surfaced to Claude, and independently fetch the exact ID from
Pinecone to prove the wrong-namespace vector was deleted.

- [ ] **Step 5: Repeat remember and recall in the canonical namespace**

Store a new isolated marker with idempotency key
`uat-memory-remember-canonical-20260809-001`, recall it, and record the returned
vector ID. Independently fetch the vector and assert `metadata.user_id` equals
the validated `KLAUS_CANONICAL_USER_ID` captured in Step 2 and its metadata
contains:

```json
{
  "kind": "fact"
}
```

The content must match the exact UAT marker and no duplicate vector may exist.

- [ ] **Step 6: Clean up the corrected UAT vector**

Forget the corrected vector by exact ID with a new idempotency key, confirm it
is absent from Pinecone, and verify the Firestore idempotency and action-audit
records for both remember and forget operations.

- [ ] **Step 7: Resume the subscription-first capability gate**

Only after the canonical namespace test passes, proceed to the prepared
high-risk action UAT, connect `/mcp/routine`, and prove unattended routine read
plus `publish_review`. Do not set routine capability flags or cut over morning,
nightly, or weekly delivery as part of this identity fix.
