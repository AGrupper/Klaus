"""Export autonomous tick_logs from Firestore + mint tick-brain eval fixtures.

Usage:
    # Dump tick logs + write a curation digest (markdown) for a date range:
    python scripts/export_tick_logs.py export --start 2026-05-23 --end 2026-06-10
    python scripts/export_tick_logs.py export --days 7

    # Mint a labeled fixture from a previously exported tick:
    python scripts/export_tick_logs.py make-fixture --date 2026-06-03 --time 14:20 \
        --slug overdue-maya-3h --should-speak true --pattern "^overdue:.*" \
        [--trigger overdue] [--note "..."] [--force]

Background (AUTO-08)
--------------------
Every live autonomous tick persists its full ``situation_snapshot`` plus the
decision trail to ``tick_logs/{YYYY-MM-DD}/ticks/{HH:MM}`` (TickLogStore,
D-21). The tick-brain judgment eval (``evals/tick_brain/``) grows from those
real snapshots via the retroactive-labeling workflow in
``evals/tick_brain/README.md``. This script is that workflow's tooling:

``export``
    Pulls each day's ticks (TickLogStore.ticks_for_date) plus the day's
    outreach_log entries, dumps raw JSON to ``evals/tick_brain/raw/``
    (gitignored) and renders ``digest.md`` — one row per tick with compact
    signals, the Layer-1 verdict, the send outcome, and FP?/FN? curation
    hints so suspected bad judgments are easy to spot.

``make-fixture``
    Reads a tick out of the raw dumps (no Firestore round-trip) and mints
    ``evals/tick_brain/fixtures/NNNN-slug.json``, enforcing the fixture
    schema that ``tests/test_evals.py`` validates. Pre-Phase-19 ticks get
    the missing meals/training/acwr keys backfilled with the same empty
    defaults production uses.

WARNING 8 (see evals/tick_brain/README.md): a due-followup-only snapshot must
be labeled ``should_speak=false`` — followups are sent by a dedicated Layer-2
path BEFORE triage (D-13), so tick-brain escalating too would double-send.
``make-fixture`` refuses ``--should-speak true`` on such ticks without
``--force``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(str(_REPO_ROOT / ".env"), override=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_RAW_DIR = _REPO_ROOT / "evals" / "tick_brain" / "raw"
_FIXTURES_DIR = _REPO_ROOT / "evals" / "tick_brain" / "fixtures"

_VALID_TRIGGER_TYPES = {"overdue", "gap", "silence", "followup", "quiet"}
_REQUIRED_TOP_KEYS = {"id", "captured_at", "situation_snapshot", "trigger_type", "ground_truth"}
_REQUIRED_SNAPSHOT_KEYS = {
    "calendar", "ticktick_overdue", "unread_email_count", "due_followups",
    "hours_since_contact", "recent_journal_digest", "self_state",
    "today_outreach_log", "now_context",
    "meals_since_last_tick", "training_status", "acwr",
}
# Production fallbacks for ticks logged before the Phase-19 deploy added these
# keys to gather_situation — identical to core/autonomous.py's own defaults so
# the rendered triage prompt stays faithful.
_PHASE19_BACKFILL = {
    "meals_since_last_tick": [],
    "training_status": {},
    "acwr": {"acute": None, "chronic": None, "ratio": None},
}

# FN? heuristic: same unresolved overdue ids visible this many consecutive
# non-sent rows means the signal "sat there" long enough to question silence.
_FN_CONSECUTIVE_OVERDUE_ROWS = 3
_FN_SILENCE_HOURS = 8.0
_FP_MARGINAL_HSC = 4.0


# ---------------------------------------------------------------------------
# Pure helpers — offline-testable, no Firestore
# ---------------------------------------------------------------------------

def _iter_dates(start: str, end: str) -> list[str]:
    """Inclusive YYYY-MM-DD range."""
    d, stop = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while d <= stop:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _layer1_verdict(decision: dict) -> dict | None:
    """Pull the {"layer1": verdict} entry out of the decision trail, if any."""
    for entry in decision.get("trail") or []:
        if isinstance(entry, dict) and "layer1" in entry:
            return entry["layer1"]
    return None


def _shipped_topic(decision: dict) -> str:
    for entry in decision.get("trail") or []:
        if isinstance(entry, dict) and "shipped" in entry:
            return entry["shipped"]
    return ""


def _compact_signals(snapshot: dict) -> str:
    """One-glance signal summary: ov=2 fu=0 hsc=4.5 cal=1 meals=0 [outlog=1]."""
    hsc = snapshot.get("hours_since_contact")
    parts = [
        f"ov={len(snapshot.get('ticktick_overdue') or [])}",
        f"fu={len(snapshot.get('due_followups') or [])}",
        f"hsc={'?' if hsc is None else round(hsc, 1)}",
        f"cal={len(snapshot.get('calendar') or [])}",
        f"meals={len(snapshot.get('meals_since_last_tick') or [])}",
    ]
    outlog = snapshot.get("today_outreach_log") or []
    if outlog:
        parts.append(f"outlog={len(outlog)}")
    return " ".join(parts)


def _verdict_cell(decision: dict) -> str:
    """Render the Layer-1 outcome for a digest row."""
    if decision.get("skipped") == "empty":
        return "skipped:empty"
    trail = decision.get("trail") or []
    if "layer1_exception" in trail:
        return "ERR layer1_exception"
    verdict = _layer1_verdict(decision)
    if verdict is None:
        return "(no layer1)"
    if verdict.get("reason") in ("parse_failure", "llm_error"):
        return f"ERR {verdict['reason']}"
    reason = (verdict.get("reason") or "").strip()
    if len(reason) > 60:
        reason = reason[:57] + "..."
    if verdict.get("should_act"):
        return f"ACT {verdict.get('topic_key') or '?'} — \"{reason}\""
    return f"no_act \"{reason}\""


def _sent_cell(decision: dict) -> str:
    if decision.get("sent"):
        topic = _shipped_topic(decision)
        return f"yes {topic}".strip()
    if "send_failed" in (decision.get("trail") or []):
        return "send_failed"
    return "-"


def _topic_prefix(topic_key: str) -> str:
    return (topic_key or "").split(":", 1)[0]


def _flag(tick: dict, consecutive_overdue_rows: int) -> str:
    """Curation hint, not a label: FP? = questionable send, FN? = questionable
    silence. Heuristics only — every flagged row still needs human judgment."""
    decision = tick.get("decision_trail") or {}
    snapshot = tick.get("situation_snapshot") or {}
    verdict = _layer1_verdict(decision) or {}

    if decision.get("sent"):
        hsc = snapshot.get("hours_since_contact")
        marginal = (
            not (snapshot.get("ticktick_overdue") or [])
            and not (snapshot.get("due_followups") or [])
            and (hsc is None or hsc < _FP_MARGINAL_HSC)
            and not (snapshot.get("meals_since_last_tick") or [])
        )
        shipped = _shipped_topic(decision) or verdict.get("topic_key") or ""
        repeatish = _topic_prefix(shipped) in {
            _topic_prefix(t) for t in (snapshot.get("today_outreach_log") or [])
        }
        if marginal or repeatish:
            return "FP?"
        return ""

    if decision.get("skipped") == "empty":
        return ""

    hsc = snapshot.get("hours_since_contact")
    if hsc is not None and hsc >= _FN_SILENCE_HOURS:
        return "FN?"
    if consecutive_overdue_rows >= _FN_CONSECUTIVE_OVERDUE_ROWS:
        return "FN?"
    return ""


def _digest_rows(ticks: list[dict]) -> list[dict]:
    """Compute one digest row per tick, carrying the day-level consecutive
    unresolved-overdue state that powers the FN? hint."""
    rows = []
    streak_ids: frozenset = frozenset()
    streak_len = 0
    for tick in ticks:
        decision = tick.get("decision_trail") or {}
        snapshot = tick.get("situation_snapshot") or {}
        overdue_ids = frozenset(
            t.get("id") for t in (snapshot.get("ticktick_overdue") or [])
            if isinstance(t, dict)
        )
        if decision.get("sent") or not overdue_ids:
            streak_ids, streak_len = frozenset(), 0
        elif overdue_ids == streak_ids:
            streak_len += 1
        else:
            streak_ids, streak_len = overdue_ids, 1
        rows.append({
            "time": tick.get("time", "?"),
            "signals": _compact_signals(snapshot),
            "verdict": _verdict_cell(decision),
            "sent": _sent_cell(decision),
            "flag": _flag(tick, streak_len),
        })
    return rows


def _render_day_table(date_str: str, ticks: list[dict],
                      outreach_entries: list[dict]) -> str:
    """Markdown digest section for one day."""
    rows = _digest_rows(ticks)
    n = len(ticks)
    n_skip = sum(1 for t in ticks if (t.get("decision_trail") or {}).get("skipped") == "empty")
    n_act = sum(1 for t in ticks
                if (_layer1_verdict(t.get("decision_trail") or {}) or {}).get("should_act"))
    sent_topics = [e.get("topic_key", "?") for e in outreach_entries]
    sent_desc = f"{len(sent_topics)} sent" + (f": {', '.join(sent_topics)}" if sent_topics else "")
    lines = [
        f"## {date_str}  ({n} ticks, {n_skip} empty-skip, {n_act} L1-act, {sent_desc})",
        "",
        "| Time | Signals | L1 verdict | Sent | Flag |",
        "|------|---------|------------|------|------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['time']} | {r['signals']} | {r['verdict']} | {r['sent']} | {r['flag']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _infer_trigger(snapshot: dict) -> str:
    """Best-effort trigger_type inference; 'gap' is schedule-semantic and can
    only come from --trigger. Printed at mint time for curator confirmation."""
    if snapshot.get("due_followups"):
        return "followup"
    if snapshot.get("ticktick_overdue"):
        return "overdue"
    hsc = snapshot.get("hours_since_contact")
    if hsc is not None and hsc >= _FN_SILENCE_HOURS:
        return "silence"
    return "quiet"


def _next_fixture_number(fixtures_dir: Path) -> int:
    nums = []
    for p in fixtures_dir.glob("[0-9][0-9][0-9][0-9]-*.json"):
        nums.append(int(p.name[:4]))
    return max(nums, default=0) + 1


def _build_fixture(tick: dict, nnnn: int, slug: str, should_speak: bool,
                   pattern: str | None, trigger: str, note: str | None) -> dict:
    """Assemble a schema-complete fixture from an exported tick."""
    snapshot = dict(tick.get("situation_snapshot") or {})
    for key, default in _PHASE19_BACKFILL.items():
        snapshot.setdefault(key, json.loads(json.dumps(default)))
    captured_at = (
        (snapshot.get("now_context") or {}).get("now_iso")
        or tick.get("captured_at", "")
    )
    ground_truth: dict = {"should_speak": should_speak}
    if should_speak:
        ground_truth["topic_key_pattern"] = pattern
    if note:
        ground_truth["_note"] = note
    return {
        "id": f"{nnnn:04d}-{slug}",
        "captured_at": captured_at,
        "situation_snapshot": snapshot,
        "trigger_type": trigger,
        "ground_truth": ground_truth,
    }


def _validate_fixture(fixture: dict, expected_stem: str) -> list[str]:
    """Mirror tests/test_evals.py schema checks; returns error strings."""
    errors = []
    missing = _REQUIRED_TOP_KEYS - fixture.keys()
    if missing:
        errors.append(f"missing top-level keys: {sorted(missing)}")
    snap = fixture.get("situation_snapshot") or {}
    missing = _REQUIRED_SNAPSHOT_KEYS - snap.keys()
    if missing:
        errors.append(f"situation_snapshot missing keys: {sorted(missing)}")
    if fixture.get("trigger_type") not in _VALID_TRIGGER_TYPES:
        errors.append(f"invalid trigger_type {fixture.get('trigger_type')!r}")
    gt = fixture.get("ground_truth") or {}
    if not isinstance(gt.get("should_speak"), bool):
        errors.append("ground_truth.should_speak must be bool")
    if gt.get("should_speak"):
        pattern = gt.get("topic_key_pattern")
        if not pattern:
            errors.append("should_speak=true requires topic_key_pattern")
        else:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"topic_key_pattern does not compile: {exc}")
    if fixture.get("id") != expected_stem:
        errors.append(f"id {fixture.get('id')!r} != filename stem {expected_stem!r}")
    if not fixture.get("captured_at"):
        errors.append("captured_at is empty")
    return errors


# ---------------------------------------------------------------------------
# Subcommands — Firestore / filesystem side effects live here
# ---------------------------------------------------------------------------

def _cmd_export(args: argparse.Namespace) -> int:
    from memory.firestore_db import OutreachLogStore, TickLogStore

    if args.start and args.end:
        dates = _iter_dates(args.start, args.end)
    else:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        dates = _iter_dates((today - timedelta(days=args.days)).isoformat(),
                            today.isoformat())

    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    tls = TickLogStore(project_id, database)
    ols = OutreachLogStore(project_id, database)

    raw_dir = Path(args.out)
    raw_dir.mkdir(parents=True, exist_ok=True)

    digest_sections = ["# Tick-log curation digest", ""]
    total = 0
    for date_str in dates:
        ticks = tls.ticks_for_date(date_str)
        if not ticks:
            continue
        total += len(ticks)
        outreach = ols.get_today(date_str)
        dump_path = raw_dir / f"ticks-{date_str}.json"
        dump_path.write_text(
            json.dumps(ticks, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        section = _render_day_table(date_str, ticks, outreach)
        digest_sections.append(section)
        print(section)
        logger.info("%s: %d ticks -> %s", date_str, len(ticks), dump_path)

    digest_path = raw_dir / "digest.md"
    digest_path.write_text("\n".join(digest_sections), encoding="utf-8")
    print(f"\n{total} ticks across {len(dates)} dates. Digest: {digest_path}")
    return 0


def _cmd_make_fixture(args: argparse.Namespace) -> int:
    raw_path = Path(args.raw) / f"ticks-{args.date}.json"
    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found — run the export subcommand first.")
        return 1
    ticks = json.loads(raw_path.read_text(encoding="utf-8"))
    tick = next((t for t in ticks if t.get("time") == args.time), None)
    if tick is None:
        times = ", ".join(t.get("time", "?") for t in ticks)
        print(f"ERROR: no tick at {args.time} on {args.date}. Available: {times}")
        return 1

    snapshot = tick.get("situation_snapshot") or {}
    should_speak = args.should_speak == "true"

    # WARNING 8 guard (D-13): followups are sent by their own Layer-2 path
    # before triage — tick-brain's correct behavior on such snapshots is
    # silence. Labeling these true is the documented easy mislabel.
    if should_speak and snapshot.get("due_followups") and not args.force:
        print(
            "REFUSING: this snapshot has due_followups and --should-speak true.\n"
            "Per WARNING 8 (evals/tick_brain/README.md, 'What should_speak Means'),\n"
            "due-followup snapshots reach tick-brain with the followup already\n"
            "handled — the expected label is false. Re-run with --force only if\n"
            "a SEPARATE signal (overdue/gap/silence) justifies speaking."
        )
        return 1

    inferred = _infer_trigger(snapshot)
    trigger = args.trigger or inferred
    print(f"Inferred trigger: {inferred}" + (
        f" (overridden to: {trigger})" if args.trigger and args.trigger != inferred else ""
    ))

    fixtures_dir = Path(args.fixtures)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    nnnn = _next_fixture_number(fixtures_dir)
    fixture = _build_fixture(
        tick, nnnn, args.slug, should_speak, args.pattern, trigger, args.note,
    )
    out_path = fixtures_dir / f"{fixture['id']}.json"
    if out_path.exists():
        print(f"ERROR: {out_path} already exists — refusing to overwrite.")
        return 1

    errors = _validate_fixture(fixture, out_path.stem)
    if errors:
        print("ERROR: fixture failed validation:")
        for e in errors:
            print(f"  - {e}")
        return 1

    out_path.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_path}  (should_speak={should_speak}, trigger={trigger})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export tick_logs + mint tick-brain eval fixtures (AUTO-08).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_exp = sub.add_parser("export", help="Dump tick logs + curation digest.")
    p_exp.add_argument("--start", help="YYYY-MM-DD inclusive range start.")
    p_exp.add_argument("--end", help="YYYY-MM-DD inclusive range end.")
    p_exp.add_argument("--days", type=int, default=14,
                       help="Days back from today (ignored when --start/--end given).")
    p_exp.add_argument("--out", default=str(_DEFAULT_RAW_DIR),
                       help="Output dir for raw dumps + digest.md (gitignored).")
    p_exp.set_defaults(func=_cmd_export)

    p_fix = sub.add_parser("make-fixture", help="Mint a fixture from an exported tick.")
    p_fix.add_argument("--date", required=True, help="YYYY-MM-DD of the tick.")
    p_fix.add_argument("--time", required=True, help="HH:MM of the tick.")
    p_fix.add_argument("--slug", required=True, help="kebab-case fixture slug.")
    p_fix.add_argument("--should-speak", required=True, choices=["true", "false"])
    p_fix.add_argument("--pattern", help="topic_key regex (required when true).")
    p_fix.add_argument("--trigger", choices=sorted(_VALID_TRIGGER_TYPES),
                       help="Override the inferred trigger_type (gap needs this).")
    p_fix.add_argument("--note", help="Labeler note stored in ground_truth._note.")
    p_fix.add_argument("--force", action="store_true",
                       help="Override the WARNING-8 followup guard.")
    p_fix.add_argument("--raw", default=str(_DEFAULT_RAW_DIR),
                       help="Dir holding ticks-YYYY-MM-DD.json dumps.")
    p_fix.add_argument("--fixtures", default=str(_FIXTURES_DIR),
                       help="Fixtures output dir.")
    p_fix.set_defaults(func=_cmd_make_fixture)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
