# Klaus Self-Monitoring Heartbeat — Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** A `/cron/heartbeat` endpoint that periodically checks Klaus's own health
(crons, tokens, degradation, deployment) and sends tiered Telegram alerts — instant
for things broken now, digested for the rest — each with a remediation hint.

**Architecture:** New `core/heartbeat.py` runs a single hourly tick. Each tick runs
Critical checks; once daily it also runs Warning checks + emits a digest; once weekly
it also runs FYI checks. Hybrid observability: an inside-out Firestore ledger
(`heartbeat_runs`, `heartbeat_metrics`) plus outside-in GCP/GitHub API calls. Incident
dedup via a Firestore `heartbeat_incidents` store. Mirrors the existing
`proactive_alerts.py` / `morning_briefing.py` cron patterns exactly.

**Tech Stack:** Python 3.11, FastAPI, Firestore, Cloud Scheduler (OIDC), Cloud
Monitoring API, Cloud Run Admin API, GitHub Actions API, python-telegram-bot, Gemini
(worker model) for message composition.

---

## Context

Klaus is a deployed Cloud Run agent with several scheduled jobs and many external
dependencies (Google + TickTick OAuth, Gemini, Pinecone, Telegram). Today, when any
of these fail it fails **silently** — a cron stops firing, an OAuth token expires,
Gemini starts 429ing and Klaus quietly degrades to the Haiku fallback. The user could
go days without noticing. The codebase also leans heavily on broad `except Exception`,
which makes tool failures invisible by design.

This feature gives Klaus self-awareness: a heartbeat that watches Klaus's own runtime,
integrations, and deployment, and proactively tells the user (via Telegram) when
something is wrong — with a diagnosis and a suggested fix.

Approved design spec: `docs/superpowers/specs/2026-05-17-heartbeat-design.md`.

## File Structure

**New files:**
- `core/heartbeat.py` — `Signal` dataclass, all checkers, composer, `run_tick`, CLI.
- `prompts/heartbeat.md` — composer system prompt.
- `tests/test_heartbeat.py` — unit tests for checkers, classification, dedup, tiers.
- `docs/superpowers/plans/2026-05-17-heartbeat.md` — copy of this plan (Task 0).

**Modified files:**
- `memory/firestore_db.py` — revive `HeartbeatConfigStore`; add `IncidentStore`,
  `record_cron_run`, `increment_fallback_counter`.
- `interfaces/web_server.py` — add `/cron/heartbeat` route; wrap all six `/cron/*`
  routes with `record_cron_run` liveness logging.
- `core/main.py` — call `increment_fallback_counter()` at the Gemini→Haiku fallback site.
- `.env.example` — add `KLAUS_GITHUB_REPO`, `KLAUS_GITHUB_TOKEN`, `HEARTBEAT_DEADMAN_URL`.
- `.github/workflows/deploy.yml` — append `KLAUS_GITHUB_REPO` env var + `KLAUS_GITHUB_TOKEN` secret.
- `requirements.txt` — add `google-cloud-monitoring`, `google-cloud-run`.

**Reuse (do not reinvent):**
- `interfaces/web_server.py:227` `_verify_cron_request` — OIDC auth for the new route.
- `core/scheduled_message.py:22` `send_and_inject` — Telegram send + conversation injection.
- `memory/firestore_db.py:24` `_make_firestore_client` — authenticated Firestore client.
- `attic/heartbeat/firestore_heartbeat_config.py:22-86` — `HeartbeatConfigStore` to revive
  (config schema updated, see Task 2).
- `attic/heartbeat/heartbeat.py:82-111` — `_in_quiet_hours` / `_parse_hm` helpers to port.
- `core/proactive_alerts.py:334-392` — patterns for `_compose_alert`/`_plain_text_fallback`;
  `core/proactive_alerts.py:399-470` — the `_cli()` `--dry-run` smoke-test pattern.

**Infra (one-time, manual — listed in Task 18):**
- Cloud Scheduler job `klaus-heartbeat` (`0 * * * *`, OIDC, SA
  `klaus-heartbeat@klaus-agent.iam.gserviceaccount.com` — already referenced in
  `deploy.yml:90` as `CLOUD_SCHEDULER_SA_EMAIL`).
- IAM on the **runtime** SA `klaus-runtime@klaus-agent.iam.gserviceaccount.com`
  (the SA the API calls execute as): `roles/monitoring.viewer`, `roles/run.viewer`.
- IAM on the scheduler SA `klaus-heartbeat@...`: `roles/run.invoker`.
- Secret Manager secret `klaus-github-token` (GitHub fine-grained read token, Actions: read).

---

## Task 0: Save this plan into the repo

**Files:**
- Create: `docs/superpowers/plans/2026-05-17-heartbeat.md`

- [ ] **Step 1:** Copy this plan file verbatim to `docs/superpowers/plans/2026-05-17-heartbeat.md`.
- [ ] **Step 2:** Commit.

```bash
git add docs/superpowers/plans/2026-05-17-heartbeat.md
git commit -m "docs: add heartbeat self-monitoring implementation plan"
```

---

# Phase 1 — Detection core (no sending)

## Task 1: `Signal` dataclass + module skeleton

**Files:**
- Create: `core/heartbeat.py`
- Test: `tests/test_heartbeat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_heartbeat.py
from __future__ import annotations
import os
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
os.environ.setdefault("GCP_PROJECT_ID", "klaus-agent")


def test_signal_fields():
    from core.heartbeat import Signal, SEVERITY_CRITICAL
    s = Signal(
        fingerprint="cron:morning-briefing:stale",
        severity=SEVERITY_CRITICAL,
        area="cron",
        title="morning-briefing did not run",
        detail="last run 30h ago",
        remediation="Check Cloud Scheduler job klaus-morning-briefing.",
    )
    assert s.fingerprint == "cron:morning-briefing:stale"
    assert s.severity == "critical"
```

- [ ] **Step 2: Run** `pytest tests/test_heartbeat.py::test_signal_fields -v` — expect FAIL (module missing).

- [ ] **Step 3: Create `core/heartbeat.py` skeleton**

