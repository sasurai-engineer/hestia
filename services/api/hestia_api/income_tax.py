"""The income-tax rates a property's own chain resolves, per taxing body.

Issue #8 asked for a per-jurisdiction state rate on tax_profiles. The rate was
already in the packs — Kentucky's flat 3.5% has cited KRS 141.020 since the
pack shipped, Cincinnati's 1.8% cites ORC ch. 718 — so what ships here is the
reader that was missing, and module 020 removed the entity-side column that
would have become a second place for the same number to live. ADR 0003: a
cited statutory number is jurisdiction data, resolved through
jurisdiction_chain(), never copied into a taxpayer's row.

TWO THINGS THIS DOES DIFFERENTLY FROM appeal._rules, both deliberate.

Resolution is PER BODY, not collapsed across the chain. The appeal card takes
one winner per code over the whole chain because exactly one appeal window
governs. Income tax is levied by more than one government at once — Kentucky
at the state and Cincinnati at the city, both owed, on the same dollar — and
collapsing would silently drop whichever body lost. The ordering WITHIN a body
is the shared one, so no reader disagrees with another about which ROW wins;
they differ only in how many BODIES answer, which is the fact being measured.

The as-of date is derived from the tax year and never from the clock:
December 31 of the year asked for, because an income tax is a full-year
measure applied on a return filed after the year closes. The appeal card
anchors its ratio at January 1 of the assessed year, which is the lien date —
a different fact with a different anchor, not a drift from this one. A card
for 2026 must read the same in 2029.

NOTHING IS SUMMED, and no combined rate is published. Whether a municipal rate
stacks on a state rate, is deductible against it, or is credited by the state
of residence is a governance fact; Ohio's own reciprocity and residence-credit
rules differ by municipality and no pack states any of it. This lists bodies.
And nothing here is after-tax anything: Schedule E computes taxable rental
income and is deliberately untouched, the rate applying downstream.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import psycopg
from pydantic import BaseModel

Conn = psycopg.Connection[dict[str, Any]]

DOMAIN = "income_tax"

# Which income_tax codes state a RATE this card may present as one. A
# whitelist and not a blacklist, on the appeal card's reasoning: a code seeded
# later is carried as a note until somebody decides it belongs, which is the
# safe direction. A domain constant rather than pack data — the code
# vocabulary is the packs' shared language and means the same thing in all
# fifty states, so fifty identical rows would only create fifty chances for
# one of them to disagree.
#
#   income.flat_rate      — a state taxing at one rate (Kentucky, KRS 141.020)
#   income.municipal_rate — a city levying its own (Cincinnati, ORC ch. 718)
#
# INADMISSIBLE, each for a stated reason, and each still carried verbatim in
# `notes` so nothing is dropped:
#
#   income.entity_excise_rate, income.entity_franchise_rate — a different
#     taxpayer's tax. Tennessee's own seed says so in the file: the entity
#     "still meets the franchise and excise taxes, which is a different
#     question from the owner's own return".
#   income.entity_franchise_minimum — 100 is one hundred DOLLARS.
#     jurisdiction_rules.value_numeric carries no unit, the code name is the
#     only thing that says which figures are rates, and a card that treated
#     this one as a rate would be off by a factor of a hundred.
#   income.type, income.entity_exemption — prose. They carry no number.
ADMISSIBLE_RATE_CODES = ("income.flat_rate", "income.municipal_rate")


class UnknownEntity(Exception):
    """No such entity."""


class RateGap(BaseModel):
    """A question this chain cannot answer. Named, never defaulted.

    Field-identical to appeal.AppealGap and deposit.GapOut and deliberately
    NOT shared, for the reason the appeal card's own docstring gives: two
    classes with one name make FastAPI qualify both and rename the very
    schema the separation protects. Named differently instead.
    """

    code: str
    reason: str
    detail: str


class BodyRateOut(BaseModel):
    """One taxing body's rate, with the body's own authority."""

    jurisdiction_id: str
    jurisdiction: str
    level: str
    # Depth 0 is the property's own most specific body. Published so a reader
    # can see WHY two rates are both owed rather than one overriding the other.
    depth: int
    code: str
    rate: Decimal
    citation: str


class RuleNoteOut(BaseModel):
    """Everything else the domain carries at a body, whole and unparsed.

    Number AND words: income.entity_excise_rate states 0.065 in value_numeric
    and its subject in value_text, and a note dropping either half would be
    lossy. Not parsed — the pack's leading-token convention already has two
    implementations that must agree, and a third would be a third place to
    disagree. This prints what the pack wrote.
    """

    jurisdiction: str
    level: str
    depth: int
    code: str
    value: Decimal | None
    text: str | None
    citation: str


class PropertyTaxRates(BaseModel):
    property_id: str
    label: str
    state: str
    tax_year: int
    as_of: dt.date
    # Carried, not filtered on: an entity that sold its Ohio property in the
    # filing year still owes Ohio on the gain, and the disposal year is
    # precisely when the rate matters. The coverage report excludes disposed
    # properties because a deadline for a sold house is noise; a rate for the
    # year it sold is not.
    disposed_on: dt.date | None
    rates: list[BodyRateOut]
    notes: list[RuleNoteOut]
    gaps: list[RateGap]


class EntityTaxRates(BaseModel):
    """Every property this entity owns, each resolving its own chain.

    This is issue #8's first acceptance clause as the schema can honestly meet
    it. The entity carries no rates — an entity has no situs, and
    entities.formation_state is explicitly not one. Its PROPERTIES carry them,
    and this is the union, unaggregated: no combined rate, no apportionment,
    no total.
    """

    entity_id: str
    entity: str
    tax_year: int
    properties: list[PropertyTaxRates]


ANCHOR_SQL = """
SELECT p.id::text AS property_id, p.label, p.state, p.disposed_on,
       COALESCE(p.jurisdiction_id, s.id) AS start_id
