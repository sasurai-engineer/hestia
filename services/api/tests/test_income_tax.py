"""Income-tax rates, resolved from the property's own chain.

Issue #8's acceptance as the schema can honestly meet it. The ticket asked for
a per-jurisdiction rate column on tax_profiles; the rate was already in the
packs, so what is tested here is that a two-state entity gets both answers
from the properties that sourced the income — and that nothing sums them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
from fastapi.testclient import TestClient


def make_entity(client: TestClient, name: str = "Cross River LLC") -> str:
    return client.post("/entities", json={"name": name, "kind": "llc"}).json()["id"]


def add_property(client: TestClient, entity_id: str, *, city: str, state: str, postal: str) -> str:
    return client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": f"{city} parcel",
            "street_1": "1 Riverfront Way",
            "city": city,
            "state": state,
            "postal_code": postal,
            "kind": "single_family",
        },
    ).json()["id"]


def rates(client: TestClient, property_id: str, year: int = 2026) -> dict[str, Any]:
    got = client.get(f"/properties/{property_id}/tax-rates?tax_year={year}")
    assert got.status_code == 200, got.text
    return got.json()


class TestTheCrossRiverCase:
    def test_one_entity_two_states_two_answers(self, clean: None, client: TestClient) -> None:
        """#8's acceptance. The entity carries no rate — it has no situs — and
        each property answers from the chain that actually reaches it."""
        entity_id = make_entity(client)
        add_property(client, entity_id, city="Newport", state="KY", postal="41071")
        add_property(client, entity_id, city="Cincinnati", state="OH", postal="45202")

        got = client.get(f"/entities/{entity_id}/tax-rates?tax_year=2026")
        assert got.status_code == 200, got.text
        body = got.json()
        assert len(body["properties"]) == 2
        by_state = {p["state"]: p for p in body["properties"]}

        # Kentucky: one body, one rate, the statute the pack cites.
        (kentucky,) = by_state["KY"]["rates"]
        assert kentucky["jurisdiction"] == "Kentucky"
        assert kentucky["level"] == "state"
        assert Decimal(kentucky["rate"]) == Decimal("0.035000")
        assert "KRS 141.020" in kentucky["citation"]

        # Ohio: the CITY levies too, and both are owed on the same dollar.
        ohio = {r["jurisdiction"]: r for r in by_state["OH"]["rates"]}
        assert set(ohio) == {"Cincinnati"}
        assert Decimal(ohio["Cincinnati"]["rate"]) == Decimal("0.018000")
        assert "718" in ohio["Cincinnati"]["citation"]
        assert ohio["Cincinnati"]["level"] == "municipality"
        assert ohio["Cincinnati"]["depth"] == 0

    def test_nothing_is_summed_into_one_number(self, clean: None, client: TestClient) -> None:
        """Whether a municipal rate stacks, is deductible, or is credited by
        the state of residence is a governance fact no pack states. So the
        card lists bodies and publishes no total — there is nothing in the
        payload a reader could mistake for a combined rate."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Cincinnati", state="OH", postal="45202")
        body = rates(client, property_id)
        assert "total" not in body
        assert "combined_rate" not in body
        assert "effective_rate" not in body

    def test_ohio_state_row_is_a_note_because_it_states_no_rate(
        self, clean: None, client: TestClient
    ) -> None:
        """Ohio's pack says "graduated; brackets not yet loaded". That is a
        real answer about Ohio and it is carried whole — but it is not a rate,
        and a card that rendered it as one would be inventing a number."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Cincinnati", state="OH", postal="45202")
        body = rates(client, property_id)
        notes = {(n["jurisdiction"], n["code"]): n for n in body["notes"]}
        state_note = notes[("Ohio", "income.type")]
        assert "brackets not yet loaded" in state_note["text"]
        assert state_note["value"] is None
        assert "5747.02" in state_note["citation"]
        assert all(rate["code"] != "income.type" for rate in body["rates"])


class TestWhatItWillNotPresentAsARate:
    def test_tennessee_owes_nothing_personally_and_says_why(
        self, clean: None, client: TestClient
    ) -> None:
        """Tennessee has no individual income tax, and its pack says so with
        its authority. That is a finding, so it arrives as a note — and the
        gap that accompanies it must not read as "we know nothing"."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Nashville", state="TN", postal="37206")
        body = rates(client, property_id)
        assert body["rates"] == []
        notes = {n["code"]: n for n in body["notes"]}
        assert notes["income.type"]["text"].startswith("none;")
        (gap,) = body["gaps"]
        assert gap["reason"] == "no_rate_for_chain"
        assert "carried below as notes" in gap["detail"]

    def test_an_entity_level_tax_is_not_the_owners_rate(
        self, clean: None, client: TestClient
    ) -> None:
        """Tennessee's franchise and excise rates are a different taxpayer's
        tax — the pack file says so in as many words. Folding them in would
        answer the wrong question with a number."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Nashville", state="TN", postal="37206")
        body = rates(client, property_id)
        codes = {n["code"] for n in body["notes"]}
        assert "income.entity_excise_rate" in codes
        assert all("entity_" not in rate["code"] for rate in body["rates"])
        # The excise rate is carried WHOLE: its number and its words.
        excise = next(n for n in body["notes"] if n["code"] == "income.entity_excise_rate")
        assert Decimal(excise["value"]) == Decimal("0.065000")
        assert "excise" in excise["text"]

    def test_a_dollar_minimum_is_never_read_as_a_rate(
        self, clean: None, client: TestClient
    ) -> None:
        """income.entity_franchise_minimum is 100 — one hundred DOLLARS.
        value_numeric carries no unit, so the code name is the only thing that
        says which figures are rates; read as one it is off by a factor of a
        hundred."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Nashville", state="TN", postal="37206")
        body = rates(client, property_id)
        minimum = next(n for n in body["notes"] if n["code"] == "income.entity_franchise_minimum")
        assert Decimal(minimum["value"]) == Decimal("100.000000")
        assert all(Decimal(rate["rate"]) < 1 for rate in body["rates"])