```python
"""Klaus self-monitoring heartbeat.

Runs one health-check tick: inspects Klaus's own crons, integration tokens,
runtime degradation, and deployment state, then sends tiered Telegram alerts.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/heartbeat  (hourly, 0 * * * *, Asia/Jerusalem)

Local smoke test:
  python -m core.heartbeat --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_FYI = "fyi"


@dataclass
class Signal:
    """A single detected health problem.

    fingerprint: stable dedup key, e.g. "cron:morning-briefing:stale".
    severity:    SEVERITY_CRITICAL | SEVERITY_WARNING | SEVERITY_FYI.
    area:        "cron" | "token" | "degradation" | "deployment" | "code".
    title:       one-line human summary.
    detail:      specific evidence (numbers, timestamps).
    remediation: static fix hint.
    """
    fingerprint: str
    severity: str
    area: str
    title: str
    detail: str
    remediation: str
```

- [ ] **Step 4: Run** `pytest tests/test_heartbeat.py::test_signal_fields -v` — expect PASS.
- [ ] **Step 5: Commit** — `feat(heartbeat): add Signal dataclass and module skeleton`

## Task 2: Revive `HeartbeatConfigStore` with the v1 config schema

**Files:**
- Modify: `memory/firestore_db.py` (insert after `UserProfileStore`, before `_smoke_test`)

- [ ] **Step 1: Write the failing test**

```python
def test_heartbeat_config_defaults():
    from memory.firestore_db import _HEARTBEAT_CONFIG_DEFAULTS as d
    assert d["enabled"] is True
    assert d["digest_hour"] == 9
    assert d["weekly_digest_day"] == 1
    assert d["reping_interval_hours"] == 24
    assert d["quiet_start"] == "22:00"
```

- [ ] **Step 2: Run** `pytest tests/test_heartbeat.py::test_heartbeat_config_defaults -v` — expect FAIL.

- [ ] **Step 3: Add to `memory/firestore_db.py`** — copy the `HeartbeatConfigStore` class
  from `attic/heartbeat/firestore_heartbeat_config.py:22-86`, but **replace** the defaults
  dict with the v1 schema (drop `cadence_minutes`; the new tick is fixed-hourly):

```python
_HEARTBEAT_CONFIG_DEFAULTS: dict = {
    "enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "timezone": "Asia/Jerusalem",
    "digest_hour": 9,            # local hour to emit the daily Warning digest
    "weekly_digest_day": 1,      # isoweekday (1=Mon) to emit the weekly FYI digest
    "reping_interval_hours": 24, # silence window for an already-open incident
}
```

  Use the existing module-level `_make_firestore_client(project_id, database)` (line 24)
  inside `HeartbeatConfigStore.__init__` instead of the attic version's inline credential
  block, for consistency with `RosterStore` / `AttendanceStore`.

- [ ] **Step 4: Run** `pytest tests/test_heartbeat.py::test_heartbeat_config_defaults -v` — expect PASS.
- [ ] **Step 5: Commit** — `feat(heartbeat): revive HeartbeatConfigStore with v1 config schema`

## Task 3: Quiet-hours + tier-selection helpers

**Files:**
- Modify: `core/heartbeat.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime
from zoneinfo import ZoneInfo


def _dt(hour, minute, isoweekday=2):
    # 2026-05-18 is a Monday (isoweekday 1); offset to hit the requested weekday.
    day = 17 + isoweekday
    return datetime(2026, 5, day, hour, minute, tzinfo=ZoneInfo("Asia/Jerusalem"))


def test_in_quiet_hours_spans_midnight():
    from core.heartbeat import _in_quiet_hours
    cfg = {"quiet_start": "22:00", "quiet_end": "07:00", "timezone": "Asia/Jerusalem"}
    assert _in_quiet_hours(cfg, _dt(23, 30)) is True
    assert _in_quiet_hours(cfg, _dt(3, 0)) is True
    assert _in_quiet_hours(cfg, _dt(12, 0)) is False


def test_tiers_for_now():
    from core.heartbeat import (_tiers_for_now, SEVERITY_CRITICAL,
                                SEVERITY_WARNING, SEVERITY_FYI)
    cfg = {"digest_hour": 9, "weekly_digest_day": 1, "timezone": "Asia/Jerusalem"}
    assert _tiers_for_now(cfg, _dt(9, 5, isoweekday=1)) == {
        SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_FYI}
    assert _tiers_for_now(cfg, _dt(9, 5, isoweekday=2)) == {
        SEVERITY_CRITICAL, SEVERITY_WARNING}
    assert _tiers_for_now(cfg, _dt(15, 0, isoweekday=2)) == {SEVERITY_CRITICAL}
```

- [ ] **Step 2: Run** the two tests — expect FAIL.

- [ ] **Step 3: Implement in `core/heartbeat.py`** — port `_in_quiet_hours` / `_parse_hm`
  from `attic/heartbeat/heartbeat.py:82-111`, changing `_in_quiet_hours` to accept an
  explicit `now: datetime` argument instead of calling `datetime.now`. Add:

```python
def _tiers_for_now(config: dict, now: datetime) -> set[str]:
    """Return the severity tiers to check this tick.

    Critical always; Warning at the configured digest_hour; FYI additionally
    on the configured weekly_digest_day at digest_hour.
    """
    tiers = {SEVERITY_CRITICAL}
    if now.hour == int(config.get("digest_hour", 9)):
        tiers.add(SEVERITY_WARNING)
        if now.isoweekday() == int(config.get("weekly_digest_day", 1)):
            tiers.add(SEVERITY_FYI)
    return tiers
```

- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** — `feat(heartbeat): add quiet-hours and tier-selection helpers`

## Task 4: `check_cron_health` + `check_tokens` (inside-out, ledger-based)

**Files:**
- Modify: `core/heartbeat.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_check_cron_health_flags_stale(monkeypatch):
    from core import heartbeat
    from datetime import datetime, timezone, timedelta
    stale = datetime.now(timezone.utc) - timedelta(hours=40)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "morning-briefing": {"last_run_at": stale, "consecutive_failures": 0, "last_ok": True},
    })
    signals = heartbeat.check_cron_health()
    assert any(s.fingerprint == "cron:morning-briefing:stale" for s in signals)
    assert all(s.severity == heartbeat.SEVERITY_CRITICAL for s in signals)


def test_check_cron_health_flags_failure_streak(monkeypatch):
    from core import heartbeat
    from datetime import datetime, timezone
    fresh = datetime.now(timezone.utc)
    monkeypatch.setattr(heartbeat, "_read_cron_ledger", lambda: {
        "ingest-chats": {"last_run_at": fresh, "consecutive_failures": 3, "last_ok": False},
    })
    signals = heartbeat.check_cron_health()
    assert any(s.fingerprint == "cron:ingest-chats:failing" for s in signals)
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Implement in `core/heartbeat.py`.**

```python
# job_id -> max hours since last_run_at before the job is considered "stale".
# five-fingers is intentionally absent: it runs only on certain weekdays, so a
# stale-timestamp check would false-positive. It is still covered by the
# consecutive-failures check below.
_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
}
_CRON_FAILURE_STREAK_THRESHOLD = 3


