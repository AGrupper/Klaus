# Phase 22: Expert Coaching Knowledge + D-13 Release - Pattern Map

**Mapped:** 2026-06-04
**Files analyzed:** 8 (3 new, 5 modified)
**Analogs found:** 8 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `docs/COACHING_GUIDE.md` | config/docs | file-I/O (read-only, authored content) | `docs/SELF.md` (structure); `docs/hybrid_athlete_blueprint.md` (content framing) | role-match |
| `core/main.py` — `_load_coaching_guide_slim()` + `__init__` startup-cache | utility | file-I/O | `core/main.py:757` `_load_self_md()` + line 219 startup assignment | exact |
| `core/main.py` — `render_smart_system` `{coaching_guide}` substitution | utility | request-response | `core/main.py:416–422` existing `.replace("{self_md}", ...)` chain | exact |
| `core/tools.py` — `read_coaching_guide` schema | config | request-response | `core/tools.py:655–666` `get_training_profile` schema; `core/tools.py:526–544` `read_own_source` schema | exact |
| `core/tools.py` — `_handle_read_coaching_guide` handler | utility | file-I/O | `core/tools.py:1146–1155` `_handle_read_own_source` handler | exact |
| `core/tools.py` — `_HANDLERS` + `SMART_AGENT_DIRECT_TOOLS` registration | config | request-response | `core/tools.py:39–57` `SMART_AGENT_DIRECT_TOOLS`; `core/tools.py:1492` `_HANDLERS` entry for `get_training_profile` | exact |
| `prompts/smart_agent.md` | config/prompt | request-response | `prompts/smart_agent.md:105–136` existing Tier A/B block + sharper-edge block | exact (self-analog — hardens existing text) |
| `core/morning_briefing.py` + `core/proactive_alerts.py` slim-core injection | utility | request-response | Each file's own `_compose_briefing` / `_compose_alert` `{today_date}` `.replace()` pattern | exact (self-analog) |
| `tests/test_main_render_smart_system.py` | test | request-response | `tests/test_main_render_smart_system.py:232–294` `TestPhase19TrainingProfile` class | exact |
| `tests/test_tools.py` | test | request-response | `tests/test_tools.py:326–394` `TestPhase19ToolRegistration` class | exact |

---

## Pattern Assignments

### `docs/COACHING_GUIDE.md` (content/docs, file-I/O)

**Analog:** `docs/SELF.md` (structure), `docs/hybrid_athlete_blueprint.md` (content framing)

**Structure pattern** (`docs/SELF.md` lines 1–15 — front-matter + H2 sections):
```markdown
---
generated_at: ...
---

# Klaus — Capability Manifest

## Identity
...

## Model Map
...
```

**Required structure for COACHING_GUIDE.md** — the slim-core markers and section-slug anchors are load-critical (the loader and tool regex depend on them):

```markdown
<!-- SLIM_CORE_START -->
## Core Principles Digest

### AM/PM Split — The Interference Mitigation Rule
### Session-by-Session Execution Cues
### Fueling Slot Map
### Key Critique Flags
### Tier A/B Quick Reference
<!-- SLIM_CORE_END -->

<!-- SECTION: interference-effect -->
## Concurrent Training & The Interference Effect
...

<!-- SECTION: block-periodization -->
## Block Periodization
...

<!-- SECTION: threshold-runs -->
## Threshold Runs
...

<!-- SECTION: top-set-strength -->
## Top-Set Strength
...

<!-- SECTION: calisthenics-progressions -->
## Calisthenics Progressions
...

<!-- SECTION: intervals-vo2max -->
## Intervals & VO2 Max
...

<!-- SECTION: peri-workout-fueling -->
## Peri-Workout Fueling
...

<!-- SECTION: protein-timing -->
## Protein Timing
...

<!-- SECTION: carb-periodization -->
## Carbohydrate Periodization
...

<!-- SECTION: supplements -->
## Supplement Rationale
...
```

**Key constraint:** `<!-- SLIM_CORE_START -->` / `<!-- SLIM_CORE_END -->` delimiters must be present — `_load_coaching_guide_slim()` extracts exactly that block. Each `<!-- SECTION: slug -->` must be present — `_handle_read_coaching_guide` uses a regex on this anchor.

---

### `core/main.py` — `_load_coaching_guide_slim()` and startup-cache (utility, file-I/O)

