"""The append-only ledger through the API: entries, reversals, the register."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def world(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "L", "kind": "llc"}).json()["id"]
    property_id = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "412 Maple",
            "street_1": "412 Maple St",
            "city": "Newport",
            "state": "KY",
            "postal_code": "41071",
            "kind": "single_family",
        },
    ).json()["id"]
    return {"entity": entity_id, "property": property_id}


def _entry(world: dict[str, str], **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "occurred_on": "2026-08-01",
        "category": "rent",
        "amount": "1450.00",
        "memo": "August rent",
        "property_id": world["property"],
    }
    entry.update(overrides)
    return entry


class TestAppend:
    def test_append_and_read_back(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        request_id = f"ledger-{uuid.uuid4()}"
        created = client.post("/ledger", json=_entry(world), headers={"x-request-id": request_id})
        assert created.status_code == 201
        event = created.json()
        assert event["amount"] == "1450.00"
        assert event["reversed"] is False
        assert event["reverses_event_uuid"] is None
        audit = conn.execute(
            "SELECT action, record_id FROM audit_log WHERE request_id = %s", (request_id,)
        ).fetchone()
        assert audit is not None
        assert audit["action"] == "ledger.append"
        assert str(audit["record_id"]) == event["event_uuid"]

    def test_the_api_refuses_what_the_schema_would_not(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # No anchor at all: insertable at the schema layer, meaningless to an
        # owner — the API is the stricter gate.
        unanchored = _entry(world)
        del unanchored["property_id"]
        assert client.post("/ledger", json=unanchored).status_code == 422
        assert client.post("/ledger", json=_entry(world, amount="0.00")).status_code == 422
        capital = _entry(world, category="capital_improvement", is_capital=True)
        assert client.post("/ledger", json=capital).status_code == 422  # no rationale
        capital["capitalisation_rationale"] = "new roof: betterment under BAR"
        assert client.post("/ledger", json=capital).status_code == 201

    def test_a_bad_anchor_names_itself(self, world: dict[str, str], client: TestClient) -> None:
        response = client.post("/ledger", json=_entry(world, property_id=str(uuid.uuid4())))
        assert response.status_code == 422
        assert "property_id" in response.json()["detail"]


class TestReversal:
    def test_reversal_cancels_and_links(self, world: dict[str, str], client: TestClient) -> None:
        original = client.post("/ledger", json=_entry(world)).json()
        reversed_out = client.post(f"/ledger/{original['event_uuid']}/reverse", json={})
        assert reversed_out.status_code == 201
        reversal = reversed_out.json()["reversal"]
        assert Decimal(reversal["amount"]) == Decimal("-1450.00")
        assert reversal["reverses_event_uuid"] == original["event_uuid"]
        assert reversal["memo"] == f"reversal of {original['event_uuid']}"
        register = client.get(f"/ledger?property_id={world['property']}").json()
        assert Decimal(register["net"]) == 0
        by_uuid = {e["event_uuid"]: e for e in register["events"]}
        assert by_uuid[original["event_uuid"]]["reversed"] is True
        assert by_uuid[reversal["event_uuid"]]["reversed"] is False

    def test_reverse_with_correction_in_one_call(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        original = client.post("/ledger", json=_entry(world, amount="1540.00")).json()
        result = client.post(
            f"/ledger/{original['event_uuid']}/reverse",
            json={
                "memo": "transposed digits",
                "corrected": _entry(world, amount="1450.00"),
            },
        ).json()
        assert result["corrected"]["amount"] == "1450.00"
        register = client.get(f"/ledger?property_id={world['property']}").json()
        assert Decimal(register["net"]) == Decimal("1450.00")

    def test_a_capital_reversal_keeps_its_explanation(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        original = client.post(
            "/ledger",
            json=_entry(
                world,
                category="capital_improvement",
                amount="-8200.00",
                is_capital=True,
                capitalisation_rationale="roof replacement: restoration under BAR",
            ),
        ).json()
        reversal = client.post(f"/ledger/{original['event_uuid']}/reverse", json={}).json()[
            "reversal"
        ]
        assert reversal["is_capital"] is True
        assert reversal["capitalisation_rationale"].startswith("reversal: roof")

    def test_double_reversal_is_a_conflict(self, world: dict[str, str], client: TestClient) -> None:
        original = client.post("/ledger", json=_entry(world)).json()
        assert client.post(f"/ledger/{original['event_uuid']}/reverse", json={}).status_code == 201
        second = client.post(f"/ledger/{original['event_uuid']}/reverse", json={})
        assert second.status_code == 409
        assert "correct the correction" in second.json()["detail"]

    def test_reversing_nothing_is_a_404(self, world: dict[str, str], client: TestClient) -> None:
        assert client.post(f"/ledger/{uuid.uuid4()}/reverse", json={}).status_code == 404


class TestRegister:
    def test_filters_and_totals(self, world: dict[str, str], client: TestClient) -> None:
        entries = [
            _entry(world, occurred_on="2026-07-01", amount="1450.00"),
            _entry(world, occurred_on="2026-08-01", amount="1450.00"),
            _entry(
                world,
                occurred_on="2026-08-14",
                category="repairs",
                amount="-380.00",
                memo="water heater relief valve",
                counterparty="NKY Plumbing",
            ),
            _entry(
                world,
                occurred_on="2026-08-20",
                category="utilities",
                amount="-92.40",
                property_id=None,
                entity_id=world["entity"],
            ),
        ]
        for entry in entries:
            assert client.post("/ledger", json=entry).status_code == 201

        # Scoped to this test's own property: the ledger is append-only and
        # shared, so global arithmetic belongs to reports, not to tests.
        mine = f"property_id={world['property']}"
        scoped = client.get(f"/ledger?{mine}").json()
        assert len(scoped["events"]) == 3  # the utilities row anchors to the entity
        assert Decimal(scoped["total_in"]) == Decimal("2900.00")
        assert Decimal(scoped["total_out"]) == Decimal("-380.00")
        assert Decimal(scoped["net"]) == Decimal("2520.00")
        # Newest first, ties broken by insertion order.
        assert [e["occurred_on"] for e in scoped["events"]] == [
            "2026-08-14",
            "2026-08-01",
            "2026-07-01",
        ]

        just_repairs = client.get(f"/ledger?{mine}&category=repairs").json()
        assert len(just_repairs["events"]) == 1
        assert just_repairs["events"][0]["counterparty"] == "NKY Plumbing"

        august = client.get(
            f"/ledger?{mine}&occurred_from=2026-08-01&occurred_to=2026-08-31"
        ).json()
        assert len(august["events"]) == 2

        # The entity-anchored row is reachable unscoped by its category.
        utilities = client.get("/ledger?category=utilities").json()
        assert any(e["entity_id"] == world["entity"] for e in utilities["events"])

    def test_the_limit_truncates_rows_never_arithmetic(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        for day in ("01", "02", "03"):
            client.post("/ledger", json=_entry(world, occurred_on=f"2026-08-{day}"))
        register = client.get(f"/ledger?property_id={world['property']}&limit=1").json()
        assert len(register["events"]) == 1
        assert Decimal(register["net"]) == Decimal("4350.00")
