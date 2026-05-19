# Phase 16: Self-Model & State Awareness - Pattern Map

**Mapped:** 2026-05-18
**Files analyzed:** 7
**Analogs found:** 6 / 7 (cloudbuild.yaml has no prior analog in repo; deploy.yml serves as reference)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `core/self_manifest.py` (NEW) | utility | transform | `mcp_tools/self_inspect.py` | role-match |
| `docs/SELF.md` (GENERATED) | config | — | none (generated artifact) | no-analog |
| `memory/firestore_db.py` (MODIFY) | store | CRUD | `memory/firestore_db.py` HeartbeatConfigStore | exact |
| `core/main.py` (MODIFY) | controller | request-response | `core/main.py` AgentOrchestrator | exact (self-modify) |
| `core/tools.py` (MODIFY) | utility | request-response | `core/tools.py` `list_own_files` / `remember` | exact (self-modify) |
| `core/heartbeat.py` (MODIFY) | service | event-driven | `core/heartbeat.py` `check_code()` docs-drift check | exact (self-modify) |
| `cloudbuild.yaml` (MODIFY) | config | — | `.github/workflows/deploy.yml` | partial (different CI system) |

---

## Pattern Assignments

### `core/self_manifest.py` (utility, transform)

**Analog:** `mcp_tools/self_inspect.py`

**Module header / imports pattern** (`mcp_tools/self_inspect.py` lines 1–18):
```python
"""Codebase self-inspection tools for the Klaus agent.

Provides three functions that let Klaus read and search his own deployed source
at conversation time. These functions are intentionally read-only and apply a
secret denylist so Klaus can never expose credentials via tool output.

Registration: core/tools.py registers these as SMART_AGENT_DIRECT_TOOLS
(brain-only, never delegated to the worker).
"""
from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
```

**Source root discovery pattern** (`mcp_tools/self_inspect.py` lines 27–31):
```python
def _get_source_root() -> Path:
    env_override = os.environ.get("SOURCE_ROOT")
    if env_override:
        return Path(env_override).resolve()
    return Path(__file__).resolve().parent.parent
```
Note: `core/self_manifest.py` lives in `core/`, so `Path(__file__).resolve().parent.parent` already resolves to project root — same formula works.

**File reading with error handling** (`mcp_tools/self_inspect.py` lines 171–178):
```python
try:
    content = target.read_text(encoding="utf-8", errors="replace")
except OSError as exc:
    logger.warning("read_own_source: cannot read %s: %s", target, exc)
    return {"error": f"Cannot read file: {exc}"}
```

**Return dict convention** (`mcp_tools/self_inspect.py` lines 98–99):
```python
Returns:
    {"files": ["path/to/file.py", ...], "count": N, "root": "/abs/path"}
```
`generate_manifest()` should return `{"path": "docs/SELF.md", "sha": "<hash>", "sections": N}` on success or `{"error": "..."}` on failure — same dict-return convention.

**`generate_manifest()` main entrypoint structure** — copy the module-level `__main__` pattern from `self_inspect.py`; add:
```python
if __name__ == "__main__":
    import sys
    result = generate_manifest()
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"SELF.md written — sha={result['sha']}")
```

---

### `memory/firestore_db.py` — new `SelfStateStore` class (store, CRUD)

**Analog:** `HeartbeatConfigStore` (`memory/firestore_db.py` lines 406–439)

**Class skeleton with singleton document pattern** (lines 406–439):
```python
class HeartbeatConfigStore:
    """Read/write heartbeat scheduler config stored in Firestore.

    Config doc lives at collection='config', document='heartbeat'.
    If the document is absent, defaults are returned without writing them.
    """

    _COLLECTION = "config"
    _DOCUMENT = "heartbeat"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)

    def get(self) -> dict:
        """Return the heartbeat config, falling back to defaults for missing fields."""
        try:
            snap = self._doc_ref.get()
            stored = snap.to_dict() or {} if snap.exists else {}
        except GoogleAPICallError:
            logger.warning("HeartbeatConfigStore.get() failed — using defaults")
            stored = {}
        return {**_HEARTBEAT_CONFIG_DEFAULTS, **stored}

    def set(self, patch: dict) -> None:
        """Merge `patch` into the stored config document (creates it if absent)."""
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except GoogleAPICallError:
            logger.error("HeartbeatConfigStore.set() failed")
            raise
```

