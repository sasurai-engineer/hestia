"""Reports against a lived-in ledger: Schedule E, cash flow, rent roll,
financials, and the capex forecast."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def world(clean: None, client: TestClient, conn: psycopg.Connection[Any]) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "R", "kind": "llc"}).json()["id"]
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
            "year_built": 1962,
        },
    ).json()["id"]
    ids = {"entity": entity_id, "property": property_id}
    entries = [
        # A year of rent, two repair bills (one above de minimis, unanswered),
        # the operating stack, and money that must NOT reach Schedule E.
        ("2026-03-01", "rent", "1450.00", None, None),
        ("2026-04-01", "rent", "1450.00", None, None),
        ("2026-04-15", "late_fee", "50.00", None, None),
        ("2026-05-10", "repairs", "-380.00", None, None),
        ("2026-06-20", "repairs", "-4800.00", None, None),  # needs classification
        ("2026-06-25", "insurance", "-1140.00", None, None),
        ("2026-07-01", "property_tax", "-2210.00", None, None),
        ("2026-07-15", "utilities", "-92.40", None, None),
        ("2026-08-01", "mortgage_interest", "-905.00", None, None),
        ("2026-08-01", "mortgage_principal", "-411.00", None, None),
        (
            "2026-08-05",
            "capital_improvement",
            "-8200.00",
            True,
            "roof replacement: restoration under BAR",
        ),
        ("2026-08-10", "owner_distribution", "-1000.00", None, None),
        ("2026-09-01", "deposit_received", "1450.00", None, None),
    ]
    for occurred_on, category, amount, is_capital, rationale in entries:
        response = client.post(
            "/ledger",
            json={
                "occurred_on": occurred_on,
                "category": category,
                "amount": amount,
                "property_id": property_id,
                "is_capital": is_capital,
                "capitalisation_rationale": rationale,
            },
        )
        assert response.status_code == 201
    return ids


class TestScheduleE:
    def test_the_form_assembles_with_authorities(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        income = {line["line_no"]: line for line in report["income_lines"]}
        assert Decimal(income[3]["amount"]) == Decimal("2950.00")  # rent + late fee
        expenses = {line["line_no"]: line for line in report["expense_lines"]}
        assert Decimal(expenses[9]["amount"]) == Decimal("1140.00")
        assert Decimal(expenses[12]["amount"]) == Decimal("905.00")
        assert Decimal(expenses[14]["amount"]) == Decimal("5180.00")  # both repair rows
        assert Decimal(expenses[16]["amount"]) == Decimal("2210.00")
        assert Decimal(expenses[17]["amount"]) == Decimal("92.40")
        assert "IRC s.163" in expenses[12]["citation"]

        # Money that is real but does not belong on the form is SHOWN.
        excluded = {row["label"]: row for row in report["excluded"]}
        assert any("principal" in label for label in excluded)
        assert any("liability" in label for label in excluded)
        assert any("equity" in label for label in excluded)
        principal = next(row for label, row in excluded.items() if "principal" in label)
        assert Decimal(principal["amount"]) == Decimal("411.00")

        # The unanswered $4,800 repair is flagged with its regulation.
        (flag,) = report["needs_classification"]
        assert Decimal(flag["amount"]) == Decimal("4800.00")
        assert "1.263(a)-1(f)" in flag["reason"]

        assert Decimal(report["total_income"]) == Decimal("2950.00")
        assert Decimal(report["total_expenses"]) == Decimal("9527.40")
        assert report["signoff"] is None
        assert "not tax advice" in report["caveat"]

    def test_line_18_comes_from_the_depreciation_engine(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        conn.execute(
            """
            WITH asset AS (
              INSERT INTO depreciable_assets
                (property_id, book, description, class, method, convention,
                 recovery_years, placed_in_service_on, original_basis)
              VALUES (%s, 'federal', 'building', 'building', 'macrs_gds_sl',
                      'mid_month', 27.5, '2025-06-01', 220000.00)
              RETURNING id
            )
            INSERT INTO depreciation_entries (asset_id, tax_year, amount, accumulated, law_as_of)
            SELECT id, 2026, 8000.00, 12333.33, '2026-01-01' FROM asset
            """,
            (world["property"],),
        )
        conn.commit()
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        assert Decimal(report["depreciation_line_18"]) == Decimal("8000.00")
        assert "dual-book engine" in report["depreciation_citation"]
        assert Decimal(report["net"]) == Decimal("2950.00") - Decimal("9527.40") - Decimal(
            "8000.00"
        )

    def test_signoff_gates_and_conflicts(self, world: dict[str, str], client: TestClient) -> None:
        body = {
            "property_id": world["property"],
            "tax_year": 2026,
            "report_kind": "schedule_e",
            "confirmed_by": "Jane CPA",
            "note": "reviewed against the register",
        }
        assert client.post("/reports/signoff", json=body).status_code == 201
        assert client.post("/reports/signoff", json=body).status_code == 409
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        assert report["signoff"]["confirmed_by"] == "Jane CPA"

    def test_a_reversed_repair_leaves_the_classification_queue(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """A reversal PAIR nets to zero, so it is no longer an open question —
        and the reversal half mirrors a charge rather than being one. Both
        halves leave the queue: asking twice, forever, about money that no
        longer exists is the defect."""
        posted = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-09-12",
                "category": "repairs",
                "amount": "-3600.00",
                "memo": "furnace invoice, mis-posted",
                "property_id": world["property"],
            },
        ).json()
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        assert {Decimal(flag["amount"]) for flag in report["needs_classification"]} == {
            Decimal("4800.00"),
            Decimal("3600.00"),
        }

        reversal = client.post(f"/ledger/{posted['event_uuid']}/reverse", json={})
        assert reversal.status_code == 201
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        flagged = {flag["event_uuid"] for flag in report["needs_classification"]}
        assert posted["event_uuid"] not in flagged
        assert reversal.json()["reversal"]["event_uuid"] not in flagged
        assert [Decimal(flag["amount"]) for flag in report["needs_classification"]] == [
            Decimal("4800.00")
        ]
        # The pair cancels on the form too: line 14 is unmoved by the round trip.
        expenses = {line["line_no"]: line for line in report["expense_lines"]}
        assert Decimal(expenses[14]["amount"]) == Decimal("5180.00")

    def test_a_correction_that_is_still_unanswered_stays_in_the_queue(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """Dropping settled pairs must not swallow a live question: the
        corrected entry is its own charge and is judged on its own merits."""
        posted = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-09-12",
                "category": "repairs",
                "amount": "-5100.00",
                "memo": "porch rebuild invoice",
                "property_id": world["property"],
            },
        ).json()
        result = client.post(
            f"/ledger/{posted['event_uuid']}/reverse",
            json={
                "memo": "transposed digits",
                "corrected": {
                    "occurred_on": "2026-09-12",
                    "category": "repairs",
                    "amount": "-4650.00",
                    "memo": "porch rebuild invoice, restated",
                    "property_id": world["property"],
                },
            },
        ).json()
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        flagged = {flag["event_uuid"]: flag for flag in report["needs_classification"]}
        assert posted["event_uuid"] not in flagged
        assert result["reversal"]["event_uuid"] not in flagged
        corrected = flagged[result["corrected"]["event_uuid"]]
        assert Decimal(corrected["amount"]) == Decimal("4650.00")
        assert "1.263(a)-1(f)" in corrected["reason"]

    def test_missing_property_is_a_404(self, clean: None, client: TestClient) -> None:
        assert (
            client.get(f"/properties/{uuid.uuid4()}/reports/schedule-e?tax_year=2026").status_code
            == 404
        )


class TestCashFlow:
    def test_monthly_buckets_partition_every_dollar(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        report = client.get(f"/properties/{world['property']}/reports/cash-flow?year=2026").json()
        months = {month["month"]: month for month in report["months"]}
        assert Decimal(months[3]["operating_in"]) == Decimal("1450.00")
        august = months[8]
        assert Decimal(august["debt_service"]) == Decimal("-1316.00")
        assert Decimal(august["capital"]) == Decimal("-8200.00")
        assert Decimal(august["owner_flows"]) == Decimal("-1000.00")
        september = months[9]
        assert Decimal(september["owner_flows"]) == Decimal("1450.00")  # deposit held
        total = sum(Decimal(month["net"]) for month in report["months"])
        assert Decimal(report["total_net"]) == total
        assert Decimal(report["total_net"]) == Decimal("-14738.40")


class TestRentRollAndFinancials:
    def test_rent_roll_lists_active_leases_with_residents(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        conn.execute(
            """
            WITH unit AS (
              INSERT INTO units (property_id, label)
              VALUES (%(property)s, 'A') RETURNING id
            ), lease AS (
              INSERT INTO leases (unit_id, status, starts_on, ends_on, rent)
              SELECT id, 'active', '2026-04-01', '2027-03-31', 1450.00 FROM unit
              RETURNING id
            ), resident AS (
              INSERT INTO residents (full_name) VALUES ('Jordan Tenant') RETURNING id
            )
            INSERT INTO lease_residents (lease_id, resident_id)
            SELECT lease.id, resident.id FROM lease, resident
            """,
            {"property": world["property"]},
        )
        conn.commit()
        (row,) = client.get("/reports/rent-roll").json()
        assert row["property_label"] == "998 Monmouth"
        assert row["unit_label"] == "A"
        assert row["residents"] == ["Jordan Tenant"]
        assert Decimal(row["rent"]) == Decimal("1450.00")

    def test_financials_feed_the_engines(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        client.post(
            "/valuations",
            json={
                "property_id": world["property"],
                "value": "265000.00",
                "source": "owner_estimate",
                "as_of": "2026-08-01",
            },
        )
        conn.execute(
            """
            INSERT INTO debt_instruments
              (property_id, kind, original_principal, interest_rate, term_months,
               originated_on, first_payment_on, lender)
            VALUES (%s, 'conventional_mortgage', 190000.00, 0.0625, 360,
                    '2024-06-01', '2024-07-01', 'Test Lender')
            """,
            (world["property"],),
        )
        conn.commit()
        client.post(
            "/policies",
            json={
                "property_id": world["property"],
                "kind": "landlord_package",
                "carrier": "Test Mutual",
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "coinsurance_percent": "0.8",
                "coverages": [
                    {"description": "Coverage A - Dwelling", "limit_amount": "210000.00"},
                    {"description": "Loss of Rents", "months_covered": 12},
                ],
            },
        )
        financials = client.get(
            f"/properties/{world['property']}/financials?as_of=2026-12-31"
        ).json()
        assert Decimal(financials["income_12mo"]) == Decimal("2950.00")
        assert Decimal(financials["operating_expenses_12mo"]) == Decimal("8622.40")
        assert Decimal(financials["noi_12mo"]) == Decimal("-5672.40")
        assert financials["valuation"]["value"] == "265000.00"
        (debt,) = financials["debts"]
        assert debt["lender"] == "Test Lender"
        assert debt["months_elapsed"] == 30  # Jul 2024 -> Dec 2026
        (policy,) = financials["policies"]
        assert policy["dwelling_limit"] == "210000.00"
        assert policy["loss_of_rents_months"] == 12
        assert Decimal(policy["coinsurance_percent"]) == Decimal("0.8")


class TestCapexForecast:
    def test_forecast_over_the_inferred_inventory(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hestia_api import dossier
        from test_dossier import fixture_fetch

        monkeypatch.setattr(dossier, "live_fetch", fixture_fetch())
        assert (
            client.post(f"/properties/{world['property']}/dossier?as_of=2026-08-25").status_code
            == 200
        )
        # One component with a KNOWN install date, one whose type carries no
        # cost anywhere — the forecast uses the first and NAMES the second.
        conn.execute(
            """
            WITH known AS (
              INSERT INTO component_types
                (code, system, display_name, life_years_low, life_years_high,
                 weibull_scale_years, typical_cost)
              VALUES ('test.known_date', 'appliance', 'Known-date thing', 10, 20, 18, 5000)
              RETURNING id
            ), costless AS (
              INSERT INTO component_types
                (code, system, display_name, life_years_low, life_years_high,
                 weibull_scale_years)
              VALUES ('test.costless', 'appliance', 'Costless thing', 10, 20, 18)
              RETURNING id
            ), c1 AS (
              INSERT INTO components (property_id, component_type_id, installed_on, provenance_id)
              SELECT %(property)s, known.id, '2020-06-15',
                     (SELECT id FROM provenance LIMIT 1)
              FROM known RETURNING id
            )
            INSERT INTO components (property_id, component_type_id, installed_year_low,
                                    installed_year_high, provenance_id)
            SELECT %(property)s, costless.id, 2015, 2020,
                   (SELECT id FROM provenance LIMIT 1)
            FROM costless
            """,
            {"property": world["property"]},
        )
        conn.commit()
        forecast = client.get(
            f"/properties/{world['property']}/capex-forecast?horizon_years=10&as_of=2026-08-25"
        ).json()
        assert forecast["components_without_cost"] == ["test.costless"]
        assert forecast["components_simulated"] > 0
        assert len(forecast["bands"]) == 10
        assert Decimal(forecast["total_expected"]) > 0
        for band in forecast["bands"]:
            assert Decimal(band["p10"]) <= Decimal(band["p50"]) <= Decimal(band["p90"])
        # Seeded from the property id: the forecast is reproducible.
        again = client.get(
            f"/properties/{world['property']}/capex-forecast?horizon_years=10&as_of=2026-08-25"
        ).json()
        assert again == forecast

    def test_an_empty_inventory_is_a_zero_forecast(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        forecast = client.get(
            f"/properties/{world['property']}/capex-forecast?horizon_years=5"
        ).json()
        assert forecast["components_simulated"] == 0
        assert Decimal(forecast["total_expected"]) == 0


class TestPolicyAndValuationInputs:
    def test_bad_property_anchors_404(self, clean: None, client: TestClient) -> None:
        ghost = str(uuid.uuid4())
        assert (
            client.post(
                "/valuations",
                json={
                    "property_id": ghost,
                    "value": "1.00",
                    "source": "avm",
                    "as_of": "2026-01-01",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/policies",
                json={
                    "property_id": ghost,
                    "kind": "umbrella",
                    "effective_from": "2026-01-01",
                    "effective_to": "2027-01-01",
                },
            ).status_code
            == 404
        )