**Analog:** `core/main.py:757–769` `_load_self_md()`

**Exact analog** (lines 757–769):
```python
def _load_self_md() -> str:
    """Read docs/SELF.md from disk. Returns empty string if file absent.

    Called once at startup; the result is stored on the orchestrator and
    injected into every smart_system prompt without further file I/O.
    """
    root = Path(__file__).resolve().parent.parent
    self_md_path = root / "docs" / "SELF.md"
    try:
        return self_md_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("SELF.md not found at %s — self-knowledge injection disabled", self_md_path)
        return ""
```

**New function to write — mirror exactly, then add slim-core extraction:**
```python
def _load_coaching_guide_slim() -> str:
    """Read the slim core digest block from docs/COACHING_GUIDE.md.

    Extracts only the content between <!-- SLIM_CORE_START --> and
    <!-- SLIM_CORE_END --> markers. Returns empty string if file absent
    or markers not found. Called once at startup; stored on orchestrator.
    Per D-04: only the slim core (~200–300 lines) is injected as a
    stable cached prefix. Full guide is read on-demand by read_coaching_guide().
    """
    root = Path(__file__).resolve().parent.parent
    guide_path = root / "docs" / "COACHING_GUIDE.md"
    try:
        content = guide_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "COACHING_GUIDE.md not found at %s — coaching knowledge injection disabled",
            guide_path,
        )
        return ""
    # Extract slim core block between markers
    import re as _re
    m = _re.search(
        r"<!-- SLIM_CORE_START -->(.*?)<!-- SLIM_CORE_END -->",
        content,
        _re.DOTALL,
    )
    if not m:
        logger.warning("COACHING_GUIDE.md: <!-- SLIM_CORE_START/END --> markers not found — "
                       "returning empty coaching injection")
        return ""
    slim = m.group(1).strip()
    # Sanity guard: warn if the slim core is suspiciously large (Pitfall 2)
    if len(slim) > 10_000:
        logger.warning(
            "COACHING_GUIDE.md slim core is %d chars — larger than expected (~4000). "
            "Check SLIM_CORE_START/END markers.", len(slim)
        )
    return slim
```

**Startup-cache in `AgentOrchestrator.__init__`** — add immediately after line 219 (`self._self_md_content = _load_self_md()`):
```python
# Load slim coaching guide digest once at startup.
# Per D-04: only the slim core digest (~200–300 lines) is injected as a
# stable cached prefix. The full guide is read on-demand by read_coaching_guide().
self._coaching_guide_content = _load_coaching_guide_slim()
```

---

### `core/main.py` — `render_smart_system` `{coaching_guide}` substitution (utility, request-response)

**Analog:** `core/main.py:416–423` — the `.replace()` chain at the end of `render_smart_system`

**Exact analog** (lines 416–423):
```python
        return (
            template
            .replace("{self_md}", self._self_md_content)      # stable — benefits from cache
            .replace("{self_state}", self_state_snippet)       # volatile — after stable
            .replace("{journal_digest}", journal_digest)       # Phase 17 — smart-only (D-15)
            .replace("{training_profile}", training_profile_snippet)  # PHASE 19 — PROMPT-01
            .replace("{today_date}", today_label)              # dynamic — always last
        )
```

**Modified return block** — insert `{coaching_guide}` as the FIRST substitution (stable prefix before `{self_md}`):
```python
        return (
            template
            .replace("{coaching_guide}", self._coaching_guide_content)  # PHASE 22 — stable, first
            .replace("{self_md}", self._self_md_content)                 # stable — benefits from cache
            .replace("{self_state}", self_state_snippet)                 # volatile — after stable
            .replace("{journal_digest}", journal_digest)                 # Phase 17 — smart-only (D-15)
            .replace("{training_profile}", training_profile_snippet)     # PHASE 19 — PROMPT-01
            .replace("{today_date}", today_label)                        # dynamic — always last
        )
```

**Critical ordering rule:** `{coaching_guide}` must precede `{self_state}` and `{today_date}` in the chain. Stable content first preserves Gemini's cached-prefix optimization (see also Pitfall 1 in RESEARCH.md).

---

### `core/tools.py` — `read_coaching_guide` schema (config, request-response)

**Analog:** `core/tools.py:653–666` `get_training_profile` schema + `core/tools.py:526–544` `read_own_source` schema

