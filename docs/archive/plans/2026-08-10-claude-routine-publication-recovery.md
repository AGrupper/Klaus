# Claude Routine Publication Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish exact schemas for Klaus-specific MCP tools, reject incomplete nightly callbacks before side effects, repair the `2026-08-09` placeholder incident, and prove the corrected flow in shadow mode before any Claude routine cutover is re-enabled.

**Architecture:** Add a dependency-light custom JSON-schema registry that the MCP server merges with legacy tool metadata. Add a strict, pure nightly payload validator before the routine state transition. Keep the existing one-shot state machine, update the three routine skills to forbid write-based schema discovery, and use a preconditioned Firestore batch repair for the known incident.

**Tech Stack:** Python 3.13, MCP Python SDK, Pydantic v2 JSON-schema annotations, Google Cloud Firestore, pytest, deterministic ZIP packaging, Google Cloud Run.

## Global Constraints

- Keep `KLAUS_ROUTINE_MORNING_CUTOVER=false`, `KLAUS_ROUTINE_NIGHTLY_CUTOVER=false`, and `KLAUS_ROUTINE_WEEKLY_CUTOVER=false` through implementation, deployment, and shadow verification.
- Preserve the stable outer MCP `arguments` envelope, OAuth scopes, endpoint catalogs, idempotency, auditing, and the existing routine state machine.
- `publish_review` remains final and one-shot; no amend endpoint is added.
- No routine state transition, journal write, self-state patch, review write, behavioral-feedback write, or push may occur before payload validation succeeds.
- Do not fabricate a replacement reflection for `2026-08-09`.
- The repair may touch only the identified nightly review, journal, self-state incident fields, and routine-run incident metadata.
- Preserve `.claude/scheduled_tasks.lock` and the untracked `AGENTS.md`; never stage them.

---

### Task 1: Publish exact schemas for all custom MCP tools

**Files:**
- Create: `interfaces/mcp_custom_schemas.py`
- Modify: `interfaces/mcp_server.py:330-415`
- Modify: `tests/test_mcp_server.py:50-85`

**Interfaces:**
- Produces: `CUSTOM_TOOL_SCHEMAS: dict[str, dict[str, Any]]`
- Produces: `custom_tool_schema(name: str) -> dict[str, Any] | None`
- Consumes: custom schema metadata in `_register_tool(...)`
- Produces: exact nested MCP `arguments` schemas with `additionalProperties: false`

- [ ] **Step 1: Write the failing custom-schema catalog test**

```python
def test_custom_tools_publish_exact_nested_argument_schemas():
    from interfaces.mcp_custom_schemas import CUSTOM_TOOL_SCHEMAS
    from interfaces.mcp_server import create_mcp_bundle

    bundle = create_mcp_bundle(_oauth_service(), dispatcher=lambda _name, _args: "{}")
    interactive = {
        tool.name: tool for tool in bundle.interactive._tool_manager.list_tools()
    }
    routine = {tool.name: tool for tool in bundle.routine._tool_manager.list_tools()}

    for name, expected in CUSTOM_TOOL_SCHEMAS.items():
        tool = routine.get(name) or interactive.get(name)
        assert tool is not None, name
        actual = tool.parameters["properties"]["arguments"]
        assert actual["properties"] == expected["properties"], name
        assert actual.get("required", []) == expected.get("required", []), name
        assert actual["additionalProperties"] is False, name

    publish = routine["publish_review"].parameters["properties"]["arguments"]
    assert set(publish["required"]) == {
        "correlation_id", "routine", "target_date", "text",
        "structured", "action_ids", "partial_actions",
    }
    assert publish["properties"]["routine"]["enum"] == [
        "morning", "nightly", "weekly",
    ]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_server.py::test_custom_tools_publish_exact_nested_argument_schemas -q
```

Expected: FAIL because `publish_review` and the other custom tools expose only
`additionalProperties: true`.

