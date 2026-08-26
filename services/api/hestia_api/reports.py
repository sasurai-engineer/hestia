"""Report read models: the ledger rolled up with its authorities attached.

Schedule E is a JOIN against the effectivity-dated mapping data — the report
takes the newest mapping row with tax_year_from <= the report year, shows the
excluded categories instead of dropping them, pulls line 18 from the
depreciation engine's persisted entries, and surfaces spend that still needs
a repair-vs-improvement answer instead of guessing one. Property scope means
rows anchored to the property or to its units and leases; entity-anchored
rows are portfolio-level and belong to the entity's own statements.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import psycopg
from hestia_sim.capex import ComponentSpec, simulate
from pydantic import BaseModel

Conn = psycopg.Connection[dict[str, Any]]

# The de minimis safe harbor: repair-category spend at or above this, with the
# capital question unanswered, is flagged for classification rather than
# silently deducted. Treas. Reg. 1.263(a)-1(f)(1)(ii)(D) — $2,500 per item
# without an applicable financial statement.
DE_MINIMIS_CENTS = Decimal("2500.00")

PROPERTY_SCOPE = """
  (e.property_id = %(property_id)s
   OR e.unit_id IN (SELECT id FROM units WHERE property_id = %(property_id)s)
   OR e.lease_id IN (SELECT l.id FROM leases l
                     JOIN units u ON u.id = l.unit_id
                     WHERE u.property_id = %(property_id)s))
"""


class ScheduleELine(BaseModel):
    line_no: int
    label: str
    citation: str
    amount: Decimal  # positive magnitudes, per the form


class ExcludedAmount(BaseModel):
    label: str
    citation: str
    amount: Decimal


class NeedsClassification(BaseModel):
    event_uuid: str
    occurred_on: dt.date
    memo: str | None
    amount: Decimal
    reason: str


class Signoff(BaseModel):
    confirmed_by: str
    confirmed_at: dt.datetime
    note: str | None
    # A sign-off certifies NUMBERS. When the live report no longer matches
    # what was certified (a back-dated correction), it is STALE and says so.
    stale: bool


class ScheduleEReport(BaseModel):
    property_id: str
    tax_year: int
    income_lines: list[ScheduleELine]
    expense_lines: list[ScheduleELine]
    depreciation_line_18: Decimal
    depreciation_citation: str
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    excluded: list[ExcludedAmount]
    needs_classification: list[NeedsClassification]
    signoff: Signoff | None
    caveat: str


class MonthlyFlow(BaseModel):
    month: int
    operating_in: Decimal
    operating_out: Decimal
    debt_service: Decimal
    capital: Decimal
    owner_flows: Decimal
    net: Decimal


class CashFlowReport(BaseModel):
    property_id: str
    year: int
    months: list[MonthlyFlow]
    total_net: Decimal


class RentRollRow(BaseModel):
    property_label: str
    unit_label: str
    residents: list[str]
    rent: Decimal
    status: str
    starts_on: dt.date
    ends_on: dt.date | None


def _mapping(conn: Conn, tax_year: int) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT DISTINCT ON (category)
               category::text, line_no, line_label, citation
        FROM schedule_e_map
        WHERE tax_year_from <= %s
        ORDER BY category, tax_year_from DESC
        """,
        (tax_year,),
    ).fetchall()