**Exact analog** (lines 653–666):
```python
    {
        "name": "get_training_profile",
        "description": (
            "Read Sir's stored training profile (athletic_goals, training_constraints, "
            "recovery_preferences). Brain-direct — call this when you need to know "
            "Sir's coaching context before answering or planning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
```

**New schema to add** — place after the `get_training_profile` block (~line 666), before the next schema entry:
```python
    # ============ PHASE 22 — COACHING GUIDE ON-DEMAND LOOKUP ============
    {
        "name": "read_coaching_guide",
        "description": (
            "Read a deep section of the coaching knowledge guide. Brain-direct. "
            "Call when Sir asks 'why?' about a training concept, or when the slim "
            "core digest (already in your system prompt) is not detailed enough. "
            "Returns the full section text for the requested topic. "
            "Do NOT call for routine coaching messages — the slim core covers those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Section to retrieve. Use one of: 'interference-effect', "
                        "'block-periodization', 'threshold-runs', 'top-set-strength', "
                        "'calisthenics-progressions', 'intervals-vo2max', "
                        "'peri-workout-fueling', 'protein-timing', "
                        "'carb-periodization', 'supplements'. "
                        "Free-text also accepted — nearest section slug is matched."
                    ),
                },
            },
            "required": ["topic"],
        },
    },
```

---

### `core/tools.py` — `_handle_read_coaching_guide` handler (utility, file-I/O)

**Analog:** `core/tools.py:1146–1155` `_handle_read_own_source` (thin wrapper calling a helper) and `core/tools.py:1318–1330` `_handle_get_training_profile` (file read + JSON return)

**Exact analog** (lines 1146–1155):
```python
def _handle_read_own_source(path: str) -> str:
    """Return the contents of a source file, with denylist and traversal protection."""
    result = _read_own_source(path=path)
    return json.dumps(result)
```

**Exact analog** (lines 1318–1330):
```python
def _handle_get_training_profile() -> str:
    """PROFILE-04 brain-direct: return the user training profile dict as JSON.

    Uses _jsonsafe_doc to ISO-convert any DatetimeWithNanoseconds values
    (e.g. updated_at, bootstrapped_at) before json.dumps so this handler
    never raises a TypeError on a real Firestore doc.  T-21-04 mitigation.
    """
    from memory.firestore_db import UserProfileStore, _jsonsafe_doc
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(_jsonsafe_doc(store.load()))
```

**New handler to write** — add after `_handle_get_training_profile` (~line 1330):
```python
def _handle_read_coaching_guide(topic: str) -> str:
    """COACH-01 brain-direct: return the coaching guide section for the requested topic.

    Reads docs/COACHING_GUIDE.md, finds the <!-- SECTION: {slug} --> anchor,
    and returns the section text as JSON. Fuzzy fallback on partial word match.
    """
    import re as _re
    root = Path(__file__).resolve().parent.parent
    guide_path = root / "docs" / "COACHING_GUIDE.md"
    try:
        content = guide_path.read_text(encoding="utf-8")
    except OSError:
        return json.dumps({"error": "COACHING_GUIDE.md not found"})

    # Normalize topic slug
    slug = topic.strip().lower().replace(" ", "-").replace("_", "-")

    # Find section by anchor <!-- SECTION: slug -->
    pattern = _re.compile(
        r"<!-- SECTION: " + _re.escape(slug) + r" -->(.*?)(?=<!-- SECTION:|$)",
        _re.DOTALL | _re.IGNORECASE,
    )
    m = pattern.search(content)
    if m:
        return json.dumps({"topic": slug, "content": m.group(1).strip()})

    # Fuzzy fallback: first section whose anchor contains any word of the query
    for word in slug.split("-"):
        if not word:
            continue
        fallback = _re.compile(
            r"<!-- SECTION: [^>]*" + _re.escape(word) + r"[^>]* -->(.*?)(?=<!-- SECTION:|$)",
            _re.DOTALL | _re.IGNORECASE,
        )
        fm = fallback.search(content)
        if fm:
            return json.dumps({"topic": slug, "content": fm.group(1).strip()})

    return json.dumps({"error": f"Section '{topic}' not found in COACHING_GUIDE.md"})
```

---

### `core/tools.py` — `SMART_AGENT_DIRECT_TOOLS` + `WORKER_TOOL_SCHEMAS` + `_HANDLERS` registration (config, request-response)

