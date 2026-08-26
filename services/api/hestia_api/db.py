"""Connections and the audit write path.

One connection per request, context-managed; every mutating endpoint records
what it did in audit_log with the request's correlation id, in the SAME
transaction as the change — an audit trail that can miss writes is a story,
not a trail.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import psycopg
from psycopg.rows import dict_row


def open_connection(url: str) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(url, row_factory=dict_row)


def connection_for(url: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """FastAPI dependency: yield a connection, commit on success, roll back on
    any exception, always close."""
    conn = open_connection(url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_audit(
    conn: psycopg.Connection[dict[str, Any]],
    *,
    actor: str,
    action: str,
    request_id: str,
    table_name: str | None = None,
    record_id: str | None = None,
    after_value: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (actor, action, table_name, record_id, after_value, request_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            actor,
            action,
            table_name,
            record_id,
            json.dumps(after_value, default=str) if after_value is not None else None,
            request_id,
        ),
    )
