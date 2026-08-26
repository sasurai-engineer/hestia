"""Resolve a property's governing jurisdiction from what the owner typed.

Name-based and offline on purpose: an exact municipality match under the
state, disambiguated by county where US geography makes names collide
(Ohio's twenty Washington Townships), falling back to the state row, and to
None where no pack is loaded. The Census-FIPS resolve — which returns exactly
the fips_code keys the hierarchy carries — is the ingestion orchestrator's
upgrade path and never blocks a property from being created.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

Conn = psycopg.Connection[dict[str, Any]]


@dataclass(frozen=True)
class Resolved:
    jurisdiction_id: str | None
    level: str | None


def resolve(conn: Conn, *, state: str, city: str, county: str | None = None) -> Resolved:
    """The most specific jurisdiction the loaded packs can name for an address."""
    municipal = conn.execute(
        """
        SELECT j.id, parent.name AS county_name
        FROM jurisdictions j
        LEFT JOIN jurisdictions parent ON parent.id = j.parent_id
        WHERE j.level = 'municipality' AND j.state = %s AND j.name = %s
        """,
        (state, city),
    ).fetchall()
    if county is not None:
        municipal = [m for m in municipal if m["county_name"] == county]
    if len(municipal) == 1:
        return Resolved(jurisdiction_id=str(municipal[0]["id"]), level="municipality")
    # Zero matches falls through to the state row; more than one means the
    # name is ambiguous without a county and the state row is the honest
    # answer — a wrong municipality would attach the wrong rules.
    state_row = conn.execute(
        "SELECT id FROM jurisdictions WHERE level = 'state' AND state = %s",
        (state,),
    ).fetchone()
    if state_row is None:
        return Resolved(jurisdiction_id=None, level=None)
    return Resolved(jurisdiction_id=str(state_row["id"]), level="state")
