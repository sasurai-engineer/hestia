"""The deadline sweep against a seeded portfolio.

The world: one KY property with an active lease, a live policy, an ARM with a
maturity, and a §1031 exchange whose 45-day clock has ALREADY run — proving
the sweep alerts on what is ahead, never on what is lost.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

AS_OF = dt.date(2026, 8, 25)


@pytest.fixture
def world(clean: None, conn: psycopg.Connection[Any]) -> dict[str, str]:
    ids = {
        name: str(uuid.uuid4())
        for name in ("entity", "property", "unit", "lease", "policy", "debt", "exchange")
    }
    conn.execute(
        "INSERT INTO entities (id, name, kind) VALUES (%s, 'Sweep Holdings LLC', 'llc')",
        (ids["entity"],),
    )
    conn.execute(
        """
        INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                postal_code, kind)
        VALUES (%s, %s, '412 Maple', '412 Maple St', 'Testville', 'KY',
                '41071', 'single_family')
        """,
        (ids["property"], ids["entity"]),
    )
    conn.execute(
        "INSERT INTO units (id, property_id, label) VALUES (%s, %s, 'A')",
        (ids["unit"], ids["property"]),
    )
    conn.execute(
        """
        INSERT INTO leases (id, unit_id, status, starts_on, ends_on, rent)
        VALUES (%s, %s, 'active', '2026-04-01', '2027-03-31', 145000)
        """,
        (ids["lease"], ids["unit"]),
    )
    conn.execute(
        """
        INSERT INTO policies (id, property_id, kind, effective_from, effective_to)
        VALUES (%s, %s, 'landlord_package', '2026-01-01', '2026-12-31')
        """,
        (ids["policy"], ids["property"]),
    )
    conn.execute(
        """
        INSERT INTO debt_instruments
          (id, property_id, kind, original_principal, interest_rate, amortization,
           term_months, originated_on, matures_on, rate_adjusts_on, rate_index)
        VALUES (%s, %s, 'conventional_mortgage', 24000000, 0.065, 'arm',
                360, '2020-06-01', '2030-01-01', '2027-06-01', 'SOFR-30A')
        """,
        (ids["debt"], ids["property"]),
    )
    # A second lien with no dated events at all — the sweep must pass over it.
    conn.execute(
        """
        INSERT INTO debt_instruments
          (id, property_id, kind, original_principal, interest_rate,
           term_months, originated_on)
        VALUES (%s, %s, 'heloc', 5000000, 0.08, 120, '2024-03-01')
        """,
        (str(uuid.uuid4()), ids["property"]),
    )
    # Three exchanges, one per posture of the clocks:
    #   half-run  — closed 2026-07-01: identification (08-15) has run out by
    #               as_of; only acquisition (12-28) remains.
    #   both live — closed 2026-08-20: identify by 10-04, acquire by 2027-02-16.
    #   both run  — closed 2025-12-01: everything is history; zero rows.
    conn.execute(
        """
        INSERT INTO exchanges (id, relinquished_property_id, closed_relinquished_on,
                               identify_by, acquire_by)
        VALUES (%s, %s, '2026-07-01', '2026-08-15', '2026-12-28'),
               (%s, %s, '2026-08-20', '2026-10-04', '2027-02-16'),
               (%s, %s, '2025-12-01', '2026-01-15', '2026-05-30')
        """,
        (
            ids["exchange"],
            ids["property"],
            str(uuid.uuid4()),
            ids["property"],
            str(uuid.uuid4()),
            ids["property"],
        ),
    )
    conn.commit()
    return ids


def _deadlines(conn: psycopg.Connection[Any]) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT kind, due_on, window_opens_on, citation, note FROM deadlines"
    ).fetchall()
    return {row["kind"]: row for row in rows}


def test_the_sweep_builds_the_owner_calendar(
    world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    response = client.post(f"/sweep/deadlines?as_of={AS_OF}")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-08-25"
    assert body["inserted"] == {
        "assessment_appeal_window": 1,
        "lease_expiration": 1,
        "policy_expiration": 1,
        "loan_maturity": 1,  # the HELOC has no dated events; one row only
        "rate_adjustment": 1,
        "exchange_identification": 1,  # only the both-live exchange still identifies
        "exchange_acquisition": 2,  # half-run + both-live; the spent one is silent
        "estimated_tax": 2,  # Sep 15 2026 and Jan 15 2027 remain
        "form_1099_nec": 1,
    }
    assert body["total"] == 11
    # The KY pack covers this property completely: no gaps.
    assert body["coverage_gaps"] == []

    by_kind = _deadlines(conn)
    # The first real-world deadline the platform must hit: KRS 133.045, 2027.
    appeal = by_kind["assessment_appeal_window"]
    assert appeal["due_on"] == dt.date(2027, 5, 17)
    assert appeal["window_opens_on"] == dt.date(2027, 5, 3)
    assert appeal["citation"] == "KRS 133.045"
    assert "62A307" in appeal["note"]
    assert by_kind["lease_expiration"]["due_on"] == dt.date(2027, 3, 31)
    assert by_kind["policy_expiration"]["due_on"] == dt.date(2026, 12, 31)
    assert by_kind["loan_maturity"]["due_on"] == dt.date(2030, 1, 1)
    assert by_kind["rate_adjustment"]["due_on"] == dt.date(2027, 6, 1)
    assert by_kind["exchange_identification"]["due_on"] == dt.date(2026, 10, 4)
    assert by_kind["exchange_identification"]["citation"] == "IRC s.1031(a)(3)(A)"
    acquisitions = conn.execute(
        "SELECT due_on FROM deadlines WHERE kind = 'exchange_acquisition' ORDER BY due_on"
    ).fetchall()
    assert [r["due_on"] for r in acquisitions] == [dt.date(2026, 12, 28), dt.date(2027, 2, 16)]
    assert by_kind["form_1099_nec"]["due_on"] == dt.date(2027, 2, 1)


def test_rerunning_the_sweep_inserts_nothing(world: dict[str, str], client: TestClient) -> None:
    first = client.post(f"/sweep/deadlines?as_of={AS_OF}").json()
    assert first["total"] == 11
    second = client.post(f"/sweep/deadlines?as_of={AS_OF}").json()
    assert second["total"] == 0
    assert second["inserted"] == {}


def test_the_sweep_audits_itself(
    world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    request_id = f"sweep-proof-{uuid.uuid4()}"
    client.post(f"/sweep/deadlines?as_of={AS_OF}", headers={"x-request-id": request_id})
    row = conn.execute(
        "SELECT action, after_value FROM audit_log WHERE request_id = %s",
        (request_id,),
    ).fetchone()
    assert row is not None
    assert row["action"] == "sweep.deadlines"
    assert row["after_value"]["as_of"] == "2026-08-25"
    assert row["after_value"]["gap_count"] == 0


def test_uncovered_jurisdictions_gap_instead_of_guessing(
    clean: None, client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    """Three properties, three postures: no pack at all (TN), a pack whose
    rule names a calendar this build does not register (QQ), and a pack with
    no appeal rule loaded (ZZ). None may produce a deadline; all must
    produce a typed gap. Synthetic two-letter codes pass the us_state domain
    without colliding with any real pack."""
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities (id, name, kind) VALUES (%s, 'Gap Holdings LLC', 'llc')",
        (entity_id,),
    )
    qq_state = str(uuid.uuid4())
    zz_state = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO jurisdictions (id, level, name, state, parent_id)
        SELECT v.id::uuid, 'state', v.name, v.code, f.id
        FROM (VALUES (%s, 'Queuestate', 'QQ'), (%s, 'Zedland', 'ZZ'))
             AS v (id, name, code)
        CROSS JOIN (SELECT id FROM jurisdictions WHERE level = 'federal') f
        ON CONFLICT (level, name, state, parent_id) DO NOTHING
        """,
        (qq_state, zz_state),
    )
    qq_rule = conn.execute(
        """
        SELECT r.id FROM jurisdiction_rules r
        JOIN jurisdictions j ON j.id = r.jurisdiction_id
        WHERE j.state = 'QQ' AND r.code = 'appeal.window.calendar'
        """
    ).fetchone()
    if qq_rule is None:  # rules are append-only; insert once per session
        conn.execute(
            """
            INSERT INTO jurisdiction_rules
              (jurisdiction_id, domain, code, value_text, citation, effective_from)
            SELECT id, 'assessment_appeal', 'appeal.window.calendar',
                   'qq.future-calendar', 'QQ Rev. Stat. 1.1 (test)', DATE '2000-01-01'
            FROM jurisdictions WHERE state = 'QQ' AND level = 'state'
            """
        )
    properties = {}
    for state in ("IN", "QQ", "ZZ"):
        pid = str(uuid.uuid4())
        properties[state] = pid
        conn.execute(
            """
            INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                    postal_code, kind)
            VALUES (%s, %s, %s, '1 Test St', 'Testburg', %s, '00000', 'single_family')
            """,
            (pid, entity_id, f"gap-{state}", state),
        )
    conn.commit()

    body = client.post(f"/sweep/deadlines?as_of={AS_OF}").json()
    assert "assessment_appeal_window" not in body["inserted"]
    gaps = {g["state"]: g for g in body["coverage_gaps"]}
    assert gaps["IN"]["reason"] == "no_state_jurisdiction"
    assert gaps["IN"]["property_id"] == properties["IN"]
    assert gaps["QQ"]["reason"] == "calendar_key_unregistered"
    assert "qq.future-calendar" in gaps["QQ"]["detail"]
    assert gaps["ZZ"]["reason"] == "no_rule_for_domain"
    assert all(g["domain"] == "assessment_appeal" for g in body["coverage_gaps"])
    assert len(body["coverage_gaps"]) == 3
    rows = conn.execute(
        "SELECT count(*) AS n FROM deadlines WHERE kind = 'assessment_appeal_window'"
    ).fetchone()
    assert rows is not None and rows["n"] == 0


