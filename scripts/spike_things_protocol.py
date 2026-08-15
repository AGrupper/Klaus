"""Things Cloud protocol spike — READ-ONLY schema discovery.

Throwaway exploration script for Step 0 of the Things 3 integration.  Cultured
Code publishes no API; the item payload uses short obfuscated keys whose meaning
is not documented anywhere.  This script authenticates against the real account,
replays the history journal from index 0, and reports the observed schema so the
mapping in ``docs/things_protocol.md`` can be derived from real data rather than
guessed from third-party libraries.

**This script never writes.**  It does not import, reference, or construct a call
to the ``/commit`` endpoint.  The worst it can do is read.

Usage::

    .venv/bin/python scripts/spike_things_protocol.py            # summary only
    .venv/bin/python scripts/spike_things_protocol.py --dump     # + raw JSON dump

Requires ``THINGS_EMAIL`` and ``THINGS_PASSWORD`` in ``.env``.

Protocol (reverse-engineered, cross-checked against disrupted/things-cloud-api):

    GET  /version/1/account/{email}
         Authorization: Password <url-quoted password>
      -> {"history-key", "maildrop-email", "status", "SLA-version-accepted", ...}

    POST /api/account/login/getT3SharedSession
         Authorization: B64SON <base64 of {"ep":{"e":email,"p":password}}>
      -> {"headIndex", "historyKeySessionSecret"}

    GET  /version/1/history/{history-key}/items?start-index=N
      -> {"updates": [{"id", "body": {"type", "payload"}}], "current-item-index"}
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

# Always override — the default silently ignores .env when the shell already
# exported the var, which has bitten this project before.
load_dotenv(override=True)

API_BASE = "https://cloud.culturedcode.com/version/1"
LOGIN_URL = "https://cloud.culturedcode.com/api/account/login/getT3SharedSession"

APP_ID = os.environ.get("THINGS_APP_ID", "com.culturedcode.ThingsMac")
USER_AGENT = os.environ.get("THINGS_USER_AGENT", "ThingsMac/31001504mas (x86_64; OS X 14.0.0)")
SCHEMA_VERSION = os.environ.get("THINGS_SCHEMA_VERSION", "301")

HEADERS = {
    "Accept": "application/json",
    "Accept-Charset": "UTF-8",
    "Accept-Language": "en-gb",
    "User-Agent": USER_AGENT,
    "Schema": SCHEMA_VERSION,
    "Content-Type": "application/json; charset=UTF-8",
    "App-Id": APP_ID,
    "App-Instance-Id": f"-{APP_ID}",
    "Push-Priority": "5",
}

TIMEOUT = 30
MAX_PAGES = 400  # generous ceiling; the journal is replayed once

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-amitgrupper-Desktop-Klaus"
    "/e9b31edc-ff16-4afa-ab96-531b09d2ce48/scratchpad"
)


def _redact(value: str | None, keep: int = 4) -> str:
    """Show only the first few characters of a sensitive value."""
    if not value:
        return "<empty>"
    return f"{value[:keep]}…({len(value)} chars)"


def _credentials() -> tuple[str, str]:
    email = os.environ.get("THINGS_EMAIL", "").strip()
    password = os.environ.get("THINGS_PASSWORD", "")
    if not email or not password:
        sys.exit(
            "THINGS_EMAIL and THINGS_PASSWORD must be set in .env.\n"
            "These are your Things Cloud account credentials "
            "(the same ones you'd use to sign in to Things Cloud)."
        )
    return email, password


# ------------------------------------------------------------------ #
# Protocol calls (read-only)                                          #
# ------------------------------------------------------------------ #

def login(session: requests.Session, email: str, password: str) -> dict:
    """GET the account record, which carries the history key."""
    resp = session.get(
        f"{API_BASE}/account/{quote(email, safe='')}",
        headers={**HEADERS, "Authorization": f"Password {quote(password, safe=chr(39))}"},
        timeout=TIMEOUT,
    )
    if resp.status_code in (401, 403):
        sys.exit(f"Things Cloud rejected the credentials (HTTP {resp.status_code}).")
    if not resp.ok:
        sys.exit(f"Login failed: HTTP {resp.status_code} — {resp.text[:300]}")
    return resp.json()


def new_session(session: requests.Session, email: str, password: str) -> dict:
    """POST for a shared session, which carries the current head index."""
    payload = json.dumps({"ep": {"e": email, "p": password}}).encode("utf-8")
    token = base64.b64encode(payload).decode("utf-8")
    resp = session.post(
        LOGIN_URL,
        headers={**HEADERS, "Authorization": f"B64SON {token}"},
        timeout=TIMEOUT,
    )
    if not resp.ok:
        print(f"  ! getT3SharedSession failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return {}
    return resp.json()


def fetch_page(session: requests.Session, history_key: str, start_index: int) -> dict:
    """GET one page of journal updates starting at ``start_index``."""
    resp = session.get(
        f"{API_BASE}/history/{history_key}/items",
        headers=HEADERS,
        params={"start-index": str(start_index)},
        timeout=TIMEOUT,
    )
    if not resp.ok:
        sys.exit(f"Fetch failed at index {start_index}: HTTP {resp.status_code} — {resp.text[:300]}")
    return resp.json()


def replay_journal(session: requests.Session, history_key: str) -> tuple[list[dict], dict]:
    """Replay the whole journal from index 0. Returns (updates, last envelope)."""
    items: list[dict] = []
    cursor = 0
    head = 0
    envelope: dict = {}

    for page in range(MAX_PAGES):
        envelope = fetch_page(session, history_key, cursor)

        if page == 0:
            print(f"  envelope keys: {sorted(envelope.keys())}")

        batch = envelope.get("items") or []
        head = envelope.get("current-item-index", head)
        items.extend(batch)
        print(f"  page {page + 1}: start-index={cursor} -> {len(batch)} elements (head {head})")

        if not batch:
            break
        # The cursor advances by the page length. `current-item-index` is the HEAD,
        # and each response is capped — using the head as the cursor silently skips
        # every element between the end of this page and the head.
        cursor += len(batch)
        if cursor >= head:
            break
    else:
        print(f"  ! hit MAX_PAGES ({MAX_PAGES}) — journal may be truncated")

    return items, envelope


# ------------------------------------------------------------------ #
# Schema analysis                                                     #
# ------------------------------------------------------------------ #

def flatten(items: list[dict]) -> list[tuple[str, int, str, dict]]:
    """Flatten journal pages into ordered (uuid, op, entity_class, payload) tuples.

    Each element of ``items`` is a dict mapping one or more UUIDs to
    ``{"t": <op>, "e": <entity class>, "p": <payload>}``.  A single element can
    batch up to ~90 entities, so this is a nested flatten, not a simple map.
    """
    out: list[tuple[str, int, str, dict]] = []
    for element in items:
        if not isinstance(element, dict):
            continue
        for uuid, rec in element.items():
            if not isinstance(rec, dict):
                continue
            out.append((uuid, rec.get("t"), rec.get("e") or "UNKNOWN", rec.get("p") or {}))
    return out


OP_CREATE, OP_EDIT, OP_DELETE = 0, 1, 2


def materialize(flat: list[tuple[str, int, str, dict]]) -> dict[str, dict]:
    """Fold the journal into current state: uuid -> merged payload.

    Operation codes (``t``):
        0  create — payload is complete
        1  edit   — payload is a sparse delta, merge over what's there
        2  delete — drop the entity entirely

    Honouring ``t == 2`` is **mandatory**.  Treating deletes as merges inflated
    this account from 52 open to-dos to 251, resurrecting long-deleted projects
    and areas.  ``Tombstone2`` entities are a second, independent delete signal
    (``dloid`` names the doomed UUID) and must also be applied.
    """
    state: dict[str, dict] = {}
    for uuid, op, entity_class, payload in flat:
        if op == OP_DELETE:
            state.pop(uuid, None)
            continue
        if uuid not in state:
            state[uuid] = {"_class": entity_class}
        state[uuid].update(payload)

    for uuid, _op, entity_class, payload in flat:
        if entity_class == "Tombstone2":
            state.pop(payload.get("dloid"), None)

    return state


def analyze(flat: list[tuple[str, int, str, dict]], state: dict[str, dict]) -> None:
    """Print the observed schema: op codes, entity classes, keys, value samples."""
    print("\n" + "=" * 72)
    print("OBSERVED SCHEMA")
    print("=" * 72)

    ops = Counter(op for _, op, _, _ in flat)
    print(f"\nOperation codes ('t'): {dict(ops)}  (0=create, 1=edit, 2=DELETE)")
    print(f"Entity classes ('e')  : {dict(Counter(cls for _, _, cls, _ in flat))}")
    print(f"\nJournal records: {len(flat)}   Live entities after deletes: {len(state)}")
    print(f"  ({ops.get(OP_DELETE, 0)} delete records applied — ignoring these "
          f"resurrects deleted data)")

    by_class: dict[str, list[dict]] = defaultdict(list)
    for payload in state.values():
        by_class[payload.get("_class", "UNKNOWN")].append(payload)

    print(f"Materialized by class: { {k: len(v) for k, v in sorted(by_class.items())} }")

    # Counts to eyeball against the running app — the gate on this whole spike.
    tasks = by_class.get("Task6", [])
    live = [t for t in tasks if t.get("ss") == 0 and not t.get("tr") and t.get("tp") == 0]
    bucket = {0: "Inbox", 1: "Anytime", 2: "Someday"}
    print("\n  --- verify against the app ---")
    print(f"  Open to-dos : {len(live)}")
    for code, name in bucket.items():
        print(f"    {name:<8}: {sum(1 for t in live if t.get('st') == code)}")
    # Computed outside the f-string: a multi-line expression inside one is
    # PEP 701 syntax, valid on 3.12+ but a SyntaxError on the 3.11 that
    # production and CI run.
    projects = [
        t.get("tt") for t in tasks
        if t.get("tp") == 1 and t.get("ss") == 0 and not t.get("tr")
    ]
    print(f"  Projects    : {projects}")
    print(f"  Areas       : {[a.get('tt') for a in by_class.get('Area3', [])]}")
    print(f"  Tags        : {[t.get('tt') for t in by_class.get('Tag4', [])]}")

    for cls, entities in sorted(by_class.items()):
        print("\n" + "-" * 72)
        print(f"CLASS: {cls}   ({len(entities)} entities)")
        print("-" * 72)

        key_counts = Counter()
        samples: dict[str, list] = defaultdict(list)
        for ent in entities:
            for key, value in ent.items():
                key_counts[key] += 1
                if len(samples[key]) < 4 and value not in samples[key]:
                    samples[key].append(value)

        for key, count in key_counts.most_common():
            sample_repr = ", ".join(repr(s)[:60] for s in samples[key][:3])
            pct = 100 * count / len(entities)
            print(f"  {key:<8} {count:>5}/{len(entities)} ({pct:5.1f}%)  e.g. {sample_repr}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", action="store_true", help="write raw JSON to scratchpad")
    args = parser.parse_args()

    email, password = _credentials()
    session = requests.Session()

    print("=" * 72)
    print("THINGS CLOUD PROTOCOL SPIKE — read-only")
    print("=" * 72)

    print(f"\n[1] Login as {email} …")
    info = login(session, email, password)
    history_key = info.get("history-key", "")
    print(f"  status               : {info.get('status')}")
    print(f"  history-key          : {_redact(history_key, 8)}")
    print(f"  maildrop-email       : {_redact(info.get('maildrop-email'), 6)}")
    print(f"  SLA-version-accepted : {info.get('SLA-version-accepted')}")
    print(f"  issues               : {info.get('issues')}")
    known = {"status", "history-key", "maildrop-email", "SLA-version-accepted", "issues"}
    print(f"  other keys           : {sorted(k for k in info if k not in known)}")

    if not history_key:
        sys.exit("No history-key in the account response — cannot continue.")

    print("\n[2] Requesting shared session …")
    sess = new_session(session, email, password)
    if sess:
        print(f"  headIndex : {sess.get('headIndex')}")
        print(f"  secret    : {_redact(sess.get('historyKeySessionSecret'), 6)}")

    print("\n[3] Replaying journal from index 0 …")
    items, envelope = replay_journal(session, history_key)
    print(f"  journal elements: {len(items)}")
    print(f"  schema version  : {envelope.get('schema')}")

    flat = flatten(items)
    state = materialize(flat)
    analyze(flat, state)

    if args.dump:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        raw_path = SCRATCH / "things_journal_raw.json"
        state_path = SCRATCH / "things_state_materialized.json"
        raw_path.write_text(json.dumps(items, indent=2, ensure_ascii=False))
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        print(f"\n[4] Raw journal      -> {raw_path}")
        print(f"    Materialized state -> {state_path}")
        print("    (these contain real task text — scratchpad only, never commit)")

    print("\nDone. No writes were performed.")


if __name__ == "__main__":
    main()
