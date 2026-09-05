"""The FastAPI application: the typed contract over the ledger.

Small on purpose — health, a first anchoring slice of CRUD, and the sweep —
but the conventions it sets are the service's constitution: every request
carries a correlation id, every mutation commits its audit row in the same
transaction, every error is a typed shape, and the OpenAPI document IS the
contract the web client will be generated from.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Annotated, Any, Literal

import psycopg
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hestia_api import (
    appeal,
    assessments,
    bank_import,
    config,
    coverage,
    db,
    debt,
    deposit,
    documents,
    dossier,
    income_tax,
    jurisdiction,
    ledger,
    maintenance,
    payments,
    rent,
    reports,
    screening,
    sweep,
    views,
)

app = FastAPI(
    title="Hestia API",
    version="0.1.0",
    description="The owner's operating platform for real property.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.web_origin()],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "x-request-id", "x-actor"],
    expose_headers=["x-request-id"],
)


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


@app.middleware("http")
async def correlate(request: Request, call_next):  # type: ignore[no-untyped-def]
    request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response: Response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def get_conn() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    yield from db.connection_for(config.database_url())


# scope="function" is load-bearing, not decoration. It puts the connection on
# the exit stack FastAPI unwinds BEFORE sending the response, rather than the
# default one it unwinds after — so the commit finishes while the caller is
# still waiting, and the answer it gets describes state that already exists.
# Issue #83; see db.connection_for and tests/test_transaction_boundary.py.
Conn = Annotated[psycopg.Connection[dict[str, Any]], Depends(get_conn, scope="function")]
Actor = Annotated[str, Header(alias="x-actor")]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class Health(BaseModel):
    status: Literal["alive"]


class Readiness(BaseModel):
    status: Literal["ready"]
    migrations: int


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="alive")


@app.get("/readyz", response_model=Readiness)
def readyz(conn: Conn) -> Readiness:
    row = conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()
    return Readiness(status="ready", migrations=int(row["n"]) if row else 0)


# ---------------------------------------------------------------------------
# Entities and properties — the anchoring slice
# ---------------------------------------------------------------------------


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal[
        "individual",
        "joint",
        "llc",
        "series_llc_cell",
        "limited_partnership",
        "s_corporation",
        "c_corporation",
        "revocable_trust",
        "irrevocable_trust",
        "land_trust",
    ]
    formation_state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class EntityOut(EntityIn):
    id: uuid.UUID


class PropertyIn(BaseModel):
    entity_id: uuid.UUID
    label: str = Field(min_length=1, max_length=200)
    street_1: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    postal_code: str = Field(min_length=3, max_length=10)
    kind: Literal[
        "single_family",
        "duplex",
        "triplex",
        "fourplex",
        "small_multifamily",
        "condominium",
        "townhouse",
        "manufactured",
        "mixed_use",
        "land",
    ]
    year_built: int | None = Field(default=None, ge=1600, le=2200)
    # Disambiguates municipalities whose names collide within a state
    # (Ohio's twenty Washington Townships); optional everywhere else.
    county: str | None = Field(default=None, min_length=1)


class PropertyOut(PropertyIn):
    id: uuid.UUID
    # The most specific governing body the loaded packs can name; None means
    # no pack covers this state yet, which the coverage report surfaces.
    jurisdiction_id: uuid.UUID | None


@app.post("/entities", response_model=EntityOut, status_code=201)
def create_entity(
    body: EntityIn, conn: Conn, request: Request, actor: Actor = "system"
) -> EntityOut:
    row = conn.execute(
        """
        INSERT INTO entities (name, kind, formation_state)
        VALUES (%s, %s, %s) RETURNING id
        """,
        (body.name, body.kind, body.formation_state),
    ).fetchone()
    entity = EntityOut(id=row["id"], **body.model_dump())  # type: ignore[index]
    db.record_audit(
        conn,
        actor=actor,
        action="entity.create",
        request_id=request.state.request_id,
        table_name="entities",
        record_id=str(entity.id),
        after_value=entity.model_dump(mode="json"),
    )
    return entity


@app.get("/entities", response_model=list[EntityOut])
def list_entities(conn: Conn) -> list[EntityOut]:
    rows = conn.execute(
        "SELECT id, name, kind, formation_state FROM entities ORDER BY created_at"
    ).fetchall()
    return [EntityOut(**row) for row in rows]


@app.post("/properties", response_model=PropertyOut, status_code=201)
def create_property(
    body: PropertyIn, conn: Conn, request: Request, actor: Actor = "system"
) -> PropertyOut:
    resolved = jurisdiction.resolve(conn, state=body.state, city=body.city, county=body.county)
    try:
        row = conn.execute(
            """
            INSERT INTO properties
              (entity_id, label, street_1, city, state, postal_code, county,
               kind, year_built, jurisdiction_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                str(body.entity_id),
                body.label,
                body.street_1,
                body.city,
                body.state,
                body.postal_code,
                body.county,
                body.kind,
                body.year_built,
                resolved.jurisdiction_id,
            ),
        ).fetchone()
    except psycopg.errors.ForeignKeyViolation as error:
        # Name the FK that actually failed: the resolver runs before the
        # INSERT, so a jurisdiction row vanishing in between raises the
        # jurisdiction FK — blaming entity_id for that would be false.
        if error.diag.constraint_name == "properties_entity_id_fkey":
            detail = "entity_id does not exist"
        else:
            detail = "resolved jurisdiction no longer exists; retry the request"
        raise HTTPException(status_code=422, detail=detail) from error
    prop = PropertyOut(
        id=row["id"],  # type: ignore[index]
        jurisdiction_id=resolved.jurisdiction_id,
        **body.model_dump(),
    )
    db.record_audit(
        conn,
        actor=actor,
        action="property.create",
        request_id=request.state.request_id,
        table_name="properties",
        record_id=str(prop.id),
        after_value=prop.model_dump(mode="json"),
    )
    return prop


