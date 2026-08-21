# User Profile & Core Context

Everything Klaus should already know about Amit, in one place.

This file is **served to Klaus on every turn** in the `profile` block of
`get_life_snapshot`, and section-by-section through `read_user_profile`. It is
the single source of these facts: they must not be restated inside individual
skills, because a fact written into one skill is a fact the other three do not
have.

What belongs here: durable facts about Amit and the shape of his life. What does
not: instructions about how Klaus should behave (that is `docs/AGENT.md`), how
Klaus should coach (`docs/COACHING_GUIDE.md`), or anything that changes daily —
live state comes from the rest of the snapshot.

<!-- SECTION: identity -->
## Identity

- **Location:** Tel Aviv, Israel. Timezone `Asia/Jerusalem`, and all times in
  Klaus's world are local unless stated otherwise.
- **Life stage:** Pre-military window, after finishing high school. Weekday
  obligations are light, which means his time is mostly self-directed — the
  constraint on his days is his own planning, not an external schedule.
- **Work:** Part-time at "Studio", a restaurant. See `rhythms` for shift shapes.
- **Character:** Ambitious and driven, builds technical projects for their own
  sake, highly social with a close group of friends. Prone to occasional
  procrastination on the things he says matter most — see `working-style`.
- **Language:** Klaus always replies in English, even when Amit writes in
  Hebrew, unless Amit asks otherwise.
- **Money:** Reported in ILS (₪). Foreign holdings are converted at the current
  `USD_ILS` rate, and an estimated cost basis is always labelled as estimated.

<!-- SECTION: goals -->
## Goals

Three dated events, and the targets that matter for each. These are the whole
list — if something is not here, it is not a goal he is training for.

| When | Event | Target |
|---|---|---|
| **2026-10-09** | 5K race | Sub-**17:30** (3:30/km) |
| **2026-10-28** | 15K race | No pace target he cares about; expects to come in under **4:00/km** (sub-1:00:00) |
| **November 2026**, exact date not yet known | Testing session at practice — 3K, pull-ups, push-ups, 400m | 3K sub-**9:45** (3:15/km) · **26+** pull-ups · **85+** push-ups · 400m sub-**56s** |

**Barbell numbers are explicitly not goals.** Bench press and squat targets were
part of an earlier blueprint and Amit has said plainly he does not care about
them. Do not coach toward them, do not treat a missing bench log as a gap, and
do not reintroduce them as proxies for strength progress. Pull-ups and push-ups
are the strength that counts, because they are on the November test.

**He schedules his own training, and he knows how to train.** He decides what to
do and when based on how the day looks. There is no prescribed weekly template
and no fixed AM/PM split — see `rhythms`, and read the calendar for what is
actually planned.

In his own words, what he wants from Klaus is "someone to keep me accountable,
sort of." Not a programme, not tracking, not benchmark reminders — he tests
himself when he means to. The value is noticing: a goal getting close, a pattern
he has not clocked, a plan that does not physically fit. See `docs/AGENT.md` for
how to act on that.

<!-- SECTION: rhythms -->
## Rhythms

**The training week lives in the calendar and the training plan, not in this
file.** Read it. Do not assume a fixed weekly template and do not hardcode
session times — recurring fixtures (practice, long runs) appear as real calendar
events and planned sessions, and that is the authority on when they happen. If a
fixture is not in the calendar, it is not scheduled, and saying so is more
useful than inferring it from habit.

**He plans tomorrow every night.** He will do this whether or not Klaus helps,
so the nightly review should arrive with a finished draft he edits rather than a
proposal he has to author or approve.

**Studio shifts** come in four shapes. Each has a fixed travel and eating
buffer, because he eats at the restaurant before travelling home:

| Shift | Starts | Ends | Home by |
|---|---|---|---|
| Opening | 11:00 | 16:30 | 17:00 |
| Late morning | 11:30 | 17:00 | 17:30 |
| Early evening (early release) | 17:00 | 22:30 | 23:00 |
| Standard evening | 17:00 or 18:00 | 23:00 | 23:30 |

- **Pre-shift:** 15-minute travel buffer immediately before the start.
- **Post-shift:** 30-minute combined eating and travel buffer immediately after.

Note that he says "11:00" for 23:00 in spoken 12-hour form; read it from
context.

<!-- SECTION: footprints -->
## Footprints

Real durations, for checking whether a plan physically fits. Most bad plans are
not bad priorities — they are plans that never fit in the first place.

- **A gym session costs about 3h15m door to door:** ~1h15m training, 45m to eat
  and shower, 15m travel each way, 45m to get ready beforehand. Not 75 minutes.
- **Any scheduled event** carries a 15-minute travel block before and after
  unless stated otherwise — 30 minutes of buffer in total.
- **Studio shifts** carry the buffers in `rhythms`: 15m before, 30m after.

<!-- SECTION: working-style -->
## Working style

**His task list is a capture bucket, not a task list.** Most items have no date,
no project and no tag, and they sit for months — the median age reached roughly
four months. The blocking step is never writing something down; it is deciding
where it goes. Klaus should make that decision for him rather than asking, file
new to-dos into a real project or area instead of leaving them in the Inbox, and
treat a wrong guess as cheap (it costs one drag to fix) against a missing to-do,
which costs everything.

**He sets almost no deadlines.** Deadline-pressure checks will therefore usually
come back empty. That is the true answer, not a gap to fill.

**He procrastinates on the things he says matter most** — usually his own
projects, rarely his obligations to other people. The drift is almost never
about priorities; it is about not having decided the first concrete step.

**A day scheduled to the edges fails on first contact with reality.** He
consistently underestimates how much of a day a small number of commitments
actually consumes — see `footprints` for the real numbers.

How Klaus should *respond* to any of this is in `docs/AGENT.md`; this section
only records what is true.

<!-- SECTION: scheduling-rules -->
## Scheduling rules

These are deterministic and implemented in the calendar tool, not left to
judgement. They are recorded here so Klaus can explain and reason about them.

**Standard buffers.** Every scheduled event gets a 15-minute travel block
immediately before it and a 15-minute return block immediately after.

**What counts as a training block.** Any event living in the dedicated
**Training** calendar — excluding its own automatic "Get Ready" and "Travel"
buffer blocks. It is not keyword matching: when Klaus is asked to create an
event, Klaus judges whether it is a workout, and if so routes it to the Training
calendar with the buffers below. Typical workouts: running, biking, basketball,
gym, Five Fingers practice.

**Training block timeline.**

| Offset | Block |
|---|---|
| T-60 min | "Get Ready" begins |
| T-15 min | "Travel" begins |
| T-0 | the session itself begins |

"Get Ready" blocks never generate buffers of their own — they are already
buffers, and treating them as events caused an infinite recursion once.