**Analog — `SMART_AGENT_DIRECT_TOOLS`** (lines 39–57):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember",
    ...
    # Phase 19 Plan 02 — brain-direct training-profile tools (PROFILE-04)
    "get_training_profile",
    "update_training_profile",
    # Phase 21 Plan 02 — update_plan alias (PLAN-03 / SC-3)
    "update_plan",
    ...
})
```

**Addition:** Add `"read_coaching_guide"` to `SMART_AGENT_DIRECT_TOOLS` with a Phase 22 comment:
```python
    # Phase 22 — brain-direct coaching guide on-demand lookup (COACH-01)
    "read_coaching_guide",
```

**Analog — `WORKER_TOOL_SCHEMAS`** exclusion list (lines 860–884):
```python
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        ...
        # Phase 19 Plan 02 — brain-direct profile tools
        "get_training_profile",
        "update_training_profile",
        ...
    }
]
```

**Addition:** Add `"read_coaching_guide"` to the exclusion set in `WORKER_TOOL_SCHEMAS` with a comment (the worker MUST NOT call coaching guide tools):
```python
        # Phase 22 — brain-direct coaching guide (COACH-01)
        "read_coaching_guide",
```

**Analog — `_HANDLERS` dispatch** (lines 1492–1495):
```python
    "get_training_profile":    lambda args: _handle_get_training_profile(),
    "update_training_profile": lambda args: _handle_update_training_profile(**args),
    # Phase 21 Plan 02 — update_plan alias (PLAN-03 / SC-3): same handler as above
    "update_plan":             lambda args: _handle_update_training_profile(**args),
```

**Addition:** Add after the Phase 21 entries:
```python
    # Phase 22 — coaching guide on-demand lookup (COACH-01)
    "read_coaching_guide":     lambda args: _handle_read_coaching_guide(**args),
```

---

### `prompts/smart_agent.md` — `{coaching_guide}` placeholder + Tier A/B hardening + critique posture (prompt, request-response)

**Analog:** `prompts/smart_agent.md:1–7` existing placeholder block; `prompts/smart_agent.md:105–136` existing Tier A/B + sharper-edge blocks

**Existing placeholder block** (lines 1–7):
```markdown
{self_md}

{self_state}

{journal_digest}

{training_profile}
```

**Modified placeholder block** — add `{coaching_guide}` before `{self_md}` (stable content first for Gemini caching):
```markdown
{coaching_guide}

{self_md}

{self_state}

{journal_digest}

{training_profile}
```

**Existing Tier A/B block** (lines 105–112) to be REPLACED by the recency-windowed contract:
```markdown
Tier A vs Tier B data discipline:
- **Tier A (targets — in the profile):** dated_goals, weekly_split targets,
  nutrition_targets, plan_start_date. These are citable as "your target" or
  "your plan calls for." They live in the profile and are always up to date.
- **Tier B (measured actuals — from Garmin / TrainingLogStore):** current pace,
  current lifts, recent RPE, actual nutrition intake. Derive at read time from
  the real data tools — **never hand-seed Tier B values in the profile** and
  **never invent them if the tool returns nothing**.
