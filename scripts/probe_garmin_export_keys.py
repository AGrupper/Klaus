#!/usr/bin/env python3
"""Wave-0 probe — NOT for CI.

One-shot operator-run script that dumps Garmin export JSON keys to verify
the ASSUMED field names from RESEARCH §Garmin Export Field Map BEFORE the
parser code in scripts/ingest_garmin_zip.py is finalized.

Usage:
    python scripts/probe_garmin_export_keys.py /path/to/garmin_export.zip

Outputs:
    - First 5 keys of the first activity entry in *summaries.json
    - First 5 keys of the first UDS entry in *UDSFile.json
    - PRESENT/MISSING report for each of the 4 expected Phase 19 keys:
        activityTrainingLoad, directWorkoutRpe, directWorkoutFeel, vO2MaxValue

Exit code: always 0 (probe, not a CI gate). Phase 19 Pitfall 3 mitigation.
"""

import json
import sys
import tempfile
import zipfile
from pathlib import Path


EXPECTED_ACTIVITY_KEYS = ("activityTrainingLoad", "directWorkoutRpe", "directWorkoutFeel")
EXPECTED_UDS_KEYS = ("vO2MaxValue",)


def _dump_keys(label: str, path: Path) -> set[str]:
    """Load JSON at path, print first 5 keys, return full keyset."""
    print(f"=== {label} ({path.name}) ===")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"  ERROR reading {path}: {exc}")
        return set()
    if isinstance(data, list):
        if not data:
            print("  (empty list)")
            return set()
        first = data[0]
        if not isinstance(first, dict):
            print(f"  (first element is {type(first).__name__}, not dict)")
            return set()
        keys = list(first.keys())
    elif isinstance(data, dict):
        keys = list(data.keys())
    else:
        print(f"  (top-level is {type(data).__name__}, not list/dict)")
        return set()
    print(f"  first 5 keys: {keys[:5]}")
    return set(keys)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_garmin_export_keys.py /path/to/export.zip")
        print("(Wave-0 probe — NOT for CI)")
        return 0

    zip_path = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="garmin_probe_") as tmpdir:
        print(f"Extracting {zip_path} -> {tmpdir} ...")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmpdir)
        except Exception as exc:
            print(f"ERROR extracting zip: {exc}")
            return 0

        root = Path(tmpdir)
        activity_glob = list(root.glob("DI_CONNECT/DI-Connect-Fitness/*summaries.json"))
        uds_glob = list(root.glob("DI_CONNECT/DI-Connect-User/*UDSFile.json"))

        activity_keys: set[str] = set()
        uds_keys: set[str] = set()

        if activity_glob:
            activity_keys = _dump_keys("ACTIVITIES", activity_glob[0])
        else:
            print("=== ACTIVITIES === no *summaries.json found")

        if uds_glob:
            uds_keys = _dump_keys("UDS", uds_glob[0])
        else:
            print("=== UDS === no *UDSFile.json found")

        print("=== EXPECTED KEY CHECK ===")
        for key in EXPECTED_ACTIVITY_KEYS:
            status = "PRESENT" if key in activity_keys else "MISSING"
            print(f"  activities.{key}: {status}")
        for key in EXPECTED_UDS_KEYS:
            status = "PRESENT" if key in uds_keys else "MISSING"
            print(f"  uds.{key}: {status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
