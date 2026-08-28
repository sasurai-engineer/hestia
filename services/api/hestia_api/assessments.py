"""Assessment records: what an assessing body said a property is worth.

Two doors, one table. An owner types the notice they were mailed, or the same
notice arrives as an uploaded document and its reviewed fields are written
here. Both leave a provenance row behind, because module 019 made that column
NOT NULL: a figure the appeal card renders is a figure the owner must be able
to trace back to paper.

What this module deliberately does NOT do is judge. No ratio is applied on the
way in, no market comparison is drawn, no verdict about over-assessment is
formed — that is the detector's work, and it needs the pack's assessment.ratio
which this module never reads. What is stored is what the paper said, plus the
one fact the paper's own layout hides: WHICH figure it was.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

from hestia_api import documents, extraction_parse

Conn = psycopg.Connection[dict[str, Any]]

ValueBasis = Literal["market", "taxable"]


class UnknownProperty(Exception):
    """No such property."""


class NotAGoverningBody(Exception):
    """The named jurisdiction is not on this property's chain."""


class JurisdictionUnavailable(Exception):
    """No pack resolves this property, and the caller named no body."""


class DuplicateAssessment(Exception):
    """One body, one property, one year, one basis — already recorded."""


class UnusableValue(Exception):
    """A confirmed value the domain refuses, in the domain's own words."""


class AssessmentIn(BaseModel):
    """A notice typed off the paper."""

    property_id: uuid.UUID
    # Which body issued it. Omitted, the property's own resolved jurisdiction
    # stands in; named, it must be on that property's chain. Never inferred
    # from the notice text — see _resolve_jurisdiction.
    jurisdiction_id: uuid.UUID | None = None
    tax_year: int = Field(ge=extraction_parse.MIN_TAX_YEAR, le=extraction_parse.MAX_TAX_YEAR)
    # No default. Market and taxable differ by a factor of three in Ohio and
    # four in Tennessee, so a default would be the largest silent error this
    # system can make.
    value_basis: ValueBasis
    assessed_total: Decimal = Field(ge=0, decimal_places=2, max_digits=18)
    assessed_land: Decimal | None = Field(default=None, ge=0, decimal_places=2, max_digits=18)
    assessed_improvement: Decimal | None = Field(
        default=None, ge=0, decimal_places=2, max_digits=18
    )
    notice_received_on: dt.date | None = None


class NoticeApplyIn(BaseModel):
    """The one decision applying a notice asks for; every number comes off the
    reviewed document."""

    jurisdiction_id: uuid.UUID | None = None


class AssessmentOut(BaseModel):
    id: str
    property_id: str
    jurisdiction_id: str
    jurisdiction: str
    tax_year: int
    value_basis: str
    assessed_land: Decimal | None
    assessed_improvement: Decimal | None
    assessed_total: Decimal
    notice_received_on: dt.date | None
    # Server-computed, because the browser computes nothing: the land share
    # documents._suggestion already cites, and the year-over-year move that is
    # the reason an owner appeals at all. Both are SQL, so neither costs a
    # Python branch, and prior_tax_year travels with the delta so the card can
    # never imply a comparison with last year when it was with 2019.
    land_share: Decimal | None
    prior_tax_year: int | None
    change_from_prior: Decimal | None
    # How we know. Non-optional, because module 019 made provenance_id NOT
    # NULL — the card cannot render an authorless number.
    provenance_kind: str
    confidence: float
    source_label: str | None
    source_document_id: str | None
    created_at: dt.datetime


