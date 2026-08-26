"""The deadline sweep: portfolio facts in, calendar rows out, idempotently.

Each generator reads one kind of fact and emits deadline rows; the
`deadlines_sweep_identity` unique index makes re-runs no-ops at the database,
so the sweep can be fired on every dossier refresh without ceremony. Every row
carries the authority that creates the date — the platform does not alert on
guesses.

Jurisdiction-dependent deadlines are resolved through jurisdiction_chain() x
jurisdiction_rules (most specific body wins, newest effective rule, superseded
rows excluded) and a calendar registry keyed by pack data (ADR 0003). Where a
property's chain has no loaded rule, the sweep emits NO deadline and a typed
COVERAGE GAP instead: partial coverage is honest and visible, never silent.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import psycopg

from hestia_api import calendar

Conn = psycopg.Connection[dict[str, Any]]

INSERT = """
INSERT INTO deadlines
  (kind, due_on, window_opens_on, property_id, entity_id, lease_id,
   policy_id, debt_id, exchange_id, citation, note)
VALUES (%(kind)s, %(due_on)s, %(window_opens_on)s, %(property_id)s, %(entity_id)s,
        %(lease_id)s, %(policy_id)s, %(debt_id)s, %(exchange_id)s, %(citation)s, %(note)s)
ON CONFLICT (kind, due_on, property_id, entity_id, lease_id,
             policy_id, debt_id, exchange_id, appeal_id)
DO NOTHING
"""


@dataclass(frozen=True)
class CoverageGap:
    """A deadline the sweep could NOT compute, and exactly why."""

    property_id: str
    state: str
    domain: str
    reason: str  # no_state_jurisdiction | no_rule_for_domain | calendar_key_unregistered
    detail: str


@dataclass(frozen=True)
class SweepResult:
    inserted: dict[str, int]
    gaps: list[CoverageGap]

    @property
    def total(self) -> int:
        return sum(self.inserted.values())


def _row(kind: str, due_on: dt.date, citation: str, **anchors: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": kind,
        "due_on": due_on,
        "window_opens_on": None,
        "property_id": None,
        "entity_id": None,
        "lease_id": None,
        "policy_id": None,
        "debt_id": None,
        "exchange_id": None,
        "citation": citation,
        "note": None,
    }
    base.update(anchors)
    return base


# Resolution: anchor every live property to a jurisdiction (its resolved
# jurisdiction_id, else its state row), walk the chain once in SQL, and take
# the most specific open rule per code, newest effective_from first. The
# citation and instructions the sweep emits come from the RULE ROWS — the
# code carries no state's statutes.
APPEAL_RESOLUTION_SQL = """
WITH anchored AS (
  SELECT p.id AS property_id, p.state,
         COALESCE(p.jurisdiction_id, s.id) AS start_id
  FROM properties p
  LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
  WHERE p.disposed_on IS NULL
),
resolved AS (
  SELECT DISTINCT ON (a.property_id, r.code)
         a.property_id, r.code, r.value_text, r.citation
  FROM anchored a
  CROSS JOIN LATERAL jurisdiction_chain(a.start_id) c
  JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
  WHERE r.domain = 'assessment_appeal'
    AND r.superseded_by IS NULL
    AND r.effective_from <= %(as_of)s
    AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
  ORDER BY a.property_id, r.code, c.depth ASC, r.effective_from DESC
)
SELECT a.property_id, a.state, a.start_id,
       cal.value_text AS calendar_key, cal.citation AS citation,
       ins.value_text AS instructions
FROM anchored a
LEFT JOIN resolved cal
  ON cal.property_id = a.property_id AND cal.code = 'appeal.window.calendar'
LEFT JOIN resolved ins
  ON ins.property_id = a.property_id AND ins.code = 'appeal.instructions'
