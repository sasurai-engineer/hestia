"""The coverage report: honest per-domain answers, never a silent unknown."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def two_properties(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "Cov", "kind": "llc"}).json()["id"]
    ids = {}
    for label, city, state in (("covered", "Newport", "KY"), ("bare", "Indianapolis", "IN")):
        ids[label] = client.post(
            "/properties",
            json={
                "entity_id": entity_id,
                "label": label,
                "street_1": "1 Main St",
                "city": city,
                "state": state,
                "postal_code": "00000",
                "kind": "single_family",
            },
        ).json()["id"]
    return ids


def test_the_report_answers_every_domain(
    two_properties: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    body = client.get("/coverage/jurisdictions?as_of=2026-08-25").json()
    assert body["as_of"] == "2026-08-25"

    covered = next(p for p in body["properties"] if p["label"] == "covered")
    assert covered["resolution"]["level"] == "municipality"
    assert covered["resolution"]["chain"] == [
        "Newport",
        "Campbell County",
        "Kentucky",
        "United States",
    ]
    appeal = covered["domains"]["assessment_appeal"]
    assert appeal["status"] == "covered"
    assert appeal["source"] == "Kentucky"
    assert appeal["citation"] == "KRS 133.045"
    assert appeal["calendar_key"] == "us-ky.open-inspection"
    assert appeal["calendar_registered"] is True
    ltl = covered["domains"]["landlord_tenant_act"]
    assert ltl["status"] == "covered"
    assert ltl["source"] == "Newport"  # the municipal adoption row wins over the state
    # Kentucky's 100% ratio is seeded now (seed/950). It was absent for as long
    # as nothing divided by it, and "obvious" is exactly why it went missing:
    # Ohio's 35% and Tennessee's 25% were seeded because they surprise.
    ratio = covered["domains"]["assessment_ratio"]
    assert ratio["status"] == "covered"
    assert ratio["source"] == "Kentucky"
    assert "s.172" in ratio["citation"]

    # The enum drives the domain list: every member is answered, none invented.
    enum_domains = {
        row["domain"]
        for row in conn.execute(
            "SELECT unnest(enum_range(NULL::rule_domain))::text AS domain"
        ).fetchall()
    }
    assert set(covered["domains"]) == enum_domains

    # The Indiana property is a gap, not a row that quietly knows nothing.
    assert [p["label"] for p in body["properties"]] == ["covered"]
    (gap,) = body["gaps"]
    assert gap["property_id"] == two_properties["bare"]
    assert gap["reason"] == "no_state_jurisdiction"
    assert "IN" in gap["message"]


def test_an_unregistered_calendar_key_is_reported(
    clean: None, client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    """A synthetic state pack whose rule names a calendar this build does not
    register. Sandboxed in state 'QX' so the REAL packs stay pristine —
    jurisdiction_rules is append-only, and a bogus rule planted on a real
    chain would poison every later test in the session."""
    exists = conn.execute(
        "SELECT 1 AS x FROM jurisdictions WHERE state = 'QX' AND level = 'state'"
    ).fetchone()
    if exists is None:
        conn.execute(
            """
            WITH state_row AS (
              INSERT INTO jurisdictions (level, name, state, parent_id)
              SELECT 'state', 'Quexland', 'QX', id
              FROM jurisdictions WHERE level = 'federal' RETURNING id
            ), county_row AS (
              INSERT INTO jurisdictions (level, name, state, parent_id)
              SELECT 'county', 'Quex County', 'QX', id FROM state_row RETURNING id
            )
            INSERT INTO jurisdictions (level, name, state, parent_id)
            SELECT 'municipality', 'Quexville', 'QX', id FROM county_row
            """
        )
        conn.execute(
            """
            INSERT INTO jurisdiction_rules
              (jurisdiction_id, domain, code, value_text, citation, effective_from)
            SELECT id, 'assessment_appeal', 'appeal.window.calendar',
                   'us-qx.future-calendar', 'QX Rev. Stat. 1.1 (test fixture)',
                   DATE '2000-01-01'
            FROM jurisdictions WHERE state = 'QX' AND level = 'county'
            """
        )
        conn.commit()
    entity_id = client.post("/entities", json={"name": "QX", "kind": "llc"}).json()["id"]
    created = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "quex",
            "street_1": "1 Main St",
            "city": "Quexville",
            "state": "QX",
            "postal_code": "00000",
            "kind": "single_family",
        },
    ).json()
    body = client.get("/coverage/jurisdictions?as_of=2026-08-25").json()
    quex = next(p for p in body["properties"] if p["label"] == "quex")
    assert quex["property_id"] == created["id"]
    assert quex["resolution"]["chain"] == [
        "Quexville",
        "Quex County",
        "Quexland",
        "United States",
    ]
    appeal = quex["domains"]["assessment_appeal"]
    assert appeal["calendar_key"] == "us-qx.future-calendar"
    assert appeal["calendar_registered"] is False
    assert appeal["source"] == "Quex County"


def test_coverage_defaults_to_today(clean: None, client: TestClient) -> None:
    body = client.get("/coverage/jurisdictions").json()
    assert body["properties"] == [] and body["gaps"] == []