PROJECTION = """
    SELECT ranked.* FROM (
      SELECT a.id::text AS id, a.property_id::text AS property_id,
             a.jurisdiction_id::text AS jurisdiction_id, j.name AS jurisdiction,
             a.tax_year, a.value_basis::text AS value_basis,
             a.assessed_land, a.assessed_improvement, a.assessed_total,
             a.notice_received_on,
             CASE WHEN a.assessed_land IS NOT NULL AND a.assessed_total > 0
                  THEN round(a.assessed_land / a.assessed_total, 6) END AS land_share,
             lag(a.tax_year) OVER prior AS prior_tax_year,
             a.assessed_total - lag(a.assessed_total) OVER prior AS change_from_prior,
             pr.kind::text AS provenance_kind, pr.confidence::float AS confidence,
             pr.source_label, pr.source_document::text AS source_document_id,
             a.created_at
      FROM assessments a
      JOIN jurisdictions j ON j.id = a.jurisdiction_id
      JOIN provenance pr ON pr.id = a.provenance_id
      WHERE a.property_id = %(property_id)s
      -- PARTITION BY the assessing body AND the basis: a prior year from a
      -- different body is not a comparison but two separate claims, and a
      -- market total minus last year's taxable total is arithmetic on two
      -- different units.
      WINDOW prior AS (PARTITION BY a.jurisdiction_id, a.value_basis ORDER BY a.tax_year)
    ) ranked
    WHERE (%(assessment_id)s::uuid IS NULL OR ranked.id::uuid = %(assessment_id)s)
    ORDER BY ranked.tax_year DESC, ranked.jurisdiction, ranked.value_basis
"""


def for_property(
    conn: Conn, property_id: str, *, assessment_id: str | None = None
) -> list[AssessmentOut]:
    """Every assessment on file for a property, newest tax year first.

    The NULL-guarded id filter is the list_documents idiom: reading back the
    row just written and rendering the dossier are one query, so the two can
    never compute the year-over-year move differently.
    """
    return [
        AssessmentOut(**row)
        for row in conn.execute(
            PROJECTION, {"property_id": property_id, "assessment_id": assessment_id}
        ).fetchall()
    ]


def _resolve_jurisdiction(
    conn: Conn, property_id: uuid.UUID, named: uuid.UUID | None
) -> tuple[str, str]:
    """Which body assessed this property: the caller's choice validated
    against the property's own chain, else the jurisdiction the packs resolved
    for the property, else a refusal that names the gap.

    Not from the notice. A notice prints an OFFICE — "Campbell County Property
    Valuation Administrator" — and matching that string to a jurisdictions row
    is fuzzy matching on names that collide by design; this repository now has
    a Hamilton County in two states. A near miss attaches an assessment to a
    neighbouring county silently, so the office is extracted, shown to the
    reviewer, and never matched.

    Not by walking to the nearest county either. "Counties assess real
    property" is true in Kentucky, Ohio and Tennessee and false in New England
    towns and Virginia's independent cities; encoding it here would put a
    governance fact in dispatch logic, which is the ADR 0003 failure mode —
    and one the state-literal ratchet would NOT catch, because it contains no
    state literal. jurisdiction_chain() is data, and the caller chooses in it.
    """
    row = conn.execute(
        """
        SELECT p.state,
               p.jurisdiction_id::text AS resolved_id,
               resolved.name           AS resolved_name,
               chosen.id::text         AS chosen_id,
               chosen.name             AS chosen_name,
               (EXISTS (SELECT 1 FROM jurisdiction_chain(p.jurisdiction_id) c
                        WHERE c.jurisdiction_id = chosen.id)
                -- The federal row is on every chain and assesses nothing.
                -- A predicate, not a branch.
                AND chosen.state IS NOT NULL) AS governs
        FROM properties p
        LEFT JOIN jurisdictions resolved ON resolved.id = p.jurisdiction_id
        LEFT JOIN jurisdictions chosen   ON chosen.id = %(named)s::uuid
        WHERE p.id = %(property_id)s
        """,
        {"named": named, "property_id": property_id},
    ).fetchone()
    if row is None:
        raise UnknownProperty(str(property_id))
    if named is None:
        if row["resolved_id"] is None:
            raise JurisdictionUnavailable(row["state"])
        return row["resolved_id"], row["resolved_name"]
    # An unknown id and a real id from another chain land in one refusal: with
    # no `chosen` row, EXISTS is false and `governs` is false, not NULL. Two
    # error shapes for the same wrong id would buy nothing.
    if not row["governs"]:
        raise NotAGoverningBody(
            "that jurisdiction does not govern this property; choose one of the bodies on its chain"
        )
    return row["chosen_id"], row["chosen_name"]


