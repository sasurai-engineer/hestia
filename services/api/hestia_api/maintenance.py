"""Maintenance: vendors, work orders, and the completion that teaches the
inventory.

A work order is not a ticket with a real-estate coat of paint. Completing one
with `resolution='replaced'` is the moment the capital forecast stops guessing
about that component: the retired row leaves the live inventory, the installed
row arrives with a KNOWN date, and the Weibull fan narrows because of it. That
is why completion is a transaction here — and why the ledger row it posts is
refused until the owner has answered the betterment/adaptation/restoration
question that decides whether the money was an expense or basis.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

from hestia_api import ledger as ledger_module
from hestia_api.reports import DE_MINIMIS_CENTS

Conn = psycopg.Connection[dict[str, Any]]

# Treas. Reg. 1.263(a)-3(k)(1)(vi): replacing a MAJOR COMPONENT of a unit of
# property is a restoration, and restorations are capitalised. The plumbing
# system is its own unit of property (1.263(a)-3(e)(2)(ii)), so "the building
# is fine" is not the question being asked.
RESTORATION_CITATION = (
    "Treas. Reg. 1.263(a)-3(k)(1)(vi) — replacing a major component of a unit "
    "of property is a restoration; the building system is its own unit of "
    "property under 1.263(a)-3(e)(2)(ii)"
)
# DE_MINIMIS_CENTS is misnamed in reports.py — the value is DOLLARS
# (Decimal("2500.00")). Imported rather than re-declared so this module and
# the Schedule E classification flag can never disagree about the line.
DE_MINIMIS_CITATION = (
    f"Treas. Reg. 1.263(a)-1(f) — the de minimis safe harbour, ${DE_MINIMIS_CENTS} "
    "per item without an applicable financial statement"
)
ROUTINE_MAINTENANCE_CITATION = (
    "Treas. Reg. 1.263(a)-3(i) — the routine maintenance safe harbour, for "
    "work expected more than once over the property's class life"
)

# What may follow what. Completion is NOT here: it needs a resolution and it
# writes to the inventory, so it has its own door.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "reported": frozenset({"triaged", "scheduled", "in_progress", "cancelled"}),
    "triaged": frozenset({"scheduled", "in_progress", "cancelled"}),
    "scheduled": frozenset({"scheduled", "in_progress", "triaged", "cancelled"}),
    "in_progress": frozenset({"cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}
COMPLETABLE_FROM = frozenset({"reported", "triaged", "scheduled", "in_progress"})


class UnknownVendor(Exception):
    pass


class UnknownWorkOrder(Exception):
    pass


class UnknownEntity(Exception):
    pass


class UnknownProperty(Exception):
    pass


class DuplicateVendor(Exception):
    """One vendor name per owner's list."""


class IllegalTransition(Exception):
    def __init__(self, current: str, requested: str) -> None:
        legal = ", ".join(sorted(LEGAL_TRANSITIONS[current])) or "nothing (terminal)"
        super().__init__(f"{current} may become {legal}; not {requested}")


class AlreadyResolved(Exception):
    """A completed or cancelled job is closed; its history is not re-made."""


class MissingComponent(Exception):
    """A replacement must name what it replaced."""


class ComponentAlreadyRetired(Exception):
    pass


class CapitalNeedsRationale(Exception):
    """is_capital=true without the authority that makes it so."""


class WrongProperty(Exception):
    """A cost anchored to a different property than the job it is joining."""


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

VendorTrade = Literal[
    "plumbing",
    "hvac",
    "electrical",
    "roofing",
    "appliance",
    "general_contractor",
    "handyman",
    "landscaping",
    "pest_control",
    "cleaning",
    "flooring",
    "painting",
    "restoration",
    "inspection",
    "other",
]


