---
phase: 29-web-push-transition
plan: 01
subsystem: infra
tags: [web-push, vapid, pywebpush, secret-manager, dependencies]

# Dependency graph
requires: []
provides:
  - "pywebpush>=2.3 pinned in requirements.txt and installed (py-vapid 1.9.4 transitive)"
  - "Secret Manager secret klaus-vapid-private-key (v1, project klaus-agent) holding the VAPID private key PEM"
  - "VAPID_PUBLIC_KEY env var set on Cloud Run (rev klaus-agent-00139-4sm) + local .env, documented in .env.example"
  - "DEPLOYMENT.md §27 VAPID key-gen/storage/rotation runbook"
affects:
  - 29-04 (core/push_sender.py reads klaus-vapid-private-key)
  - 29-08 (send paths use pywebpush webpush/WebPushException)
  - frontend subscribe flow (VAPID_PUBLIC_KEY via /api/push/vapid-public-key)

# Tech tracking
tech-stack:
  added: [pywebpush 2.3.0, py-vapid 1.9.4 (transitive)]
  patterns:
    - "VAPID private key ONLY in Secret Manager (access_secret_version on latest); public key env-driven"
    - "Package-legitimacy human gate before any new PyPI install (T-29-SC)"

key-files:
  created: []
  modified:
    - requirements.txt
    - .env.example
    - docs/DEPLOYMENT.md

key-decisions:
  - "py-vapid not explicitly pinned — arrives transitively with pywebpush and imports fine (per plan guidance)"
  - "DEPLOYMENT.md runbook includes a rotation section warning that VAPID rotation invalidates all subscriptions (rotate only on compromise)"

# Metrics
duration: ~10min active (spanned two human gates)
completed: 2026-07-04
---

# Phase 29 Plan 01: Web Push Dependency + VAPID Key Setup Summary

**pywebpush 2.3.0 installed behind a human legitimacy gate; VAPID keypair generated with the private key in Secret Manager (`klaus-vapid-private-key`) and the public key as `VAPID_PUBLIC_KEY` on Cloud Run — unblocking every push-sending plan.**

## What Was Done

### Task 1: Package legitimacy gate (checkpoint:human-verify, blocking-human)
Both `pywebpush` and `py-vapid` were tagged [ASSUMED] in research (slopcheck unavailable). The user verified on PyPI: pywebpush 2.3.0 published by web-push-libs (github.com/web-push-libs/pywebpush), py-vapid by mozilla-services, no yank/security warnings. **Approved** — install proceeded only after approval, per threat T-29-SC.

### Task 2: Pin and install pywebpush (`bfeee5f`)
- Added `pywebpush>=2.3` to `requirements.txt` under a new "Web Push notifications (Phase 29)" section, following the existing grouped-by-phase convention.
- Installed into the project `.venv` (Python 3.13.12 — never system 3.14 per grpc GC segfault invariant). Resolved: pywebpush 2.3.0, py-vapid 1.9.4 (transitive), http-ece 1.2.1, aiohttp 3.14.1.
- Verified: `import pywebpush, py_vapid` and `from pywebpush import webpush, WebPushException` both exit 0.

### Task 3: VAPID keypair + Secret Manager + documentation (`eb17145` + operator)
Claude-side (committed):
- `.env.example`: `VAPID_PUBLIC_KEY` placeholder with a comment explaining generation (`vapid --applicationServerKey`) and the private-key-never-an-env-var rule.
- `docs/DEPLOYMENT.md` §27: full runbook — 5-step key-gen/storage procedure (`vapid --gen` → `--applicationServerKey` → `gcloud secrets create klaus-vapid-private-key` → Cloud Run env update → verify via `versions access latest`), IAM note (existing `secretAccessor` suffices, read-only), and a rotation section warning that rotating the keypair invalidates every push subscription.

Operator-side (confirmed complete via "vapid ready"):
- Keypair generated; private key stored as Secret Manager secret `klaus-vapid-private-key` (project `klaus-agent`, version 1, verified readable).
- `VAPID_PUBLIC_KEY` set on Cloud Run service `klaus-agent` (me-west1, revision `klaus-agent-00139-4sm`) and in local `.env`.
- Local `.pem` files deleted (private key never entered the repo tree).

## Verification Results

| Check | Result |
|-------|--------|
| `python -c "import pywebpush"` exits 0 (.venv) | PASS |
| `from pywebpush import webpush, WebPushException` exits 0 | PASS |
| `grep -q pywebpush requirements.txt` | PASS |
| `grep -q VAPID_PUBLIC_KEY .env.example` | PASS |
| `docs/DEPLOYMENT.md` contains `klaus-vapid-private-key` + runbook | PASS |
| Secret `klaus-vapid-private-key` exists + readable; VAPID_PUBLIC_KEY on Cloud Run | PASS (operator-confirmed, rev klaus-agent-00139-4sm) |

## Deviations from Plan

**1. [Minor] Version check via importlib.metadata instead of `pywebpush.__version__`**
- **Found during:** Task 2 verification
- **Issue:** The plan's automated verify used `pywebpush.__version__`, but pywebpush 2.3.0 does not expose a `__version__` attribute (AttributeError).
- **Fix:** Verified with `importlib.metadata.version('pywebpush')` → 2.3.0. All acceptance criteria (import exit-0 checks) still ran exactly as written and passed. No code changes.
- **Files modified:** none
- **Commit:** n/a

No other deviations — plan executed as written.

## Human Gates (normal flow, not deviations)

- **Task 1 (human-verify, blocking-human):** package legitimacy — approved.
- **Task 3 (human-action, blocking):** live GCP key/secret setup — completed by operator, confirmed "vapid ready".

## Known Stubs

None. This plan is dependency + key infrastructure only; `core/push_sender.py` (the consumer of `klaus-vapid-private-key`) is Plan 04's deliverable by design.

## Threat Model Compliance

- **T-29-SC (mitigate):** install gated behind blocking human-verify checkpoint — enforced, not auto-approved.
- **T-29-01 (mitigate):** private key exists only in Secret Manager; `.env.example` carries a placeholder + explicit warning; PEM files deleted post-upload; nothing key-shaped committed.
- **T-29-02 (accept):** as planned.

No new threat surface introduced beyond the plan's threat model (docs + dependency pin only; no new endpoints/auth paths/schema).

## Commits

| Commit | Message |
|--------|---------|
| `bfeee5f` | chore(29-01): pin pywebpush>=2.3 for Web Push sends |
| `eb17145` | docs(29-01): document VAPID_PUBLIC_KEY env var + Secret Manager runbook |

## Self-Check: PASSED
