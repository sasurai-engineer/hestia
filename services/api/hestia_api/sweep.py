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
from hestia_api.screening import ADVERSE_ACTION_CITATION

Conn = psycopg.Connection[dict[str, Any]]

INSERT = """
INSERT INTO deadlines
  (kind, due_on, window_opens_on, property_id, entity_id, lease_id,
   policy_id, debt_id, exchange_id, vendor_id, screening_request_id,
   citation, note)
VALUES (%(kind)s, %(due_on)s, %(window_opens_on)s, %(property_id)s, %(entity_id)s,
        %(lease_id)s, %(policy_id)s, %(debt_id)s, %(exchange_id)s, %(vendor_id)s,
        %(screening_request_id)s, %(citation)s, %(note)s)
ON CONFLICT (kind, due_on, property_id, entity_id, lease_id,
             policy_id, debt_id, exchange_id, appeal_id, vendor_id,
             screening_request_id)
DO NOTHING
"""


@dataclass(frozen=True)
class CoverageGap:
    """A deadline the sweep could NOT compute, and exactly why."""

    property_id: str
    state: str
    domain: str
    reason: str  # no_state_jurisdiction | no_rule_for_domain |
    #              calendar_key_unregistered | window_not_published |
    #              window_awaiting_publication
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
        "vendor_id": None,
        "screening_request_id": None,
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
,
-- Not every state's window is a function of the year. Tennessee's county
-- boards convene on a statutory date but ADJOURN on one each county sets
-- administratively and moves annually, and no statewide list of those dates
-- exists -- so for such a state the window is a published DATE the pack
-- carries, not a builder the code registers. The opens/closes pair is
-- matched on effective_from, which is what makes the two rows one window.
published AS (
  SELECT DISTINCT ON (a.property_id)
         a.property_id,
         opens.value_text::date AS opens_on,
         closes.value_text::date AS closes_on,
         closes.citation
  FROM anchored a
  CROSS JOIN LATERAL jurisdiction_chain(a.start_id) c
  JOIN jurisdiction_rules closes
    ON closes.jurisdiction_id = c.jurisdiction_id
   AND closes.domain = 'assessment_appeal'
   AND closes.code = 'appeal.window.closes_on'
   AND closes.superseded_by IS NULL
  LEFT JOIN jurisdiction_rules opens
    ON opens.jurisdiction_id = closes.jurisdiction_id
   AND opens.code = 'appeal.window.opens_on'
   AND opens.superseded_by IS NULL
   AND opens.effective_from = closes.effective_from
  -- A window that has already closed is not the next one. With no later date
  -- loaded the property gets a gap, which is the honest answer: nobody has
  -- published next year's date yet.
  WHERE closes.value_text::date >= %(as_of)s
  ORDER BY a.property_id, c.depth ASC, closes.value_text::date ASC
)
,
-- The most recent window that has already closed — history, not law, which is
-- why the effective window filter is absent on purpose: an expired row is
-- exactly what this looks for. A published-shape state goes dark every year
-- by design the day its window closes, and stays dark until the county
-- publishes the next date; the difference between that and a state nobody
-- ever entered is the difference between "act when the county speaks" and
-- "this state has no data", and only this row can tell them apart.
expired AS (
  SELECT DISTINCT ON (a.property_id)
         a.property_id,
         closes.value_text::date AS closes_on,
         closes.citation
  FROM anchored a
  CROSS JOIN LATERAL jurisdiction_chain(a.start_id) c
  JOIN jurisdiction_rules closes
    ON closes.jurisdiction_id = c.jurisdiction_id
   AND closes.domain = 'assessment_appeal'
   AND closes.code = 'appeal.window.closes_on'
   AND closes.superseded_by IS NULL
  WHERE closes.value_text::date < %(as_of)s
  ORDER BY a.property_id, closes.value_text::date DESC, c.depth ASC
)
SELECT a.property_id, a.state, a.start_id,
       cal.value_text AS calendar_key, cal.citation AS citation,
       ins.value_text AS instructions,
       src.value_text AS window_source, src.citation AS source_citation,
       pub.opens_on AS published_opens_on, pub.closes_on AS published_closes_on,
       pub.citation AS published_citation,
       exp.closes_on AS last_closes_on, exp.citation AS last_citation
FROM anchored a
LEFT JOIN resolved cal
  ON cal.property_id = a.property_id AND cal.code = 'appeal.window.calendar'
LEFT JOIN resolved ins
  ON ins.property_id = a.property_id AND ins.code = 'appeal.instructions'
LEFT JOIN resolved src
  ON src.property_id = a.property_id AND src.code = 'appeal.window.source'