class VendorIn(BaseModel):
    # UUID-typed so a malformed id is a 422 at the edge, not a 500 in SQL.
    entity_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    trade: VendorTrade
    phone: str | None = None
    email: str | None = None
    license_number: str | None = None
    license_expires_on: dt.date | None = None
    insurer: str | None = None
    liability_expires_on: dt.date | None = None
    workers_comp_expires_on: dt.date | None = None
    w9_on_file: bool = False
    is_1099_reportable: bool = True
    notes: str | None = None


class VendorOut(BaseModel):
    id: str
    entity_id: str
    entity_name: str
    name: str
    trade: VendorTrade
    phone: str | None
    email: str | None
    license_number: str | None
    license_expires_on: dt.date | None
    insurer: str | None
    liability_expires_on: dt.date | None
    workers_comp_expires_on: dt.date | None
    w9_on_file: bool
    is_1099_reportable: bool
    notes: str | None
    retired_on: dt.date | None
    # Computed against as_of, server-side: the browser displays this, it does
    # not decide it.
    coverage_state: Literal["current", "expiring", "expired", "unknown"]
    earliest_expiry: dt.date | None
    open_work_orders: int
    # Vendors are scoped to the entity that hires them, which is right for
    # filing (the 1099 obligation is per payer) and wrong for operations: the
    # same plumber under three LLCs is three rows with three certificate
    # chains. Counted and shown rather than left silent.
    also_registered_under: int


# A certificate inside this window is worth chasing before it lapses.
EXPIRING_SOON_DAYS = 30


def _coverage_state(row: dict[str, Any], as_of: dt.date) -> tuple[str, dt.date | None]:
    """A vendor's credential standing, from the dates on file.

    'unknown' is not 'current': a vendor whose certificate was never recorded
    has not been shown to carry insurance, and saying otherwise would be the
    kind of quiet reassurance this system exists to refuse.
    """
    # INSURANCE decides the standing. A vendor with a trade licence and no
    # certificate has shown a qualification, not coverage, and reporting that
    # as 'current' is precisely the quiet reassurance this refuses to give.
    insurance = [
        row[column]
        for column in ("liability_expires_on", "workers_comp_expires_on")
        if row[column] is not None
    ]
    if not insurance:
        return "unknown", row["license_expires_on"]
    dates = insurance + (
        [row["license_expires_on"]] if row["license_expires_on"] is not None else []
    )
    earliest = min(dates)
    if earliest < as_of:
        return "expired", earliest
    if (earliest - as_of).days <= EXPIRING_SOON_DAYS:
        return "expiring", earliest
    return "current", earliest


def create_vendor(conn: Conn, body: VendorIn) -> VendorOut:
    entity = conn.execute(
        "SELECT id::text FROM entities WHERE id = %s", (body.entity_id,)
    ).fetchone()
    if entity is None:
        raise UnknownEntity(body.entity_id)
    try:
        row = conn.execute(
            """
            INSERT INTO vendors
              (entity_id, name, trade, phone, email, license_number, license_expires_on,
               insurer, liability_expires_on, workers_comp_expires_on, w9_on_file,
               is_1099_reportable, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id::text
            """,
            (
                body.entity_id,
                body.name.strip(),
                body.trade,
                body.phone,
                body.email,
                body.license_number,
                body.license_expires_on,
                body.insurer,
                body.liability_expires_on,
                body.workers_comp_expires_on,
                body.w9_on_file,
                body.is_1099_reportable,
                body.notes,
            ),
        ).fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise DuplicateVendor(body.name) from error
    return read_vendor(conn, row["id"], as_of=dt.date.today())