```

**Existing D-13 blanket-guard block** (lines 121–130) to be REMOVED:
```markdown
If the training profile is empty (no structured fields populated), do NOT
invent thresholds, targets, or scheduling buffers. This discipline extends to
ALL structured fields — even if you know "typical" targets, do not fabricate
personalized numbers. Instead:
1. Answer questions using just the metric (e.g., "Your ACWR this week is
   1.42, Sir. That puts you above the typical sweet spot of 0.8–1.3.").
2. When commentary would benefit from a personalized rule, politely ask Sir
   to state his preference, then call `update_plan` to record it.
3. Never make up a personalized rule. The discipline here is honesty over
   coverage. This applies equally to all structured fields.
```

**Existing sharper-edge block** (lines 132–136) — keep as-is (the critique posture block appended after it):
```markdown
Sharper edge: training and nutrition are areas where Sir asked for direct
coaching. The JARVIS register holds, but pull less of the C-3PO hedging.
"Sir, that's your second protein-free meal in a row before a heavy lift —
worth reconsidering" is in voice. Avoid "I'm afraid I must mention" softening
when the metric is unambiguous.
```

**New blocks to add** (see RESEARCH.md Pattern 3 for exact wording):
1. Replace lines 105–112 with the recency-windowed Tier A/B contract (D-06/07/08/09)
2. Remove lines 121–130 (D-13 blanket guard release)
3. Append after line 136: Specificity bar block (D-13 minimum bar)
4. Append after specificity bar: Structural critique posture block (D-10/11/12)

The RESEARCH.md `Pattern 3` section (lines 299–348) contains the exact ready-to-paste wording for all four new/replaced blocks.

---

### `core/morning_briefing.py` — slim-core injection at compose time (utility, request-response)

**Analog:** `core/morning_briefing.py:280–289` `_compose_briefing` — existing `{today_date}` injection pattern

**Exact analog** (lines 280–289):
```python
def _compose_briefing(today_data: dict, today_iso: str) -> str:
    """Compose the briefing via LLM with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "morning_briefing.md"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8").replace(
            "{today_date}", today_iso
        )
    except OSError:
        logger.warning("morning_briefing: prompt file missing — using fallback")
        return _plain_text_fallback(today_data, today_iso)
```

**Pattern to extend** — add `{coaching_guide}` injection alongside `{today_date}`. Two options per RESEARCH.md:

Option A (preferred — matches the autonomous.py pattern, reuses the orchestrator singleton):
```python
    # PHASE 22 — inject slim coaching core. _get_orchestrator() is a process-wide
    # singleton (already imported in autonomous.py). The slim content is loaded
    # once at startup and cached on the orchestrator.
    from core.main import _get_orchestrator
    coaching_guide_content = _get_orchestrator()._coaching_guide_content
    system_prompt = (
        prompt_path.read_text(encoding="utf-8")
        .replace("{today_date}", today_iso)
        .replace("{coaching_guide}", coaching_guide_content)
    )
```

Option B (simpler, no orchestrator import — pass content as parameter):
Change `_compose_briefing(today_data, today_iso)` signature to
`_compose_briefing(today_data, today_iso, coaching_guide_content: str = "")` and
inject at the call site from `run_morning_briefing()`.

The `prompts/morning_briefing.md` file also needs a `{coaching_guide}` placeholder at an appropriate location (before `{today_date}` to maintain stable-prefix ordering).

---

### `core/proactive_alerts.py` — slim-core injection at compose time (utility, request-response)

**Analog:** `core/proactive_alerts.py:369–379` `_compose_alert` — existing `{today_date}` injection pattern

**Exact analog** (lines 369–379):
```python
def _compose_alert(alerts_context: dict) -> str:
    """Compose the alert message via Smart Agent, with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "proactive_alert.md"
    today_str = date.today().isoformat()

    try:
        system_prompt = prompt_path.read_text(encoding="utf-8").replace(
            "{today_date}", today_str
        )
    except OSError:
        system_prompt = "You are Klaus, composing a proactive evening alert for Sir."
```

**Pattern to extend** — identical to `morning_briefing.py` Option A above:
```python
    try:
        from core.main import _get_orchestrator
        coaching_guide_content = _get_orchestrator()._coaching_guide_content
        system_prompt = (
            prompt_path.read_text(encoding="utf-8")
            .replace("{coaching_guide}", coaching_guide_content)
            .replace("{today_date}", today_str)
        )
    except OSError:
        system_prompt = "You are Klaus, composing a proactive evening alert for Sir."
```

The `prompts/proactive_alert.md` file needs a `{coaching_guide}` placeholder added.

---

### `tests/test_main_render_smart_system.py` — `{coaching_guide}` substitution tests (test, request-response)

**Analog:** `tests/test_main_render_smart_system.py:110–131` `_make_orchestrator` factory + `138–143` `test_render_substitutes_self_md` + `172–181` `test_render_no_unresolved_placeholders` + `232–294` `TestPhase19TrainingProfile` class

**Factory pattern** (lines 110–131) — extend `_make_orchestrator` to accept `coaching_guide_content`:
```python
def _make_orchestrator(
    *,
    self_md: str = "SELF.MD-CONTENT",
    coaching_guide_content: str = "COACHING-GUIDE-SLIM",  # Phase 22 addition
    self_state_store=None,
    journal_store=None,
):
    from core.main import AgentOrchestrator
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._self_md_content = self_md
    orchestrator._coaching_guide_content = coaching_guide_content  # Phase 22
    orchestrator._self_state_store = self_state_store
    orchestrator._journal_store = journal_store
    orchestrator._smart_prompt_template = (
        "SMART_PROMPT\n{self_md}\n---\n{self_state}\n---\n"
        "{journal_digest}\n---\n{today_date}\nEND"
    )
    return orchestrator
```

**Tests to write** — mirror `test_render_substitutes_self_md` (line 138) and `test_render_no_unresolved_placeholders` (line 172):
```python
def test_render_substitutes_coaching_guide():
    """{coaching_guide} is replaced with the orchestrator's _coaching_guide_content."""
    orch = _make_orchestrator(coaching_guide_content="COACHING-SLIM-BLOCK")
    out = orch.render_smart_system("Header\n{coaching_guide}\nFooter")
    assert "COACHING-SLIM-BLOCK" in out
    assert "{coaching_guide}" not in out


def test_render_coaching_guide_empty_no_literal_placeholder():
    """When _coaching_guide_content is '', {coaching_guide} resolves to '' not literal."""
    orch = _make_orchestrator(coaching_guide_content="")
    out = orch.render_smart_system("A\n{coaching_guide}\nB")
    assert "{coaching_guide}" not in out


def test_render_no_unresolved_placeholders_includes_coaching_guide():
    """After rendering, {coaching_guide} (plus original 4 tokens) must not survive."""
    orch = _make_orchestrator()
    template = (
        "{coaching_guide}\n{self_md}\n{self_state}\n{journal_digest}\n{today_date}\n"
    )
    out = orch.render_smart_system(template)
    for token in ("{coaching_guide}", "{self_md}", "{self_state}", "{journal_digest}", "{today_date}"):
        assert token not in out, f"placeholder {token} survived render"
```

**Slim-core size guard test** (Pitfall 2 gate):
```python
def test_load_coaching_guide_slim_returns_under_size_limit(tmp_path, monkeypatch):
    """_load_coaching_guide_slim must return fewer than 350 lines / 15000 chars."""
    guide = tmp_path / "docs" / "COACHING_GUIDE.md"
    guide.parent.mkdir(parents=True)
    # Write a minimal valid guide with SLIM_CORE_START/END
    guide.write_text("<!-- SLIM_CORE_START -->\nslim content\n<!-- SLIM_CORE_END -->\n")
    import core.main as main_module
    monkeypatch.setattr(main_module.Path, "__new__", ...)  # mock path to tmp_path
    # ... use monkeypatch to redirect _load_coaching_guide_slim to tmp_path
    result = main_module._load_coaching_guide_slim()
    assert len(result.splitlines()) < 350
    assert len(result) < 15_000
```

---

### `tests/test_tools.py` — `read_coaching_guide` registration tests (test, request-response)

**Analog:** `tests/test_tools.py:326–394` `TestPhase19ToolRegistration` class — 4-site registration pattern

**Exact analog** (lines 338–353):
```python
def test_phase19_profile_tools_registered(self):
    """Brain-direct tools appear at all 4 expected sites."""
    # Site 1: SMART_AGENT_DIRECT_TOOLS membership
    assert "get_training_profile" in tools.SMART_AGENT_DIRECT_TOOLS
    assert "update_training_profile" in tools.SMART_AGENT_DIRECT_TOOLS
    # Site 2: TOOL_SCHEMAS entry exists (by name)
    names = {s["name"] for s in tools.TOOL_SCHEMAS}
    assert "get_training_profile" in names
    # Site 3: WORKER_TOOL_SCHEMAS EXCLUSION
    worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
    assert "get_training_profile" not in worker_names
    # Site 4: _HANDLERS dispatch
    assert "get_training_profile" in tools._HANDLERS
```

**Tests to write** — add a `TestPhase22CoachingGuideTool` class mirroring the above:
```python
class TestPhase22CoachingGuideTool:
    """COACH-01 — verify read_coaching_guide registration at all 4 sites."""

    def test_read_coaching_guide_in_smart_agent_direct_tools(self):
        assert "read_coaching_guide" in tools.SMART_AGENT_DIRECT_TOOLS

    def test_read_coaching_guide_in_tool_schemas(self):
        names = {s["name"] for s in tools.TOOL_SCHEMAS}
        assert "read_coaching_guide" in names

    def test_read_coaching_guide_not_in_worker_schemas(self):
        """Brain-direct — worker MUST NOT see this tool."""
        worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
        assert "read_coaching_guide" not in worker_names

    def test_read_coaching_guide_in_handlers_dispatch(self):
        assert "read_coaching_guide" in tools._HANDLERS

    def test_read_coaching_guide_schema_requires_topic(self):
        schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "read_coaching_guide")
        assert schema["input_schema"]["required"] == ["topic"]
        assert "topic" in schema["input_schema"]["properties"]

    def test_handle_read_coaching_guide_known_topic(self, tmp_path, monkeypatch):
        """Handler returns section content for a known topic slug."""
        guide = tmp_path / "docs" / "COACHING_GUIDE.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            "<!-- SECTION: threshold-runs -->\n## Threshold Runs\nRun at LT2 pace.\n"
        )
        # monkeypatch Path to use tmp_path
        import core.tools as tools_module
        monkeypatch.setattr(tools_module, "Path", lambda *a, **kw: ...)
        # ... verify result is JSON with "content" key containing section text

    def test_handle_read_coaching_guide_unknown_topic(self, tmp_path, monkeypatch):
        """Handler returns error JSON for unknown topic slug."""
        # ... write guide without the requested section, verify {"error": ...}
