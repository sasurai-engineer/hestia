"""Debt: recording the note, and splitting the payment it demands.

`debt_instruments` and `debt_payments` have carried full schema since module
003, and three consumers read them — the financials read model, the hold/sell
card, and the bank-import mortgage split. Until now nothing outside the test
suite could WRITE one, so an owner could not record their own mortgage and
every consumer read an empty table.

The split is not computed here. `hestia_sim.finance.amortization` produces the
schedule in cents and this module reports what it says: the engines compute,
this explains. A payment recorded without its split takes the engine's, to the
cent, for the period it belongs to — which is the same number the bank-import
mortgage split will suggest.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

import psycopg
from hestia_sim.finance import amortization
from pydantic import BaseModel, Field

from hestia_api import ledger as ledger_module

Conn = psycopg.Connection[dict[str, Any]]

CENTS = Decimal("100")

DebtKind = Literal[
    "conventional_mortgage",
    "portfolio_loan",
    "dscr_loan",
    "agency_multifamily",
    "bridge",
    "hard_money",
    "heloc",
    "seller_financing",
    "private_note",
]
AmortizationKind = Literal[
    "fully_amortizing", "interest_only", "balloon", "arm", "negative_amortizing"
]
PrepaymentKind = Literal[
    "none", "step_down", "flat_percent", "yield_maintenance", "defeasance", "lockout"
]


# The note's own rules, named so a refusal says which one bit.
DEBT_REFUSALS: dict[str, str] = {
    "principal_is_positive": "a note has to be for some money",
    "positive_term": "a note has to have a term",
    "amortization_at_least_term": (
        "the amortization period cannot be shorter than the term — a balloon "
        "amortizes over longer than it runs, never shorter"
    ),
    "arm_has_index": "an adjustable note has to say what it adjusts against",
    "lien_position_positive": "lien position counts from first",
}


class PayoffIn(BaseModel):
    paid_off_on: dt.date


class UnknownProperty(Exception):
    pass


class UnknownDebt(Exception):
    pass


class AlreadyPaidOff(Exception):
    pass


class DuplicatePayment(Exception):
    """One payment per date per note; a correction reverses, it does not overwrite."""


class ScheduleUnavailable(Exception):
    """The engine only amortizes a level-payment note."""


class DebtIn(BaseModel):
    property_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    lender: str | None = Field(default=None, max_length=200)
    kind: DebtKind = "conventional_mortgage"
    lien_position: int = Field(default=1, ge=1, le=9)

    original_principal: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    interest_rate: Decimal = Field(ge=0, lt=1, decimal_places=8, max_digits=9)
    amortization: AmortizationKind = "fully_amortizing"
    term_months: int = Field(gt=0, le=600)
    amortization_months: int | None = Field(default=None, gt=0, le=600)
    originated_on: dt.date
    first_payment_on: dt.date | None = None
    matures_on: dt.date | None = None

    rate_adjusts_on: dt.date | None = None
    rate_index: str | None = None
    rate_margin: Decimal | None = Field(default=None, ge=0, lt=1, decimal_places=8, max_digits=9)
    rate_cap_periodic: Decimal | None = Field(
        default=None, ge=0, lt=1, decimal_places=8, max_digits=9
    )
    rate_cap_lifetime: Decimal | None = Field(
        default=None, ge=0, lt=1, decimal_places=8, max_digits=9
    )

    prepayment: PrepaymentKind = "none"
    prepayment_terms: str | None = None
    is_recourse: bool = True
    has_due_on_sale: bool = True
    escrows_taxes: bool = False
    escrows_insurance: bool = False
    document_id: uuid.UUID | None = None


class PaymentIn(BaseModel):
    paid_on: dt.date
    # Leave the split out and the engine supplies it for the period this date
    # falls in. Supply it and what the lender actually applied is recorded.
    principal: Decimal | None = Field(default=None, ge=0, decimal_places=2, max_digits=18)
    interest: Decimal | None = Field(default=None, ge=0, decimal_places=2, max_digits=18)
    escrow: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2, max_digits=18)
    extra_principal: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2, max_digits=18)
    # Money that moved belongs in the ledger, split across the two categories
    # module 005 already carries.
    post_to_ledger: bool = True


class ScheduleRow(BaseModel):
    month: int
    payment: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal


class DebtOut(BaseModel):
    id: str
    property_id: str
    property_label: str
    entity_id: str | None
    lender: str | None
    kind: str
    lien_position: int
    original_principal: Decimal
    interest_rate: Decimal
    amortization: str
    term_months: int
    amortization_months: int | None
    originated_on: dt.date
    first_payment_on: dt.date | None
    matures_on: dt.date | None
    rate_adjusts_on: dt.date | None
    rate_index: str | None
    prepayment: str
    prepayment_terms: str | None
    is_recourse: bool
    has_due_on_sale: bool
    escrows_taxes: bool
    escrows_insurance: bool
    paid_off_on: dt.date | None
    document_id: str | None
    # Everything below is computed by the engine, never stored.
    scheduled_payment: Decimal | None
    payments_recorded: int
    principal_paid: Decimal
    interest_paid: Decimal


class ScheduleOut(BaseModel):
    debt_id: str
    scheduled_payment: Decimal
    total_interest: Decimal
    rows: list[ScheduleRow]
    # What the next payment owes, so a split never has to be guessed at.
    next_month: int | None
    next_interest: Decimal | None
    next_principal: Decimal | None
    citation: str


ENGINE_CITATION = (
    "level-payment amortization, hestia_sim.finance.amortization — the same "
    "schedule the hold/sell card and the bank-import split read"
)


def _schedule(row: dict[str, Any]) -> dict[str, Any]:
    """The engine's schedule for a note, in cents. Interest-only and negative
    amortization are different arithmetic and are not claimed here."""
    if row["amortization"] not in ("fully_amortizing", "balloon", "arm"):
        raise ScheduleUnavailable(row["amortization"])
    months = row["amortization_months"] or row["term_months"]
    return amortization(int(row["original_principal"] * CENTS), str(row["interest_rate"]), months)


def _payment_number(row: dict[str, Any], paid_on: dt.date) -> int:
    """Which scheduled payment a date belongs to, counting from the first."""
    start = row["first_payment_on"] or row["originated_on"]
    return (paid_on.year - start.year) * 12 + (paid_on.month - start.month) + 1


def _read(conn: Conn, debt_id: str) -> DebtOut:
    row = conn.execute(
        """
        SELECT d.id::text, d.property_id::text, p.label AS property_label,
               d.entity_id::text, d.lender, d.kind::text AS kind, d.lien_position,
               d.original_principal, d.interest_rate,
               d.amortization::text AS amortization, d.term_months,
               d.amortization_months, d.originated_on, d.first_payment_on,
               d.matures_on, d.rate_adjusts_on, d.rate_index,
               d.prepayment::text AS prepayment, d.prepayment_terms, d.is_recourse,
               d.has_due_on_sale, d.escrows_taxes, d.escrows_insurance,
               d.paid_off_on, d.document_id::text,
               (SELECT count(*) FROM debt_payments dp WHERE dp.debt_id = d.id)
                 AS payments_recorded,
               (SELECT coalesce(sum(dp.principal + dp.extra_principal), 0)
                  FROM debt_payments dp WHERE dp.debt_id = d.id) AS principal_paid,
               (SELECT coalesce(sum(dp.interest), 0) FROM debt_payments dp
                 WHERE dp.debt_id = d.id) AS interest_paid
        FROM debt_instruments d JOIN properties p ON p.id = d.property_id
        WHERE d.id = %s
        """,
        (debt_id,),
    ).fetchone()
    if row is None:
        raise UnknownDebt(debt_id)
    try:
        scheduled = Decimal(_schedule(row)["payment"]) / CENTS
    except ScheduleUnavailable:
        scheduled = None
    return DebtOut(**row, scheduled_payment=scheduled)


def create(conn: Conn, body: DebtIn) -> DebtOut:
    prop = conn.execute(
        "SELECT id::text, entity_id::text FROM properties WHERE id = %s",
        (body.property_id,),
    ).fetchone()
    if prop is None:
        raise UnknownProperty(str(body.property_id))
    row = conn.execute(
        """
        INSERT INTO debt_instruments
          (property_id, entity_id, lender, kind, lien_position, original_principal,
           interest_rate, amortization, term_months, amortization_months,
           originated_on, first_payment_on, matures_on, rate_adjusts_on, rate_index,
           rate_margin, rate_cap_periodic, rate_cap_lifetime, prepayment,
           prepayment_terms, is_recourse, has_due_on_sale, escrows_taxes,
           escrows_insurance, document_id)
        VALUES (%s, coalesce(%s::uuid, %s::uuid), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text
        """,
        (
            body.property_id,
            body.entity_id,
            prop["entity_id"],
            body.lender,
            body.kind,
            body.lien_position,
            body.original_principal,
            body.interest_rate,
            body.amortization,
            body.term_months,
            body.amortization_months,
            body.originated_on,
            body.first_payment_on,
            body.matures_on,
            body.rate_adjusts_on,
            body.rate_index,
            body.rate_margin,
            body.rate_cap_periodic,
            body.rate_cap_lifetime,
            body.prepayment,
            body.prepayment_terms,
            body.is_recourse,
            body.has_due_on_sale,
            body.escrows_taxes,
            body.escrows_insurance,
            body.document_id,
        ),
    ).fetchone()
    return _read(conn, row["id"])


def read(conn: Conn, debt_id: str) -> DebtOut:
    return _read(conn, debt_id)


def list_debts(
    conn: Conn, *, property_id: str | None = None, include_paid_off: bool = False
) -> list[DebtOut]:
    rows = conn.execute(
        """
        SELECT id::text FROM debt_instruments
        WHERE (%(property_id)s::uuid IS NULL OR property_id = %(property_id)s::uuid)
          AND (%(include_paid_off)s OR paid_off_on IS NULL)
        ORDER BY lien_position, originated_on
        """,
        {"property_id": property_id, "include_paid_off": include_paid_off},
    ).fetchall()
    return [_read(conn, row["id"]) for row in rows]


def schedule(conn: Conn, debt_id: str, *, as_of: dt.date) -> ScheduleOut:
    row = conn.execute(
        """
        SELECT id::text, original_principal, interest_rate,
               amortization::text AS amortization, term_months, amortization_months,
               originated_on, first_payment_on
        FROM debt_instruments WHERE id = %s
        """,
        (debt_id,),
    ).fetchone()
    if row is None:
        raise UnknownDebt(debt_id)
    computed = _schedule(row)
    rows = [
        ScheduleRow(
            month=entry["month"],
            payment=Decimal(entry["payment"]) / CENTS,
            interest=Decimal(entry["interest"]) / CENTS,
            principal=Decimal(entry["principal"]) / CENTS,
            balance=Decimal(entry["balance"]) / CENTS,
        )
        for entry in computed["rows"]
    ]
    number = _payment_number(row, as_of)
    upcoming = rows[number - 1] if 1 <= number <= len(rows) else None
    return ScheduleOut(
        debt_id=row["id"],
        scheduled_payment=Decimal(computed["payment"]) / CENTS,
        total_interest=Decimal(computed["total_interest"]) / CENTS,
        rows=rows,
        next_month=upcoming.month if upcoming else None,
        next_interest=upcoming.interest if upcoming else None,
        next_principal=upcoming.principal if upcoming else None,
        citation=ENGINE_CITATION,
    )


class PaymentOut(BaseModel):
    debt_id: str
    paid_on: dt.date
    principal: Decimal
    interest: Decimal
    escrow: Decimal
    extra_principal: Decimal
    balance_after: Decimal | None
    # Which schedule row supplied the split, when the caller did not.
    from_schedule_month: int | None
    ledger_event_uuids: list[str]


def record_payment(conn: Conn, debt_id: str, body: PaymentIn) -> PaymentOut:
    """One payment, its split, and the two ledger rows it becomes.

    Interest and principal are different lines on Schedule E — one is
    deductible and the other is equity — so a mortgage payment has never been
    one ledger row here, and this posts the pair the categories were made for.
    """
    row = conn.execute(
        """
        SELECT id::text, property_id::text, entity_id::text, lender, paid_off_on,
               original_principal, interest_rate, amortization::text AS amortization,
               term_months, amortization_months, originated_on, first_payment_on
        FROM debt_instruments WHERE id = %s FOR UPDATE
        """,
        (debt_id,),
    ).fetchone()
    if row is None:
        raise UnknownDebt(debt_id)
    if row["paid_off_on"] is not None:
        raise AlreadyPaidOff(str(row["paid_off_on"]))

    from_month: int | None = None
    principal = body.principal
    interest = body.interest
    if principal is None or interest is None:
        computed = _schedule(row)
        number = _payment_number(row, body.paid_on)
        if not 1 <= number <= len(computed["rows"]):
            raise ScheduleUnavailable(f"payment {number} is outside the schedule")
        entry = computed["rows"][number - 1]
        from_month = entry["month"]
        principal = Decimal(entry["principal"]) / CENTS if principal is None else principal
        interest = Decimal(entry["interest"]) / CENTS if interest is None else interest

    try:
        payment = conn.execute(
            """
            INSERT INTO debt_payments
              (debt_id, paid_on, principal, interest, escrow, extra_principal)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id::text
            """,
            (
                debt_id,
                body.paid_on,
                principal,
                interest,
                body.escrow,
                body.extra_principal,
            ),
        ).fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise DuplicatePayment(str(body.paid_on)) from error

    events: list[str] = []
    if body.post_to_ledger:
        for category, amount in (
            ("mortgage_interest", interest),
            ("mortgage_principal", principal + body.extra_principal),
        ):
            if amount <= 0:
                continue
            event = ledger_module.append_event(
                conn,
                ledger_module.LedgerEntryIn(
                    occurred_on=body.paid_on,
                    category=category,  # type: ignore[arg-type]
                    amount=-amount,
                    memo=f"{row['lender'] or 'note'} payment",
                    counterparty=row["lender"],
                    property_id=row["property_id"],
                    entity_id=row["entity_id"],
                ),
            )
            events.append(event.event_uuid)

    balance = conn.execute(
        """
        UPDATE debt_payments SET balance_after = %s WHERE id = %s
        RETURNING balance_after
        """,
        (
            _balance_after(conn, debt_id, row),
            payment["id"],
        ),
    ).fetchone()
    return PaymentOut(
        debt_id=debt_id,
        paid_on=body.paid_on,
        principal=principal,
        interest=interest,
        escrow=body.escrow,
        extra_principal=body.extra_principal,
        balance_after=balance["balance_after"],
        from_schedule_month=from_month,
        ledger_event_uuids=events,
    )


def _balance_after(conn: Conn, debt_id: str, row: dict[str, Any]) -> Decimal:
    """Original principal less every principal dollar recorded against it."""
    paid = conn.execute(
        "SELECT coalesce(sum(principal + extra_principal), 0) AS paid"
        " FROM debt_payments WHERE debt_id = %s",
        (debt_id,),
    ).fetchone()
    return max(Decimal("0"), row["original_principal"] - paid["paid"])


def pay_off(conn: Conn, debt_id: str, paid_off_on: dt.date) -> DebtOut:
    updated = conn.execute(
        """
        UPDATE debt_instruments SET paid_off_on = %s, updated_at = now()
        WHERE id = %s AND paid_off_on IS NULL RETURNING id::text
        """,
        (paid_off_on, debt_id),
    ).fetchone()
    if updated is None:
        existing = conn.execute(
            "SELECT paid_off_on FROM debt_instruments WHERE id = %s", (debt_id,)
        ).fetchone()
        if existing is None:
            raise UnknownDebt(debt_id)
        raise AlreadyPaidOff(str(existing["paid_off_on"]))
    return _read(conn, debt_id)
