"""The dossier orchestrator against the live-recorded provider fixtures.

The fake fetch routes by provider name to payloads recorded from the real
Census geocoder and FEMA NFHL (2026-08-25) — the pipeline runs exactly as in
production, minus the socket. CI never touches the network.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import dossier
from hestia_ingest.fetch import FetchError, FetchResult, ProviderRequest

FIXTURES = Path(__file__).resolve().parents[2] / "ingest" / "fixtures"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def fixture_fetch(flood_fixture: str = "fema-nfhl-newport.json") -> dossier.Fetcher:
    def fetch(request: ProviderRequest) -> FetchResult:
        payload = {
            "census-geocoder": lambda: _fixture("census-geocode-newport.json"),
            "fema-nfhl": lambda: _fixture(flood_fixture),
        }[request.provider]()
        return FetchResult(payload=payload, raw_text=json.dumps(payload))

    return fetch


def _steps(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["name"]: step for step in body["steps"]}


def test_an_address_becomes_a_dossier(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dossier, "live_fetch", fixture_fetch())
    request_id = f"dossier-{uuid.uuid4()}"
    response = client.post(
        f"/properties/{newport_property}/dossier?as_of=2026-08-25",
        headers={"x-request-id": request_id},
    )
    assert response.status_code == 200
    body = response.json()
    steps = _steps(body)
    assert {s["status"] for s in body["steps"]} == {"ok"}

    # Geocode: the recorded match, stored verbatim in ingestion_runs.
    assert "MONMOUTH" in steps["geocode"]["detail"]
    runs = conn.execute(
        "SELECT provider, status, raw_response FROM ingestion_runs"
        " WHERE property_id = %s ORDER BY requested_at",
        (newport_property,),
    ).fetchall()
    assert [(r["provider"], r["status"]) for r in runs] == [
        ("census-geocoder", "ok"),
        ("fema-nfhl", "ok"),
    ]
    assert all(r["raw_response"] is not None for r in runs)

    # Jurisdiction: the FIPS/name upgrade lands on the Newport municipality,
    # and the coordinates + county are recorded with public-record provenance.
    prop = conn.execute(
        """
        SELECT p.latitude, p.longitude, p.county, j.name AS jurisdiction,
               pr.kind AS provenance_kind
        FROM properties p
        JOIN jurisdictions j ON j.id = p.jurisdiction_id
        JOIN provenance pr ON pr.id = p.provenance_id
        WHERE p.id = %s
        """,
        (newport_property,),
    ).fetchone()
    assert prop is not None
    assert prop["jurisdiction"] == "Newport"
    assert prop["county"] == "Campbell County"
    assert prop["latitude"] is not None and prop["longitude"] is not None
    assert prop["provenance_kind"] == "public_record"

    # Flood: levee-protected Newport probes zone X, outside the SFHA.
    hazard = conn.execute(
        "SELECT zone, in_special_flood_hazard_area FROM hazard_facts"
        " WHERE property_id = %s AND kind = 'flood'",
        (newport_property,),
    ).fetchone()
    assert hazard is not None
    assert hazard["zone"] == "X"
    assert hazard["in_special_flood_hazard_area"] is False

    # Components: one row per catalog system, provenance mandatory and bands
    # ordered — a 1962 house has replaced everything at least once.
    components = conn.execute(
        """
        SELECT ct.code, c.installed_year_low, c.installed_year_high, pr.kind
        FROM components c
        JOIN component_types ct ON ct.id = c.component_type_id
        JOIN provenance pr ON pr.id = c.provenance_id
        WHERE c.property_id = %s
        """,
        (newport_property,),
    ).fetchall()
    assert len(components) == 11  # every CATALOG_LIVES system
    assert all(r["kind"] == "inferred" for r in components)
    assert all(r["installed_year_low"] <= r["installed_year_high"] for r in components)

    # Defects: the 1962 era register — lead paint, asbestos, orangeburg — but
    # NOT aluminium wiring (1965-73 starts after this vintage).
    defects = {
        r["kind"]
        for r in conn.execute(
            "SELECT kind FROM latent_defects WHERE property_id = %s",
            (newport_property,),
        ).fetchall()
    }
    assert defects == {"lead_paint", "asbestos", "orangeburg_sewer", "cast_iron_drain"}
    assert "aluminium_branch_wiring" not in defects

    # The sweep ran inside the same call: the 2027 KY window is on the books.
    assert body["sweep"]["inserted"]["assessment_appeal_window"] == 1
    # The appeal side is fully covered; the one gap is the collection
    # calendar being honest — Campbell's discount schedule publishes yearly
    # and the next year's is not out yet (issue #149).
    assert [g["domain"] for g in body["sweep"]["gaps"]] == ["tax_collection"]
    assert body["sweep"]["gaps"][0]["reason"] == "window_awaiting_publication"

    # And the whole assembly audited itself under this request id.
    audit = conn.execute(
        "SELECT action, after_value FROM audit_log WHERE request_id = %s",
        (request_id,),
    ).fetchone()
    assert audit is not None
    assert audit["action"] == "dossier.assemble"
    assert [s["status"] for s in audit["after_value"]["steps"]] == ["ok"] * 6


def test_rerunning_the_dossier_duplicates_nothing(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dossier, "live_fetch", fixture_fetch())
    first = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    second = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    steps = _steps(second)
    assert steps["components"]["detail"] == "0 inferred, 11 already present"
    assert steps["defects"]["detail"].startswith("0 flagged")
    assert second["sweep"]["inserted"] == {}
    assert first["sweep"]["inserted"] != {}
    counts = conn.execute(
        """
        SELECT (SELECT count(*) FROM components WHERE property_id = %(p)s) AS components,
               (SELECT count(*) FROM latent_defects WHERE property_id = %(p)s) AS defects,
               (SELECT count(*) FROM hazard_facts WHERE property_id = %(p)s) AS hazards
        """,
        {"p": newport_property},
    ).fetchone()
    assert counts is not None
    assert (counts["components"], counts["defects"], counts["hazards"]) == (11, 4, 1)


def test_a_sfha_property_gets_the_flood_truth(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dossier, "live_fetch", fixture_fetch(flood_fixture="fema-nfhl-sfha-derived.json")
    )
    body = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    assert "IN the special flood hazard area" in _steps(body)["flood"]["detail"]
    hazard = conn.execute(
        "SELECT zone, in_special_flood_hazard_area, base_flood_elevation_ft"
        " FROM hazard_facts WHERE property_id = %s AND kind = 'flood'",
        (newport_property,),
    ).fetchone()
    assert hazard is not None
    assert hazard["zone"] == "AE"
    assert hazard["in_special_flood_hazard_area"] is True
    assert float(hazard["base_flood_elevation_ft"]) == 512.3


def test_a_dead_network_degrades_and_says_so(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dead(request: ProviderRequest) -> FetchResult:
        raise FetchError(request.provider, "transport failure: socket down")

    monkeypatch.setattr(dossier, "live_fetch", dead)
    body = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    steps = _steps(body)
    assert steps["geocode"]["status"] == "failed"
    assert steps["jurisdiction"]["status"] == "skipped"
    assert steps["flood"]["status"] == "skipped"
    # Inference needs no network: the dossier still fills what it can.
    assert steps["components"]["status"] == "ok"
    assert steps["defects"]["status"] == "ok"
    assert steps["sweep"]["status"] == "ok"
    run = conn.execute(
        "SELECT status, error_detail FROM ingestion_runs WHERE property_id = %s",
        (newport_property,),
    ).fetchone()
    assert run is not None
    assert run["status"] == "error"
    assert "socket down" in run["error_detail"]


def test_an_unmatched_address_is_an_error_run_with_the_payload_kept(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unmatched(request: ProviderRequest) -> FetchResult:
        payload: dict[str, Any] = {"result": {"addressMatches": []}}
        return FetchResult(payload=payload, raw_text=json.dumps(payload))

    monkeypatch.setattr(dossier, "live_fetch", unmatched)
    body = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    assert _steps(body)["geocode"]["status"] == "failed"
    run = conn.execute(
        "SELECT status, raw_response FROM ingestion_runs WHERE property_id = %s"
        " AND provider = 'census-geocoder'",
        (newport_property,),
    ).fetchone()
    assert run is not None
    assert run["status"] == "error"
    assert run["raw_response"] is not None  # the payload survives for re-mapping


def test_flood_probe_failure_alone_still_upgrades_jurisdiction(
    newport_property: str, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def flaky(request: ProviderRequest) -> FetchResult:
        if request.provider == "fema-nfhl":
            raise FetchError(request.provider, "HTTP 503")
        return fixture_fetch()(request)

    monkeypatch.setattr(dossier, "live_fetch", flaky)
    body = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    steps = _steps(body)
    assert steps["geocode"]["status"] == "ok"
    assert steps["jurisdiction"]["status"] == "ok"
    assert steps["flood"]["status"] == "failed"


def _routed(census_payload: dict[str, Any], flood_payload: dict[str, Any]) -> dossier.Fetcher:
    def fetch(request: ProviderRequest) -> FetchResult:
        payload = {"census-geocoder": census_payload, "fema-nfhl": flood_payload}[request.provider]
        return FetchResult(payload=payload, raw_text=json.dumps(payload))

    return fetch


def test_an_unpacked_geography_records_coordinates_without_a_wrong_guess(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Incorporated Place in the match and a county no pack carries: the
    coordinates land, the jurisdiction stays whatever the name-based resolver
    chose, and the flood probe reports an unmapped point as an answer."""
    census_payload = _fixture("census-geocode-newport.json")
    geographies = census_payload["result"]["addressMatches"][0]["geographies"]
    del geographies["Incorporated Places"]
    geographies["Counties"][0]["GEOID"] = "18097"  # Marion County IN: no pack seeds it
    monkeypatch.setattr(dossier, "live_fetch", _routed(census_payload, {"features": []}))
    body = client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25").json()
    steps = _steps(body)
    assert steps["jurisdiction"]["detail"] == (
        "coordinates recorded; no pack row matched the FIPS keys"
    )
    assert steps["flood"]["detail"] == "point is outside any mapped flood polygon"
    row = conn.execute(
        "SELECT latitude, jurisdiction_id FROM properties WHERE id = %s",
        (newport_property,),
    ).fetchone()
    assert row is not None
    assert row["latitude"] is not None
    assert row["jurisdiction_id"] is not None  # the create-time resolve survives
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM hazard_facts WHERE property_id = %s",
            (newport_property,),
        ).fetchone()["n"]  # type: ignore[index]
        == 0
    )


