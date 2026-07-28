# Phase 33: Occasion Cascade - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-28
**Phase:** 33-occasion-cascade
**Areas discussed:** Skip appetite & Hub contract, Occasion ↔ tick collision, Agentic Layer 2 powers, Explaining silence, Rollout A/B gap, BackgroundTask vs agentic compose, Saving what the templates got right, What the occasion prompts say

---

## Skip appetite & Hub contract

### How much should the three occasions differ in their willingness to stay silent?

| Option | Description | Selected |
|--------|-------------|----------|
| Nightly free, morning near-certain | Nightly/weekly can skip; morning keeps a very high prior (recommended) | |
| All three equally free to skip | One uniform prior, morning included | |
| All three high prior, skip is the exception | Default to speaking; skip only on directive veto or a truly empty day | ✓ |

**User's choice:** All three high prior, skip is the exception
**Notes:** Lowest-risk posture during the flag rollout. → D-01

### When Klaus judgment-skips the morning, what happens to the Hub's day summary?

| Option | Description | Selected |
|--------|-------------|----------|
| Skip = no snapshot, Hub shows nothing | Keep the locked write-on-send contract (recommended) | |
| Always write the snapshot, send is separate | Layer 0 always writes; decouples perception from speech | ✓ |
| Snapshot yes, daily_note no | Facts always, voice line only on send | |

**User's choice:** Always write the snapshot, send is separate
**Notes:** Inverts the plan's "written only on actual send". → D-05

### Where does `daily_note` come from if no message was composed?

| Option | Description | Selected |
|--------|-------------|----------|
| Triage draft's one-liner | Reuse Layer 1's free draft (recommended) | ✓ |
| Deterministic line from the snapshot | Template-composed, no LLM | |
| Leave it empty on a skip | Note stays tied to something actually said | |

**User's choice:** Triage draft's one-liner → D-06

### What should legitimately earn a skip? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| A standing directive says so | Phase 31 Step-0 veto | ✓ |
| Already covered it recently | Tick or earlier occasion said the substantive thing | ✓ |
| Genuinely nothing happened | Empty day, empty tomorrow | ✓ |
| Reaction history says back off | Consistent ignoring/pushback from the reflection loop | ✓ |

**User's choice:** All four → D-02

### On a judgment-skipped nightly, does the journal still get written?

| Option | Description | Selected |
|--------|-------------|----------|
| Always — journal is not the message | Continuity/self-state are internal machinery (recommended) | ✓ |
| Only when he speaks | Journal tied to an actual send | |
| Always, but cheaper on a skip | Free path (tick-brain) when silent | |

**User's choice:** Always — journal is not the message → D-07

### Weekly review skips a Sunday — what happens to that week?

| Option | Description | Selected |
|--------|-------------|----------|
| Gone — next week covers a wider window | No catch-up machinery (recommended) | |
| Never skip the weekly | Periodic report; a missing week leaves a hole | ✓ |
| Skip, but leave a marker | Write the scorecard data without narrating | |

**User's choice:** Never skip the weekly → D-03

### "Never skip the weekly" vs Phase 31's directive veto

| Option | Description | Selected |
|--------|-------------|----------|
| Directive still wins | Judgment can't skip it; an explicit standing order can (recommended) | ✓ |
| Weekly is unvetoable | Fires no matter what | |

**User's choice:** Directive still wins → D-03

### If the weekly always speaks, what is its triage judgment for?

| Option | Description | Selected |
|--------|-------------|----------|
| Shape and emphasis | What the week is about, which topics lead (recommended) | ✓ |
| Length and depth | Same topics, variable weight | |
| Both | | |

**User's choice:** Shape and emphasis → D-03

### Does the 01:00 backstop get fresh judgment?

| Option | Description | Selected |
|--------|-------------|----------|
| Fresh judgment, skip-aware | Full cascade; `skipped_by_judgment` terminal (recommended) | ✓ (via deferral) |
| Backstop always sends | Safety net, not a judgment surface | |
| Fresh judgment, higher bar | Message must earn the late hour | |

**User's choice:** Deferred to Claude — *"I won't see the message anyway until the morning… whatever you think is best."*
**Notes:** His rationale eliminated the "higher bar" option outright: the hour is irrelevant because the message is read in the morning either way. → D-04

### Does the Garmin wake-up anchor stay a hard gate?

