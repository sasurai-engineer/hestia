"""The over-assessment card: what a body said against what the market says.

Issue #9's acceptance, executable — and the two ways it can be wrong by a
factor of three. A Kentucky notice states a value that already IS market; an
Ohio taxable notice states 35% of it. Which of those a row holds is recorded
per row, never inferred, and this suite pins both directions.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
from fastapi.testclient import TestClient

CAMPBELL_COUNTY = "a0000000-0000-4000-8000-000000000021"
HAMILTON_COUNTY_OH = "a0000000-0039-4000-8000-000000000021"
DAVIDSON_COUNTY = "a0000000-0047-4000-8000-000000000021"


def make_property(
    client: TestClient, *, city: str, state: str, postal: str, label: str | None = None
) -> str:
    entity = client.post("/entities", json={"name": f"{city} LLC", "kind": "llc"}).json()
    return client.post(
        "/properties",
        json={
            "entity_id": entity["id"],
            "label": label or city,
            "street_1": "1 Main St",
            "city": city,
            "state": state,
            "postal_code": postal,
            "kind": "single_family",
        },
    ).json()["id"]


def record(
    client: TestClient,
    property_id: str,
    *,
    basis: str,
    total: str,
    year: int = 2026,
    jurisdiction_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "property_id": property_id,
        "tax_year": year,
        "value_basis": basis,
        "assessed_total": total,
    }
    if jurisdiction_id is not None:
        payload["jurisdiction_id"] = jurisdiction_id
    created = client.post("/assessments", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def value(
    client: TestClient, property_id: str, *, amount: str, source: str, as_of: str = "2026-03-01"
) -> None:
    created = client.post(
        "/valuations",
        json={"property_id": property_id, "value": amount, "source": source, "as_of": as_of},
    )
    assert created.status_code == 201, created.text


def card(client: TestClient, property_id: str, as_of: str = "2026-06-01") -> dict[str, Any]:
    got = client.get(f"/properties/{property_id}/appeal?as_of={as_of}")
    assert got.status_code == 200, got.text
    return got.json()


class TestTheAcceptanceWalk:
    def test_newport_flags_with_kentucky_citations(self, clean: None, client: TestClient) -> None:
        """A Kentucky notice states fair cash value, which already IS market —
        so the ratio is cited and NOT applied, and the comparison is direct."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(
            client,
            property_id,
            basis="market",
            total="200000.00",
            jurisdiction_id=CAMPBELL_COUNTY,
        )
        value(client, property_id, amount="160000.00", source="appraisal")
        client.post("/sweep/deadlines?as_of=2026-06-01")

        body = card(client, property_id)
        assert body["state"] == "KY"
        assert body["tax_year"] == 2026
        (finding,) = body["findings"]

        assert finding["ratio"]["applied"] is False
        assert Decimal(finding["ratio"]["value"]) == Decimal("1.000000")
        assert "s.172" in finding["ratio"]["citation"]
        assert "Russman" in finding["ratio"]["citation"]
        # Stated at market, so the implied full value is the stated total.
        assert Decimal(finding["implied_market_value"]) == Decimal("200000.00")
        assert Decimal(finding["over_market_amount"]) == Decimal("40000.00")
        assert Decimal(finding["over_market_pct"]) == Decimal("0.250000")
        assert finding["over_assessed"] is True
        assert finding["gaps"] == []

        assert body["market_opinion"]["source"] == "appraisal"
        assert body["window"] is not None
        assert "KRS 133.045" in body["window"]["citation"]
        assert "62F031" in body["window"]["form"]["text"]

    def test_cincinnati_applies_the_thirty_five_percent_ratio(
        self, clean: None, client: TestClient
    ) -> None:
        """The same finding through Ohio's ratio. A taxable notice of 70,000 is
        an assertion that the property is worth 200,000 — and without the
        ratio it would read as wildly UNDER-assessed against a 160,000
        appraisal, which is the error the ticket exists to prevent."""
        property_id = make_property(client, city="Cincinnati", state="OH", postal="45202")
        record(
            client,
            property_id,
            basis="taxable",
            total="70000.00",
            jurisdiction_id=HAMILTON_COUNTY_OH,
        )
        value(client, property_id, amount="160000.00", source="appraisal")
        client.post("/sweep/deadlines?as_of=2026-06-01")

        body = card(client, property_id)
        (finding,) = body["findings"]
        assert finding["ratio"]["applied"] is True
        assert Decimal(finding["ratio"]["value"]) == Decimal("0.350000")
        assert "5715.01" in finding["ratio"]["citation"]
        assert Decimal(finding["implied_market_value"]) == Decimal("200000.00")
        assert Decimal(finding["over_market_amount"]) == Decimal("40000.00")
        assert finding["over_assessed"] is True
        assert "DTE Form 1" in body["window"]["form"]["text"]
        assert "ORC 5715.19" in body["window"]["citation"]

    def test_the_same_figures_without_the_ratio_would_read_as_under_assessed(
        self, clean: None, client: TestClient
    ) -> None:
        """The counterfactual, pinned. 70,000 compared naively against 160,000
        is 56% under — the opposite conclusion, on the same paper."""
        property_id = make_property(client, city="Norwood", state="OH", postal="45212")
        record(client, property_id, basis="taxable", total="70000.00")
        value(client, property_id, amount="160000.00", source="appraisal")
        body = card(client, property_id)
        (finding,) = body["findings"]
        assert Decimal(finding["implied_market_value"]) == Decimal("200000.00")
        assert finding["over_assessed"] is True
        naive = Decimal("70000.00") - Decimal("160000.00")
        assert naive < 0 and Decimal(finding["over_market_amount"]) > 0