```

---

## Shared Patterns

### Startup-Cache Pattern
**Source:** `core/main.py:216–219` + `757–769`
**Apply to:** `_load_coaching_guide_slim()` function + `AgentOrchestrator.__init__`
**Pattern:** Read file once at startup via a module-level `_load_*()` function that returns `""` on `OSError` with a `logger.warning`. Store result on `self._<name>_content`. This enables Gemini's cached-prefix optimization.

### Brain-Direct Tool 4-Site Registration
**Source:** `core/tools.py:39–57` (`SMART_AGENT_DIRECT_TOOLS`) + schema in `TOOL_SCHEMAS` + exclusion in `WORKER_TOOL_SCHEMAS:860–884` + `_HANDLERS:1470–1510`
**Apply to:** `read_coaching_guide`
**All 4 sites must be updated together.** Missing any one site = the tool either fails to dispatch, reaches the worker, or fails schema validation.

### JSON Return Convention for Brain-Direct Handlers
**Source:** `core/tools.py:1318–1330` `_handle_get_training_profile`
**Apply to:** `_handle_read_coaching_guide`
**Pattern:** Handler always returns `json.dumps(...)`. On success returns `{"topic": slug, "content": text}`. On error returns `{"error": "message"}`. Never raises — caller receives JSON either way.

### Prompt `.replace()` Injection at Compose Time
**Source:** `core/morning_briefing.py:284–286`; `core/proactive_alerts.py:375–377`
**Apply to:** Both cron compose functions for `{coaching_guide}`
**Pattern:**
```python
system_prompt = prompt_path.read_text(encoding="utf-8").replace(
    "{today_date}", today_iso
)
```
Chain an additional `.replace("{coaching_guide}", coaching_guide_content)` before the `{today_date}` replacement (stable before volatile — same ordering as `render_smart_system`).

### `render_smart_system` Pass-Through (autonomous cron)
**Source:** `core/autonomous.py:568–579`
**Apply to:** `prompts/autonomous.md` — add `{coaching_guide}` placeholder
**Pattern:** `_compose_layer2` already calls `orchestrator.render_smart_system(smart_system_template)`. No code change needed in `autonomous.py`; only the `.md` template needs the `{coaching_guide}` placeholder added.

### Test Factory Pattern (`AgentOrchestrator.__new__`)
**Source:** `tests/test_main_render_smart_system.py:110–131`
**Apply to:** New coaching guide substitution tests
**Pattern:** Bypass `__init__` entirely via `AgentOrchestrator.__new__(AgentOrchestrator)`, then manually set all attributes that `render_smart_system` reads. Add `_coaching_guide_content` to the factory.

---

## No Analog Found

No files in this phase are without analog. All patterns have direct codebase matches.

---

## Metadata

**Analog search scope:** `core/main.py`, `core/tools.py`, `core/morning_briefing.py`, `core/proactive_alerts.py`, `core/autonomous.py`, `prompts/smart_agent.md`, `docs/SELF.md`, `tests/test_main_render_smart_system.py`, `tests/test_tools.py`
**Files scanned:** 9 source + 2 test files read directly
**Pattern extraction date:** 2026-06-04