"""


def _appeal_windows(conn: Conn, as_of: dt.date) -> tuple[list[dict[str, Any]], list[CoverageGap]]:
    """The next assessment-appeal window for every live property whose
    jurisdiction chain names a registered calendar; a typed gap for every
    property whose chain does not."""
    rows: list[dict[str, Any]] = []
    gaps: list[CoverageGap] = []
    for record in conn.execute(APPEAL_RESOLUTION_SQL, {"as_of": as_of}).fetchall():
        if record["start_id"] is None:
            gaps.append(
                CoverageGap(
                    property_id=str(record["property_id"]),
                    state=record["state"],
                    domain="assessment_appeal",
                    reason="no_state_jurisdiction",
                    detail=f"no jurisdiction pack is loaded for {record['state']}",
                )
            )
            continue
        if record["calendar_key"] is None:
            gaps.append(
                CoverageGap(
                    property_id=str(record["property_id"]),
                    state=record["state"],
                    domain="assessment_appeal",
                    reason="no_rule_for_domain",
                    detail="no appeal.window.calendar rule is loaded on the chain",
                )
            )
            continue
        builder = calendar.APPEAL_WINDOWS.get(record["calendar_key"])
        if builder is None:
            gaps.append(
                CoverageGap(
                    property_id=str(record["property_id"]),
                    state=record["state"],
                    domain="assessment_appeal",
                    reason="calendar_key_unregistered",
                    detail=f"rule names calendar {record['calendar_key']!r},"
                    " which this build does not register",
                )
            )
            continue
        window = calendar.next_window(builder, as_of)
        rows.append(
            _row(
                "assessment_appeal_window",
                window.closes_on,
                record["citation"],
                window_opens_on=window.opens_on,
                property_id=record["property_id"],
                note=record["instructions"],
            )
        )
    return rows, gaps


def _lease_expirations(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT l.id AS lease_id, l.ends_on, u.property_id
        FROM leases l JOIN units u ON u.id = l.unit_id
        WHERE l.status IN ('active', 'month_to_month')
          AND l.ends_on IS NOT NULL AND l.ends_on >= %s
        """,
        (as_of,),
    ).fetchall()
    return [
        _row(
            "lease_expiration",
            record["ends_on"],
            "lease agreement (ends_on)",
            property_id=record["property_id"],
            lease_id=record["lease_id"],
        )
        for record in rows
    ]


def _policy_expirations(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, property_id, effective_to FROM policies WHERE effective_to >= %s",
        (as_of,),
    ).fetchall()
    return [
        _row(
            "policy_expiration",
            record["effective_to"],
            "policy term (effective_to)",
            property_id=record["property_id"],
            policy_id=record["id"],
        )
        for record in rows
    ]


def _debt_events(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, property_id, matures_on, rate_adjusts_on
        FROM debt_instruments WHERE paid_off_on IS NULL
        """,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for record in rows:
        if record["matures_on"] is not None and record["matures_on"] >= as_of:
            out.append(
                _row(
                    "loan_maturity",
                    record["matures_on"],
                    "note terms (maturity)",
                    property_id=record["property_id"],
                    debt_id=record["id"],
                )
            )
        if record["rate_adjusts_on"] is not None and record["rate_adjusts_on"] >= as_of:
            out.append(
                _row(
                    "rate_adjustment",
                    record["rate_adjusts_on"],
                    "note terms (rate adjustment)",
                    property_id=record["property_id"],
                    debt_id=record["id"],
                )
            )
    return out


def _exchange_clocks(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, relinquished_property_id, identify_by, acquire_by
        FROM exchanges WHERE NOT failed
        """,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for record in rows:
        if record["identify_by"] >= as_of:
            out.append(
                _row(
                    "exchange_identification",
                    record["identify_by"],
                    "IRC s.1031(a)(3)(A)",
                    property_id=record["relinquished_property_id"],
                    exchange_id=record["id"],
                )
            )
        if record["acquire_by"] >= as_of:
            out.append(
                _row(
                    "exchange_acquisition",
                    record["acquire_by"],
                    "IRC s.1031(a)(3)(B)",
                    property_id=record["relinquished_property_id"],
                    exchange_id=record["id"],
                )
            )
    return out


def _entity_tax_dates(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id FROM entities WHERE dissolved_on IS NULL").fetchall()
    out: list[dict[str, Any]] = []
    for record in rows:
        for due in calendar.federal_estimated_tax_due_dates(as_of.year):
            if due >= as_of:
                out.append(_row("estimated_tax", due, "IRC s.6654(c)", entity_id=record["id"]))
        # Always ahead: the 1099-NEC for tax year Y is due Jan 31 (rolled
        # forward off weekends) of Y+1, which strictly follows every day of
        # year Y — so no guard against the past is reachable here.
        nec = calendar.form_1099_nec_due_date(as_of.year)
        out.append(_row("form_1099_nec", nec, "IRC s.6071(c)", entity_id=record["id"]))
    return out


# The dispatch seam is the rule data plus the calendar registry, not this
# tuple: the tuple only lists the KINDS of fact the sweep reads.
GENERATORS = (
    _lease_expirations,
    _policy_expirations,
    _debt_events,
    _exchange_clocks,
    _entity_tax_dates,
)


def run_sweep(conn: Conn, as_of: dt.date) -> SweepResult:
    inserted: dict[str, int] = {}
    appeal_rows, gaps = _appeal_windows(conn, as_of)
    rows = appeal_rows + [row for generator in GENERATORS for row in generator(conn, as_of)]
    for row in rows:
        result = conn.execute(INSERT, row)
        if result.rowcount == 1:
            inserted[row["kind"]] = inserted.get(row["kind"], 0) + 1
    return SweepResult(inserted=inserted, gaps=gaps)