class TestTheBasisDecidesEverything:
    def test_an_ohio_market_row_is_not_divided(self, clean: None, client: TestClient) -> None:
        """An Ohio value notice states MARKET and nothing else, so the same
        pack, the same property and the same ratio must leave it alone."""
        property_id = make_property(client, city="Cincinnati", state="OH", postal="45202")
        record(client, property_id, basis="market", total="200000.00")
        value(client, property_id, amount="160000.00", source="appraisal")
        body = card(client, property_id)
        (finding,) = body["findings"]
        assert finding["ratio"]["applied"] is False
        assert (
            "already the figure a market opinion compares against"
            in (finding["ratio"]["applied_reason"])
        )
        assert Decimal(finding["implied_market_value"]) == Decimal("200000.00")

    def test_both_bases_of_one_notice_are_each_a_finding(
        self, clean: None, client: TestClient
    ) -> None:
        """A Tennessee card states both. Neither row is dropped, and the two
        reach different places — the market half compares, the taxable half
        gaps because Tennessee's pack carries two ratios."""
        property_id = make_property(client, city="Nashville", state="TN", postal="37206")
        record(
            client,
            property_id,
            basis="market",
            total="200000.00",
            jurisdiction_id=DAVIDSON_COUNTY,
        )
        record(
            client,
            property_id,
            basis="taxable",
            total="50000.00",
            jurisdiction_id=DAVIDSON_COUNTY,
        )
        value(client, property_id, amount="160000.00", source="broker_opinion")
        body = card(client, property_id)
        assert len(body["findings"]) == 2
        by_basis = {f["assessment"]["value_basis"]: f for f in body["findings"]}
        assert Decimal(by_basis["market"]["implied_market_value"]) == Decimal("200000.00")
        assert by_basis["market"]["over_assessed"] is True
        taxable = by_basis["taxable"]
        assert taxable["implied_market_value"] is None
        assert taxable["over_assessed"] is None
        (gap,) = taxable["gaps"]
        assert gap["reason"] == "ambiguous_ratio"
        assert "assessment.ratio" in gap["detail"]
        assert "assessment.ratio.commercial" in gap["detail"]

    def test_the_tennessee_caveat_travels_with_the_ratio(
        self, clean: None, client: TestClient
    ) -> None:
        """The attorney-general opinion that says there is no bright-line rule
        is why the ambiguity above is a gap rather than a guess."""
        property_id = make_property(client, city="Nashville", state="TN", postal="37206")
        record(client, property_id, basis="market", total="200000.00")
        body = card(client, property_id)
        notes = {note["code"]: note for note in body["ratio_notes"]}
        assert "assessment.ratio.caveat" in notes
        assert "No bright-line rule" in notes["assessment.ratio.caveat"]["text"]
        assert "25-016" in notes["assessment.ratio.caveat"]["citation"]


