# MCP Schemas and ACWR Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish Klaus's canonical legacy tool schemas through MCP and keep the Postgres activity summaries used by ACWR current from the daily Garmin sync.

**Architecture:** Preserve MCP's stable outer `arguments` envelope, but attach each canonical `core.tools.TOOL_SCHEMAS` input schema to that parameter through the callable signature consumed by `MCPServer`. Add a best-effort Postgres activity-summary upsert to the existing Garmin run-ingest batch and make its steady-state fetch cover the full 28-day ACWR window plus a seven-day margin.

**Tech Stack:** Python 3.13, Pydantic v2 JSON-schema annotations, MCP Python SDK, psycopg2, pytest.

## Global Constraints

- Preserve the `arguments` envelope expected by the MCP gateway and Claude skills.
- Preserve OAuth scopes, endpoint catalogs, idempotency enforcement, and audit behavior.
- Persist all Garmin activity types because ACWR measures total training load.
- A Postgres failure must not block Firestore run-detail ingestion.
- Keep all Claude cutover flags disabled during implementation and verification.
- Do not stage `.claude/scheduled_tasks.lock` or the untracked `AGENTS.md`.

---

### Task 1: Publish canonical MCP argument schemas

**Files:**
- Modify: `core/self_manifest.py`
- Modify: `interfaces/mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `core.tools.TOOL_SCHEMAS[*].input_schema`
- Produces: `_schema_metadata() -> dict[str, dict[str, Any]]`
- Produces: MCP tool parameters whose nested `arguments` schema contains the canonical properties and required fields

- [x] **Step 1: Write the failing schema-publication test**

```python
calendar_arguments = tools["list_calendar_events"].parameters["properties"]["arguments"]
assert set(calendar_arguments["properties"]) == {"time_min_iso", "time_max_iso"}
assert set(calendar_arguments["required"]) == {"time_min_iso", "time_max_iso"}
```

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py::test_legacy_tools_publish_their_exact_nested_argument_schemas -q
```

Expected: failure because the old MCP schema exposes only `additionalProperties: true`.

- [x] **Step 3: Carry input schemas through dependency-neutral metadata loading**

```python
rows.append({
    "name": name,
    "routing": routing,
    "purpose": purpose,
    "input_schema": schema.get("input_schema"),
})
```

- [x] **Step 4: Attach canonical JSON schema to the MCP callable signature**

```python
arguments_annotation = Annotated[
    dict[str, Any],
    WithJsonSchema(input_schema),
]
invoke.__signature__ = inspect.Signature(
    parameters=parameters,
    return_annotation=dict[str, Any],
)
```

- [x] **Step 5: Run the focused connector suite**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_server.py \
  tests/test_mcp_oauth.py \
  tests/test_mcp_runtime.py \
  tests/test_mcp_mounting.py \
  tests/test_claude_skills.py -q
```

Expected: all tests pass.

---

### Task 2: Refresh the ACWR activity source during Garmin sync

**Files:**
- Modify: `mcp_tools/garmin_tool.py`
- Modify: `core/run_ingest.py`
- Test: `tests/test_garmin_extensions.py`
- Test: `tests/test_run_ingest.py`

**Interfaces:**
- Produces: `upsert_activity_summaries_to_postgres(activities: list[dict]) -> int`
- Consumes: `fetch_garmin_activities(days: int) -> list[dict]`
- Produces: `run_one_batch()["activity_summaries_synced"]`

- [x] **Step 1: Write failing persistence and window tests**

```python
count = gt.upsert_activity_summaries_to_postgres(activities)
assert count == 2
assert "INSERT INTO activities" in fake_cursor.executemany.call_args.args[0]

fga.assert_called_once_with(35)
writer.assert_called_once_with(activities)
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_garmin_extensions.py::test_activity_summaries_upsert_refreshes_acwr_source \
  tests/test_run_ingest.py::test_delta_mode_uses_short_window \
  tests/test_run_ingest.py::test_every_fetched_activity_summary_is_persisted_before_run_filtering -q
```

Expected: failures because the writer does not exist, delta fetches only 14 days, and no summary upsert is called.

- [x] **Step 3: Implement the idempotent Postgres upsert**

```sql
INSERT INTO activities (
    activity_id, date, type, duration_sec, distance_m,
    training_load, perceived_exertion, feel
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (activity_id) DO UPDATE SET
    training_load = EXCLUDED.training_load,
    perceived_exertion = EXCLUDED.perceived_exertion,
    feel = EXCLUDED.feel
```

- [x] **Step 4: Wire the writer into the daily batch before run filtering**

```python
window = max(delta_days, acwr_days) if backfill_done else max(backfill_days, acwr_days)
activities = fetch_garmin_activities(window)
activity_summaries_synced = upsert_activity_summaries_to_postgres(activities)
```

- [x] **Step 5: Run focused and full offline verification**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_run_ingest.py \
  tests/test_garmin_extensions.py \
  tests/test_compute_acwr.py \
  tests/test_ingest_garmin.py \
  tests/test_ingest_schema.py -q

.venv/bin/python -m pytest -q \
  --ignore=tests/test_token_budget.py \
  --ignore=tests/memory/test_pinecone_embed.py
```

Expected: all offline tests pass. The two ignored files require live network services.

---

## Self-Review

- Spec coverage: MCP schema visibility, write idempotency visibility, ACWR source refresh, full-window fetch, and fail-open ingestion are covered.
- Placeholder scan: no deferred implementation steps or unspecified error handling remain.
- Type consistency: the writer accepts the normalized list returned by `fetch_garmin_activities` and returns the integer surfaced by `run_one_batch`.