class TestWhenTheChainAnswersNothing:
    def test_a_state_with_no_pack_names_the_state(self, clean: None, client: TestClient) -> None:
        entity_id = make_entity(client)
        property_id = add_property(
            client, entity_id, city="Indianapolis", state="IN", postal="46204"
        )
        body = rates(client, property_id)
        (gap,) = body["gaps"]
        assert gap["reason"] == "no_state_jurisdiction"
        assert "IN" in gap["detail"]

    def test_a_chain_that_carries_nothing_at_all_says_so_differently(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """ "No rate, but here is what the pack does say" and "the domain is
        empty" are different sentences. Sandboxed in a synthetic state, since
        jurisdiction_rules is append-only."""
        if (
            conn.execute(
                "SELECT 1 AS x FROM jurisdictions WHERE state = 'QT' AND level = 'state'"
            ).fetchone()
            is None
        ):
            conn.execute(
                """
                WITH state_row AS (
                  INSERT INTO jurisdictions (level, name, state, parent_id)
                  SELECT 'state', 'Quotland', 'QT', id FROM jurisdictions
                  WHERE level = 'federal' RETURNING id
                )
                INSERT INTO jurisdictions (level, name, state, parent_id)
                SELECT 'municipality', 'Quotville', 'QT', id FROM state_row
                """
            )
            conn.commit()
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Quotville", state="QT", postal="00000")
        body = rates(client, property_id)
        assert body["rates"] == [] and body["notes"] == []
        (gap,) = body["gaps"]
        assert gap["reason"] == "no_rate_for_chain"
        assert "carries nothing else either" in gap["detail"]

    def test_an_unknown_property_and_an_unknown_entity_are_both_404(
        self, clean: None, client: TestClient
    ) -> None:
        assert client.get(f"/properties/{uuid.uuid4()}/tax-rates?tax_year=2026").status_code == 404
        assert client.get(f"/entities/{uuid.uuid4()}/tax-rates?tax_year=2026").status_code == 404


class TestTheYearDecidesTheAnswer:
    def test_the_year_is_required_and_not_defaulted_to_today(
        self, clean: None, client: TestClient
    ) -> None:
        """A rate is a fact about a year. Defaulting to the clock would answer
        a different question than the one a filing asks, and would make a 2026
        card read differently in 2029."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Newport", state="KY", postal="41071")
        assert client.get(f"/properties/{property_id}/tax-rates").status_code == 422

    def test_a_year_before_the_rule_took_effect_resolves_nothing(
        self, clean: None, client: TestClient
    ) -> None:
        """Kentucky's row is effective from 2026. Asked about 2024 the chain
        answers with a gap rather than with a rate that did not exist yet."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Newport", state="KY", postal="41071")
        body = rates(client, property_id, year=2024)
        assert body["as_of"] == "2024-12-31"
        assert body["rates"] == []
        (gap,) = body["gaps"]
        assert gap["reason"] == "no_rate_for_chain"

    def test_a_sold_property_still_answers_for_its_disposal_year(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The year a property sold is precisely the year its state rate
        matters, so unlike the coverage report this does not filter it out."""
        entity_id = make_entity(client)
        property_id = add_property(client, entity_id, city="Newport", state="KY", postal="41071")
        conn.execute(
            "UPDATE properties SET disposed_on = '2026-07-01' WHERE id = %s", (property_id,)
        )
        conn.commit()
        body = rates(client, property_id)
        assert body["disposed_on"] == "2026-07-01"
        assert len(body["rates"]) == 1
