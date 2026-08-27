"""Maintenance: vendors, work orders, and the completion that teaches the
inventory.

The load-bearing test is the water-heater replacement: the old component
leaves the live inventory, the new one arrives with a known install date, the
cost posts as capital with its authority, and the capital forecast VISIBLY
moves because it is no longer guessing about that component.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import maintenance

WATER_HEATER = "water_heater.tank"


@pytest.fixture
def world(
    newport_property: str, conn: psycopg.Connection[Any], client: TestClient
) -> dict[str, str]:
    """A property with an aged, inferred water heater and a vendor to call."""
    entity = conn.execute(
        "SELECT entity_id::text FROM properties WHERE id = %s", (newport_property,)
    ).fetchone()
    kind = conn.execute(
        "SELECT id::text FROM component_types WHERE code = %s", (WATER_HEATER,)
    ).fetchone()
    assert kind is not None, "seed 901 must carry the tank water heater"
    provenance = conn.execute(
        """
        INSERT INTO provenance (kind, confidence, derived_from)
        VALUES ('inferred', 0.5, 'vintage 1962, no permit on file') RETURNING id::text
        """
    ).fetchone()
    component = conn.execute(
        """
        INSERT INTO components
          (property_id, component_type_id, installed_year_low, installed_year_high,
           provenance_id, condition)
        VALUES (%s, %s, 2004, 2014, %s, 'poor')
        RETURNING id::text
        """,
        (newport_property, kind["id"], provenance["id"]),
    ).fetchone()
    conn.commit()
    vendor = client.post(
        "/vendors",
        json={
            "entity_id": entity["entity_id"],
            "name": "Licking Valley Plumbing",
            "trade": "plumbing",
            "liability_expires_on": "2027-06-30",
            "workers_comp_expires_on": "2027-06-30",
        },
    ).json()
    return {
        "property": newport_property,
        "entity": entity["entity_id"],
        "component": component["id"],
        "component_type": kind["id"],
        "vendor": vendor["id"],
    }


def open_order(client: TestClient, world: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body = {
        "property_id": world["property"],
        "component_id": world["component"],
        "vendor_id": world["vendor"],
        "summary": "No hot water",
        "priority": "urgent",
        "reported_on": "2026-08-01",
        **overrides,
    }
    response = client.post("/work-orders", json=body)
    assert response.status_code == 201, response.text
    return response.json()


class TestVendors:
    def test_a_vendor_carries_its_credentials_and_their_standing(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        vendor = client.get(f"/vendors/{world['vendor']}?as_of=2026-08-27").json()
        assert vendor["coverage_state"] == "current"
        assert vendor["earliest_expiry"] == "2027-06-30"
        assert vendor["entity_name"] == "D"
        assert vendor["open_work_orders"] == 0

    def test_an_expired_certificate_says_so(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """The day it lapses, the owner silently reassumes the risk."""
        vendor = client.post(
            "/vendors",
            json={
                "entity_id": world["entity"],
                "name": "Lapsed Roofing",
                "trade": "roofing",
                "liability_expires_on": "2026-01-31",
            },
        ).json()
        assert vendor["coverage_state"] == "expired"
        soon = client.post(
            "/vendors",
            json={
                "entity_id": world["entity"],
                "name": "Expiring Soon HVAC",
                "trade": "hvac",
                "liability_expires_on": str(dt.date.today() + dt.timedelta(days=10)),
            },
        ).json()
        assert soon["coverage_state"] == "expiring"
        # A vendor who never showed a certificate has not been shown to carry
        # one; that is not the same as being covered.
        bare = client.post(
            "/vendors",
            json={"entity_id": world["entity"], "name": "Cash Handyman", "trade": "handyman"},
        ).json()
        assert bare["coverage_state"] == "unknown"
        assert bare["earliest_expiry"] is None
        # A trade licence is a qualification, not coverage: a vendor carrying
        # one and no certificate has NOT been shown to be insured.
        licensed = client.post(
            "/vendors",
            json={
                "entity_id": world["entity"],
                "name": "Licensed But Bare",
                "trade": "electrical",
                "license_expires_on": "2030-01-01",
            },
        ).json()
        assert licensed["coverage_state"] == "unknown"
        assert licensed["earliest_expiry"] == "2030-01-01"

    def test_the_same_trade_under_two_entities_says_so(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """Vendors are scoped per entity — right for filing, wrong for
        operations. The split is counted, not hidden."""
        second = client.post("/entities", json={"name": "Second LLC", "kind": "llc"}).json()
        client.post(
            "/vendors",
            json={
                "entity_id": second["id"],
                "name": "Licking Valley Plumbing",
                "trade": "plumbing",
            },
        )
        vendor = client.get(f"/vendors/{world['vendor']}").json()
        assert vendor["also_registered_under"] == 1

    def test_the_de_minimis_line_is_the_one_schedule_e_uses(self) -> None:
        """One constant, so the completion citation and the classification
        flag can never disagree about where $2,500 is."""
        from hestia_api.reports import DE_MINIMIS_CENTS

        # "does not exceed $2,500" — the threshold itself is INSIDE the harbour.
        assert "1.263(a)-1(f)" in maintenance._bar_citation(
            False, DE_MINIMIS_CENTS - Decimal("0.01"), "repaired"
        )
        assert "1.263(a)-1(f)" in maintenance._bar_citation(False, DE_MINIMIS_CENTS, "repaired")
        assert "1.263(a)-3(i)" in maintenance._bar_citation(
            False, DE_MINIMIS_CENTS + Decimal("0.01"), "repaired"
        )

    def test_one_vendor_name_per_owner_list(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        response = client.post(
            "/vendors",
            json={
                "entity_id": world["entity"],
                "name": "Licking Valley Plumbing",
                "trade": "hvac",
            },
        )
        assert response.status_code == 409

    def test_vendor_guards(self, world: dict[str, str], client: TestClient) -> None:
        assert (
            client.post(
                "/vendors",
                json={
                    "entity_id": "00000000-0000-4000-8000-000000000000",
                    "name": "Ghost",
                    "trade": "other",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/vendors",
                json={"entity_id": world["entity"], "name": "", "trade": "other"},
            ).status_code
            == 422
        )
        assert client.get("/vendors/00000000-0000-4000-8000-000000000000").status_code == 404
        listed = client.get(f"/vendors?entity_id={world['entity']}").json()
        assert any(row["id"] == world["vendor"] for row in listed)
        assert client.get("/vendors?include_retired=true").status_code == 200

    def test_credentials_become_deadlines_per_vendor(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """Two vendors expiring on one day are two deadlines, and one vendor's
        liability and comp expiring together are two more."""
        client.post(
            "/vendors",
            json={
                "entity_id": world["entity"],
                "name": "Second Trade Co",
                "trade": "electrical",
                "liability_expires_on": "2027-06-30",
            },
        )
        client.post("/sweep/deadlines?as_of=2026-08-27")
        rows = conn.execute(
            """
            SELECT kind::text AS kind, vendor_id::text, note
            FROM deadlines WHERE due_on = '2027-06-30' AND vendor_id IS NOT NULL
            ORDER BY note, kind
            """
        ).fetchall()
        kinds = {(row["kind"], row["note"]) for row in rows}
        assert ("vendor_insurance_expiration", "Licking Valley Plumbing") in kinds
        assert ("vendor_workers_comp_expiration", "Licking Valley Plumbing") in kinds
        assert ("vendor_insurance_expiration", "Second Trade Co") in kinds
        # Re-running the sweep inserts nothing new: the vendor anchor makes
        # each of these its own identity.
        before = len(rows)
        client.post("/sweep/deadlines?as_of=2026-08-27")
        after = conn.execute(
            "SELECT count(*) AS n FROM deadlines WHERE due_on = '2027-06-30'"
            " AND vendor_id IS NOT NULL"
        ).fetchone()
        assert after["n"] == before


class TestLifecycle:
    def test_the_board_walks_reported_to_scheduled_to_in_progress(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        assert order["status"] == "reported"
        assert order["legal_transitions"] == ["cancelled", "in_progress", "scheduled", "triaged"]
        assert order["component_label"] is not None
        assert order["vendor_name"] == "Licking Valley Plumbing"

        triaged = client.post(
            f"/work-orders/{order['id']}/transitions", json={"status": "triaged"}
        ).json()
        assert triaged["status"] == "triaged"
        scheduled = client.post(
            f"/work-orders/{order['id']}/transitions",
            json={"status": "scheduled", "scheduled_for": "2026-08-05"},
        ).json()
        assert scheduled["scheduled_for"] == "2026-08-05"
        started = client.post(
            f"/work-orders/{order['id']}/transitions", json={"status": "in_progress"}
        ).json()
        assert started["status"] == "in_progress"
        assert started["legal_transitions"] == ["cancelled"]

    def test_an_illegal_transition_names_what_is_legal(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        client.post(f"/work-orders/{order['id']}/transitions", json={"status": "in_progress"})
        response = client.post(
            f"/work-orders/{order['id']}/transitions", json={"status": "triaged"}
        )
        assert response.status_code == 409
        assert "in_progress may become cancelled" in response.json()["detail"]

    def test_scheduling_without_a_date_is_refused_by_the_database(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/transitions", json={"status": "scheduled"}
        )
        assert response.status_code == 422

    def test_a_cancellation_says_why(self, world: dict[str, str], client: TestClient) -> None:
        order = open_order(client, world)
        assert (
            client.post(
                f"/work-orders/{order['id']}/transitions", json={"status": "cancelled"}
            ).status_code
            == 422
        )
        cancelled = client.post(
            f"/work-orders/{order['id']}/transitions",
            json={"status": "cancelled", "cancelled_reason": "resident fixed the pilot light"},
        ).json()
        assert cancelled["status"] == "cancelled"
        assert cancelled["legal_transitions"] == []
        # Closed is closed.
        assert (
            client.post(
                f"/work-orders/{order['id']}/complete",
                json={"completed_on": "2026-08-10", "resolution": "repaired"},
            ).status_code
            == 409
        )

    def test_a_transition_cannot_name_a_vendor_that_does_not_exist(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """Handing the job to a vendor id that names nothing is an unknown
        reference, not a foreign key violation escaping as a 500."""
        order = open_order(client, world, vendor_id=None)
        ghost = client.post(
            f"/work-orders/{order['id']}/transitions",
            json={"status": "triaged", "vendor_id": "00000000-0000-4000-8000-000000000000"},
        )
        assert ghost.status_code == 404
        assert ghost.json()["detail"] == "vendor not found"
        # The refusal rolled back: the job never moved.
        assert client.get(f"/work-orders/{order['id']}").json()["status"] == "reported"
        assigned = client.post(
            f"/work-orders/{order['id']}/transitions",
            json={"status": "triaged", "vendor_id": world["vendor"]},
        )
        assert assigned.status_code == 200
        assert assigned.json()["vendor_name"] == "Licking Valley Plumbing"

    def test_a_work_order_cannot_borrow_another_property_s_unit(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        entity = client.post("/entities", json={"name": "Other", "kind": "llc"}).json()
        other = client.post(
            "/properties",
            json={
                "entity_id": entity["id"],
                "label": "Elsewhere",
                "street_1": "1 Elsewhere Ave",
                "city": "Newport",
                "state": "KY",
                "postal_code": "41071",
                "kind": "single_family",
            },
        ).json()
        unit = client.post("/units", json={"property_id": other["id"], "label": "A"}).json()
        response = client.post(
            "/work-orders",
            json={
                "property_id": world["property"],
                "unit_id": unit["id"],
                "summary": "Wrong property's unit",
            },
        )
        assert response.status_code == 422

    def test_a_refused_transition_names_the_rule_that_fired(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """One message for three different CHECKs told the operator to add a
        date when the date was exactly what was wrong."""
        order = open_order(client, world)  # reported_on 2026-08-01
        no_date = client.post(
            f"/work-orders/{order['id']}/transitions", json={"status": "scheduled"}
        )
        assert no_date.status_code == 422
        assert no_date.json()["detail"] == "a scheduled visit needs a date"
        no_reason = client.post(
            f"/work-orders/{order['id']}/transitions", json={"status": "cancelled"}
        )
        assert no_reason.status_code == 422
        assert no_reason.json()["detail"] == "a cancellation needs a reason"
        backdated = client.post(
            f"/work-orders/{order['id']}/transitions",
            json={"status": "scheduled", "scheduled_for": "2026-07-15"},
        )
        assert backdated.status_code == 422
        detail = backdated.json()["detail"]
        assert detail == "a visit cannot be scheduled before the job was reported"

    def test_listing_and_reading_guards(self, world: dict[str, str], client: TestClient) -> None:
        order = open_order(client, world)
        open_rows = client.get(
            f"/work-orders?property_id={world['property']}&open_only=true"
        ).json()
        assert any(row["id"] == order["id"] for row in open_rows)
        by_status = client.get("/work-orders?status=reported").json()
        assert all(row["status"] == "reported" for row in by_status)
        assert client.get("/work-orders/00000000-0000-4000-8000-000000000000").status_code == 404
        assert (
            client.post(
                "/work-orders/00000000-0000-4000-8000-000000000000/transitions",
                json={"status": "triaged"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/work-orders/00000000-0000-4000-8000-000000000000/complete",
                json={"completed_on": "2026-08-10", "resolution": "repaired"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/work-orders",
                json={
                    "property_id": "00000000-0000-4000-8000-000000000000",
                    "summary": "Ghost property",
                },
            ).status_code
            == 404
        )


class TestCompletion:
    def test_the_water_heater_replacement(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The acceptance criterion: old retired, new installed, cost posted as
        capital with its rationale, and the forecast visibly sharper."""
        before = client.get(
            f"/properties/{world['property']}/capex-forecast?horizon_years=10&as_of=2026-08-27"
        ).json()
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "replaced",
                "resolution_note": "50-gal gas tank, permit pulled",
                "replacement": {"installed_on": "2026-08-27", "warranty_expires_on": "2032-08-27"},
                "cost": {
                    "amount": "1850.00",
                    "is_capital": True,
                    "capitalisation_rationale": "restoration: replaced a major component "
                    "of the plumbing system",
                    "relation": "invoice",
                },
            },
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["retired_component_id"] == world["component"]
        assert result["installed_component_id"] is not None
        assert "1.263(a)-3(k)(1)(vi)" in result["capitalisation_citation"]

        retired = conn.execute(
            "SELECT retired_on, replaced_by_id::text, condition::text AS condition"
            " FROM components WHERE id = %s",
            (world["component"],),
        ).fetchone()
        assert retired["retired_on"] == dt.date(2026, 8, 27)
        assert retired["replaced_by_id"] == result["installed_component_id"]
        assert retired["condition"] == "failed"

        installed = conn.execute(
            """
            SELECT c.installed_on, c.condition::text AS condition, c.warranty_expires_on,
                   c.replacement_cost, p.kind::text AS provenance_kind, p.confidence
            FROM components c JOIN provenance p ON p.id = c.provenance_id
            WHERE c.id = %s
            """,
            (result["installed_component_id"],),
        ).fetchone()
        assert installed["installed_on"] == dt.date(2026, 8, 27)
        assert installed["condition"] == "new"
        assert installed["warranty_expires_on"] == dt.date(2032, 8, 27)
        assert installed["replacement_cost"] == Decimal("1850.00")
        # Someone did the work, so the date is stated, not inferred.
        assert installed["provenance_kind"] == "owner_stated"
        assert installed["confidence"] == Decimal("1.000")

        event = conn.execute(
            """
            SELECT amount, category::text AS category, is_capital, capitalisation_rationale
            FROM ledger_events WHERE event_uuid = %s
            """,
            (result["ledger_event_uuid"],),
        ).fetchone()
        assert event["amount"] == Decimal("-1850.00")
        assert event["category"] == "capital_improvement"
        assert event["is_capital"] is True
        assert "major component" in event["capitalisation_rationale"]

        detail = client.get(f"/work-orders/{order['id']}").json()
        assert detail["status"] == "completed"
        assert detail["resolution"] == "replaced"
        assert Decimal(detail["net_cost"]) == Decimal("1850.00")
        assert detail["costs"][0]["relation"] == "invoice"
        assert detail["costs"][0]["reversed"] is False

        # THE POINT: the forecast stops guessing about this component. The old
        # row carried a 2004-2014 band (12-22 years old, well past its life);
        # the new one is a day old.
        after = client.get(
            f"/properties/{world['property']}/capex-forecast?horizon_years=10&as_of=2026-08-27"
        ).json()
        assert Decimal(after["total_expected"]) < Decimal(before["total_expected"])

    def test_a_repair_leaves_the_inventory_alone(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        order = open_order(client, world)
        result = client.post(
            f"/work-orders/{order['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "repaired",
                "cost": {"amount": "180.00", "is_capital": False},
            },
        ).json()
        assert result["retired_component_id"] is None
        assert result["installed_component_id"] is None
        # Under the de minimis threshold, the safe harbour is the citation.
        assert "1.263(a)-1(f)" in result["capitalisation_citation"]
        event = conn.execute(
            "SELECT category::text AS category FROM ledger_events WHERE event_uuid = %s",
            (result["ledger_event_uuid"],),
        ).fetchone()
        assert event["category"] == "repairs"
        still_live = conn.execute(
            "SELECT retired_on FROM components WHERE id = %s", (world["component"],)
        ).fetchone()
        assert still_live["retired_on"] is None

    def test_a_large_repair_cites_the_routine_maintenance_harbour(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        result = client.post(
            f"/work-orders/{order['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "repaired",
                "cost": {"amount": "4200.00", "is_capital": False},
            },
        ).json()
        assert "1.263(a)-3(i)" in result["capitalisation_citation"]

    def test_no_action_completes_without_money_or_inventory(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        result = client.post(
            f"/work-orders/{order['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "no_action",
                "resolution_note": "no fault found",
            },
        ).json()
        assert result["ledger_event_uuid"] is None
        assert result["capitalisation_citation"] is None
        assert Decimal(result["work_order"]["net_cost"]) == 0

    def test_an_unanswered_bar_question_lands_in_the_classification_queue(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """The owner may not know yet. An unanswered question is recorded as
        unanswered — not guessed — and Schedule E asks for it later
        (Treas. Reg. 1.263(a)-1(f), the de minimis line at $2,500)."""
        order = open_order(client, world)
        result = client.post(
            f"/work-orders/{order['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "repaired",
                "cost": {"amount": "3000.00", "memo": "compressor work"},
            },
        ).json()
        assert result["capitalisation_citation"] is None
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        assert any(
            "compressor work" in (row["memo"] or "") for row in report["needs_classification"]
        )

    def test_capital_spending_must_explain_itself(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "repaired",
                "cost": {"amount": "9000.00", "is_capital": True},
            },
        )
        assert response.status_code == 422
        # The umbrella rule, not the restoration paragraph: nothing in this
        # request says a major component was replaced.
        assert "1.263(a)-3(d)" in response.json()["detail"]
        assert "1.263(a)-3(k)(1)(vi)" not in response.json()["detail"]
        # The refusal rolled the whole completion back.
        assert client.get(f"/work-orders/{order['id']}").json()["status"] == "reported"

    def test_a_replacement_must_name_what_it_replaced(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world, component_id=None)
        response = client.post(
            f"/work-orders/{order['id']}/complete",
            json={"completed_on": "2026-08-27", "resolution": "replaced"},
        )
        assert response.status_code == 422

    def test_a_component_is_retired_once(self, world: dict[str, str], client: TestClient) -> None:
        first = open_order(client, world)
        client.post(
            f"/work-orders/{first['id']}/complete",
            json={"completed_on": "2026-08-27", "resolution": "replaced"},
        )
        second = open_order(client, world, summary="Second bite at the same heater")
        response = client.post(
            f"/work-orders/{second['id']}/complete",
            json={"completed_on": "2026-08-28", "resolution": "replaced"},
        )
        assert response.status_code == 409

    def test_completion_happens_once(self, world: dict[str, str], client: TestClient) -> None:
        order = open_order(client, world)
        assert (
            client.post(
                f"/work-orders/{order['id']}/complete",
                json={"completed_on": "2026-08-27", "resolution": "repaired"},
            ).status_code
            == 201
        )
        response = client.post(
            f"/work-orders/{order['id']}/complete",
            json={"completed_on": "2026-08-28", "resolution": "repaired"},
        )
        assert response.status_code == 409
        assert "already completed" in response.json()["detail"]

    def test_work_cannot_complete_before_it_was_reported(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/complete",
            json={"completed_on": "2026-07-01", "resolution": "repaired"},
        )
        assert response.status_code == 422