def read_vendor(conn: Conn, vendor_id: str, *, as_of: dt.date) -> VendorOut:
    row = conn.execute(
        """
        SELECT v.id::text, v.entity_id::text, e.name AS entity_name, v.name,
               v.trade::text AS trade, v.phone, v.email, v.license_number,
               v.license_expires_on, v.insurer, v.liability_expires_on,
               v.workers_comp_expires_on, v.w9_on_file, v.is_1099_reportable,
               v.notes, v.retired_on,
               (SELECT count(*) FROM vendors other
                 WHERE lower(other.name) = lower(v.name)
                   AND other.id <> v.id) AS also_registered_under,
               (SELECT count(*) FROM work_orders w
                 WHERE w.vendor_id = v.id
                   AND w.status NOT IN ('completed', 'cancelled')) AS open_work_orders
        FROM vendors v JOIN entities e ON e.id = v.entity_id
        WHERE v.id = %s
        """,
        (vendor_id,),
    ).fetchone()
    if row is None:
        raise UnknownVendor(vendor_id)
    state, earliest = _coverage_state(row, as_of)
    return VendorOut(**row, coverage_state=state, earliest_expiry=earliest)


def list_vendors(
    conn: Conn, *, as_of: dt.date, entity_id: str | None = None, include_retired: bool = False
) -> list[VendorOut]:
    rows = conn.execute(
        """
        SELECT v.id::text, v.entity_id::text, e.name AS entity_name, v.name,
               v.trade::text AS trade, v.phone, v.email, v.license_number,
               v.license_expires_on, v.insurer, v.liability_expires_on,
               v.workers_comp_expires_on, v.w9_on_file, v.is_1099_reportable,
               v.notes, v.retired_on,
               (SELECT count(*) FROM vendors other
                 WHERE lower(other.name) = lower(v.name)
                   AND other.id <> v.id) AS also_registered_under,
               (SELECT count(*) FROM work_orders w
                 WHERE w.vendor_id = v.id
                   AND w.status NOT IN ('completed', 'cancelled')) AS open_work_orders
        FROM vendors v JOIN entities e ON e.id = v.entity_id
        WHERE (%(entity_id)s::uuid IS NULL OR v.entity_id = %(entity_id)s::uuid)
          AND (%(include_retired)s OR v.retired_on IS NULL)
        ORDER BY v.name
        """,
        {"entity_id": entity_id, "include_retired": include_retired},
    ).fetchall()
    out: list[VendorOut] = []
    for row in rows:
        state, earliest = _coverage_state(row, as_of)
        out.append(VendorOut(**row, coverage_state=state, earliest_expiry=earliest))
    return out


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

WorkOrderStatus = Literal[
    "reported", "triaged", "scheduled", "in_progress", "completed", "cancelled"
]
WorkOrderPriority = Literal["emergency", "urgent", "routine", "planned"]
Resolution = Literal["repaired", "replaced", "no_action"]
CostRelation = Literal[
    "invoice", "materials", "deposit", "tenant_chargeback", "warranty_credit", "other"
]


Reporter = Literal["resident", "owner", "inspection", "vendor"]


class WorkOrderIn(BaseModel):
    property_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    component_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    summary: str = Field(min_length=1, max_length=400)
    detail: str | None = None
    priority: WorkOrderPriority = "routine"
    reported_by: Reporter = "owner"
    reported_on: dt.date | None = None


class TransitionIn(BaseModel):
    status: Literal["triaged", "scheduled", "in_progress", "cancelled"]
    scheduled_for: dt.date | None = None
    vendor_id: uuid.UUID | None = None
    cancelled_reason: str | None = None


class CostIn(BaseModel):
    """A cost typed as a positive magnitude; the ledger's sign is our business,
    not the operator's."""

    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    occurred_on: dt.date | None = None
    relation: CostRelation = "invoice"
    is_capital: bool | None = None
    capitalisation_rationale: str | None = None
    counterparty: str | None = None
    memo: str | None = None
    document_id: uuid.UUID | None = None


class ReplacementIn(BaseModel):
    component_type_id: uuid.UUID | None = None  # defaults to the retired row's type
    installed_on: dt.date | None = None  # defaults to the completion date
    # Bounded to the columns these land in — components.quantity NUMERIC(10,2),
    # expected_life_years NUMERIC(5,2), replacement_cost money_amount
    # NUMERIC(18,2). Unbounded, they overflowed the column as a 500.
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=2, max_digits=10)
    warranty_expires_on: dt.date | None = None
    expected_life_years: Decimal | None = Field(default=None, gt=0, decimal_places=2, max_digits=5)
    replacement_cost: Decimal | None = Field(default=None, ge=0, decimal_places=2, max_digits=18)
    notes: str | None = None


