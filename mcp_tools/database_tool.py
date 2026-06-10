"""Database tool — read-only PostgreSQL query executor for Master Shifu.

Provides direct access for executing time-series analytical queries (e.g. rolling averages,
moving HRV baselines, and Pace-to-HR correlations) directly within the database.
Enforces read-only constraints at the query parsing level for security.
"""
from __future__ import annotations

import logging
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Word-boundary match for write/DDL keywords. WHY \b (not "delete " with a trailing
# space): a substring check is trivially evaded with a tab/newline/comment after the
# keyword (e.g. "delete\tfrom"), so it must match the token regardless of the following
# whitespace. This is defense-in-depth on top of the DB-level read-only session below.
_WRITE_KEYWORDS_RE = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|"
    r"merge|comment|copy|call|do|vacuum|reindex|refresh)\b"
)


class DatabaseUnavailableError(Exception):
    """Raised when the database connection fails or queries time out."""


# Hard ceiling on returned rows. An unbounded time-series query (e.g. every
# heart-rate sample for a year) would otherwise flood the LLM context. When
# the cap trips, the result ends with a sentinel record
# {"_truncated": True, "_max_rows": N} — shape-preserving, so callers that
# branch on isinstance(rows, list) keep working and just skip the sentinel.
MAX_ROWS = 200


def query_health_database(sql_query: str, max_rows: int = MAX_ROWS) -> list[dict] | str:
    """Execute a read-only SELECT or CTE SQL query against the Postgres database.

    Defense in depth (the parse checks are a fast fail; the read-only DB session is
    the actual guarantee — a write slipping past the string checks still fails at the
    database with "cannot execute … in a read-only transaction"):
      1. Must start with SELECT or WITH.
      2. No write/DDL keyword anywhere (word-boundary match, whitespace-evasion proof).
      3. Single statement only (no ``;``-chained second statement).
      4. The connection runs ``SET SESSION CHARACTERISTICS … READ ONLY``.

    Args:
        sql_query: The SQL query string to run. Must be a read-only SELECT or WITH statement.
        max_rows:  Row cap (default MAX_ROWS). Results beyond the cap are dropped
                   and a {"_truncated": True, "_max_rows": N} sentinel record is
                   appended so the caller can tell the result was cut off.

    Returns:
        A list of dictionaries representing row records, or an error string.

    Raises:
        DatabaseUnavailableError: If connection or execution fails.
    """
    # 1. Enforce strict read-only queries
    normalized_query = sql_query.strip().lower()
    if not (normalized_query.startswith("select") or normalized_query.startswith("with")):
        logger.warning("Blocked non-SELECT/CTE query (len=%d)", len(sql_query))
        return "Error: Security block. Only read-only SELECT or CTE (WITH) statements are permitted."

    # 2. Block write/DDL keywords anywhere (catches nested writes inside a CTE and
    #    second statements). Word-boundary so "delete\tfrom" can't slip past a space check.
    if _WRITE_KEYWORDS_RE.search(normalized_query):
        logger.warning("Blocked write/DDL keyword in query (len=%d)", len(sql_query))
        return "Error: Security block. DDL or write keywords detected in the query."

    # 3. Reject multi-statement input — a chained ";delete…" must never reach execute().
    #    Strip a single trailing ';' first so a normal "SELECT … ;" is still allowed.
    if ";" in normalized_query.rstrip().rstrip(";"):
        logger.warning("Blocked multi-statement query (len=%d)", len(sql_query))
        return "Error: Security block. Only a single statement is permitted."

    conn_str = os.environ.get("PG_CONNECTION_STRING") or os.environ.get("DATABASE_URL")
    conn = None
    try:
        if conn_str:
            conn = psycopg2.connect(conn_str, connect_timeout=5)
        else:
            host = os.environ.get("PGHOST", "localhost")
            port = os.environ.get("PGPORT", "5432")
            user = os.environ.get("PGUSER", "postgres")
            password = os.environ.get("PGPASSWORD", "")
            database = os.environ.get("PGDATABASE", "klaus-postgres")
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=5  # Tight timeout for fast response
            )

        # DB-level read-only guarantee. WHY: the string checks above are a fast fail,
        # but the connection itself running read-only means any write that slips past
        # them (or a future parser gap) is rejected by Postgres with "cannot execute
        # … in a read-only transaction". autocommit so no write-transaction is opened.
        conn.set_session(readonly=True, autocommit=True)

        # RealDictCursor parses row records as clean key-value dictionaries
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            logger.info("Executing analytical query...")
            cur.execute(sql_query)
            # Fetch one extra row so we can tell "exactly max_rows" apart
            # from "more rows were available" without pulling the full set.
            records = cur.fetchmany(max_rows + 1)
            truncated = len(records) > max_rows
            if truncated:
                records = records[:max_rows]
                logger.warning(
                    "Query returned more than %d rows — result truncated.", max_rows
                )

            # Convert decimal/numeric types and date objects to standard JSON-compatible floats/strings
            serializable_records = []
            for record in records:
                clean_record = {}
                for k, v in record.items():
                    if hasattr(v, "isoformat"):
                        clean_record[k] = v.isoformat()
                    elif hasattr(v, "to_eng_string") or isinstance(v, (int, float)) or v is None:
                        clean_record[k] = float(v) if hasattr(v, "to_eng_string") else v
                    else:
                        clean_record[k] = str(v)
                serializable_records.append(clean_record)

            if truncated:
                serializable_records.append(
                    {"_truncated": True, "_max_rows": max_rows}
                )
            return serializable_records

    except psycopg2.Error as e:
        error_msg = f"Database query failed: {e}"
        logger.error(error_msg, exc_info=True)
        return f"Error executing query: {str(e)}"
        
    except Exception as e:
        error_msg = f"Unexpected database error: {e}"
        logger.error(error_msg, exc_info=True)
        raise DatabaseUnavailableError(error_msg) from e
        
    finally:
        if conn:
            conn.close()