- [ ] **Step 3: Implement the dependency-light custom schema registry**

Define exact contracts for every current custom handler. The `publish_review`
entry must be equivalent to:

```python
"publish_review": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "correlation_id": {"type": "string", "minLength": 1},
        "routine": {"type": "string", "enum": ["morning", "nightly", "weekly"]},
        "target_date": {"type": "string", "format": "date"},
        "text": {"type": "string", "minLength": 1},
        "structured": {"type": "object"},
        "action_ids": {"type": "array", "items": {"type": "string"}},
        "partial_actions": {"type": "array", "items": {"type": "object"}},
    },
    "required": [
        "correlation_id", "routine", "target_date", "text",
        "structured", "action_ids", "partial_actions",
    ],
}
```

The other schemas mirror their production handlers exactly, including bounded
health-query rows, portfolio quote provenance, prepared-action fields, and empty
objects for no-argument tools.

- [ ] **Step 4: Merge custom and legacy metadata in MCP registration**

```python
canonical = metadata.get(name, {})
input_schema = canonical.get("input_schema") or custom_tool_schema(name)
```

Change the `publish_review` description to state that it is final, one-shot, and
must never be called with schema probes, placeholders, or test content.

- [ ] **Step 5: Run focused MCP tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_server.py \
  tests/test_mcp_oauth.py \
  tests/test_mcp_mounting.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add interfaces/mcp_custom_schemas.py interfaces/mcp_server.py tests/test_mcp_server.py
git commit -m "fix: publish exact custom MCP schemas"
```

---

### Task 2: Reject incomplete nightly publications before side effects

**Files:**
- Modify: `interfaces/mcp_runtime.py:111-270`
- Modify: `tests/test_mcp_runtime.py:139-end`

**Interfaces:**
- Produces: `_validate_publish_review(arguments: dict[str, Any]) -> tuple[str, dict, list[str], list[dict]]`
- Consumes: canonical `publish_review.arguments`
- Guarantees: a failed validation has zero external side effects

- [ ] **Step 1: Write failing structural-validation tests**

```python
INCIDENT_PAYLOAD = {
    "correlation_id": "a485e1a9914893c100eb2dce1d25b53e",
    "routine": "nightly",
    "target_date": "2026-08-09",
    "text": "test text eighteen",
    "structured": {
        "reflection": {"summary": "test reflection", "mood": "steady"},
        "self_state": {"proposed_mood": "steady"},
        "quiet_night": True,
    },
    "action_ids": [],
    "partial_actions": [],
}

def test_validate_publish_review_rejects_incident_placeholder_shape():
    from interfaces.mcp_runtime import _validate_publish_review
    with pytest.raises(ValueError, match="current_focus"):
        _validate_publish_review(INCIDENT_PAYLOAD)

def test_validate_publish_review_accepts_complete_nightly_shape():
    from interfaces.mcp_runtime import _validate_publish_review
    text, structured, action_ids, partial_actions = _validate_publish_review(
        complete_nightly_payload()
    )
    assert text.startswith("Nightly review")
    assert structured["reflection"]["highlights"] == ["Good recovery"]
    assert action_ids == []
    assert partial_actions == []
```

- [ ] **Step 2: Write a failing zero-side-effect handler test**

Build handlers with monkeypatched `RoutineRunStore`, `JournalStore`,
`SelfStateStore`, `RoutineReviewStore`, `BehavioralFeedbackStore`, and
`send_push_to_all`. Call `publish_review` with `INCIDENT_PAYLOAD`, assert it raises,
and assert every transition/write/push spy remains empty.

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_runtime.py::test_validate_publish_review_rejects_incident_placeholder_shape \
  tests/test_mcp_runtime.py::test_invalid_nightly_publish_has_zero_side_effects -q
```

Expected: FAIL because the current validator accepts any reflection/self-state
objects and the handler can transition the routine.

- [ ] **Step 4: Implement strict pre-transition validation**