class CompletionIn(BaseModel):
    completed_on: dt.date
    resolution: Resolution
    resolution_note: str | None = None
    cost: CostIn | None = None
    replacement: ReplacementIn | None = None


class CostOut(BaseModel):
    ledger_event_uuid: str
    occurred_on: dt.date
    amount: Decimal
    category: str
    relation: CostRelation
    is_capital: bool | None
    reversed: bool


class WorkOrderOut(BaseModel):
    id: str
    property_id: str
    property_label: str
    unit_id: str | None
    unit_label: str | None
    component_id: str | None
    component_label: str | None
    vendor_id: str | None
    vendor_name: str | None
    status: WorkOrderStatus
    priority: WorkOrderPriority
    reported_by: Reporter
    reported_on: dt.date
    summary: str
    detail: str | None
    scheduled_for: dt.date | None
    completed_on: dt.date | None
    resolution: Resolution | None
    resolution_note: str | None
    replacement_component_id: str | None
    cancelled_reason: str | None
    costs: list[CostOut]
    # The job's money, net of any reversal: a mis-posted invoice corrected by
    # a reversal pair nets to what was actually spent.
    net_cost: Decimal
    legal_transitions: list[WorkOrderStatus]


class CompletionOut(BaseModel):
    work_order: WorkOrderOut
    retired_component_id: str | None
    installed_component_id: str | None
    ledger_event_uuid: str | None
    # Why the money landed where it did, cited.
    capitalisation_citation: str | None


def _bar_citation(is_capital: bool | None, amount: Decimal) -> str | None:
    if is_capital is True:
        return RESTORATION_CITATION
    if is_capital is False:
        # Treas. Reg. 1.263(a)-1(f)(1)(ii)(D) reads "does not exceed", so the
        # threshold itself is INSIDE the harbour. (Schedule E's
        # needs_classification flag fires at >= the same number on purpose:
        # asking a human at the boundary is caution, not a contradiction.)
        return DE_MINIMIS_CITATION if amount <= DE_MINIMIS_CENTS else ROUTINE_MAINTENANCE_CITATION
    return None


def _costs_for(conn: Conn, work_order_id: str) -> tuple[list[CostOut], Decimal]:
    rows = conn.execute(
        """
        SELECT e.event_uuid::text AS ledger_event_uuid, e.occurred_on, e.amount,
               e.category::text AS category, l.relation::text AS relation, e.is_capital,
               EXISTS (SELECT 1 FROM ledger_events r WHERE r.reverses_event_id = e.id)
                 AS reversed,
               -- The reversal half of a correction pair is a SEPARATE event and
               -- is not itself associated with the job, so the net has to reach
               -- for it explicitly. Without this a mis-posted invoice that was
               -- properly reversed still shows as money the job cost.
               e.amount + coalesce(
                 (SELECT sum(r.amount) FROM ledger_events r WHERE r.reverses_event_id = e.id),
                 0
               ) AS effective_amount
        FROM work_order_ledger_events l
        JOIN ledger_events e ON e.id = l.ledger_event_id
        WHERE l.work_order_id = %s
        ORDER BY e.occurred_on, e.id
        """,
        (work_order_id,),
    ).fetchall()
    costs = [CostOut(**{key: row[key] for key in CostOut.model_fields}) for row in rows]
    # Money OUT is negative in the ledger, so a job's cost is the magnitude of
    # the net outflow: reversals cancel, and a credit genuinely reduces it.
    net = -sum((row["effective_amount"] for row in rows), Decimal("0"))
    return costs, net


