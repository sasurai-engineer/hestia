"""The service against a real database: contract, audit, and error shapes."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import config, db


class TestHealth:
    def test_alive_needs_no_database(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_ready_counts_migrations(self, client: TestClient) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        # 8 modules + 2 seeds, at minimum, forever after.
        assert body["migrations"] >= 10

    def test_unreachable_database_is_a_server_error(
        self, flaky_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HESTIA_DATABASE_URL", "postgresql://postgres:x@127.0.0.1:1/void")
        assert flaky_client.get("/readyz").status_code == 500


class TestConfig:
    def test_missing_url_is_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HESTIA_DATABASE_URL", raising=False)
        with pytest.raises(config.ConfigurationError, match="HESTIA_DATABASE_URL"):
            config.database_url()

    def test_stripe_webhook_secret_is_required_when_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HESTIA_STRIPE_WEBHOOK_SECRET", raising=False)
        with pytest.raises(config.ConfigurationError, match="HESTIA_STRIPE_WEBHOOK_SECRET"):
            config.stripe_webhook_secret()
        monkeypatch.setenv("HESTIA_STRIPE_WEBHOOK_SECRET", "whsec_x")
        assert config.stripe_webhook_secret() == "whsec_x"

    def test_non_postgres_url_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HESTIA_DATABASE_URL", "mysql://nope")
        with pytest.raises(config.ConfigurationError, match="postgresql://"):
            config.database_url()


class TestContract:
    def test_openapi_document_carries_the_routes(self, client: TestClient) -> None:
        spec = client.get("/openapi.json").json()
        assert spec["info"]["title"] == "Hestia API"
        for path in (
            "/healthz",
            "/readyz",
            "/entities",
            "/properties",
            "/properties/{property_id}",
            "/properties/{property_id}/dossier",
            "/sweep/deadlines",
            "/coverage/jurisdictions",
        ):
            assert path in spec["paths"], path
        # Two gap models exist on purpose (sweep vs coverage); both must keep
        # clean component names in the published contract.
        components = spec["components"]["schemas"]
        assert "SweepGapOut" in components
        assert "CoverageGapOut" in components
        # FastAPI derives multipart body schema names from the route path
        # (Body_..._post) — those are fine; module-mangled model names
        # (hestia_api__x__Model) are not.
        assert not any("__" in name for name in components if not name.startswith("Body_"))

    def test_every_response_carries_a_request_id(self, client: TestClient) -> None:
        minted = client.get("/healthz")
        assert uuid.UUID(minted.headers["x-request-id"])
        echoed = client.get("/healthz", headers={"x-request-id": "req-abc-123"})
        assert echoed.headers["x-request-id"] == "req-abc-123"


@pytest.mark.usefixtures("clean")
class TestEntitiesAndProperties:
    def test_create_and_list_round_trip(self, client: TestClient) -> None:
        created = client.post(
            "/entities",
            json={"name": "Test Holdings LLC", "kind": "llc", "formation_state": "KY"},
        )
        assert created.status_code == 201
        entity = created.json()
        assert uuid.UUID(entity["id"])
        listed = client.get("/entities").json()
        assert [e["name"] for e in listed] == ["Test Holdings LLC"]

    def test_property_lifecycle_and_404(self, client: TestClient) -> None:
        entity_id = client.post("/entities", json={"name": "E", "kind": "llc"}).json()["id"]
        created = client.post(
            "/properties",
            json={
                "entity_id": entity_id,
                "label": "412 Maple",
                "street_1": "412 Maple St",
                "city": "Newport",
                "state": "KY",
                "postal_code": "41071",
                "kind": "single_family",
                "year_built": 1962,
            },
        )
        assert created.status_code == 201
        prop = created.json()
        fetched = client.get(f"/properties/{prop['id']}").json()
        assert fetched == prop
        missing = client.get(f"/properties/{uuid.uuid4()}")
        assert missing.status_code == 404

    def test_jurisdiction_resolves_from_the_loaded_packs(
        self, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        entity_id = client.post("/entities", json={"name": "J", "kind": "llc"}).json()["id"]

        def make(city: str, state: str, county: str | None = None) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "entity_id": entity_id,
                "label": f"{city} {state}",
                "street_1": "1 Main St",
                "city": city,
                "state": state,
                "postal_code": "00000",
                "kind": "single_family",
            }
            if county is not None:
                payload["county"] = county
            response = client.post("/properties", json=payload)
            assert response.status_code == 201
            return response.json()

        # A seeded municipality resolves to itself...
        newport = make("Newport", "KY", county="Campbell County")
        row = conn.execute(
            "SELECT name, level FROM jurisdictions WHERE id = %s",
            (newport["jurisdiction_id"],),
        ).fetchone()
        assert row is not None and (row["name"], row["level"]) == ("Newport", "municipality")
        assert newport["county"] == "Campbell County"
        # ...an unseeded city falls back to its state row...
        rural = make("Somewhereville", "KY")
        row = conn.execute(
            "SELECT name, level FROM jurisdictions WHERE id = %s",
            (rural["jurisdiction_id"],),
        ).fetchone()
        assert row is not None and (row["name"], row["level"]) == ("Kentucky", "state")
        # ...and a state with no pack resolves to nothing, honestly.
        assert make("Nashville", "TN")["jurisdiction_id"] is None

    def test_validation_is_the_contract_not_a_suggestion(self, client: TestClient) -> None:
        assert client.post("/entities", json={"name": "", "kind": "llc"}).status_code == 422
        assert client.post("/entities", json={"name": "X", "kind": "megacorp"}).status_code == 422
        orphan = client.post(
            "/properties",
            json={
                "entity_id": str(uuid.uuid4()),
                "label": "L",
                "street_1": "S",
                "city": "C",
                "state": "KY",
                "postal_code": "41071",
                "kind": "single_family",
            },
        )
        assert orphan.status_code == 422
        assert "entity_id" in orphan.json()["detail"]

    def test_a_vanished_jurisdiction_is_not_blamed_on_the_entity(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hestia_api import app as app_module

        entity_id = client.post("/entities", json={"name": "V", "kind": "llc"}).json()["id"]
        monkeypatch.setattr(
            app_module.jurisdiction,
            "resolve",
            lambda conn, **kw: app_module.jurisdiction.Resolved(
                jurisdiction_id=str(uuid.uuid4()), level="municipality"
            ),
        )
        response = client.post(
            "/properties",
            json={
                "entity_id": entity_id,
                "label": "ghost",
                "street_1": "1 Main St",
                "city": "Nowhere",
                "state": "KY",
                "postal_code": "40000",
                "kind": "single_family",
            },
        )
        assert response.status_code == 422
        assert "jurisdiction" in response.json()["detail"]

    def test_mutations_write_their_audit_row_in_the_same_transaction(
        self, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        request_id = f"audit-proof-{uuid.uuid4()}"
        response = client.post(
            "/entities",
            json={"name": "Audited LLC", "kind": "llc"},
            headers={"x-request-id": request_id, "x-actor": "tai"},
        )
        assert response.status_code == 201
        row = conn.execute(
            "SELECT actor, action, table_name, record_id, after_value"
            " FROM audit_log WHERE request_id = %s",
            (request_id,),
        ).fetchone()
        assert row is not None
        assert row["actor"] == "tai"
        assert row["action"] == "entity.create"
        assert str(row["record_id"]) == response.json()["id"]
        assert row["after_value"]["name"] == "Audited LLC"


def test_record_audit_accepts_a_payload_free_action(conn: psycopg.Connection[Any]) -> None:
    request_id = f"bare-{uuid.uuid4()}"
    db.record_audit(conn, actor="system", action="noop", request_id=request_id)
    row = conn.execute(
        "SELECT after_value FROM audit_log WHERE request_id = %s", (request_id,)
    ).fetchone()
    assert row is not None and row["after_value"] is None
