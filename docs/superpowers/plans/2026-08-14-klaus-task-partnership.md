# Klaus Task Partnership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Klaus file to-dos as Amit mentions them, and turn the nightly
review into a planning routine that closes today and drafts tomorrow.

**Architecture:** Almost none of this is backend logic. Klaus's reasoning lives
in the Claude Skills checked into `claude/skills/`, and the MCP surface already
exposes every tool required — `ROUTINE_TOOLS` includes `task_create`,
`task_edit`, `task_reschedule`, `task_complete`, `task_delete` and the calendar
writes. So the work is: tell Klaus what `task_list` gives back (he cannot reason
over fields he is not told exist), write the two behaviours into the skills,
version and repackage them, and add a measurement script for the success
criteria.

**Tech Stack:** Python 3.13, pytest, Claude Skills (Markdown + VERSION + zip
artifacts), MCP tool schemas in `core/tools.py`.

**Spec:** `docs/superpowers/specs/2026-08-14-klaus-task-partnership-design.md`

## Global Constraints

- **Reversibility is the permission line.** Klaus acts on anything undoable
  inside Things and asks only for irreversible, outward-facing, or bulk changes.
  Never add a confirmation step for filing, dating, tagging or renaming.
- **Dates only when timing is genuinely implied.** Never invent a date to make a
  to-do look scheduled.
- **No nagging about overdue items.** The account has none and will not have
  any until dates exist.
- **Klaus does not execute tasks.** No email, no web. Out of scope entirely.
- **Skill version must match `EXPECTED_SKILL_VERSION`** in
  `interfaces/mcp_server.py`, in all four `claude/skills/*/VERSION` files, and in
  the `Skill version:` line inside each `SKILL.md`. Guarded by
  `tests/test_claude_skills.py`.
- **All four skills version together.** `test_skill_sources_and_mcp_capability_version_match`
  asserts every skill matches, so bumping one means bumping all four.
- **Venv is Python 3.13.** Run tests with `.venv/bin/python -m pytest`.

---

### Task 1: Tell Klaus what a to-do actually contains

Klaus decides staleness and deadline pressure from `created_at` and
`hard_deadline_at`, and placement from `bucket`. `normalize_task()` returns all
three, but the `task_list` schema never mentions them, so Klaus has no reason to
know they exist. This is spec §4 gap 1.

**Files:**
- Modify: `core/tools.py:263-292` (the `task_list` schema description)
- Modify: `core/tools.py:202-208` (the `task_create` schema description)
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: no new symbols. Later tasks rely only on the schema text being
  present, which Task 6's eval cases exercise behaviourally.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools.py`:

```python
def _schema(name: str) -> dict:
    from core.tools import TOOL_SCHEMAS
    return next(s for s in TOOL_SCHEMAS if s["name"] == name)


def test_task_list_schema_documents_the_returned_fields():
    """Klaus cannot reason over fields he is not told come back.

    Staleness needs created_at, deadline lookahead needs hard_deadline_at, and
    placement needs bucket. All three are returned by normalize_task(); without
    this text Klaus has no reason to believe they exist.
    """
    description = _schema("task_list")["description"]
    for field in ("created_at", "hard_deadline_at", "bucket"):
        assert field in description, f"task_list must document {field}"


def test_task_create_schema_tells_klaus_to_file_and_not_invent_dates():
    """The two behaviours from spec section 3.1 that live in the schema."""
    description = _schema("task_create")["description"]
    assert "list_id" in description
    assert "Inbox" in description
    assert "invent" in description.lower() or "guess" in description.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools.py -k "schema_documents or tells_klaus" -v`
Expected: FAIL — `AssertionError: task_list must document created_at`

(`TOOL_SCHEMAS` is the module-level list at `core/tools.py:29`; the task schemas
are entries within it.)

- [ ] **Step 3: Update the two descriptions**

Replace the `task_list` description at `core/tools.py:265-271` with:

```python
        "description": (
            "Read Amit's open Things 3 to-dos. All filters are optional — omit them "
            "all to see the whole list, including project, area, and tag labels. "
            "Use upcoming_days to see the week ahead; note that Amit dates very few "
            "to-dos, so most of his list has no date at all and a date filter will "
            "usually come back empty. "
            "Every to-do also carries created_at (how long it has been sitting — "
            "the median age of his list is around four months, so this is how you "
            "spot what has gone stale), hard_deadline_at (a real deadline, distinct "
            "from the scheduled date), and bucket (inbox, anytime, upcoming or "
            "someday). An item in 'inbox' is unfiled and probably needs a home."
        ),
```

Replace the `task_create` description at `core/tools.py:203-208` with:

```python
        "description": (
            "Add a to-do to Amit's Things 3 list. Set due_date for when Amit plans "
            "to DO it, and hard_deadline_at for when it is actually DUE — these are "
            "different fields in Things and either alone is fine. "
            "Always try to file it: pass list_id with the project or area it "
            "belongs to rather than letting it fall into the Inbox, which is where "
            "Amit's to-dos go to die. Use task_list to see what projects and areas "
            "exist. Only set a date when the timing is genuinely implied — do not "
            "invent one to make the to-do look scheduled; an undated to-do is "
            "honest, a fabricated date is noise."
        ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: PASS, and no other test in the file regresses.

- [ ] **Step 5: Commit**

```bash
git add core/tools.py tests/test_tools.py
git commit -m "feat(tasks): document returned fields and filing in the task schemas

Klaus decides staleness from created_at and placement from bucket, both of
which normalize_task() has always returned and the schema never mentioned.
task_create now tells him to file rather than default to the Inbox, and not to
invent dates."
```

---

### Task 2: Measure whether any of this works

Spec §5 has numeric success criteria and nothing produces the numbers. This is
spec §4 gap 2. A script, not a store — every figure comes from the Things mirror
that already exists.

**Files:**
- Create: `scripts/task_health.py`
- Test: `tests/test_task_health.py`

**Interfaces:**
- Consumes: `mcp_tools.things_tool.live_todos()`, which returns a list of
  normalized dicts with keys `title`, `due_date`, `hard_deadline_at`, `bucket`,
  `project_name`, `area_name`, `created_at`.
- Produces: `scripts.task_health.summarize(tasks: list[dict], today: str) -> dict`
  returning exactly the keys `total`, `dated`, `with_deadline`, `filed`,
  `median_age_days`, `oldest_age_days`. No later task consumes it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_health.py`:

```python
"""The 2026-08-14 baseline is 17 real to-dos, 1 dated, 2 filed, median age 116."""
from scripts.task_health import summarize


def _task(**overrides) -> dict:
    base = {
        "title": "x", "due_date": None, "hard_deadline_at": None,
        "bucket": "inbox", "project_name": None, "area_name": None,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_summarize_counts_the_success_criteria():
    tasks = [
        _task(due_date="2026-08-20"),
        _task(hard_deadline_at="2026-08-30"),
        _task(project_name="Klaus"),
        _task(area_name="Shopping"),
        _task(),
    ]
    out = summarize(tasks, today="2026-08-14")
    assert out["total"] == 5
    assert out["dated"] == 1
    assert out["with_deadline"] == 1
    assert out["filed"] == 2


def test_summarize_reports_age_from_created_at():
    tasks = [
        _task(created_at="2026-08-04T00:00:00+00:00"),   # 10 days
        _task(created_at="2026-07-15T00:00:00+00:00"),   # 30 days
        _task(created_at="2025-08-14T00:00:00+00:00"),   # 365 days
    ]
    out = summarize(tasks, today="2026-08-14")
    assert out["median_age_days"] == 30
    assert out["oldest_age_days"] == 365


def test_summarize_handles_an_empty_list_without_dividing_by_zero():
    out = summarize([], today="2026-08-14")
    assert out["total"] == 0
    assert out["median_age_days"] is None
    assert out["oldest_age_days"] is None


def test_summarize_tolerates_a_missing_created_at():
    """Things payloads are not guaranteed complete; never crash a report."""
    out = summarize([_task(created_at=None)], today="2026-08-14")
    assert out["total"] == 1
    assert out["median_age_days"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_task_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.task_health'`