**`SelfStateStore` adaptation notes:**
- `_COLLECTION = "config"`, `_DOCUMENT = "self_state"` (one singleton doc)
- `get()`: catch `Exception` (not just `GoogleAPICallError`) → return `{}` on any error, never raise (D-05 graceful fallback)
- Add `bootstrap_if_empty(identity_summary: str) -> None`: read the doc; if `snap.exists` is False, call `self._doc_ref.set({"identity_summary": identity_summary, "current_focus": "", "recent_context": "", "mood": "", "bootstrapped_at": firestore.SERVER_TIMESTAMP})`. Never overwrites existing doc.
- `set(patch)`: same as `HeartbeatConfigStore.set()` — merge=True, SERVER_TIMESTAMP

**`LLMUsageStore` reference for `get_self_status`** (lines 563–598) — call `LLMUsageStore(...).summary("today")` and read `today_data.get("smart_calls", 0)` as message count proxy (D-06).

---

### `core/main.py` — prompt render step + `__init__` bootstrap (controller, request-response)

**Analog:** `core/main.py` itself (self-modify)

**Prompt render step** (lines 219–222):
```python
# Inject today's date in Israel time so the agent has accurate temporal context.
today_label = _today_israel()
smart_system = self._smart_prompt_template.replace("{today_date}", today_label)
worker_system = self._worker_prompt_template.replace("{today_date}", today_label)
```
Phase 16 extends this block. New code inserts SELF.md content and self_state snippet into `smart_system` using the same chained `.replace()` pattern:
```python
smart_system = (
    self._smart_prompt_template
    .replace("{today_date}", today_label)
    .replace("{self_md}", self._self_md_content)        # full SELF.md
    .replace("{self_state}", self._self_state_snippet)  # compact non-empty fields
)
```
Stable content (`{self_md}`) must appear before dynamic content (`{today_date}`) in the template for Gemini prompt caching (D-03).

**`AgentOrchestrator.__init__` pattern** (lines 167–201):
```python
def __init__(self) -> None:
    # ... LLMClient construction ...
    # Load prompts from disk at startup — avoids repeated file I/O per message.
    self._smart_prompt_template = _load_prompt("prompts/smart_agent.md")
    self._worker_prompt_template = _load_prompt("prompts/worker_agent.md")
    self.conversation_manager = build_conversation_store_from_env()
```
Phase 16 adds after the prompt loading block:
```python
# Load SELF.md content once at startup for prompt injection.
self._self_md_content = _load_self_md()          # reads docs/SELF.md; "" on missing
# Bootstrap self_state in Firestore if this is first startup.
self._self_state_store = _build_self_state_store()
self._self_state_store.bootstrap_if_empty(
    identity_summary=_extract_intro_paragraph(self._self_md_content)
)
```

---

### `core/tools.py` — `get_self_status` direct tool (utility, request-response)

**Analog:** `core/tools.py` — existing direct tool pattern (`list_own_files`, `remember`)