def test_the_cross_river_portfolio_gets_both_regimes(
    clean: None, client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    """The nationwide acceptance shape: one owner, four properties — Newport
    KY, Cincinnati OH (one bridge apart), Nashville TN, and an Indianapolis
    outpost in a state with no pack. ONE sweep yields each covered state's own
    window, citation and instructions, no Indiana row, and exactly one honest
    Indiana gap."""
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities (id, name, kind) VALUES (%s, 'Cross River LLC', 'llc')",
        (entity_id,),
    )
    for label, city, state, zip_ in (
        ("newport-side", "Newport", "KY", "41071"),
        ("cincinnati-side", "Cincinnati", "OH", "45202"),
        ("nashville-outpost", "Nashville", "TN", "37201"),
        ("indianapolis-outpost", "Indianapolis", "IN", "46204"),
    ):
        conn.execute(
            """
            INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                    postal_code, kind, jurisdiction_id)
            VALUES (%s, %s, %s, '1 Riverfront Way', %s, %s, %s, 'single_family',
                    (SELECT id FROM jurisdictions
                     WHERE name = %s AND state = %s AND level = 'municipality'))
            """,
            (str(uuid.uuid4()), entity_id, label, city, state, zip_, city, state),
        )
    conn.commit()

    # 2026-06-01: Kentucky's and Ohio's 2026 windows have closed, so both roll
    # to 2027; Davidson County's published 2026 date is still ahead.
    body = client.post("/sweep/deadlines?as_of=2026-06-01").json()
    assert body["inserted"]["assessment_appeal_window"] == 3
    appeal_gaps = [g for g in body["coverage_gaps"] if g["domain"] == "assessment_appeal"]
    (gap,) = appeal_gaps
    assert (gap["state"], gap["reason"]) == ("IN", "no_state_jurisdiction")
    # The collection calendar rides the same sweep now: at this as_of the
    # Newport property's county discount sits between published schedules,
    # which is a named gap, not silence — and not a guess.
    assert any(
        g["domain"] == "tax_collection" and g["reason"] == "window_awaiting_publication"
        for g in body["coverage_gaps"]
    )

    rows = conn.execute(
        """
        SELECT p.state, d.due_on, d.window_opens_on, d.citation, d.note
        FROM deadlines d JOIN properties p ON p.id = d.property_id
        WHERE d.kind = 'assessment_appeal_window' ORDER BY p.state
        """
    ).fetchall()
    ky, oh, tn = rows[0], rows[1], rows[2]
    assert ky["state"] == "KY"
    assert ky["due_on"] == dt.date(2027, 5, 17)
    assert ky["window_opens_on"] == dt.date(2027, 5, 3)
    assert ky["citation"] == "KRS 133.045"
    assert "62A307" in ky["note"]
    assert oh["state"] == "OH"
    assert oh["due_on"] == dt.date(2027, 3, 31)
    assert oh["window_opens_on"] == dt.date(2027, 1, 1)
    assert "ORC 5715.19" in oh["citation"]
    assert "DTE Form 1" in oh["note"]
    # Tennessee's date is not computed at all: it is the one Davidson County
    # published for 2026, and the citation names the county rather than a
    # statute, because no statute fixes it.
    assert tn["state"] == "TN"
    assert tn["due_on"] == dt.date(2026, 6, 26)
    assert tn["window_opens_on"] == dt.date(2026, 5, 26)
    assert "Metropolitan Board of Equalization" in tn["citation"]
    assert "Assessor of Property" in tn["citation"]
    # The note must not let the State Board's August 1 read as the deadline.
    assert "SECOND-level" in tn["note"]
    assert tn["due_on"] < dt.date(2026, 8, 1)
    # Three states, three windows, no two alike — from one sweep.
    assert len({ky["due_on"], oh["due_on"], tn["due_on"]}) == 3


