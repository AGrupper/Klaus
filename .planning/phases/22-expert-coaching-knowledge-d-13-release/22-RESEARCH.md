# Phase 22: Expert Coaching Knowledge + D-13 Release - Research

**Researched:** 2026-06-04
**Domain:** Hybrid-athlete coaching science + prompt-injection architecture + tool registration
**Confidence:** HIGH (codebase verified in-session; coaching domain peer-reviewed / practitioner consensus)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01** — Guide is written applied to Amit's plan — knowledge framed around his actual sessions, goals, and AM/PM split, with the underlying science behind each. Not pure generic reference.
- **D-02** — Rich / comprehensive on disk (1000+ lines acceptable). Depth lives on disk, not in every prompt.
- **D-03** — Topics (all four required): concurrent training & interference effect; block periodization; session execution (threshold runs, top-set strength, calisthenics progressions, intervals); fueling science (peri-workout fueling, protein timing, carb periodization, supplement rationale).
- **D-04** — Slim core (~200–300 lines) always injected as stable cached prefix via `_load_coaching_guide()`; full deep sections accessible only via brain-direct `read_coaching_guide(topic)` tool. Overrides the v4.0 research decision of injecting the whole guide.
- **D-05** — Crons always carry the slim core; may call `read_coaching_guide()` but prompt biases high-freq crons (morning briefing, autonomous tick) to stay on cheap core. Sunday weekly review may go deep.
- **D-06** — Tier B recency windows: lifts ≤ 14 days, running pace ≤ 7 days, nutrition/macros ≤ 2 days. Garmin recovery (HRV / sleep / body battery / resting HR) always fresh.
- **D-07** — Just-past-window = cite with staleness caveat ("…that was 18 days ago, Sir, stale reference").
- **D-08** — No-data = "I don't have a recent X logged, Sir" + cite blueprint goal as "your target."
- **D-09** — Tier A always citable: dated_goals, weekly_split targets, nutrition_targets, plan_start_date.
- **D-10** — Klaus volunteers structural critique unprompted when data + knowledge clearly show something suboptimal. Structural only, not daily micro-tweaks, not repeated hammering.
- **D-11** — Blunt expert tone. JARVIS register, names flaw and fix directly, minimal C-3PO hedging.
- **D-12** — Klaus states critique + specific alternative, then waits. Calls `update_plan` / `update_training_profile` only on Amit's explicit confirmation. Never silently rewrites.
- **D-13** — Minimum specificity bar: every coaching point names session type + target load/pace + one-line rationale.
- **D-14** — One-liner rationale by default; expand to mini-lesson (3–4 sentences) only when Amit asks "why?" or topic warrants — pulls deep section via `read_coaching_guide()`.

### Claude's Discretion
- Exact line-count and section structure of the slim core digest vs. the deep guide; how `read_coaching_guide(topic)` enumerates/keys its sections (topic enum vs. free-text match).
- Whether `read_coaching_guide` is a standalone brain-direct tool or folded into an existing self-inspect-style accessor; tool schema shape and `_HANDLERS` wiring.
- A sane upper bound beyond which very old Tier B data stops being cited even with a caveat (degrades to D-08 "no recent data").
- Exact prompt wording for the Tier A/B contract, the recency thresholds, and the staleness-caveat phrasing in `prompts/smart_agent.md`.
- How the slim-core vs. deep-lookup bias is expressed to the crons without a hard prohibition.
- Whether the rich guide is one file with section anchors or a small set of section files behind the lookup tool.

### Deferred Ideas (OUT OF SCOPE)
- `BlockStore` / `BenchmarkStore`, block-state surfacing, week-number computation, benchmark triggers → Phase 23.
- Macro-adherence engine against `MealStore`, fueling-slot miss detection → Phase 24.
- Cross-cron coaching-message dedup / repeat-suppression → Phase 24.
- Progress projection / trend reporting → Phase 25.
- Any new crons, backends, or dependencies.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COACH-01 | Klaus carries curated expert hybrid-athlete coaching knowledge (concurrent strength/endurance & interference effect, block periodization, session execution, fueling science) injected into his reasoning substrate | Domain science sections below + `_load_coaching_guide()` injection architecture |
| COACH-06 | D-13 no-fabrication guard released under data-presence contract: Tier A (blueprint goals) citable as targets; Tier B (measured numbers) citable only within recency window; never invented | Tier A/B recency contract section; exact prompt wording pattern |
| COACH-02 | Klaus names the specific session, load/pace, and rationale in coaching messages | Specificity bar section; session execution cues in domain science |
| COACH-07 | Klaus treats blueprint as a critiqueable guide; when expert knowledge or data shows suboptimal design he says so and recommends a specific better approach; recommends only, never silently rewrites | Critique posture section; protein / supplement domain findings |
</phase_requirements>

---

## Summary

Phase 22 has three distinct sub-problems: (1) author and wire a hybrid-athlete coaching knowledge base, (2) replace a prompt-level no-fabrication guard with a two-tier data-presence contract, and (3) harden Klaus's output so every coaching point names a specific session, load, and rationale. All three are prompt-engineering and file-authoring work — no new Firestore stores, no new cron jobs, no new backends.

The codebase pattern is already well-established: `_load_self_md()` at line 757 of `core/main.py` reads a file once at startup, stores it on the orchestrator, and `render_smart_system()` injects it as the stable leading prefix of the smart system prompt. The identical pattern applies for `_load_coaching_guide()`. The slim core (~200–300 lines) loads at startup; the full rich guide (~1000+ lines) stays on disk, read-on-demand by the `read_coaching_guide(topic)` brain-direct tool. This mirrors the `read_own_source` self-inspect pattern already in `core/tools.py` (schema ~line 653, handler ~1286, `_HANDLERS` ~1455).

The D-13 guard removal is a surgical prompt edit: the existing Phase 21 Tier A/B framing (lines 105–112 of `prompts/smart_agent.md`) is already the seed. Phase 22 hardens it into a contract with explicit recency windows and staleness-caveat phrasing, and removes the blanket "do NOT invent thresholds, targets, or scheduling buffers" block (lines 121–130). The critique posture (D-10/11/12) is a new prose block appended to the TRAINING & ATHLETIC COACHING section.

The coaching domain science research below is the raw material for authoring `docs/COACHING_GUIDE.md`. All four required topic areas are covered with source-tiered findings. The slim-core digest should distill the always-needed coaching constants (AM/PM ordering rule, session-execution headline cues, fueling-slot map, key critique flags) from the rich guide.

**Primary recommendation:** One file (`docs/COACHING_GUIDE.md`) with clearly titled H2 sections and a `<!-- SECTION: slug -->` anchor per section — the `read_coaching_guide(topic)` tool does a section-slug match, not a vector search. Simpler, no extra dependencies, perfectly auditable.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Coaching guide content (static knowledge) | File / Prompt | — | Pure knowledge base on disk; no runtime store needed |
| Slim-core injection | API / Backend (orchestrator) | — | `render_smart_system` inserts as stable cached prefix |
| On-demand deep section lookup | API / Backend (brain-direct tool) | — | Brain calls `read_coaching_guide(topic)` when needed |
| Tier A/B data-presence contract | Prompt | — | Prompt-only; no code changes needed |
| Critique posture | Prompt | — | Prompt-only behavioral directive |
| Specificity bar | Prompt | — | Prompt-only output shape directive |
| Regression consumers (briefing/alerts/autonomous) | Prompt | — | They call `render_smart_system` already — slim-core arrives automatically |

---

## Standard Stack

This phase is **prompt + file authoring only**. No new libraries. No new packages. The only code changes are in `core/main.py`, `core/tools.py`, and `prompts/smart_agent.md`.

### Existing Code Reused (not new installs)

