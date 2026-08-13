# Things Cloud protocol — reverse-engineered reference

**Status:** derived empirically on 2026-08-11 by replaying Amit's real journal
(321 elements → 487 entities) with `scripts/spike_things_protocol.py`.
Cross-checked against [disrupted/things-cloud-api](https://github.com/disrupted/things-cloud-api).

Cultured Code publishes **no** API and no schema documentation. Everything below was
observed, not documented. It can break on any Things release. Treat this file as the
source of truth for Klaus's integration and re-run the spike whenever behaviour
looks wrong.

---

## 1. Endpoints

Base: `https://cloud.culturedcode.com/version/1`

### Login — get the history key

```http
GET /version/1/account/{url-encoded-email}
Authorization: Password {url-quoted password, safe="'"}
```

```json
{ "status": "SYAccountStatusActive", "history-key": "<uuid>",
  "email": "...", "SLA-version-accepted": 7, "issues": [] }
```

`history-key` is the handle for every subsequent call. **Treat it as a credential.**

> `maildrop-email` (the Mail to Things address) is documented by the community as
> part of this response, but came back **empty** for this account — Mail to Things is
> not enabled. It must be turned on in Things → Settings → Things Cloud before that
> field is populated. Not required for this integration.

> `POST /api/account/login/getT3SharedSession` (`Authorization: B64SON <base64>`)
> returns **404** — that endpoint is dead. Do not use it. `headIndex` is not needed;
> the journal's own `current-item-index` serves as the cursor.

### Read — the journal

```http
GET /version/1/history/{history-key}/items?start-index={N}
```

```json
{ "items": [ … ], "current-item-index": 340, "schema": 301,
  "start-total-content-size": …, "end-total-content-size": …,
  "latest-total-content-size": … }
```

The list key is **`items`**, not `updates`.

### ⚠️ Pagination — `current-item-index` is the HEAD, not the end of the page

Each response is **capped** (321 elements in this account); `current-item-index`
always reports the journal head regardless of how much was returned. Elements map
1:1 to indices, so:

```
next_cursor = start_index + len(items)        ✅
next_cursor = current-item-index              ❌ skips the gap, silently
```

Measured on the live account at head 340:

| `start-index` | elements returned |
|---|---|
| 0 | 321 |
| 321 | 19 |
| 338 | 2 |
| 340 | 0 |

Using the head as the cursor jumps 0 → 340 and drops indices 321–339 with no error.
This masqueraded as a *sync* problem — a to-do added on the Mac appeared to never
reach the cloud — and it stayed hidden while the journal fit in one page. Drained
when `cursor >= head` or a page returns no items.

`things_tool.replay_journal()` encapsulates this; prefer it over hand-rolling the
loop.

### Write — commit

```http
POST /version/1/history/{history-key}/commit?ancestor-index={N}&_cnt=1
```

Returns a new server head index. **Not yet exercised** — Step 1 territory.

### Required headers

```
Accept: application/json          Schema: 301
Accept-Charset: UTF-8             App-Id: com.culturedcode.ThingsMac
Accept-Language: en-gb            App-Instance-Id: -com.culturedcode.ThingsMac
Content-Type: application/json; charset=UTF-8
Push-Priority: 5                  User-Agent: ThingsMac/… (any plausible value)
```

---

## 2. Journal element shape

Each element of `items` maps **one or more** UUIDs to a record. One element batched
up to 90 entities in this account — flattening is nested, not a simple map.

```json
{ "22ouPegdQwze3xKpxxLqP5": { "t": 0, "e": "Task6", "p": { …payload… } } }
```

| Key | Meaning |
|---|---|
| `t` | **operation code** — see below |
| `e` | entity class |
| `p` | payload |

### Operation codes (`t`) — the single most important detail here

| Code | Meaning | Payload |
|---|---|---|
| `0` | create | complete |
| `1` | edit | **sparse delta** — merge over accumulated state |
| `2` | **delete** | ignore; drop the UUID |

**Materializing = replay in order; merge `p` on 0/1, `pop` the UUID on 2.**

> ⚠️ Getting this wrong is silent and catastrophic. The first spike run treated
> `t=2` as a merge and reported **251 open to-dos when the account has 52** —
> resurrecting deleted projects and areas from months earlier. Nothing errors; you
> just get confidently wrong data. 232 of this account's 1,002 journal records are
> deletes.

`Tombstone2` entities are a **second, independent** delete signal — `dloid` names
the doomed UUID. Apply both.

### Entity classes observed

Journal records (all ops) → live entities after deletes:

| Class | Records | Live | Role |
|---|---|---|---|
| `Task6` | 929 | 200 | to-dos, projects, headings (discriminated by `tp`) |
| `ChecklistItem3` | 32 | 22 | checklist rows inside a to-do |
| `Tombstone2` | 25 | 25 | deletions — `dloid` = deleted id, `dld` = timestamp |
| `Tag4` | 7 | 7 | tags — `tt` name, `pn` parent tag |
| `Area3` | 8 | 0 | areas — `tt` name (all 4 were later deleted) |
| `Settings5` | 1 | 1 | account settings singleton |

---

## 3. `Task6` payload

### Enums — confirmed by cross-tabulation against real data

Counts below are over the 200 **live** `Task6` entities (post-delete).

| Field | Values | Meaning |
|---|---|---|
| `tp` | `0` / `1` / `2` | **type**: to-do / project / heading |
| `ss` | `0` / `2` / `3` | **status**: open / canceled / completed |
| `st` | `0` / `1` / `2` | **bucket**: Inbox / Anytime / Someday |
| `tr` | bool | **trashed** |

Two independent confirmations of the `ss` mapping: `sp` (completion timestamp) is set
on **exactly** the rows where `ss != 0` and null on every `ss == 0` row; and filtering
`ss == 0 and not tr and tp == 0` reproduces the app's bucket counts exactly
(12 Inbox / 38 Anytime / 2 Someday). `st = 0` (Inbox) never carries a scheduled date.

### Dates

Two distinct encodings, do not mix them:

- **Day fields** — `sr`, `dd`, `tir`, `icsd` — integer epoch seconds at **UTC
  midnight**. Decode with `datetime.fromtimestamp(v, UTC).date()`.
- **Timestamp fields** — `cd`, `md`, `sp`, `lai` — float epoch seconds, sub-second
  precision.

### Field reference

| Key | Type | Meaning | Klaus mapping |
|---|---|---|---|
| `tt` | str | title | `title` |
| `nt` | dict | notes — see the checksum warning below | `notes` (read `.v`) |
| `sr` | day\|null | **scheduled date** ("when") | `due_date` |
| `dd` | day\|null | **deadline** (hard due) | `hard_deadline_at` |
| `ato` | int\|null | reminder, seconds after midnight (`36000` = 10:00) | `due_time` |
| `ss` | enum | status | `status` |
| `st` | enum | Inbox / Anytime / Someday | — |
| `tp` | enum | to-do / project / heading | — |
| `tr` | bool | trashed | soft-delete target |
| `tg` | [uuid] | tags → `Tag4` | *(new capability)* |
| `pr` | [uuid] | parent project → `Task6` with `tp=1` | `list_id` |
| `ar` | [uuid] | parent area → `Area3` | `list_id` |
| `agr` | [uuid] | ancestor group (heading/project containment) | — |
| `rr` | dict\|null | recurrence rule — **present ⇒ this row is the template** | `recurrence` |
| `rt` | [uuid] | link back to template — **non-empty ⇒ spawned instance** | — |
| `icsd` | day\|null | next-instance creation date (templates only) | — |
| `cd` `md` | ts | created / modified | `created_at` / `updated_at` |
| `sp` | ts\|null | completion timestamp | — |
| `ix` `ti` | int | sort order (negative ints) | — |
| `icc` | int | checklist item count | — |
| `lai` | ts\|null | last alarm/interaction | — |
| `lt` | bool | unknown; only ever seen on completed, scheduled rows | — |
| `xx` | dict | opaque envelope `{"sn":{},"_t":"oo"}` | echo unchanged |

**Constant across all 423 rows** — echo back unchanged on write, never synthesize:
`do=0`, `sb=0`, `dl=[]`, `dds=null`, `rmd=null`, `acrd=null`, `rp=null`, `icp=false`.

### ☠️ Notes: `ch` must be the CRC32 of the text — a wrong value crashes the app

```json
"nt": {"_t": "tx", "v": "<note text>", "ch": <crc32 of v as utf-8>, "t": 1}
```

Verified against **all 64** non-empty notes in the live account, and consistent
with the 142 empty ones (`ch = 0`, and `crc32(b"") == 0`).

**This is the single most dangerous field in the protocol.** Writing a note whose
checksum does not match its text is accepted by the server without error. The
damage lands later: every Things client that replays that record **crashes on
launch**, on every device, with an assertion failure (`EXC_BREAKPOINT`, `brk 1`)
inside `LegacySCHistoryPerformSync`. The user cannot open the app to fix it.

Because the journal is append-only the record cannot be edited away — recovery is
to append a delete (`{"t": 2, "e": "Task6", "p": {}}`) for the poisoned UUID and
hope clients fold the batch before validating. That worked here, but it is luck,
not a guarantee. The fallback is Cultured Code support resetting the history.

The trap is that a placeholder `ch = 0` looks completely fine in testing: it is
genuinely correct for an empty note, so reads round-trip and nothing complains.
It only detonates the first time real text is attached.

*(2026-08-13: this took down Amit's Mac and iPhone simultaneously.)*

### Recurrence

A repeating to-do is **two** rows:

- the **template**: `rr` set, `icsd` = next spawn date
- each **instance**: `rt=[template-uuid]`, its own `sr`, its own `ss`

Observed `rr` shape:

```json
{"rrv": 4, "tp": 0, "ts": 0, "fu": 16, "rc": 0, "fa": 1,
 "of": [{"dy": 0}], "ia": 1777334400, "sr": 1777334400, "ed": 1777680000}
```

`ia`/`sr`/`ed` are day-encoded (start / anchor / end). The rest are unmapped.

**Klaus must not write `rr` and must not spawn instances.** Things generates the next
instance itself. `complete()` marks the instance done and returns `next_id: None`; the
new instance surfaces on the following delta pull. Klaus's own recurrence engine
(`_advance_once` / `_next_due_date`, `memory/firestore_db.py:3425-3467`) stays inert
for Things-backed tasks.

---

## 4. Consequences for Klaus

- **Things has no priority field.** Confirmed — no candidate key exists. `priority`
  stays Klaus-side in the `task_meta/{uuid}` sidecar, as do `estimated_minutes`,
  `auto_schedule`, `manual_lock`, and `calendar_event_id`.
- **`sr` vs `dd` is a real split** that Klaus's single `due_date` flattens. Map
  `due_date`→`sr` and `hard_deadline_at`→`dd`. Rescheduling must move `sr` only.
- **Tags and areas are new capabilities** Klaus's task model has no field for. Read
  them into the mirror now; surface them when the Hub UI is redesigned.
- **Tombstones are the delete signal** — a `Tombstone2` with `dloid` pointing at a
  UUID means that entity is gone. The mirror must honour them.
- **`tir` tracks `sr`** (63/65 agreement). Echo it alongside `sr` on write.

### Containment is load-bearing, in two directions

A to-do cannot be judged in isolation. Both rules below were learned by finding
Klaus's read disagreeing with the running app:

1. **Project membership resolves three ways.** `pr` is a direct link; `agr` points at
   a **heading** whose own `pr` names the project; neither means loose in Inbox or
   Someday. In the live account only 2 of 52 to-dos used `pr` — 36 reached their
   project through a heading. Checking `pr` alone mislabels most of the list.

2. **Trashing a project does not set `tr` on its children.** They vanish with the
   parent, carrying `tr = False` forever. A per-task filter therefore keeps
   surfacing tasks the user threw away.

So the open-task query is **not** a flat predicate:

```python
tp == 0 and ss == 0 and not tr and not any_ancestor_trashed
```

`things_tool.live_todos(state)` implements both rules; prefer it over hand-rolling
the filter.

---

## 5. Account snapshot (2026-08-11 baseline)

Verified field-by-field against screenshots of the running Mac app.

| Metric | Cloud | App | |
|---|---|---|---|
| Open to-dos | 52 | 52 | ✅ |
| — Inbox | 12 | 12 | ✅ (all 12 titles matched) |
| — Anytime | 38 | 38 | ✅ (Klaus 2 + iPhone 18 + Mac 18) |
| — Someday | 2 | 2 | ✅ |
| Open projects | Meet Things for Mac, Meet Things for iPhone, Klaus | same 3 | ✅ |
| Areas | Shopping | Shopping | ✅ |
| Tags | Pending, Office, Important, Errand, Home, smoke, test | — | |

Baseline taken at head 339 (52 to-dos); a live write during the session moved the
head to 340 and the count to 54, which is how the pagination bug above surfaced.

**Test residue in this account.** Two canceled rows titled `[TEST] Due today task` /
`[TEST] Overdue task`, the `smoke` and `test` tags, a to-do named
`poller-debug-fixverify`, and a junk project `dfdf` containing `dfidknf` all appear
to be leftovers from the retired Phase 4 URL-scheme poller. Harmless, but they will
show up in Klaus's reads until deleted by hand.

---

## 6. Reproducing

```bash
.venv/bin/python scripts/spike_things_protocol.py --dump
```

Read-only — it never references the `/commit` endpoint. Needs `THINGS_EMAIL` and
`THINGS_PASSWORD` in `.env`. `--dump` writes the raw journal and materialized state to
the scratchpad; **never commit those** — they contain real task text.
