#!/usr/bin/env python3
"""Wave-0 probe — NOT for CI.

One-shot operator-run script that dumps Garmin export JSON keys to verify
the ASSUMED field names from RESEARCH §Garmin Export Field Map BEFORE the
parser code in scripts/ingest_garmin_zip.py is finalized.

Usage:
    python scripts/probe_garmin_export_keys.py /path/to/garmin_export.zip
    python scripts/probe_garmin_export_keys.py /path/to/unzipped_export_dir

Outputs:
    - Glob counts for each Phase 19 file class
    - First 5 keys of the first entry in each file class
    - PRESENT/MISSING report for each expected Phase 19 key

Expected keys (verified against real 2023-2026 Garmin export, 2026-05-27):
    - activities (DI-Connect-Fitness/*summarizedActivities.json, nested under
      "summarizedActivitiesExport"):
        activityTrainingLoad, workoutRpe, workoutFeel
    - metrics (DI-Connect-Metrics/MetricsMaxMetData_*.json):
        vo2MaxValue
    - UDS (DI-Connect-Aggregator/UDSFile_*.json):
        restingHeartRate (sanity check; UDS no longer carries VO2 directly)

Exit code: always 0 (probe, not a CI gate). Phase 19 Pitfall 3 mitigation.
"""

import json
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path


EXPECTED_ACTIVITY_KEYS = ("activityTrainingLoad", "workoutRpe", "workoutFeel")
EXPECTED_METRICS_KEYS = ("vo2MaxValue",)
EXPECTED_UDS_KEYS = ("restingHeartRate",)


def _peek_keys(label: str, path: Path, drill: str | None = None) -> set[str]:
    """Load JSON at path, print first 5 keys of first entry, return full keyset.

    If `drill` is given, the file is expected to be a list whose first element is
    a wrapper dict containing `drill` -> list of actual entries (used for the
    summarizedActivities export nested layout).
    """
    print(f"=== {label} ({path.name}) ===")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"  ERROR reading {path}: {exc}")
        return set()

    container = data
    if drill and isinstance(data, list) and data and isinstance(data[0], dict):
        inner = data[0].get(drill)
        if isinstance(inner, list):
            container = inner

    if isinstance(container, list):
        if not container:
            print("  (empty list)")
            return set()
        first = container[0]
        if not isinstance(first, dict):
            print(f"  (first element is {type(first).__name__}, not dict)")
            return set()
        keys = list(first.keys())
    elif isinstance(container, dict):
        keys = list(container.keys())
    else:
        print(f"  (top-level is {type(container).__name__}, not list/dict)")
        return set()
    print(f"  first 5 keys: {keys[:5]}")
    return set(keys)


@contextmanager
def _resolve_root(path: str):
    """Yield a Path pointing at the DI_CONNECT-containing root.

    Accepts either a .zip (extracted into a temp dir) or an already-unzipped
    directory path.
    """
    p = Path(path)
    if p.is_dir():
        yield p
        return
    if p.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory(prefix="garmin_probe_") as tmpdir:
            print(f"Extracting {p} -> {tmpdir} ...")
            with zipfile.ZipFile(p, "r") as zf:
                zf.extractall(tmpdir)
            yield Path(tmpdir)
            return
    raise ValueError(f"path is neither a .zip nor a directory: {path}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_garmin_export_keys.py /path/to/export.zip-or-dir")
        print("(Wave-0 probe — NOT for CI)")
        return 0

    arg = sys.argv[1]
    try:
        ctx = _resolve_root(arg)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 0

    with ctx as root:
        activity_glob = sorted(
            root.glob("DI_CONNECT/DI-Connect-Fitness/*summarizedActivities.json")
        )
        metrics_glob = sorted(
            root.glob("DI_CONNECT/DI-Connect-Metrics/MetricsMaxMetData_*.json")
        )
        uds_glob = sorted(root.glob("DI_CONNECT/DI-Connect-Aggregator/UDSFile*.json"))

        print(f"activity files: {len(activity_glob)}")
        print(f"metrics MaxMet files: {len(metrics_glob)}")
        print(f"UDS files: {len(uds_glob)}")

        activity_keys: set[str] = set()
        metrics_keys: set[str] = set()
        uds_keys: set[str] = set()

        if activity_glob:
            activity_keys = _peek_keys(
                "ACTIVITIES", activity_glob[0], drill="summarizedActivitiesExport"
            )
        else:
            print("=== ACTIVITIES === no *summarizedActivities.json found")

        if metrics_glob:
            metrics_keys = _peek_keys("METRICS-MAXMET", metrics_glob[0])
        else:
            print("=== METRICS-MAXMET === no MetricsMaxMetData_*.json found")

        if uds_glob:
            uds_keys = _peek_keys("UDS", uds_glob[0])
        else:
            print("=== UDS === no UDSFile*.json found")

        print("=== EXPECTED KEY CHECK ===")
        for key in EXPECTED_ACTIVITY_KEYS:
            status = "PRESENT" if key in activity_keys else "MISSING"
            print(f"  activities.{key}: {status}")
        for key in EXPECTED_METRICS_KEYS:
            status = "PRESENT" if key in metrics_keys else "MISSING"
            print(f"  metrics.{key}: {status}")
        for key in EXPECTED_UDS_KEYS:
            status = "PRESENT" if key in uds_keys else "MISSING"
            print(f"  uds.{key}: {status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
