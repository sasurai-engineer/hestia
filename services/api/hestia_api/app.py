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
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hestia_api import config, coverage, db, dossier, jurisdiction, ledger, sweep, views

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
