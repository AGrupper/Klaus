# tests/test_database_tool.py
"""Security tests for the read-only analytical DB tool (WS4).

The string checks are fast-fail; the read-only DB session is the real guarantee.
These tests cover both: the parse guards (no DB needed — they return before connecting)
and that a valid query opens a read-only session."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_tools.database_tool import MAX_ROWS, query_health_database


# ---------------------------------------------------------------------------
# Parse-level guards — return before any DB connection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_query", [
    "DROP TABLE daily_biometrics",
    "delete from meals",
    "UPDATE meals SET calories = 0",
    "insert into meals values (1)",
    "TRUNCATE meals",
    "ALTER TABLE meals ADD COLUMN x int",
    "GRANT ALL ON meals TO public",
])
def test_blocks_non_readonly_statements(bad_query):
    result = query_health_database(bad_query)
    assert isinstance(result, str) and "Security block" in result


def test_blocks_write_keyword_nested_in_cte():
    """A CTE that starts with WITH but hides a write must be blocked."""
    q = "WITH x AS (DELETE FROM meals RETURNING *) SELECT * FROM x"
    result = query_health_database(q)
    assert "Security block" in result


def test_blocks_whitespace_evasion():
    """'delete\\tfrom' must not slip past a naive trailing-space keyword check."""
    q = "SELECT 1;delete\tfrom meals"
    result = query_health_database(q)
    assert "Security block" in result


def test_blocks_multi_statement():
    """A chained second statement is rejected even if both are SELECTs."""
    q = "SELECT 1; SELECT 2"
    result = query_health_database(q)
    assert "Security block" in result and "single statement" in result.lower()


# ---------------------------------------------------------------------------
# Valid query — opens a read-only session
# ---------------------------------------------------------------------------

def _mock_conn(rows):
    conn = MagicMock(name="conn")
    cur = MagicMock(name="cursor")
    # The tool fetches max_rows + 1 via fetchmany; honour the size argument.
    cur.fetchmany.side_effect = lambda size: rows[:size]
    cur_ctx = MagicMock()
    cur_ctx.__enter__.return_value = cur
    cur_ctx.__exit__.return_value = False
    conn.cursor.return_value = cur_ctx
    return conn


def test_valid_select_opens_readonly_session(monkeypatch):
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://u:p@h/db")
    conn = _mock_conn([{"avg_hrv": 58.0}])
    with patch("mcp_tools.database_tool.psycopg2.connect", return_value=conn):
        result = query_health_database("SELECT avg(hrv) AS avg_hrv FROM daily_biometrics")
    # The DB-level guarantee: the session is set read-only before executing.
    conn.set_session.assert_called_once_with(readonly=True, autocommit=True)
    assert result == [{"avg_hrv": 58.0}]


def test_trailing_semicolon_is_allowed(monkeypatch):
    """A single statement with a trailing ';' is fine (not multi-statement)."""
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://u:p@h/db")
    conn = _mock_conn([{"n": 1}])
    with patch("mcp_tools.database_tool.psycopg2.connect", return_value=conn):
        result = query_health_database("SELECT 1 AS n;")
    assert result == [{"n": 1}]
    conn.set_session.assert_called_once_with(readonly=True, autocommit=True)


# ---------------------------------------------------------------------------
# Row cap — truncation sentinel
# ---------------------------------------------------------------------------

def test_truncates_at_max_rows_with_sentinel(monkeypatch):
    """More rows than the cap → exactly max_rows data rows + a sentinel record."""
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://u:p@h/db")
    rows = [{"n": i} for i in range(MAX_ROWS + 50)]
    conn = _mock_conn(rows)
    with patch("mcp_tools.database_tool.psycopg2.connect", return_value=conn):
        result = query_health_database("SELECT n FROM samples")

    assert isinstance(result, list)
    assert len(result) == MAX_ROWS + 1
    assert result[-1] == {"_truncated": True, "_max_rows": MAX_ROWS}
    assert result[0] == {"n": 0}
    assert result[MAX_ROWS - 1] == {"n": MAX_ROWS - 1}


def test_under_cap_has_no_sentinel(monkeypatch):
    """A result within the cap is returned as-is — no sentinel appended."""
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://u:p@h/db")
    rows = [{"n": i} for i in range(3)]
    conn = _mock_conn(rows)
    with patch("mcp_tools.database_tool.psycopg2.connect", return_value=conn):
        result = query_health_database("SELECT n FROM samples")

    assert result == rows
    assert not any(r.get("_truncated") for r in result)


def test_exactly_max_rows_has_no_sentinel(monkeypatch):
    """Exactly max_rows rows → not truncated (the +1 probe row distinguishes)."""
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://u:p@h/db")
    rows = [{"n": i} for i in range(MAX_ROWS)]
    conn = _mock_conn(rows)
    with patch("mcp_tools.database_tool.psycopg2.connect", return_value=conn):
        result = query_health_database("SELECT n FROM samples")

    assert len(result) == MAX_ROWS
    assert not any(r.get("_truncated") for r in result)


def test_custom_max_rows_param(monkeypatch):
    """Callers can tighten the cap per query."""
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://u:p@h/db")
    rows = [{"n": i} for i in range(10)]
    conn = _mock_conn(rows)
    with patch("mcp_tools.database_tool.psycopg2.connect", return_value=conn):
        result = query_health_database("SELECT n FROM samples", max_rows=5)

    assert len(result) == 6
    assert result[-1] == {"_truncated": True, "_max_rows": 5}
