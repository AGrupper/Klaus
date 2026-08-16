#!/usr/bin/env python3
"""Build or verify deterministic upload ZIPs for repository Claude skills.

Skills share safety rules. The publication contract, shadow-mode restrictions
and untrusted-source handling were copy-pasted across the routine skills and had
already drifted — the untrusted-source rule existed in three different wordings,
which is how a safety rule quietly stops meaning the same thing.

Those blocks now live once under `claude/skills/_shared/` and are pulled in with

    <!-- INCLUDE: routine-contract -->

which this packager **expands inline** into the SKILL.md that goes into the ZIP.
Inline expansion is deliberate rather than shipping the shared files alongside:
a bundled reference file is loaded at the model's discretion, and a publication
contract that might not be read is not a contract. What Claude receives is one
self-contained SKILL.md; what a human edits is one copy of each rule.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "claude" / "skills"
SHARED_ROOT = SOURCE_ROOT / "_shared"
DIST_ROOT = ROOT / "claude" / "dist"
SKILLS = (
    "klaus-live-agent",
    "klaus-morning-review",
    "klaus-nightly-review",
    "klaus-weekly-review",
)
FILES = ("SKILL.md", "VERSION")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_INCLUDE_RE = re.compile(r"^[ \t]*<!-- INCLUDE: ([a-z0-9-]+) -->[ \t]*$", re.MULTILINE)


class SkillBuildError(RuntimeError):
    """Raised when a skill source cannot be rendered."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_skill(name: str) -> str:
    """Return a skill's SKILL.md with every shared include expanded inline.

    This is exactly the text uploaded to the Claude Project, so tests assert
    against it rather than against the source file — a rule that lives in a
    shared include is still a rule the skill ships.

    Args:
        name: Skill directory name, e.g. ``"klaus-nightly-review"``.

    Returns:
        str: Fully expanded SKILL.md text.

    Raises:
        SkillBuildError: If an include names a file that does not exist.
    """
    source = (SOURCE_ROOT / name / "SKILL.md").read_text(encoding="utf-8")

    def _expand(match: re.Match) -> str:
        shared = SHARED_ROOT / f"{match.group(1)}.md"
        if not shared.is_file():
            raise SkillBuildError(
                f"{name}/SKILL.md includes '{match.group(1)}', "
                f"but {shared.relative_to(ROOT)} does not exist"
            )
        return shared.read_text(encoding="utf-8").strip()

    return _INCLUDE_RE.sub(_expand, source)


def _skill_payload(name: str) -> dict[str, bytes]:
    """Return the exact file bytes shipped for one skill."""
    return {
        "SKILL.md": render_skill(name).encode("utf-8"),
        "VERSION": (SOURCE_ROOT / name / "VERSION").read_bytes(),
    }


def _archive_bytes(name: str, payload: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for filename in FILES:
            info = zipfile.ZipInfo(f"{name}/{filename}", ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload[filename])
    return output.getvalue()


def _expected() -> tuple[dict[str, bytes], bytes]:
    artifacts: dict[str, bytes] = {}
    manifest_items = []
    versions = set()
    for name in SKILLS:
        payload = _skill_payload(name)
        version = payload["VERSION"].decode("utf-8").strip()
        versions.add(version)
        artifact_name = f"{name}-{version}.zip"
        artifact = _archive_bytes(name, payload)
        artifacts[artifact_name] = artifact
        # Digest the rendered payload, not the raw sources: editing a shared
        # include changes what ships, so it must change the recorded hash.
        source_digest = _sha256(b"".join(payload[item] for item in FILES))
        manifest_items.append(
            {
                "name": name,
                "version": version,
                "artifact": artifact_name,
                "source_sha256": source_digest,
                "artifact_sha256": _sha256(artifact),
            }
        )
    if len(versions) != 1:
        raise ValueError(f"skill versions differ: {sorted(versions)}")
    manifest = json.dumps(
        {"schema_version": 1, "skill_version": versions.pop(), "skills": manifest_items},
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    return artifacts, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if artifacts differ")
    args = parser.parse_args()
    artifacts, manifest = _expected()
    expected = {**artifacts, "manifest.json": manifest}
    if args.check:
        drift = []
        for filename, data in expected.items():
            path = DIST_ROOT / filename
            if not path.is_file() or path.read_bytes() != data:
                drift.append(filename)
        unexpected = (
            {path.name for path in DIST_ROOT.iterdir()} - set(expected)
            if DIST_ROOT.exists()
            else set()
        )
        if drift or unexpected:
            print(f"Claude skill artifacts drifted: {sorted(drift + list(unexpected))}")
            return 1
        print("Claude skill artifacts match canonical sources.")
        return 0

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    for path in DIST_ROOT.glob("klaus-*.zip"):
        if path.name not in expected:
            path.unlink()
    for filename, data in expected.items():
        (DIST_ROOT / filename).write_bytes(data)
    print(f"Built {len(artifacts)} Claude skill ZIPs in {DIST_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