# The sentence each schema rule owes an owner, keyed by the constraint's own
# name so a rule renamed in a later module fails to find its sentence rather
# than quietly explaining the wrong thing. The rules are NOT restated in
# Python — the database is the authority and this is only its voice.
REFUSALS = {
    "assessed_land_within_total": (
        "the land line exceeds the total it is part of; enter both in the same"
        " basis, or leave the land line blank"
    ),
    "notice_not_before_its_year": "the notice is dated before the tax year it assesses",
    "plausible_assessment_year": "that is not a tax year a notice states",
    "money_nonneg_check": "an assessed value cannot be negative",
    "millage_rate_nonneg": "a millage rate cannot be negative",
}


def _insert(
    conn: Conn,
    *,
    property_id: str,
    jurisdiction_id: str,
    tax_year: int,
    value_basis: str,
    assessed_land: Decimal | None,
    assessed_improvement: Decimal | None,
    assessed_total: Decimal,
    notice_received_on: dt.date | None,
    provenance_id: str,
) -> str:
    try:
        row = conn.execute(
            """
            INSERT INTO assessments
              (property_id, jurisdiction_id, tax_year, value_basis, assessed_land,
               assessed_improvement, assessed_total, notice_received_on, provenance_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
            """,
            (
                property_id,
                jurisdiction_id,
                tax_year,
                value_basis,
                assessed_land,
                assessed_improvement,
                assessed_total,
                notice_received_on,
                provenance_id,
            ),
        ).fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise DuplicateAssessment(
            f"that body already has a {value_basis} {tax_year} assessment for this property"
        ) from error
    except psycopg.errors.CheckViolation as error:
        # A confirmed notice can still be impossible — a reviewer can ratify a
        # land line above the total — and a psycopg error reaching the client
        # as a 500 is a defect. Each rule answers in its own words instead.
        raise UnusableValue(
            REFUSALS.get(error.diag.constraint_name or "", "the notice's values were refused")
        ) from error
    assert row is not None
    return str(row["id"])


def record(conn: Conn, body: AssessmentIn, actor: str) -> AssessmentOut:
    """The manual door: an owner typing the notice they were mailed."""
    jurisdiction_id, jurisdiction_name = _resolve_jurisdiction(
        conn, body.property_id, body.jurisdiction_id
    )
    # confidence 1.0 is not decoration: provenance.stated_facts_are_certain
    # refuses 'owner_stated' at anything else — and it is true, because the
    # owner is reading the paper.
    provenance = conn.execute(
        """
        INSERT INTO provenance (kind, confidence, source_label)
        VALUES ('owner_stated', 1.0, %s) RETURNING id::text
        """,
        (
            f"{body.tax_year} assessment notice, {body.value_basis} value"
            f" ({jurisdiction_name}) entered by {actor}",
        ),
    ).fetchone()
    assert provenance is not None
    assessment_id = _insert(
        conn,
        property_id=str(body.property_id),
        jurisdiction_id=jurisdiction_id,
        tax_year=body.tax_year,
        value_basis=body.value_basis,
        assessed_land=body.assessed_land,
        assessed_improvement=body.assessed_improvement,
        assessed_total=body.assessed_total,
        notice_received_on=body.notice_received_on,
        provenance_id=str(provenance["id"]),
    )
    return for_property(conn, str(body.property_id), assessment_id=assessment_id)[0]