| Option | Description | Selected |
|--------|-------------|----------|
| Hard gate stays | Locked by OCC-02 (recommended) | |
| Anchor becomes a judgment input | Other awake signals can also fire the occasion | ✓ |

**User's choice:** Anchor becomes a judgment input
**Notes:** Flagged as an override of OCC-02 before proceeding. Superseded later the same session by the push trigger. → D-08/D-09

### Which other signals count as evidence of being awake? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| You messaged Klaus | Chat/Hub activity | ✓ |
| A calendar event already started | | ✓ |
| Hub was opened | | ✓ |
| Nothing else — Garmin only, just softer | | |

**User's choice:** All three activity signals
**Notes:** Superseded by the push trigger — no polling signals needed.

### Does the 10:15 cutoff stay hard?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — hard cutoff stays | Contains the change (recommended) | |
| Soften it too | Let judgment decide past 10:15 | ✓ |

**User's choice:** Soften it too
**Notes:** Prompted the Cloud Scheduler constraint disclosure (cron is `*/10 6-10`, last tick ~10:50; beyond that needs a scheduler change OCC-06 rules out).

### How far should the morning occasion be allowed to run?

| Option | Description | Selected |
|--------|-------------|----------|
| To the cron's natural end (~10:50) | Zero infra cost (recommended) | |
| Extend the cron window too | Breaks OCC-06 | |
| Hand off to the tick after ~10:50 | | |

**User's choice:** Free-text counter-proposal — *"make a change to the infrastructure so that the tick brain handles the wake-up instead of the Google scheduler… starts at 7:00 and looks for a Garmin sync… until 12:00… if he already found it beforehand he should stop looking. What do you think?"*
**Notes:** Assessed honestly: right thesis, four flags raised (resolution drop `*/10`→`*/20`, 06:00→07:00 early-wake regression, collision with the OCC-06 A/B window, minor polling cost). Recommended Phase 35.

### Where should the tick-owns-wake-up change land?

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 35, after the observation window | Keeps the A/B safety net (recommended) | |
| Phase 33, now | Cleaner end state, loses the fallback | |
| Phase 33, but keep both crons | Two detectors racing | |

**User's choice:** Free-text — *"Let's do it now, but make it more sophisticated… via my phone's sleep alarm… when my alarm goes off, or I turn off sleep mode when I wake up."*
**Notes:** This is the mirror of the existing Sleep-Focus-on → `/trigger/nightly` automation. Push, not poll — kills both the resolution-loss and early-wake flags. Accepted. → D-08

### Backstop when `/trigger/morning` doesn't fire?

| Option | Description | Selected |
|--------|-------------|----------|
| Tick polls Garmin until ~12:00 | His original idea, demoted to backstop (recommended) | |
| Keep morning-briefing-tick as the backstop | | |
| No backstop — trigger or nothing | | ✓ |

**User's choice:** No backstop — *"If I forgot, then I just probably don't need the morning briefing because 99% of days I have that sleep focus in my routine."* → D-09

### Fire immediately, or wait?

| Option | Description | Selected |
|--------|-------------|----------|
| Immediately | Zero latency, the point of the push trigger (recommended) | ✓ |
| Short delay (~10-15 min) | Lets Garmin data land | |
| Immediately, but judgment can defer | | |

**User's choice:** Immediately → D-11

### Sleep Focus off at 03:40 — time floor?

| Option | Description | Selected |
|--------|-------------|----------|
| Time floor — nothing before ~05:00 | (recommended) | |
| No floor — trust the signal | | ✓ |
| Let judgment decide | | |

**User's choice:** No floor — trust the signal → D-09

### Dedup for repeated trigger hits?

| Option | Description | Selected |
|--------|-------------|----------|
| Daily state doc, same as nightly | One proven pattern both directions (recommended) | ✓ |
| Daily state doc + short cooldown | | |

**User's choice:** Daily state doc, same as nightly → D-12

### Own token or reuse `NIGHTLY_TRIGGER_TOKEN`?

| Option | Description | Selected |
|--------|-------------|----------|
| Own token (MORNING_TRIGGER_TOKEN) | Matches documented least-privilege rationale (recommended) | ✓ |
| Reuse NIGHTLY_TRIGGER_TOKEN | | |
| Rename to a shared TRIGGER_TOKEN | | |

**User's choice:** Own token → D-13

### What does a manual "brief me" ask do?