class TestCosts:
    def test_costs_accumulate_and_a_reversal_shows(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        client.post(
            f"/work-orders/{order['id']}/costs",
            json={"cost": {"amount": "120.00", "relation": "materials", "is_capital": False}},
        )
        detail = client.post(
            f"/work-orders/{order['id']}/costs",
            json={"cost": {"amount": "300.00", "relation": "invoice", "is_capital": False}},
        ).json()
        assert Decimal(detail["net_cost"]) == Decimal("420.00")
        # A mis-posted invoice is corrected by a reversal PAIR. The reversal is
        # its own ledger event and is NOT associated with the job, so the net
        # has to reach for it — otherwise the page reports money the job never
        # cost. The reversed row stays visible; only the total moves.
        client.post(f"/ledger/{detail['costs'][1]['ledger_event_uuid']}/reverse", json={})
        after = client.get(f"/work-orders/{order['id']}").json()
        assert any(cost["reversed"] for cost in after["costs"])
        assert len(after["costs"]) == 2  # the pair is not hidden
        assert Decimal(after["net_cost"]) == Decimal("120.00")

    def test_an_existing_ledger_event_can_join_the_job(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        event = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-02",
                "category": "repairs",
                "amount": "-95.00",
                "property_id": world["property"],
                "memo": "parts run",
            },
        ).json()
        detail = client.post(
            f"/work-orders/{order['id']}/costs",
            json={"ledger_event_uuid": event["event_uuid"], "relation": "materials"},
        ).json()
        assert Decimal(detail["net_cost"]) == Decimal("95.00")
        # Linking the same event twice is a no-op, not a 500.
        again = client.post(
            f"/work-orders/{order['id']}/costs",
            json={"ledger_event_uuid": event["event_uuid"], "relation": "materials"},
        ).json()
        assert len(again["costs"]) == 1

    def test_a_cost_from_another_property_is_refused(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        entity = client.post("/entities", json={"name": "Third", "kind": "llc"}).json()
        other = client.post(
            "/properties",
            json={
                "entity_id": entity["id"],
                "label": "Other Books",
                "street_1": "3 Other St",
                "city": "Newport",
                "state": "KY",
                "postal_code": "41071",
                "kind": "single_family",
            },
        ).json()
        event = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-02",
                "category": "repairs",
                "amount": "-95.00",
                "property_id": other["id"],
            },
        ).json()
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/costs",
            json={"ledger_event_uuid": event["event_uuid"]},
        )
        assert response.status_code == 422

    def test_cost_guards(self, world: dict[str, str], client: TestClient) -> None:
        order = open_order(client, world)
        assert (
            client.post(
                f"/work-orders/{order['id']}/costs",
                json={"ledger_event_uuid": "00000000-0000-4000-8000-000000000000"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/work-orders/00000000-0000-4000-8000-000000000000/costs",
                json={"cost": {"amount": "10.00"}},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/work-orders/{order['id']}/costs",
                json={"cost": {"amount": "10.00", "is_capital": True}},
            ).status_code
            == 422
        )

    def test_a_cost_may_cite_only_a_receipt_that_exists(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The document behind the money is attached at INSERT, because the
        ledger refuses UPDATE forever after. A document_id naming nothing is a
        404 -- not a psycopg error at the client, and not a pydantic one
        either: the ledger's model wants text and a bare UUID never reached it."""
        document = conn.execute(
            """
            INSERT INTO source_documents (kind, filename, content_hash, status)
            VALUES ('invoice', 'licking-valley-8842.pdf', %s, 'confirmed')
            RETURNING id::text
            """,
            ("d" * 64,),
        ).fetchone()
        conn.commit()
        order = open_order(client, world)
        ghost = client.post(
            f"/work-orders/{order['id']}/costs",
            json={
                "cost": {
                    "amount": "300.00",
                    "is_capital": False,
                    "document_id": "00000000-0000-4000-8000-000000000000",
                },
            },
        )
        assert ghost.status_code == 404
        assert ghost.json()["detail"] == "document not found"
        assert client.get(f"/work-orders/{order['id']}").json()["costs"] == []

        posted = client.post(
            f"/work-orders/{order['id']}/costs",
            json={
                "cost": {
                    "amount": "300.00",
                    "is_capital": False,
                    "document_id": document["id"],
                },
            },
        )
        assert posted.status_code == 201, posted.text
        event_uuid = posted.json()["costs"][0]["ledger_event_uuid"]
        stored = conn.execute(
            "SELECT document_id::text FROM ledger_events WHERE event_uuid = %s",
            (event_uuid,),
        ).fetchone()
        assert stored["document_id"] == document["id"]

        # The completion door posts its money through the same helper.
        second = open_order(client, world)
        refused = client.post(
            f"/work-orders/{second['id']}/complete",
            json={
                "completed_on": "2026-08-27",
                "resolution": "repaired",
                "cost": {
                    "amount": "300.00",
                    "is_capital": False,
                    "document_id": "00000000-0000-4000-8000-000000000000",
                },
            },
        )
        assert refused.status_code == 404
        assert refused.json()["detail"] == "document not found"
        # The refusal rolled the half-written completion back with it.
        assert client.get(f"/work-orders/{second['id']}").json()["status"] == "reported"


class TestEdgeValidation:
    """Malformed input is a 422 at the edge, never a 500 in SQL."""

    def test_a_malformed_id_is_refused_before_it_reaches_postgres(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        assert (
            client.post(
                "/work-orders",
                json={"property_id": "not-a-uuid", "summary": "No hot water"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/vendors",
                json={"entity_id": "not-a-uuid", "name": "Ghost", "trade": "other"},
            ).status_code
            == 422
        )
        order = open_order(client, world)
        assert (
            client.post(
                f"/work-orders/{order['id']}/transitions",
                json={"status": "triaged", "vendor_id": "not-a-uuid"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/work-orders/{order['id']}/costs",
                json={"ledger_event_uuid": "not-a-uuid"},
            ).status_code
            == 422
        )

    def test_a_replacement_cannot_overflow_the_component_columns(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """components.quantity is NUMERIC(10,2) and expected_life_years is
        NUMERIC(5,2); unbounded Decimals overflowed the column as a 500."""
        order = open_order(client, world)
        for field, value in (
            ("quantity", "99999999999.00"),
            ("expected_life_years", "9999.00"),
            ("replacement_cost", "9" * 17 + ".00"),
        ):
            response = client.post(
                f"/work-orders/{order['id']}/complete",
                json={
                    "completed_on": "2026-08-27",
                    "resolution": "replaced",
                    "replacement": {field: value},
                },
            )
            assert response.status_code == 422, f"{field}={value} -> {response.status_code}"
        # The refusals rolled back: the job is still open and still completable.
        assert client.get(f"/work-orders/{order['id']}").json()["status"] == "reported"


class TestRenewalAndRefusals:
    def test_a_certificate_can_be_renewed_without_inventing_a_second_vendor(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """Certificates expire yearly. Without this there was no door: the
        unique name per entity made re-adding the vendor impossible."""
        lapsed = client.post(
            "/vendors",
            json={
                "entity_id": world["entity"],
                "name": "Lapsed Then Renewed",
                "trade": "roofing",
                "liability_expires_on": "2026-01-31",
            },
        ).json()
        assert lapsed["coverage_state"] == "expired"
        renewed = client.post(
            f"/vendors/{lapsed['id']}/credentials",
            json={"liability_expires_on": "2028-01-31", "insurer": "Second Carrier"},
        )
        assert renewed.status_code == 200, renewed.text
        body = renewed.json()
        assert body["coverage_state"] == "current"
        assert body["insurer"] == "Second Carrier"
        # Untouched fields stay put: a renewal names what was renewed.
        assert body["name"] == "Lapsed Then Renewed"
        assert body["trade"] == "roofing"

    def test_renewal_guards(self, world: dict[str, str], client: TestClient) -> None:
        assert (
            client.post(
                "/vendors/00000000-0000-4000-8000-000000000000/credentials",
                json={"insurer": "Nobody"},
            ).status_code
            == 404
        )
        assert client.post(f"/vendors/{world['vendor']}/credentials", json={}).status_code == 422

    def test_a_cost_body_may_not_carry_two_relations(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """The outer relation describes a LINK to an existing event; a posted
        cost carries its own. Setting both said two things about one row and
        silently kept one."""
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/costs",
            json={
                "cost": {"amount": "50.00", "relation": "materials"},
                "relation": "invoice",
            },
        )
        assert response.status_code == 422
        # Either one alone is fine.
        assert (
            client.post(
                f"/work-orders/{order['id']}/costs",
                json={"cost": {"amount": "50.00", "relation": "materials"}},
            ).status_code
            == 201
        )

    def test_the_inventory_refuses_a_completion_by_name(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """A replacement dated before the component it retires trips
        retired_after_installed, which used to escape as a 500."""
        conn.execute(
            "UPDATE components SET installed_on = '2026-09-01' WHERE id = %s",
            (world["component"],),
        )
        conn.commit()
        order = open_order(client, world)
        response = client.post(
            f"/work-orders/{order['id']}/complete",
            json={"completed_on": "2026-08-27", "resolution": "replaced"},
        )
        assert response.status_code == 422
        assert "cannot retire before it was installed" in response.json()["detail"]


class TestCredits:
    def test_a_tenant_chargeback_is_income_and_reduces_what_the_job_cost(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """A resident reimbursing damage is money coming IN. Posting it as an
        outflow would overstate the job and understate rental income."""
        order = open_order(client, world)
        client.post(
            f"/work-orders/{order['id']}/costs",
            json={"cost": {"amount": "400.00", "relation": "invoice", "is_capital": False}},
        )
        detail = client.post(
            f"/work-orders/{order['id']}/costs",
            json={"cost": {"amount": "150.00", "relation": "tenant_chargeback"}},
        ).json()
        assert Decimal(detail["net_cost"]) == Decimal("250.00")
        chargeback = next(
            cost for cost in detail["costs"] if cost["relation"] == "tenant_chargeback"
        )
        assert Decimal(chargeback["amount"]) == Decimal("150.00")  # positive: money in
        assert chargeback["category"] == "other_income"

    def test_a_warranty_credit_comes_back_against_the_repair(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        client.post(
            f"/work-orders/{order['id']}/costs",
            json={"cost": {"amount": "900.00", "relation": "invoice", "is_capital": False}},
        )
        detail = client.post(
            f"/work-orders/{order['id']}/costs",
            json={"cost": {"amount": "300.00", "relation": "warranty_credit"}},
        ).json()
        assert Decimal(detail["net_cost"]) == Decimal("600.00")
        credit = next(cost for cost in detail["costs"] if cost["relation"] == "warranty_credit")
        assert credit["category"] == "repairs"  # a negative expense, honestly signed
        assert credit["is_capital"] is False

    def test_a_credit_is_never_a_capital_election_however_it_is_asked_for(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        order = open_order(client, world)
        detail = client.post(
            f"/work-orders/{order['id']}/costs",
            json={
                "cost": {
                    "amount": "300.00",
                    "relation": "warranty_credit",
                    "is_capital": True,
                    "capitalisation_rationale": "nonsense",
                }
            },
        ).json()
        assert detail["costs"][0]["is_capital"] is False


class TestPureHelpers:
    def test_the_transition_message_names_a_terminal_state_honestly(self) -> None:
        error = maintenance.IllegalTransition("completed", "triaged")
        assert "nothing (terminal)" in str(error)
