"""Read models for the web surface: the dossier as a document, not a form.

Never a blank state: every read assembles what the platform knows — with the
provenance kind and confidence attached wherever a value was inferred rather
than stated — so the client's job is display and correction, never data entry.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from pydantic import BaseModel

Conn = psycopg.Connection[dict[str, Any]]


class PropertySummary(BaseModel):
    id: str
    label: str
    street_1: str
    city: str
    state: str
    postal_code: str
    kind: str
    year_built: int | None
    jurisdiction: str | None
    defect_count: int
    component_count: int
    next_deadline_on: dt.date | None


class ChainLink(BaseModel):
    name: str
    level: str


class HazardOut(BaseModel):
    kind: str
    zone: str | None
    in_special_flood_hazard_area: bool | None
    base_flood_elevation_ft: float | None
    observed_at: dt.datetime


class ComponentOut(BaseModel):
    code: str
    display_name: str
    system: str
    installed_year_low: int | None
    installed_year_high: int | None
    life_years_low: float | None
    life_years_high: float | None
    condition: str
    provenance_kind: str
    confidence: float
    derived_from: str | None


class DefectOut(BaseModel):
    kind: str
    status: str
    affects_safety: bool
    affects_insurance: bool
    affects_financing: bool
    triggers_disclosure: bool
    citation: str | None
    derived_from: str | None


class DeadlineOut(BaseModel):
    id: str
    kind: str
    status: str
    due_on: dt.date
    window_opens_on: dt.date | None
    citation: str
    note: str | None
    property_label: str | None


class DossierView(BaseModel):
    id: str
    entity_id: str
    label: str
    street_1: str
    city: str
    state: str
    postal_code: str
    county: str | None
    kind: str
    year_built: int | None
    latitude: float | None
    longitude: float | None
    jurisdiction_chain: list[ChainLink]
    hazards: list[HazardOut]
    components: list[ComponentOut]
    defects: list[DefectOut]
    deadlines: list[DeadlineOut]


def list_properties(conn: Conn) -> list[PropertySummary]:
    rows = conn.execute(
        """
        SELECT p.id::text, p.label, p.street_1, p.city, p.state, p.postal_code,
               p.kind::text, p.year_built, j.name AS jurisdiction,
               (SELECT count(*) FROM latent_defects d
                WHERE d.property_id = p.id AND d.status <> 'remediated') AS defect_count,
               (SELECT count(*) FROM components c
                WHERE c.property_id = p.id AND c.retired_on IS NULL) AS component_count,
               (SELECT min(dl.due_on) FROM deadlines dl
                WHERE dl.property_id = p.id AND dl.status = 'upcoming'
                  AND dl.due_on >= CURRENT_DATE) AS next_deadline_on
        FROM properties p
        LEFT JOIN jurisdictions j ON j.id = p.jurisdiction_id
        WHERE p.disposed_on IS NULL
        ORDER BY p.created_at
        """
    ).fetchall()
    return [PropertySummary(**row) for row in rows]


def dossier_view(conn: Conn, property_id: str) -> DossierView | None:
    prop = conn.execute(
        """
        SELECT p.id::text, p.entity_id::text, p.label, p.street_1, p.city, p.state,
               p.postal_code, p.county, p.kind::text, p.year_built,
               p.latitude::float, p.longitude::float, p.jurisdiction_id
        FROM properties p WHERE p.id = %s
        """,
        (property_id,),
    ).fetchone()
    if prop is None:
        return None
    chain: list[dict[str, Any]] = []
    if prop["jurisdiction_id"] is not None:
        chain = conn.execute(
            """
            SELECT j.name, j.level::text
            FROM jurisdiction_chain(%s) c
            JOIN jurisdictions j ON j.id = c.jurisdiction_id
            ORDER BY c.depth
            """,
            (prop["jurisdiction_id"],),
        ).fetchall()
    hazards = conn.execute(
        """
        SELECT kind::text, zone, in_special_flood_hazard_area,
               base_flood_elevation_ft::float, observed_at
        FROM hazard_facts WHERE property_id = %s ORDER BY kind
        """,
        (property_id,),
    ).fetchall()
    components = conn.execute(
        """
        SELECT ct.code, ct.display_name, ct.system::text,
               c.installed_year_low, c.installed_year_high,
               ct.life_years_low::float, ct.life_years_high::float,
               c.condition::text, pr.kind::text AS provenance_kind,
               pr.confidence::float, pr.derived_from
        FROM components c
        JOIN component_types ct ON ct.id = c.component_type_id
        JOIN provenance pr ON pr.id = c.provenance_id
        WHERE c.property_id = %s AND c.retired_on IS NULL
        ORDER BY ct.system, ct.code
        """,
        (property_id,),
    ).fetchall()
    defects = conn.execute(
        """
        SELECT d.kind::text, d.status::text, d.affects_safety, d.affects_insurance,
               d.affects_financing, d.triggers_disclosure, d.citation,
               pr.derived_from
        FROM latent_defects d
        JOIN provenance pr ON pr.id = d.provenance_id
        WHERE d.property_id = %s
        ORDER BY d.kind
        """,
        (property_id,),
    ).fetchall()
    deadlines = conn.execute(
        """
        SELECT d.id::text, d.kind::text, d.status::text, d.due_on, d.window_opens_on,
               d.citation, d.note, p.label AS property_label
        FROM deadlines d
        LEFT JOIN properties p ON p.id = d.property_id
        WHERE d.property_id = %s AND d.status = 'upcoming'
        ORDER BY d.due_on
        """,
        (property_id,),
    ).fetchall()
    return DossierView(
        **{k: v for k, v in prop.items() if k != "jurisdiction_id"},
        jurisdiction_chain=[ChainLink(**link) for link in chain],
        hazards=[HazardOut(**h) for h in hazards],
        components=[ComponentOut(**c) for c in components],
        defects=[DefectOut(**d) for d in defects],
        deadlines=[DeadlineOut(**d) for d in deadlines],
    )


def upcoming_deadlines(conn: Conn, *, due_before: dt.date | None, limit: int) -> list[DeadlineOut]:
    rows = conn.execute(
        """
        SELECT d.id::text, d.kind::text, d.status::text, d.due_on, d.window_opens_on,
               d.citation, d.note, p.label AS property_label
        FROM deadlines d
        LEFT JOIN properties p ON p.id = d.property_id
        WHERE d.status = 'upcoming'
          AND (%(due_before)s::date IS NULL OR d.due_on <= %(due_before)s)
        ORDER BY d.due_on, d.kind
        LIMIT %(limit)s
        """,
        {"due_before": due_before, "limit": limit},
    ).fetchall()
    return [DeadlineOut(**row) for row in rows]
