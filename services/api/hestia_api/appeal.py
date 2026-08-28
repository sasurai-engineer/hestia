"""The over-assessment card: what a body said, what the market says, and the
ratio the pack puts between them.

Two numbers are compared and one of them may need converting first. WHICH one
is never inferred: assessments.value_basis records it per row (module 019),
because market and taxable differ by a factor of three in Ohio and four in
Tennessee — "the largest silent error available anywhere in this system". A
market row is compared directly and the pack's ratio is CITED beside it,
unapplied, so a reader can see the ratio was considered and correctly
withheld. A taxable row is divided by the chain-resolved ratio, or it produces
a named gap; it is never divided by an assumed 1.0.

The window comes from the deadlines row the sweep already wrote rather than
from a second resolver, because jurisdiction_chain()'s own comment forbids
resolution order disagreeing between readers, and sweep._appeal_windows is the
sole authority on which of the three window shapes governs. What this module
resolves for itself is the paperwork the sweep does not carry: the form, the
conference prerequisite, and the offset that says which tax year the window
contests.

NO THRESHOLD IS APPLIED ANYWHERE. Every numeric threshold in this repository
traces to a named authority — the de-minimis cents to Treas. Reg.
1.263(a)-1(f), the Ohio deposit rate to ORC 5321.16(A) under "every number
here comes from the statute; none is a default". No pack seeds a materiality
figure and no jurisdiction publishes one, so this card states the gap between
two numbers and does not decide whether that gap is worth a filing fee.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel

from hestia_api import assessments

Conn = psycopg.Connection[dict[str, Any]]

CENT = Decimal("0.01")
# Six places, matching the land_share the assessment projection already
# publishes and jurisdiction_rules.value_numeric's own scale.
RATE = Decimal("0.000001")

# Which opinions of value are INDEPENDENT of the assessment being tested.
# A whitelist and not a blacklist: a ninth valuation_source member added later
# is inadmissible until somebody decides it belongs, which is the safe
# direction. This is a domain constant rather than pack data — it is
# identically true in all fifty states, so fifty identical rows would only
# create fifty chances for one of them to disagree.
#
#   assessor                  — IS the assessment. Comparing it to itself
#                               reports 0.00% over-assessed with a statute
#                               attached, and nothing about it looks broken.
#   purchase_price            — one transaction on one day, stale by
#                               construction. The document suggestion path
#                               already refuses the mirror image of this.
#   replacement_cost_estimate — cost to rebuild, land excluded; it answers an
#                               insurance question, not a market one.
#   owner_estimate            — the owner's own number, in the one proceeding
#                               where it is the number in dispute.
#                               assessment_appeals.opinion_of_value is where
#                               that belongs.
ADMISSIBLE_SOURCES = ("appraisal", "broker_opinion", "comparable_sales", "avm")

Pairing = Literal["contests_this_assessment", "contests_a_different_year", "unknown"]


class AppealGap(BaseModel):
    """A question this chain cannot answer. Named, never defaulted.

    Field-identical to deposit.GapOut and deliberately NOT shared: hoisting
    that model would rename its published schema and churn the generated
    client for no gain. Named differently, though — two classes called GapOut
    make FastAPI qualify BOTH into hestia_api__deposit__GapOut and
    hestia_api__appeal__GapOut, which renames the very schema the separation
    was meant to protect. A third occurrence is when to hoist one shared
    model; the second one just needs its own name.
    """

    code: str
    reason: str
    detail: str


class RuleTextOut(BaseModel):
    """A pack rule carried verbatim — the pack's own words and authority.

    Not parsed. `appeal.conference_required` reads "true; PVA conference ..."
    in Kentucky and "false; no conference prerequisite ..." in Ohio, and the
    leading-token convention already has two implementations that must agree.
    A third copy would be a third place for three readers to disagree, so this
    card prints what the pack wrote and lets the reader read it.
    """

    code: str
    text: str | None
    citation: str
    source: str


class RatioOut(BaseModel):
    """The pack's ratio, and whether this row's BASIS called for it."""

    code: str
    value: Decimal
    class_text: str | None
    citation: str
    source: str
    applied: bool
    applied_reason: str


class MarketOpinionOut(BaseModel):
    value: Decimal
    source: str
    as_of: dt.date
    # Stated, never scored. A 2019 opinion against a 2026 assessment is the
    # defect the land-split suggestion already refuses to commit.
    age_days: int
    # Present in the schema since module 005 and unreachable today: the
    # valuation writer accepts no band. Carried so the card can say the
    # comparand states no interval, rather than implying a precision one
    # figure does not have.
    low_estimate: Decimal | None
    high_estimate: Decimal | None
    provenance_kind: str
    confidence: float
    source_label: str | None


class AssessmentFinding(BaseModel):
    """One assessing body's claim about this property in one tax year, tested.

    `assessment` is the SAME projection the dossier renders, so the card and
    the dossier can never disagree about what the notice said.
    """

    assessment: assessments.AssessmentOut
    ratio: RatioOut | None
    implied_market_value: Decimal | None
    over_market_amount: Decimal | None
    over_market_pct: Decimal | None
    # The SIGN of a subtraction. Not a recommendation, and not a threshold.
    over_assessed: bool | None
    gaps: list[AppealGap]


class WindowOut(BaseModel):
    """The next appeal window, as the sweep wrote it, plus the paperwork."""

    opens_on: dt.date | None
    closes_on: dt.date
    citation: str
    instructions: RuleTextOut | None
    form: RuleTextOut | None
    conference: RuleTextOut | None
    # The window's CALENDAR year is not the tax year it contests. None where
    # no appeal.contests_tax_year_offset rule resolves — and that None is why
    # `pairing` reads "unknown" rather than pairing them anyway.
    contests_tax_year: int | None
    contests_tax_year_citation: str | None


class AppealCase(BaseModel):
    property_id: str
    state: str
    as_of: dt.date
    tax_year: int | None
    findings: list[AssessmentFinding]
    market_opinion: MarketOpinionOut | None
    # Prose that travels with the ratio: any assessment_ratio rule carrying
    # text and no number. Tennessee's attorney-general caveat is one, and it
    # renders whether or not a ratio was produced.
    ratio_notes: list[RuleTextOut]
    window: WindowOut | None
    pairing: Pairing
    gaps: list[AppealGap]


ANCHOR_SQL = """
SELECT p.id::text AS property_id, p.state,
       COALESCE(p.jurisdiction_id, s.id) AS start_id
