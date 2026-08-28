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

    body = client.post("/sweep/deadlines?as_of=2026-11-01").json()
    assert body["inserted"]["assessment_appeal_window"] == 3
    (gap,) = body["coverage_gaps"]
    assert (gap["state"], gap["reason"]) == ("IN", "no_state_jurisdiction")

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
    # Tennessee's 2026 window closed August 3; the next one is a summer 2027
    # window, and 2027-08-01 is a Sunday that TCA 1-3-102 rolls to Monday.
    assert tn["state"] == "TN"
    assert tn["due_on"] == dt.date(2027, 8, 2)
    assert tn["window_opens_on"] == dt.date(2027, 6, 1)
    assert "TCA 67-5-1412" in tn["citation"]
    assert "State Board of Equalization" in tn["note"]
    # Three states, three windows, no two alike — from one sweep.
    assert len({ky["due_on"], oh["due_on"], tn["due_on"]}) == 3


def test_an_empty_portfolio_sweeps_to_zero_today(clean: None, client: TestClient) -> None:
    # No as_of: the endpoint defaults to today. With nothing in the portfolio
    # there is nothing to schedule, whatever today happens to be.
    body = client.post("/sweep/deadlines").json()
    assert body["total"] == 0