| Component | File | What Changes |
|-----------|------|--------------|
| `_load_self_md()` pattern | `core/main.py:757` | Mirror as `_load_coaching_guide()` |
| `render_smart_system` | `core/main.py:239` | Add `{coaching_guide}` placeholder substitution |
| `_smart_prompt_template` startup load | `core/main.py:211` | `prompts/smart_agent.md` gains `{coaching_guide}` placeholder |
| Brain-direct tool schema | `core/tools.py:653–666` | Add `read_coaching_guide(topic)` schema |
| Brain-direct tool handler | `core/tools.py:1286–1307` | Add `_handle_read_coaching_guide(topic)` |
| `_HANDLERS` dispatch | `core/tools.py:1470` | Add entry for `read_coaching_guide` |
| SMART_AGENT_DIRECT_TOOLS | `core/tools.py` | Add `read_coaching_guide` to the set |

### Package Legitimacy Audit

> No external packages are installed in this phase.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
prompts/smart_agent.md
  └── {coaching_guide} placeholder ──► render_smart_system()
                                           │
                                           ├── self._coaching_guide_content
                                           │      (loaded once at startup by
                                           │       _load_coaching_guide())
                                           │      ≈200–300 lines slim core
                                           │
                                           └── returns resolved system prompt
                                                  ↓
                                           Brain (gemini-3.5-flash) sees
                                           slim core on EVERY call

When brain needs deep content:
  Brain calls read_coaching_guide(topic)
       ↓
  _handle_read_coaching_guide(topic)
       │   reads docs/COACHING_GUIDE.md
       │   finds <!-- SECTION: {topic} --> anchor
       └── returns the section text (< 2000 tokens)
            ↓
       Brain uses it in its response
```

### Recommended Project Structure — New / Modified Files

```
docs/
├── COACHING_GUIDE.md        # NEW — rich 1000+ line guide with section anchors
├── hybrid_athlete_blueprint.md  # UNCHANGED (source of Amit's specifics)
prompts/
├── smart_agent.md           # MODIFIED — add {coaching_guide}, harden Tier A/B contract,
│                            #   add critique posture, remove old D-13 blanket guard
core/
├── main.py                  # MODIFIED — _load_coaching_guide() + render_smart_system injection
└── tools.py                 # MODIFIED — read_coaching_guide schema + handler + dispatch
tests/
├── test_main_render_smart_system.py  # MODIFIED — add {coaching_guide} substitution tests
└── test_tools.py            # MODIFIED — add read_coaching_guide registration tests
```

### Pattern 1: `_load_coaching_guide()` — Startup Cache (mirrors `_load_self_md()`)

**What:** Read `docs/COACHING_GUIDE.md` once at startup, store on orchestrator, inject as stable prefix.
**When to use:** This pattern is correct whenever a stable document should benefit from Gemini's prompt caching — the stable prefix lands before dynamic content (self_state, journal, today_date).

```python
# Source: core/main.py:757 (_load_self_md pattern — mirror exactly)

def _load_coaching_guide() -> str:
    """Read docs/COACHING_GUIDE.md from disk. Returns empty string if absent.

    Called once at startup; result stored on orchestrator and injected
    into every smart_system prompt via render_smart_system().
    """
    root = Path(__file__).resolve().parent.parent
    path = root / "docs" / "COACHING_GUIDE.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "COACHING_GUIDE.md not found at %s — coaching knowledge injection disabled",
            path,
        )
        return ""
```

**In `AgentOrchestrator.__init__`** (after `_load_self_md` on line ~219):
```python
# Load slim coaching guide digest once at startup.
# Per D-04: only the slim core digest (~200–300 lines) is injected as a
# stable cached prefix. The full guide is read on-demand by read_coaching_guide().
self._coaching_guide_content = _load_coaching_guide_slim()
```

**Note:** Either (a) `COACHING_GUIDE.md` has a `<!-- SLIM_CORE_START -->` / `<!-- SLIM_CORE_END -->` marker pair and `_load_coaching_guide_slim()` extracts that block, OR (b) the slim core lives in a separate `docs/COACHING_GUIDE_CORE.md`. Option (a) is recommended: one file, section markers, simpler to maintain. [ASSUMED — see Assumptions Log A1]

### Pattern 2: `read_coaching_guide(topic)` — Brain-Direct Tool

**What:** On-demand deep-section lookup. Brain calls this tool when a specific topic needs a mini-lesson or the user asks "why?"
**When to use:** Only when the slim core is insufficient for the query. Consistent with D-14: one-liner rationale by default, mini-lesson on demand.

**Schema** (in `TOOL_SCHEMAS` list, near `get_training_profile` at ~line 653):
```python
# Source: core/tools.py:653–666 (get_training_profile pattern — mirror)
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

**Handler** (~line 1286):
```python
# Source: core/tools.py:_handle_read_own_source pattern
def _handle_read_coaching_guide(topic: str) -> str:
    """Brain-direct: return the coaching guide section for the requested topic."""
    import re as _re
    root = Path(__file__).resolve().parent.parent
    guide_path = root / "docs" / "COACHING_GUIDE.md"
    try:
        content = guide_path.read_text(encoding="utf-8")
    except OSError:
        return json.dumps({"error": "COACHING_GUIDE.md not found"})

    # Normalize topic slug
    slug = topic.strip().lower().replace(" ", "-").replace("_", "-")

    # Find the section by anchor marker <!-- SECTION: slug -->
    pattern = _re.compile(
        r"<!-- SECTION: " + _re.escape(slug) + r" -->(.*?)(?=<!-- SECTION:|$)",
        _re.DOTALL | _re.IGNORECASE,
    )
    m = pattern.search(content)
    if not m:
        # Fuzzy fallback: first section whose slug contains any word of the query
        for word in slug.split("-"):
            fallback = _re.compile(
                r"<!-- SECTION: [^-]*" + _re.escape(word) + r"[^>]* -->(.*?)(?=<!-- SECTION:|$)",
                _re.DOTALL | _re.IGNORECASE,
            )
            fm = fallback.search(content)
            if fm:
                return json.dumps({"topic": slug, "content": fm.group(1).strip()})
        return json.dumps({"error": f"Section '{topic}' not found in COACHING_GUIDE.md"})

    return json.dumps({"topic": slug, "content": m.group(1).strip()})
```

**`_HANDLERS` dispatch** (~line 1470):
```python
"read_coaching_guide": lambda args: _handle_read_coaching_guide(**args),
```

**`SMART_AGENT_DIRECT_TOOLS` set** — add `"read_coaching_guide"` to the existing set.

### Pattern 3: `prompts/smart_agent.md` — Tier A/B Contract Hardening

**What:** Replace the current blanket no-fabrication guard (lines 121–130) with the recency-windowed data-presence contract. Harden the Phase 21 Tier A/B framing (lines 105–112) to include explicit windows. Add the critique posture block. Add `{coaching_guide}` placeholder.

