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
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Any, Literal

import psycopg
from fastapi import (
    Depends,
    FastAPI,
    File,
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
    bank_import,
    config,
    coverage,
    db,
    dossier,
    jurisdiction,
    ledger,
    payments,
    rent,
    reports,
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


Conn = Annotated[psycopg.Connection[dict[str, Any]], Depends(get_conn)]
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
    updated = conn.execute(
        """
        UPDATE rent_charges SET status = 'waived', waived_reason = %s
        WHERE id = %s AND status IN ('scheduled', 'due', 'partially_paid')
        """,
        (body.reason, str(charge_id)),
    )
    if updated.rowcount == 0:
        raise HTTPException(status_code=404, detail="no waivable charge found")
    _audit(
        conn,
        request,
        actor,
        "rent.waive",
        "rent_charges",
        str(charge_id),
        {"reason": body.reason},
    )


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
    reason: Literal["no_state_jurisdiction", "no_rule_for_domain", "calendar_key_unregistered"]
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