def _read_cron_ledger() -> dict:
    """Return {job_id: doc_dict} from the Firestore heartbeat_runs collection."""
    from memory.firestore_db import _make_firestore_client
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    client = _make_firestore_client(project_id, database)
    out: dict = {}
    for snap in client.collection("heartbeat_runs").stream():
        out[snap.id] = snap.to_dict() or {}
    return out


def check_cron_health() -> list[Signal]:
    """Critical-tier: each cron ran recently and is not in a failure streak."""
    signals: list[Signal] = []
    try:
        ledger = _read_cron_ledger()
    except Exception:
        logger.warning("heartbeat: cron ledger read failed", exc_info=True)
        return signals

    now = datetime.now(timezone.utc)
    for job_id, max_hours in _CRON_MAX_STALENESS_HOURS.items():
        doc = ledger.get(job_id)
        if doc is None:
            signals.append(Signal(
                fingerprint=f"cron:{job_id}:missing",
                severity=SEVERITY_CRITICAL, area="cron",
                title=f"{job_id} has never recorded a run",
                detail="No heartbeat_runs ledger entry exists.",
                remediation=f"Confirm the Cloud Scheduler job for {job_id} exists and is enabled.",
            ))
            continue
        last = doc.get("last_run_at")
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_h = (now - last).total_seconds() / 3600
            if age_h > max_hours:
                signals.append(Signal(
                    fingerprint=f"cron:{job_id}:stale",
                    severity=SEVERITY_CRITICAL, area="cron",
                    title=f"{job_id} has not run in {age_h:.0f}h",
                    detail=f"Last run {last.isoformat()}; expected within {max_hours}h.",
                    remediation=f"Check the Cloud Scheduler job for {job_id} and Cloud Run logs.",
                ))

    for job_id, doc in ledger.items():
        if doc.get("consecutive_failures", 0) >= _CRON_FAILURE_STREAK_THRESHOLD:
            signals.append(Signal(
                fingerprint=f"cron:{job_id}:failing",
                severity=SEVERITY_CRITICAL, area="cron",
                title=f"{job_id} failed {doc['consecutive_failures']}x in a row",
                detail=f"last_ok={doc.get('last_ok')}.",
                remediation=f"Inspect Cloud Run logs for the {job_id} endpoint.",
            ))
    return signals


def check_tokens() -> list[Signal]:
    """Token/integration health: Google OAuth and TickTick OAuth refresh probes."""
    signals: list[Signal] = []

    try:
        from core.auth_google import get_credentials
        get_credentials()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:google:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="Google OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Re-run the Google OAuth bootstrap; refresh klaus-google-oauth-token.",
        ))

    try:
        from mcp_tools.ticktick_auth import get_access_token
        get_access_token()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:ticktick:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="TickTick OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Run scripts/ticktick_oauth_bootstrap.py to re-issue the token pair.",
        ))

    return signals
```

  > **Executor note:** verify the real symbol names in `core/auth_google.py` and
  > `mcp_tools/ticktick_auth.py` first (`grep -n "^def \|^    def " core/auth_google.py
  > mcp_tools/ticktick_auth.py`). Use whatever function performs a token load/refresh;
  > adjust the two imports above to match. Pinecone / Gemini / Telegram failures are
  > derived from the degradation metrics in Task 9 — keep `check_tokens` to the two
  > OAuth flows that genuinely need a live refresh probe.

- [ ] **Step 4: Run** the cron tests — expect PASS.
- [ ] **Step 5: Commit** — `feat(heartbeat): add cron-health and token checkers`

## Task 5: `run_tick` skeleton + `--dry-run` CLI (no sending)

**Files:**
- Modify: `core/heartbeat.py`

- [ ] **Step 1: Write the failing test**

```python
def test_collect_signals_filters_by_tier(monkeypatch):
    from core import heartbeat
    crit = heartbeat.Signal("x:y:z", heartbeat.SEVERITY_CRITICAL, "cron", "t", "d", "fix")
    warn = heartbeat.Signal("a:b:c", heartbeat.SEVERITY_WARNING, "token", "t", "d", "fix")
    monkeypatch.setattr(heartbeat, "check_cron_health", lambda: [crit])
    monkeypatch.setattr(heartbeat, "check_tokens", lambda: [warn])
    monkeypatch.setattr(heartbeat, "check_degradation", lambda: [])
    monkeypatch.setattr(heartbeat, "check_deployment", lambda: [])
    signals = heartbeat._collect_signals(tiers={heartbeat.SEVERITY_CRITICAL})
    assert crit in signals and warn not in signals
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Implement in `core/heartbeat.py`** — add `_load_config` (port from
  `attic/heartbeat/heartbeat.py:72-79`), stub `check_degradation` / `check_deployment` /
  `check_code` to `return []` for now, and:

```python
def _collect_signals(*, tiers: set[str], weekly: bool = False) -> list[Signal]:
    """Run all checkers, then keep only signals whose severity is in `tiers`."""
    raw: list[Signal] = []
    for checker in (check_cron_health, check_tokens, check_degradation, check_deployment):
        try:
            raw.extend(checker())
        except Exception:
            logger.warning("heartbeat: checker %s crashed", checker.__name__, exc_info=True)
    if weekly:
        try:
            raw.extend(check_code())
        except Exception:
            logger.warning("heartbeat: check_code crashed", exc_info=True)
    return [s for s in raw if s.severity in tiers]


async def run_tick(bot, now: datetime | None = None) -> list[Signal]:
    """Run one heartbeat tick. Returns the signals collected (for tests / dry-run)."""
    now = now or datetime.now(_TZ)
    config = _load_config()
    if not config.get("enabled", True):
        logger.info("heartbeat: disabled in config")
        return []
    tiers = _tiers_for_now(config, now)
    signals = _collect_signals(tiers=tiers, weekly=SEVERITY_FYI in tiers)
    logger.info("heartbeat: %d signal(s) in tiers %s", len(signals), sorted(tiers))
    # Delivery is wired in Phase 4 (Task 14).
    return signals
```

  Add the CLI (mirror `proactive_alerts.py:399-470`):