FROM properties p
LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
WHERE p.id = %(property_id)s
"""

# One winner per (BODY, code) — not per code across the chain.
RULES_SQL = """
SELECT resolved.* FROM (
  SELECT DISTINCT ON (c.jurisdiction_id, r.code)
         c.depth,
         j.id::text    AS jurisdiction_id,
         j.name        AS jurisdiction,
         j.level::text AS level,
         r.code, r.value_numeric, r.value_text, r.citation
  FROM jurisdiction_chain(%(start_id)s) c
  JOIN jurisdictions j ON j.id = c.jurisdiction_id
  JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
  WHERE r.domain = %(domain)s
    AND r.superseded_by IS NULL
    AND r.effective_from <= %(as_of)s
    AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
  -- The id tail is not decoration. jurisdiction_rules has no uniqueness
  -- constraint covering same-day corrections, so two rows can share an
  -- effective_from and would otherwise be ordered by whatever the planner
  -- returned. A rate that changes when nothing changed gets reported as data
  -- corruption.
  ORDER BY c.jurisdiction_id, r.code, r.effective_from DESC, r.id DESC
) resolved
ORDER BY resolved.depth ASC, resolved.code
"""

ENTITY_SQL = "SELECT name FROM entities WHERE id = %(entity_id)s"

ENTITY_PROPERTIES_SQL = """
SELECT id::text AS property_id FROM properties
WHERE entity_id = %(entity_id)s
ORDER BY created_at, id
"""


def for_property(conn: Conn, property_id: str, *, tax_year: int) -> PropertyTaxRates:
    """Every taxing body that reaches this property, and what each levies."""
    # December 31: an income tax is a full-year measure, so the year decides
    # the as-of and the clock never does. A 2026 card reads the same in 2029.
    as_of = dt.date(tax_year, 12, 31)
    anchor = conn.execute(ANCHOR_SQL, {"property_id": property_id}).fetchone()
    assert anchor is not None  # the endpoint has already proven it exists
    empty = PropertyTaxRates(
        property_id=property_id,
        label=anchor["label"],
        state=anchor["state"],
        tax_year=tax_year,
        as_of=as_of,
        disposed_on=anchor["disposed_on"],
        rates=[],
        notes=[],
        gaps=[],
    )
    if anchor["start_id"] is None:
        empty.gaps.append(
            RateGap(
                code="jurisdiction",
                reason="no_state_jurisdiction",
                detail=f"no jurisdiction pack is loaded for {anchor['state']}",
            )
        )
        return empty

    rows = conn.execute(
        RULES_SQL, {"start_id": anchor["start_id"], "domain": DOMAIN, "as_of": as_of}
    ).fetchall()
    rates = [
        BodyRateOut(
            jurisdiction_id=row["jurisdiction_id"],
            jurisdiction=row["jurisdiction"],
            level=row["level"],
            depth=row["depth"],
            code=row["code"],
            rate=row["value_numeric"],
            citation=row["citation"],
        )
        for row in rows
        if row["code"] in ADMISSIBLE_RATE_CODES and row["value_numeric"] is not None
    ]
    notes = [
        RuleNoteOut(
            jurisdiction=row["jurisdiction"],
            level=row["level"],
            depth=row["depth"],
            code=row["code"],
            value=row["value_numeric"],
            text=row["value_text"],
            citation=row["citation"],
        )
        for row in rows
        if row["code"] not in ADMISSIBLE_RATE_CODES or row["value_numeric"] is None
    ]
    gaps: list[RateGap] = []
    if not rates:
        # Not the same as "this state has no income tax". Tennessee says that
        # in a note, with its authority; a state whose pack simply carries no
        # rate says nothing at all, and the two must not read alike.
        gaps.append(
            RateGap(
                code="income_tax",
                reason="no_rate_for_chain",
                detail=(
                    "no taxing body on this property's chain states a rate this"
                    " build reads as one"
                    + (
                        "; the domain's other rows are carried below as notes"
                        if notes
                        else ", and the domain carries nothing else either"
                    )
                ),
            )
        )
    return PropertyTaxRates(
        property_id=property_id,
        label=anchor["label"],
        state=anchor["state"],
        tax_year=tax_year,
        as_of=as_of,
        disposed_on=anchor["disposed_on"],
        rates=rates,
        notes=notes,
        gaps=gaps,
    )


def for_entity(conn: Conn, entity_id: str, *, tax_year: int) -> EntityTaxRates:
    """The cross-river case: one entity, two states, each property answering
    from its own chain rather than from a column that could name one."""
    entity = conn.execute(ENTITY_SQL, {"entity_id": entity_id}).fetchone()
    if entity is None:
        raise UnknownEntity(entity_id)
    owned = conn.execute(ENTITY_PROPERTIES_SQL, {"entity_id": entity_id}).fetchall()
    return EntityTaxRates(
        entity_id=entity_id,
        entity=entity["name"],
        tax_year=tax_year,
        properties=[for_property(conn, row["property_id"], tax_year=tax_year) for row in owned],
    )