def schedule_e(conn: Conn, property_id: str, tax_year: int) -> ScheduleEReport:
    rollup = {
        row["category"]: row["total"]
        for row in conn.execute(
            f"""
            SELECT e.category::text AS category, sum(e.amount) AS total
            FROM ledger_events e
            WHERE {PROPERTY_SCOPE}
              AND e.occurred_on >= make_date(%(year)s, 1, 1)
              AND e.occurred_on <= make_date(%(year)s, 12, 31)
            GROUP BY e.category
            """,  # noqa: S608 - PROPERTY_SCOPE is a module constant
            {"property_id": property_id, "year": tax_year},
        ).fetchall()
    }
    income_lines: dict[int, ScheduleELine] = {}
    expense_lines: dict[int, ScheduleELine] = {}
    excluded: list[ExcludedAmount] = []
    for entry in _mapping(conn, tax_year):
        total = rollup.get(entry["category"])
        if total is None:
            continue
        if entry["line_no"] is None:
            excluded.append(
                ExcludedAmount(
                    label=entry["line_label"],
                    citation=entry["citation"],
                    amount=abs(total),
                )
            )
            continue
        # SIGNED honesty: income lines carry the net as-is (a clawback year
        # shows negative rent, never fake income); expense lines negate the
        # net so money spent reads positive — and a net REFUND in an expense
        # category reads negative, a recovery, instead of abs() forging it
        # into an expense (the adversarial review's insurance-refund case).
        is_income = entry["line_no"] <= 4
        signed = total if is_income else -total
        bucket = income_lines if is_income else expense_lines
        line = bucket.get(entry["line_no"])
        if line is None:
            bucket[entry["line_no"]] = ScheduleELine(
                line_no=entry["line_no"],
                label=entry["line_label"],
                citation=entry["citation"],
                amount=signed,
            )
        else:
            line.amount += signed
    depreciation = conn.execute(
        """
        SELECT coalesce(sum(de.amount), 0) AS total
        FROM depreciation_entries de
        JOIN depreciable_assets da ON da.id = de.asset_id
        WHERE da.property_id = %s AND da.book = 'federal' AND de.tax_year = %s
        """,
        (property_id, tax_year),
    ).fetchone()["total"]  # type: ignore[index]
    flags = conn.execute(
        f"""
        SELECT e.event_uuid::text, e.occurred_on, e.memo, e.amount
        FROM ledger_events e
        WHERE {PROPERTY_SCOPE}
          AND e.occurred_on >= make_date(%(year)s, 1, 1)
          AND e.occurred_on <= make_date(%(year)s, 12, 31)
          AND e.category = 'repairs'
          AND e.is_capital IS NULL
          AND abs(e.amount) >= %(threshold)s
        ORDER BY e.occurred_on
        """,  # noqa: S608 - PROPERTY_SCOPE is a module constant
        {"property_id": property_id, "year": tax_year, "threshold": DE_MINIMIS_CENTS},
    ).fetchall()
    signoff_row = conn.execute(
        """
        SELECT confirmed_by, confirmed_at, note,
               certified_income, certified_expenses,
               certified_depreciation, certified_net
        FROM report_signoffs
        WHERE property_id = %s AND tax_year = %s AND report_kind = 'schedule_e'
        """,
        (property_id, tax_year),
    ).fetchone()
    total_income = sum((line.amount for line in income_lines.values()), Decimal(0))
    total_expenses = sum((line.amount for line in expense_lines.values()), Decimal(0))
    net = total_income - total_expenses - depreciation
    signoff = None
    if signoff_row is not None:
        signoff = Signoff(
            confirmed_by=signoff_row["confirmed_by"],
            confirmed_at=signoff_row["confirmed_at"],
            note=signoff_row["note"],
            stale=(
                signoff_row["certified_net"] is not None
                and (
                    signoff_row["certified_income"] != total_income
                    or signoff_row["certified_expenses"] != total_expenses
                    or signoff_row["certified_depreciation"] != depreciation
                    or signoff_row["certified_net"] != net
                )
            ),
        )
    return ScheduleEReport(
        property_id=property_id,
        tax_year=tax_year,
        income_lines=sorted(income_lines.values(), key=lambda line: line.line_no),
        expense_lines=sorted(expense_lines.values(), key=lambda line: line.line_no),
        depreciation_line_18=depreciation,
        depreciation_citation=(
            "Schedule E line 18; computed per-asset by the dual-book engine "
            "(IRC s.167/s.168), federal book"
        ),
        total_income=total_income,
        total_expenses=total_expenses,
        net=net,
        excluded=excluded,
        needs_classification=[
            NeedsClassification(
                event_uuid=flag["event_uuid"],
                occurred_on=flag["occurred_on"],
                memo=flag["memo"],
                amount=abs(flag["amount"]),
                reason=(
                    "repairs-category spend at or above the $2,500 de minimis "
                    "threshold with the repair-vs-improvement question "
                    "unanswered — Treas. Reg. 1.263(a)-1(f)"
                ),
            )
            for flag in flags
        ],
        signoff=signoff,
        caveat=(
            "Engineering scaffolding for a tax professional's review, not tax "
            "advice; the sign-off gate exists for exactly that reason."
        ),
    )


OPERATING_EXPENSE = (
    "advertising",
    "travel",
    "insurance",
    "legal_professional",
    "management_fee",
    "repairs",
    "supplies",
    "property_tax",
    "utilities",
    "hoa",
)
INCOME = ("rent", "other_income", "late_fee")
DEBT_SERVICE = ("mortgage_interest", "mortgage_principal")
CAPITAL = ("capital_improvement", "acquisition_cost", "disposition_cost")
OWNER = ("owner_contribution", "owner_distribution", "deposit_received", "deposit_returned")