- [ ] **Step 3: Write the script**

Create `scripts/task_health.py`:

```python
"""Report the task-list health figures behind the success criteria.

The design at docs/superpowers/specs/2026-08-14-klaus-task-partnership-design.md
sets numeric targets against a 2026-08-14 baseline: 17 real to-dos, 1 dated,
0 with deadlines, 2 filed, median age 116 days. This prints the same figures so
the targets can actually be checked.

Read-only. Every number comes from the Things mirror; no new storage.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/task_health.py
"""
from __future__ import annotations

import statistics
from datetime import date


def summarize(tasks: list[dict], today: str) -> dict:
    """Count the success-criteria figures over normalized Things to-dos.

    Args:
        tasks: normalized to-dos from ``things_tool.live_todos()``.
        today: ISO date the ages are measured against.

    Returns:
        Counts plus median and oldest age in days.  Both ages are ``None`` when
        no to-do carries a usable ``created_at`` — a report must never divide by
        zero on an empty list.
    """
    reference = date.fromisoformat(today)
    ages = [
        (reference - date.fromisoformat(str(task["created_at"])[:10])).days
        for task in tasks
        if task.get("created_at")
    ]
    return {
        "total": len(tasks),
        "dated": sum(1 for t in tasks if t.get("due_date")),
        "with_deadline": sum(1 for t in tasks if t.get("hard_deadline_at")),
        "filed": sum(1 for t in tasks if t.get("project_name") or t.get("area_name")),
        "median_age_days": int(statistics.median(ages)) if ages else None,
        "oldest_age_days": max(ages) if ages else None,
    }


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(override=True)
    import mcp_tools.things_tool as things

    state, _head = things.replay_journal(things.fetch_history_key()["history-key"])
    report = summarize(things.live_todos(state), things.today_iso())
    baseline = {"total": 17, "dated": 1, "with_deadline": 0, "filed": 2,
                "median_age_days": 116}
    for key, value in report.items():
        was = baseline.get(key)
        suffix = f"   (2026-08-14 baseline: {was})" if was is not None else ""
        print(f"{key:18} {value}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_task_health.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/task_health.py tests/test_task_health.py
git commit -m "feat(tasks): report the task-health figures the design is judged on

Spec section 5 sets numeric targets against the 2026-08-14 baseline and nothing
produced the numbers. Read-only, straight off the Things mirror."
```

---

### Task 3: Teach the live agent to capture and file

Spec §3.1. Klaus creates the to-do in the turn Amit mentions it, filed, and says
so in one line. He never asks where it should go — that question is what stops
tasks being written down.

**Files:**
- Modify: `claude/skills/klaus-live-agent/SKILL.md` (add a section after
  "## Actions", before "## Untrusted sources")
- Test: `tests/test_claude_skills.py`

**Interfaces:**
- Consumes: the `task_create` schema text from Task 1 — the skill relies on
  `list_id` being described as the filing field.
- Produces: a `## Tasks` heading in `klaus-live-agent/SKILL.md`. Task 5 repackages
  this file; Task 6 adds eval cases naming the same behaviours.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_claude_skills.py`:

```python
def _skill_text(name: str) -> str:
    return (ROOT / "claude" / "skills" / name / "SKILL.md").read_text()


def test_live_agent_captures_and_files_tasks_in_the_moment():
    """Spec 3.1. Deferring to the nightly review was explicitly rejected."""
    text = _skill_text("klaus-live-agent")
    assert "## Tasks" in text
    assert "list_id" in text, "must tell Klaus to file, not just create"
    lowered = text.lower()
    assert "do not ask" in lowered or "never ask" in lowered
    assert "invent" in lowered, "must forbid inventing dates"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -k live_agent_captures -v`
Expected: FAIL — `AssertionError: assert '## Tasks' in ...`

- [ ] **Step 3: Add the section to the skill**

Insert into `claude/skills/klaus-live-agent/SKILL.md`, immediately before
`## Untrusted sources`:

```markdown
## Tasks

Amit's Things list is a capture bucket, not a task list: most of it has no date,
no project and no tag, and items sit for months. The blocking step is not
writing a to-do down — it is deciding where it goes. Make that decision for him.

When he says something that is a commitment, create the to-do in that turn:

- File it. Pass `list_id` with the project or area it belongs to. Read
  `task_list` first if you do not already know what exists. Leaving it in the
  Inbox is the failure mode, not the safe default.
- Set a date only when the timing is genuinely implied — "tomorrow", "before the
  race", "when the order arrives". Do not invent a date to make it look
  scheduled. An undated to-do is honest.
- Say what you did in one line. Not a paragraph, not a checklist.

Do not ask where it should go. That question is the reason things never get
written down, and a wrong guess costs him one drag in Things.

Distinguish a commitment from a remark. "I should sort the newsletters" is a
commitment. "The newsletters are getting out of hand" is not. When genuinely
ambiguous, ask — but a wrong to-do is cheaper than a missing one.

Do not nag about overdue items. He has none, because he sets almost no dates.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -k live_agent_captures -v`
Expected: PASS.

The version-drift tests in this file will now FAIL, because the zip artifacts no
longer match the sources. That is expected and Task 5 fixes it. Do not repackage
here.

- [ ] **Step 5: Commit**

```bash
git add claude/skills/klaus-live-agent/SKILL.md tests/test_claude_skills.py
git commit -m "feat(skills): Klaus files to-dos as Amit mentions them

The friction is deciding where a task goes, not writing it down, so Klaus makes
that call. Artifacts are repackaged in a later commit."
```

---

### Task 4: Turn the nightly review into a planning routine

Spec §3.2. The existing skill already closes the day; this replaces that section
with the six-step routine and makes the plan get written rather than proposed.

**Files:**
- Modify: `claude/skills/klaus-nightly-review/SKILL.md` (replace the
  "## Close the day" section)
- Test: `tests/test_claude_skills.py`

**Interfaces:**
- Consumes: the `task_list` schema text from Task 1 — the tidying step relies on
  `created_at` being described. Also the `_skill_text(name) -> str` test helper
  added to `tests/test_claude_skills.py` in Task 3; if Task 3 has not run, add
  that helper here instead of duplicating it.
- Produces: a `## Plan tomorrow` heading in `klaus-nightly-review/SKILL.md`.
  Task 5 repackages it; Task 6 adds matching eval cases.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_claude_skills.py`:

```python
def test_nightly_review_plans_tomorrow_and_writes_the_plan():
    """Spec 3.2. The plan is written when sent — no pending-plan state."""
    text = _skill_text("klaus-nightly-review")
    assert "## Plan tomorrow" in text
    lowered = text.lower()
    assert "3h15" in text or "3 h 15" in text, "must use the real gym footprint"
    assert "created_at" in text, "tidying needs the staleness field"
    assert "do not wait" in lowered or "without waiting" in lowered


def test_nightly_review_still_honours_shadow_mode():
    """Shadow mode forbids every mutating call; planning must not bypass it."""
    text = _skill_text("klaus-nightly-review")
    assert "## Shadow mode" in text
    plan_section = text.split("## Plan tomorrow", 1)[1]
    assert "shadow" in plan_section.lower(), "the planning section must defer to it"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -k nightly_review -v`
Expected: FAIL — `AssertionError: assert '## Plan tomorrow' in ...`

- [ ] **Step 3: Replace the "Close the day" section**

In `claude/skills/klaus-nightly-review/SKILL.md`, replace the whole
`## Close the day` section with:

```markdown
## Close the day

Account for completed, unfinished, and newly urgent work. Anything unfinished
gets a real date or is dropped, and say which — an unfinished task that silently
rolls forward is how his list reached a median age of four months. Respect
explicit times, recurrence, hard deadlines, and manual locks.

## Plan tomorrow

Amit plans tomorrow every night anyway. Arrive with a draft so he edits instead
of authoring, and **write the plan as you send it** — do not wait for a reply
and do not hold a proposal. Everything in it is reversible, and a plan that
needs confirmation is a plan that evaporates when he falls asleep. He adjusts by
replying.

In shadow mode, write nothing: record the same plan in `partial_actions` only.

1. **Draft the day.** Training, tasks with real times, and Klaus-owned calendar
   blocks. Prefer to-dos that are already dated for tomorrow, then deadline
   pressure, then something that fits the shape of the day.
2. **Check it fits.** Use real footprints: a gym session costs him about 3h15m
   door to door — roughly 1h15m training, 45m to eat and shower, 15m travel each
   way, 45m to get ready — not 75 minutes. Most bad plans are not bad
   priorities, they are plans that never physically fit. Keep roughly 20% of
   usable time as slack.
3. **Place training for weather and recovery.** Use tomorrow's forecast and his
   Garmin sleep, HRV and body battery to suggest moving a session earlier or
   later. Training changes stay recommendation-only — propose, do not mutate the
   plan.
4. **Look ahead at deadlines.** Flag anything with a `hard_deadline_at` close by
   and nothing scheduled to get it done. He sets almost no deadlines today, so
   this will often be silent; say nothing rather than manufacturing urgency.
5. **Tidy.** Use `created_at` to find what has gone stale and `bucket` to find
   what is still sitting unfiled in the Inbox. Surface as many as genuinely
   warrant it — there is no limit, and a long-overdue clear-out is welcome.
   Reorganize on your own initiative: filing, re-dating and re-bucketing are all
   reversible.

Create, move, or remove only Klaus-owned task blocks. Never move or delete a
user-created calendar event or training session.

A bulk irreversible change — culling a large part of the list — is the one thing
you present in full and wait for a yes on. Everything else, just do and report.

Do not nag about overdue items; he has none. Record the day's reflection and
proposed self-state in the structured review. Surface pattern-based learned
preferences as proposals supported by evidence and an explicit veto; never
silently convert them into facts or standing directives.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -k nightly_review -v`
Expected: PASS. Artifact-drift tests still fail; Task 5 fixes them.

- [ ] **Step 5: Commit**

```bash
git add claude/skills/klaus-nightly-review/SKILL.md tests/test_claude_skills.py
git commit -m "feat(skills): nightly review drafts and writes tomorrow's plan

Attaches to a habit Amit already has rather than adding a weekly ceremony. The
plan is written when sent, so there is no pending state and no plan that
evaporates overnight."
```

---

### Task 5: Version and repackage the skills

The drift guards have been failing since Task 3. Both edited skills changed
behaviour, so the suite versions up together and Amit re-uploads.

> **Correction (preflight, 2026-08-14).** The file list below was incomplete.
> It also needs `core/subscription_routines.py:120`, which hardcodes
> `"skill_version": "7.1.0"` in the payload fired at the Remote Routine, and
> `tests/test_claude_skills.py:132 test_skill_version_is_7_1_0_everywhere`,
> which pins the version in both its name and its assertions. Without both, the
> suite cannot go green and the routine would advertise a stale version.

**Files:**
- Modify: `interfaces/mcp_server.py:23` (`EXPECTED_SKILL_VERSION`)
- Modify: `core/subscription_routines.py:120` (`"skill_version"` in the payload)
- Modify: `tests/test_claude_skills.py:132` (rename to `..._is_7_2_0_...`, update
  both assertions)
