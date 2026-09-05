"""The transaction ledger API: append-only, reversal-corrected, anchored.

`ledger_events` is the tax position's paper trail — nothing is ever updated
or deleted (schema triggers refuse it), so a mistake is corrected by
appending a reversal row and, optionally, the corrected entry in the same
transaction. Every event must anchor to something the owner can find it by;
the schema permits an unanchored row, the API does not.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field, model_validator

Conn = psycopg.Connection[dict[str, Any]]

LedgerCategory = Literal[
    "rent",
    "other_income",
    "late_fee",
    "deposit_received",
    "deposit_returned",
    "mortgage_interest",
    "mortgage_principal",
    "property_tax",
    "insurance",
    "repairs",
    "capital_improvement",
    "utilities",
    "management_fee",
    "hoa",
    "legal_professional",
    "advertising",
    "supplies",
    "travel",
    "acquisition_cost",
    "disposition_cost",
    "owner_contribution",
    "owner_distribution",
]


class LedgerEntryIn(BaseModel):
    occurred_on: dt.date
    category: LedgerCategory
    # Signed: inflow positive, outflow negative. Never zero — a zero-dollar
    # event records nothing and pollutes every rollup it touches.
    amount: Decimal = Field(decimal_places=2, max_digits=18)
    memo: str | None = None
    counterparty: str | None = None
    is_capital: bool | None = None
    capitalisation_rationale: str | None = None
    property_id: str | None = None
    unit_id: str | None = None
    lease_id: str | None = None
    entity_id: str | None = None
    # The source document behind the entry (a bank statement, a receipt) —
    # attached at insert because the ledger refuses UPDATE forever after.
    document_id: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> LedgerEntryIn:
        if self.amount == 0:
            raise ValueError("amount must not be zero")
        if not (self.property_id or self.unit_id or self.lease_id or self.entity_id):
            raise ValueError("a ledger event must anchor to a property, unit, lease, or entity")
        if self.is_capital is True and not self.capitalisation_rationale:
            raise ValueError(
                "capital spending explains itself: capitalisation_rationale is required"
            )
        return self


class LedgerEventOut(BaseModel):
    event_uuid: str
    occurred_on: dt.date
    recorded_at: dt.datetime
    category: str
    amount: Decimal
    memo: str | None
    counterparty: str | None
    is_capital: bool | None
    capitalisation_rationale: str | None
    property_id: str | None
    unit_id: str | None
    lease_id: str | None
    entity_id: str | None
    reverses_event_uuid: str | None
    # True once a later row reverses this one; reversed pairs cancel in every
    # rollup but stay visible — the position is reconstructible as taken.
    reversed: bool


class LedgerRegister(BaseModel):
    events: list[LedgerEventOut]
    total_in: Decimal
    total_out: Decimal
    net: Decimal


class ReversalIn(BaseModel):
    memo: str | None = None
    corrected: LedgerEntryIn | None = None


class ReversalOut(BaseModel):
    reversal: LedgerEventOut
    corrected: LedgerEventOut | None


class AlreadyReversed(Exception):
    pass


def refresh_charge_status(conn: Conn, charge_id: str) -> None:
    """Recompute a charge's status from its allocations — in BOTH directions
    (a reversal can un-pay a charge), never touching waived/written_off — or
    superseded, which is history and must never be resurrected to 'due'."""
    conn.execute(
        """
        UPDATE rent_charges c SET status = CASE
          WHEN c.status IN ('waived', 'written_off', 'superseded') THEN c.status
          WHEN coalesce((SELECT sum(a.amount) FROM rent_receipt_allocations a
                         WHERE a.charge_id = c.id), 0) >= c.amount THEN 'paid'
          WHEN coalesce((SELECT sum(a.amount) FROM rent_receipt_allocations a
                         WHERE a.charge_id = c.id), 0) > 0 THEN 'partially_paid'
          ELSE 'due' END
        WHERE c.id = %s
        """,
        (charge_id,),
    )


class UnknownEvent(Exception):
    pass


_COLUMNS = """
  e.event_uuid::text, e.occurred_on, e.recorded_at, e.category::text,
  e.amount, e.memo, e.counterparty, e.is_capital, e.capitalisation_rationale,
  e.property_id::text, e.unit_id::text, e.lease_id::text, e.entity_id::text,
  original.event_uuid::text AS reverses_event_uuid,
  EXISTS (SELECT 1 FROM ledger_events r WHERE r.reverses_event_id = e.id)
    AS reversed
"""


def _row_out(row: dict[str, Any]) -> LedgerEventOut:
    return LedgerEventOut(**row)


def append_event(conn: Conn, entry: LedgerEntryIn) -> LedgerEventOut:
    row = conn.execute(
        """
        INSERT INTO ledger_events
          (occurred_on, category, amount, memo, counterparty, is_capital,
           capitalisation_rationale, property_id, unit_id, lease_id, entity_id,
           document_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            entry.occurred_on,
            entry.category,
            entry.amount,
            entry.memo,
            entry.counterparty,
            entry.is_capital,
            entry.capitalisation_rationale,
            entry.property_id,
            entry.unit_id,
            entry.lease_id,
            entry.entity_id,
            entry.document_id,
        ),
    ).fetchone()
    return read_event_by_id(conn, row["id"])  # type: ignore[index]