def read_work_order(conn: Conn, work_order_id: str) -> WorkOrderOut:
    row = conn.execute(
        """
        SELECT w.id::text, w.property_id::text, p.label AS property_label,
               w.unit_id::text, u.label AS unit_label,
               w.component_id::text, ct.display_name AS component_label,
               w.vendor_id::text, v.name AS vendor_name,
               w.status::text AS status, w.priority::text AS priority,
               w.reported_by::text AS reported_by, w.reported_on, w.summary, w.detail,
               w.scheduled_for, w.completed_on, w.resolution::text AS resolution,
               w.resolution_note, w.replacement_component_id::text, w.cancelled_reason
        FROM work_orders w
        JOIN properties p ON p.id = w.property_id
        LEFT JOIN units u ON u.id = w.unit_id
        LEFT JOIN components c ON c.id = w.component_id
        LEFT JOIN component_types ct ON ct.id = c.component_type_id
        LEFT JOIN vendors v ON v.id = w.vendor_id
        WHERE w.id = %s
        """,
        (work_order_id,),
    ).fetchone()
    if row is None:
        raise UnknownWorkOrder(work_order_id)
    costs, net = _costs_for(conn, work_order_id)
    return WorkOrderOut(
        **row,
        costs=costs,
        net_cost=net,
        legal_transitions=sorted(LEGAL_TRANSITIONS[row["status"]]),
    )


def list_work_orders(
    conn: Conn,
    *,
    property_id: str | None = None,
    status: str | None = None,
    open_only: bool = False,
) -> list[WorkOrderOut]:
    rows = conn.execute(
        """
        SELECT w.id::text
        FROM work_orders w
        WHERE (%(property_id)s::uuid IS NULL OR w.property_id = %(property_id)s::uuid)
          AND (%(status)s::text IS NULL OR w.status::text = %(status)s)
          AND (NOT %(open_only)s OR w.status NOT IN ('completed', 'cancelled'))
        ORDER BY
          array_position(ARRAY['emergency','urgent','routine','planned'],
                         w.priority::text),
          w.reported_on DESC, w.id
        """,
        {"property_id": property_id, "status": status, "open_only": open_only},
    ).fetchall()
    return [read_work_order(conn, row["id"]) for row in rows]


def create_work_order(conn: Conn, body: WorkOrderIn) -> WorkOrderOut:
    prop = conn.execute(
        "SELECT id::text FROM properties WHERE id = %s", (body.property_id,)
    ).fetchone()
    if prop is None:
        raise UnknownProperty(body.property_id)
    row = conn.execute(
        """
        INSERT INTO work_orders
          (property_id, unit_id, component_id, vendor_id, summary, detail, priority,
           reported_by, reported_on)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s, CURRENT_DATE))
        RETURNING id::text
        """,
        (
            body.property_id,
            body.unit_id,
            body.component_id,
            body.vendor_id,
            body.summary.strip(),
            body.detail,
            body.priority,
            body.reported_by,
            body.reported_on,
        ),
    ).fetchone()
    return read_work_order(conn, row["id"])


def transition(conn: Conn, work_order_id: str, body: TransitionIn) -> WorkOrderOut:
    # FOR UPDATE: the legality check below is a decision, not a guess about
    # what another request may be doing to this row right now.
    current = conn.execute(
        "SELECT status::text AS status, scheduled_for FROM work_orders WHERE id = %s FOR UPDATE",
        (work_order_id,),
    ).fetchone()
    if current is None:
        raise UnknownWorkOrder(work_order_id)
    if body.status not in LEGAL_TRANSITIONS[current["status"]]:
        raise IllegalTransition(current["status"], body.status)
    conn.execute(
        """
        UPDATE work_orders
        SET status = %s,
            scheduled_for = coalesce(%s, scheduled_for),
            vendor_id = coalesce(%s, vendor_id),
            cancelled_reason = coalesce(%s, cancelled_reason)
        WHERE id = %s
        """,
        (body.status, body.scheduled_for, body.vendor_id, body.cancelled_reason, work_order_id),
    )
    return read_work_order(conn, work_order_id)