**Where `{coaching_guide}` lands in the template:** At the very top — before `{self_md}` — so the stable coaching knowledge lands first in the cached prefix order:
```
{coaching_guide}

{self_md}
...
```
[ASSUMED — see Assumptions Log A2; the exact position affects Gemini caching. `self_md` is documented as "stable — benefits from cache"; coaching_guide is also stable. Either can come first. Recommendation: coaching_guide first since it's more volatile across phases than self_md.]

**Existing Phase 21 Tier A/B block (lines 105–112) — keep, expand:**
```markdown
Tier A vs Tier B data discipline:
- **Tier A (targets — in the profile):** dated_goals, weekly_split targets,
  nutrition_targets, plan_start_date. Always citable as "your target" or
  "your plan calls for." They live in the profile and are always up to date.
- **Tier B (measured actuals — from Garmin / TrainingLogStore):** current pace,
  current lifts, recent RPE, actual nutrition intake. Derive at read time from
  the real data tools — **never hand-seed Tier B values in the profile** and
  **never invent them if the tool returns nothing**.
```

**Replace / expand with the recency-windowed contract:**
```markdown
Tier A vs Tier B data-presence contract:

**Tier A — blueprint targets (always citable):**
dated_goals, weekly_split targets, nutrition_targets, plan_start_date, fueling_timeline,
supplement_schedule. Always citable as "your target" or "your plan calls for."
These live in the profile and are always current.

**Tier B — measured actuals (recency-gated):**
Derive at read time from Garmin / TrainingLogStore / MealStore.
Never invent. Recency windows:
  - Strength lifts (bench, squat, weighted pull-ups, etc.): citable if logged ≤ 14 days ago
  - Running pace (threshold, long run, interval): citable if logged ≤ 7 days ago
  - Nutrition / macros: citable if logged ≤ 2 days ago
  - Garmin recovery (HRV, sleep score, body battery, resting HR): always fresh — cite it

**When data is within window:** cite directly. e.g. "Your last logged bench was 92.5kg."

**When data is past window but exists:** name the number + flag its age.
e.g. "Your last logged bench was 92.5kg — though that was 18 days ago, Sir,
so treat it as a stale reference, not your current number."
Upper bound: beyond 3× the window (42 days for lifts, 21 days for pace, 6 days for nutrition)
treat as no-data (use D-08 behavior below).

**When there is no data at all:**
Say "I don't have a recent [metric] logged, Sir" and cite the blueprint goal as
"your target," never as current performance, never an invented number.
e.g. "I don't have a recent bench logged, Sir. Your target is 100kg by October."
```

**Remove lines 121–130** (the old blanket guard that starts "If the training profile is empty…do NOT invent thresholds…").

**Critique posture block (new, append after the specificity bar):**
```markdown
Structural critique posture:
When your coaching knowledge or Amit's data clearly shows a structural element of
the plan or his habits is suboptimal — training architecture, target sizing, timing,
sequencing — name the flaw and the fix directly. Do not soften or hedge.
e.g. "Sir, your protein target (150g/day ≈ 1.6g/kg) is low for concurrent strength
and endurance volume. 180–190g (~2.0g/kg) is the evidence-based floor for this load.
Worth reconsidering." Then offer to record the change via update_plan if Sir agrees.
Rules:
- Structural critique only (design-level: target / architecture / timing / sequencing).
  Not daily micro-tweaks ("add 12g carbs to lunch").
- Volunteer once — do not repeat the same structural critique on the same topic within
  the same conversation or within the same cron day.
- Never silently rewrite. Call update_plan / update_training_profile only on Amit's
  explicit confirmation ("yes", "do it", "update that").
```

**Specificity bar (new or replace generic coaching line):**
```markdown
Specificity bar:
Every coaching point must name: (1) the session type, (2) the target load or pace,
(3) a one-line rationale.
Wrong: "Do your strength session tonight, Sir."
Right: "Tonight: top-set bench — aim for a heavy triple ~92kg. Main strength stimulus
this block toward the 100kg October target."
Expand to a 3–4 sentence mini-lesson only when Sir asks 'why?' or the topic genuinely
warrants it — and pull the deep section via read_coaching_guide(topic).
```

### Anti-Patterns to Avoid

- **Inventing a Tier B number:** Stating "your bench is currently ~85kg" when `TrainingLogStore` has returned nothing. Hard violation of the data-presence contract.
- **Re-nagging the same structural critique:** Volunteer structural critique once; suppress repetition within the same conversation and same cron-day. Phase 24 introduces formal cross-cron dedup; Phase 22 needs basic same-conversation discipline.
- **Deep lookup for every coaching message:** `read_coaching_guide(topic)` on the morning briefing path dramatically inflates token cost. The slim core must cover the session-type cues, fueling slots, and key flags that every cron needs. Deep lookup is for chat "why?" queries and the Sunday weekly review.
- **Putting `{coaching_guide}` after volatile placeholders:** `{today_date}` and `{self_state}` change every call, breaking Gemini's cached-prefix optimization. Stable content (`{coaching_guide}`, `{self_md}`) must precede dynamic content.
- **Tool available to worker:** `read_coaching_guide` must be brain-direct only (in `SMART_AGENT_DIRECT_TOOLS`, absent from `get_worker_schemas`). The worker does not make coaching judgments.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Section extraction from guide | Custom parser / RAG pipeline | Simple regex on `<!-- SECTION: slug -->` anchors | One file, no extra dependencies, deterministic |
| Stale-data age computation | Complex date arithmetic | `(today - logged_date).days` compared to window constant | Trivial; no special library needed |
| Prompt caching | Manual caching layer | Let Gemini's stable-prefix caching work automatically by placing stable content first | Already built into Gemini AI Studio — just maintain prefix order |
| Knowledge versioning | Separate versioned files | Section markers in one file with inline source tags | The guide is authored once; no versioning system needed at this scale |

**Key insight:** This is a prompt-engineering phase. The "don't hand-roll" rule here means: don't build infrastructure (RAG, vector search, knowledge graph) for what is simply a well-structured markdown file with section anchors.

---

## Domain Science: What COACHING_GUIDE.md Must Contain

This section is the raw material for authoring the guide. Each finding carries a source tier:
- `[PEER]` = peer-reviewed research (PMC / journal)
- `[CONSENSUS]` = practitioner consensus (multiple expert sources agree)
- `[HEURISTIC]` = practitioner heuristic, limited formal evidence

### 1. Concurrent Training & The Interference Effect

**The Interference Effect — Definition:** [PEER]
Concurrent strength + endurance training in the same program can attenuate strength and hypertrophy gains compared to strength-only training. The mechanism is competing molecular signaling: endurance work activates AMPK (energy-sensing pathway), which can inhibit mTOR (the anabolic signaling pathway that drives muscle protein synthesis). AMPK phosphorylation → TSC2 activation → mTOR suppression → blunted protein synthesis signal.

Sources: [PMC7153037](https://pmc.ncbi.nlm.nih.gov/articles/PMC7153037/), [PMC3854410](https://pmc.ncbi.nlm.nih.gov/articles/PMC3854410/), Barbellmedicine.com interference review

**The AM/PM Split as the Primary Mitigation:** [PEER]
Session separation of ≥ 6 hours substantially reduces acute interference. Running economy, neuromuscular fatigue, and the residual AMPK signal dissipate over 6+ hours, restoring a clean anabolic window for the PM strength session. This is the core rationale for Amit's AM run / PM lift split — it is not merely aesthetic scheduling.

Applied to Amit's blueprint: AM run finishes by ≈09:00; PM strength is ≥ 17:00 on most days. The separation window is ≥ 8 hours — adequate. [PEER]

Source: [PMC5752732](https://pmc.ncbi.nlm.nih.gov/articles/PMC5752732/), [PMC11359207](https://pmc.ncbi.nlm.nih.gov/articles/PMC11359207/)

**Session Order Within Single-Session Training:** [PEER]
When sessions cannot be separated (rare for Amit — Sunday mixed practice is the exception), resistance-before-endurance is superior for lower-body strength adaptations in prolonged (≥5 weeks) programs. However, Amit's Sunday protocol is explicitly mixed practice (sprints + VO2 max + calisthenics) — not a heavy strength session — so order within Sunday is less critical.

Source: [PMC5752732](https://pmc.ncbi.nlm.nih.gov/articles/PMC5752732/)

**Endurance Modality Matters:** [PEER]
HIIT (high-intensity interval) endurance as a modality causes less interference with strength gains than high-volume steady-state endurance, likely because HIIT generates less overall AMPK load per session. Amit's blueprint uses threshold runs (not pure HIIT) — these are an intermediate case. The AM/PM separation is the primary protective factor.

**Practical Red Flags (for Claude's critique posture):**
- Same-session AM strength + PM run = acceptable (rare overlap risk)
- Same-session AM long run + PM heavy strength = manageable with 8h separation and post-run reload
- Heavy strength immediately after a threshold run (no separation) = interference risk — flag this if Amit ever proposes it [PEER]

---

### 2. Block Periodization for Amit's Hybrid Program

**What Block Periodization Is:** [CONSENSUS]
Dividing a training year into dedicated mesocycles (blocks) that emphasize one quality while maintaining others. For a 16-week program like Amit's, the blocks are roughly:
- Weeks 1–4: Aerobic Base (higher Zone-2 volume, strength at 3–5 rep max)
- Weeks 5–8: Capacity Build (increasing threshold work + volume, strength maintained)
- Weeks 9–12: Deep Waters / Peak Engine (near-race threshold paces, strength peak)
- Weeks 13–14: Race Specificity (pace lock-in, taper prep)
- Weeks 15–16: Taper + Race

Applied to Amit's aerobic table (§4 of blueprint — loose reference only, not a contract):
The aerobic progression table already has these phases named. The coaching knowledge should reference them by name when contextualizing weekly training: "You're in the Aerobic Base block, Sir — this is the volume-building phase. Resist the urge to add intensity."

**Why Block > Fully Concurrent for the HM Goal:** [CONSENSUS]
A pure concurrent approach (same intensity in every modality every week) is appropriate for maintenance but plateaus faster for peak performance. Amit's 1:25 HM target is 4:01/km — a genuine stretch goal requiring structured aerobic progression. Block structure provides the concentrated stimulus and planned overreach + deload pattern needed.

**Deload Weeks:** [PEER / CONSENSUS]
Weeks 4, 8, 12 in Amit's plan are deload weeks (blueprint §4). Deload = reduce volume ~40–50% while maintaining intensity. Key coaching point: deload weeks are when neural supercompensation occurs — strength top-sets often feel easier, not harder. Do not skip deloads.

**Benchmark Timing:** [CONSENSUS]
Benchmark tests belong at deload-week ends (Weeks 4, 8, 12, 16) when fatigue is lowest. This is Amit's stated philosophy: "test at block ends, not mid-cycle." Mid-block testing fatigues the athlete and gives false readouts. (Phase 23 builds the tooling; Phase 22 only needs to reference this principle in the guide.)

---

### 3. Session Execution

#### 3a. Threshold Runs (Wednesday AM + progressive volume)

**What a Threshold Run Is:** [PEER]
The lactate threshold (LT2 / anaerobic threshold) is the highest intensity at which blood lactate is at steady state. For Amit's target (1:25 HM = 4:01/km race pace), threshold pace is approximately **3:50–3:55/km** (Phase 1–3 blocks) progressing to **4:01/km lock-in** (Weeks 13–14). The Wednesday sessions are specifically named the "1:25 HM Engine" in the blueprint.

Applied: Wednesday threshold volume starts at 6km (Week 1) and builds to 11km (Week 11). This is total work volume, not warm-up. Standard structure: 2–3km warm-up Zone 2 → threshold intervals → 1–2km cool-down.

**Execution Cues:** [CONSENSUS]
- RPE 6–7 / 10 ("comfortably hard" — can say 3–4 words, not a sentence)
- Breathing: heavy but controlled, not ragged
- Should feel difficult at first, settles at ~15 minutes
- Pace discipline: do NOT exceed target pace on good days — consistency matters more than peak effort
- Strides (Tuesday AM: 6×20s): neuromuscular priming; should be at sprint pace (3:00–3:20/km) with full recovery between; not exhausting

Sources: [PMC10496601](https://pmc.ncbi.nlm.nih.gov/articles/PMC10496601/), [PMC10611166](https://pmc.ncbi.nlm.nih.gov/articles/PMC10611166/)

**Easy Run Cues (Monday, Thursday):** [CONSENSUS]
Zone 2 = 4:50–5:30/km (per blueprint §4). Conversational pace — can speak full sentences. HR ≤ 75% HRmax. Monday is an active recovery flush after Sunday; Thursday is a second easy day. These sessions build aerobic base, not fitness — resist the urge to push pace.

**Long Run (Friday):** [CONSENSUS]
Start at 16km Zone 2 (Week 1), peak at 26km (Week 11), with HM-pace finish segments in Phase 4 (Weeks 9–11). Key rule: Weeks 1–8, the long run is strictly Zone 2 — no progression run until the Capacity Build phase. Going too hard too early on the long run is a common injury vector.

#### 3b. Top-Set Strength (Monday PM Lower A, Tuesday PM Upper A)

**What a Top Set Is:** [CONSENSUS]
The heaviest working effort of the session, typically 85–95% of 1RM, for 3–5 reps. The purpose: teach the nervous system to handle heavy loads without crossing to failure. Not the only set — there are back-off sets after.

Applied to Amit's bench (Upper Body A):
- 4 sets × 3–5 reps driving toward 100kg
- Top set is the heaviest of the 4; remaining 3 are back-off sets (typically 80–85% of top set weight)
- After the final set: immediately perform 1 max-effort set of bodyweight push-ups ("fatigue squeeze" / drop set)
- The drop set capitalizes on the pump-state for hypertrophy while the heavy sets drive neural strength

**Weekly Progression Model:** [CONSENSUS]
Double progression: when all 4 sets hit 5 reps with clean form, add 1.25–2.5kg to the bar. If the top set only hit 3, stay at the same weight next session. Target: +2.5kg per 2–3 weeks on bench (10–12 weeks = ~10kg gain over the block — consistent with the 92.5kg → 100kg target).

Applied to Amit's squat (Lower Body A):
- 3 sets × 3–5 reps heavy (top set + 2 back-off)
- Same double-progression model; +2.5–5kg increments

**Red Flags:** Too much fatigue before the heavy lift (e.g., excessive assistance work beforehand), or going to muscular failure on the top set. Failure compromises recovery and neural drive for subsequent sessions. [CONSENSUS]

Source: [StrongFirst 3-5 method](https://www.strongfirst.com/the-3-5-method-revisited/), [powerliftingtechnique.com top sets](https://powerliftingtechnique.com/how-powerlifters-use-top-and-working-sets-to-build-max-strength/)

#### 3c. Calisthenics Progressions (Upper B — Weighted Dips + Pull-ups)

**Upper Body B (Thursday PM) Purpose:** [CONSENSUS]
Volume / Capacity day — accumulates total reps in pushing and pulling. Weighted dips + weighted pull-ups (3 sets heavy + max-rep drop set). This is the "absolute ceiling" session for calisthenics targets (125 push-ups, 35 pull-ups by November).

**Weighted vs. Bodyweight Balance:**
- Weighted dips/pull-ups at 70–80% of current 1RM for 3–5 reps = neural strength stimulus
- The bodyweight max-rep drop set immediately after = volume / capacity stimulus
- This dual approach (heavy + volume) is the most efficient path to both strength (35 weighted pull-ups) and endurance (35+ bodyweight reps) [CONSENSUS]

**Progressive Loading Cap:** [CONSENSUS]
Add no more than 1–2.5kg per week on weighted movements. For pull-ups especially, elbow tendons adapt slower than muscles — exceeding 2.5kg/week increases injury risk. If form breaks on the top set, reduce weight rather than adding.

**Volume Targets for November Goals:** [HEURISTIC]
125 push-ups target = able to perform sets of 25–30 with short rest. 35 pull-ups target = able to perform 10+ per set with 2–3 minute rest. Both require the bodyweight drop-set volume: don't skip it thinking "it's just a drop set."

Source: [Calisthenics Association weighted pull-up program](https://calisthenicsassociation.org/blog/weighted-pull-up-program/)

#### 3d. Sunday Mixed Practice (Sprints + VO2 Max + Calisthenics)

**VO2 Max Intervals:** [PEER]
Effective physiological stimulus: maintain intensity at ≥90% VO2max for several minutes total. Longer intervals (3–5 minutes) with active recovery achieve this better than very short sprints (<60s). Applied to Sunday: 4–6×3min at sprint effort with 90s–2min recovery is evidence-consistent for VO2max development.

**Sprint Cues:** [CONSENSUS]
20s sprint protocol (strides/true sprints): maximal or near-maximal effort, full recovery (2–3min) between. These serve neuromuscular purposes (fast-twitch activation, 400m prep) rather than aerobic development.

**Mixed Calisthenics on Sunday:** [CONSENSUS]
Sunday calisthenics serve as a skill/capacity session — not a heavy strength day. Bodyweight or light-weighted movements, focusing on technique, volume, and active recovery from Saturday rest.

Source: [PMC11743937](https://pmc.ncbi.nlm.nih.gov/articles/PMC11743937/), [PMC10099854](https://pmc.ncbi.nlm.nih.gov/articles/PMC10099854/)

---

### 4. Fueling Science

#### 4a. Peri-Workout Fueling Architecture

Applied directly to Amit's 6-slot blueprint fueling timeline:

**Slot 1 — Pre-AM Run (30–50g simple carbs + coffee):** [PEER / CONSENSUS]
Simple carbs (banana, electrofuel) top off liver glycogen depleted overnight. Coffee: 3–6mg/kg caffeine enhances endurance performance (reduces RPE, improves fat oxidation). The small carb amount avoids GI distress during running. Do NOT train fasted for threshold runs — glycogen availability is critical at lactate threshold pace. [PEER]

**Slot 2 — Post-AM Run Reload (massive carb hit + 3–4 eggs):** [PEER]
Glycogen resynthesis is fastest in the first 30–45 minutes post-exercise. Optimal rate: 0.8g carbohydrate/kg/hour + 0.2–0.4g protein/kg/hour. For Amit (~75–80kg): ~60g carb + 15–20g protein immediately post-run. Oats/rice/sourdough + whole eggs hits this target. Vitamin D3+K2 and Omega-3 taken here (with fat from eggs — fat-soluble vitamins require dietary fat for absorption). [PEER]

Source: [PMC11206787](https://pmc.ncbi.nlm.nih.gov/articles/PMC11206787/), [blog.pre-script.com peri-workout guide](https://blog.pre-script.com/structured-peri-workout-nutrition/)

**Slot 3 — Mid-Day (lean beef/steak + complex carbs + greens):** [CONSENSUS]
Sustained engine between sessions. Goal: protein synthesis window maintenance + glycogen top-off before PM lift. Protein every 3–4 hours maximizes muscle protein synthesis throughout the day. Complex carbs (rice, sweet potato) provide sustained glucose without the spike/crash of simple sugars.

**Slot 4 — PM Pre-Lift (electrofuel or fruit, 30–60min before; Beta-Alanine):** [PEER / CONSENSUS]
30–50g fast carbs 30–60min before lifts: raises blood glucose for the session. Beta-alanine (3.2g/day, split doses) increases muscle carnosine over weeks → buffers lactic acid → extends capacity in high-intensity sets. Beta-alanine is effective for repeated high-intensity bouts lasting >60 seconds — directly relevant to 3–5 rep strength sets and max-rep drop sets. [PEER]

Source: [PMC11206787](https://pmc.ncbi.nlm.nih.gov/articles/PMC11206787/)

**Slot 5 — PM Post-Lift (high protein + easily digestible carbs + Creatine):** [PEER]
Post-lift anabolic window: 20–40g protein + 40–60g fast carbs. Creatine (3–5g/day maintenance dose) added to shake — timing relative to workout is less critical than consistent daily intake; post-workout is a fine convention. Creatine increases phosphocreatine availability for the next session's high-intensity sets (bench, squat). [PEER]

Evidence for creatine: consistently supports strength and power output; one of the few supplements with robust evidence across training modalities. [PEER]

Source: [PMC11206787](https://pmc.ncbi.nlm.nih.gov/articles/PMC11206787/)

**Slot 6 — Pre-Bed (Magnesium Glycinate + Zinc + Copper):** [PEER / CONSENSUS]
Magnesium glycinate 200–400mg elemental, 30–60min before bed: most evidence-backed magnesium form for sleep quality. 8-week RCT showed faster sleep onset, longer sleep, fewer awakenings. Sleep is the primary recovery window for muscle protein synthesis. [PEER]

Zinc (up to 40mg/day upper limit) + Magnesium together: support hormone regulation and nervous system recovery. Note: long-term high-dose zinc can reduce copper absorption → copper supplementation co-prescribed (Amit's blueprint already includes it). Taking zinc in the morning and magnesium glycinate at night is an alternative if GI sensitivity is an issue. [PEER / CONSENSUS]

Source: [remedysnutrition.com magnesium glycinate sleep review](https://remedysnutrition.com/blogs/sleep-wellness/magnesium-glycinate-for-sleep-what-the-research-shows), [ubiehealth.com zinc+magnesium](https://ubiehealth.com/doctors-note/magnesium-zinc-combination-sleep-immunity-boost-4751q1)

#### 4b. Protein Timing

**Daily Total — The Most Important Variable:** [PEER]
Total daily protein intake matters more than timing windows. For hybrid athletes doing concurrent strength + endurance training, evidence-based floor: **1.6–2.0g/kg/day**. The 1.6g/kg figure (from several concurrent training trials) is sufficient for most strength adaptations; 1.8–2.0g/kg provides additional benefits for lean mass during high training volume. [PEER]

Source: [PMC10388821](https://pmc.ncbi.nlm.nih.gov/articles/PMC10388821/), [PMC11349518](https://pmc.ncbi.nlm.nih.gov/articles/PMC11349518/)

**Applied Critique (COACH-07 trigger):** Amit's blueprint target is 150g/day. At estimated bodyweight ~75–80kg:
- 150g ÷ 80kg = 1.875g/kg — technically within the evidence-based range (≥1.6g/kg)
- However, with both heavy strength work AND high-volume endurance (threshold runs + long runs), the upper end of the range (180–190g at ~2.0–2.4g/kg) would provide a more robust muscle protein synthesis signal
- This is a legitimate structural critique (COACH-07): not wrong, but potentially underoptimized
- Structural critique: "Sir, 150g protein (≈1.875g/kg if 80kg) is at the low end of the concurrent-training evidence range. For your volume of both strength AND endurance work, 180–190g would be more robust. Worth reconsidering." [PEER]

Source: [PMC11613885](https://pmc.ncbi.nlm.nih.gov/articles/PMC11613885/), [weareathleats.com hybrid athlete protein](https://www.weareathleats.com/knowledge/balancing-strength-and-endurance-nutrition-as-a-hybrid-athlete)

**Protein Distribution:** [CONSENSUS]
20–40g per meal, every 3–4 hours. Amit's 3 main protein slots (post-run eggs, mid-day steak, post-lift) cover this adequately if portions are sufficient.

#### 4c. Carbohydrate Periodization

**The Principle:** [PEER / CONSENSUS]
Carbohydrate needs vary with session intensity and duration. "Fuel for the work required" — not uniform daily carb intake. Applied to Amit's split:

| Day | Session Type | Carb Guidance |
|-----|-------------|---------------|
| Sunday | Mixed Practice (sprints + VO2 + calisthenics) | High — 350g+ target; higher carb load for high-intensity day |
| Monday | Easy Run + Lower A Strength | Moderate-High — 350g; glycogen for PM heavy squats |
| Tuesday | Medium Long Run + Strides + Upper A Heavy | High — 350g+ if ≥12km run day |
| Wednesday | Threshold Run + Lower B Speed | High — threshold runs consume glycogen rapidly |
| Thursday | Easy Run + Upper B Volume | Moderate — 300–350g; lighter run day |
| Friday | Long Run | High — 350g+ for 16–26km long runs; intra-run carbs for runs >90min |
| Saturday | Rest | Moderate — 250–300g; reduce if genuinely passive rest |

Amit's target of 350g carbs/day is appropriate for high-volume days; could be reduced on Saturday (rest) and Thursday (easy + volume). This is a discretion area, not a critical critique. [CONSENSUS]

Source: [sensai.fit carb periodization framework](https://www.sensai.fit/blog/carbohydrate-periodization-training-intensity-fueling-framework)

#### 4d. Supplement Rationale Summary

| Supplement | Mechanism | Evidence | Applied to Amit |
|-----------|-----------|----------|-----------------|
| Creatine | Increases PCr stores → more ATP for high-intensity efforts | VERY HIGH [PEER] | 3–5g/day post-lift; supports bench/squat top sets and sprint capacity |
| Beta-Alanine | Increases carnosine → buffers H+ in muscle → delays fatigue in 60s+ efforts | HIGH [PEER] | 3.2g/day split; pre-lift Slot 4; benefits high-rep drop sets + threshold runs |
| Magnesium Glycinate | Activates GABA → sleep induction + muscle relaxation | HIGH [PEER] | 200–400mg elemental pre-bed Slot 6; primary sleep quality support |
| Zinc | Hormone regulation, immune function, enzyme cofactor | MEDIUM [PEER] | Slot 6 with copper; keep to ≤40mg/day to avoid copper depletion |
| Copper | Counteracts zinc-induced copper depletion | MEDIUM [CONSENSUS] | Co-prescribed with zinc; blueprint already includes it — correct approach |
| Vitamin D3+K2 | Muscle function, bone density, immune, inflammation | HIGH [PEER] | Post-run Slot 2 with dietary fat for absorption; 1000–2000 IU D3 typical |
| Omega-3 | Reduces exercise-induced inflammation (CK, IL-6, CRP, DOMS) | HIGH [PEER] | Post-run Slot 2 with fat-containing meal; 1–3g EPA+DHA/day |

Source: [PMC12498230](https://pmc.ncbi.nlm.nih.gov/articles/PMC12498230/), [puresport.co D3 performance](https://puresport.co/en-us/blogs/the-run-down/the-power-of-vitamin-d3), [grassrootshealth.net omega-3 recovery](https://www.grassrootshealth.net/blog/omega-3s-inflammation-and-muscle-recovery-what-the-latest-meta-analysis-reveals/)

---

## COACHING_GUIDE.md Structure Recommendation

The guide should be structured as follows. Each H2 section has a `<!-- SECTION: slug -->` anchor for the lookup tool. The first major section (`## Core Principles Digest`) is the **slim core** — delimited by `<!-- SLIM_CORE_START -->` and `<!-- SLIM_CORE_END -->` markers so `_load_coaching_guide_slim()` can extract exactly that block at startup. [ASSUMED — A1]

```
docs/COACHING_GUIDE.md

<!-- SLIM_CORE_START -->
## Core Principles Digest

### AM/PM Split — The Interference Mitigation Rule
### Session-by-Session Execution Cues (one paragraph each, concise)
### Fueling Slot Map (6 slots, one-line each)
### Key Critique Flags (protein floor, deload compliance, threshold pace discipline)
### Tier A/B Quick Reference
<!-- SLIM_CORE_END -->

<!-- SECTION: interference-effect -->
## Concurrent Training & The Interference Effect
[deep science, AMPK/mTOR, mitigation strategies, research citations]
<!-- end section -->

<!-- SECTION: block-periodization -->
## Block Periodization
[blocks, deload weeks, benchmark timing, Amit's 16-week arc]
<!-- end section -->

<!-- SECTION: threshold-runs -->
## Threshold Runs
[execution protocol, pacing cues, RPE, Wednesday structure]
<!-- end section -->

<!-- SECTION: top-set-strength -->
## Top-Set Strength
[bench, squat, double progression, drop sets, fatigue management]
<!-- end section -->

<!-- SECTION: calisthenics-progressions -->
## Calisthenics Progressions
[weighted pull-ups, dips, volume targets for November goals]
<!-- end section -->

<!-- SECTION: intervals-vo2max -->
## Intervals & VO2 Max
[Sunday mixed practice, sprint protocol, 90% VO2max stimulus]
<!-- end section -->

<!-- SECTION: peri-workout-fueling -->
## Peri-Workout Fueling
[all 6 slots in depth, timing, quantities, glycogen dynamics]
<!-- end section -->

<!-- SECTION: protein-timing -->
## Protein Timing
[daily total, distribution, applied critique of 150g target]
<!-- end section -->

<!-- SECTION: carb-periodization -->
## Carbohydrate Periodization
[fuel-for-work principle, day-by-day applied to Amit's split]
<!-- end section -->

<!-- SECTION: supplements -->
## Supplement Rationale
[creatine, beta-alanine, Mg, Zn, Cu, D3K2, Omega-3 — mechanism + evidence + dose]
<!-- end section -->
```

**Slim core target:** ~200–300 lines. Each session type gets one clear execution paragraph. The fueling slot map is 6 one-liners. Key critique flags (3–5 bullet points: protein floor, threshold pace discipline, deload compliance, AM/PM ordering rule, long run Zone-2 discipline) tell Klaus when to volunteer a critique without looking things up.

---

## Common Pitfalls

### Pitfall 1: `{coaching_guide}` Placeholder Position Breaking Caching
**What goes wrong:** If `{coaching_guide}` is placed after `{self_state}` or `{today_date}` in the template, every call has different prefix content before the coaching guide, destroying Gemini's stable-prefix cache optimization.
**Why it happens:** Natural instinct is to put the coaching section near the coaching instructions in the middle of the prompt, not at the top.
**How to avoid:** Maintain strict ordering: `{coaching_guide}` first, `{self_md}` second, then volatile content (`{self_state}`, `{journal_digest}`, `{today_date}`). Mirror the existing comment in `render_smart_system`: "Stable content first, then dynamic."
**Warning signs:** Higher-than-expected token costs on morning briefing / autonomous tick calls.

### Pitfall 2: Slim Core Loads Whole Guide Instead of Digest
**What goes wrong:** `_load_coaching_guide_slim()` accidentally reads the entire 1000+ line file instead of just the core digest block, injecting ~3000–5000 tokens into every single prompt call.
**Why it happens:** Off-by-one in the marker extraction regex, or forgetting to add the `<!-- SLIM_CORE_START/END -->` markers to the file.
**How to avoid:** (a) Write a unit test that verifies the slim-core load returns fewer than 350 lines, and (b) add an assertion in `_load_coaching_guide_slim()` that logs a warning if the extracted content exceeds a threshold (e.g., 10,000 chars).
**Warning signs:** Smart agent system prompt length explodes; token usage per call rises dramatically.

### Pitfall 3: `read_coaching_guide` Listed as Worker Tool
**What goes wrong:** Worker agent (`deepseek-v4-flash`) gains access to the coaching guide lookup and starts calling it autonomously, costing tokens without brain judgment.
**Why it happens:** Accidentally including the schema in `get_worker_schemas()` or forgetting to add it to the `SMART_AGENT_DIRECT_TOOLS` exclusion set.
**How to avoid:** Mirror `get_training_profile` exactly — it is in `SMART_AGENT_DIRECT_TOOLS` (which excludes it from worker), not in the worker schema list. Add to `test_tools.py` with the same test pattern as Phase 19 tool registration tests.
**Warning signs:** Worker tool call logs show `read_coaching_guide` being called.

### Pitfall 4: Stale-Data Upper Bound Not Defined
**What goes wrong:** Klaus cites a 45-day-old bench number with a staleness caveat when it should degrade to "no recent data." The upper-bound rule (3× window) is in the CONTEXT but if absent from the prompt text, Klaus has no guidance.
**Why it happens:** The D-07/D-08 distinction is clear but the 3× cutoff is in Claude's Discretion — it must be explicitly written into the prompt or it won't be honored.
**How to avoid:** Include the upper-bound numbers explicitly in the Tier B contract block in `prompts/smart_agent.md`: "beyond 42 days for lifts, 21 days for pace, 6 days for nutrition → treat as no-data."
**Warning signs:** Klaus hedges on very old data instead of using the "no recent data" phrasing.

### Pitfall 5: Critique Volunteered Repeatedly in Same Context
**What goes wrong:** Klaus mentions the protein target critique in the morning briefing, again in the 21:30 check-in, and again in chat — even though Phase 24 hasn't built cross-cron dedup yet.
**Why it happens:** The critique posture directive says "volunteer it" but Phase 22 only has basic same-conversation suppression; cross-cron dedup is Phase 24.
**How to avoid:** Add an explicit same-conversation suppression rule to the critique posture block: "Once you have raised a structural critique on a topic in this conversation, do not repeat it." For cross-cron suppression, note in the prompt that Phase 24 will add the dedup gate.
**Warning signs:** Multiple identical critique points within a single conversation thread.

### Pitfall 6: `{coaching_guide}` Placeholder Left Unresolved in Cron Templates
**What goes wrong:** `proactive_alert.md`, `morning_briefing.md`, `autonomous.md`, and other cron prompt files don't have `{coaching_guide}` placeholders, but they pass through `render_smart_system()`. If the placeholder is added only to `smart_agent.md`, cron templates that load their own prompt file via `_compose_alert()` / `_compose_briefing()` will not inject the slim core.
**Why it happens:** The cron templates load their own `.md` file directly (`prompt_path.read_text()`), not `smart_agent.md`. They then call `render_smart_system()` to resolve placeholders.
**How to avoid:** Add `{coaching_guide}` to each cron prompt template file that needs coaching knowledge (morning_briefing.md, proactive_alert.md, autonomous.md). `render_smart_system()` already resolves all placeholders — just add the token to the template file. Regression test: run dry-run smoke tests on all crons after the change.
**Warning signs:** Morning briefing coaching output has no session-type specificity (cron working off old generic prompt without the guide).

---

## Regression Surface Analysis

The slim-core injection + `read_coaching_guide` tool land in the following consumers:

### `core/morning_briefing.py`
- **How it composes:** `_compose_briefing()` loads `prompts/morning_briefing.md`, appends `meal_audit.md`, then calls `client.chat()` with a standalone system prompt — it does NOT call `render_smart_system()`. This means `{coaching_guide}` in `morning_briefing.md` will be left as a literal placeholder unless either (a) `morning_briefing.py` explicitly replaces it, or (b) it calls `render_smart_system()`.
- **Recommended fix (Pitfall 6):** Add `{coaching_guide}` to `prompts/morning_briefing.md` and have `_compose_briefing()` inject the slim core content the same way it already injects `{today_date}`. The orchestrator singleton is available via `_get_orchestrator()` (already imported in `autonomous.py`). **OR** pass `coaching_guide_content` as a startup-loaded string to the briefing compose function.
- **Risk if ignored:** SC-2 (briefing names specific session + load) fails — briefing has no guide and produces generic "strength session" output.

### `core/proactive_alerts.py`
- **How it composes:** `_compose_alert()` loads `prompts/proactive_alert.md`, calls `LLMClient.chat()` directly. Same pattern as morning briefing — does not go through `render_smart_system()`.
- **Same fix applies:** Add `{coaching_guide}` placeholder to `proactive_alert.md` and inject the slim core content at compose time.

### `core/autonomous.py`
- **How it composes (Layer 2):** `_compose_layer2()` loads `prompts/autonomous.md`, then calls `orchestrator.render_smart_system(smart_system_template)`. THIS ONE already flows through `render_smart_system()`. As long as `autonomous.md` has the `{coaching_guide}` placeholder and `render_smart_system()` substitutes it, the autonomous tick gets the slim core automatically.
- **Risk:** None from the architecture change, provided `autonomous.md` gains the `{coaching_guide}` placeholder.

### `core/main.py` — `handle_message()` (chat path)
- **How it composes:** Uses `self._smart_prompt_template` (loaded at startup) and calls `render_smart_system()`. Adding `{coaching_guide}` to `smart_agent.md` and `render_smart_system()` substitution covers this automatically.
- **No special handling needed.**

**Summary table:**

| Consumer | Calls `render_smart_system`? | Fix Needed |
|----------|-----------------------------|-|
| `handle_message` (chat) | Yes | Add `{coaching_guide}` to `smart_agent.md` |
| `_compose_layer2` (autonomous) | Yes | Add `{coaching_guide}` to `autonomous.md` |
| `_compose_briefing` (morning) | No | Inject slim core at compose time (see Pitfall 6) |
| `_compose_alert` (proactive) | No | Inject slim core at compose time (see Pitfall 6) |

**Cost discipline for crons:** The prompt bias in D-05 ("high-freq crons stay on the cheap core") should be expressed in `autonomous.md` and `morning_briefing.md` prompts — something like: "You have the coaching guide core already. Only call `read_coaching_guide(topic)` if Sir asks 'why?' or the topic requires a precise protocol not answered by the core above." This is a prompt instruction, not a hard code prohibition.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Slim core is delimited by `<!-- SLIM_CORE_START/END -->` markers in the single `COACHING_GUIDE.md` file, and `_load_coaching_guide_slim()` extracts that block | Patterns; COACHING_GUIDE structure | If a separate file is preferred, the loader function and startup wiring change slightly — minor impact |
| A2 | `{coaching_guide}` is placed before `{self_md}` in `smart_agent.md` for Gemini caching | Patterns: Pattern 3 | If `{self_md}` is more stable (true — it only changes on deploy), putting it first is equally valid; ordering is a cost-efficiency preference, not functional correctness |
| A3 | Amit's approximate bodyweight is ~75–80kg for protein-per-kg calculations | Domain science §4b | If bodyweight is materially different, the protein critique numbers shift slightly; the structural critique direction (150g may be underoptimized) holds across all reasonable bodyweights in the 70–90kg range |
| A4 | The `SMART_AGENT_DIRECT_TOOLS` set exists as a frozenset/set in `core/tools.py` that controls which tools are brain-direct (confirmed by grep; Phase 19 pattern) | Patterns: Pattern 2 | Confirmed [VERIFIED: codebase] — `SMART_AGENT_DIRECT_TOOLS` is defined and used in `get_smart_schemas()` |

**If this table is empty for A4:** That assumption was verified by codebase read.

---

## Open Questions

1. **Bodyweight for protein critique**
   - What we know: Blueprint says 150g protein. Evidence floor for concurrent training: 1.6g/kg.
   - What's unclear: Amit's exact current bodyweight.
   - Recommendation: Use 80kg as the working assumption. At 80kg: 150g = 1.875g/kg — technically above 1.6g/kg floor. Critique is still valid (upper range 2.0–2.4g/kg is better for this volume). Klaus should state: "at ~80kg" to flag the assumption, not assert it as fact.

2. **Slim core line count**
   - What we know: D-04 says ~200–300 lines.
   - What's unclear: Whether 300 lines in the slim core stays within cost budget for 43 autonomous ticks/day.
   - Recommendation: Target 200 lines for the slim core. At ~80 tokens per 100 lines of markdown, 200 lines ≈ 1600 tokens per call — 43 ticks × 1600 tokens = 68,800 tokens/day on the slim core alone. At Groq's free Qwen3 model (tick-brain Layer 1) this costs $0; at Gemini brain (Layer 2, triggered maybe 5×/day), 5 × 1600 = 8,000 tokens — negligible. This budget is fine.

3. **`read_coaching_guide` response size cap**
   - What we know: Deep sections may be 100–400 lines.
   - What's unclear: Whether any single section will exceed Gemini's practical single-tool-result context.
   - Recommendation: Each COACHING_GUIDE.md section should be capped at ~400 lines (~3200 tokens). If a topic is longer, split into subsections with separate anchors (e.g., `peri-workout-fueling-am` and `peri-workout-fueling-pm`).

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified — this phase is pure code/config/file changes, no new services or CLI tools required)

---

## Validation Architecture

> `workflow.nyquist_validation: true` in `.planning/config.json` — section required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none explicitly (run from project root) |
| Quick run command | `python -m pytest tests/test_main_render_smart_system.py tests/test_tools.py -x` |
| Full suite command | `python -m pytest tests/ --ignore=tests/test_google_fit_tool.py -x` (774 passing baseline) |

**Note on full suite:** Full `pytest tests/` in one process can segfault (grpc/protobuf GC, Python 3.13). Run per-file for new tests; use full suite on the CI/CD baseline.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COACH-01 | `{coaching_guide}` placeholder is resolved in `render_smart_system` | unit | `python -m pytest tests/test_main_render_smart_system.py -x -k coaching_guide` | ❌ Wave 0 |
| COACH-01 | `_load_coaching_guide_slim()` returns < 350 lines / < 15000 chars | unit | `python -m pytest tests/test_main_render_smart_system.py -x -k slim_core_size` | ❌ Wave 0 |
| COACH-01 | `read_coaching_guide` tool is in `SMART_AGENT_DIRECT_TOOLS` and NOT in worker schemas | unit | `python -m pytest tests/test_tools.py -x -k read_coaching_guide` | ❌ Wave 0 |
| COACH-01 | `read_coaching_guide` handler returns section content for known topic slug | unit | `python -m pytest tests/test_tools.py -x -k handle_read_coaching_guide` | ❌ Wave 0 |
| COACH-01 | `read_coaching_guide` handler returns error JSON for unknown topic | unit | `python -m pytest tests/test_tools.py -x -k coaching_guide_unknown_topic` | ❌ Wave 0 |
| COACH-06 | No Tier B invented number — behavioral (prompt-only) | manual smoke | See SC-1 validation below | N/A |
| COACH-06 | Staleness caveat emitted for past-window data — behavioral | manual smoke | See SC-1 validation below | N/A |
| COACH-02 | Specificity bar — names session type + load + rationale — behavioral | manual smoke | See SC-3 validation below | N/A |
| COACH-07 | Structural critique posture — behavioral | manual smoke | See SC-4 validation below | N/A |
| Regression | `render_smart_system` no unresolved placeholders after adding `{coaching_guide}` | unit | `python -m pytest tests/test_main_render_smart_system.py -x -k no_unresolved_placeholders` | ✅ (extend existing test) |
| Regression | Morning briefing prompt does not contain literal `{coaching_guide}` after injection | unit | `python -m pytest tests/test_main_render_smart_system.py -x -k briefing_no_literal_placeholder` | ❌ Wave 0 |

### Behavioral Validation Protocols (SC-1 through SC-4)

These success criteria are prompt-behavioral and cannot be verified by automated unit tests alone. Recommended smoke protocol per SC:

**SC-1 (No-data behavior):** Send Telegram message: "What was my last bench press?" when `TrainingLogStore` is empty / has data older than 42 days. Expected: Klaus says "I don't have a recent bench logged, Sir" and cites the October 100kg goal as "your target." Failure: Klaus invents a number or omits the qualifier.

**SC-2 (Cron specificity — morning briefing + evening alert):** Trigger `python -m core.morning_briefing --dry-run --date <tomorrow>`. Expected output names the scheduled session type (e.g., "Tuesday's medium long run + strides") and the plan target (pace or load). Failure: generic "strength session" or "easy run" with no specifics.

**SC-3 (Chat specificity bar):** Send Telegram: "What should I do tonight?" on a Tuesday (Upper Body A day). Expected: Klaus names "top-set bench, ~92kg heavy triple — main strength stimulus toward the 100kg October target." Failure: "Do your strength session."

**SC-4 (Structural critique):** Send Telegram: "Review my nutrition targets." Expected: Klaus mentions the protein target, names the evidence-based floor (1.6–2.0g/kg for concurrent training), and offers to update via `update_plan`. Failure: Klaus either ignores the structural issue or silently modifies the plan without confirmation.

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_main_render_smart_system.py tests/test_tools.py -x`
- **Per wave merge:** Full suite on affected files
- **Phase gate:** SC-1/SC-2/SC-3/SC-4 behavioral smoke tests + full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_main_render_smart_system.py` — extend with `{coaching_guide}` substitution test and slim-core-size guard
- [ ] `tests/test_tools.py` — add `read_coaching_guide` registration tests (schema, handler, direct-tool-only, unknown-topic error)
- [ ] `docs/COACHING_GUIDE.md` — the guide itself must exist with `<!-- SLIM_CORE_START/END -->` and `<!-- SECTION: slug -->` markers before any code tests run

---

## Project Constraints (from CLAUDE.md)

| Directive | How It Applies to Phase 22 |
|-----------|---------------------------|
| Brain (`gemini-3.5-flash`) sees every message | `read_coaching_guide` is brain-direct only — correct |
| Worker never sees coaching judgment tools | Enforce via `SMART_AGENT_DIRECT_TOOLS` exclusion |
| `load_dotenv(override=True)` always | No new env vars in this phase; existing pattern unaffected |
| All GCP/Pinecone names lowercase `klaus-` | No new GCP resources in this phase |
| Brain never routes through worker first | `read_coaching_guide` must NOT be delegatable |
| No new crons, backends, or dependencies | Phase boundary is explicitly prompt + file + tool only |
| Firestore `SERVER_TIMESTAMP` → `DatetimeWithNanoseconds` | Not relevant — guide is file-based, not Firestore |
| 774-test passing baseline must hold | Add new tests; do not break existing `test_main_render_smart_system.py` or `test_tools.py` |

---

## Sources

### Primary (HIGH confidence)
- CLAUDE.md + codebase (core/main.py, core/tools.py, prompts/smart_agent.md) — [VERIFIED: in-session read]
- 22-CONTEXT.md — locked decisions [VERIFIED: in-session read]
- docs/hybrid_athlete_blueprint.md — Amit's blueprint [VERIFIED: in-session read]

### Secondary (MEDIUM confidence — peer-reviewed)
- [PMC7153037](https://pmc.ncbi.nlm.nih.gov/articles/PMC7153037/) — mTOR order in concurrent training
- [PMC3854410](https://pmc.ncbi.nlm.nih.gov/articles/PMC3854410/) — AMPK/mTOR signaling concurrent training
- [PMC5752732](https://pmc.ncbi.nlm.nih.gov/articles/PMC5752732/) — intra-session exercise sequence interference effect
- [PMC11359207](https://pmc.ncbi.nlm.nih.gov/articles/PMC11359207/) — strength/endurance sequence on endurance performance
- [PMC11206787](https://pmc.ncbi.nlm.nih.gov/articles/PMC11206787/) — supplementation strategies for strength and power
- [PMC10388821](https://pmc.ncbi.nlm.nih.gov/articles/PMC10388821/) — 16-week high-protein diets + concurrent training
- [PMC11349518](https://pmc.ncbi.nlm.nih.gov/articles/PMC11349518/) — protein intake lean mass concurrent training
- [PMC11613885](https://pmc.ncbi.nlm.nih.gov/articles/PMC11613885/) — protein intake meta-analysis athletic performance
- [PMC11743937](https://pmc.ncbi.nlm.nih.gov/articles/PMC11743937/) — VO2max interval training long vs short intervals
- [PMC10099854](https://pmc.ncbi.nlm.nih.gov/articles/PMC10099854/) — aerobic HIIT superior for VO2max vs sprint intervals
- [PMC12498230](https://pmc.ncbi.nlm.nih.gov/articles/PMC12498230/) — efficacy of dietary supplements in elite athletes
- [PMC10496601](https://pmc.ncbi.nlm.nih.gov/articles/PMC10496601/) — post-analysis lactate threshold methods
- [PMC10611166](https://pmc.ncbi.nlm.nih.gov/articles/PMC10611166/) — running at fixed lactate thresholds

### Tertiary (MEDIUM confidence — practitioner / evidence-backed)
- [barbellmedicine.com concurrent training interference review](https://www.barbellmedicine.com/blog/concurrent-training-and-the-interference-effect/)
- [blog.pre-script.com peri-workout nutrition complete guide](https://blog.pre-script.com/structured-peri-workout-nutrition/)
- [StrongFirst 3-5 method](https://www.strongfirst.com/the-3-5-method-revisited/)
- [calisthenicsassociation.org weighted pull-up program](https://calisthenicsassociation.org/blog/weighted-pull-up-program/)
- [sensai.fit carbohydrate periodization framework](https://www.sensai.fit/blog/carbohydrate-periodization-training-intensity-fueling-framework)
- [remedysnutrition.com magnesium glycinate sleep](https://remedysnutrition.com/blogs/sleep-wellness/magnesium-glycinate-for-sleep-what-the-research-shows)
- [weareathleats.com hybrid athlete protein](https://www.weareathleats.com/knowledge/balancing-strength-and-endurance-nutrition-as-a-hybrid-athlete)

---

## Metadata

**Confidence breakdown:**
- Codebase architecture: HIGH — in-session read of all referenced files
- Standard stack (no new packages): HIGH — prompt-only phase confirmed
- Coaching domain science (interference, periodization, fueling): HIGH-MEDIUM — anchored in peer-reviewed PMC sources
- Supplement evidence: HIGH for creatine/beta-alanine/magnesium; MEDIUM for zinc/copper/D3K2/omega-3
- Pitfalls: HIGH — derived from direct codebase analysis of cron composition paths

**Research date:** 2026-06-04
**Valid until:** 2026-07-04 (coaching science is stable; code patterns valid until next major refactor)