def read_event_by_id(conn: Conn, event_id: int) -> LedgerEventOut:
    row = conn.execute(
        f"""
        SELECT {_COLUMNS}
        FROM ledger_events e
        LEFT JOIN ledger_events original ON original.id = e.reverses_event_id
        WHERE e.id = %s
        """,  # noqa: S608 - only the module constant _COLUMNS is interpolated
        (event_id,),
    ).fetchone()
    return _row_out(row)  # type: ignore[arg-type]


def reverse_event(conn: Conn, event_uuid: str, body: ReversalIn) -> ReversalOut:
    original = conn.execute(
        "SELECT * FROM ledger_events WHERE event_uuid = %s", (event_uuid,)
    ).fetchone()
    if original is None:
        raise UnknownEvent(event_uuid)
    existing = conn.execute(
        "SELECT 1 AS x FROM ledger_events WHERE reverses_event_id = %s",
        (original["id"],),
    ).fetchone()
    if existing is not None:
        raise AlreadyReversed(event_uuid)
    # Money the reversed event had applied to rent charges is released, and
    # every touched charge's status is recomputed — a reversed receipt must
    # not leave rent looking paid.
    released = conn.execute(
        "DELETE FROM rent_receipt_allocations WHERE ledger_event_id = %s RETURNING charge_id::text",
        (original["id"],),
    ).fetchall()
    for row_released in released:
        refresh_charge_status(conn, row_released["charge_id"])
    try:
        return _insert_reversal(conn, original, body, event_uuid)
    except psycopg.errors.UniqueViolation as error:
        # The race loser: another reversal committed between our check and
        # insert; one_reversal_per_event turned corruption into a conflict.
        raise AlreadyReversed(event_uuid) from error


def _insert_reversal(
    conn: Conn, original: dict[str, Any], body: ReversalIn, event_uuid: str
) -> ReversalOut:
    rationale = original["capitalisation_rationale"]
    if original["is_capital"] is True:
        rationale = f"reversal: {rationale}"
    row = conn.execute(
        """
        INSERT INTO ledger_events
          (occurred_on, category, amount, memo, counterparty, is_capital,
           capitalisation_rationale, property_id, unit_id, lease_id, entity_id,
           reverses_event_id, document_id, provenance_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            original["occurred_on"],
            original["category"],
            -original["amount"],
            body.memo or f"reversal of {event_uuid}",
            original["counterparty"],
            original["is_capital"],
            rationale,
            original["property_id"],
            original["unit_id"],
            original["lease_id"],
            original["entity_id"],
            original["id"],
            original["document_id"],
            original["provenance_id"],
        ),
    ).fetchone()  # one_reversal_per_event backs the check above at the schema
    reversal = read_event_by_id(conn, row["id"])  # type: ignore[index]
    corrected = append_event(conn, body.corrected) if body.corrected else None
    return ReversalOut(reversal=reversal, corrected=corrected)


def register(
    conn: Conn,
    *,
    property_id: str | None = None,
    category: str | None = None,
    occurred_from: dt.date | None = None,
    occurred_to: dt.date | None = None,
    limit: int = 200,
) -> LedgerRegister:
    rows = conn.execute(
        f"""
        SELECT {_COLUMNS}
        FROM ledger_events e
        LEFT JOIN ledger_events original ON original.id = e.reverses_event_id
        WHERE (%(property_id)s::uuid IS NULL OR e.property_id = %(property_id)s)
          AND (%(category)s::ledger_category IS NULL OR e.category = %(category)s)
          AND (%(occurred_from)s::date IS NULL OR e.occurred_on >= %(occurred_from)s)
          AND (%(occurred_to)s::date IS NULL OR e.occurred_on <= %(occurred_to)s)
        ORDER BY e.occurred_on DESC, e.id DESC
        LIMIT %(limit)s
        """,  # noqa: S608 - only the module constant _COLUMNS is interpolated
        {
            "property_id": property_id,
            "category": category,
            "occurred_from": occurred_from,
            "occurred_to": occurred_to,
            "limit": limit,
        },
    ).fetchall()
    # Totals over the SAME filter without the limit: the register page may be
    # truncated, the arithmetic never is. Reversal PAIRS are excluded from the
    # gross in/out figures (a mistake and its correction are not cash flow);
    # net is computed over everything, and the pairs cancel there.
    totals = conn.execute(
        """
        SELECT
          coalesce(sum(amount) FILTER (WHERE amount > 0
            AND reverses_event_id IS NULL
            AND NOT EXISTS (SELECT 1 FROM ledger_events r
                            WHERE r.reverses_event_id = e.id)), 0) AS total_in,
          coalesce(sum(amount) FILTER (WHERE amount < 0
            AND reverses_event_id IS NULL
            AND NOT EXISTS (SELECT 1 FROM ledger_events r
                            WHERE r.reverses_event_id = e.id)), 0) AS total_out,
          coalesce(sum(amount), 0) AS net
        FROM ledger_events e
        WHERE (%(property_id)s::uuid IS NULL OR e.property_id = %(property_id)s)
          AND (%(category)s::ledger_category IS NULL OR e.category = %(category)s)
          AND (%(occurred_from)s::date IS NULL OR e.occurred_on >= %(occurred_from)s)
          AND (%(occurred_to)s::date IS NULL OR e.occurred_on <= %(occurred_to)s)
        """,
        {
            "property_id": property_id,
            "category": category,
            "occurred_from": occurred_from,
            "occurred_to": occurred_to,
        },
    ).fetchone()
    return LedgerRegister(
        events=[_row_out(row) for row in rows],
        **totals,  # type: ignore[arg-type]
    )