| Option | Description | Selected |
|--------|-------------|----------|
| Runs the occasion, ignores state | Marks state `manual` (recommended) | ✓ |
| Just answers in chat, no occasion | | |
| Runs the occasion, respects dedup | | |

**User's choice:** Runs the occasion, ignores state → D-14

### Garmin sleep data may not have synced when Sleep Focus turns off

| Option | Description | Selected |
|--------|-------------|----------|
| Brief without it, mention the gap | Matches the Tier A/B no-fabrication contract (recommended) | ✓ |
| One short retry before composing | | |
| Let triage decide | | |

**User's choice:** Brief without it, mention the gap → D-11

### Night with no wind-down — does the morning cover the gap?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — morning widens its window | Push triggers can both miss (recommended) | ✓ |
| No — each occasion owns its own window | | |
| The 01:00 backstop already covers it | | |

**User's choice:** Yes — morning widens its window → D-15

---

## Occasion ↔ tick collision

### Tick messaged at 22:40; nightly fires at 23:10. What should the nightly do?

| Option | Description | Selected |
|--------|-------------|----------|
| Fold — knows what was said, doesn't repeat | Composes around it (recommended) | ✓ |
| Skip if the tick covered the substance | | |
| Fire independently | | |

**User's choice:** Fold → D-16

### Should an occasion suppress later ticks?

| Option | Description | Selected |
|--------|-------------|----------|
| Existing topic dedup handles it | Occasion keys land in the same OutreachLog (recommended) | ✓ |
| Explicit quiet window after an occasion | | |
| No suppression — different jobs | | |

**User's choice:** Existing topic dedup handles it → D-18

### Sunday: morning at ~07:30 and weekly at 10:00

| Option | Description | Selected |
|--------|-------------|----------|
| Morning defers training to the weekly | Two messages, no overlap (recommended) | ✓ |
| Fold the weekly into Sunday's morning | | |
| Keep them fully independent | | |

**User's choice:** Morning defers training to the weekly → D-20

### Shared dedup namespace?

| Option | Description | Selected |
|--------|-------------|----------|
| Shared — one log, one namespace | Occasions and ticks as peers (recommended) | ✓ |
| Shared log, but occasions outrank ticks | | |

**User's choice:** Shared — one log, one namespace → D-18

### What does "fold" concretely mean?

| Option | Description | Selected |
|--------|-------------|----------|
| Full message text of today's outreach | Enables natural back-reference (recommended) | ✓ |
| Topic keys + triage reasons only | Cheaper, no back-reference | |
| Message text at triage too | Best judgment, but Layer 1 is on the Groq budget | |

**User's choice:** Full message text of today's outreach
**Notes:** Layer 2 only — Layer 1 stays on topic keys to protect the Groq per-request budget. → D-17

### Same-minute tick/occasion race

| Option | Description | Selected |
|--------|-------------|----------|
| Occasion wins, tick yields | Needs an in-flight marker (recommended) | ✓ |
| Accept it — rare and self-correcting | | |
| Occasion absorbs the tick's signals | | |

**User's choice:** Occasion wins, tick yields → D-19

---

## Agentic Layer 2 powers

### Per-compose tool-call budget

| Option | Description | Selected |
|--------|-------------|----------|
| Tight (~3-5 calls) | Predictable cost/latency (recommended) | |
| Generous (~8-10 calls) | | |
| Different per occasion | | |

**User's choice:** Free-text — *"I don't want a specific budget. I want him to be able to think and look through stuff if he wants to, just be smart and sophisticated about it."*
**Notes:** Resolved by finding the existing `MAX_TOOL_ITERATIONS = 12` in `core/main.py:50` — the same loop Layer 2 already uses. "No budget" = keep the existing runaway guard, add no tighter cap. Satisfies OCC-05's "bounded" wording. Also surfaced stale docs: `core/self_manifest.py:590` still says 8. → D-21

### Budget exhausted mid-compose

| Option | Description | Selected |
|--------|-------------|----------|
| Force a final answer with what he has | (recommended) | ✓ (via deferral) |
| Fall back to the triage draft | | |
| Send what he has, and say so | | |

**User's choice:** Deferred to Claude — *"whatever you think is best."*
**Notes:** Chose force-a-final-answer with tools stripped; D-19's draft fallback only if that also fails. Never truncate mid-thought; never downgrade to the free draft as a penalty for thoroughness. → D-22

### Can Layer 2 write?