```python
def _cli() -> None:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Klaus heartbeat smoke test")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all checkers, print signals + message; no send/write.")
    args = parser.parse_args()
    if args.dry_run:
        signals = _collect_signals(
            tiers={SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_FYI}, weekly=True)
        print(f"[dry-run] {len(signals)} signal(s):")
        for s in signals:
            print(f"  [{s.severity}] {s.title} — {s.detail} -> {s.remediation}")
        if signals:
            print("\n[dry-run] Composed message:")
            print(_compose_message(signals))
        return
    print("Use --dry-run for local testing.")


if __name__ == "__main__":
    _cli()
```

  > `_compose_message` is added in Task 13. Until then, leave the
  > `if signals:` composed-message block out and add it back in Task 13.

- [ ] **Step 4: Run** `pytest tests/test_heartbeat.py -v` (all green) and
  `python -m core.heartbeat --dry-run` (prints signals, no crash).
- [ ] **Step 5: Commit** — `feat(heartbeat): add run_tick skeleton and --dry-run CLI`

---

# Phase 2 — Self-instrumentation

## Task 6: `record_cron_run` + `increment_fallback_counter` in firestore_db.py

**Files:**
- Modify: `memory/firestore_db.py`

- [ ] **Step 1: Write the failing test**

```python
def test_record_cron_run_ok_resets_failures(monkeypatch):
    import memory.firestore_db as fdb
    captured = {}
    class _Doc:
        def set(self, payload, merge): captured.update(payload)
    class _Col:
        def document(self, _id): return _Doc()
    class _Client:
        def collection(self, _name): return _Col()
    monkeypatch.setattr(fdb, "_make_firestore_client", lambda *a, **k: _Client())
    fdb.record_cron_run("ingest-chats", ok=True)
    assert captured["job_id"] == "ingest-chats"
    assert captured["last_ok"] is True
    assert captured["consecutive_failures"] == 0
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Add to `memory/firestore_db.py`** (module-level, near `_make_firestore_client`):

```python
def record_cron_run(job_id: str, ok: bool) -> None:
    """Write a liveness ledger entry to heartbeat_runs/{job_id}.

    Called once per cron-endpoint invocation. On success, consecutive_failures
    is reset to 0; on failure it is incremented. Never raises.
    """
    try:
        from datetime import datetime, timezone
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        payload = {
            "job_id": job_id,
            "last_run_at": datetime.now(timezone.utc),
            "last_ok": ok,
        }
        if ok:
            payload["consecutive_failures"] = 0
            payload["last_ok_at"] = datetime.now(timezone.utc)
        else:
            payload["consecutive_failures"] = firestore.Increment(1)
        client.collection("heartbeat_runs").document(job_id).set(payload, merge=True)
    except Exception:
        logger.warning("record_cron_run(%s, ok=%s) failed", job_id, ok, exc_info=True)


def increment_fallback_counter() -> None:
    """Increment today's Gemini->Haiku fallback counter in heartbeat_metrics. Never raises."""
    try:
        from datetime import date
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        today = date.today().isoformat()
        client.collection("heartbeat_metrics").document(today).set(
            {"date": today, "fallback_count": firestore.Increment(1)}, merge=True)
    except Exception:
        logger.warning("increment_fallback_counter failed", exc_info=True)
