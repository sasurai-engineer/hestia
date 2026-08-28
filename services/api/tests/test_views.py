"""The read surface: the dossier as a document the web client displays."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import dossier
from test_dossier import fixture_fetch


@pytest.fixture
def assembled(newport_property: str, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(dossier, "live_fetch", fixture_fetch())
    response = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25")
    assert response.status_code == 200
    return newport_property


def test_the_portfolio_list_carries_the_summary(assembled: str, client: TestClient) -> None:
    (summary,) = client.get("/properties").json()
    assert summary["id"] == assembled
    assert summary["label"] == "998 Monmouth"
    assert summary["jurisdiction"] == "Newport"
    assert summary["defect_count"] == 4
    assert summary["component_count"] == 11
    assert summary["next_deadline_on"] == "2027-05-17"  # the KY appeal window


def test_the_dossier_reads_as_a_document(assembled: str, client: TestClient) -> None:
    view = client.get(f"/properties/{assembled}/dossier").json()
    assert [link["name"] for link in view["jurisdiction_chain"]] == [
        "Newport",
        "Campbell County",
        "Kentucky",
        "United States",
    ]
    assert view["county"] == "Campbell County"
    assert view["latitude"] is not None

    (flood,) = view["hazards"]
    assert (flood["kind"], flood["zone"]) == ("flood", "X")
    assert flood["in_special_flood_hazard_area"] is False

    assert len(view["components"]) == 11
    water_heater = next(c for c in view["components"] if c["code"] == "water_heater.tank")
    assert water_heater["display_name"]
    assert water_heater["life_years_low"] == 8.0
    assert water_heater["provenance_kind"] == "inferred"
    assert 0 < water_heater["confidence"] < 1
    assert water_heater["derived_from"]  # every inference explains itself

    kinds = {d["kind"] for d in view["defects"]}
    assert kinds == {"lead_paint", "asbestos", "orangeburg_sewer", "cast_iron_drain"}
    lead = next(d for d in view["defects"] if d["kind"] == "lead_paint")
    assert lead["triggers_disclosure"] is True
    assert "4852d" in lead["citation"]

    appeal = next(d for d in view["deadlines"] if d["kind"] == "assessment_appeal_window")
    assert appeal["due_on"] == "2027-05-17"
    assert appeal["window_opens_on"] == "2027-05-03"
    assert "62A307" in appeal["note"]


def test_the_calendar_lists_deadlines_in_order(assembled: str, client: TestClient) -> None:
    rows = client.get("/deadlines").json()
    assert rows == sorted(rows, key=lambda r: (r["due_on"], r["kind"]))
    assert any(r["property_label"] == "998 Monmouth" for r in rows)
    # Entity-anchored dates (estimated tax) carry no property label.
    estimated = next(r for r in rows if r["kind"] == "estimated_tax")
    assert estimated["property_label"] is None

    capped = client.get("/deadlines?due_before=2026-12-31&limit=2").json()
    assert len(capped) <= 2
    assert all(r["due_on"] <= "2026-12-31" for r in capped)


def test_an_unresolved_property_reads_with_an_empty_chain(clean: None, client: TestClient) -> None:
    entity_id = client.post("/entities", json={"name": "U", "kind": "llc"}).json()["id"]
    property_id = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "indianapolis",
            "street_1": "1 Monument Cir",
            "city": "Indianapolis",
            "state": "IN",
            "postal_code": "46204",
            "kind": "single_family",
        },
    ).json()["id"]
    view = client.get(f"/properties/{property_id}/dossier").json()
    assert view["jurisdiction_chain"] == []  # no IN pack: shown, not guessed
    assert view["components"] == [] and view["defects"] == []


def test_missing_dossier_view_is_a_404(clean: None, client: TestClient) -> None:
    assert client.get(f"/properties/{uuid.uuid4()}/dossier").status_code == 404


def test_an_empty_portfolio_lists_empty(
    clean: None, client: TestClient, conn: psycopg.Connection[Any]
) -> None:
    assert client.get("/properties").json() == []
    assert conn.execute("SELECT count(*) AS n FROM properties").fetchone()["n"] == 0  # type: ignore[index]