LEFT JOIN published pub ON pub.property_id = a.property_id
LEFT JOIN expired exp ON exp.property_id = a.property_id
"""


def _appeal_windows(conn: Conn, as_of: dt.date) -> tuple[list[dict[str, Any]], list[CoverageGap]]:
    """The next assessment-appeal window for every live property, from the
    date its pack published or the calendar its pack names; a typed gap for
    every property whose chain gives neither.

    A published date wins over a computed one. Some states' windows are a
    function of the year and some are an administrative decision a county
    makes annually, and only the first kind can be a builder."""
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
        if record["published_closes_on"] is not None:
            # A date somebody published beats a date this build could compute,
            # because in a state like Tennessee there is nothing correct to
            # compute: the deadline is whatever the county board set this year.
            rows.append(
                _row(
                    "assessment_appeal_window",
                    record["published_closes_on"],
                    record["published_citation"],
                    window_opens_on=record["published_opens_on"],
                    property_id=record["property_id"],
                    note=record["instructions"],
                )
            )
            continue
        if record["window_source"] is not None:
            # The pack says this state's window is published rather than
            # computed, and no upcoming date is loaded. Two different silences
            # hide behind that, and they demand different acts. A state whose
            # LAST window is on record went dark on schedule — every
            # published-shape state does, yearly, the day its window closes —
            # and the act is to enter the county's next date when it speaks.
            # A state with no dated row at all was never entered, and the act
            # is to go find this year's date now. One reason for each, so
            # neither can hide inside the other.
            if record["last_closes_on"] is not None:
                gaps.append(
                    CoverageGap(
                        property_id=str(record["property_id"]),
                        state=record["state"],
                        domain="assessment_appeal",
                        reason="window_awaiting_publication",
                        detail=(
                            f"the last known appeal window closed "
                            f"{record['last_closes_on'].isoformat()} "
                            f"({record['last_citation']}); the next date is set by "
                            "the county and must be entered when it publishes — "
                            "until then the window is honestly unknown"
                        ),
                    )
                )
                continue
            gaps.append(
                CoverageGap(
                    property_id=str(record["property_id"]),
                    state=record["state"],
                    domain="assessment_appeal",
                    reason="window_not_published",
                    detail=(
                        f"{record['source_citation']}: no appeal window has ever "
                        "been loaded for this jurisdiction, and the date is not one "
                        "this build may compute — find this year's published date "
                        "and enter it"
                    ),
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
def _vendor_credentials(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    """A vendor's certificate expiry is a deadline like any other: the day it
    lapses is the day the owner silently reassumes the risk the vendor was
    hired to carry. Anchored on the VENDOR, so two vendors expiring on one day
    are two deadlines (module 016 added the anchor for exactly this)."""
    rows = conn.execute(
        """
        SELECT id, entity_id, liability_expires_on, workers_comp_expires_on,
               license_expires_on, name
        FROM vendors
        WHERE retired_on IS NULL
          AND (liability_expires_on >= %(as_of)s
               OR workers_comp_expires_on >= %(as_of)s
               OR license_expires_on >= %(as_of)s)
        """,
        {"as_of": as_of},
    ).fetchall()
    out: list[dict[str, Any]] = []
    for record in rows:
        for column, kind, citation in (
            (
                "liability_expires_on",
                "vendor_insurance_expiration",
                "certificate of insurance — general liability term",
            ),
            (
                "workers_comp_expires_on",
                "vendor_workers_comp_expiration",
                "certificate of insurance — workers compensation term",
            ),
            (
                "license_expires_on",
                "vendor_license_expiration",
                "trade licence term on file",
            ),
        ):
            due = record[column]
            if due is None or due < as_of:
                continue
            out.append(
                _row(
                    kind,
                    due,
                    citation,
                    entity_id=record["entity_id"],
                    vendor_id=record["id"],
                    note=record["name"],
                )
            )
    return out


def _adverse_action_notices(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    """A denial a consumer report drove owes the applicant a notice.

    FCRA s.615(a) sets no day count, so none is invented: the duty is dated to
    the decision, which is when it attaches. Anchored on the request, so two
    applicants refused on one day at one property are two notices (module 018
    added the anchor for exactly that).
    """
    rows = conn.execute(
        """
        SELECT s.id, s.property_id, s.decided_on, s.decision::text AS decision,
               r.full_name
        FROM screening_requests s JOIN residents r ON r.id = s.resident_id
        WHERE s.adverse_action_required
          AND s.adverse_action_sent_on IS NULL
          AND s.decided_on IS NOT NULL
        """,
    ).fetchall()
    return [
        _row(
            "adverse_action_notice",
            record["decided_on"],
            ADVERSE_ACTION_CITATION,
            property_id=record["property_id"],
            screening_request_id=record["id"],
            note=f"{record['full_name']} — {record['decision']}",
        )
        for record in rows
    ]


def _deposit_itemizations(conn: Conn, as_of: dt.date) -> list[dict[str, Any]]:
    """A tenancy that ended owes the deposit back inside the period the
    jurisdiction sets. Where the chain sets none, the sweep says so as a gap
    rather than inventing a period — a made-up deadline looks like law.
    """
    rows = conn.execute(
        """
        WITH lease_anchor AS (
          SELECT l.id AS lease_id, u.property_id, p.state,
                 l.moved_out_on,
                 COALESCE(p.jurisdiction_id, s.id) AS start_id
          FROM leases l
          JOIN units u ON u.id = l.unit_id
          JOIN properties p ON p.id = u.property_id
          LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
          WHERE l.moved_out_on IS NOT NULL AND l.deposit_returned_on IS NULL
        ),
        resolved AS (
          SELECT DISTINCT ON (a.lease_id)
                 a.lease_id, r.value_numeric AS return_days, r.citation
          FROM lease_anchor a
          CROSS JOIN LATERAL jurisdiction_chain(a.start_id) c
          JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
          WHERE r.domain = 'security_deposit'
            AND r.code = 'deposit.return_days'
            AND r.superseded_by IS NULL
            AND r.effective_from <= %(as_of)s
            AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
          ORDER BY a.lease_id, c.depth ASC, r.effective_from DESC
        )
        SELECT a.lease_id, a.property_id, a.state, a.moved_out_on,
               resolved.return_days, resolved.citation
        FROM lease_anchor a LEFT JOIN resolved ON resolved.lease_id = a.lease_id
        """,
        {"as_of": as_of},
    ).fetchall()
    out: list[dict[str, Any]] = []
    for record in rows:
        if record["return_days"] is None:
            continue  # reported as a coverage gap by run_sweep, never defaulted
        out.append(
            _row(
                "deposit_itemization",
                record["moved_out_on"] + dt.timedelta(days=int(record["return_days"])),
                record["citation"],
                property_id=record["property_id"],
                lease_id=record["lease_id"],
                window_opens_on=record["moved_out_on"],
                note=f"deposit itemisation and return, {record['return_days']} days from move-out",
            )
        )
    return out


def _deposit_gaps(conn: Conn, as_of: dt.date) -> list[CoverageGap]:
    """Ended tenancies whose chain sets no return period."""
    rows = conn.execute(
        """
        WITH lease_anchor AS (
          SELECT l.id AS lease_id, u.property_id, p.state,
                 COALESCE(p.jurisdiction_id, s.id) AS start_id
          FROM leases l
          JOIN units u ON u.id = l.unit_id
          JOIN properties p ON p.id = u.property_id
          LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
          WHERE l.moved_out_on IS NOT NULL AND l.deposit_returned_on IS NULL
        )
        SELECT a.lease_id::text, a.property_id::text, a.state
        FROM lease_anchor a
        WHERE NOT EXISTS (
          SELECT 1 FROM jurisdiction_chain(a.start_id) c
          JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
          WHERE r.domain = 'security_deposit' AND r.code = 'deposit.return_days'
            AND r.superseded_by IS NULL
            AND r.effective_from <= %(as_of)s
            AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
        )
        -- A pack may state that its state fixes no return deadline at all.
        -- That is an answer, not missing coverage: Tennessee's chapter gives
        -- a forfeiture rule in place of a due date, and calling it a gap
        -- would send an owner looking for a statute that does not exist.
        AND NOT EXISTS (
          SELECT 1 FROM (
            SELECT r.value_text
            FROM jurisdiction_chain(a.start_id) c
            JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
            WHERE r.domain = 'security_deposit'
              AND r.code = 'deposit.return_deadline_exists'
              AND r.superseded_by IS NULL
              AND r.effective_from <= %(as_of)s
              AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
            ORDER BY c.depth ASC, r.effective_from DESC
            LIMIT 1
          ) nearest
          -- btrim on both sides of split_part, because deposit.py's
          -- _rule_truth strips the same whitespace. A pack author who
          -- writes 'false ; ...' must not get a panel and a sweep that
          -- disagree about the same lease.
          WHERE lower(btrim(split_part(btrim(nearest.value_text), ';', 1))) = 'false'
        )
        """,
        {"as_of": as_of},
    ).fetchall()
    return [
        CoverageGap(
            property_id=record["property_id"],
            state=record["state"],
            domain="security_deposit",
            reason="no_rule_for_domain",
            detail=(
                f"lease {record['lease_id']} has ended with the deposit unsettled and "
                f"no deposit.return_days rule resolves for {record['state']}"
            ),
        )
        for record in rows
    ]


GENERATORS = (
    _lease_expirations,
    _policy_expirations,
    _debt_events,
    _exchange_clocks,
    _entity_tax_dates,
    _vendor_credentials,
    _adverse_action_notices,
    _deposit_itemizations,
)


def run_sweep(conn: Conn, as_of: dt.date) -> SweepResult:
    inserted: dict[str, int] = {}
    appeal_rows, gaps = _appeal_windows(conn, as_of)
    rows = appeal_rows + [row for generator in GENERATORS for row in generator(conn, as_of)]
    gaps = gaps + _deposit_gaps(conn, as_of)
    for row in rows:
        result = conn.execute(INSERT, row)
        if result.rowcount == 1:
            inserted[row["kind"]] = inserted.get(row["kind"], 0) + 1
    return SweepResult(inserted=inserted, gaps=gaps)
