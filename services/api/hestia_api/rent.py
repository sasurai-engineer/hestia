"""Leases, rent charges, receipts, and renewals.

Charges are expectations (mutable, outside the ledger); receipts are money
that moved (ledger rows, appended through the same door as everything else)
and allocations tie the two together. The rent sweep is idempotent through
the one-charge-per-period key; the late-fee sweep is JURISDICTION-DRIVEN and
refuses to invent a fee where no cited rule exists — absence is reported as
a coverage gap, the deadline sweep's discipline.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

from hestia_api import ledger as ledger_module

Conn = psycopg.Connection[dict[str, Any]]

CENT = Decimal("0.01")


class UnknownLease(Exception):
    pass


class NothingOutstanding(Exception):
    pass


class OverAllocation(Exception):
    pass


class UnitIn(BaseModel):
    property_id: str
    label: str = Field(min_length=1, max_length=40)
    market_rent: Decimal | None = Field(default=None, gt=0, decimal_places=2, max_digits=18)


class ResidentIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    phone: str | None = None


class LeaseIn(BaseModel):
    unit_id: str
    starts_on: dt.date
    ends_on: dt.date | None = None
    rent: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    rent_due_day: int = Field(default=1, ge=1, le=28)
    security_deposit: Decimal = Field(default=Decimal(0), ge=0, decimal_places=2, max_digits=18)
    escalation: Literal["none", "fixed_amount", "fixed_percent"] = "none"
    escalation_value: Decimal | None = None
    status: Literal["active", "month_to_month", "draft"] = "active"
    resident_ids: list[str] = []


class LeaseSummary(BaseModel):
    id: str
    property_label: str
    unit_label: str
    status: str
    starts_on: dt.date
    ends_on: dt.date | None
    rent: Decimal
    residents: list[str]
    balance_due: Decimal
    # Receipts not yet applied to any charge (a prepayment); the next sweep
    # consumes it before anything is billed as due.
    open_credit: Decimal


class ChargeOut(BaseModel):
    id: str
    kind: str
    period_start: dt.date
    due_on: dt.date
    amount: Decimal
    status: str
    allocated: Decimal
    outstanding: Decimal
    rule_citation: str | None
    waived_reason: str | None


class LeaseDetail(BaseModel):
    id: str
    property_id: str
    property_label: str
    unit_label: str
    status: str
    starts_on: dt.date
    ends_on: dt.date | None
    rent: Decimal
    rent_due_day: int
    security_deposit: Decimal
    deposit_returned_on: dt.date | None
    escalation: str
    escalation_value: Decimal | None
    residents: list[str]
    charges: list[ChargeOut]
    balance_due: Decimal
    open_credit: Decimal


@dataclass(frozen=True)
class RentSweepGap:
    lease_id: str
    reason: str  # cpi_index_unavailable | no_late_fee_rule
    detail: str


class RentSweepResult(BaseModel):
    charges_created: int
    gaps: list[dict[str, str]]


def create_unit(conn: Conn, body: UnitIn) -> str:
    row = conn.execute(
        """
        INSERT INTO units (property_id, label, market_rent, market_rent_as_of)
        VALUES (%s, %s, %s, CASE WHEN %s::numeric IS NULL THEN NULL ELSE CURRENT_DATE END)
        RETURNING id::text
        """,
        (body.property_id, body.label, body.market_rent, body.market_rent),
    ).fetchone()
    return row["id"]  # type: ignore[index]


def create_resident(conn: Conn, body: ResidentIn) -> str:
    row = conn.execute(
        "INSERT INTO residents (full_name, email, phone) VALUES (%s, %s, %s) RETURNING id::text",
        (body.full_name, body.email, body.phone),
    ).fetchone()
    return row["id"]  # type: ignore[index]


def create_lease(conn: Conn, body: LeaseIn) -> str:
    row = conn.execute(
        """
        INSERT INTO leases
          (unit_id, status, starts_on, ends_on, rent, rent_due_day,
           security_deposit, escalation, escalation_value)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text
        """,
        (
            body.unit_id,
            body.status,
            body.starts_on,
            body.ends_on,
            body.rent,
            body.rent_due_day,
            body.security_deposit,
            body.escalation,
            body.escalation_value,
        ),
    ).fetchone()
    lease_id: str = row["id"]  # type: ignore[index]
    for resident_id in body.resident_ids:
        conn.execute(
            "INSERT INTO lease_residents (lease_id, resident_id) VALUES (%s, %s)",
            (lease_id, resident_id),
        )
    return lease_id


_LEASE_BASE = """
SELECT l.id::text, u.property_id::text, p.label AS property_label,
       u.label AS unit_label, l.status::text, l.starts_on, l.ends_on, l.rent,
       l.rent_due_day, l.security_deposit, l.deposit_returned_on,
       l.escalation::text, l.escalation_value,
       coalesce(array_agg(r.full_name ORDER BY r.full_name)
                FILTER (WHERE r.full_name IS NOT NULL), '{}') AS residents,
       -- Independent scalar subqueries — never a JOIN that fans a charge out
       -- once per allocation (the review's critical finding: a charge paid in
       -- two installments double-counted itself and /collect billed a
       -- paid-up tenant). Waived/written_off drop out of BOTH sides.
       coalesce((SELECT sum(c.amount) FROM rent_charges c
                 WHERE c.lease_id = l.id
                   AND c.status NOT IN ('waived', 'written_off')), 0)
       - coalesce((SELECT sum(a.amount)
                   FROM rent_receipt_allocations a
                   JOIN rent_charges c ON c.id = a.charge_id
                   WHERE c.lease_id = l.id
                     AND c.status NOT IN ('waived', 'written_off')), 0)
         AS balance_due,
       -- Money received but not yet applied to any charge: a prepayment,
       -- persistent and visible, consumed by the next sweep.
       coalesce((SELECT sum(e.amount) FROM ledger_events e
                 WHERE e.lease_id = l.id
                   AND e.category IN ('rent', 'late_fee')
                   AND e.amount > 0
                   AND e.reverses_event_id IS NULL
                   AND NOT EXISTS (SELECT 1 FROM ledger_events r
                                   WHERE r.reverses_event_id = e.id)), 0)
       - coalesce((SELECT sum(a.amount)
                   FROM rent_receipt_allocations a
                   JOIN rent_charges c ON c.id = a.charge_id
                   WHERE c.lease_id = l.id), 0)
         AS open_credit