FROM properties p
LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
WHERE p.id = %(property_id)s
"""

RULES_SQL = """
SELECT DISTINCT ON (r.code)
       r.code, r.value_numeric, r.value_text, r.citation, j.name AS source
FROM jurisdiction_chain(%(start_id)s) c
JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
JOIN jurisdictions j ON j.id = c.jurisdiction_id
WHERE r.domain = %(domain)s
  AND r.superseded_by IS NULL
  AND r.effective_from <= %(as_of)s
  AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
ORDER BY r.code, c.depth ASC, r.effective_from DESC
"""

COMPARAND_SQL = """
SELECT v.value, v.source::text AS source, v.as_of,
       v.low_estimate, v.high_estimate,
       pr.kind::text AS provenance_kind, pr.confidence::float AS confidence,
       pr.source_label
FROM valuations v JOIN provenance pr ON pr.id = v.provenance_id
WHERE v.property_id = %(property_id)s
  AND v.source = ANY(%(admissible)s::valuation_source[])
  -- money_amount is a bare NUMERIC(18,2): the DOMAIN permits zero and
  -- negatives, and only the writer's own gt=0 keeps them out of the one
  -- writer that exists today. The divisor is guarded here, in SQL.
  AND v.value > 0
  AND v.as_of <= %(as_of)s