def test_a_published_window_that_has_passed_is_a_named_gap_not_a_guess(
    clean: None, client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    """Tennessee's deadline is whatever its county board set this year, so
    once the published date is behind us there is nothing honest to compute.
    The sweep must say that in as many words rather than roll a year forward
    the way a builder-backed state does — Davidson's date was June 14 in
    2024, June 27 in 2025 and June 26 in 2026, and no rule generates it."""
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities (id, name, kind) VALUES (%s, 'Nashville LLC', 'llc')",
        (entity_id,),
    )
    property_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                postal_code, kind, jurisdiction_id)
        VALUES (%s, %s, 'weona', '2226 Weona Dr', 'Nashville', 'TN', '37206',
                'single_family',
                (SELECT id FROM jurisdictions
                  WHERE name = 'Nashville' AND level = 'municipality'))
        """,
        (property_id, entity_id),
    )
    conn.commit()

    # Before the published close: the real date, from the county.
    early = client.post("/sweep/deadlines?as_of=2026-06-01").json()
    assert early["inserted"]["assessment_appeal_window"] == 1
    assert not [g for g in early["coverage_gaps"] if g["domain"] == "assessment_appeal"]

    # After it: a gap that names why, and NO invented deadline. This is the
    # state every published-shape jurisdiction enters yearly, ON SCHEDULE, the
    # day its window closes — so the gap must read as "the county has not
    # spoken yet", never as "nobody ever entered this state" (issue #127: the
    # two silences demand different acts, and the darkness was silent).
    late = client.post("/sweep/deadlines?as_of=2026-07-01").json()
    assert "assessment_appeal_window" not in late["inserted"]
    gap = next(g for g in late["coverage_gaps"] if g["domain"] == "assessment_appeal")
    assert gap["reason"] == "window_awaiting_publication"
    assert gap["property_id"] == property_id
    # The detail names the last known window and its authority, so a reader
    # knows the data was alive and what to watch for.
    assert "2026-06-26" in gap["detail"]
    assert "Metropolitan Board of Equalization" in gap["detail"]
    assert "entered when it publishes" in gap["detail"]
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM deadlines WHERE kind = 'assessment_appeal_window'"
            " AND property_id = %s AND due_on > DATE '2026-06-26'",
            (property_id,),
        ).fetchone()["n"]
        == 0
    )


def test_a_published_state_with_no_date_ever_loaded_says_so_differently(
    clean: None, client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    """The other silence. A pack may declare its windows are published by the
    county before anyone has entered a single date — a brand-new state, mid
    onboarding. That is not "awaiting publication", it is "go find this
    year's date", and the two must not share a reason. Sandboxed synthetic
    state, since jurisdiction_rules is append-only."""
    if (
        conn.execute(
            "SELECT 1 AS x FROM jurisdictions WHERE state = 'QP' AND level = 'state'"
        ).fetchone()
        is None
    ):
        conn.execute(
            """
            WITH state_row AS (
              INSERT INTO jurisdictions (level, name, state, parent_id)
              SELECT 'state', 'Quopland', 'QP', id FROM jurisdictions
              WHERE level = 'federal' RETURNING id
            )
            INSERT INTO jurisdictions (level, name, state, parent_id)
            SELECT 'municipality', 'Quopville', 'QP', id FROM state_row
            """
        )
        conn.execute(
            """
            INSERT INTO jurisdiction_rules
              (jurisdiction_id, domain, code, value_text, citation, effective_from)
            SELECT id, 'assessment_appeal', 'appeal.window.source',
                   'published_by_county; the county sets the date annually',
                   'QP Rev. Stat. 9.9 (test fixture)', DATE '2000-01-01'
            FROM jurisdictions WHERE state = 'QP' AND level = 'state'
            """
        )
        conn.commit()
    entity_id = str(uuid.uuid4())
    conn.execute("INSERT INTO entities (id, name, kind) VALUES (%s, 'QP LLC', 'llc')", (entity_id,))
    property_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                postal_code, kind, jurisdiction_id)
        VALUES (%s, %s, 'qp', '1 Main St', 'Quopville', 'QP', '00000',
                'single_family',
                (SELECT id FROM jurisdictions
                  WHERE name = 'Quopville' AND level = 'municipality'))
        """,
        (property_id, entity_id),
    )
    conn.commit()

    body = client.post("/sweep/deadlines?as_of=2026-07-01").json()
    gap = next(
        g
        for g in body["coverage_gaps"]
        if g["domain"] == "assessment_appeal" and g["property_id"] == property_id
    )
    assert gap["reason"] == "window_not_published"
    assert "no appeal window has ever been loaded" in gap["detail"]
    assert "QP Rev. Stat. 9.9" in gap["detail"]