| Option | Description | Selected |
|--------|-------------|----------|
| Directive-gated writes | What the milestone plan assumes (recommended) | |
| Writes allowed, always disclosed | Acts without prior permission, declares after | ✓ |
| Read-only — always propose | | |

**User's choice:** Writes allowed, always disclosed
**Notes:** Overrides OCC-05's "directive-gated". Two invariants explicitly preserved: the B2 idempotency check before any calendar create (correctness, not permission) and the Phase 31 directive veto. → D-23

### Which tools should an unattended compose reach for? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Same set as a chat turn | | ✓ |
| Reads yes, writes gated | | |
| Exclude the slow ones | | |

**User's choice:** Same set as a chat turn — *"he should be able to read and write without my consent but just declare after writing if he does so."* → D-23

### Destructive actions (move/delete)?

| Option | Description | Selected |
|--------|-------------|----------|
| Creates yes, destructive asks | Creates are recoverable (recommended) | |
| Everything, always disclosed | Full symmetry | ✓ |
| Creates yes, destructive only on cleanup | | |

**User's choice:** Everything, always disclosed → D-23

### How should the disclosure read?

| Option | Description | Selected |
|--------|-------------|----------|
| Woven in, one clause | Matches no-mandated-sections (recommended) | |
| Explicit action line | Always scannable | ✓ |
| Klaus decides | | |

**User's choice:** Explicit action line → D-24

### Write succeeds, send fails — action taken, never disclosed

| Option | Description | Selected |
|--------|-------------|----------|
| Record actions separately from sends | Own audit record, decoupled from D-10 (recommended) | ✓ |
| Idempotency check is enough | | |
| Compose reads, sends, then writes | | |

**User's choice:** Record actions separately from sends → D-25

### Where should actions be auditable from?

| Option | Description | Selected |
|--------|-------------|----------|
| Same store `get_recent_decisions` reads | One tool, one place (recommended) | ✓ |
| TickLog trail only | | |
| Both — trail plus a queryable action log | | |

**User's choice:** Same store `get_recent_decisions` reads → D-25/D-26

---

## Explaining silence

### What should `get_recent_decisions` return? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Verdict + reasoning per run | | ✓ |
| What he sent, and when | | ✓ |
| Actions taken | | ✓ |
| Skip causes, categorized | | ✓ |

**User's choice:** All four → D-26

### Default window

| Option | Description | Selected |
|--------|-------------|----------|
| 2 days default, callable further | Matches the review amendment (recommended) | ✓ |
| 7 days default | | |
| Since last conversation | | |

**User's choice:** 2 days default, callable further → D-26

### Does a skip ever surface unasked?

| Option | Description | Selected |
|--------|-------------|----------|
| Only surfaces when asked | Silence stays silent (recommended) | ✓ |
| Undisclosed actions surface next message | | |
| Weekly pattern surfaces in the Sunday review | | |

**User's choice:** Only surfaces when asked
**Notes:** Undisclosed *actions* remain the exception via D-25. → D-27

### How to watch the cascade during rollout?

| Option | Description | Selected |
|--------|-------------|----------|
| Ask Klaus — that's the tool's other job | (recommended) | |
| Ask Klaus + a heartbeat summary | Anomalies surfaced without having to remember to check | ✓ |
| Firestore + logs directly | | |

**User's choice:** Ask Klaus + a heartbeat summary → D-28

### What should the heartbeat flag as anomalous? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Any occasion that errored out | Failure-skip class, SC-1 | ✓ |
| A skip streak | Could be quiet week or prompt regression | ✓ |
| The weekly not firing | By D-03 it never self-skips | ✓ |
| Undisclosed actions pending | Orphaned D-25 write | ✓ |

**User's choice:** All four → D-28

### Go/no-go for Phase 35 deletion

| Option | Description | Selected |
|--------|-------------|----------|
| Your judgment from the daily asks | Taste question, no metric answers it (recommended) | ✓ |
| Zero failure-class errors + your judgment | | |
| A fixed checklist in DEPLOYMENT.md | | |

**User's choice:** Your judgment from the daily asks → D-29

---

## Rollout A/B gap

### Morning can't be A/B'd against a retired trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Ship morning cascade-only, A/B the other two | (recommended) | ✓ |
| Keep morning-briefing-tick alive through the window | | |
| Split it — trigger now, cascade later | | |

**User's choice:** Ship morning cascade-only → D-30

### Sequencing around the iOS Shortcut Amit must build