```python
def _require_nonempty_string(mapping: dict, field: str, *, parent: str) -> str:
    value = str(mapping.get(field) or "").strip()
    if not value:
        raise ValueError(f"{parent}.{field} is required")
    return value

def _validate_publish_review(arguments: dict) -> tuple[str, dict, list[str], list[dict]]:
    text, structured = _normalise_publish_review(arguments)
    action_ids = arguments.get("action_ids")
    partial_actions = arguments.get("partial_actions")
    if not isinstance(action_ids, list):
        raise ValueError("action_ids must be an array")
    if not isinstance(partial_actions, list):
        raise ValueError("partial_actions must be an array")
    if str(arguments.get("routine") or "") == "nightly":
        reflection = structured.get("reflection")
        self_state = structured.get("self_state")
        if not isinstance(reflection, dict):
            raise ValueError("structured.reflection must be an object")
        if not isinstance(self_state, dict):
            raise ValueError("structured.self_state must be an object")
        for field in ("summary", "mood", "current_focus", "recent_context"):
            _require_nonempty_string(reflection, field, parent="structured.reflection")
        if not isinstance(reflection.get("highlights"), list):
            raise ValueError("structured.reflection.highlights must be an array")
        for field in ("mood", "current_focus", "recent_context"):
            _require_nonempty_string(self_state, field, parent="structured.self_state")
    return text, structured, [str(item) for item in action_ids], list(partial_actions)
```

Call this validator before constructing stores, reading/transiting the run, or
performing any write. Reuse the returned normalized lists for shadow/live storage.

- [ ] **Step 5: Run runtime tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_runtime.py tests/test_subscription_routines.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add interfaces/mcp_runtime.py tests/test_mcp_runtime.py
git commit -m "fix: validate nightly callbacks before publication"
```

---

### Task 3: Make the hosted skill contract explicit and rebuild artifacts

**Files:**
- Modify: `claude/skills/klaus-morning-review/SKILL.md`
- Modify: `claude/skills/klaus-nightly-review/SKILL.md`
- Modify: `claude/skills/klaus-weekly-review/SKILL.md`
- Modify: `claude/dist/klaus-morning-review-7.0.0.zip`
- Modify: `claude/dist/klaus-nightly-review-7.0.0.zip`
- Modify: `claude/dist/klaus-weekly-review-7.0.0.zip`
- Modify: `claude/dist/manifest.json`
- Modify: `tests/test_claude_skills.py`

**Interfaces:**
- Consumes: exact connector schemas from Task 1
- Produces: uploaded skill instructions that permit exactly one final publication
- Produces: deterministic ZIPs matching canonical source files

- [ ] **Step 1: Read the writing-skills instructions completely**

Run the repository-available `superpowers:writing-skills` skill before editing any
`SKILL.md` file.

- [ ] **Step 2: Write the failing skill-contract test**

```python
def test_routine_skills_forbid_write_based_schema_discovery():
    routine_names = (
        "klaus-morning-review", "klaus-nightly-review", "klaus-weekly-review",
    )
    for name in routine_names:
        text = (ROOT / "claude" / "skills" / name / "SKILL.md").read_text().lower()
        assert "never call a write tool to discover its schema" in text
        assert "final and one-shot" in text
        assert "correlation_id" in text
        assert "partial_actions" in text

    nightly = (
        ROOT / "claude" / "skills" / "klaus-nightly-review" / "SKILL.md"
    ).read_text().lower()
    for field in ("summary", "mood", "current_focus", "recent_context", "highlights"):
        assert field in nightly
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claude_skills.py::test_routine_skills_forbid_write_based_schema_discovery -q
```

Expected: FAIL because the current skills do not name the canonical payload or
forbid schema-discovery writes.

- [ ] **Step 4: Update the three routine skills**

Add a complete publication contract to each skill:

```markdown
`publish_review` is final and one-shot. Never call a write tool to discover its
schema, and never send test, placeholder, or probe content. Finish the review and
check every field locally before the single call. Use the connector's published
schema as authoritative.