def cash_flow(conn: Conn, property_id: str, year: int) -> CashFlowReport:
    rows = conn.execute(
        f"""
        SELECT extract(month FROM e.occurred_on)::int AS month,
               e.category::text AS category, sum(e.amount) AS total
        FROM ledger_events e
        WHERE {PROPERTY_SCOPE}
          AND e.occurred_on >= make_date(%(year)s, 1, 1)
          AND e.occurred_on <= make_date(%(year)s, 12, 31)
        GROUP BY 1, 2
        """,  # noqa: S608 - PROPERTY_SCOPE is a module constant
        {"property_id": property_id, "year": year},
    ).fetchall()
    months = {
        month: {
            "in": Decimal(0),
            "out": Decimal(0),
            "debt": Decimal(0),
            "capital": Decimal(0),
            "owner": Decimal(0),
        }
        for month in range(1, 13)
    }
    for row in rows:
        bucket = months[row["month"]]
        if row["category"] in INCOME:
            bucket["in"] += row["total"]
        elif row["category"] in OPERATING_EXPENSE:
            bucket["out"] += row["total"]
        elif row["category"] in DEBT_SERVICE:
            bucket["debt"] += row["total"]
        elif row["category"] in CAPITAL:
            bucket["capital"] += row["total"]
        else:
            bucket["owner"] += row["total"]
    monthly = [
        MonthlyFlow(
            month=month,
            operating_in=values["in"],
            operating_out=values["out"],
            debt_service=values["debt"],
            capital=values["capital"],
            owner_flows=values["owner"],
            net=sum(values.values(), Decimal(0)),
        )
        for month, values in months.items()
    ]
    return CashFlowReport(
        property_id=property_id,
        year=year,
        months=monthly,
        total_net=sum((flow.net for flow in monthly), Decimal(0)),
    )


def rent_roll(conn: Conn) -> list[RentRollRow]:
    rows = conn.execute(
        """
        SELECT p.label AS property_label, u.label AS unit_label,
               l.rent, l.status::text, l.starts_on, l.ends_on,
               coalesce(array_agg(r.full_name ORDER BY r.full_name)
                        FILTER (WHERE r.full_name IS NOT NULL), '{}') AS residents
        FROM leases l
        JOIN units u ON u.id = l.unit_id
        JOIN properties p ON p.id = u.property_id
        LEFT JOIN lease_residents lr ON lr.lease_id = l.id
        LEFT JOIN residents r ON r.id = lr.resident_id
        WHERE l.status IN ('active', 'month_to_month')
        GROUP BY p.label, u.label, l.rent, l.status, l.starts_on, l.ends_on
        ORDER BY p.label, u.label
        """
    ).fetchall()
    return [RentRollRow(**row) for row in rows]


class DebtTerms(BaseModel):
    lender: str | None
    original_principal: Decimal
    annual_rate: Decimal
    term_months: int
    months_elapsed: int


class PolicyOut(BaseModel):
    id: str
    kind: str
    carrier: str | None
    effective_to: dt.date
    coinsurance_percent: Decimal | None
    dwelling_limit: Decimal | None
    loss_of_rents_months: int | None


class ValuationOut(BaseModel):
    value: Decimal
    source: str
    as_of: dt.date


class Financials(BaseModel):
    property_id: str
    income_12mo: Decimal
    operating_expenses_12mo: Decimal
    noi_12mo: Decimal
    valuation: ValuationOut | None
    debts: list[DebtTerms]
    policies: list[PolicyOut]