- Modify: `claude/skills/klaus-live-agent/VERSION`
- Modify: `claude/skills/klaus-morning-review/VERSION`
- Modify: `claude/skills/klaus-nightly-review/VERSION`
- Modify: `claude/skills/klaus-weekly-review/VERSION`
- Modify: the `Skill version:` line in all four `SKILL.md` files
- Regenerate: `claude/dist/*.zip`, `claude/dist/manifest.json`
- Test: `tests/test_claude_skills.py` (existing tests, no new ones)

**Interfaces:**
- Consumes: the edited `SKILL.md` files from Tasks 3 and 4.
- Produces: `EXPECTED_SKILL_VERSION == "7.2.0"`. Nothing later consumes it.

- [ ] **Step 1: Run the drift tests to see them failing**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -v`
Expected: FAIL on `test_uploadable_zips_exactly_match_canonical_sources` and
`test_packager_check_mode_detects_no_drift` — the sources changed, the zips did
not.

- [ ] **Step 2: Bump every version marker**

```bash
sed -i '' 's/EXPECTED_SKILL_VERSION = "7.1.0"/EXPECTED_SKILL_VERSION = "7.2.0"/' interfaces/mcp_server.py
sed -i '' 's/"skill_version": "7\.1\.0"/"skill_version": "7.2.0"/' core/subscription_routines.py
for s in klaus-live-agent klaus-morning-review klaus-nightly-review klaus-weekly-review; do
  printf '7.2.0\n' > "claude/skills/$s/VERSION"
  sed -i '' 's/^Skill version: 7\.1\.0$/Skill version: 7.2.0/' "claude/skills/$s/SKILL.md"
