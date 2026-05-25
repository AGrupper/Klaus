"""Database tool — read-only PostgreSQL query executor for Master Shifu.

Provides direct access for executing time-series analytical queries (e.g. rolling averages,
moving HRV baselines, and Pace-to-HR correlations) directly within the database.
Enforces read-only constraints at the query parsing level for security.
"""
from __future__ import annotations

import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(Exception):
    """Raised when the database connection fails or queries time out."""


def query_health_database(sql_query: str) -> list[dict] | str:
    """Execute a read-only SELECT or CTE SQL query against the Postgres database.

    Args:
        sql_query: The SQL query string to run. Must be a read-only SELECT or WITH statement.

    Returns:
        A list of dictionaries representing row records, or an error string.

    Raises:
        DatabaseUnavailableError: If connection or execution fails.
    """
    # 1. Enforce strict read-only queries
    normalized_query = sql_query.strip().lower()
    if not (normalized_query.startswith("select") or normalized_query.startswith("with")):
        logger.warning(f"Blocked write attempt or invalid query structure: {sql_query}")
        return "Error: Security block. Only read-only SELECT or CTE (WITH) statements are permitted."

    # Prevent potential nested writes inside a CTE
    blocked_keywords = ["insert ", "update ", "delete ", "drop ", "truncate ", "alter ", "create "]
    if any(keyword in normalized_query for keyword in blocked_keywords):
        logger.warning(f"Blocked suspicious keyword in query: {sql_query}")
        return "Error: Security block. DDL or write keywords detected in the query."

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
        
        # RealDictCursor parses row records as clean key-value dictionaries
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            logger.info("Executing analytical query...")
            cur.execute(sql_query)
            records = cur.fetchall()
            
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
