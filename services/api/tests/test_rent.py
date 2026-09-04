"""Leases, the rent sweep, receipts with allocation, late fees as law."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def world(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "L4", "kind": "llc"}).json()["id"]
    property_id = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "998 Monmouth",
            "street_1": "998 Monmouth St",
            "city": "Newport",
            "state": "KY",
            "postal_code": "41071",
            "kind": "single_family",
        },
    ).json()["id"]
    unit_id = client.post(
        "/units",
        json={"property_id": property_id, "label": "A", "market_rent": "1550.00"},
    ).json()["id"]
    resident_id = client.post(
        "/residents", json={"full_name": "Jordan Tenant", "email": "jordan@example.com"}
    ).json()["id"]
    lease_id = client.post(
        "/leases",
        json={
            "unit_id": unit_id,
            "starts_on": "2025-04-01",
            "ends_on": "2027-03-31",
            "rent": "1450.00",
            "rent_due_day": 1,
            "security_deposit": "1450.00",
            "resident_ids": [resident_id],
        },
    ).json()["id"]
    return {
        "entity": entity_id,
        "property": property_id,
        "unit": unit_id,
        "resident": resident_id,
        "lease": lease_id,
    }


class TestLeaseCrud:
    def test_create_list_detail(self, world: dict[str, str], client: TestClient) -> None:
        (summary,) = client.get("/leases").json()
        assert summary["property_label"] == "998 Monmouth"
        assert summary["residents"] == ["Jordan Tenant"]
        assert Decimal(summary["balance_due"]) == 0
        detail = client.get(f"/leases/{world['lease']}").json()
        assert detail["rent"] == "1450.00"
        assert detail["security_deposit"] == "1450.00"
        assert detail["charges"] == []

    def test_overlapping_lease_is_a_conflict(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        response = client.post(
            "/leases",
            json={
                "unit_id": world["unit"],
                "starts_on": "2026-01-01",
                "rent": "1500.00",
                "status": "active",
            },
        )
        assert response.status_code == 409
        assert "live lease" in response.json()["detail"]

    def test_missing_anchors_404_and_422(self, world: dict[str, str], client: TestClient) -> None:
        assert client.get(f"/leases/{uuid.uuid4()}").status_code == 404
        ghost_unit = client.post("/units", json={"property_id": str(uuid.uuid4()), "label": "X"})
        assert ghost_unit.status_code == 422
        assert "property" in ghost_unit.json()["detail"]
        bad = client.post(
            "/leases",
            json={"unit_id": str(uuid.uuid4()), "starts_on": "2026-01-01", "rent": "1.00"},
        )
        assert bad.status_code == 422


class TestRentSweep:
    def test_monthly_charge_idempotent(self, world: dict[str, str], client: TestClient) -> None:
        first = client.post("/sweep/rent-charges?as_of=2026-09-03").json()
        assert first == {"charges_created": 1, "gaps": []}
        again = client.post("/sweep/rent-charges?as_of=2026-09-20").json()
        assert again["charges_created"] == 0
        detail = client.get(f"/leases/{world['lease']}").json()
        (charge,) = detail["charges"]
        assert charge["period_start"] == "2026-09-01"
        assert charge["due_on"] == "2026-09-01"
        assert Decimal(charge["amount"]) == Decimal("1450.00")
        assert Decimal(detail["balance_due"]) == Decimal("1450.00")

    def test_percent_form_escalation_is_refused_with_the_unit_spelled_out(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # The issue #104 confusion: 3.5 meant as 3.5% is a 350% annual
        # increase through (1 + value) ** years. The API answers 422 with
        # the unit in the message, before the schema CHECK ever sees it.
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U104"}
        ).json()["id"]
        refused = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2026-01-01",
                "rent": "1450.00",
                "escalation": "fixed_percent",
                "escalation_value": "3.5",
            },
        )
        assert refused.status_code == 422
        assert "0.035" in refused.text and "350%" in refused.text
        negative = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2026-01-01",
                "rent": "1450.00",
                "escalation": "fixed_amount",
                "escalation_value": "-25.00",
            },
        )
        assert negative.status_code == 422
        assert "non-negative dollars" in negative.text
        # The correctly-united forms both pass this validator (the fixtures
        # in test_escalations_and_cpi_gap create them for real).
        ok = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2026-01-01",
                "rent": "1450.00",
                "escalation": "fixed_percent",
                "escalation_value": "0.035",
            },
        )
        assert ok.status_code == 201

    def test_due_on_is_a_day_of_the_month_not_day_arithmetic(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # Issue #103: with rent_due_day = 31 the old arithmetic put
        # February's due date on March 3 — outside its own period, feeding
        # wrong late fees and a wrong ageing bucket. "The 31st" means the
        # month's last day where no 31st exists.
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U103"}
        ).json()["id"]
        lease = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2026-01-01",
                "rent": "1200.00",
                "rent_due_day": 31,
            },
        )
        assert lease.status_code == 201, lease.text
        lease_id = lease.json()["id"]
        for as_of in ["2026-01-01", "2026-02-01", "2026-09-01", "2028-02-01"]:
            client.post(f"/sweep/rent-charges?as_of={as_of}")
        charges = client.get(f"/leases/{lease_id}").json()["charges"]
        by_period = {c["period_start"]: c["due_on"] for c in charges}
        assert by_period["2026-01-01"] == "2026-01-31"
        assert by_period["2026-02-01"] == "2026-02-28"
        assert by_period["2026-09-01"] == "2026-09-30"
        assert by_period["2028-02-01"] == "2028-02-29"
        # Every due date sits inside its own period — the defect's signature
        # was a due date in the following month.
        for period, due in by_period.items():
            assert due[:7] == period[:7]

    def test_escalation_waits_for_the_anniversary_date_not_its_month(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # Issue #102's table: a 2024-03-15 lease used to bill the WHOLE of
        # March 2025 escalated — fourteen days early. The convention (posted
        # on the ticket): the first escalated charge is the first period
        # starting on or after the anniversary date.
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U102a"}
        ).json()["id"]
        lease_id = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2024-03-15",
                "rent": "1000.00",
                "escalation": "fixed_percent",
                "escalation_value": "0.05",
            },
        ).json()["id"]
        for as_of in ["2025-03-01", "2025-04-01", "2026-03-01", "2026-04-01"]:
            client.post(f"/sweep/rent-charges?as_of={as_of}")
        by_period = {
            c["period_start"]: Decimal(c["amount"])
            for c in client.get(f"/leases/{lease_id}").json()["charges"]
        }
        assert by_period["2025-03-01"] == Decimal("1000.00")  # old rate to the date
        assert by_period["2025-04-01"] == Decimal("1050.00")  # first full period after
        assert by_period["2026-03-01"] == Decimal("1050.00")
        assert by_period["2026-04-01"] == Decimal("1102.50")  # compounded year two

    def test_a_december_31_lease_no_longer_escalates_thirty_days_early(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U102b"}
        ).json()["id"]
        lease_id = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2024-12-31",
                "rent": "2000.00",
                "escalation": "fixed_amount",
                "escalation_value": "100.00",
            },
        ).json()["id"]
        for as_of in ["2025-12-01", "2026-01-01"]:
            client.post(f"/sweep/rent-charges?as_of={as_of}")
        by_period = {
            c["period_start"]: Decimal(c["amount"])
            for c in client.get(f"/leases/{lease_id}").json()["charges"]
        }
        # December 2025 spans the anniversary but STARTS before it: old rate.
        assert by_period["2025-12-01"] == Decimal("2000.00")
        assert by_period["2026-01-01"] == Decimal("2100.00")

    def test_a_leap_day_lease_escalates_from_the_clamped_anniversary(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U102c"}
        ).json()["id"]
        lease_id = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2024-02-29",
                "rent": "1000.00",
                "escalation": "fixed_percent",
                "escalation_value": "0.03",
            },
        ).json()["id"]
        for as_of in ["2025-02-01", "2025-03-01"]:
            client.post(f"/sweep/rent-charges?as_of={as_of}")
        by_period = {
            c["period_start"]: Decimal(c["amount"])
            for c in client.get(f"/leases/{lease_id}").json()["charges"]
        }
        assert by_period["2025-02-01"] == Decimal("1000.00")
        assert by_period["2025-03-01"] == Decimal("1030.00")

    def test_the_stub_first_month_bills_prorated_instead_of_never(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # Issue #102's second defect: a mid-month lease was invisible to its
        # own first sweep and the stub month was never billed at all.
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U102d"}
        ).json()["id"]
        lease_id = client.post(
            "/leases",
            json={"unit_id": unit, "starts_on": "2026-03-15", "rent": "3100.00"},
        ).json()["id"]
        client.post("/sweep/rent-charges?as_of=2026-03-01")
        client.post("/sweep/rent-charges?as_of=2026-03-01")
        # Exactly one charge for THIS lease after two sweeps: the stub month
        # billed once, idempotent under its deterministic stub key. (The
        # sweep total also counts the world fixture's own lease.)
        (charge,) = client.get(f"/leases/{lease_id}").json()["charges"]
        assert charge["period_start"] == "2026-03-15"
        # 17 of March's 31 days at 3100.00: exactly 1700.00.
        assert Decimal(charge["amount"]) == Decimal("1700.00")
        # Rent for a mid-month start is not due before the lease exists.
        assert charge["due_on"] == "2026-03-15"

    def test_the_final_month_bills_prorated_instead_of_in_full(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # The third defect, found in this pass: ends_on >= period_start swept
        # a lease ending April 10 into April and billed the FULL month.
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U102e"}
        ).json()["id"]
        lease_id = client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2026-01-01",
                "ends_on": "2026-04-10",
                "rent": "3000.00",
            },
        ).json()["id"]
        client.post("/sweep/rent-charges?as_of=2026-04-01")
        client.post("/sweep/rent-charges?as_of=2026-05-01")
        charges = client.get(f"/leases/{lease_id}").json()["charges"]
        by_period = {c["period_start"]: c for c in charges}
        april = by_period["2026-04-01"]
        # 10 of April's 30 days at 3000.00: exactly 1000.00.
        assert Decimal(april["amount"]) == Decimal("1000.00")
        assert "2026-05-01" not in by_period  # May is past the lease

    def test_a_sub_cent_stub_share_is_a_gap_not_a_sweep_abort(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # Adversarial-panel finding on this change: a peppercorn rent whose
        # one-day stub share rounds to 0.00 would violate the amount > 0
        # CHECK and roll back EVERY lease's charge for the month. It must
        # be a reported gap instead, with the other leases still billed.
        unit = client.post(
            "/units", json={"property_id": world["property"], "label": "U102f"}
        ).json()["id"]
        client.post(
            "/leases",
            json={
                "unit_id": unit,
                "starts_on": "2026-01-31",
                "ends_on": "2026-03-01",
                "rent": "0.10",
            },
        )
        result = client.post("/sweep/rent-charges?as_of=2026-01-15").json()
        assert result["charges_created"] >= 1  # the world lease still billed
        (gap,) = [g for g in result["gaps"] if g["reason"] == "amount_rounds_to_zero"]
        assert "rounds to zero" in gap["detail"]

    def test_escalations_and_cpi_gap(self, world: dict[str, str], client: TestClient) -> None:
        # A second unit with each escalation shape.
        unit2 = client.post("/units", json={"property_id": world["property"], "label": "B"}).json()[
            "id"
        ]
        pct = client.post(
            "/leases",
            json={
                "unit_id": unit2,
                "starts_on": "2024-09-01",
                "rent": "1000.00",
                "escalation": "fixed_percent",
                "escalation_value": "0.03",
            },
        ).json()["id"]
        unit3 = client.post("/units", json={"property_id": world["property"], "label": "C"}).json()[
            "id"
        ]
        client.post(
            "/leases",
            json={
                "unit_id": unit3,
                "starts_on": "2025-03-01",
                "rent": "900.00",
                "escalation": "fixed_amount",
                "escalation_value": "25.00",
            },
        )

        # CPI leases cannot be created through the API shape; plant directly.
        # (The API restricts to the shapes the sweep can honor.)
        result = client.post("/sweep/rent-charges?as_of=2026-09-01").json()
        assert result["charges_created"] == 3  # A, B, C
        leases = {entry["unit_label"]: entry for entry in client.get("/leases").json()}
        b_detail = client.get(f"/leases/{pct}").json()
        (b_charge,) = b_detail["charges"]
        # Two full years elapsed on a 3% compounder: 1000 * 1.03^2 = 1060.90.
        assert Decimal(b_charge["amount"]) == Decimal("1060.90")
        c_detail = client.get(f"/leases/{leases['C']['id']}").json()
        (c_charge,) = c_detail["charges"]
        # One full year on a $25 step: 925.
        assert Decimal(c_charge["amount"]) == Decimal("925.00")

    def test_cpi_lease_reports_a_gap(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        unit = client.post("/units", json={"property_id": world["property"], "label": "E"}).json()[
            "id"
        ]
        conn.execute(
            """
            INSERT INTO leases (unit_id, status, starts_on, rent, escalation, escalation_value)
            VALUES (%s, 'active', '2025-01-01', 800.00, 'cpi', 0.02)
            """,
            (unit,),
        )
        conn.commit()
        result = client.post("/sweep/rent-charges?as_of=2026-09-01").json()
        (gap,) = [g for g in result["gaps"] if g["reason"] == "cpi_index_unavailable"]
        assert "index series" in gap["detail"]


class TestReceipts:
    def test_receipt_allocates_oldest_first_and_updates_status(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post("/sweep/rent-charges?as_of=2026-09-01")
        receipt = client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-09-02", "amount": "2000.00", "memo": "catch-up"},
        )
        assert receipt.status_code == 201
        body = receipt.json()
        assert len(body["allocations"]) == 2
        assert Decimal(body["unallocated"]) == 0
        detail = client.get(f"/leases/{world['lease']}").json()
        by_period = {c["period_start"]: c for c in detail["charges"]}
        assert by_period["2026-08-01"]["status"] == "paid"
        assert by_period["2026-09-01"]["status"] == "partially_paid"
        assert Decimal(by_period["2026-09-01"]["outstanding"]) == Decimal("900.00")
        assert Decimal(detail["balance_due"]) == Decimal("900.00")

    def test_a_small_receipt_stops_at_the_oldest_charge(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post("/sweep/rent-charges?as_of=2026-09-01")
        receipt = client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-09-01", "amount": "1450.00"},
        ).json()
        # Exactly the oldest charge: the loop reaches September and stops.
        assert len(receipt["allocations"]) == 1
        detail = client.get(f"/leases/{world['lease']}").json()
        by_period = {c["period_start"]: c for c in detail["charges"]}
        assert by_period["2026-08-01"]["status"] == "paid"
        assert by_period["2026-09-01"]["status"] == "due"

    def test_overpayment_stays_visible_and_deposits_skip_allocation(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        over = client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "1500.00"},
        ).json()
        assert Decimal(over["unallocated"]) == Decimal("50.00")
        deposit = client.post(
            f"/leases/{world['lease']}/receipts",
            json={
                "occurred_on": "2026-08-01",
                "amount": "1450.00",
                "category": "deposit_received",
                "memo": "security deposit",
            },
        ).json()
        assert deposit["allocations"] == []
        row = conn.execute(
            "SELECT category::text FROM ledger_events WHERE event_uuid = %s",
            (deposit["event_uuid"],),
        ).fetchone()
        assert row is not None and row["category"] == "deposit_received"

    def test_waive_requires_a_reason_and_a_waivable_charge(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        detail = client.get(f"/leases/{world['lease']}").json()
        (charge,) = detail["charges"]
        assert (
            client.post(
                f"/rent-charges/{charge['id']}/waive", json={"reason": "storm damage credit"}
            ).status_code
            == 204
        )
        after = client.get(f"/leases/{world['lease']}").json()
        assert after["charges"][0]["status"] == "waived"
        assert Decimal(after["balance_due"]) == 0
        assert (
            client.post(f"/rent-charges/{charge['id']}/waive", json={"reason": "again"}).status_code
            == 404
        )


class TestLateFees:
    def test_no_rule_means_a_gap_never_a_default(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        result = client.post("/sweep/late-fees?as_of=2026-08-20").json()
        assert result["charges_created"] == 0
        # Ledger-pinned leases from earlier tests survive the clean, so scope
        # to this test's own lease rather than counting globally.
        (gap,) = [g for g in result["gaps"] if g["lease_id"] == world["lease"]]
        assert gap["reason"] == "no_late_fee_rule"
        assert "KY chain" in gap["detail"]

    def test_a_cited_rule_assesses_the_fee_idempotently(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        exists = conn.execute(
            """
            SELECT 1 AS x FROM jurisdiction_rules r
            JOIN jurisdictions j ON j.id = r.jurisdiction_id
            WHERE j.state = 'KY' AND j.level = 'state' AND r.code = 'latefee.grace_days'
            """
        ).fetchone()
        if exists is None:  # append-only rules: once per module session
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, citation, effective_from)
                SELECT id, 'late_fee', 'latefee.grace_days', 5,
                       'Test Ordinance 1.1 (fixture)', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'KY' AND level = 'state'
                """
            )
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, citation, effective_from)
                SELECT id, 'late_fee', 'latefee.percent', 0.05,
                       'Test Ordinance 1.2 (fixture)', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'KY' AND level = 'state'
                """
            )
            conn.commit()
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        # Inside the grace window: nothing happens.
        inside = client.post("/sweep/late-fees?as_of=2026-08-04").json()
        assert inside == {"charges_created": 0, "gaps": []}
        assessed = client.post("/sweep/late-fees?as_of=2026-08-20").json()
        assert assessed["charges_created"] >= 1  # ours, plus any pinned survivors
        again = client.post("/sweep/late-fees?as_of=2026-08-25").json()
        assert again["charges_created"] == 0
        detail = client.get(f"/leases/{world['lease']}").json()
        fee = next(c for c in detail["charges"] if c["kind"] == "late_fee")
        assert Decimal(fee["amount"]) == Decimal("72.50")  # 5% of 1450
        assert "Test Ordinance" in fee["rule_citation"]
        # A paid charge draws no fee next month.
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-21", "amount": "1522.50"},
        )
        after_paid = client.post("/sweep/late-fees?as_of=2026-08-30").json()
        assert after_paid["charges_created"] == 0

    def test_a_flat_amount_rule_beats_the_percent(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        exists = conn.execute("SELECT 1 AS x FROM jurisdictions WHERE state = 'QZ'").fetchone()
        if exists is None:
            conn.execute(
                """
                INSERT INTO jurisdictions (level, name, state, parent_id)
                SELECT 'state', 'Quozland', 'QZ', id FROM jurisdictions
                WHERE level = 'federal'
                """
            )
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, value_money, citation,
                   effective_from)
                SELECT id, 'late_fee', 'latefee.grace_days', 3, NULL,
                       'QZ Stat. 9.1 (fixture)', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'QZ' AND level = 'state'
                """
            )
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, value_money, citation,
                   effective_from)
                SELECT id, 'late_fee', 'latefee.amount', NULL, 35.00,
                       'QZ Stat. 9.2 (fixture): flat $35', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'QZ' AND level = 'state'
                """
            )
            conn.commit()
        property_id = client.post(
            "/properties",
            json={
                "entity_id": world["entity"],
                "label": "qz-house",
                "street_1": "1 Flat Fee Ln",
                "city": "Quozton",
                "state": "QZ",
                "postal_code": "00000",
                "kind": "single_family",
            },
        ).json()["id"]
        unit_id = client.post("/units", json={"property_id": property_id, "label": "A"}).json()[
            "id"
        ]
        lease_id = client.post(
            "/leases",
            json={"unit_id": unit_id, "starts_on": "2026-01-01", "rent": "1000.00"},
        ).json()["id"]
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post("/sweep/late-fees?as_of=2026-08-20")
        detail = client.get(f"/leases/{lease_id}").json()
        fee = next(c for c in detail["charges"] if c["kind"] == "late_fee")
        assert Decimal(fee["amount"]) == Decimal("35.00")
        assert "flat $35" in fee["rule_citation"]


class TestPaidMoneyDrawsNoFee:
    def _qy_world(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> str:
        """A synthetic QY state with grace 3 + flat $20, its own property and
        lease at 1000/mo — self-contained so test order cannot matter."""
        exists = conn.execute("SELECT 1 AS x FROM jurisdictions WHERE state = 'QY'").fetchone()
        if exists is None:
            conn.execute(
                """
                INSERT INTO jurisdictions (level, name, state, parent_id)
                SELECT 'state', 'Quyland', 'QY', id FROM jurisdictions
                WHERE level = 'federal'
                """
            )
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, value_money, citation,
                   effective_from)
                SELECT id, 'late_fee', 'latefee.grace_days', 3, NULL,
                       'QY Stat. 1.1 (fixture)', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'QY' AND level = 'state'
                """
            )
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, value_money, citation,
                   effective_from)
                SELECT id, 'late_fee', 'latefee.amount', NULL, 20.00,
                       'QY Stat. 1.2 (fixture): flat $20', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'QY' AND level = 'state'
                """
            )
            conn.commit()
        property_id = client.post(
            "/properties",
            json={
                "entity_id": world["entity"],
                "label": "qy-house",
                "street_1": "1 Paid Up Pl",
                "city": "Quyton",
                "state": "QY",
                "postal_code": "00000",
                "kind": "single_family",
            },
        ).json()["id"]
        unit_id = client.post("/units", json={"property_id": property_id, "label": "A"}).json()[
            "id"
        ]
        return client.post(
            "/leases",
            json={"unit_id": unit_id, "starts_on": "2026-01-01", "rent": "1000.00"},
        ).json()["id"]

    def test_a_check_through_the_ledger_door_draws_no_fee(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        # Issue #138: the owner records the tenant's on-time check via
        # POST /ledger (which allocates nothing); the late-fee sweep used to
        # take its overdue snapshot BEFORE applying that credit and fined a
        # tenant whose money had been on account since the due date.
        lease_id = self._qy_world(world, client, conn)
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        posted = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "1000.00",
                "lease_id": lease_id,
                "memo": "tenant check, recorded by hand",
            },
        )
        assert posted.status_code == 201, posted.text
        # The world fixture's lease is overdue too — pay it the same way, so
        # the sweep's second snapshot is EMPTY and the everyone-is-cured
        # early return is the path actually exercised.
        client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "1450.00",
                "lease_id": world["lease"],
            },
        )
        swept = client.post("/sweep/late-fees?as_of=2026-08-20").json()
        assert swept == {"charges_created": 0, "gaps": []}
        detail = client.get(f"/leases/{lease_id}").json()
        assert [c["kind"] for c in detail["charges"]] == ["rent"]
        (rent_charge,) = detail["charges"]
        assert rent_charge["status"] == "paid"
        assert Decimal(detail["balance_due"]) == Decimal("0.00")

    def test_credit_covering_one_of_two_months_fines_only_the_unpaid_one(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        lease_id = self._qy_world(world, client, conn)
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post("/sweep/rent-charges?as_of=2026-09-01")
        client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "1000.00",
                "lease_id": lease_id,
            },
        )
        client.post("/sweep/late-fees?as_of=2026-09-20")
        charges = client.get(f"/leases/{lease_id}").json()["charges"]
        fees = [c for c in charges if c["kind"] == "late_fee"]
        # August was covered by the credit (oldest first); only September's
        # genuinely unpaid month draws its flat fee.
        assert len(fees) == 1
        assert Decimal(fees[0]["amount"]) == Decimal("20.00")
        paid_aug = next(c for c in charges if c["period_start"] == "2026-08-01")
        assert paid_aug["status"] == "paid"

    def test_credit_landing_after_the_charge_is_applied_by_the_next_rent_sweep(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        # The rowcount gate: a re-swept month created no charge, so credit
        # that arrived in between was never applied until something else
        # touched the lease. The apply is now unconditional per sweep.
        lease_id = self._qy_world(world, client, conn)
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-02",
                "category": "rent",
                "amount": "1000.00",
                "lease_id": lease_id,
            },
        )
        client.post("/sweep/rent-charges?as_of=2026-08-01")  # same month, 0 created
        detail = client.get(f"/leases/{lease_id}").json()
        (rent_charge,) = detail["charges"]
        assert rent_charge["status"] == "paid"
        assert Decimal(detail["open_credit"]) == Decimal("0.00")


class TestWaiverConvention:
    def test_waive_forgives_the_unpaid_remainder_and_paid_money_stays(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        # The convention this test PINS (issue #137): waiving a partially
        # paid charge forgives only the unpaid remainder; the paid portion
        # remains payment for the waived charge and is NOT released back to
        # open credit. An adversarial reviewer hand-running the queries once
        # concluded the paid money had vanished — these exact figures are
        # the proof it did not, and changing this convention must break
        # this test on purpose.
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-02", "amount": "500.00"},
        )
        detail = client.get(f"/leases/{world['lease']}").json()
        charge_a = next(c for c in detail["charges"] if c["period_start"] == "2026-08-01")
        assert charge_a["status"] == "partially_paid"
        waived = client.post(f"/rent-charges/{charge_a['id']}/waive", json={"reason": "goodwill"})
        assert waived.status_code == 204
        client.post("/sweep/rent-charges?as_of=2026-09-01")
        detail = client.get(f"/leases/{world['lease']}").json()
        # 500 paid (stays), 950 forgiven, September's 1450 owed — no money
        # vanished and none came back.
        assert Decimal(detail["balance_due"]) == Decimal("1450.00")
        assert Decimal(detail["open_credit"]) == Decimal("0.00")
        waived_charge = next(c for c in detail["charges"] if c["period_start"] == "2026-08-01")
        assert waived_charge["status"] == "waived"
        assert Decimal(waived_charge["allocated"]) == Decimal("500.00")

    def test_a_fully_paid_charge_has_nothing_to_forgive(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-02", "amount": "1450.00"},
        )
        detail = client.get(f"/leases/{world['lease']}").json()
        (charge,) = detail["charges"]
        assert charge["status"] == "paid"
        refused = client.post(f"/rent-charges/{charge['id']}/waive", json={"reason": "goodwill"})
        assert refused.status_code == 404


class TestRenewals:
    def test_context_carries_labeled_defaults_then_measured_history(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        context = client.get(f"/leases/{world['lease']}/renewal-context").json()
        assert Decimal(context["current_rent"]) == Decimal("1450.00")
        assert Decimal(context["market_rent"]) == Decimal("1550.00")
        assert context["vacancy_days"] == 21
        assert "defaults" in context["assumptions_source"]
        # Record a refused renewal with its measured turn; the context sharpens.
        renewal = client.post(
            f"/leases/{world['lease']}/renewals",
            json={"offered_on": "2026-09-01", "offered_rent": "1500.00"},
        )
        assert renewal.status_code == 201
        conn.execute(
            """
            UPDATE lease_renewals SET accepted = FALSE, vacancy_days = 34, turn_cost = 2100.00
            WHERE id = %s
            """,
            (renewal.json()["id"],),
        )
        conn.commit()
        measured = client.get(f"/leases/{world['lease']}/renewal-context").json()
        assert Decimal(measured["turn_cost"]) == Decimal("2100.00")
        assert measured["vacancy_days"] == 34
        assert "measured from 1 recorded turn" in measured["assumptions_source"]

    def test_renewal_404s(self, clean: None, client: TestClient) -> None:
        ghost = uuid.uuid4()
        assert client.get(f"/leases/{ghost}/renewal-context").status_code == 404
        assert (
            client.post(
                f"/leases/{ghost}/renewals",
                json={"offered_on": "2026-01-01", "offered_rent": "1.00"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/leases/{ghost}/receipts",
                json={"occurred_on": "2026-01-01", "amount": "1.00"},
            ).status_code
            == 404
        )