**Site 1 — `SMART_AGENT_DIRECT_TOOLS` frozenset** (lines 39–47):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember",
    "recall",
    "run_morning_briefing",
    "search_chat_history",
    "list_own_files",
    "read_own_source",
    "search_own_source",
    # ADD: "get_self_status",
})
```

**Site 2 — `TOOL_SCHEMAS` entry** (lines 574–595 show list_own_files as template):
```python
{
    "name": "list_own_files",
    "description": (
        "List Klaus's deployed source files. "
        "Call this directly — do NOT delegate to the worker. "
        ...
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subdir": { "type": "string", ... },
        },
        "required": [],
    },
},
```
`get_self_status` schema has `"required": []` and no required parameters (all fields computed internally).

**Site 3 — `WORKER_TOOL_SCHEMAS` exclusion set** (lines 675–686):
```python
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        "delegate_to_worker",
        "remember",
        "recall",
        "search_chat_history",
        "list_own_files",
        "read_own_source",
        "search_own_source",
        # ADD: "get_self_status",
    }
]
```

**Site 4 — `_handle_get_self_status()` function** (pattern from `_handle_list_own_files` lines 1079–1082):
```python
def _handle_list_own_files(subdir: str | None = None) -> str:
    """List Klaus's source files, optionally filtered to a subdirectory."""
    result = _list_own_files(subdir=subdir)
    return json.dumps(result)
```
`_handle_get_self_status()` calls into `core/self_manifest.py` and `LLMUsageStore`, aggregates the five data points (identity, capabilities, uptime, message count, active limits), returns `json.dumps(result)`.

**Site 5 — `_HANDLERS` dispatch dict** (lines 1101–1129):
```python
_HANDLERS: dict[str, object] = {
    ...
    "list_own_files":  lambda args: _handle_list_own_files(**args),
    # ADD:
    "get_self_status": lambda args: _handle_get_self_status(**args),
    ...
}
```

---

### `core/heartbeat.py` — extend `check_code()` with SELF.md SHA staleness (service, event-driven)

**Analog:** `core/heartbeat.py` `check_code()` (lines 378–474) — docs-drift check block is the direct template

**Signal dataclass** (lines 38–54):
```python
@dataclass
class Signal:
    fingerprint: str
    severity: str
    area: str
    title: str
    detail: str
    remediation: str
```

**Docs-drift check structure to copy** (lines 387–427):
```python
try:
    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        ...
        if missing_paths:
            signals.append(Signal(
                fingerprint="code:docs-drift",
                severity=SEVERITY_FYI, area="code",
                title="CLAUDE.md references paths that don't exist",
                detail=f"{len(missing_paths)} missing: ...",
                remediation="Update the directory tree in CLAUDE.md to match the current codebase.",
            ))
except Exception:
    logger.warning("heartbeat: docs-drift check failed", exc_info=True)
```

**SHA staleness check to add** — new block appended inside `check_code()` before `return signals`:
```python
# --- SELF.md SHA staleness: embedded hash vs fresh tool-schema hash ---
try:
    self_md = root / "docs" / "SELF.md"
    if self_md.exists():
        content = self_md.read_text(encoding="utf-8")
        # Extract embedded SHA line: "<!-- sha: <hash> -->"
        stored_sha = ...  # parse from content
        # Recompute hash of current tool schemas + cron routes
        fresh_sha = ...
        if stored_sha and stored_sha != fresh_sha:
            signals.append(Signal(
                fingerprint="code:self-md-stale",
                severity=SEVERITY_FYI, area="code",
                title="SELF.md SHA is stale — tool schemas may have changed",
                detail=f"stored={stored_sha[:8]} fresh={fresh_sha[:8]}",
                remediation="Run 'python core/self_manifest.py' or redeploy to regenerate SELF.md.",
            ))
except Exception:
    logger.warning("heartbeat: self-md-sha check failed", exc_info=True)