def financials(conn: Conn, property_id: str, as_of: dt.date) -> Financials:
    """The raw inputs the client-side engines want: NOI from the ledger's
    trailing twelve months, the newest valuation, note terms, and the
    insurance position. Arithmetic beyond rollups happens in the engines."""
    start = as_of - dt.timedelta(days=365)
    rollup = conn.execute(
        f"""
        SELECT
          coalesce(sum(e.amount) FILTER (WHERE e.category::text = ANY(%(income)s)), 0)
            AS income,
          coalesce(sum(e.amount) FILTER (WHERE e.category::text = ANY(%(operating)s)), 0)
            AS operating
        FROM ledger_events e
        WHERE {PROPERTY_SCOPE}
          AND e.occurred_on > %(start)s AND e.occurred_on <= %(as_of)s
        """,  # noqa: S608 - PROPERTY_SCOPE is a module constant
        {
            "property_id": property_id,
            "start": start,
            "as_of": as_of,
            "income": list(INCOME),
            "operating": list(OPERATING_EXPENSE),
        },
    ).fetchone()
    valuation = conn.execute(
        """
        SELECT value, source::text, as_of FROM valuations
        WHERE property_id = %s ORDER BY as_of DESC, created_at DESC LIMIT 1
        """,
        (property_id,),
    ).fetchone()
    debts = conn.execute(
        """
        SELECT lender, original_principal, interest_rate AS annual_rate, term_months,
               greatest(0,
                 (extract(year FROM %(as_of)s::date) * 12
                    + extract(month FROM %(as_of)s::date))::int
                 - (extract(year FROM coalesce(first_payment_on, originated_on)) * 12
                    + extract(month FROM coalesce(first_payment_on, originated_on)))::int
                 + 1) AS months_elapsed
        FROM debt_instruments
        WHERE property_id = %(property_id)s AND paid_off_on IS NULL
        ORDER BY lien_position
        """,
        {"property_id": property_id, "as_of": as_of},
    ).fetchall()
    policies = conn.execute(
        """
        SELECT p.id::text, p.kind::text, p.carrier, p.effective_to,
               p.coinsurance_percent,
               (SELECT c.limit_amount FROM coverages c
                WHERE c.policy_id = p.id AND c.description ILIKE '%%dwelling%%'
                ORDER BY c.limit_amount DESC NULLS LAST LIMIT 1) AS dwelling_limit,
               (SELECT c.months_covered FROM coverages c
                WHERE c.policy_id = p.id AND c.months_covered IS NOT NULL
                ORDER BY c.months_covered DESC LIMIT 1) AS loss_of_rents_months
        FROM policies p
        WHERE p.property_id = %s AND p.effective_to >= CURRENT_DATE
        ORDER BY p.effective_from DESC
        """,
        (property_id,),
    ).fetchall()
    return Financials(
        property_id=property_id,
        income_12mo=rollup["income"],  # type: ignore[index]
        operating_expenses_12mo=-rollup["operating"],  # type: ignore[index] - signed: a net-refund year reads negative
        noi_12mo=rollup["income"] + rollup["operating"],  # type: ignore[index]
        valuation=ValuationOut(**valuation) if valuation else None,
        debts=[DebtTerms(**debt) for debt in debts],
        policies=[PolicyOut(**policy) for policy in policies],
    )


class CapexBand(BaseModel):
    year: int
    expected: Decimal
    p10: Decimal
    p50: Decimal
    p90: Decimal


class CapexForecastOut(BaseModel):
    property_id: str
    horizon_years: int
    components_simulated: int
    components_without_cost: list[str]
    bands: list[CapexBand]
    total_expected: Decimal


def capex_forecast(
    conn: Conn, property_id: str, *, horizon_years: int, as_of: dt.date
) -> CapexForecastOut:
    """The Weibull Monte Carlo over the LIVE component inventory. Seeded from
    the property id, so the forecast is reproducible until the inventory
    changes. Components with no cost anywhere are named, not silently
    dropped."""
    rows = conn.execute(
        """
        SELECT ct.code, ct.weibull_shape::float, ct.weibull_scale_years::float,
               coalesce(c.replacement_cost, ct.typical_cost) AS cost,
               c.installed_on, c.installed_year_low, c.installed_year_high,
               coalesce(c.expected_life_years, ct.weibull_scale_years)::float AS scale_override
        FROM components c
        JOIN component_types ct ON ct.id = c.component_type_id
        WHERE c.property_id = %s AND c.retired_on IS NULL
        ORDER BY ct.code
        """,
        (property_id,),
    ).fetchall()
    specs: list[ComponentSpec] = []
    skipped: list[str] = []
    for row in rows:
        if row["cost"] is None:
            skipped.append(row["code"])
            continue
        if row["installed_on"] is not None:
            age = (as_of - row["installed_on"]).days / 365.25
            age_low = age_high = max(0.0, age)
        else:
            age_low = max(0.0, as_of.year - row["installed_year_high"])
            age_high = max(age_low, as_of.year - row["installed_year_low"])
        specs.append(
            ComponentSpec(
                name=row["code"],
                age_low=age_low,
                age_high=age_high,
                shape=row["weibull_shape"],
                scale=row["scale_override"],
                replacement_cost_cents=int(row["cost"] * 100),
            )
        )
    seed = int(property_id.replace("-", "")[:8], 16)
    forecast = simulate(specs, horizon_years=horizon_years, trials=2000, seed=seed)
    return CapexForecastOut(
        property_id=property_id,
        horizon_years=horizon_years,
        components_simulated=len(specs),
        components_without_cost=skipped,
        bands=[
            CapexBand(
                year=year,
                expected=Decimal(expected) / 100,
                p10=Decimal(p10) / 100,
                p50=Decimal(p50) / 100,
                p90=Decimal(p90) / 100,
            )
            for year, expected, p10, p50, p90 in zip(
                forecast.years,
                forecast.expected_cents,
                forecast.p10_cents,
                forecast.p50_cents,
                forecast.p90_cents,
                strict=True,
            )
        ],
        total_expected=Decimal(forecast.total_expected_cents) / 100,
    )