Pass `correlation_id`, `routine`, `target_date`, `text`, `structured`,
`action_ids`, and `partial_actions` inside `arguments`, plus one unique outer
`idempotency_key`.
```

The nightly skill additionally enumerates the complete reflection and self-state
fields required by Task 2.

- [ ] **Step 5: Rebuild and verify deterministic skill packages**

Run:

```bash
.venv/bin/python scripts/package_claude_skills.py
.venv/bin/python scripts/package_claude_skills.py --check
.venv/bin/python -m pytest tests/test_claude_skills.py -q
```

Expected: packager check and all skill tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add claude/skills/klaus-morning-review/SKILL.md \
  claude/skills/klaus-nightly-review/SKILL.md \
  claude/skills/klaus-weekly-review/SKILL.md \
  claude/dist/klaus-morning-review-7.0.0.zip \
  claude/dist/klaus-nightly-review-7.0.0.zip \
  claude/dist/klaus-weekly-review-7.0.0.zip \
  claude/dist/manifest.json tests/test_claude_skills.py
git commit -m "fix: make routine publication one-shot contract explicit"
```

---

### Task 4: Build and test the exact production incident repair

**Files:**
- Create: `scripts/repair_claude_routine_incident.py`
- Create: `tests/test_repair_claude_routine_incident.py`

**Interfaces:**
- Produces: `repair_incident(client, *, repaired_at: str) -> dict[str, Any]`
- Consumes: a Firestore-compatible client supporting document reads and batch writes
- Guarantees: exact preconditions, all-or-nothing batch, idempotent rerun, redacted summary

- [ ] **Step 1: Write failing exact-match and preservation tests**

Use small fake Firestore references/batches. Seed the exact observed review,
journal, self-state, and routine-run documents. Assert:

```python
result = repair_incident(client, repaired_at="2026-08-10T09:00:00+00:00")
assert result["repaired"] is True
assert client.docs[REVIEW_PATH]["review_text"].startswith("Invalidated nightly review")
assert JOURNAL_PATH not in client.docs
assert "proposed_mood" not in client.docs[SELF_STATE_PATH]
assert "source" not in client.docs[SELF_STATE_PATH]
assert "reflection_date" not in client.docs[SELF_STATE_PATH]
assert client.docs[SELF_STATE_PATH]["daily_note_date"] == "2026-08-10"
assert client.docs[RUN_PATH]["incident_invalidated"] is True
```

Add tests proving an altered correlation ID/placeholder aborts before `commit`, and
an already-repaired set returns `repaired=False, already_repaired=True`.

- [ ] **Step 2: Run repair tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_repair_claude_routine_incident.py -q
```

Expected: FAIL because the repair module does not exist.

- [ ] **Step 3: Implement preconditioned batch repair**

Use constants for the four exact document paths, correlation ID, date, placeholder
review, and placeholder structured objects. Read every document before creating
writes. For an unrepaired incident:

```python
batch.set(review_ref, {
    "review_text": INVALIDATED_REVIEW_TEXT,
    "structured": {
        "invalidated": True,
        "reason": INCIDENT_REASON,
        "original_placeholder_removed": True,
    },
    "invalidated_at": repaired_at,
    "invalid_reason": INCIDENT_REASON,
}, merge=True)
batch.delete(journal_ref)
batch.update(self_state_ref, {
    "source": firestore.DELETE_FIELD,
    "reflection_date": firestore.DELETE_FIELD,
    "proposed_mood": firestore.DELETE_FIELD,
    "incident_repaired_at": repaired_at,
})
batch.set(run_ref, {
    "incident_invalidated": True,
    "incident_reason": INCIDENT_REASON,
    "incident_repaired_at": repaired_at,
}, merge=True)
batch.commit()
```

The CLI defaults to dry-run and requires `--apply` for production mutation.

- [ ] **Step 4: Run repair tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_repair_claude_routine_incident.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add scripts/repair_claude_routine_incident.py \
  tests/test_repair_claude_routine_incident.py
git commit -m "fix: add guarded Claude routine incident repair"
```