# Not every dollar on a job flows the same way. A tenant reimbursing damage is
# rental income; a warranty credit is money back against the repair. Posting
# either as an outflow would overstate what the job cost AND misreport the
# income on Schedule E.
INFLOW_CATEGORIES: dict[str, str] = {
    "tenant_chargeback": "other_income",
    "warranty_credit": "repairs",  # a credit against the repair it refunds
}


def _post_cost(
    conn: Conn,
    *,
    work_order: dict[str, Any],
    cost: CostIn,
    occurred_on: dt.date,
    linked_by: str,
) -> str:
    """One ledger event, one association. The BAR answer is demanded before
    the money can be called capital."""
    if cost.is_capital is True and not (cost.capitalisation_rationale or "").strip():
        raise CapitalNeedsRationale(RESTORATION_CITATION)
    inflow_category = INFLOW_CATEGORIES.get(cost.relation)
    if inflow_category is not None:
        # A credit is money coming back; it is definitionally not a capital
        # election, so it never carries one.
        category = inflow_category
        amount = cost.amount
        is_capital: bool | None = False
        rationale: str | None = None
    else:
        category = "capital_improvement" if cost.is_capital else "repairs"
        amount = -cost.amount
        is_capital = cost.is_capital
        rationale = cost.capitalisation_rationale
    event = ledger_module.append_event(
        conn,
        ledger_module.LedgerEntryIn(
            occurred_on=occurred_on,
            category=category,
            amount=amount,
            memo=cost.memo or work_order["summary"],
            counterparty=cost.counterparty or work_order["vendor_name"],
            is_capital=is_capital,
            capitalisation_rationale=rationale,
            property_id=work_order["property_id"],
            unit_id=work_order["unit_id"],
            document_id=cost.document_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO work_order_ledger_events
          (work_order_id, ledger_event_id, relation, linked_by)
        SELECT %s, id, %s, %s FROM ledger_events WHERE event_uuid = %s
        """,
        (work_order["id"], cost.relation, linked_by, event.event_uuid),
    )
    return event.event_uuid


def complete(conn: Conn, work_order_id: str, body: CompletionIn, actor: str) -> CompletionOut:
    """The transaction that teaches the inventory.

    Order is dictated by the schema: a CHECK cannot be deferred, so the new
    component must exist before the order can call itself replaced. That is
    also the only order in which a failure leaves nothing half-migrated — the
    endpoint's rollback takes the component with it.
    """
    work_order = conn.execute(
        """
        SELECT w.id::text, w.property_id::text, w.unit_id::text, w.component_id::text,
               w.status::text AS status, w.summary, w.reported_on, v.name AS vendor_name
        FROM work_orders w LEFT JOIN vendors v ON v.id = w.vendor_id
        WHERE w.id = %s
        FOR UPDATE OF w
        """,
        (work_order_id,),
    ).fetchone()
    if work_order is None:
        raise UnknownWorkOrder(work_order_id)
    if work_order["status"] not in COMPLETABLE_FROM:
        raise AlreadyResolved(work_order["status"])
    if body.completed_on < work_order["reported_on"]:
        raise IllegalTransition(work_order["status"], "completed before it was reported")

    retired_id: str | None = None
    installed_id: str | None = None
    if body.resolution == "replaced":
        if work_order["component_id"] is None:
            raise MissingComponent(work_order_id)
        old = conn.execute(
            """
            SELECT id::text, property_id::text, unit_id::text, component_type_id::text,
                   quantity, retired_on
            FROM components WHERE id = %s FOR UPDATE
            """,
            (work_order["component_id"],),
        ).fetchone()
        if old["retired_on"] is not None:
            raise ComponentAlreadyRetired(old["id"])
        spec = body.replacement or ReplacementIn()
        installed_on = spec.installed_on or body.completed_on
        # The install date is now KNOWN, and it is known because someone did
        # the work — owner_stated, which the schema holds to confidence 1.0.
        provenance = conn.execute(
            """
            INSERT INTO provenance (kind, confidence, source_label)
            VALUES ('owner_stated', 1.0, %s) RETURNING id::text
            """,
            (f"work order completion {body.completed_on}: {work_order['summary']}",),
        ).fetchone()
        new = conn.execute(
            """
            INSERT INTO components
              (property_id, unit_id, component_type_id, installed_on, provenance_id,
               quantity, condition, warranty_expires_on, expected_life_years,
               replacement_cost, notes)
            VALUES (%s, %s, %s, %s, %s, %s, 'new', %s, %s, %s, %s)
            RETURNING id::text
            """,
            (
                old["property_id"],
                old["unit_id"],
                spec.component_type_id or old["component_type_id"],
                installed_on,
                provenance["id"],
                spec.quantity if spec.quantity is not None else old["quantity"],
                spec.warranty_expires_on,
                spec.expected_life_years,
                spec.replacement_cost
                if spec.replacement_cost is not None
                else (body.cost.amount if body.cost else None),
                spec.notes,
            ),
        ).fetchone()
        installed_id = new["id"]
        retired_id = old["id"]
        conn.execute(
            """
            UPDATE components
            SET retired_on = %s, replaced_by_id = %s, condition = 'failed'
            WHERE id = %s
            """,
            (body.completed_on, installed_id, retired_id),
        )

    # One statement closes the order: status, resolution and the installed
    # component arrive together, so no CHECK sees a half-written completion.
    conn.execute(
        """
        UPDATE work_orders
        SET status = 'completed', completed_on = %s, resolution = %s,
            resolution_note = %s, replacement_component_id = %s
        WHERE id = %s
        """,
        (body.completed_on, body.resolution, body.resolution_note, installed_id, work_order_id),
    )

    event_uuid: str | None = None
    citation: str | None = None
    if body.cost is not None:
        event_uuid = _post_cost(
            conn,
            work_order=work_order,
            cost=body.cost,
            occurred_on=body.cost.occurred_on or body.completed_on,
            linked_by=actor,
        )
        citation = _bar_citation(body.cost.is_capital, body.cost.amount)
    return CompletionOut(
        work_order=read_work_order(conn, work_order_id),
        retired_component_id=retired_id,
        installed_component_id=installed_id,
        ledger_event_uuid=event_uuid,
        capitalisation_citation=citation,
    )


class CostLinkIn(BaseModel):
    """Either a new cost to post, or an existing ledger event to associate."""

    cost: CostIn | None = None
    ledger_event_uuid: uuid.UUID | None = None
    relation: CostRelation = "invoice"


def add_cost(conn: Conn, work_order_id: str, body: CostLinkIn, actor: str) -> WorkOrderOut:
    work_order = conn.execute(
        """
        SELECT w.id::text, w.property_id::text, w.unit_id::text, w.summary,
               v.name AS vendor_name
        FROM work_orders w LEFT JOIN vendors v ON v.id = w.vendor_id
        WHERE w.id = %s
        """,
        (work_order_id,),
    ).fetchone()
    if work_order is None:
        raise UnknownWorkOrder(work_order_id)
    if body.cost is not None:
        _post_cost(
            conn,
            work_order=work_order,
            cost=body.cost,
            occurred_on=body.cost.occurred_on or dt.date.today(),
            linked_by=actor,
        )
    else:
        event = conn.execute(
            "SELECT id, property_id::text FROM ledger_events WHERE event_uuid = %s",
            (body.ledger_event_uuid,),
        ).fetchone()
        if event is None:
            raise ledger_module.UnknownEvent(str(body.ledger_event_uuid))
        if event["property_id"] not in (None, work_order["property_id"]):
            raise WrongProperty(event["property_id"])
        conn.execute(
            """
            INSERT INTO work_order_ledger_events
              (work_order_id, ledger_event_id, relation, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (work_order_id, ledger_event_id) DO NOTHING
            """,
            (work_order_id, event["id"], body.relation, actor),
        )
    return read_work_order(conn, work_order_id)
