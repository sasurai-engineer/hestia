"""Connections and the audit write path.

One connection per request, context-managed; every mutating endpoint records
what it did in audit_log with the request's correlation id, in the SAME
transaction as the change — an audit trail that can miss writes is a story,
not a trail.

WHEN the transaction settles is part of the contract: a response is a promise
about durable state, and a promise made before the commit is a promise made
before it is true. See connection_for below.
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
    any exception, always close.

    WHEN this exit code runs is part of the API's contract, and it is not the
    default. FastAPI keeps two exit stacks per request
    (fastapi.routing.request_response): a function stack that unwinds BEFORE
    the response is sent, and a request stack that unwinds after it. A
    yield-dependency lands on the late one unless its `Depends` carries
    `scope="function"`, which is why the `Conn` alias in app.py does.

    Without it the commit happens once the client already holds its 201, so a
    caller acting on the id it was just handed can get a 404 for a row that
    exists, and a form that re-reads after submitting can miss its own write.
    That was issue #83. tests/test_transaction_boundary.py holds the line.
    """
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
