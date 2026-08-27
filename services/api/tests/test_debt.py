"""Recording a note, and the payment it demands.

Issue #37's acceptance, executable: record the real 998 Monmouth note, the
hold/sell card picks it up without SQL, the schedule renders, and a split
matches the engine to the cent.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_sim.finance import amortization

# The note the fixture property actually carries in the demo world.
NOTE = {
    "lender": "Licking Valley Savings Bank",
    "original_principal": "150000.00",
    "interest_rate": "0.04625",
    "term_months": 360,
    "originated_on": "2019-04-11",
    "first_payment_on": "2019-06-01",
}


@pytest.fixture
def note(newport_property: str, client: TestClient) -> dict[str, Any]:
    response = client.post("/debts", json={"property_id": newport_property, **NOTE})
    assert response.status_code == 201, response.text
    return response.json()


class TestTheAcceptanceWalk:
    def test_the_note_is_recorded_and_the_schedule_matches_the_engine(
        self, note: dict[str, Any], client: TestClient
    ) -> None:
        assert note["lender"] == NOTE["lender"]
        assert note["payments_recorded"] == 0
        assert Decimal(note["principal_paid"]) == 0

        engine = amortization(15_000_000, NOTE["interest_rate"], 360)
        expected_payment = Decimal(engine["payment"]) / 100
        assert Decimal(note["scheduled_payment"]) == expected_payment

        schedule = client.get(f"/debts/{note['id']}/schedule?as_of=2019-06-01").json()
        assert Decimal(schedule["scheduled_payment"]) == expected_payment
        assert Decimal(schedule["total_interest"]) == Decimal(engine["total_interest"]) / 100
        assert len(schedule["rows"]) == 360
        # To the cent, every row, because the engine produced them.
        assert [Decimal(r["interest"]) for r in schedule["rows"][:3]] == [
            Decimal(e["interest"]) / 100 for e in engine["rows"][:3]
        ]
        # The last row closes the loan out exactly.
        assert Decimal(schedule["rows"][-1]["balance"]) == 0
        assert "hestia_sim.finance.amortization" in schedule["citation"]
        # The first payment is month 1.
        assert schedule["next_month"] == 1
        assert Decimal(schedule["next_interest"]) == Decimal(engine["rows"][0]["interest"]) / 100

    def test_the_hold_sell_card_picks_it_up_without_sql(
        self, note: dict[str, Any], newport_property: str, client: TestClient
    ) -> None:
        """The financials read model is the hold/sell card's only source; it
        read an empty table until a note could be written through the API."""
        financials = client.get(f"/properties/{newport_property}/financials").json()
        assert len(financials["debts"]) == 1
        carried = financials["debts"][0]
        assert carried["lender"] == NOTE["lender"]
        assert Decimal(carried["original_principal"]) == Decimal("150000.00")
        assert Decimal(carried["annual_rate"]) == Decimal(NOTE["interest_rate"])
        assert carried["term_months"] == 360
        assert carried["months_elapsed"] > 0

    def test_a_payment_takes_the_engine_s_split_and_posts_the_pair(
        self, note: dict[str, Any], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """Interest is deductible and principal is equity — different lines on
        Schedule E, so a mortgage payment was never one ledger row."""
        engine = amortization(15_000_000, NOTE["interest_rate"], 360)
        first = engine["rows"][0]

        payment = client.post(
            f"/debts/{note['id']}/payments",
            json={"paid_on": "2019-06-01", "escrow": "310.00"},
        )
        assert payment.status_code == 201, payment.text
        body = payment.json()
        assert body["from_schedule_month"] == 1
        assert Decimal(body["interest"]) == Decimal(first["interest"]) / 100
        assert Decimal(body["principal"]) == Decimal(first["principal"]) / 100
        assert Decimal(body["balance_after"]) == Decimal("150000.00") - Decimal(body["principal"])
        assert len(body["ledger_event_uuids"]) == 2

        posted = conn.execute(
            """
            SELECT category::text AS category, amount FROM ledger_events
            WHERE event_uuid = ANY(%s) ORDER BY category
            """,
            (body["ledger_event_uuids"],),
        ).fetchall()
        assert [row["category"] for row in posted] == [
            "mortgage_interest",
            "mortgage_principal",
        ]
        assert posted[0]["amount"] == -Decimal(body["interest"])
        assert posted[1]["amount"] == -Decimal(body["principal"])

        after = client.get(f"/debts/{note['id']}").json()
        assert after["payments_recorded"] == 1
        assert Decimal(after["interest_paid"]) == Decimal(body["interest"])


class TestPayments:
    def test_what_the_lender_actually_applied_wins_over_the_schedule(
        self, note: dict[str, Any], client: TestClient
    ) -> None:
        body = client.post(
            f"/debts/{note['id']}/payments",
            json={
                "paid_on": "2019-06-01",
                "principal": "300.00",
                "interest": "500.00",
                "extra_principal": "1000.00",
            },
        ).json()
        assert body["from_schedule_month"] is None
        assert Decimal(body["principal"]) == Decimal("300.00")
        # Extra principal goes against the balance and rides the principal line.
        assert Decimal(body["balance_after"]) == Decimal("148700.00")

    def test_extra_principal_lands_on_the_principal_line(
        self, note: dict[str, Any], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        body = client.post(
            f"/debts/{note['id']}/payments",
            json={
                "paid_on": "2019-06-01",
                "principal": "200.00",
                "interest": "500.00",
                "extra_principal": "800.00",
            },
        ).json()
        principal_event = conn.execute(
            """
            SELECT amount FROM ledger_events
            WHERE event_uuid = ANY(%s) AND category::text = 'mortgage_principal'
            """,
            (body["ledger_event_uuids"],),
        ).fetchone()
        assert principal_event["amount"] == Decimal("-1000.00")

    def test_a_payment_may_stay_out_of_the_ledger(
        self, note: dict[str, Any], client: TestClient
    ) -> None:
        body = client.post(
            f"/debts/{note['id']}/payments",
            json={"paid_on": "2019-06-01", "post_to_ledger": False},
        ).json()
        assert body["ledger_event_uuids"] == []

    def test_an_interest_only_period_posts_one_line(
        self, note: dict[str, Any], client: TestClient
    ) -> None:
        body = client.post(
            f"/debts/{note['id']}/payments",
            json={"paid_on": "2019-06-01", "principal": "0.00", "interest": "578.13"},
        ).json()
        assert len(body["ledger_event_uuids"]) == 1

    def test_one_payment_per_date(self, note: dict[str, Any], client: TestClient) -> None:
        client.post(f"/debts/{note['id']}/payments", json={"paid_on": "2019-06-01"})
        again = client.post(f"/debts/{note['id']}/payments", json={"paid_on": "2019-06-01"})
        assert again.status_code == 409
        assert "corrects by reversal" in again.json()["detail"]

    def test_a_payment_outside_the_schedule_asks_for_the_split(
        self, note: dict[str, Any], client: TestClient
    ) -> None:
        response = client.post(f"/debts/{note['id']}/payments", json={"paid_on": "2019-05-01"})
        assert response.status_code == 422
        assert "state it explicitly" in response.json()["detail"]


class TestLifecycle:
    def test_paying_off_retires_the_note_from_every_reader(
        self, note: dict[str, Any], newport_property: str, client: TestClient
    ) -> None:
        paid = client.post(f"/debts/{note['id']}/payoff", json={"paid_off_on": "2026-08-27"}).json()
        assert paid["paid_off_on"] == "2026-08-27"
        assert client.get(f"/debts?property_id={newport_property}").json() == []
        assert (
            len(client.get(f"/debts?property_id={newport_property}&include_paid_off=true").json())
            == 1
        )
        # The hold/sell card stops carrying it too.
        financials = client.get(f"/properties/{newport_property}/financials").json()
        assert financials["debts"] == []
        assert (
            client.post(
                f"/debts/{note['id']}/payoff", json={"paid_off_on": "2026-09-01"}
            ).status_code
            == 409
        )
        assert (
            client.post(f"/debts/{note['id']}/payments", json={"paid_on": "2019-06-01"}).status_code
            == 409
        )

    def test_a_second_lien_sorts_behind_the_first(
        self, note: dict[str, Any], newport_property: str, client: TestClient
    ) -> None:
        client.post(
            "/debts",
            json={
                "property_id": newport_property,
                "lender": "Second Position",
                "original_principal": "25000.00",
                "interest_rate": "0.09000",
                "term_months": 180,
                "originated_on": "2021-03-01",
                "lien_position": 2,
                "kind": "heloc",
            },
        )
        rows = client.get(f"/debts?property_id={newport_property}").json()
        assert [row["lien_position"] for row in rows] == [1, 2]
        assert rows[1]["kind"] == "heloc"


class TestRefusals:
    def test_the_note_s_own_rules_refuse_by_name(
        self, newport_property: str, client: TestClient
    ) -> None:
        base = {"property_id": newport_property, **NOTE}
        short_amortization = client.post(
            "/debts", json={**base, "term_months": 360, "amortization_months": 120}
        )
        assert short_amortization.status_code == 422
        assert "shorter than the term" in short_amortization.json()["detail"]

        armless = client.post("/debts", json={**base, "amortization": "arm"})
        assert armless.status_code == 422
        assert "what it adjusts against" in armless.json()["detail"]

    def test_bad_terms_are_refused_at_the_edge(
        self, newport_property: str, client: TestClient
    ) -> None:
        base = {"property_id": newport_property, **NOTE}
        for bad in (
            {"original_principal": "0.00"},
            {"original_principal": "-1.00"},
            {"term_months": 0},
            {"interest_rate": "1.5"},
            {"lien_position": 0},
        ):
            assert client.post("/debts", json={**base, **bad}).status_code == 422, bad

    def test_unknown_things_are_404(self, newport_property: str, client: TestClient) -> None:
        ghost = "00000000-0000-4000-8000-000000000000"
        assert client.get(f"/debts/{ghost}").status_code == 404
        assert client.get(f"/debts/{ghost}/schedule").status_code == 404
        assert (
            client.post(f"/debts/{ghost}/payments", json={"paid_on": "2026-01-01"}).status_code
            == 404
        )
        assert (
            client.post(f"/debts/{ghost}/payoff", json={"paid_off_on": "2026-01-01"}).status_code
            == 404
        )
        assert client.post("/debts", json={"property_id": ghost, **NOTE}).status_code == 404
        assert (
            client.post(
                "/debts",
                json={"property_id": newport_property, "entity_id": ghost, **NOTE},
            ).status_code
            == 404
        )

    def test_an_interest_only_note_gets_no_level_schedule(
        self, newport_property: str, client: TestClient
    ) -> None:
        """The engine amortizes level payments; claiming a schedule for
        interest-only terms would be arithmetic nobody did."""
        io_note = client.post(
            "/debts",
            json={
                "property_id": newport_property,
                **NOTE,
                "amortization": "interest_only",
                "lien_position": 3,
            },
        ).json()
        assert io_note["scheduled_payment"] is None
        response = client.get(f"/debts/{io_note['id']}/schedule")
        assert response.status_code == 422
        assert "interest_only" in response.json()["detail"]
        # ...and a payment on it must state its own split.
        assert (
            client.post(
                f"/debts/{io_note['id']}/payments", json={"paid_on": "2019-06-01"}
            ).status_code
            == 422
        )


class TestScheduleEdges:
    def test_a_date_past_the_last_payment_has_no_next_row(
        self, note: dict[str, Any], client: TestClient
    ) -> None:
        schedule = client.get(f"/debts/{note['id']}/schedule?as_of=2060-01-01").json()
        assert schedule["next_month"] is None
        assert schedule["next_interest"] is None
        assert schedule["next_principal"] is None
        # The schedule itself still renders in full.
        assert len(schedule["rows"]) == 360

    def test_a_balloon_amortizes_over_the_longer_period(
        self, newport_property: str, client: TestClient
    ) -> None:
        balloon = client.post(
            "/debts",
            json={
                "property_id": newport_property,
                **NOTE,
                "amortization": "balloon",
                "term_months": 84,
                "amortization_months": 360,
                "lien_position": 4,
            },
        ).json()
        schedule = client.get(f"/debts/{balloon['id']}/schedule?as_of=2019-06-01").json()
        # Amortized over 360 even though it comes due in 84 — that is the whole
        # point of a balloon, and the payment reflects the longer period.
        assert len(schedule["rows"]) == 360
        assert (
            Decimal(schedule["scheduled_payment"])
            == Decimal(amortization(15_000_000, NOTE["interest_rate"], 360)["payment"]) / 100
        )

    def test_the_schedule_defaults_to_today(self, note: dict[str, Any], client: TestClient) -> None:
        schedule = client.get(f"/debts/{note['id']}/schedule").json()
        expected = (dt.date.today().year - 2019) * 12 + (dt.date.today().month - 6) + 1
        assert schedule["next_month"] == expected