| Option | Description | Selected |
|--------|-------------|----------|
| Route ships dark, you build, then it's live | No silent-morning gap (recommended) | ✓ |
| Cut over on deploy day | | |
| Klaus tells you if it never fires | | |

**User's choice:** Route ships dark → D-31

---

## BackgroundTask vs agentic compose

### How should the trigger routes run an agentic compose?

| Option | Description | Selected |
|--------|-------------|----------|
| Route both triggers through Cloud Tasks | Fixes an existing latent bug (recommended) | ✓ |
| Cloud Tasks for morning, leave nightly alone | | |
| Keep BackgroundTasks, cap the tools | Contradicts the no-budget decision | |

**User's choice:** Route both triggers through Cloud Tasks → D-32

### Same treatment for the `/cron/*` occasions?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — one dispatch path for all occasions | (recommended) | ✓ |
| Crons are fine as-is | Technically correct — holding the request open keeps CPU | |

**User's choice:** Yes — one dispatch path
**Notes:** Recorded honestly in CONTEXT.md: the crons are not broken today; this buys consistency and timeout headroom. The trigger routes are the actual defect. → D-32

---

## Saving what the templates got right

### Where should the legacy composers' substance live?

| Option | Description | Selected |
|--------|-------------|----------|
| In the data, not the prompt | Signals + tools already carry it (recommended) | ✓ |
| As available-blocks hints in the occasion prompts | | |
| Fold into the coaching guide | | |

**User's choice:** In the data, not the prompt → D-33

### How to catch silent content regression?

| Option | Description | Selected |
|--------|-------------|----------|
| You'll notice and tell him | Becomes a standing directive (recommended) | ✓ |
| Eval fixtures cover it | | |
| Compare old vs new during the window | | |

**User's choice:** You'll notice and tell him → D-34

---

## What the occasion prompts say

### What's left in the three occasion prompts?

| Option | Description | Selected |
|--------|-------------|----------|
| Occasion identity + its standing question | (recommended) | ✓ |
| Identity + the occasion's specific latitude | | |
| Merge into one occasion prompt | | |

**User's choice:** Occasion identity + standing question → D-35

### Where do cross-cutting behaviors land?

| Option | Description | Selected |
|--------|-------------|----------|
| The shared cascade prompts | Tick gets the same improvements (recommended) | ✓ |
| smart_agent.md, so chat shares them too | Grows the always-on prompt 30.5 just slimmed | |
| Split by nature | | |

**User's choice:** The shared cascade prompts → D-36

---

## Claude's Discretion

- 01:00 backstop judgment behavior (D-04) — deferred with reasoning that ruled out one option
- Tool-exhaustion behavior (D-22) — "whatever you think is best"
- Action-audit record shape and its merge into `get_recent_decisions` (D-25/D-26)
- In-flight marker mechanism for the occasion-wins race (D-19)
- Concrete wording of all occasion prompts and shared-prompt additions (D-35/D-36)
- How skip-causes #2 and #4 are surfaced to Layer 1 within the Groq budget
- Skip-streak threshold N for the heartbeat anomaly (D-28)
- Whether retired morning state-machine fields are deleted or left dormant
- Internal endpoint naming for the Cloud Tasks occasion dispatch (D-32)
- How the widened morning window detects a missed nightly (D-15)

## Deferred Ideas

- Legacy composer + retired prompt + flag deletion → Phase 35 (OCC-06)
- Calendar/chat write-backs to `TrainingLogStore` → Phase 34
- New occasion eval fixtures → Phase 35 / HARD-01
- Wake-up detection as a `*/20` tick Layer-0 signal → superseded by the push trigger; recorded so it isn't re-proposed
- A Hub surface for browsing Klaus's decisions/actions → not in scope

## Requirement Overrides Recorded

Three user decisions supersede locked requirement text. All are flagged **[OVERRIDE]** in CONTEXT.md:

1. **OCC-02 / SC-2** "Garmin wake-up anchor and 10:15 cutoff kept" → replaced by the Sleep-Focus-off push trigger (D-08/D-09)
2. **OCC-05** "directive-gated proactive calendar writes" → replaced by ungated writes with mandatory disclosure (D-23)
3. **OCC-06** "no Cloud Scheduler changes" + "both live for a 3-4 day window" → one scheduler exception (`morning-briefing-tick` retired) and morning ships cascade-only (D-10/D-30)