def test_a_place_name_without_a_census_suffix_still_matches(
    newport_property: str,
    client: TestClient,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    census_payload = _fixture("census-geocode-newport.json")
    geographies = census_payload["result"]["addressMatches"][0]["geographies"]
    geographies["Incorporated Places"][0]["NAME"] = "Newport"
    flood = _fixture("fema-nfhl-newport.json")
    monkeypatch.setattr(dossier, "live_fetch", _routed(census_payload, flood))
    client.post(f"/properties/{newport_property}/dossier?as_of=2026-08-25")
    row = conn.execute(
        """
        SELECT j.name FROM properties p JOIN jurisdictions j ON j.id = p.jurisdiction_id
        WHERE p.id = %s
        """,
        (newport_property,),
    ).fetchone()
    assert row is not None and row["name"] == "Newport"


def test_a_missing_property_is_a_404(clean: None, client: TestClient) -> None:
    response = client.post(f"/properties/{uuid.uuid4()}/dossier")
    assert response.status_code == 404


def test_a_property_without_a_vintage_skips_inference(
    clean: None, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entity_id = client.post("/entities", json={"name": "N", "kind": "llc"}).json()["id"]
    property_id = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "no-vintage",
            "street_1": "998 Monmouth St",
            "city": "Newport",
            "state": "KY",
            "postal_code": "41071",
            "kind": "single_family",
        },
    ).json()["id"]
    monkeypatch.setattr(dossier, "live_fetch", fixture_fetch())
    body = client.post(f"/properties/{property_id}/dossier?as_of=2026-08-25").json()
    steps = _steps(body)
    assert steps["components"]["status"] == "skipped"
    assert steps["defects"]["status"] == "skipped"
    assert steps["flood"]["status"] == "ok"