```
Severity = `SEVERITY_FYI`, tier = `"weekly"` — matches the existing docs-drift and stale-todos checks.

**`_collect_signals()` wiring** (lines 547–559) — `check_code()` is already called there under `if weekly:`; the new SHA check lives inside `check_code()` itself so no changes to `_collect_signals()` are needed.

---

### `cloudbuild.yaml` — add `python core/self_manifest.py` step

**Analog:** `.github/workflows/deploy.yml` (partial — different CI system; this is Cloud Build YAML)

**No prior `cloudbuild.yaml` exists in the repo.** The deploy pipeline lives entirely in `.github/workflows/deploy.yml` (GitHub Actions). The CONTEXT.md decision D-01 says to add a Cloud Build step, but given the actual deploy pipeline is GitHub Actions, the planner should clarify whether:
1. A new `cloudbuild.yaml` is created for GCP Cloud Build (separate pipeline), OR
2. The manifest generation step is added to `.github/workflows/deploy.yml` as a `run: python core/self_manifest.py` step before `docker build`.

**GitHub Actions step pattern** (from `.github/workflows/deploy.yml` lines 46–47):
```yaml
- name: Build Docker image
  run: docker build -t "$IMAGE" .
```
If adding to GitHub Actions, insert before docker build:
```yaml
- name: Generate SELF.md capability manifest
  run: python core/self_manifest.py
```

**Cloud Build step pattern** (standard GCP Cloud Build format — no existing file to copy from):
```yaml
steps:
  - name: 'python:3.12-slim'
    entrypoint: 'python'
    args: ['core/self_manifest.py']
    id: 'generate-self-manifest'
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '$_IMAGE', '.']
    waitFor: ['generate-self-manifest']
```

---

## Shared Patterns

### Firestore client construction
**Source:** `memory/firestore_db.py` lines 24–40
**Apply to:** `SelfStateStore.__init__`
```python
def _make_firestore_client(project_id: str, database: str) -> firestore.Client:
    credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/datastore"],
        )
        return firestore.Client(
            project=project_id, credentials=credentials, database=database
        )
    return firestore.Client(project=project_id, database=database)
```

### Never-raise store pattern
**Source:** `memory/firestore_db.py` `LLMUsageStore.record()` lines 541–561
**Apply to:** `SelfStateStore.get()` and `SelfStateStore.bootstrap_if_empty()`
```python
def record(self, ...) -> None:
    """Increment today's usage doc. Never raises."""
    try:
        ...
    except Exception:
        logger.warning("LLMUsageStore.record() failed", exc_info=True)
```
`SelfStateStore.get()` must return `{}` on any error, never raise (D-05). `bootstrap_if_empty()` logs a warning and returns silently on failure.

### Direct tool JSON serialization
**Source:** `core/tools.py` lines 1079–1094
**Apply to:** `_handle_get_self_status()`
```python
def _handle_list_own_files(subdir: str | None = None) -> str:
    result = _list_own_files(subdir=subdir)
    return json.dumps(result)
```
All direct tool handlers return `json.dumps(result)` — never a raw dict.

### Signal construction
**Source:** `core/heartbeat.py` lines 419–425
**Apply to:** SELF.md SHA staleness check in `check_code()`
```python
signals.append(Signal(
    fingerprint="code:docs-drift",
    severity=SEVERITY_FYI, area="code",
    title="...",
    detail="...",
    remediation="...",
))
```
Use `fingerprint="code:self-md-stale"`, `severity=SEVERITY_FYI`, `area="code"`.

### `from __future__ import annotations` + logger
**Source:** `mcp_tools/self_inspect.py` lines 10–18 / `core/heartbeat.py` lines 12–23
**Apply to:** `core/self_manifest.py`
Every new module opens with `from __future__ import annotations` and `logger = logging.getLogger(__name__)`.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `docs/SELF.md` | generated doc | — | Purely generated output artifact; content determined by `generate_manifest()` logic and D-02 specifics |
| `cloudbuild.yaml` | CI config | — | No Cloud Build yaml exists in repo; deploy pipeline uses GitHub Actions. Planner must decide whether to add step to existing `deploy.yml` or create a new `cloudbuild.yaml` |

---

## Metadata

**Analog search scope:** `core/`, `mcp_tools/`, `memory/`, `.github/workflows/`
**Files scanned:** 8
**Pattern extraction date:** 2026-05-18
