#!/usr/bin/env python3
"""Build or verify deterministic upload ZIPs for repository Claude skills."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "claude" / "skills"
DIST_ROOT = ROOT / "claude" / "dist"
SKILLS = (
    "klaus-live-agent",
    "klaus-morning-review",
    "klaus-nightly-review",
    "klaus-weekly-review",
)
FILES = ("SKILL.md", "VERSION")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_bytes(skill_dir: Path) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for filename in FILES:
            data = (skill_dir / filename).read_bytes()
            archive_path = f"{skill_dir.name}/{filename}"
            info = zipfile.ZipInfo(archive_path, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()


def _expected() -> tuple[dict[str, bytes], bytes]:
    artifacts: dict[str, bytes] = {}
    manifest_items = []
    versions = set()
    for name in SKILLS:
        source = SOURCE_ROOT / name
        version = (source / "VERSION").read_text(encoding="utf-8").strip()
        versions.add(version)
        artifact_name = f"{name}-{version}.zip"
        artifact = _archive_bytes(source)
        artifacts[artifact_name] = artifact
        source_digest = _sha256(b"".join((source / item).read_bytes() for item in FILES))
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