class TestWhatItRefusesToCompare:
    def test_the_assessors_own_number_is_not_a_comparand(
        self, clean: None, client: TestClient
    ) -> None:
        """The circular comparison. An assessor-sourced valuation against the
        assessment reports 0.00% over-assessed with a statute attached, and
        nothing about that looks broken — so the source is refused and the gap
        NAMES what was on file."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        value(client, property_id, amount="200000.00", source="assessor")
        body = card(client, property_id)
        (finding,) = body["findings"]
        assert finding["over_assessed"] is None
        assert body["market_opinion"] is None
        (gap,) = [g for g in body["gaps"] if g["reason"] == "no_market_opinion"]
        assert "assessor" in gap["detail"]
        assert "never over-assessed" in gap["detail"]

    def test_an_owners_own_estimate_is_not_a_comparand_either(
        self, clean: None, client: TestClient
    ) -> None:
        """The number in dispute cannot also be the evidence."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        value(client, property_id, amount="120000.00", source="owner_estimate")
        body = card(client, property_id)
        assert body["market_opinion"] is None
        (gap,) = [g for g in body["gaps"] if g["reason"] == "no_market_opinion"]
        assert "owner_estimate" in gap["detail"]

    def test_no_valuation_at_all_says_so_differently(self, clean: None, client: TestClient) -> None:
        """ "Nobody has valued this" and "the only value on file is the one
        under test" are different sentences."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        body = card(client, property_id)
        (gap,) = [g for g in body["gaps"] if g["reason"] == "no_market_opinion"]
        assert "no independent opinion of value is on file" in gap["detail"]

    def test_nothing_recorded_is_a_named_gap(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        body = card(client, property_id)
        assert body["findings"] == []
        assert body["tax_year"] is None
        (gap,) = body["gaps"]
        assert gap["reason"] == "no_assessment_on_file"

    def test_a_state_with_no_pack_says_which_state(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client, city="Indianapolis", state="IN", postal="46204")
        body = card(client, property_id)
        (gap,) = body["gaps"]
        assert gap["reason"] == "no_state_jurisdiction"
        assert "IN" in gap["detail"]

    def test_an_unknown_property_is_the_only_error_status(
        self, clean: None, client: TestClient
    ) -> None:
        assert client.get(f"/properties/{uuid.uuid4()}/appeal").status_code == 404


class TestTheWindowAndTheYearItContests:
    def test_kentucky_contests_the_same_year(self, clean: None, client: TestClient) -> None:
        """Kentucky's May inspection period is held on that year's own roll."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00", year=2027)
        client.post("/sweep/deadlines?as_of=2026-06-01")
        body = card(client, property_id)
        assert body["window"]["contests_tax_year"] == 2027
        assert "133.045" in body["window"]["contests_tax_year_citation"]
        assert body["pairing"] == "contests_this_assessment"

    def test_ohio_contests_the_year_before(self, clean: None, client: TestClient) -> None:
        """Ohio's complaint is filed in the year FOLLOWING the tax year, so an
        owner holding a 2026 notice beside a 2027 window is correctly paired
        — and one holding a 2027 notice is not."""
        property_id = make_property(client, city="Cincinnati", state="OH", postal="45202")
        record(client, property_id, basis="market", total="200000.00", year=2026)
        client.post("/sweep/deadlines?as_of=2026-06-01")
        body = card(client, property_id)
        assert body["window"]["closes_on"] == "2027-03-31"
        assert body["window"]["contests_tax_year"] == 2026
        assert body["pairing"] == "contests_this_assessment"

    def test_a_window_contesting_another_year_says_so(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client, city="Cincinnati", state="OH", postal="45202")
        record(client, property_id, basis="market", total="200000.00", year=2024)
        client.post("/sweep/deadlines?as_of=2026-06-01")
        body = card(client, property_id)
        assert body["window"]["contests_tax_year"] == 2026
        assert body["pairing"] == "contests_a_different_year"

    def test_tennessee_will_not_claim_which_year_its_window_contests(
        self, clean: None, client: TestClient
    ) -> None:
        """Nothing in the Tennessee pack sources the offset, and the
        authorities it does carry are authorities for the window, not for the
        year it contests. Unknown is the honest answer."""
        property_id = make_property(client, city="Nashville", state="TN", postal="37206")
        record(client, property_id, basis="market", total="200000.00")
        client.post("/sweep/deadlines?as_of=2026-06-01")
        body = card(client, property_id)
        assert body["window"] is not None
        assert body["window"]["contests_tax_year"] is None
        assert body["pairing"] == "unknown"

    def test_no_window_on_the_calendar_is_a_named_gap(
        self, clean: None, client: TestClient
    ) -> None:
        """The card reads the deadline the sweep wrote rather than resolving a
        second opinion, so an unswept property says exactly that."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        body = card(client, property_id)
        assert body["window"] is None
        assert body["pairing"] == "unknown"
        (gap,) = [g for g in body["gaps"] if g["reason"] == "no_window_scheduled"]
        assert "deadline sweep" in gap["detail"]


class TestTheComparandIsChosenStably:
    def test_the_newest_admissible_opinion_wins(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        value(client, property_id, amount="100000.00", source="avm", as_of="2025-01-01")
        value(client, property_id, amount="160000.00", source="appraisal", as_of="2026-03-01")
        body = card(client, property_id)
        assert Decimal(body["market_opinion"]["value"]) == Decimal("160000.00")
        assert body["market_opinion"]["age_days"] == 92

    def test_an_opinion_dated_after_the_as_of_is_not_used(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        value(client, property_id, amount="160000.00", source="appraisal", as_of="2026-03-01")
        value(client, property_id, amount="999000.00", source="appraisal", as_of="2026-12-01")
        body = card(client, property_id)
        assert Decimal(body["market_opinion"]["value"]) == Decimal("160000.00")

    def test_two_opinions_on_one_day_resolve_the_same_way_twice(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """created_at is the TRANSACTION timestamp, so a bulk load leaves it
        identical across rows; without the id tail the winner would be
        whatever the planner returned, and a percentage that moves when
        nothing moved gets reported as data corruption."""
        property_id = make_property(client, city="Newport", state="KY", postal="41071")
        record(client, property_id, basis="market", total="200000.00")
        provenance = conn.execute(
            "INSERT INTO provenance (kind, confidence, source_label)"
            " VALUES ('market_data', 0.8, 'bulk') RETURNING id"
        ).fetchone()
        for amount in ("150000.00", "170000.00", "160000.00"):
            conn.execute(
                "INSERT INTO valuations (property_id, as_of, source, value, provenance_id)"
                " VALUES (%s, '2026-03-01', 'avm', %s, %s)",
                (property_id, amount, provenance["id"]),
            )
        conn.commit()
        first = card(client, property_id)["market_opinion"]["value"]
        second = card(client, property_id)["market_opinion"]["value"]
        assert first == second


class TestARatioThatCannotBeUsed:
    """Sandboxed synthetic packs. jurisdiction_rules is append-only, so a
    bogus rule planted on a real chain would poison every later test."""

    def _plant(
        self, conn: psycopg.Connection[Any], state: str, name: str, ratio: str | None
    ) -> None:
        if (
            conn.execute(
                "SELECT 1 AS x FROM jurisdictions WHERE state = %s AND level = 'state'",
                (state,),
            ).fetchone()
            is None
        ):
            conn.execute(
                """
                WITH state_row AS (
                  INSERT INTO jurisdictions (level, name, state, parent_id)
                  SELECT 'state', %s, %s, id FROM jurisdictions WHERE level = 'federal'
                  RETURNING id
                )
                INSERT INTO jurisdictions (level, name, state, parent_id)
                SELECT 'municipality', %s, %s, id FROM state_row
                """,
                (name, state, f"{name}ville", state),
            )
            if ratio is not None:
                conn.execute(
                    """
                    INSERT INTO jurisdiction_rules
                      (jurisdiction_id, domain, code, value_numeric, citation, effective_from)
                    SELECT id, 'assessment_ratio', 'assessment.ratio', %s,
                           'Test Rev. Stat. 1.1 (fixture)', DATE '2000-01-01'
                    FROM jurisdictions WHERE state = %s AND level = 'state'
                    """,
                    (ratio, state),
                )
            conn.commit()

    def test_a_taxable_notice_with_no_ratio_is_not_assumed_to_be_one(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The failure mode the Kentucky row existed to prevent: without a
        seeded ratio, `ratio or 1` would silently be right in Kentucky and
        wrong by a factor of three in Ohio, and no ratchet catches it because
        the expression contains no state literal."""
        self._plant(conn, "QZ", "Quozland", None)
        property_id = make_property(client, city="Quozlandville", state="QZ", postal="00000")
        record(client, property_id, basis="taxable", total="70000.00")
        value(client, property_id, amount="160000.00", source="appraisal")
        body = card(client, property_id)
        (finding,) = body["findings"]
        assert finding["ratio"] is None
        assert finding["implied_market_value"] is None
        assert finding["over_assessed"] is None
        (gap,) = finding["gaps"]
        assert gap["reason"] == "no_rule_for_domain"
        assert "not assumed to be one" in gap["detail"]

    def test_a_ratio_of_zero_is_refused_rather_than_divided_by(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        self._plant(conn, "QV", "Quovland", "0")
        property_id = make_property(client, city="Quovlandville", state="QV", postal="00000")
        record(client, property_id, basis="taxable", total="70000.00")
        body = card(client, property_id)
        (finding,) = body["findings"]
        (gap,) = finding["gaps"]
        assert gap["reason"] == "unusable_ratio"
        assert "nothing can be divided by" in gap["detail"]