FROM leases l
JOIN units u ON u.id = l.unit_id
JOIN properties p ON p.id = u.property_id
LEFT JOIN lease_residents lr ON lr.lease_id = l.id
LEFT JOIN residents r ON r.id = lr.resident_id
"""

_LEASE_GROUP = """
GROUP BY l.id, u.property_id, p.label, u.label, l.status, l.starts_on, l.ends_on,
         l.rent, l.rent_due_day, l.security_deposit, l.deposit_returned_on,
         l.escalation, l.escalation_value
"""


def list_leases(conn: Conn) -> list[LeaseSummary]:
    rows = conn.execute(_LEASE_BASE + _LEASE_GROUP + " ORDER BY p.label, u.label").fetchall()
    return [
        LeaseSummary(
            id=row["id"],
            property_label=row["property_label"],
            unit_label=row["unit_label"],
            status=row["status"],
            starts_on=row["starts_on"],
            ends_on=row["ends_on"],
            rent=row["rent"],
            residents=row["residents"],
            balance_due=row["balance_due"],
            open_credit=row["open_credit"],
        )
        for row in rows
    ]


def lease_detail(conn: Conn, lease_id: str) -> LeaseDetail:
    row = conn.execute(
        _LEASE_BASE + " WHERE l.id = %s " + _LEASE_GROUP,
        (lease_id,),
    ).fetchone()
    if row is None:
        raise UnknownLease(lease_id)
    charges = conn.execute(
        """
        SELECT c.id::text, c.kind::text, c.period_start, c.due_on, c.amount,
               c.status::text, c.rule_citation, c.waived_reason,
               coalesce(sum(a.amount), 0) AS allocated
        FROM rent_charges c
        LEFT JOIN rent_receipt_allocations a ON a.charge_id = c.id
        WHERE c.lease_id = %s
        GROUP BY c.id
        ORDER BY c.period_start DESC, c.kind
        """,
        (lease_id,),
    ).fetchall()
    return LeaseDetail(
        **{k: row[k] for k in row if k not in ("balance_due", "open_credit")},
        balance_due=row["balance_due"],
        open_credit=row["open_credit"],
        charges=[
            ChargeOut(
                **{k: charge[k] for k in charge if k != "allocated"},
                allocated=charge["allocated"],
                outstanding=(
                    charge["amount"] - charge["allocated"]
                    if charge["status"] not in ("waived", "written_off")
                    else Decimal(0)
                ),
            )
            for charge in charges
        ],
    )


def _escalated_rent(
    base: Decimal, escalation: str, value: Decimal | None, years_elapsed: int
) -> Decimal:
    if years_elapsed <= 0 or escalation == "none" or value is None:
        return base
    if escalation == "fixed_amount":
        return base + value * years_elapsed
    # fixed_percent: compounded annually, HalfEven to the cent.
    grown = base * (Decimal(1) + value) ** years_elapsed
    return grown.quantize(CENT, rounding=ROUND_HALF_EVEN)


def sweep_rent_charges(conn: Conn, as_of: dt.date) -> RentSweepResult:
    """One rent charge per active lease for as_of's month. Idempotent via the
    one-charge-per-period key; CPI escalations are reported, not guessed."""
    period_start = as_of.replace(day=1)
    leases = conn.execute(
        """
        SELECT id::text, starts_on, ends_on, rent, rent_due_day,
               escalation::text, escalation_value
        FROM leases
        WHERE status IN ('active', 'month_to_month')
          AND starts_on <= %(period)s
          AND (ends_on IS NULL OR ends_on >= %(period)s)
        """,
        {"period": period_start},
    ).fetchall()
    created = 0
    gaps: list[RentSweepGap] = []
    for lease in leases:
        if lease["escalation"] == "cpi":
            gaps.append(
                RentSweepGap(
                    lease_id=lease["id"],
                    reason="cpi_index_unavailable",
                    detail="CPI escalation needs an index series; charge not generated",
                )
            )
            continue
        years = (
            period_start.year
            - lease["starts_on"].year
            - (1 if (period_start.month, 1) < (lease["starts_on"].month, 1) else 0)
        )
        amount = _escalated_rent(
            lease["rent"], lease["escalation"], lease["escalation_value"], years
        )
        due_on = period_start + dt.timedelta(days=lease["rent_due_day"] - 1)
        result = conn.execute(
            """
            INSERT INTO rent_charges
              (lease_id, kind, period_start, period_end, due_on, amount, generated_by)
            VALUES (%s, 'rent', %s,
                    (%s::date + INTERVAL '1 month' - INTERVAL '1 day')::date,
                    %s, %s, 'sweep')
            ON CONFLICT (lease_id, kind, period_start) DO NOTHING
            """,
            (lease["id"], period_start, period_start, due_on, amount),
        )
        created += result.rowcount
        if result.rowcount:
            # A prepaid tenant's open credit pays the new charge immediately —
            # before anything can call it overdue.
            apply_open_credit(conn, lease["id"])
    return RentSweepResult(charges_created=created, gaps=[vars(gap) for gap in gaps])


LATE_FEE_RULES_SQL = """
WITH lease_anchor AS (
  SELECT l.id AS lease_id, p.state,
         COALESCE(p.jurisdiction_id, s.id) AS start_id
  FROM leases l
  JOIN units u ON u.id = l.unit_id
  JOIN properties p ON p.id = u.property_id
  LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
  WHERE l.id = ANY(%(lease_ids)s)
),
resolved AS (
  SELECT DISTINCT ON (a.lease_id, r.code)
         a.lease_id, r.code, r.value_numeric, r.value_money, r.citation
  FROM lease_anchor a
  CROSS JOIN LATERAL jurisdiction_chain(a.start_id) c
  JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
  WHERE r.domain = 'late_fee'
    AND r.superseded_by IS NULL
    AND r.effective_from <= %(as_of)s
    AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
  ORDER BY a.lease_id, r.code, c.depth ASC, r.effective_from DESC
)
SELECT a.lease_id::text, a.state,
       grace.value_numeric AS grace_days, grace.citation AS grace_citation,
       fee_amount.value_money AS fee_amount,
       fee_percent.value_numeric AS fee_percent,
       coalesce(fee_amount.citation, fee_percent.citation) AS fee_citation