---

### Task 5: Verify, repair production, deploy safely, and run a shadow canary

**Files:**
- Verify only: all files changed in Tasks 1-4
- Production writes: the four incident-scoped Firestore documents from Task 4

**Interfaces:**
- Consumes: test suites, repair CLI, Cloud Run deployment, `/api/routines/nightly/shadow`
- Produces: disabled-cutover deployment and evidence for a future nightly re-enable decision

- [ ] **Step 1: Run focused verification**

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_server.py \
  tests/test_mcp_oauth.py \
  tests/test_mcp_runtime.py \
  tests/test_mcp_mounting.py \
  tests/test_subscription_routines.py \
  tests/test_claude_skills.py \
  tests/test_repair_claude_routine_incident.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the full offline suite**

```bash
.venv/bin/python -m pytest -q \
  --ignore=tests/test_token_budget.py \
  --ignore=tests/memory/test_pinecone_embed.py
```

Expected: all offline tests pass; only the two explicit live-service suites are excluded.

- [ ] **Step 3: Verify production cutover containment before writes**

```bash
gcloud run services describe klaus-agent \
  --project klaus-agent --region me-west1 \
  --format='value(spec.template.spec.containers[0].env)'
```

Expected: morning, nightly, and weekly cutover values are all `false`.

- [ ] **Step 4: Dry-run and apply the incident repair**

```bash
.venv/bin/python scripts/repair_claude_routine_incident.py
.venv/bin/python scripts/repair_claude_routine_incident.py --apply
.venv/bin/python scripts/repair_claude_routine_incident.py
```

Expected: first run reports the exact eligible changes, apply commits one batch,
and the final dry-run reports `already_repaired`.

- [ ] **Step 5: Deploy with cutovers explicitly disabled**

Use the repository's existing deployment path, then enforce:

```bash
gcloud run services update klaus-agent \
  --project klaus-agent --region me-west1 \
  --update-env-vars \
KLAUS_ROUTINE_MORNING_CUTOVER=false,KLAUS_ROUTINE_NIGHTLY_CUTOVER=false,KLAUS_ROUTINE_WEEKLY_CUTOVER=false
```

Verify the latest ready revision serves 100% of traffic and all three flags remain false.

- [ ] **Step 6: Run one nightly shadow canary**

Invoke `POST /api/routines/nightly/shadow` for `2026-08-10`, capture the returned
correlation ID, wait for Claude completion, and inspect the routine run. Verify one
complete `shadow_review`, no push, and no change to the live nightly review,
`journal/2026-08-10`, or `config/self_state` attributable to the shadow callback.

- [ ] **Step 7: Stop before live re-enable**

Report the shadow evidence to Amit. Do not set
`KLAUS_ROUTINE_NIGHTLY_CUTOVER=true` without a new explicit approval after he has
also replaced the uploaded routine skills/ZIPs and refreshed the connector schema.

---

## Self-Review

- Spec coverage: containment, exact custom schemas, pre-transition validation,
  one-shot skill instructions, deterministic packaging, guarded data repair,
  disabled-cutover deployment, and shadow proof all have explicit tasks.
- Placeholder scan: no deferred implementation, unspecified tests, or ambiguous
  production targets remain.
- Type consistency: Task 1 publishes the fields consumed by Task 2; Task 3 repeats
  those exact names; Task 4 uses the exact incident identifiers observed in
  production; Task 5 consumes the committed artifacts from Tasks 1-4.
- Scope check: notification-display troubleshooting remains intentionally separate
  because the morning backend run succeeded and that issue does not share the
  publication-schema root cause.