def _money(values: dict[str, str | None], path: str) -> Decimal | None:
    raw = values.get(path)
    if raw is None:
        return None
    amount = Decimal(raw)
    # An OPTIONAL money field can reach apply without ever passing a human, so
    # it never passed documents._canonicalise's bound either. Unbounded, an
    # eighteen-digit land line would reach the client as a psycopg
    # NumericValueOutOfRange 500 — after the gate had already flipped the
    # document. Refused here in a sentence, before anything is written.
    if abs(amount) > documents.MAX_MONEY:
        raise UnusableValue(f"{raw!r} exceeds the largest amount this records")
    return amount


def _date(values: dict[str, str | None], path: str) -> dt.date | None:
    raw = values.get(path)
    if raw is None:
        return None
    return dt.date.fromisoformat(raw)


def apply_notice(conn: Conn, doc_id: str, body: NoticeApplyIn, actor: str) -> AssessmentOut:
    """The document door: a reviewed notice becomes the row it describes."""
    gate = documents.claim_for_apply(conn, doc_id, actor)
    if gate["kind"] != "assessment_notice":
        raise documents.WrongApplyKind(
            f"a {gate['kind']} is not an assessment notice; apply it on its own route"
        )
    # No FOR UPDATE, unlike the settlement path: nothing here is a
    # read-then-write on a property row. Two concurrent notices for one year
    # race into the unique key and the loser gets a 409 from the database,
    # which is stronger than a lock because it also holds across the manual
    # door, where there is no document to gate on.
    links = conn.execute(
        "SELECT p.id::text AS id FROM document_properties dp"
        " JOIN properties p ON p.id = dp.property_id"
        " WHERE dp.document_id = %s ORDER BY p.id",
        (doc_id,),
    ).fetchall()
    if len(links) != 1:
        raise documents.NotExactlyOneProperty(
            f"{len(links)} properties are linked to this notice; one notice assesses one parcel"
        )
    property_id = str(links[0]["id"])
    jurisdiction_id, jurisdiction_name = _resolve_jurisdiction(
        conn, uuid.UUID(property_id), body.jurisdiction_id
    )
    values = documents.effective_values(conn, doc_id)
    # Subscripted, not .get(): 'confirmed' means every REQUIRED spec has a
    # reviewed, accepted value, and the gate proves the document was
    # confirmed. These three are the required specs for this kind.
    raw_year = str(values["assessment.tax_year"])
    raw_basis = str(values["assessment.value_basis"]).strip().lower()
    if not extraction_parse.plausible_tax_year(raw_year):
        raise UnusableValue(
            f"{raw_year!r} is not a tax year between {extraction_parse.MIN_TAX_YEAR}"
            f" and {extraction_parse.MAX_TAX_YEAR}; correct that field and apply again"
        )
    if raw_basis not in ("market", "taxable"):
        raise UnusableValue(
            f"{raw_basis!r} is not a value basis; say exactly 'market' (what the"
            " assessor says it is worth) or 'taxable' (what the tax is computed"
            " on), then apply again"
        )
    provenance = conn.execute(
        """
        INSERT INTO provenance (kind, confidence, source_label, source_document)
        VALUES ('document', 1.0, %s, %s) RETURNING id::text
        """,
        (
            f"Assessment notice {raw_year.strip()}, {raw_basis} value,"
            f" {jurisdiction_name} ({gate['filename']})",
            doc_id,
        ),
    ).fetchone()
    assert provenance is not None
    assessment_id = _insert(
        conn,
        property_id=property_id,
        jurisdiction_id=jurisdiction_id,
        tax_year=int(raw_year.strip()),
        value_basis=raw_basis,
        assessed_land=_money(values, "assessment.assessed_land"),
        assessed_improvement=_money(values, "assessment.assessed_improvement"),
        assessed_total=Decimal(str(values["assessment.assessed_total"])),
        notice_received_on=_date(values, "assessment.notice_date"),
        provenance_id=str(provenance["id"]),
    )
    return for_property(conn, property_id, assessment_id=assessment_id)[0]
