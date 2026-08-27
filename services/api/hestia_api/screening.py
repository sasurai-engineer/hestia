"""Screening decisions and the notice a denial owes.

The FCRA obliges a notice, not a warehouse. Nothing here stores a score, a
record, or a bureau reason code — only what was decided, when, whether a
consumer report drove it, and when the notice went out. The obligation is
derived in the database from those facts so it cannot drift from them.

The authority is 15 U.S.C. 1681m(a) (FCRA s.615(a)): a user who takes adverse
action with respect to a consumer, based in whole or in part on a consumer
report, must notify that consumer. The statute sets no day count, so this
module never invents one — the duty is dated to the decision, which is when it
attaches, and the deadline says so.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

Conn = psycopg.Connection[dict[str, Any]]

ADVERSE_ACTION_CITATION = (
    "FCRA s.615(a), 15 U.S.C. 1681m(a) — a user taking adverse action based in "
    "whole or in part on a consumer report must notify the consumer. The "
    "statute sets no day count, so the duty is dated to the decision."
)

# What the letter must contain, from the statute itself. Enumerated server-side
# because the browser displays what it is told; it does not know the law.
NOTICE_CONTENTS: tuple[dict[str, str], ...] = (
    {
        "requirement": "State the adverse action taken",
        "citation": "15 U.S.C. 1681m(a)",
    },
    {
        "requirement": (
            "Give the name, address and telephone number of the consumer "
            "reporting agency that furnished the report, including a toll-free "
            "number if the agency compiles nationwide files"
        ),
        "citation": "15 U.S.C. 1681m(a)(3)",
    },
    {
        "requirement": (
            "State that the reporting agency did not make the decision and "
            "cannot give the specific reasons for it"
        ),
        "citation": "15 U.S.C. 1681m(a)(4)(A)",
    },
    {
        "requirement": (
            "Tell the consumer of their right to a free copy of the report "
            "from that agency within sixty days"
        ),
        "citation": "15 U.S.C. 1681m(a)(4)(B), 1681j(b)",
    },
    {
        "requirement": (
            "Tell the consumer of their right to dispute the accuracy or "
            "completeness of any information in the report"
        ),
        "citation": "15 U.S.C. 1681m(a)(4)(B), 1681i",
    },
)


class UnknownResident(Exception):
    pass


class UnknownProperty(Exception):
    pass


class UnknownScreening(Exception):
    pass


class AlreadyDecided(Exception):
    """A decision is made once; changing it would rewrite why someone was
    refused a home."""


class NoticeNotOwed(Exception):
    """Only an adverse decision a report drove owes a notice."""


class NoticeAlreadySent(Exception):
    pass


Decision = Literal["approved", "conditional", "denied", "withdrawn"]


class ScreeningIn(BaseModel):
    resident_id: uuid.UUID
    property_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    requested_on: dt.date | None = None
    provider: str = Field(default="manual", min_length=1, max_length=80)
    notes: str | None = None


class DecisionIn(BaseModel):
    decision: Decision
    decided_on: dt.date | None = None
    # The owner's own words. Never a bureau reason code.
    decision_basis: str | None = None
    based_on_consumer_report: bool = False


class NoticeIn(BaseModel):
    sent_on: dt.date | None = None


class ScreeningOut(BaseModel):
    id: str
    resident_id: str
    resident_name: str
    property_id: str
    property_label: str
    unit_id: str | None
    unit_label: str | None
    requested_on: dt.date
    provider: str
    decision: str
    decided_on: dt.date | None
    decision_basis: str | None
    based_on_consumer_report: bool
    adverse_action_required: bool
    adverse_action_sent_on: dt.date | None
    notes: str | None
    # Present exactly when a notice is owed and unsent — the checklist is the
    # answer to "what do I have to say in the letter", not decoration.
    notice_contents: list[dict[str, str]]
    citation: str | None


def _read(conn: Conn, screening_id: str) -> ScreeningOut:
    row = conn.execute(
        """
        SELECT s.id::text, s.resident_id::text, r.full_name AS resident_name,
               s.property_id::text, p.label AS property_label,
               s.unit_id::text, u.label AS unit_label,
               s.requested_on, s.provider, s.decision::text AS decision,
               s.decided_on, s.decision_basis, s.based_on_consumer_report,
               s.adverse_action_required, s.adverse_action_sent_on, s.notes
        FROM screening_requests s
        JOIN residents r ON r.id = s.resident_id
        JOIN properties p ON p.id = s.property_id
        LEFT JOIN units u ON u.id = s.unit_id
        WHERE s.id = %s
        """,
        (screening_id,),
    ).fetchone()
    if row is None:
        raise UnknownScreening(screening_id)
    owed = row["adverse_action_required"] and row["adverse_action_sent_on"] is None
    return ScreeningOut(
        **row,
        notice_contents=[dict(item) for item in NOTICE_CONTENTS] if owed else [],
        citation=ADVERSE_ACTION_CITATION if row["adverse_action_required"] else None,
    )


def create(conn: Conn, body: ScreeningIn) -> ScreeningOut:
    resident = conn.execute(
        "SELECT id::text FROM residents WHERE id = %s", (body.resident_id,)
    ).fetchone()
    if resident is None:
        raise UnknownResident(str(body.resident_id))
    prop = conn.execute(
        "SELECT id::text FROM properties WHERE id = %s", (body.property_id,)
    ).fetchone()
    if prop is None:
        raise UnknownProperty(str(body.property_id))
    row = conn.execute(
        """
        INSERT INTO screening_requests
          (resident_id, property_id, unit_id, requested_on, provider, notes)
        VALUES (%s, %s, %s, coalesce(%s, CURRENT_DATE), %s, %s)
        RETURNING id::text
        """,
        (
            body.resident_id,
            body.property_id,
            body.unit_id,
            body.requested_on,
            body.provider,
            body.notes,
        ),
    ).fetchone()
    return _read(conn, row["id"])


def decide(conn: Conn, screening_id: str, body: DecisionIn) -> ScreeningOut:
    """One decision, recorded once. A screening decision is the reason someone
    did or did not get a home; re-deciding it would rewrite that record."""
    current = conn.execute(
        "SELECT decision::text AS decision FROM screening_requests WHERE id = %s FOR UPDATE",
        (screening_id,),
    ).fetchone()
    if current is None:
        raise UnknownScreening(screening_id)
    if current["decision"] != "pending":
        raise AlreadyDecided(current["decision"])
    conn.execute(
        """
        UPDATE screening_requests
        SET decision = %s, decided_on = coalesce(%s, CURRENT_DATE),
            decision_basis = %s, based_on_consumer_report = %s
        WHERE id = %s
        """,
        (
            body.decision,
            body.decided_on,
            body.decision_basis,
            body.based_on_consumer_report,
            screening_id,
        ),
    )
    return _read(conn, screening_id)


def record_notice(conn: Conn, screening_id: str, body: NoticeIn) -> ScreeningOut:
    """Recording the notice resolves the deadline that demanded it."""
    row = conn.execute(
        """
        SELECT adverse_action_required, adverse_action_sent_on, decided_on
        FROM screening_requests WHERE id = %s FOR UPDATE
        """,
        (screening_id,),
    ).fetchone()
    if row is None:
        raise UnknownScreening(screening_id)
    if not row["adverse_action_required"]:
        raise NoticeNotOwed(screening_id)
    if row["adverse_action_sent_on"] is not None:
        raise NoticeAlreadySent(str(row["adverse_action_sent_on"]))
    sent_on = body.sent_on or dt.date.today()
    conn.execute(
        "UPDATE screening_requests SET adverse_action_sent_on = %s WHERE id = %s",
        (sent_on, screening_id),
    )
    # The resident's own summary field, which 003 has carried all along.
    conn.execute(
        """
        UPDATE residents SET adverse_action_sent_on = %s
        WHERE id = (SELECT resident_id FROM screening_requests WHERE id = %s)
        """,
        (sent_on, screening_id),
    )
    conn.execute(
        """
        UPDATE deadlines SET status = 'done', completed_on = %s
        WHERE screening_request_id = %s AND status = 'upcoming'
        """,
        (sent_on, screening_id),
    )
    return _read(conn, screening_id)


def read(conn: Conn, screening_id: str) -> ScreeningOut:
    return _read(conn, screening_id)


def list_requests(
    conn: Conn,
    *,
    resident_id: str | None = None,
    property_id: str | None = None,
    notice_owed: bool = False,
) -> list[ScreeningOut]:
    rows = conn.execute(
        """
        SELECT id::text FROM screening_requests
        WHERE (%(resident_id)s::uuid IS NULL OR resident_id = %(resident_id)s::uuid)
          AND (%(property_id)s::uuid IS NULL OR property_id = %(property_id)s::uuid)
          AND (NOT %(notice_owed)s
               OR (adverse_action_required AND adverse_action_sent_on IS NULL))
        ORDER BY requested_on DESC, id
        """,
        {
            "resident_id": resident_id,
            "property_id": property_id,
            "notice_owed": notice_owed,
        },
    ).fetchall()
    return [_read(conn, row["id"]) for row in rows]