-- The id tail is not decoration. created_at defaults to now(), which is the
-- TRANSACTION timestamp and therefore identical across every row of a bulk
-- load, so two rows sharing as_of would otherwise be ordered by whatever the
-- planner returned. A percentage that changes when nothing changed gets
-- reported as data corruption.
ORDER BY v.as_of DESC, v.created_at DESC, v.id DESC
LIMIT 1
"""

PRESENT_SOURCES_SQL = """
SELECT DISTINCT v.source::text AS source FROM valuations v
WHERE v.property_id = %(property_id)s ORDER BY 1
"""

WINDOW_SQL = """
SELECT d.due_on, d.window_opens_on, d.citation
FROM deadlines d
WHERE d.property_id = %(property_id)s
  AND d.kind = 'assessment_appeal_window'
  AND d.due_on >= %(as_of)s
ORDER BY d.due_on ASC, d.id ASC
LIMIT 1
"""


def _rules(conn: Conn, start_id: str, domain: str, as_of: dt.date) -> dict[str, Any]:
    """Every rule this chain carries in one domain, most specific body first,
    newest effective rule within that body, superseded and expired excluded.

    The ORDER BY is the sweep's, the deposit panel's and the coverage report's
    verbatim, because jurisdiction_chain() exists so that readers cannot
    disagree about which row wins.
    """
    return {
        row["code"]: row
        for row in conn.execute(
            RULES_SQL, {"start_id": start_id, "domain": domain, "as_of": as_of}
        ).fetchall()
    }


def _rule_text(row: Any) -> RuleTextOut:
    return RuleTextOut(
        code=row["code"],
        text=row["value_text"],
        citation=row["citation"],
        source=row["source"],
    )


def _ratio_for(ratio_rules: dict[str, Any], basis: str) -> tuple[RatioOut | None, AppealGap | None]:
    """The ratio this row's basis calls for, or the reason there is none.

    The discrimination is by ARITY and SHAPE, never by code name. A pack that
    carries one numeric ratio has answered; a pack that carries two has said
    the answer depends on a classification, and Tennessee's own caveat row
    opens "No bright-line rule" — so two is a question, not a menu to pick
    from. Choosing between them here would put a governance fact in dispatch
    logic, which is the ADR 0003 failure mode that the state-literal ratchet
    provably cannot catch, because the code would contain no state literal.
    """
    numeric = [row for row in ratio_rules.values() if row["value_numeric"] is not None]
    if basis == "market":
        # The comparison never needed it. Cited anyway, unapplied, so a reader
        # can see the ratio was considered and correctly withheld.
        if len(numeric) != 1:
            return None, None
        row = numeric[0]
        return (
            RatioOut(
                code=row["code"],
                value=row["value_numeric"],
                class_text=row["value_text"],
                citation=row["citation"],
                source=row["source"],
                applied=False,
                applied_reason=(
                    "the notice states a market value, so no ratio converts it —"
                    " it is already the figure a market opinion compares against"
                ),
            ),
            None,
        )
    if not numeric:
        return None, AppealGap(
            code="assessment.ratio",
            reason="no_rule_for_domain",
            detail=(
                "this notice states a taxable value and no assessment ratio resolves"
                " for its chain, so the full value it implies cannot be recovered;"
                " it is not assumed to be one"
            ),
        )
    if len(numeric) > 1:
        return None, AppealGap(
            code="assessment.ratio",
            reason="ambiguous_ratio",
            detail=(
                "the pack carries "
                + ", ".join(
                    f"{row['code']} = {row['value_numeric']}"
                    for row in sorted(numeric, key=lambda r: str(r["code"]))
                )
                + "; which one governs depends on how this property is classified,"
                " and the pack does not say"
            ),
        )
    row = numeric[0]
    if row["value_numeric"] <= 0:
        return None, AppealGap(
            code="assessment.ratio",
            reason="unusable_ratio",
            detail=(
                f"{row['code']} resolves to {row['value_numeric']} for"
                f" {row['source']}, which nothing can be divided by"
            ),
        )
    return (
        RatioOut(
            code=row["code"],
            value=row["value_numeric"],
            class_text=row["value_text"],
            citation=row["citation"],
            source=row["source"],
            applied=True,
            applied_reason=(
                "the notice states a taxable value, so the full value it implies is"
                f" the total divided by {row['value_numeric']}"
            ),
        ),
        None,
    )


def _finding(
    row: assessments.AssessmentOut,
    ratio_rules: dict[str, Any],
    market: MarketOpinionOut | None,
) -> AssessmentFinding:
    ratio, gap = _ratio_for(ratio_rules, row.value_basis)
    gaps = [gap] if gap is not None else []
    implied: Decimal | None = None
    if row.value_basis == "market":
        implied = row.assessed_total
    elif ratio is not None:
        implied = (row.assessed_total / ratio.value).quantize(CENT, rounding=ROUND_HALF_EVEN)
    if implied is None or market is None:
        return AssessmentFinding(
            assessment=row,
            ratio=ratio,
            implied_market_value=implied,
            over_market_amount=None,
            over_market_pct=None,
            over_assessed=None,
            gaps=gaps,
        )
    over = (implied - market.value).quantize(CENT, rounding=ROUND_HALF_EVEN)
    return AssessmentFinding(
        assessment=row,
        ratio=ratio,
        implied_market_value=implied,
        over_market_amount=over,
        over_market_pct=(over / market.value).quantize(RATE, rounding=ROUND_HALF_EVEN),
        # The sign of a subtraction. Whether it is worth a filing fee is a
        # question no jurisdiction publishes an answer to, so none is invented.
        over_assessed=over > 0,
        gaps=gaps,
    )


def _market_opinion(
    conn: Conn, property_id: str, as_of: dt.date
) -> tuple[MarketOpinionOut | None, AppealGap | None]:
    """The most recent independent opinion of value, or why there is none."""
    row = conn.execute(
        COMPARAND_SQL,
        {"property_id": property_id, "admissible": list(ADMISSIBLE_SOURCES), "as_of": as_of},
    ).fetchone()
    if row is not None:
        return (
            MarketOpinionOut(
                value=row["value"],
                source=row["source"],
                as_of=row["as_of"],
                age_days=(as_of - row["as_of"]).days,
                low_estimate=row["low_estimate"],
                high_estimate=row["high_estimate"],
                provenance_kind=row["provenance_kind"],
                confidence=row["confidence"],
                source_label=row["source_label"],
            ),
            None,
        )
    present = [
        found["source"]
        for found in conn.execute(PRESENT_SOURCES_SQL, {"property_id": property_id}).fetchall()
    ]
    inadmissible = sorted(set(present) - set(ADMISSIBLE_SOURCES))
    # Naming what WAS on file is the difference between "nobody has valued
    # this" and "the only value on file is the assessor's own, which is the
    # number under test". The second reads as an answer if it is not said.
    detail = (
        "no independent opinion of value is on file; an assessment can only be tested against one"
        if not inadmissible
        else (
            "the only values on file come from "
            + ", ".join(inadmissible)
            + ", none of which is independent of the assessment being tested;"
            " an assessor's own figure compared to itself is never over-assessed"
        )
    )
    return None, AppealGap(code="valuations", reason="no_market_opinion", detail=detail)


def _window(
    conn: Conn, property_id: str, appeal_rules: dict[str, Any], as_of: dt.date
) -> tuple[WindowOut | None, AppealGap | None]:
    """The window the sweep already wrote, plus the paperwork around it.

    Read rather than re-resolved: the sweep is the sole authority on which of
    the three window shapes governs — a published date beats a computed one,
    and a published date already past is a gap rather than a roll-forward —
    and a second opinion here could disagree with the calendar the owner is
    looking at.
    """
    row = conn.execute(WINDOW_SQL, {"property_id": property_id, "as_of": as_of}).fetchone()
    if row is None:
        return None, AppealGap(
            code="assessment_appeal_window",
            reason="no_window_scheduled",
            detail=(
                "no upcoming appeal window is on the calendar for this property;"
                " run a deadline sweep, and if none appears the coverage report"
                " says which jurisdiction fact is missing"
            ),
        )
    offset_rule = appeal_rules.get("appeal.contests_tax_year_offset")
    contests = (
        None if offset_rule is None else row["due_on"].year + int(offset_rule["value_numeric"])
    )
    return (
        WindowOut(
            opens_on=row["window_opens_on"],
            closes_on=row["due_on"],
            citation=row["citation"],
            instructions=(
                _rule_text(appeal_rules["appeal.instructions"])
                if "appeal.instructions" in appeal_rules
                else None
            ),
            form=(
                _rule_text(appeal_rules["appeal.form"]) if "appeal.form" in appeal_rules else None
            ),
            conference=(
                _rule_text(appeal_rules["appeal.conference_required"])
                if "appeal.conference_required" in appeal_rules
                else None
            ),
            contests_tax_year=contests,
            contests_tax_year_citation=(None if offset_rule is None else offset_rule["citation"]),
        ),
        None,
    )


def read(conn: Conn, property_id: str, *, as_of: dt.date) -> AppealCase:
    """The card: every body's claim about the latest tax year on file, each
    converted if its basis calls for it, against one independent opinion."""
    anchor = conn.execute(ANCHOR_SQL, {"property_id": property_id}).fetchone()
    assert anchor is not None  # the endpoint has already proven the property exists
    empty = AppealCase(
        property_id=property_id,
        state=anchor["state"],
        as_of=as_of,
        tax_year=None,
        findings=[],
        market_opinion=None,
        ratio_notes=[],
        window=None,
        pairing="unknown",
        gaps=[],
    )
    if anchor["start_id"] is None:
        empty.gaps.append(
            AppealGap(
                code="jurisdiction",
                reason="no_state_jurisdiction",
                detail=f"no jurisdiction pack is loaded for {anchor['state']}",
            )
        )
        return empty

    rows = assessments.for_property(conn, property_id)
    if not rows:
        empty.gaps.append(
            AppealGap(
                code="assessments",
                reason="no_assessment_on_file",
                detail=(
                    "nothing is recorded about what this property is assessed at;"
                    " enter the notice, or upload it"
                ),
            )
        )
        return empty

    # tax_year DESC is the only defensible ordering: there is no as_of column,
    # notice_received_on is nullable and may legitimately sit years after the
    # year it assesses, and created_at says when somebody typed. Every row of
    # that year is a finding — two bases for one body and two bodies for one
    # year are both legal, and a LIMIT 1 would fabricate an answer about the
    # row it dropped.
    tax_year = rows[0].tax_year
    current = [row for row in rows if row.tax_year == tax_year]

    # The ratio in force IN THE ASSESSED YEAR, not the one in force the day the
    # card is opened. Today they agree everywhere; the day a state changes its
    # ratio they will not, and a card that quietly used today's would be
    # answering about a notice with a rule that postdates it.
    ratio_rules = _rules(conn, anchor["start_id"], "assessment_ratio", dt.date(tax_year, 1, 1))
    appeal_rules = _rules(conn, anchor["start_id"], "assessment_appeal", as_of)

    market, market_gap = _market_opinion(conn, property_id, as_of)
    window, window_gap = _window(conn, property_id, appeal_rules, as_of)
    gaps = [gap for gap in (market_gap, window_gap) if gap is not None]

    pairing: Pairing = "unknown"
    if window is not None and window.contests_tax_year is not None:
        pairing = (
            "contests_this_assessment"
            if window.contests_tax_year == tax_year
            else "contests_a_different_year"
        )

    return AppealCase(
        property_id=property_id,
        state=anchor["state"],
        as_of=as_of,
        tax_year=tax_year,
        findings=[_finding(row, ratio_rules, market) for row in current],
        market_opinion=market,
        ratio_notes=[
            _rule_text(row) for row in ratio_rules.values() if row["value_numeric"] is None
        ],
        window=window,
        pairing=pairing,
        gaps=gaps,
    )