@app.get("/properties/{property_id}", response_model=PropertyOut)
def get_property(property_id: uuid.UUID, conn: Conn) -> PropertyOut:
    row = conn.execute(
        """
        SELECT id, entity_id, label, street_1, city, state, postal_code, county,
               kind, year_built, jurisdiction_id
        FROM properties WHERE id = %s
        """,
        (str(property_id),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="property not found")
    return PropertyOut(**row)


# ---------------------------------------------------------------------------
# The ledger — append-only, reversal-corrected
# ---------------------------------------------------------------------------


@app.post("/ledger", response_model=ledger.LedgerEventOut, status_code=201)
def append_ledger_event(
    body: ledger.LedgerEntryIn, conn: Conn, request: Request, actor: Actor = "system"
) -> ledger.LedgerEventOut:
    try:
        event = ledger.append_event(conn, body)
    except psycopg.errors.ForeignKeyViolation as error:
        anchor = (
            (error.diag.constraint_name or "anchor")
            .removeprefix("ledger_events_")
            .removesuffix("_fkey")
        )
        raise HTTPException(status_code=422, detail=f"{anchor} does not exist") from error
    db.record_audit(
        conn,
        actor=actor,
        action="ledger.append",
        request_id=request.state.request_id,
        table_name="ledger_events",
        record_id=event.event_uuid,
        after_value=event.model_dump(mode="json"),
    )
    return event


@app.post("/ledger/{event_uuid}/reverse", response_model=ledger.ReversalOut, status_code=201)
def reverse_ledger_event(
    event_uuid: uuid.UUID,
    body: ledger.ReversalIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> ledger.ReversalOut:
    try:
        result = ledger.reverse_event(conn, str(event_uuid), body)
    except ledger.UnknownEvent as error:
        raise HTTPException(status_code=404, detail="ledger event not found") from error
    except ledger.AlreadyReversed as error:
        raise HTTPException(
            status_code=409, detail="event is already reversed; correct the correction instead"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="ledger.reverse",
        request_id=request.state.request_id,
        table_name="ledger_events",
        record_id=result.reversal.event_uuid,
        after_value=result.model_dump(mode="json"),
    )
    return result


@app.get("/ledger", response_model=ledger.LedgerRegister)
def ledger_register(
    conn: Conn,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
    category: Annotated[ledger.LedgerCategory | None, Query()] = None,
    occurred_from: Annotated[dt.date | None, Query()] = None,
    occurred_to: Annotated[dt.date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> ledger.LedgerRegister:
    return ledger.register(
        conn,
        property_id=str(property_id) if property_id else None,
        category=category,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Bank import — file -> staging -> review -> ledger, append-only preserved
# ---------------------------------------------------------------------------


@app.post("/bank/accounts", response_model=bank_import.BankAccountOut, status_code=201)
def create_bank_account(
    body: bank_import.BankAccountIn, conn: Conn, request: Request, actor: Actor = "system"
) -> bank_import.BankAccountOut:
    try:
        account = bank_import.create_account(conn, body)
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(status_code=422, detail="entity or property does not exist") from error
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(
            status_code=409, detail="an account with this nickname already exists"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="bank.account.create",
        request_id=request.state.request_id,
        table_name="bank_accounts",
        record_id=account.id,
        after_value=account.model_dump(mode="json"),
    )
    return account


@app.get("/bank/accounts", response_model=list[bank_import.BankAccountOut])
def list_bank_accounts(conn: Conn) -> list[bank_import.BankAccountOut]:
    return bank_import.list_accounts(conn)


@app.post(
    "/bank/accounts/{account_id}/imports",
    response_model=bank_import.ImportSummary,
    status_code=201,
)
async def import_bank_statement(
    account_id: uuid.UUID,
    conn: Conn,
    request: Request,
    file: Annotated[UploadFile, File()],
    actor: Actor = "system",
) -> bank_import.ImportSummary:
    content = await file.read()
    try:
        summary = bank_import.import_statement(
            conn,
            str(account_id),
            filename=file.filename or "statement",
            content=content,
            imported_by=actor,
        )
    except bank_import.UnknownAccount as error:
        raise HTTPException(status_code=404, detail="bank account not found") from error
    except bank_import.DuplicateStatement as error:
        raise HTTPException(
            status_code=409, detail="this exact file was already imported"
        ) from error
    except bank_import.statement_parse.StatementParseError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.record_audit(
        conn,
        actor=actor,
        action="bank.import",
        request_id=request.state.request_id,
        table_name="bank_import_batches",
        record_id=summary.batch_id,
        after_value=summary.model_dump(mode="json"),
    )
    return summary


@app.get(
    "/bank/imports/{batch_id}/transactions",
    response_model=list[bank_import.StagedTransaction],
)
def bank_review_queue(
    batch_id: uuid.UUID,
    conn: Conn,
    disposition: Annotated[
        Literal["pending", "accepted", "excluded", "duplicate", "matched_existing"] | None,
        Query(),
    ] = None,
) -> list[bank_import.StagedTransaction]:
    return bank_import.review_queue(conn, str(batch_id), disposition)


def _bank_txn_errors(error: Exception) -> HTTPException:
    if isinstance(error, bank_import.UnknownTransaction):
        return HTTPException(status_code=404, detail="not found")
    if isinstance(error, bank_import.NotPending):
        return HTTPException(
            status_code=409, detail="row already has a disposition; review is not re-made"
        )
    return HTTPException(status_code=422, detail=str(error))


@app.post(
    "/bank/transactions/{txn_id}/accept",
    response_model=list[ledger.LedgerEventOut],
    status_code=201,
)
def accept_bank_transaction(
    txn_id: uuid.UUID,
    body: bank_import.AcceptIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> list[ledger.LedgerEventOut]:
    try:
        events = bank_import.accept(conn, str(txn_id), body)
    except (
        bank_import.UnknownTransaction,
        bank_import.NotPending,
        bank_import.SplitMismatch,
    ) as error:
        raise _bank_txn_errors(error) from error
    db.record_audit(
        conn,
        actor=actor,
        action="bank.accept",
        request_id=request.state.request_id,
        table_name="bank_transactions",
        record_id=str(txn_id),
        after_value={"events": [event.event_uuid for event in events]},
    )
    return events


@app.post("/bank/transactions/{txn_id}/exclude", status_code=204)
def exclude_bank_transaction(
    txn_id: uuid.UUID, conn: Conn, request: Request, actor: Actor = "system"
) -> None:
    try:
        bank_import.exclude(conn, str(txn_id))
    except (bank_import.UnknownTransaction, bank_import.NotPending) as error:
        raise _bank_txn_errors(error) from error
    db.record_audit(
        conn,
        actor=actor,
        action="bank.exclude",
        request_id=request.state.request_id,
        table_name="bank_transactions",
        record_id=str(txn_id),
    )


class MatchIn(BaseModel):
    event_uuid: uuid.UUID


@app.post("/bank/transactions/{txn_id}/match", status_code=204)
def match_bank_transaction(
    txn_id: uuid.UUID,
    body: MatchIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> None:
    try:
        bank_import.match_existing(conn, str(txn_id), str(body.event_uuid))
    except (
        bank_import.UnknownTransaction,
        bank_import.NotPending,
        bank_import.MatchMismatch,
    ) as error:
        raise _bank_txn_errors(error) from error
    db.record_audit(
        conn,
        actor=actor,
        action="bank.match",
        request_id=request.state.request_id,
        table_name="bank_transactions",
        record_id=str(txn_id),
        after_value={"event_uuid": str(body.event_uuid)},
    )


# ---------------------------------------------------------------------------
# Reads — the dossier as a document (never a blank state)
# ---------------------------------------------------------------------------


@app.get("/properties", response_model=list[views.PropertySummary])
def list_properties(conn: Conn) -> list[views.PropertySummary]:
    return views.list_properties(conn)


@app.get("/properties/{property_id}/dossier", response_model=views.DossierView)
def read_dossier(property_id: uuid.UUID, conn: Conn) -> views.DossierView:
    view = views.dossier_view(conn, str(property_id))
    if view is None:
        raise HTTPException(status_code=404, detail="property not found")
    return view


@app.get("/deadlines", response_model=list[views.DeadlineOut])
def list_deadlines(
    conn: Conn,
    due_before: Annotated[dt.date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[views.DeadlineOut]:
    return views.upcoming_deadlines(conn, due_before=due_before, limit=limit)


# ---------------------------------------------------------------------------
# Leases & rent — charges outside the ledger, receipts through it
# ---------------------------------------------------------------------------


def _audit(
    conn: Conn,
    request: Request,
    actor: str,
    action: str,
    table: str,
    record_id: str,
    after: dict[str, Any] | None = None,
) -> None:
    db.record_audit(
        conn,
        actor=actor,
        action=action,
        request_id=request.state.request_id,
        table_name=table,
        record_id=record_id,
        after_value=after,
    )


@app.post("/units", status_code=201)
def create_unit(
    body: rent.UnitIn, conn: Conn, request: Request, actor: Actor = "system"
) -> dict[str, str]:
    try:
        unit_id = rent.create_unit(conn, body)
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(status_code=422, detail="property does not exist") from error
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(
            status_code=409, detail="this property already has a unit with that label"
        ) from error
    _audit(conn, request, actor, "unit.create", "units", unit_id, body.model_dump(mode="json"))
    return {"id": unit_id}


@app.post("/residents", status_code=201)
def create_resident(
    body: rent.ResidentIn, conn: Conn, request: Request, actor: Actor = "system"
) -> dict[str, str]:
    resident_id = rent.create_resident(conn, body)
    _audit(
        conn,
        request,
        actor,
        "resident.create",
        "residents",
        resident_id,
        body.model_dump(mode="json"),
    )
    return {"id": resident_id}


@app.post("/leases", status_code=201)
def create_lease(
    body: rent.LeaseIn, conn: Conn, request: Request, actor: Actor = "system"
) -> dict[str, str]:
    try:
        lease_id = rent.create_lease(conn, body)
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(status_code=422, detail="unit or resident does not exist") from error
    except psycopg.errors.ExclusionViolation as error:
        raise HTTPException(
            status_code=409, detail="the unit already has a live lease for that period"
        ) from error
    _audit(
        conn,
        request,
        actor,
        "lease.create",
        "leases",
        lease_id,
        body.model_dump(mode="json"),
    )
    return {"id": lease_id}


@app.get("/leases", response_model=list[rent.LeaseSummary])
def list_leases(conn: Conn) -> list[rent.LeaseSummary]:
    return rent.list_leases(conn)


@app.get("/leases/{lease_id}", response_model=rent.LeaseDetail)
def lease_detail(lease_id: uuid.UUID, conn: Conn) -> rent.LeaseDetail:
    try:
        return rent.lease_detail(conn, str(lease_id))
    except rent.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error


@app.post("/sweep/rent-charges", response_model=rent.RentSweepResult)
def sweep_rent_charges(
    conn: Conn,
    request: Request,
    as_of: Annotated[dt.date | None, Query()] = None,
    actor: Actor = "system",
) -> rent.RentSweepResult:
    effective = as_of if as_of is not None else dt.date.today()
    result = rent.sweep_rent_charges(conn, effective)
    db.record_audit(
        conn,
        actor=actor,
        action="rent.sweep",
        request_id=request.state.request_id,
        table_name="rent_charges",
        after_value={"as_of": str(effective), **result.model_dump(mode="json")},
    )
    return result


@app.post("/sweep/late-fees", response_model=rent.RentSweepResult)
def sweep_late_fees(
    conn: Conn,
    request: Request,
    as_of: Annotated[dt.date | None, Query()] = None,
    actor: Actor = "system",
) -> rent.RentSweepResult:
    effective = as_of if as_of is not None else dt.date.today()
    result = rent.sweep_late_fees(conn, effective)
    db.record_audit(
        conn,
        actor=actor,
        action="latefee.sweep",
        request_id=request.state.request_id,
        table_name="rent_charges",
        after_value={"as_of": str(effective), **result.model_dump(mode="json")},
    )
    return result


@app.post("/leases/{lease_id}/receipts", response_model=rent.ReceiptOut, status_code=201)
def record_receipt(
    lease_id: uuid.UUID,
    body: rent.ReceiptIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> rent.ReceiptOut:
    try:
        receipt = rent.record_receipt(conn, str(lease_id), body)
    except rent.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error
    _audit(
        conn,
        request,
        actor,
        "rent.receipt",
        "ledger_events",
        receipt.event_uuid,
        receipt.model_dump(mode="json"),
    )
    return receipt


class WaiveIn(BaseModel):
    reason: str = Field(min_length=3)


@app.post("/rent-charges/{charge_id}/waive", status_code=204)
def waive_charge(
    charge_id: uuid.UUID,
    body: WaiveIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> None:
    """Waive forgives the UNPAID remainder; paid allocations stay.

    The convention, stated where callers can find it (issue #137): money
    already allocated to the charge remains payment for it — a tenant who
    paid 500 of 1450 and is then waived was forgiven 950, not refunded
    500. Nothing is released back to open credit, the balance arithmetic
    excludes both the waived amount and its allocations (net zero: the
    charge is settled), and the audit record carries the forgiven figure.
    A fully paid charge has nothing to forgive and is not waivable.
    """
    charge = conn.execute(
        """
        SELECT c.amount - coalesce((SELECT sum(a.amount)
                                    FROM rent_receipt_allocations a
                                    WHERE a.charge_id = c.id), 0) AS forgiven
        FROM rent_charges c
        WHERE c.id = %s AND c.status IN ('scheduled', 'due', 'partially_paid')
        FOR UPDATE OF c
        """,
        (str(charge_id),),
    ).fetchone()
    if charge is None:
        raise HTTPException(status_code=404, detail="no waivable charge found")
    conn.execute(
        "UPDATE rent_charges SET status = 'waived', waived_reason = %s WHERE id = %s",
        (body.reason, str(charge_id)),
    )
    _audit(
        conn,
        request,
        actor,
        "rent.waive",
        "rent_charges",
        str(charge_id),
        {"reason": body.reason, "forgiven": str(charge["forgiven"])},
    )


@app.post("/rent-charges/{charge_id}/correct", response_model=rent.CorrectionOut)
def correct_charge(
    charge_id: uuid.UUID,
    body: rent.CorrectionIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> rent.CorrectionOut:
    """Correct a wrong charge by supersession (issue #105): the old row
    becomes history pointing at its successor; paid money is released to
    open credit and re-applied. Superseded, waived, and written-off charges
    are not correctable — correct the LIVE row to extend a chain."""
    try:
        result = rent.correct_charge(conn, str(charge_id), body)
    except rent.UncorrectableCharge as error:
        raise HTTPException(status_code=404, detail="no correctable charge found") from error
    _audit(
        conn,
        request,
        actor,
        "rent.correct",
        "rent_charges",
        str(charge_id),
        {
            "reason": body.reason,
            "new_amount": str(body.amount),
            "new_charge_id": result.new_charge_id,
            "released": str(result.released),
        },
    )
    return result


@app.get("/leases/{lease_id}/renewal-context", response_model=rent.RenewalContextOut)
def renewal_context(lease_id: uuid.UUID, conn: Conn) -> rent.RenewalContextOut:
    try:
        return rent.renewal_context(conn, str(lease_id))
    except rent.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error


@app.post("/leases/{lease_id}/renewals", status_code=201)
def record_renewal(
    lease_id: uuid.UUID,
    body: rent.RenewalOfferIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> dict[str, str]:
    try:
        renewal_id = rent.record_renewal_offer(conn, str(lease_id), body)
    except rent.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error
    _audit(
        conn,
        request,
        actor,
        "renewal.offer",
        "lease_renewals",
        renewal_id,
        body.model_dump(mode="json"),
    )
    return {"id": renewal_id}


# ---------------------------------------------------------------------------
# Payments — the processor seam (test keys today, live keys when the bank is)
# ---------------------------------------------------------------------------


class CollectIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, decimal_places=2, max_digits=18)


@app.post("/leases/{lease_id}/collect", response_model=payments.CollectOut, status_code=201)
def collect_rent(
    lease_id: uuid.UUID,
    body: CollectIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> payments.CollectOut:
    secret_key = config.stripe_secret_key()
    if secret_key is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "payments are not configured: set HESTIA_STRIPE_SECRET_KEY "
                "(test-mode keys work before the business bank exists)"
            ),
        )
    try:
        result = payments.collect(
            conn,
            str(lease_id),
            amount=body.amount,
            transport=payments.live_transport,
            secret_key=secret_key,
        )
    except rent.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error
    except rent.NothingOutstanding as error:
        raise HTTPException(status_code=422, detail="nothing outstanding to collect") from error
    except payments.OpenPaymentExists as error:
        raise HTTPException(
            status_code=409,
            detail=f"a payment is already in flight for this lease ({error})",
        ) from error
    except payments.TransportFailure as error:
        raise HTTPException(
            status_code=502, detail=f"payment provider unreachable: {error}"
        ) from error
    _audit(
        conn,
        request,
        actor,
        "payment.collect",
        "payment_requests",
        result.payment_request_id,
        result.model_dump(mode="json"),
    )
    return result


@app.post("/payments/stripe/webhook")
async def stripe_webhook(request: Request, conn: Conn) -> dict[str, str]:
    payload = await request.body()
    header = request.headers.get("stripe-signature", "")
    try:
        secret = config.stripe_webhook_secret()  # config-audit: allow — env-sourced, not a literal
    except config.ConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        event = payments.verify_signature(payload, header, secret, now=dt.datetime.now(tz=dt.UTC))
    except payments.BadSignature as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    outcome = payments.handle_event(conn, event)
    db.record_audit(
        conn,
        actor="stripe",
        action="payment.webhook",
        request_id=request.state.request_id,
        after_value={"type": event.get("type"), "outcome": outcome},
    )
    return {"outcome": outcome}


# ---------------------------------------------------------------------------
# Reports — the ledger rolled up, with authorities attached
# ---------------------------------------------------------------------------


def _require_property(conn: Conn, property_id: uuid.UUID) -> None:
    row = conn.execute(
        "SELECT 1 AS x FROM properties WHERE id = %s", (str(property_id),)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="property not found")


@app.get(
    "/properties/{property_id}/reports/schedule-e",
    response_model=reports.ScheduleEReport,
)
def schedule_e_report(
    property_id: uuid.UUID, conn: Conn, tax_year: Annotated[int, Query(ge=1990, le=2200)]
) -> reports.ScheduleEReport:
    _require_property(conn, property_id)
    return reports.schedule_e(conn, str(property_id), tax_year)


@app.get(
    "/properties/{property_id}/reports/cash-flow",
    response_model=reports.CashFlowReport,
)
def cash_flow_report(
    property_id: uuid.UUID, conn: Conn, year: Annotated[int, Query(ge=1990, le=2200)]
) -> reports.CashFlowReport:
    _require_property(conn, property_id)
    return reports.cash_flow(conn, str(property_id), year)


@app.get("/reports/rent-roll", response_model=list[reports.RentRollRow])
def rent_roll_report(conn: Conn) -> list[reports.RentRollRow]:
    return reports.rent_roll(conn)


@app.get("/properties/{property_id}/tax-rates", response_model=income_tax.PropertyTaxRates)
def property_tax_rates(
    property_id: uuid.UUID,
    conn: Conn,
    tax_year: Annotated[int, Query(ge=1990, le=2200)],
) -> income_tax.PropertyTaxRates:
    """Every taxing body that reaches this property, and what each levies.

    tax_year is required and has no default: a rate is a fact about a year,
    and defaulting to today's would silently answer a different question than
    the one a filing asks."""
    _require_property(conn, property_id)
    return income_tax.for_property(conn, str(property_id), tax_year=tax_year)


@app.get("/entities/{entity_id}/tax-rates", response_model=income_tax.EntityTaxRates)
def entity_tax_rates(
    entity_id: uuid.UUID,
    conn: Conn,
    tax_year: Annotated[int, Query(ge=1990, le=2200)],
) -> income_tax.EntityTaxRates:
    """The cross-river case: one entity, each property answering from its own
    chain. Nothing is aggregated — an entity owning across a state line is
    reached by more than one government, and no single rate is true of it."""
    try:
        return income_tax.for_entity(conn, str(entity_id), tax_year=tax_year)
    except income_tax.UnknownEntity as error:
        raise HTTPException(status_code=404, detail="entity not found") from error


@app.get("/properties/{property_id}/appeal", response_model=appeal.AppealCase)
def property_appeal(
    property_id: uuid.UUID,
    conn: Conn,
    as_of: Annotated[dt.date | None, Query()] = None,
) -> appeal.AppealCase:
    """404 is the only error this can return. Every "we cannot answer" is a
    named gap inside a 200, because a card that vanishes tells the owner
    nothing about why."""
    _require_property(conn, property_id)
    return appeal.read(
        conn, str(property_id), as_of=as_of if as_of is not None else dt.date.today()
    )


@app.get("/properties/{property_id}/financials", response_model=reports.Financials)
def property_financials(
    property_id: uuid.UUID,
    conn: Conn,
    as_of: Annotated[dt.date | None, Query()] = None,
) -> reports.Financials:
    _require_property(conn, property_id)
    return reports.financials(
        conn, str(property_id), as_of if as_of is not None else dt.date.today()
    )


@app.get(
    "/properties/{property_id}/capex-forecast",
    response_model=reports.CapexForecastOut,
)
def property_capex_forecast(
    property_id: uuid.UUID,
    conn: Conn,
    horizon_years: Annotated[int, Query(ge=1, le=30)] = 10,
    as_of: Annotated[dt.date | None, Query()] = None,
) -> reports.CapexForecastOut:
    _require_property(conn, property_id)
    return reports.capex_forecast(
        conn,
        str(property_id),
        horizon_years=horizon_years,
        as_of=as_of if as_of is not None else dt.date.today(),
    )


class SignoffIn(BaseModel):
    property_id: uuid.UUID
    tax_year: int
    report_kind: Literal["schedule_e", "p_and_l", "cash_flow"]
    confirmed_by: str
    note: str | None = None


@app.post("/reports/signoff", status_code=201)
def signoff_report(
    body: SignoffIn, conn: Conn, request: Request, actor: Actor = "system"
) -> dict[str, str]:
    _require_property(conn, body.property_id)
    # Certify the NUMBERS as they stand right now: a later back-dated
    # correction makes the sign-off visibly stale instead of silently
    # borrowing the reviewer's name.
    live = reports.schedule_e(conn, str(body.property_id), body.tax_year)
    try:
        row = conn.execute(
            """
            INSERT INTO report_signoffs
              (property_id, tax_year, report_kind, confirmed_by, note,
               certified_income, certified_expenses, certified_depreciation,
               certified_net)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
            """,
            (
                str(body.property_id),
                body.tax_year,
                body.report_kind,
                body.confirmed_by,
                body.note,
                live.total_income,
                live.total_expenses,
                live.depreciation_line_18,
                live.net,
            ),
        ).fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(
            status_code=409, detail="this report year is already signed off"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="report.signoff",
        request_id=request.state.request_id,
        table_name="report_signoffs",
        record_id=row["id"],  # type: ignore[index]
        after_value=body.model_dump(mode="json"),
    )
    return {"id": row["id"]}  # type: ignore[index]


class ValuationIn(BaseModel):
    property_id: uuid.UUID
    value: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    source: Literal[
        "avm",
        "appraisal",
        "broker_opinion",
        "assessor",
        "purchase_price",
        "comparable_sales",
        "owner_estimate",
        "replacement_cost_estimate",
    ]
    as_of: dt.date


@app.post("/valuations", status_code=201)
def create_valuation(
    body: ValuationIn, conn: Conn, request: Request, actor: Actor = "system"
) -> dict[str, str]:
    _require_property(conn, body.property_id)
    provenance = conn.execute(
        """
        INSERT INTO provenance (kind, confidence, source_label)
        VALUES ('owner_stated', 1.0, %s) RETURNING id
        """,
        (f"valuation entered by {actor}",),
    ).fetchone()
    row = conn.execute(
        """
        INSERT INTO valuations (property_id, as_of, source, value, provenance_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING id::text
        """,
        (
            str(body.property_id),
            body.as_of,
            body.source,
            body.value,
            provenance["id"],  # type: ignore[index]
        ),
    ).fetchone()
    db.record_audit(
        conn,
        actor=actor,
        action="valuation.create",
        request_id=request.state.request_id,
        table_name="valuations",
        record_id=row["id"],  # type: ignore[index]
        after_value=body.model_dump(mode="json"),
    )
    return {"id": row["id"]}  # type: ignore[index]


class CoverageIn(BaseModel):
    description: str
    limit_amount: Decimal | None = None
    peril: str = "all_other"
    months_covered: int | None = None


class PolicyIn(BaseModel):
    property_id: uuid.UUID
    kind: Literal[
        "dwelling_fire",
        "landlord_package",
        "homeowners",
        "commercial_property",
        "general_liability",
        "umbrella",
        "flood_nfip",
        "flood_private",
        "earthquake",
        "builders_risk",
        "rent_guarantee",
    ]
    carrier: str | None = None
    effective_from: dt.date
    effective_to: dt.date
    annual_premium: Decimal | None = None
    coinsurance_percent: Decimal | None = Field(default=None, ge=0, le=1)
    coverages: list[CoverageIn] = []


@app.post("/policies", status_code=201)
def create_policy(
    body: PolicyIn, conn: Conn, request: Request, actor: Actor = "system"
) -> dict[str, str]:
    _require_property(conn, body.property_id)
    row = conn.execute(
        """
        INSERT INTO policies
          (property_id, kind, carrier, effective_from, effective_to,
           annual_premium, coinsurance_percent)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (
            str(body.property_id),
            body.kind,
            body.carrier,
            body.effective_from,
            body.effective_to,
            body.annual_premium,
            body.coinsurance_percent,
        ),
    ).fetchone()
    for coverage_in in body.coverages:
        conn.execute(
            """
            INSERT INTO coverages
              (policy_id, description, limit_amount, peril, months_covered)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                row["id"],  # type: ignore[index]
                coverage_in.description,
                coverage_in.limit_amount,
                coverage_in.peril,
                coverage_in.months_covered,
            ),
        )
    db.record_audit(
        conn,
        actor=actor,
        action="policy.create",
        request_id=request.state.request_id,
        table_name="policies",
        record_id=row["id"],  # type: ignore[index]
        after_value=body.model_dump(mode="json"),
    )
    return {"id": row["id"]}  # type: ignore[index]


# ---------------------------------------------------------------------------
# The dossier — the magic moment, as one endpoint
# ---------------------------------------------------------------------------


class DossierStepOut(BaseModel):
    name: str
    status: Literal["ok", "skipped", "failed"]
    detail: str


class DossierOut(BaseModel):
    property_id: uuid.UUID
    as_of: dt.date
    steps: list[DossierStepOut]
    sweep: dict[str, Any]


@app.post("/properties/{property_id}/dossier", response_model=DossierOut)
def assemble_dossier(
    property_id: uuid.UUID,
    conn: Conn,
    request: Request,
    as_of: Annotated[dt.date | None, Query()] = None,
    actor: Actor = "system",
) -> DossierOut:
    effective = as_of if as_of is not None else dt.date.today()
    try:
        result = dossier.assemble(conn, str(property_id), fetch=dossier.live_fetch, as_of=effective)
    except dossier.PropertyNotFound as error:
        raise HTTPException(status_code=404, detail="property not found") from error
    db.record_audit(
        conn,
        actor=actor,
        action="dossier.assemble",
        request_id=request.state.request_id,
        table_name="properties",
        record_id=str(property_id),
        after_value={"steps": result["steps"], "sweep": result["sweep"]["inserted"]},
    )
    return DossierOut(**result)


# ---------------------------------------------------------------------------
# Coverage — what the platform knows, per property, honestly (ADR 0003)
# ---------------------------------------------------------------------------


@app.get("/coverage/jurisdictions", response_model=coverage.CoverageReport)
def coverage_jurisdictions(
    conn: Conn, as_of: Annotated[dt.date | None, Query()] = None
) -> coverage.CoverageReport:
    return coverage.report(conn, as_of if as_of is not None else dt.date.today())


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


class SweepGapOut(BaseModel):
    property_id: uuid.UUID
    state: str
    domain: str
    reason: Literal[
        "no_state_jurisdiction",
        "no_rule_for_domain",
        "calendar_key_unregistered",
        # The pack says this state publishes its window rather than
        # computing it, and no date has ever been loaded.
        "window_not_published",
        # A published window did its job and expired on schedule; the county's
        # next date must be entered when it publishes.
        "window_awaiting_publication",
    ]
    detail: str


class SweepOut(BaseModel):
    as_of: dt.date
    inserted: dict[str, int]
    total: int
    # Deadlines the sweep could NOT compute, and exactly why — partial
    # jurisdiction coverage is reported, never silent (ADR 0003).
    coverage_gaps: list[SweepGapOut]


@app.post("/sweep/deadlines", response_model=SweepOut)
def sweep_deadlines(
    conn: Conn,
    request: Request,
    as_of: Annotated[dt.date | None, Query()] = None,
    actor: Actor = "system",
) -> SweepOut:
    effective = as_of if as_of is not None else dt.date.today()
    result = sweep.run_sweep(conn, effective)
    gaps = [SweepGapOut(**vars(gap)) for gap in result.gaps]
    db.record_audit(
        conn,
        actor=actor,
        action="sweep.deadlines",
        request_id=request.state.request_id,
        after_value={
            "as_of": str(effective),
            "inserted": result.inserted,
            "gap_count": len(gaps),
        },
    )
    return SweepOut(
        as_of=effective, inserted=result.inserted, total=result.total, coverage_gaps=gaps
    )


# ---------------------------------------------------------------------------
# Documents: upload -> extract -> review -> apply
# ---------------------------------------------------------------------------

DOCUMENT_KINDS = Literal[
    "settlement_statement",
    "deed",
    "lease",
    "lease_amendment",
    "insurance_declaration",
    "mortgage_note",
    "mortgage_statement",
    "assessment_notice",
    "tax_bill",
    "inspection_report",
    "appraisal",
    "permit",
    "invoice",
    "receipt",
    "estoppel",
    "photo",
    "other",
]


@app.post("/documents", response_model=documents.DocumentDetail, status_code=201)
async def upload_document(
    conn: Conn,
    request: Request,
    file: Annotated[UploadFile, File()],
    kind: Annotated[DOCUMENT_KINDS, Form()],
    property_id: Annotated[uuid.UUID, Form()],
    document_date: Annotated[dt.date | None, Form()] = None,
    actor: Actor = "system",
) -> documents.DocumentDetail:
    # BEFORE the read: `await file.read()` allocates whatever the uploader
    # sent, so a cap checked afterwards protects nothing. The domain-level
    # check in documents.upload stays as the backstop for non-HTTP callers.
    if file.size is not None and file.size > documents.MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{file.size} bytes exceeds the {documents.MAX_BYTES} cap",
        )
    content = await file.read()
    try:
        detail = documents.upload(
            conn,
            kind=kind,
            property_id=str(property_id),
            filename=file.filename or "document",
            content=content,
            mime_type=file.content_type,
            document_date=document_date,
            uploaded_by=actor,
        )
    except documents.UnknownProperty as error:
        raise HTTPException(status_code=404, detail="property not found") from error
    except documents.DuplicateDocument as error:
        raise HTTPException(
            status_code=409, detail=f"these exact bytes are already document {error}"
        ) from error
    except documents.DocumentTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except documents.extraction_parse.UnreadableDocument as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.record_audit(
        conn,
        actor=actor,
        action="documents.upload",
        request_id=request.state.request_id,
        table_name="source_documents",
        record_id=detail.id,
        after_value={"kind": detail.kind, "status": detail.status},
    )
    return detail


@app.get("/documents", response_model=list[documents.DocumentSummary])
def list_documents(
    conn: Conn,
    status: Annotated[
        Literal["pending", "extracted", "needs_review", "confirmed", "rejected", "applied"] | None,
        Query(),
    ] = None,
) -> list[documents.DocumentSummary]:
    return documents.list_documents(conn, status)


@app.get("/documents/{document_id}", response_model=documents.DocumentDetail)
def document_detail(document_id: uuid.UUID, conn: Conn) -> documents.DocumentDetail:
    try:
        return documents.detail(conn, str(document_id))
    except documents.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error


@app.get("/documents/{document_id}/content")
def document_content(document_id: uuid.UUID, conn: Conn) -> Response:
    try:
        disposition, mime_type, content = documents.get_content(conn, str(document_id))
    except documents.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="no stored content") from error
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "content-disposition": disposition,
            # The uploader picked the type; never let a browser pick a better one.
            "x-content-type-options": "nosniff",
        },
    )


@app.post("/documents/{document_id}/review", response_model=documents.DocumentDetail)
def review_document_field(
    document_id: uuid.UUID,
    body: documents.ReviewIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> documents.DocumentDetail:
    try:
        detail = documents.review_field(conn, str(document_id), body, actor)
    except documents.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except documents.AlreadyApplied as error:
        raise HTTPException(
            status_code=409, detail="already applied; review is not re-made"
        ) from error
    except (
        documents.UnknownField,
        documents.InvalidValue,
        documents.NothingToAccept,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.record_audit(
        conn,
        actor=actor,
        action=f"documents.review.{body.action}",
        request_id=request.state.request_id,
        table_name="extracted_fields",
        after_value={"document_id": str(document_id), "field_path": body.field_path},
    )
    return detail


@app.post("/documents/{document_id}/extract", response_model=documents.DocumentDetail)
def re_extract_document(
    document_id: uuid.UUID, conn: Conn, request: Request, actor: Actor = "system"
) -> documents.DocumentDetail:
    try:
        detail = documents.re_extract(conn, str(document_id))
    except documents.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except documents.AlreadyApplied as error:
        raise HTTPException(
            status_code=409, detail="already applied; the record is closed"
        ) from error
    except documents.extraction_parse.UnreadableDocument as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.record_audit(
        conn,
        actor=actor,
        action="documents.extract",
        request_id=request.state.request_id,
        table_name="source_documents",
        record_id=detail.id,
        after_value={"status": detail.status},
    )
    return detail


@app.post(
    "/documents/{document_id}/apply",
    response_model=documents.ApplyResult,
    status_code=201,
)
def apply_document(
    document_id: uuid.UUID,
    body: documents.ApplyIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> documents.ApplyResult:
    try:
        result = documents.apply_document(conn, str(document_id), body, actor)
    except documents.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except documents.AlreadyApplied as error:
        raise HTTPException(
            status_code=409, detail="already applied; a document applies exactly once"
        ) from error
    except documents.NotConfirmed as error:
        raise HTTPException(
            status_code=409,
            detail=f"apply requires status confirmed; the document is {error}",
        ) from error
    except (
        documents.NotExactlyOneProperty,
        documents.InvalidAllocation,
        documents.WrongApplyKind,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.record_audit(
        conn,
        actor=actor,
        action="documents.apply",
        request_id=request.state.request_id,
        table_name="source_documents",
        record_id=str(document_id),
        after_value=result.model_dump(mode="json"),
    )
    return result


# ---------------------------------------------------------------------------
# Maintenance: vendors, work orders, and the completion that teaches the
# inventory
# ---------------------------------------------------------------------------


@app.post("/vendors", response_model=maintenance.VendorOut, status_code=201)
def create_vendor(
    body: maintenance.VendorIn, conn: Conn, request: Request, actor: Actor = "system"
) -> maintenance.VendorOut:
    try:
        vendor = maintenance.create_vendor(conn, body)
    except maintenance.UnknownEntity as error:
        raise HTTPException(status_code=404, detail="entity not found") from error
    except maintenance.DuplicateVendor as error:
        raise HTTPException(
            status_code=409, detail=f"a vendor named {error} is already on this list"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="vendors.create",
        request_id=request.state.request_id,
        table_name="vendors",
        record_id=vendor.id,
        after_value=vendor.model_dump(mode="json"),
    )
    return vendor


@app.get("/vendors", response_model=list[maintenance.VendorOut])
def list_vendors(
    conn: Conn,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    include_retired: Annotated[bool, Query()] = False,
    as_of: Annotated[dt.date | None, Query()] = None,
) -> list[maintenance.VendorOut]:
    return maintenance.list_vendors(
        conn,
        as_of=as_of or dt.date.today(),
        entity_id=str(entity_id) if entity_id else None,
        include_retired=include_retired,
    )


@app.get("/vendors/{vendor_id}", response_model=maintenance.VendorOut)
def read_vendor(
    vendor_id: uuid.UUID, conn: Conn, as_of: Annotated[dt.date | None, Query()] = None
) -> maintenance.VendorOut:
    try:
        return maintenance.read_vendor(conn, str(vendor_id), as_of=as_of or dt.date.today())
    except maintenance.UnknownVendor as error:
        raise HTTPException(status_code=404, detail="vendor not found") from error


@app.post("/vendors/{vendor_id}/credentials", response_model=maintenance.VendorOut)
def renew_vendor_credentials(
    vendor_id: uuid.UUID,
    body: maintenance.CredentialsIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> maintenance.VendorOut:
    try:
        vendor = maintenance.renew_credentials(conn, str(vendor_id), body, as_of=dt.date.today())
    except maintenance.UnknownVendor as error:
        raise HTTPException(status_code=404, detail="vendor not found") from error
    except maintenance.NothingToRenew as error:
        raise HTTPException(
            status_code=422, detail="a renewal has to name what was renewed"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="vendors.renew_credentials",
        request_id=request.state.request_id,
        table_name="vendors",
        record_id=str(vendor_id),
        after_value={"coverage_state": vendor.coverage_state},
    )
    return vendor


@app.post("/work-orders", response_model=maintenance.WorkOrderOut, status_code=201)
def create_work_order(
    body: maintenance.WorkOrderIn, conn: Conn, request: Request, actor: Actor = "system"
) -> maintenance.WorkOrderOut:
    try:
        work_order = maintenance.create_work_order(conn, body)
    except maintenance.UnknownProperty as error:
        raise HTTPException(status_code=404, detail="property not found") from error
    except psycopg.errors.ForeignKeyViolation as error:
        # The composite keys refuse a unit or component of another property.
        raise HTTPException(
            status_code=422,
            detail="the unit or component named does not belong to that property",
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="work_orders.create",
        request_id=request.state.request_id,
        table_name="work_orders",
        record_id=work_order.id,
        after_value={"summary": work_order.summary, "priority": work_order.priority},
    )
    return work_order


@app.get("/work-orders", response_model=list[maintenance.WorkOrderOut])
def list_work_orders(
    conn: Conn,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[maintenance.WorkOrderStatus | None, Query()] = None,
    open_only: Annotated[bool, Query()] = False,
) -> list[maintenance.WorkOrderOut]:
    return maintenance.list_work_orders(
        conn,
        property_id=str(property_id) if property_id else None,
        status=status,
        open_only=open_only,
    )


@app.get("/work-orders/{work_order_id}", response_model=maintenance.WorkOrderOut)
def read_work_order(work_order_id: uuid.UUID, conn: Conn) -> maintenance.WorkOrderOut:
    try:
        return maintenance.read_work_order(conn, str(work_order_id))
    except maintenance.UnknownWorkOrder as error:
        raise HTTPException(status_code=404, detail="work order not found") from error


@app.post("/work-orders/{work_order_id}/transitions", response_model=maintenance.WorkOrderOut)
def transition_work_order(
    work_order_id: uuid.UUID,
    body: maintenance.TransitionIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> maintenance.WorkOrderOut:
    try:
        work_order = maintenance.transition(conn, str(work_order_id), body)
    except maintenance.UnknownWorkOrder as error:
        raise HTTPException(status_code=404, detail="work order not found") from error
    except maintenance.UnknownVendor as error:
        raise HTTPException(status_code=404, detail="vendor not found") from error
    except maintenance.IllegalTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except psycopg.errors.CheckViolation as error:
        # Name the rule that actually fired: three constraints reach this UPDATE
        # and one message for all of them hid which line the request crossed.
        raise HTTPException(
            status_code=422,
            detail=maintenance.TRANSITION_REFUSALS.get(
                error.diag.constraint_name or "",
                "a work-order rule refused that transition",
            ),
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action=f"work_orders.{body.status}",
        request_id=request.state.request_id,
        table_name="work_orders",
        record_id=str(work_order_id),
        after_value={"status": work_order.status},
    )
    return work_order


@app.post(
    "/work-orders/{work_order_id}/complete",
    response_model=maintenance.CompletionOut,
    status_code=201,
)
def complete_work_order(
    work_order_id: uuid.UUID,
    body: maintenance.CompletionIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> maintenance.CompletionOut:
    try:
        result = maintenance.complete(conn, str(work_order_id), body, actor)
    except maintenance.UnknownWorkOrder as error:
        raise HTTPException(status_code=404, detail="work order not found") from error
    except maintenance.AlreadyResolved as error:
        raise HTTPException(
            status_code=409, detail=f"this job is already {error}; its history is not re-made"
        ) from error
    except maintenance.ComponentAlreadyRetired as error:
        raise HTTPException(status_code=409, detail="that component was already retired") from error
    except maintenance.MissingComponent as error:
        raise HTTPException(
            status_code=422,
            detail="a replacement must name the component it replaced",
        ) from error
    except maintenance.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except maintenance.CapitalNeedsRationale as error:
        raise HTTPException(
            status_code=422, detail=f"capital spending explains itself: {error}"
        ) from error
    except maintenance.IllegalTransition as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.errors.CheckViolation as error:
        # The completion writes to the inventory, so the inventory's own rules
        # can refuse it — a replacement dated before the component it retires
        # trips retired_after_installed. Name the rule that bit.
        raise HTTPException(
            status_code=422,
            detail=maintenance.COMPLETION_REFUSALS.get(
                error.diag.constraint_name or "",
                f"the inventory refused this completion: {error.diag.constraint_name}",
            ),
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="work_orders.complete",
        request_id=request.state.request_id,
        table_name="work_orders",
        record_id=str(work_order_id),
        after_value=result.model_dump(mode="json", exclude={"work_order"}),
    )
    return result


@app.post(
    "/work-orders/{work_order_id}/costs",
    response_model=maintenance.WorkOrderOut,
    status_code=201,
)
def add_work_order_cost(
    work_order_id: uuid.UUID,
    body: maintenance.CostLinkIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> maintenance.WorkOrderOut:
    try:
        work_order = maintenance.add_cost(conn, str(work_order_id), body, actor)
    except maintenance.UnknownWorkOrder as error:
        raise HTTPException(status_code=404, detail="work order not found") from error
    except ledger.UnknownEvent as error:
        raise HTTPException(status_code=404, detail="ledger event not found") from error
    except maintenance.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except maintenance.WrongProperty as error:
        raise HTTPException(
            status_code=422, detail="that ledger event belongs to another property"
        ) from error
    except maintenance.CapitalNeedsRationale as error:
        raise HTTPException(
            status_code=422, detail=f"capital spending explains itself: {error}"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="work_orders.cost",
        request_id=request.state.request_id,
        table_name="work_order_ledger_events",
        record_id=str(work_order_id),
        after_value={"net_cost": str(work_order.net_cost)},
    )
    return work_order


# ---------------------------------------------------------------------------
# Screening decisions and the notice a denial owes (FCRA s.615(a))
# ---------------------------------------------------------------------------


@app.post("/screening", response_model=screening.ScreeningOut, status_code=201)
def open_screening(
    body: screening.ScreeningIn, conn: Conn, request: Request, actor: Actor = "system"
) -> screening.ScreeningOut:
    try:
        result = screening.create(conn, body)
    except screening.UnknownResident as error:
        raise HTTPException(status_code=404, detail="resident not found") from error
    except screening.UnknownProperty as error:
        raise HTTPException(status_code=404, detail="property not found") from error
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(
            status_code=422, detail="that unit does not belong to that property"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="screening.open",
        request_id=request.state.request_id,
        table_name="screening_requests",
        record_id=result.id,
        after_value={"provider": result.provider},
    )
    return result


@app.get("/screening", response_model=list[screening.ScreeningOut])
def list_screening(
    conn: Conn,
    resident_id: Annotated[uuid.UUID | None, Query()] = None,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
    notice_owed: Annotated[bool, Query()] = False,
) -> list[screening.ScreeningOut]:
    return screening.list_requests(
        conn,
        resident_id=str(resident_id) if resident_id else None,
        property_id=str(property_id) if property_id else None,
        notice_owed=notice_owed,
    )


@app.get("/screening/{screening_id}", response_model=screening.ScreeningOut)
def read_screening(screening_id: uuid.UUID, conn: Conn) -> screening.ScreeningOut:
    try:
        return screening.read(conn, str(screening_id))
    except screening.UnknownScreening as error:
        raise HTTPException(status_code=404, detail="screening not found") from error


@app.post("/screening/{screening_id}/decision", response_model=screening.ScreeningOut)
def decide_screening(
    screening_id: uuid.UUID,
    body: screening.DecisionIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> screening.ScreeningOut:
    try:
        result = screening.decide(conn, str(screening_id), body)
    except screening.UnknownScreening as error:
        raise HTTPException(status_code=404, detail="screening not found") from error
    except screening.AlreadyDecided as error:
        raise HTTPException(
            status_code=409,
            detail=f"this application was already {error}; a decision is recorded once",
        ) from error
    except psycopg.errors.CheckViolation as error:
        raise HTTPException(
            status_code=422,
            detail="a decision cannot precede the application it answers",
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="screening.decide",
        request_id=request.state.request_id,
        table_name="screening_requests",
        record_id=str(screening_id),
        after_value={
            "decision": result.decision,
            "adverse_action_required": result.adverse_action_required,
        },
    )
    return result


@app.post("/screening/{screening_id}/adverse-action", response_model=screening.ScreeningOut)
def record_adverse_action(
    screening_id: uuid.UUID,
    body: screening.NoticeIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> screening.ScreeningOut:
    try:
        result = screening.record_notice(conn, str(screening_id), body)
    except screening.UnknownScreening as error:
        raise HTTPException(status_code=404, detail="screening not found") from error
    except screening.NoticeNotOwed as error:
        raise HTTPException(
            status_code=422,
            detail=(
                "no notice is owed: s.615(a) attaches only when a consumer "
                "report drove an adverse decision"
            ),
        ) from error
    except screening.NoticeAlreadySent as error:
        raise HTTPException(
            status_code=409, detail=f"the notice was already sent on {error}"
        ) from error
    except psycopg.errors.CheckViolation as error:
        raise HTTPException(
            status_code=422, detail="a notice cannot precede the decision it is about"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="screening.adverse_action",
        request_id=request.state.request_id,
        table_name="screening_requests",
        record_id=str(screening_id),
        after_value={"sent_on": str(result.adverse_action_sent_on)},
    )
    return result


# ---------------------------------------------------------------------------
# Debt: the note, its schedule, and the payment it demands
# ---------------------------------------------------------------------------


@app.post("/debts", response_model=debt.DebtOut, status_code=201)
def create_debt(
    body: debt.DebtIn, conn: Conn, request: Request, actor: Actor = "system"
) -> debt.DebtOut:
    try:
        note = debt.create(conn, body)
    except debt.UnknownProperty as error:
        raise HTTPException(status_code=404, detail="property not found") from error
    except psycopg.errors.CheckViolation as error:
        raise HTTPException(
            status_code=422,
            detail=debt.DEBT_REFUSALS.get(
                error.diag.constraint_name or "",
                f"the note refused these terms: {error.diag.constraint_name}",
            ),
        ) from error
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(
            status_code=404, detail="that entity or document does not exist"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="debts.create",
        request_id=request.state.request_id,
        table_name="debt_instruments",
        record_id=note.id,
        after_value={"lender": note.lender, "principal": str(note.original_principal)},
    )
    return note


@app.get("/debts", response_model=list[debt.DebtOut])
def list_debts(
    conn: Conn,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
    include_paid_off: Annotated[bool, Query()] = False,
) -> list[debt.DebtOut]:
    return debt.list_debts(
        conn,
        property_id=str(property_id) if property_id else None,
        include_paid_off=include_paid_off,
    )


@app.get("/debts/{debt_id}", response_model=debt.DebtOut)
def read_debt(debt_id: uuid.UUID, conn: Conn) -> debt.DebtOut:
    try:
        return debt.read(conn, str(debt_id))
    except debt.UnknownDebt as error:
        raise HTTPException(status_code=404, detail="note not found") from error


@app.get("/debts/{debt_id}/schedule", response_model=debt.ScheduleOut)
def read_debt_schedule(
    debt_id: uuid.UUID, conn: Conn, as_of: Annotated[dt.date | None, Query()] = None
) -> debt.ScheduleOut:
    try:
        return debt.schedule(conn, str(debt_id), as_of=as_of or dt.date.today())
    except debt.UnknownDebt as error:
        raise HTTPException(status_code=404, detail="note not found") from error
    except debt.ScheduleUnavailable as error:
        raise HTTPException(
            status_code=422,
            detail=(
                f"no level-payment schedule for a {error} note; the engine "
                "amortizes fully amortizing, balloon and ARM terms"
            ),
        ) from error


@app.post("/debts/{debt_id}/payments", response_model=debt.PaymentOut, status_code=201)
def record_debt_payment(
    debt_id: uuid.UUID,
    body: debt.PaymentIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> debt.PaymentOut:
    try:
        payment = debt.record_payment(conn, str(debt_id), body)
    except debt.UnknownDebt as error:
        raise HTTPException(status_code=404, detail="note not found") from error
    except debt.AlreadyPaidOff as error:
        raise HTTPException(status_code=409, detail=f"this note was paid off on {error}") from error
    except debt.DuplicatePayment as error:
        raise HTTPException(
            status_code=409,
            detail=(
                f"a payment on {error} is already recorded; the ledger corrects "
                "by reversal, never by overwrite"
            ),
        ) from error
    except debt.ScheduleUnavailable as error:
        raise HTTPException(
            status_code=422,
            detail=f"the engine cannot supply a split here ({error}); state it explicitly",
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="debts.payment",
        request_id=request.state.request_id,
        table_name="debt_payments",
        record_id=str(debt_id),
        after_value=payment.model_dump(mode="json"),
    )
    return payment


@app.post("/debts/{debt_id}/payoff", response_model=debt.DebtOut)
def pay_off_debt(
    debt_id: uuid.UUID,
    body: debt.PayoffIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> debt.DebtOut:
    try:
        note = debt.pay_off(conn, str(debt_id), body.paid_off_on)
    except debt.UnknownDebt as error:
        raise HTTPException(status_code=404, detail="note not found") from error
    except debt.AlreadyPaidOff as error:
        raise HTTPException(
            status_code=409, detail=f"this note was already paid off on {error}"
        ) from error
    db.record_audit(
        conn,
        actor=actor,
        action="debts.payoff",
        request_id=request.state.request_id,
        table_name="debt_instruments",
        record_id=str(debt_id),
        after_value={"paid_off_on": str(note.paid_off_on)},
    )
    return note


# ---------------------------------------------------------------------------
# The security deposit: the jurisdiction's duties, and returning it
# ---------------------------------------------------------------------------


@app.get("/leases/{lease_id}/deposit", response_model=deposit.DepositOut)
def read_deposit(
    lease_id: uuid.UUID, conn: Conn, as_of: Annotated[dt.date | None, Query()] = None
) -> deposit.DepositOut:
    try:
        return deposit.read(conn, str(lease_id), as_of=as_of or dt.date.today())
    except deposit.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error


@app.get("/deposits/open", response_model=list[deposit.DepositOut])
def list_open_deposits(
    conn: Conn, as_of: Annotated[dt.date | None, Query()] = None
) -> list[deposit.DepositOut]:
    return deposit.list_open(conn, as_of=as_of or dt.date.today())


@app.post(
    "/leases/{lease_id}/deposit-return",
    response_model=deposit.ReturnOut,
    status_code=201,
)
def return_deposit(
    lease_id: uuid.UUID,
    body: deposit.ReturnIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> deposit.ReturnOut:
    try:
        result = deposit.return_deposit(conn, str(lease_id), body)
    except deposit.UnknownLease as error:
        raise HTTPException(status_code=404, detail="lease not found") from error
    except deposit.AlreadyReturned as error:
        raise HTTPException(
            status_code=409, detail=f"the deposit was returned on {error}"
        ) from error
    except deposit.NotMovedOut as error:
        raise HTTPException(
            status_code=422,
            detail="record the move-out date first; a deposit is settled after the tenancy",
        ) from error
    except deposit.ReturnExceedsDeposit as error:
        raise HTTPException(status_code=422, detail=f"the deposit held was only {error}") from error
    db.record_audit(
        conn,
        actor=actor,
        action="deposit.return",
        request_id=request.state.request_id,
        table_name="leases",
        record_id=str(lease_id),
        after_value=result.model_dump(mode="json"),
    )
    return result


# ---------------------------------------------------------------------------
# Assessments: what a body says a property is worth
# ---------------------------------------------------------------------------


def _record_assessment(
    write: Callable[[], assessments.AssessmentOut],
) -> assessments.AssessmentOut:
    """One error map for one writer. Both doors into `assessments` refuse for
    the same reasons in the same words; two ladders would drift apart on the
    first wording change."""
    try:
        return write()
    except documents.UnknownDocument as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except assessments.UnknownProperty as error:
        raise HTTPException(status_code=404, detail="property not found") from error
    except documents.AlreadyApplied as error:
        raise HTTPException(
            status_code=409, detail="already applied; a document applies exactly once"
        ) from error
    except documents.NotConfirmed as error:
        raise HTTPException(
            status_code=409,
            detail=f"apply requires status confirmed; the document is {error}",
        ) from error
    except assessments.DuplicateAssessment as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (
        assessments.NotAGoverningBody,
        assessments.UnusableValue,
        documents.WrongApplyKind,
        documents.NotExactlyOneProperty,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except assessments.JurisdictionUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail=(f"no jurisdiction pack is loaded for {error}; see GET /coverage/jurisdictions"),
        ) from error


@app.post("/assessments", response_model=assessments.AssessmentOut, status_code=201)
def create_assessment(
    body: assessments.AssessmentIn, conn: Conn, request: Request, actor: Actor = "system"
) -> assessments.AssessmentOut:
    result = _record_assessment(lambda: assessments.record(conn, body, actor))
    # The created ROW, not the request body: the body may omit the
    # jurisdiction, and an audit reader needs what was written.
    _audit(
        conn,
        request,
        actor,
        "assessment.create",
        "assessments",
        result.id,
        result.model_dump(mode="json"),
    )
    return result


@app.post(
    "/documents/{document_id}/apply-assessment",
    response_model=assessments.AssessmentOut,
    status_code=201,
)
def apply_assessment_notice(
    document_id: uuid.UUID,
    body: assessments.NoticeApplyIn,
    conn: Conn,
    request: Request,
    actor: Actor = "system",
) -> assessments.AssessmentOut:
    result = _record_assessment(
        lambda: assessments.apply_notice(conn, str(document_id), body, actor)
    )
    _audit(
        conn,
        request,
        actor,
        "assessment.create",
        "assessments",
        result.id,
        result.model_dump(mode="json"),
    )
    # The document changed state too, and every mutation owes a row. The same
    # action string as /documents/{id}/apply, so "what closed this document" is
    # one audit query however it was closed.
    _audit(
        conn,
        request,
        actor,
        "documents.apply",
        "source_documents",
        str(document_id),
        {"kind": "assessment_notice", "assessment_id": result.id},
    )
    return result