```

  > `record_cron_run` uses a real `datetime` (not `SERVER_TIMESTAMP`) so the value is
  > readable immediately and unit-testable. `firestore` is already imported at
  > `memory/firestore_db.py:18`, so `firestore.Increment` is available.

- [ ] **Step 4: Run** the test — expect PASS.
- [ ] **Step 5: Commit** — `feat(heartbeat): add cron-run ledger and fallback-counter helpers`

## Task 7: Wrap all six `/cron/*` routes with `record_cron_run`

**Files:**
- Modify: `interfaces/web_server.py`

The cleanest single-file instrumentation point is the route handlers themselves — the
spec's "cron handlers write a success doc"; the route *is* the handler boundary.

- [ ] **Step 1:** Add a helper near `_verify_cron_request` in `interfaces/web_server.py`:

```python
def _log_cron_run(job_id: str, ok: bool) -> None:
    """Best-effort liveness ledger write for a cron endpoint. Never raises."""
    try:
        from memory.firestore_db import record_cron_run
        record_cron_run(job_id, ok)
    except Exception:
        logger.warning("Failed to record cron run for %s", job_id, exc_info=True)
```

- [ ] **Step 2:** In each of the six `/cron/*` route functions
  (`cron_five_fingers_morning`, `cron_proactive_alerts`, `cron_five_fingers_evening`,
  `cron_morning_briefing_tick`, `cron_ingest_chats`, `cron_ingest_chat_exports`), wrap
  the body **after** `_verify_cron_request` in `try/except`, calling `_log_cron_run` in
  both paths. Job IDs: `five-fingers` (morning + evening share this id),
  `proactive-alerts`, `morning-briefing`, `ingest-chats`, `ingest-chat-exports`.
  Example for `cron_morning_briefing_tick`:

```python
@app.post("/cron/morning-briefing-tick")
async def cron_morning_briefing_tick(request: Request) -> JSONResponse:
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.morning_briefing as _morning
    try:
        await _morning.handle_tick(_application.bot)
        _log_cron_run("morning-briefing", ok=True)
    except Exception:
        _log_cron_run("morning-briefing", ok=False)
        raise
    return JSONResponse(content={"ok": True})
```

  Apply the same wrap to the other five. For the two ingest routes, a normal return
  from the executor is `ok=True`, an exception is `ok=False`. `_verify_cron_request`
  raises *before* the try block, so auth failures are never recorded as cron runs.

- [ ] **Step 3:** Run `python -c "import interfaces.web_server"` — expect no import error.
- [ ] **Step 4: Commit** — `feat(heartbeat): record cron-run liveness for all cron routes`

## Task 8: Fallback counter at the Gemini→Haiku site in main.py

**Files:**
- Modify: `core/main.py` (`_run_smart_loop`, line ~267)

- [ ] **Step 1:** At `core/main.py:267`, immediately after
  `logger.info("Retrying with Smart Agent fallback…")`, add:

```python
                        try:
                            from memory.firestore_db import increment_fallback_counter
                            increment_fallback_counter()
                        except Exception:
                            logger.debug("fallback counter increment failed", exc_info=True)
```

  This is inside the existing `if self.smart_agent_fallback is not None:` block, so it
  only fires on an actual fallback. Match the surrounding indentation exactly.

- [ ] **Step 2:** Run `python -c "import core.main"` — expect no import error.
- [ ] **Step 3: Commit** — `feat(heartbeat): count Gemini->Haiku fallbacks in Firestore`

---

# Phase 3 — Outside-in checks

## Task 9: `check_degradation` (Firestore fallback metric + Cloud Monitoring 5xx)

**Files:**
- Modify: `core/heartbeat.py`, `requirements.txt`

- [ ] **Step 1: Write the failing test**

```python
def test_check_degradation_flags_high_fallback(monkeypatch):
    from core import heartbeat
    monkeypatch.setattr(heartbeat, "_read_fallback_count_today", lambda: 25)
    monkeypatch.setattr(heartbeat, "_read_cloud_run_5xx", lambda: 0)
    signals = heartbeat.check_degradation()
    assert any(s.fingerprint == "degradation:fallback-rate" for s in signals)
    assert all(s.severity == heartbeat.SEVERITY_WARNING for s in signals)
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Implement in `core/heartbeat.py`.** `_read_fallback_count_today()` reads
  `heartbeat_metrics/{today}.fallback_count` (today = `date.today().isoformat()`),
  returns `0` on any error. `_read_cloud_run_5xx()` queries Cloud Monitoring for the
  `run.googleapis.com/request_count` metric over the last hour, returns `0` on error.

```python
_FALLBACK_WARN_THRESHOLD = 10        # fallbacks/day before flagging
_CLOUD_RUN_5XX_WARN_THRESHOLD = 5    # 5xx responses in the last hour


def check_degradation() -> list[Signal]:
    """Warning-tier: fallback-rate climbing, Cloud Run 5xx spikes."""
    signals: list[Signal] = []
    try:
        fallbacks = _read_fallback_count_today()
        if fallbacks >= _FALLBACK_WARN_THRESHOLD:
            signals.append(Signal(
                fingerprint="degradation:fallback-rate",
                severity=SEVERITY_WARNING, area="degradation",
                title=f"Gemini->Haiku fallback fired {fallbacks}x today",
                detail="Primary Smart Agent (Gemini 3) is erroring or rate-limited.",
                remediation="Check Gemini quota / API key; review Cloud Run logs for LLMError.",
            ))
    except Exception:
        logger.warning("heartbeat: fallback metric read failed", exc_info=True)
    try:
        errs = _read_cloud_run_5xx()
        if errs >= _CLOUD_RUN_5XX_WARN_THRESHOLD:
            signals.append(Signal(
                fingerprint="degradation:cloud-run-5xx",
                severity=SEVERITY_WARNING, area="degradation",
                title=f"{errs} Cloud Run 5xx responses in the last hour",
                detail="klaus-agent is returning server errors.",
                remediation="Inspect Cloud Run logs for unhandled exceptions / OOM.",
            ))
    except Exception:
        logger.warning("heartbeat: Cloud Monitoring read failed", exc_info=True)
    return signals
```

  `_read_cloud_run_5xx` uses `google.cloud.monitoring_v3.MetricServiceClient`, a 3600s
  `Aggregation` with `ALIGN_SUM`, and the filter
  `metric.type="run.googleapis.com/request_count" AND
  resource.labels.service_name="klaus-agent" AND
  metric.labels.response_code_class="5xx"`. Sum the points in the returned series.

- [ ] **Step 4:** Add `google-cloud-monitoring>=2.20` to `requirements.txt` under the
  `# --- Cloud state ---` group.
- [ ] **Step 5: Run** the test — expect PASS.
- [ ] **Step 6: Commit** — `feat(heartbeat): add degradation checker (fallback rate + 5xx)`

## Task 10: `check_deployment` (GitHub Actions API + Cloud Run revision)

**Files:**
- Modify: `core/heartbeat.py`, `requirements.txt`

- [ ] **Step 1: Write the failing test**

```python
def test_check_deployment_flags_failed_deploy(monkeypatch):
    from core import heartbeat
    monkeypatch.setattr(heartbeat, "_latest_deploy_status",
                        lambda: {"conclusion": "failure", "head_sha": "abc123def"})
    monkeypatch.setattr(heartbeat, "_live_revision_sha", lambda: "abc123def")
    signals = heartbeat.check_deployment()
    assert any(s.fingerprint == "deployment:last-deploy-failed" for s in signals)
    assert any(s.severity == heartbeat.SEVERITY_CRITICAL for s in signals)
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Implement in `core/heartbeat.py`.**
  - `_latest_deploy_status()` — GET
    `https://api.github.com/repos/{KLAUS_GITHUB_REPO}/actions/workflows/deploy.yml/runs?per_page=1`
    with header `Authorization: Bearer {KLAUS_GITHUB_TOKEN}` (use `requests`, already a
    dependency; 10s timeout). Return `{"conclusion", "head_sha", "status"}` from
    `workflow_runs[0]`, or `None` on error.
  - `_live_revision_sha()` — Cloud Run Admin API (`google-cloud-run`): describe service
    `klaus-agent` in region `me-west1`, read the serving revision's container image
    tag, and extract the commit SHA (`deploy.yml:23` tags images `agent:${{ github.sha }}`).
    Return `None` on error.
  - `check_deployment()`:

```python
def check_deployment() -> list[Signal]:
    """Deployment health: last deploy succeeded; live revision matches latest main."""
    signals: list[Signal] = []
    try:
        deploy = _latest_deploy_status()
        if deploy and deploy.get("conclusion") == "failure":
            signals.append(Signal(
                fingerprint="deployment:last-deploy-failed",
                severity=SEVERITY_CRITICAL, area="deployment",
                title="Last GitHub Actions deploy failed",
                detail=f"Workflow run for {deploy.get('head_sha', '?')[:8]} concluded 'failure'.",
                remediation="Open the Actions tab for the deploy.yml run and fix the failure.",
            ))
        live = _live_revision_sha()
        head = (deploy or {}).get("head_sha")
        if live and head and not head.startswith(live) and not live.startswith(head):
            signals.append(Signal(
                fingerprint="deployment:revision-behind",
                severity=SEVERITY_WARNING, area="deployment",
                title="Live Cloud Run revision is behind main",
                detail=f"Live={live[:8]}, latest main={head[:8]}.",
                remediation="Re-run the deploy workflow or push to main to trigger a deploy.",
            ))
    except Exception:
        logger.warning("heartbeat: deployment check failed", exc_info=True)
    return signals
```

- [ ] **Step 4:** Add `google-cloud-run>=0.10` to `requirements.txt`.
- [ ] **Step 5: Run** the test — expect PASS.
- [ ] **Step 6: Commit** — `feat(heartbeat): add deployment checker (GitHub + Cloud Run revision)`

## Task 11: Env vars for the GitHub token

**Files:**
- Modify: `.env.example`

- [ ] **Step 1:** In `.env.example`, after the Phase 13 block (line 134), append:

```
# Phase 14: Self-monitoring heartbeat
# GitHub repo "owner/name" for the deploy-status check (e.g. amitgrupper/Klaus).
KLAUS_GITHUB_REPO=
# Fine-grained GitHub read token (Actions: read). On Cloud Run this is injected
# from Secret Manager secret "klaus-github-token"; set inline only for local dev.
KLAUS_GITHUB_TOKEN=
# Optional dead-man's-switch: a healthchecks.io ping URL hit at the end of a
# successful tick. Leave blank to disable.
HEARTBEAT_DEADMAN_URL=
```

- [ ] **Step 2: Commit** — `docs(heartbeat): document GitHub token and dead-man env vars`

  > `CLOUD_RUN_URL` and `CLOUD_SCHEDULER_SA_EMAIL` already exist in `.env.example`
  > (lines 88–93) and `deploy.yml` (line 90) — no change needed there.

---

# Phase 4 — Incidents + delivery

## Task 12: `IncidentStore` in firestore_db.py

**Files:**
- Modify: `memory/firestore_db.py`

- [ ] **Step 1: Write the failing test**

```python
def test_incident_store_should_ping_logic():
    from memory.firestore_db import IncidentStore
    from datetime import datetime, timezone, timedelta
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    assert IncidentStore._should_ping(None, reping_interval_hours=24) is True
    assert IncidentStore._should_ping({"last_pinged": recent}, reping_interval_hours=24) is False
    assert IncidentStore._should_ping({"last_pinged": old}, reping_interval_hours=24) is True
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Add `IncidentStore` to `memory/firestore_db.py`** — Firestore collection
  `heartbeat_incidents`, document id = `fingerprint` with any `/` replaced by `_`
  (`:` is a legal Firestore id char). Methods:
  - `_should_ping(doc, *, reping_interval_hours) -> bool` — staticmethod, pure. `True`
    if `doc is None`, or if `now - doc["last_pinged"] >= reping_interval_hours`.
  - `record_open(signal, *, reping_interval_hours) -> bool` — read the existing doc;
    compute `_should_ping`; upsert `{fingerprint, severity, title, status:"open",
    first_seen (set once), last_seen:now}` and, when ping is due, also set
    `last_pinged:now`. Return the `_should_ping` result.
  - `resolve_absent(active_fingerprints: set[str]) -> list[dict]` — stream all docs
    with `status=="open"`; for any whose `fingerprint` is **not** in
    `active_fingerprints`, set `status:"resolved"`, `resolved_at:now`; return the list
    of just-resolved docs (for optional "recovered" notes).

- [ ] **Step 4: Run** the test — expect PASS.
- [ ] **Step 5: Commit** — `feat(heartbeat): add IncidentStore for dedup and escalation`

## Task 13: Composer + `prompts/heartbeat.md`

**Files:**
- Create: `prompts/heartbeat.md`
- Modify: `core/heartbeat.py`

- [ ] **Step 1: Create `prompts/heartbeat.md`** — system prompt for the worker model:

```
You are Klaus's self-monitoring voice, reporting on Klaus's own health.

You are given a JSON list of health signals. Each has: severity
("critical"|"warning"|"fyi"), area, title, detail, and remediation.

Write ONE concise Telegram message:
- Group signals by severity, Critical first, then Warning, then FYI.
- For each signal: one line stating the problem, then the suggested fix.
- If there are only Warning/FYI signals, frame the message as a status digest.
- No greetings, no sign-offs, no filler. Get to the point.
- Tone: calm, clipped, precise — like a good EA reporting on itself.

Compose the message now.
```

- [ ] **Step 2: Write the failing test**

```python
def test_plain_text_fallback_groups_by_severity():
    from core.heartbeat import (_plain_text_fallback, Signal,
                                SEVERITY_CRITICAL, SEVERITY_WARNING)
    msg = _plain_text_fallback([
        Signal("a:b:c", SEVERITY_CRITICAL, "cron", "Cron down", "stale 40h", "Check scheduler."),
        Signal("d:e:f", SEVERITY_WARNING, "token", "Token expiring", "3 days left", "Refresh it."),
    ])
    assert "Cron down" in msg and "Check scheduler." in msg
    assert msg.index("Cron down") < msg.index("Token expiring")
```

- [ ] **Step 3: Run** — expect FAIL.

- [ ] **Step 4: Implement `_compose_message` + `_plain_text_fallback` in `core/heartbeat.py`**
  — model on `proactive_alerts._compose_alert` (lines 334–392), but use the **worker**
  model (`WORKER_AGENT_BACKEND` / `WORKER_AGENT_MODEL` / `WORKER_AGENT_API_KEY`):

```python
_SEVERITY_ORDER = [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_FYI]
_SEVERITY_HEADER = {
    SEVERITY_CRITICAL: "CRITICAL",
    SEVERITY_WARNING: "Warnings",
    SEVERITY_FYI: "FYI",
}


def _plain_text_fallback(signals: list[Signal]) -> str:
    """Deterministic grouped message used when the LLM composer is unavailable."""
    lines: list[str] = []
    for severity in _SEVERITY_ORDER:
        group = [s for s in signals if s.severity == severity]
        if not group:
            continue
        lines.append(f"[{_SEVERITY_HEADER[severity]}]")
        for s in group:
            lines.append(f"• {s.title} — {s.detail}")
            lines.append(f"  → {s.remediation}")
        lines.append("")
    return "\n".join(lines).strip() or "Heartbeat: all systems nominal."


def _compose_message(signals: list[Signal]) -> str:
    """Compose the Telegram message via the worker LLM, with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "heartbeat.md"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8")
    except OSError:
        return _plain_text_fallback(signals)

    payload = json.dumps([{
        "severity": s.severity, "area": s.area, "title": s.title,
        "detail": s.detail, "remediation": s.remediation,
    } for s in signals], ensure_ascii=False, indent=2)

    try:
        from core.llm_client import LLMClient
        client = LLMClient(
            backend=os.environ["WORKER_AGENT_BACKEND"],
            model=os.environ["WORKER_AGENT_MODEL"],
            api_key=os.environ["WORKER_AGENT_API_KEY"],
        )
        response = client.chat(
            messages=[{"role": "user", "content": payload}],
            system=system_prompt,
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("heartbeat: LLM composition failed", exc_info=True)

    return _plain_text_fallback(signals)
```

  Restore the `_compose_message` block in `_cli()` (deferred in Task 5).

- [ ] **Step 5: Run** the test — expect PASS.
- [ ] **Step 6: Commit** — `feat(heartbeat): add LLM composer and plain-text fallback`

## Task 14: Wire delivery + incident dedup into `run_tick`

**Files:**
- Modify: `core/heartbeat.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_tick_pings_new_critical(monkeypatch):
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core import heartbeat
    monkeypatch.setattr(heartbeat, "_load_config", lambda: {
        "enabled": True, "quiet_start": "22:00", "quiet_end": "07:00",
        "timezone": "Asia/Jerusalem", "digest_hour": 9,
        "weekly_digest_day": 1, "reping_interval_hours": 24})
    crit = heartbeat.Signal("cron:x:stale", heartbeat.SEVERITY_CRITICAL,
                            "cron", "t", "d", "fix")
    monkeypatch.setattr(heartbeat, "_collect_signals", lambda **k: [crit])
    monkeypatch.setattr(heartbeat, "_compose_message", lambda s: "composed")
    monkeypatch.setattr(heartbeat, "_register_incidents",
                        lambda crits, cfg: [crit])          # all should ping
    monkeypatch.setattr(heartbeat, "_resolve_absent", lambda fps: None)
    monkeypatch.setattr(heartbeat, "_drain_quiet_queue",
                        lambda bot, now, cfg: None)
    sent = []
    async def _send(bot, text, **kw): sent.append(text)
    monkeypatch.setattr(heartbeat, "send_and_inject", _send)
    noon = datetime(2026, 5, 19, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    asyncio.run(heartbeat.run_tick(object(), now=noon))
    assert sent == ["composed"]
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Extend `run_tick` in `core/heartbeat.py`.** Add `from core.scheduled_message
  import send_and_inject` at the top. After `_collect_signals`, implement:
  1. `_drain_quiet_queue(bot, now, config)` at the **top** of `run_tick` (before
     collecting) — if not in quiet hours and a `heartbeat_queue/pending` doc exists,
     compose its queued signals, send, and delete the doc.
  2. Split `signals` by severity.
  3. `_register_incidents(critical_signals, config)` — for each Critical signal call
     `IncidentStore.record_open(...)`; return the sublist whose `record_open` returned
     `True` (new, or re-ping interval elapsed). If that sublist is non-empty:
     - **Not** in quiet hours → `send_and_inject(bot, _compose_message(sublist),
       inject_into_conversation=True)`.
     - In quiet hours → append the sublist's signals to `heartbeat_queue/pending` for
       `_drain_quiet_queue` to deliver after `quiet_end`.
  4. If Warning tier active and Warning signals non-empty → compose + send a daily
     digest. If FYI tier active and FYI signals non-empty → weekly digest. Digests are
     **suppressed when empty** (no send).
  5. `_resolve_absent({s.fingerprint for s in signals})` → wraps
     `IncidentStore.resolve_absent`.
  6. If `os.getenv("HEARTBEAT_DEADMAN_URL")` is set, `requests.get(url, timeout=10)`
     inside `try/except` as the final step (Task 17 also references this — implement
     it here).

  Keep `_register_incidents`, `_resolve_absent`, `_drain_quiet_queue` as module-level
  functions so tests can monkeypatch them.

- [ ] **Step 4: Run** the test — expect PASS; run full `pytest tests/test_heartbeat.py -v`.
- [ ] **Step 5: Commit** — `feat(heartbeat): wire incident dedup, quiet-hours queue, and delivery`

---

# Phase 5 — Wire-up + deploy

## Task 15: `/cron/heartbeat` route

**Files:**
- Modify: `interfaces/web_server.py`

- [ ] **Step 1:** Add after `cron_ingest_chat_exports`:

```python
@app.post("/cron/heartbeat")
async def cron_heartbeat(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler hourly tick and run one heartbeat health check.

    Schedule: 0 * * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.heartbeat as _heartbeat
    try:
        await _heartbeat.run_tick(_application.bot)
        _log_cron_run("heartbeat", ok=True)
    except Exception:
        _log_cron_run("heartbeat", ok=False)
        raise
    return JSONResponse(content={"ok": True})
```

  > `run_tick` makes blocking Firestore / HTTP calls. If a tick proves slow in
  > practice, wrap the checker fan-out in `loop.run_in_executor` as the ingest routes
  > do (`web_server.py:382-383`). Decide during execution based on observed latency.

- [ ] **Step 2:** Run `python -c "import interfaces.web_server"` — expect no error.
- [ ] **Step 3: Write + run the auth test**

```python
def test_cron_heartbeat_rejects_unauthenticated(monkeypatch):
    monkeypatch.setenv("CRON_DEV_BYPASS", "false")
    from fastapi.testclient import TestClient
    from interfaces.web_server import app
    with TestClient(app) as client:
        resp = client.post("/cron/heartbeat")
    assert resp.status_code == 401
```

- [ ] **Step 4: Commit** — `feat(heartbeat): add /cron/heartbeat route`

## Task 16: deploy.yml env vars

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1:** In the `--set-env-vars` string (`deploy.yml:90`), append
  `,KLAUS_GITHUB_REPO=${{ secrets.KLAUS_GITHUB_REPO }}` before the closing quote.
- [ ] **Step 2:** In the `--update-secrets` string (`deploy.yml:91`), append
  `,KLAUS_GITHUB_TOKEN=klaus-github-token:latest` before the closing quote.
- [ ] **Step 3: Commit** — `chore(deploy): wire heartbeat GitHub token env vars`

## Task 17: Confirm dead-man's-switch wiring

The healthchecks.io ping was implemented as step 6 of Task 14's `run_tick`.

- [ ] **Step 1:** Confirm `run_tick` ends with the `HEARTBEAT_DEADMAN_URL` ping inside a
  `try/except` and that `HEARTBEAT_DEADMAN_URL` is documented in `.env.example` (Task 11).
- [ ] **Step 2:** No commit if nothing changed; otherwise
  `feat(heartbeat): confirm dead-man's-switch ping`.

## Task 18: Infra provisioning (manual — run by the user)

Not code. Document these in the PR description; the user runs them once:

- [ ] Grant outside-in read access to the **runtime** SA:
```bash
gcloud projects add-iam-policy-binding klaus-agent \
  --member="serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com" \
  --role="roles/monitoring.viewer"
gcloud projects add-iam-policy-binding klaus-agent \
  --member="serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com" \
  --role="roles/run.viewer"
```
- [ ] Create the GitHub token secret + grant the runtime SA access:
```bash
printf '%s' "<github-fine-grained-token>" | gcloud secrets create klaus-github-token \
  --data-file=- --project klaus-agent
gcloud secrets add-iam-policy-binding klaus-github-token \
  --member="serviceAccount:klaus-runtime@klaus-agent.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project klaus-agent
```
- [ ] Set the `KLAUS_GITHUB_REPO` GitHub Actions repository secret to `amitgrupper/Klaus`.
- [ ] Ensure the scheduler SA can invoke Cloud Run:
```bash
gcloud run services add-iam-policy-binding klaus-agent \
  --member="serviceAccount:klaus-heartbeat@klaus-agent.iam.gserviceaccount.com" \
  --role="roles/run.invoker" --region me-west1 --project klaus-agent
```
- [ ] Create the Cloud Scheduler job:
```bash
gcloud scheduler jobs create http klaus-heartbeat \
  --location me-west1 --schedule "0 * * * *" --time-zone "Asia/Jerusalem" \
  --uri "https://klaus-agent-y2abtypx4q-zf.a.run.app/cron/heartbeat" \
  --http-method POST \
  --oidc-service-account-email "klaus-heartbeat@klaus-agent.iam.gserviceaccount.com" \
  --oidc-token-audience "https://klaus-agent-y2abtypx4q-zf.a.run.app" \
  --project klaus-agent
```

## Task 19: Deploy + live verification

- [ ] Push to `main`; confirm the GitHub Actions deploy succeeds and `/health` is green.
- [ ] Manually trigger the scheduler job:
  `gcloud scheduler jobs run klaus-heartbeat --location me-west1 --project klaus-agent`.
- [ ] Confirm no Telegram message when healthy (silent tick), and that a
  `heartbeat_runs/heartbeat` ledger doc was written.
- [ ] Synthetic failure: set `heartbeat_runs/ingest-chats.last_run_at` 40h in the past
  → trigger the job → confirm a Critical Telegram ping and a
  `heartbeat_incidents/{fingerprint}` doc with `status:"open"`.
- [ ] Trigger again immediately → confirm the second run is **silent** (dedup within
  `reping_interval_hours`).

---

# Phase 6 — F-tier (weekly, independently shippable)

## Task 20: `check_code` — docs drift + stale TODOs + repeated-fix clusters

**Files:**
- Modify: `core/heartbeat.py`
- Test: `tests/test_heartbeat.py`

- [ ] **Step 1: Write the failing test** — point `check_code` at a temp dir (via a
  `repo_root` argument defaulting to the real repo root) containing a `CLAUDE.md` that
  references a non-existent path and a file with an old `# TODO`. Assert it returns
  FYI-severity signals with `area == "code"`.

- [ ] **Step 2: Implement `check_code(repo_root: Path | None = None)`** — all signals
  `SEVERITY_FYI`, `area="code"`:
  - **Docs drift:** parse the directory-tree block in `CLAUDE.md` (the fenced
    ```text``` block, lines ~30–55); for each referenced path, flag any that no longer
    exists on disk. Fingerprint `code:docs-drift`.
  - **Stale TODOs:** `grep -rn "TODO\\|FIXME" core/ mcp_tools/ interfaces/ memory/`;
    if the count exceeds 15, emit one signal listing the count and a few examples.
    Fingerprint `code:stale-todos`.
  - **Repeated-fix clusters:** `git log --since="60 days ago" --pretty=%s`; count
    commit subjects starting with `fix(`; if any single scope (the text inside
    `fix(...)`) appears ≥4 times, flag it as a churn hotspot. Fingerprint
    `code:fix-cluster:{scope}`.

- [ ] **Step 3: Run** the test — expect PASS.
- [ ] **Step 4: Commit** — `feat(heartbeat): add weekly F-tier code self-knowledge checker`

## Task 21: Verify weekly wiring

- [ ] Run `python -m core.heartbeat --dry-run` — confirm `check_code` signals appear
  (the dry-run CLI already passes `weekly=True`).
- [ ] Confirm `_tiers_for_now` includes FYI only on `weekly_digest_day` at `digest_hour`
  (covered by Task 3's test).
- [ ] Commit only if anything changed.

## Task 22: Self-review pass

- [ ] Re-read the spec (`docs/superpowers/specs/2026-05-17-heartbeat-design.md`); confirm
  every watch-list item A/B/C/E/F maps to a checker. Note any gap.
- [ ] Grep `core/heartbeat.py` for placeholder strings (`TODO`, `pass  #`, `...`).
- [ ] Confirm fingerprint strings, `Signal` field names, and store method names are
  consistent across all tasks.

---

## Verification (end-to-end)

1. **Unit:** `pytest tests/test_heartbeat.py -v` — all green.
2. **CLI smoke:** `python -m core.heartbeat --dry-run` — runs every checker, prints
   signals + would-be message, no send/write.
3. **Synthetic failure:** age a `heartbeat_runs` ledger doc 40h → confirm the matching
   Critical signal is detected and classified.
4. **Dedup:** run the tick twice against the same failure → second run silent.
5. **Auth:** unauthenticated `POST /cron/heartbeat` → 401 (Task 15 test).
6. **Live:** trigger the `klaus-heartbeat` Cloud Scheduler job → Telegram message +
   `heartbeat_incidents` doc.

## Out of scope (deferred)

- **D. Pipeline freshness** (chat-log upload stalled / ingestion throughput).
- **Self-healing** — Klaus acting on prod (retrying crons, refreshing tokens). v1 is
  report + diagnose only.
- **Tool-failure aggregation** — counting every broad-`except` site.
- The broader calendar / Claude-Code-history watchers from the original idea.
