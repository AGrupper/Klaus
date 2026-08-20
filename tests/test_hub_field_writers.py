"""Every Firestore field the Hub renders must have something that writes it.

The failure this exists to prevent: on 2026-08-11 the morning routine moved from
the in-repo Python cascade to Claude Routines. The cascade wrote `daily_note` as
a side effect on its way past; the replacement did not. Nothing raised, no test
failed, the routine kept publishing — and the Hub's coach note card sat on its
"coming after your morning briefing" placeholder for eight days before a human
noticed. The same cutover killed the profile's `bodyweight_kg` refresh, which is
still frozen (deliberately — see the SKIP note below).

A reader with no writer is the signature, and it is invisible from the read side:
`_today_coach_note` was correct the whole time. So the guard has to come from the
write side, which is what this module checks.

Design notes, because the obvious versions of this test do not work:

  - Checking that store WRITE METHODS have callers would not have caught it.
    `SelfStateStore.set()` was still called every night by the nightly branch;
    it was one FIELD inside the payload that vanished. The granularity has to be
    the field, not the method.
  - Deriving the field list from reads automatically is too noisy — `.get("x")`
    on an ordinary dict is everywhere in this codebase. The list below is
    curated on purpose, in the same spirit as PUBLIC_API_ROUTES in
    test_hub_auth_coverage: adding an entry is cheap, and each one carries the
    reason it matters.
  - Written fields ARE derived automatically, by AST rather than grep, so a
    payload key cannot be missed because of how the call was formatted.
"""
from __future__ import annotations

import ast
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]

# Application code only. Tests are excluded deliberately: a field written only by
# a test fixture is exactly the bug this looks for.
APP_DIRS = ("core", "interfaces", "mcp_tools", "memory", "scripts")

# Methods whose dict argument is a document payload.
WRITE_METHODS = frozenset({"set", "update", "patch", "create", "record", "append"})


# Firestore document fields the Hub renders, and what breaks when the writer goes
# away. Every entry must be written by production code somewhere.
HUB_RENDERED_FIELDS: dict[str, str] = {
    # config/self_state — the Today card's coach note (dead 2026-08-11..08-19).
    "daily_note": "Hub coach note text — written by publish_review's morning branch",
    "daily_note_date": "gates the note to today; a stale date blanks the card",
    "daily_note_at": "the 'written at' stamp shown beside the note",
    # config/self_state — Klaus's retained state, shown in Klaus's corner.
    "mood": "self-state shown in the Hub and fed to Claude",
    "current_focus": "self-state shown in the Hub and fed to Claude",
    "recent_context": "self-state shown in the Hub and fed to Claude",
    # users/amit — session revocation (D-02).
    "session_version": "bumped by /api/auth/revoke-all; a dead writer breaks sign-out-everywhere",
}

# Fields whose writer is known to be gone and deliberately NOT being restored.
# An entry here is a decision, not an oversight — which is the point of writing
# it down rather than leaving the field off the list entirely.
KNOWN_UNWRITTEN: dict[str, str] = {
    "bodyweight_kg": (
        "Garmin weigh-in sync died with the 2026-08-11 cutover "
        "(morning_briefing._sync_bodyweight_from_garmin). Amit chose not to restore it "
        "on 2026-08-20: he stopped logging food, so nothing downstream coaches on it. "
        "Frozen at the last synced value; treat as known-stale, not as a bug."
    ),
}


def _written_field_names() -> set[str]:
    """Every literal dict key passed to a store write, found via AST.

    Catches `store.set({"a": 1})`, `store.set({**base, "a": 1})` and keyword
    payloads alike. A key built dynamically cannot be seen — if that ever becomes
    the reason a field looks unwritten, write the field literally or move it to
    KNOWN_UNWRITTEN with a reason.
    """
    written: set[str] = set()

    def collect(node: ast.AST) -> None:
        for arg in list(getattr(node, "args", [])) + [
            kw.value for kw in getattr(node, "keywords", [])
        ]:
            if isinstance(arg, ast.Dict):
                for key in arg.keys:
                    # `None` is the key slot of a `**spread` — no literal to read.
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        written.add(key.value)

    for directory in APP_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in WRITE_METHODS:
                        collect(node)
    return written


def test_every_hub_rendered_field_has_a_writer():
    """The guard the coach-note regression needed and did not have."""
    written = _written_field_names()

    orphaned = sorted(
        f"{field} ({why})"
        for field, why in HUB_RENDERED_FIELDS.items()
        if field not in written
    )

    assert orphaned == [], (
        "these Hub fields are read but nothing writes them:\n  "
        + "\n  ".join(orphaned)
        + "\n\nA reader with no writer renders as stale or absent data forever, "
        "with nothing failing. Restore the write path, or — if the field is "
        "deliberately frozen — move it to KNOWN_UNWRITTEN with the reason."
    )


def test_the_ast_scan_actually_finds_writes():
    """Guard the guard: a scan that finds nothing would pass vacuously."""
    written = _written_field_names()

    assert len(written) > 50, f"only found {len(written)} written fields"
    # Two fields written through visibly different call shapes.
    assert "daily_note" in written, "publish_review's morning branch writes this"
    assert "session_version" in written, "/api/auth/revoke-all writes this"


def test_deliberately_frozen_fields_are_still_frozen():
    """KNOWN_UNWRITTEN is a decision log, so it must not silently go stale.

    If a writer comes back, the entry is now a lie about how the system behaves —
    delete it and move the field into HUB_RENDERED_FIELDS where it is enforced.
    """
    written = _written_field_names()

    revived = sorted(f for f in KNOWN_UNWRITTEN if f in written)

    assert revived == [], (
        f"{revived} now has a writer again — remove it from KNOWN_UNWRITTEN and "
        "add it to HUB_RENDERED_FIELDS so the writer is enforced from now on."
    )