def _newport_property(conn: psycopg.Connection[Any]) -> str:
    """A property anchored at the Newport municipality, whose chain carries
    the whole collection stack: city calendar keys (seed 912), the county's
    published discount schedule (seed 910), and the license conflict row
    (seed 911)."""
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities (id, name, kind) VALUES (%s, 'Collection LLC', 'llc')",
        (entity_id,),
    )
    property_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                postal_code, kind, jurisdiction_id)
        VALUES (%s, %s, 'monmouth', '998 Monmouth St', 'Newport', 'KY', '41071',
                'single_family',
                'a0000000-0000-4000-8000-000000000101')
        """,
        (property_id, entity_id),
    )
    conn.commit()
    return property_id


def test_the_collection_calendar_reaches_the_deadlines_table(
    world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    # Mid-2026: the city tax and the license both compute to October 31 —
    # emitted AS-IS on a Saturday, because the KY roll question is open and
    # staging errs early (seed 910). Campbell's published 2025 discount
    # window has expired and 2026's does not exist, so the county's free
    # money is an awaiting-publication gap citing the sheriff, never a
    # computed guess.
    property_id = _newport_property(conn)
    body = client.post("/sweep/deadlines?as_of=2026-06-01").json()
    assert body["inserted"].get("tax_payment_due", 0) >= 1
    assert body["inserted"].get("license_renewal", 0) >= 1
    rows = conn.execute(
        """
        SELECT kind::text, due_on, citation, note FROM deadlines
        WHERE property_id = %s AND kind IN ('tax_payment_due', 'license_renewal')
        ORDER BY kind
        """,
        (property_id,),
    ).fetchall()
    by_kind = {r["kind"]: r for r in rows}
    tax = by_kind["tax_payment_due"]
    assert tax["due_on"] == dt.date(2026, 10, 31)
    assert "91A.070" in tax["citation"]
    assert "October 31" in (tax["note"] or "")
    lic = by_kind["license_renewal"]
    assert lic["due_on"] == dt.date(2026, 10, 31)
    assert "99.09" in lic["citation"]
    # The conflict row rides as the note: both dates and the rule to choose.
    assert "October 15" in (lic["note"] or "") and "SOURCES DISAGREE" in (lic["note"] or "")
    gap = next(
        g
        for g in body["coverage_gaps"]
        if g["domain"] == "tax_collection" and g["property_id"] == property_id
    )
    assert gap["reason"] == "window_awaiting_publication"
    assert "2025-11-30" in gap["detail"]
    assert "campbellcountysheriffky.org" in gap["detail"]

    # Idempotent: the same sweep again inserts nothing new for this property.
    again = client.post("/sweep/deadlines?as_of=2026-06-01").json()
    assert again["inserted"].get("tax_payment_due", 0) == 0
    assert again["inserted"].get("license_renewal", 0) == 0


def test_a_published_discount_window_is_emitted_while_it_is_live(
    world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    # Autumn 2025: the published window is ahead, so it lands on the
    # calendar with its open attached — and no awaiting gap rides beside it.
    property_id = _newport_property(conn)
    body = client.post("/sweep/deadlines?as_of=2025-10-15").json()
    row = conn.execute(
        """
        SELECT due_on, window_opens_on, citation FROM deadlines
        WHERE property_id = %s AND kind = 'tax_discount_close'
        """,
        (property_id,),
    ).fetchone()
    assert row is not None
    assert row["due_on"] == dt.date(2025, 11, 30)
    assert row["window_opens_on"] == dt.date(2025, 11, 1)
    assert "Campbell County Sheriff" in row["citation"]
    assert "CONFIRM ANNUALLY" in row["citation"]
    assert not [
        g
        for g in body["coverage_gaps"]
        if g["domain"] == "tax_collection" and g["property_id"] == property_id
    ]
    # Mid-October: this year's October 31 is still ahead and is the one
    # emitted — the date itself counts until it has fully passed.
    tax = conn.execute(
        "SELECT due_on FROM deadlines WHERE property_id = %s AND kind = 'tax_payment_due'",
        (property_id,),
    ).fetchone()
    assert tax is not None and tax["due_on"] == dt.date(2025, 10, 31)


def test_collection_sources_without_dates_and_unknown_keys_are_named_gaps(
    world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    # A synthetic state whose pack names a schedule source but has never
    # loaded a dated window, plus calendar keys this build does not
    # register — one named gap each, nothing guessed.
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities (id, name, kind) VALUES (%s, 'QC LLC', 'llc')",
        (entity_id,),
    )
    conn.execute(
        """
        INSERT INTO jurisdictions (level, name, state, parent_id)
        SELECT 'state', 'Quocland', 'QC', id FROM jurisdictions WHERE level = 'federal'
        ON CONFLICT DO NOTHING
        """
    )
    conn.execute(
        """
        INSERT INTO jurisdiction_rules
          (jurisdiction_id, domain, code, value_text, citation, effective_from)
        SELECT id, 'tax_collection', 'collection.schedule.source',
               'published_by_collector; QC treasurer', 'QC Treasurer site (fixture)',
               DATE '2020-01-01'
        FROM jurisdictions WHERE state = 'QC' AND level = 'state'
        ON CONFLICT DO NOTHING
        """
    )
    conn.execute(
        """
        INSERT INTO jurisdiction_rules
          (jurisdiction_id, domain, code, value_text, citation, effective_from)
        SELECT id, 'tax_collection', 'collection.calendar',
               'us-qc.not-registered', 'QC Stat. 1 (fixture)', DATE '2020-01-01'
        FROM jurisdictions WHERE state = 'QC' AND level = 'state'
        ON CONFLICT DO NOTHING
        """
    )
    conn.execute(
        """
        INSERT INTO jurisdiction_rules
          (jurisdiction_id, domain, code, value_text, citation, effective_from)
        SELECT id, 'registration', 'registration.rental_license.calendar',
               'us-qc.also-not-registered', 'QC Ord. 2 (fixture)', DATE '2020-01-01'
        FROM jurisdictions WHERE state = 'QC' AND level = 'state'
        ON CONFLICT DO NOTHING
        """
    )
    property_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO properties (id, entity_id, label, street_1, city, state,
                                postal_code, kind, jurisdiction_id)
        VALUES (%s, %s, 'qc', '1 Main St', 'Quoc City', 'QC', '00000',
                'single_family',
                (SELECT id FROM jurisdictions WHERE state = 'QC' AND level = 'state'))
        """,
        (property_id, entity_id),
    )
    conn.commit()
    body = client.post("/sweep/deadlines?as_of=2026-07-01").json()
    mine = [g for g in body["coverage_gaps"] if g["property_id"] == property_id]
    reasons = {(g["domain"], g["reason"]) for g in mine}
    assert ("tax_collection", "window_not_published") in reasons
    assert ("tax_collection", "calendar_key_unregistered") in reasons
    assert ("registration", "calendar_key_unregistered") in reasons
    not_published = next(g for g in mine if g["reason"] == "window_not_published")
    assert "no discount window has ever been loaded" in not_published["detail"]


def test_an_empty_portfolio_sweeps_to_zero_today(clean: None, client: TestClient) -> None:
    # No as_of: the endpoint defaults to today. With nothing in the portfolio
    # there is nothing to schedule, whatever today happens to be.
    body = client.post("/sweep/deadlines").json()
    assert body["total"] == 0