FROM lease_anchor a
LEFT JOIN resolved grace ON grace.lease_id = a.lease_id AND grace.code = 'latefee.grace_days'
LEFT JOIN resolved fee_amount
  ON fee_amount.lease_id = a.lease_id AND fee_amount.code = 'latefee.amount'
LEFT JOIN resolved fee_percent
  ON fee_percent.lease_id = a.lease_id AND fee_percent.code = 'latefee.percent'
"""


def sweep_late_fees(conn: Conn, as_of: dt.date) -> RentSweepResult:
    """Assess late fees ONLY where the jurisdiction chain provides a cited
    rule (grace days + a fee amount or percent). No rule, no fee — the gap
    says so, and the owner can still assess manually from the lease terms."""
    overdue = conn.execute(
        """
        SELECT c.id::text AS charge_id, c.lease_id::text, c.period_start, c.due_on,
               c.amount, coalesce(sum(a.amount), 0) AS allocated
        FROM rent_charges c
        LEFT JOIN rent_receipt_allocations a ON a.charge_id = c.id
        WHERE c.kind = 'rent' AND c.status IN ('due', 'partially_paid')
          AND c.due_on < %(as_of)s
          AND NOT EXISTS (SELECT 1 FROM rent_charges lf
                          WHERE lf.lease_id = c.lease_id AND lf.kind = 'late_fee'
                            AND lf.period_start = c.period_start)
        GROUP BY c.id
        HAVING coalesce(sum(a.amount), 0) < c.amount
        """,
        {"as_of": as_of},
    ).fetchall()
    if not overdue:
        return RentSweepResult(charges_created=0, gaps=[])
    rules = {
        row["lease_id"]: row
        for row in conn.execute(
            LATE_FEE_RULES_SQL,
            {"lease_ids": [row["lease_id"] for row in overdue], "as_of": as_of},
        ).fetchall()
    }
    created = 0
    gaps: list[RentSweepGap] = []
    for charge in overdue:
        rule = rules[charge["lease_id"]]
        has_fee = rule["fee_amount"] is not None or rule["fee_percent"] is not None
        if rule["grace_days"] is None or not has_fee:
            gaps.append(
                RentSweepGap(
                    lease_id=charge["lease_id"],
                    reason="no_late_fee_rule",
                    detail=(
                        f"no cited late-fee rule on the {rule['state']} chain; "
                        "assess manually from the lease terms if they provide one"
                    ),
                )
            )
            continue
        if as_of <= charge["due_on"] + dt.timedelta(days=int(rule["grace_days"])):
            continue  # inside the grace window
        if rule["fee_amount"] is not None:
            fee = rule["fee_amount"]
        else:
            fee = (charge["amount"] * rule["fee_percent"]).quantize(CENT, rounding=ROUND_HALF_EVEN)
        result = conn.execute(
            """
            INSERT INTO rent_charges
              (lease_id, kind, period_start, due_on, amount, generated_by, rule_citation)
            VALUES (%s, 'late_fee', %s, %s, %s, 'sweep', %s)
            ON CONFLICT (lease_id, kind, period_start) DO NOTHING
            """,
            (
                charge["lease_id"],
                charge["period_start"],
                as_of,
                fee,
                rule["fee_citation"],
            ),
        )
        created += result.rowcount
        # Unconditional: the overdue query already excludes periods with an
        # existing fee, so the only rowcount-0 case is a concurrent sweep —
        # and applying credit is idempotent either way.
        apply_open_credit(conn, charge["lease_id"])
    return RentSweepResult(charges_created=created, gaps=[vars(gap) for gap in gaps])


class ReceiptIn(BaseModel):
    occurred_on: dt.date
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    memo: str | None = None
    category: Literal["rent", "late_fee", "deposit_received"] = "rent"


class ReceiptOut(BaseModel):
    event_uuid: str
    allocations: list[dict[str, str]]
    unallocated: Decimal


def apply_open_credit(conn: Conn, lease_id: str) -> list[dict[str, str]]:
    """Apply every unapplied receipt to every open charge, oldest first on
    both sides — the single allocation engine behind receipts, sweeps, and
    webhook settlements. A prepayment therefore pays the next charge the
    moment the sweep creates it, instead of vanishing while a late fee
    accrues (the adversarial review's scenario). Charge rows are locked so
    concurrent applications serialize; the schema's allocation-cap trigger
    backs the arithmetic at the database.
    """
    credits = conn.execute(
        """
        SELECT e.id, e.event_uuid::text,
               e.amount - coalesce((SELECT sum(a.amount)
                                    FROM rent_receipt_allocations a
                                    WHERE a.ledger_event_id = e.id), 0) AS remaining
        FROM ledger_events e
        WHERE e.lease_id = %s
          AND e.category IN ('rent', 'late_fee')
          AND e.amount > 0
          AND e.reverses_event_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM ledger_events r
                          WHERE r.reverses_event_id = e.id)
        ORDER BY e.occurred_on, e.id
        """,
        (lease_id,),
    ).fetchall()
    open_charges = conn.execute(
        """
        SELECT c.id::text,
               c.amount - coalesce((SELECT sum(a.amount)
                                    FROM rent_receipt_allocations a
                                    WHERE a.charge_id = c.id), 0) AS outstanding
        FROM rent_charges c
        WHERE c.lease_id = %s AND c.status IN ('due', 'partially_paid')
        ORDER BY c.due_on, c.created_at
        FOR UPDATE OF c
        """,
        (lease_id,),
    ).fetchall()
    allocations: list[dict[str, str]] = []
    charge_queue = [dict(charge) for charge in open_charges if charge["outstanding"] > 0]
    for credit in credits:
        remaining = credit["remaining"]
        for charge in charge_queue:
            if remaining <= 0:
                break
            if charge["outstanding"] <= 0:
                continue
            portion = min(remaining, charge["outstanding"])
            conn.execute(
                """
                INSERT INTO rent_receipt_allocations (charge_id, ledger_event_id, amount)
                VALUES (%s, %s, %s)
                """,
                (charge["id"], credit["id"], portion),
            )
            ledger_module.refresh_charge_status(conn, charge["id"])
            charge["outstanding"] -= portion
            remaining -= portion
            allocations.append(
                {
                    "charge_id": charge["id"],
                    "event_uuid": credit["event_uuid"],
                    "amount": str(portion),
                }
            )
    return allocations


def record_receipt(conn: Conn, lease_id: str, body: ReceiptIn) -> ReceiptOut:
    """Append the ledger row, then allocate oldest-charge-first. Anything left
    over stays visible as unallocated — never silently absorbed."""
    lease = conn.execute(
        """
        SELECT l.id::text, u.property_id::text, u.id::text AS unit_id
        FROM leases l JOIN units u ON u.id = l.unit_id WHERE l.id = %s
        """,
        (lease_id,),
    ).fetchone()
    if lease is None:
        raise UnknownLease(lease_id)
    event = ledger_module.append_event(
        conn,
        ledger_module.LedgerEntryIn(
            occurred_on=body.occurred_on,
            category=body.category,
            amount=body.amount,
            memo=body.memo,
            property_id=lease["property_id"],
            unit_id=lease["unit_id"],
            lease_id=lease["id"],
        ),
    )
    allocations: list[dict[str, str]] = []
    if body.category != "deposit_received":
        # The shared engine applies THIS receipt and any older open credit.
        applied = apply_open_credit(conn, lease_id)
        allocations = [
            {"charge_id": entry["charge_id"], "amount": entry["amount"]}
            for entry in applied
            if entry["event_uuid"] == event.event_uuid
        ]
    allocated_here = sum((Decimal(entry["amount"]) for entry in allocations), Decimal(0))
    return ReceiptOut(
        event_uuid=event.event_uuid,
        allocations=allocations,
        # Anything left is OPEN CREDIT — persistent, visible on the lease,
        # and consumed by the next sweep. Never absorbed, never forgotten.
        unallocated=body.amount - allocated_here,
    )


class RenewalContextOut(BaseModel):
    lease_id: str
    current_rent: Decimal
    ends_on: dt.date | None
    market_rent: Decimal | None
    market_rent_source: str | None
    # Turn assumptions with their provenance: measured from this portfolio's
    # own renewal history when it exists, labeled defaults when it does not.
    turn_cost: Decimal
    vacancy_days: int
    assumptions_source: str


def renewal_context(conn: Conn, lease_id: str) -> RenewalContextOut:
    lease = conn.execute(
        """
        SELECT l.id::text, l.rent, l.ends_on, u.market_rent, u.market_rent_as_of
        FROM leases l JOIN units u ON u.id = l.unit_id WHERE l.id = %s
        """,
        (lease_id,),
    ).fetchone()
    if lease is None:
        raise UnknownLease(lease_id)
    history = conn.execute(
        """
        SELECT avg(turn_cost) AS turn_cost, avg(vacancy_days)::int AS vacancy_days,
               count(*) AS observations
        FROM lease_renewals
        WHERE accepted = FALSE AND turn_cost IS NOT NULL AND vacancy_days IS NOT NULL
        """
    ).fetchone()
    if history is not None and history["observations"] > 0:
        turn_cost = history["turn_cost"].quantize(CENT)
        vacancy_days = history["vacancy_days"]
        source = f"measured from {history['observations']} recorded turn(s)"
    else:
        turn_cost = lease["rent"].quantize(CENT)
        vacancy_days = 21
        source = (
            "defaults: one month's rent turn cost, 21 vacancy days — no "
            "recorded turns yet; every refused renewal you log sharpens this"
        )
    return RenewalContextOut(
        lease_id=lease["id"],
        current_rent=lease["rent"],
        ends_on=lease["ends_on"],
        market_rent=lease["market_rent"],
        market_rent_source=(
            f"unit market rent as of {lease['market_rent_as_of']}"
            if lease["market_rent"] is not None
            else None
        ),
        turn_cost=turn_cost,
        vacancy_days=vacancy_days,
        assumptions_source=source,
    )


class RenewalOfferIn(BaseModel):
    offered_on: dt.date
    offered_rent: Decimal = Field(gt=0, decimal_places=2, max_digits=18)


def record_renewal_offer(conn: Conn, lease_id: str, body: RenewalOfferIn) -> str:
    lease = conn.execute("SELECT rent FROM leases WHERE id = %s", (lease_id,)).fetchone()
    if lease is None:
        raise UnknownLease(lease_id)
    row = conn.execute(
        """
        INSERT INTO lease_renewals (prior_lease_id, offered_on, offered_rent, prior_rent)
        VALUES (%s, %s, %s, %s) RETURNING id::text
        """,
        (lease_id, body.offered_on, body.offered_rent, lease["rent"]),
    ).fetchone()
    return row["id"]  # type: ignore[index]
