"""Tests for Phase 19 schema migration in scripts/ingest_garmin_zip.py.

Covers SCHEMA-01/02/03:
- 3 new activities columns (training_load, perceived_exertion, feel)
- 4 new daily_biometrics columns (vo2_max, training_load_acute,
  training_load_chronic, acwr)
- setup_schema idempotency (calls execute twice without raising)

Uses sys.modules MagicMock for psycopg2 + psycopg2.extras so the script
can be loaded without real psycopg2 installed (test infra independence
per tests/test_firestore_db.py pattern).
"""

import importlib.util
import sys
from unittest.mock import MagicMock

import pytest  # noqa: F401  -- pytest discovery marker


def _import_module():
    """Load scripts/ingest_garmin_zip.py by path with psycopg2 mocked."""
    if "psycopg2" not in sys.modules:
        psy = MagicMock()
        psy.extras = MagicMock()
        psy.extras.execute_values = MagicMock()
        psy.tz = MagicMock()
        psy.tz.FixedOffset = MagicMock(return_value=None)
        sys.modules["psycopg2"] = psy
        sys.modules["psycopg2.extras"] = psy.extras
    spec = importlib.util.spec_from_file_location(
        "ingest_garmin_zip", "scripts/ingest_garmin_zip.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_activities_has_phase19_columns():
    mod = _import_module()
    for col_clause in [
        "ALTER TABLE activities ADD COLUMN IF NOT EXISTS training_load REAL",
        "ALTER TABLE activities ADD COLUMN IF NOT EXISTS perceived_exertion SMALLINT",
        "ALTER TABLE activities ADD COLUMN IF NOT EXISTS feel SMALLINT",
    ]:
        assert col_clause in mod.SCHEMA_DDL, f"missing: {col_clause}"


def test_daily_biometrics_has_phase19_columns():
    mod = _import_module()
    for col_clause in [
        "ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS vo2_max REAL",
        "ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_acute REAL",
        "ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_chronic REAL",
        "ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS acwr REAL",
    ]:
        assert col_clause in mod.SCHEMA_DDL, f"missing: {col_clause}"


def test_setup_schema_idempotent():
    mod = _import_module()
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    mod.setup_schema(conn)
    mod.setup_schema(conn)
    assert cur.execute.call_count == 2
    args1, _ = cur.execute.call_args_list[0]
    args2, _ = cur.execute.call_args_list[1]
    assert args1 == args2