done
# The pinning test names the version in its function name and both assertions.
sed -i '' 's/test_skill_version_is_7_1_0_everywhere/test_skill_version_is_7_2_0_everywhere/; s/EXPECTED_SKILL_VERSION == "7\.1\.0"/EXPECTED_SKILL_VERSION == "7.2.0"/; s/"skill_version": "7\.1\.0"/"skill_version": "7.2.0"/' tests/test_claude_skills.py
git grep -n "7\.1\.0" -- . ':!claude/dist' || echo "no 7.1.0 left in tracked sources"
```

The final `git grep` must come back empty apart from the prose sentence noted
below. If it still lists `claude/skills/klaus-live-agent/SKILL.md:18`, that is
the expected hand-fix in the next paragraph.

Note `klaus-live-agent/SKILL.md` also names the version in prose ("If it differs
from 7.1.0"). The `sed` above only matches the standalone `Skill version:` line,
so fix that sentence by hand — grep will show it.

- [ ] **Step 3: Regenerate the artifacts**

```bash
.venv/bin/python scripts/package_claude_skills.py
git status --short claude/dist/
```

Expected: four new `*-7.2.0.zip` files and an updated `manifest.json`. Delete the
superseded `*-7.1.0.zip` files — the tests only look for the current version, but
leaving stale artifacts invites uploading the wrong one:

```bash
git rm -q claude/dist/*-7.1.0.zip
```

- [ ] **Step 4: Run the full skill suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -v`
Expected: all pass, including the packager `--check` subprocess.

Then the whole suite, since `EXPECTED_SKILL_VERSION` is asserted elsewhere:

Run: `.venv/bin/python -m pytest -q --ignore=tests/test_runtime_subtraction.py`
Expected: no failures. (`test_runtime_subtraction.py` fails locally on untracked
`.worktrees/` and `.venv.py314.bak/` clutter; it passes in CI, which clones
fresh.)

- [ ] **Step 5: Commit**

```bash
git add -A claude/ interfaces/mcp_server.py
git commit -m "chore(skills): release skill suite 7.2.0

Capture-and-file and the nightly planning routine change Klaus's behaviour, so
the suite versions together and the artifacts are regenerated. Amit must
re-upload all four zips to Claude for these to take effect."
```

---

### Task 6: Pressure-test the new behaviours in the eval suite

`test_skill_eval_suite_covers_each_skill_with_three_pressure_cases` already
requires three cases per skill. These add cases for the behaviours most likely to
regress — the ones where the obvious action is the wrong one.

**Files:**
- Modify: `claude/evals/skill-evals.json`
- Test: `tests/test_claude_skills.py` (existing assertions cover the shape)

**Interfaces:**
- Consumes: the behaviours written in Tasks 3 and 4.
- Produces: nothing consumed later.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_claude_skills.py`:

```python
def test_evals_cover_the_task_partnership_behaviours():
    """The three failure modes most likely to reappear as 'helpful' defaults."""
    cases = json.loads((ROOT / "claude" / "evals" / "skill-evals.json").read_text())
    blob = json.dumps(cases).lower()
    assert "inbox" in blob, "filing rather than defaulting to the Inbox"
    assert "invent" in blob or "fabricat" in blob, "not inventing dates"
    assert "overdue" in blob, "not nagging about overdue items"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -k evals_cover_the_task -v`
Expected: FAIL — `AssertionError: filing rather than defaulting to the Inbox`

- [ ] **Step 3: Add the eval cases**

Append these four objects to the array in `claude/evals/skill-evals.json`:

```json
  {
    "skill": "klaus-live-agent",
    "query": "I really need to sort out my newsletters at some point.",
    "expected_behavior": [
      "Creates the to-do in this turn rather than deferring it",
      "Files it under a project or area instead of leaving it in the Inbox",
      "Sets no date, because no timing was implied and inventing one is forbidden",
      "Confirms in a single line"
    ]
  },
  {
    "skill": "klaus-live-agent",
    "query": "The newsletters are getting completely out of hand.",
    "expected_behavior": [
      "Recognises a remark, not a commitment",
      "Does not silently create a to-do",
      "Asks only if the intent is genuinely ambiguous"
    ]
  },
  {
    "skill": "klaus-nightly-review",
    "query": "Run tonight's review. Amit has fourteen undated to-dos and an empty calendar tomorrow.",
    "expected_behavior": [
      "Drafts tomorrow and writes it without waiting for a reply",
      "Does not report anything as overdue, since nothing is dated",
      "Uses the full 3h15m footprint if a gym session is placed",
      "Leaves roughly 20% of usable time as slack"
    ]
  },
  {
    "skill": "klaus-nightly-review",
    "query": "Run tonight's review. Eleven of Amit's to-dos are over a year old and unfiled.",
    "expected_behavior": [
      "Surfaces stale items using created_at, with no artificial limit on how many",
      "Files or re-buckets on its own initiative, as those are reversible",
      "Presents a bulk cull in full and waits for approval before deleting",
      "Writes nothing at all when delivery_mode is shadow"
    ]
  }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_claude_skills.py -v`
Expected: all pass, including the existing per-skill count and
`expected_behavior` length assertions.

- [ ] **Step 5: Commit**

```bash
git add claude/evals/skill-evals.json tests/test_claude_skills.py
git commit -m "test(skills): pressure-test filing, date restraint and no-nagging

Each case targets a behaviour where the obvious action is the wrong one:
defaulting to the Inbox, inventing a date to look useful, and reporting overdue
items on a list that has none."
```

---

## After the plan

**Amit must re-upload the four skill zips** from `claude/dist/` to his Claude
account. Nothing in Tasks 3, 4 or 6 changes Klaus's behaviour until he does —
the repo holds the canonical source, but Claude runs the uploaded copy. The
version bump in Task 5 makes a stale upload visible: `klaus-live-agent` warns
once when `klaus/skillVersion` does not match.

**Deploy** as usual: merge to `main`, which triggers the Cloud Run workflow. Only
Tasks 1, 2 and 5 touch deployed code, and none changes runtime behaviour on its
own.

**Then measure.** Run `PYTHONPATH=. .venv/bin/python scripts/task_health.py`
before the skills are uploaded to confirm the baseline, and again after a few
weeks. Spec §5 is the scorecard; the failure mode to watch is Amit ignoring the
nightly plans, which would mean Klaus's judgement about what matters tomorrow is
wrong — a prompt and eval problem, not a feature gap.
