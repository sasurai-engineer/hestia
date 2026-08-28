"""The security deposit, answered by the jurisdiction rather than by default.

Issue #5's acceptance, executable: an Ohio lease with a move-out date gets a
thirty-day deadline citing ORC 5321.16(B); a Kentucky lease shows the
separate-account duty; a state with no pack reports a gap instead of a guess.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import deposit


def make_lease(
    client: TestClient,
    *,
    state: str,
    city: str,
    postal: str,
    label: str,
    rent: str = "1450.00",
    security_deposit: str = "1450.00",
    starts_on: str = "2025-01-01",
) -> str:
    entity = client.post("/entities", json={"name": f"{label} LLC", "kind": "llc"}).json()
    prop = client.post(
        "/properties",
        json={
            "entity_id": entity["id"],
            "label": label,
            "street_1": f"1 {label} St",
            "city": city,
            "state": state,
            "postal_code": postal,
            "kind": "single_family",
        },
    ).json()
    unit = client.post("/units", json={"property_id": prop["id"], "label": "A"}).json()
    lease = client.post(
        "/leases",
        json={
            "unit_id": unit["id"],
            "starts_on": starts_on,
            "ends_on": None,
            "rent": rent,
            "rent_due_day": 1,
            "security_deposit": security_deposit,
            "escalation": "none",
            "status": "active",
            "resident_ids": [],
        },
    ).json()
    return lease["id"]


def move_out(conn: psycopg.Connection[Any], lease_id: str, on: str) -> None:
    conn.execute("UPDATE leases SET moved_out_on = %s WHERE id = %s", (on, lease_id))
    conn.commit()


@pytest.fixture
def ohio_lease(clean: None, client: TestClient) -> str:
    # Cincinnati: ORC ch. 5321 applies statewide, no adoption step.
    return make_lease(client, state="OH", city="Cincinnati", postal="45202", label="Ohio")


@pytest.fixture
def kentucky_lease(clean: None, client: TestClient) -> str:
    # Newport has adopted URLTA; Campbell County has not — the contrast the
    # packs exist to prove.
    return make_lease(client, state="KY", city="Newport", postal="41071", label="Newport")


class TestTheAcceptanceWalk:
    def test_an_ohio_move_out_gets_a_thirty_day_deadline_citing_the_statute(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        move_out(conn, ohio_lease, "2026-08-01")
        panel = client.get(f"/leases/{ohio_lease}/deposit?as_of=2026-08-05").json()
        assert panel["return_days"] == 30
        assert panel["return_due_on"] == "2026-08-31"
        assert "5321.16(B)" in panel["return_citation"]
        assert panel["gaps"] == []

        client.post("/sweep/deadlines?as_of=2026-08-05")
        row = conn.execute(
            """
            SELECT kind::text AS kind, due_on, window_opens_on, citation, status::text AS status
            FROM deadlines WHERE lease_id = %s AND kind::text = 'deposit_itemization'
            """,
            (ohio_lease,),
        ).fetchone()
        assert row is not None
        assert row["due_on"] == dt.date(2026, 8, 31)
        # The runway is visible: the duty opens at move-out.
        assert row["window_opens_on"] == dt.date(2026, 8, 1)
        assert "5321.16(B)" in row["citation"]
        assert row["status"] == "upcoming"

    def test_a_kentucky_lease_shows_the_separate_account_duty(
        self, kentucky_lease: str, client: TestClient
    ) -> None:
        panel = client.get(f"/leases/{kentucky_lease}/deposit?as_of=2026-08-05").json()
        codes = {duty["code"]: duty for duty in panel["duties"]}
        assert "urlta.deposit.separate_account_required" in codes
        assert "separate account" in codes["urlta.deposit.separate_account_required"]["requirement"]
        assert "383.580" in codes["urlta.deposit.separate_account_required"]["citation"]
        assert "urlta.deposit.itemized_list_required" in codes
        # Kentucky's pack sets no return period, so none is invented.
        assert panel["return_days"] is None
        assert panel["return_due_on"] is None
        assert [gap["code"] for gap in panel["gaps"]] == ["deposit.return_days"]

    def test_tennessee_answers_no_duty_where_ohio_answers_a_duty(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The seam a third state exposes: "no such duty exists here" and "no
        rule is loaded" must not look alike.

        Tennessee owes no deposit interest and its chapter fixes no deadline
        to return a deposit at all — the widely repeated thirty days belongs
        to TCA 66-28-301(g), the window for discovering damage after the
        tenant leaves, not to a duty to pay. Both absences are seeded as
        stated rules, so the panel answers them instead of reporting gaps.
        """
        lease = make_lease(client, state="TN", city="Nashville", postal="37206", label="Nashville")
        move_out(conn, lease, "2026-08-01")
        panel = client.get(f"/leases/{lease}/deposit?as_of=2026-08-05").json()

        # No date is invented, and no gap is raised: an explicit answer is an
        # answer. An Indiana lease in the same shape gets a gap for both.
        assert panel["return_days"] is None
        assert panel["return_due_on"] is None
        assert panel["interest"] is None
        assert panel["gaps"] == []

        codes = {duty["code"]: duty for duty in panel["duties"]}
        assert "urlta.deposit.separate_account_required" in codes
        assert "66-28-301(a)" in codes["urlta.deposit.separate_account_required"]["citation"]
        # The forfeiture rule is what Tennessee gives instead of a due date,
        # so it is what the owner is shown.
        stated = codes["deposit.return_deadline_exists"]
        assert "may retain no part of it" in stated["requirement"]
        assert "66-28-301(c)" in stated["citation"]
        # A duty the pack denies is never printed as a duty.
        assert "deposit.interest_required" not in codes

        # And the sweep agrees with the panel: no deadline, and no gap either.
        sweep = client.post("/sweep/deadlines?as_of=2026-08-05").json()
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM deadlines WHERE lease_id = %s", (lease,)
            ).fetchone()["n"]
            == 0
        )
        assert not any(
            g["domain"] == "security_deposit" and g["state"] == "TN" for g in sweep["coverage_gaps"]
        )

    def test_a_state_with_no_pack_reports_a_gap_and_raises_no_deadline(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """Indiana has no pack. The honest answer is a named gap — a deadline
        invented from a national average would look like law."""
        lease = make_lease(
            client, state="IN", city="Indianapolis", postal="46201", label="Indianapolis"
        )
        move_out(conn, lease, "2026-08-01")
        panel = client.get(f"/leases/{lease}/deposit?as_of=2026-08-05").json()
        assert panel["duties"] == []
        assert panel["return_days"] is None
        gap = next(g for g in panel["gaps"] if g["code"] == "deposit.return_days")
        assert gap["reason"] == "no_rule_for_domain"
        assert "IN" in gap["detail"]

        sweep = client.post("/sweep/deadlines?as_of=2026-08-05").json()
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM deadlines WHERE lease_id = %s", (lease,)
            ).fetchone()["n"]
            == 0
        )
        assert any(
            g["domain"] == "security_deposit" and g["state"] == "IN" for g in sweep["coverage_gaps"]
        )


class TestOhioInterest:
    def test_interest_runs_only_on_the_excess_over_a_month_s_rent(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """ORC 5321.16(A): 5% per annum on the amount exceeding the greater of
        $50 or one month's rent, once held six months or more."""
        move_out(conn, ohio_lease, "2026-01-01")
        panel = client.get(f"/leases/{ohio_lease}/deposit?as_of=2026-01-05").json()
        interest = panel["interest"]
        assert interest is not None
        assert Decimal(interest["rate"]) == Decimal("0.05")
        assert interest["months_held"] == 12
        # Deposit equals one month's rent, so nothing bears interest at all.
        assert Decimal(interest["exempt_amount"]) == Decimal("1450.00")
        assert Decimal(interest["interest_bearing"]) == 0
        assert Decimal(interest["accrued"]) == 0
        assert "5321.16(A)" in interest["citation"]

    def test_a_deposit_above_one_month_accrues(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        lease = make_lease(
            client,
            state="OH",
            city="Cincinnati",
            postal="45202",
            label="Bigger",
            rent="1000.00",
            security_deposit="2500.00",
        )
        move_out(conn, lease, "2026-01-01")
        panel = client.get(f"/leases/{lease}/deposit?as_of=2026-01-05").json()
        interest = panel["interest"]
        # 2500 - 1000 = 1500 bearing, at 5% for 12 whole months.
        assert Decimal(interest["interest_bearing"]) == Decimal("1500.00")
        assert Decimal(interest["accrued"]) == Decimal("75.00")

    def test_the_pure_formula(self) -> None:
        """Held under six months: nothing, however large the deposit."""
        assert deposit.ohio_interest(
            deposit=Decimal("5000.00"),
            monthly_rent=Decimal("1000.00"),
            months=5,
            as_of_rate=Decimal("0.05"),
        ) == Decimal("0.00")
        # The floor is fifty dollars when the rent is lower than that.
        assert deposit.ohio_interest(
            deposit=Decimal("100.00"),
            monthly_rent=Decimal("20.00"),
            months=12,
            as_of_rate=Decimal("0.05"),
        ) == Decimal("2.50")

    def test_kentucky_owes_no_interest(self, kentucky_lease: str, client: TestClient) -> None:
        panel = client.get(f"/leases/{kentucky_lease}/deposit?as_of=2026-08-05").json()
        assert panel["interest"] is None


class TestUnfamiliarPacks:
    """A state whose pack says something this release has no formula or
    sentence for. The honest answer is a named gap, never Ohio's numbers."""

    def _quexland(self, conn: psycopg.Connection[Any]) -> None:
        """Sandboxed in 'QZ' — jurisdiction_rules is append-only, so planting
        a fixture rule on a real chain would poison every later test."""
        exists = conn.execute(
            "SELECT 1 AS x FROM jurisdictions WHERE state = 'QZ' AND level = 'state'"
        ).fetchone()
        if exists is None:
            conn.execute(
                """
                WITH state_row AS (
                  INSERT INTO jurisdictions (level, name, state, parent_id)
                  SELECT 'state', 'Quizland', 'QZ', id
                  FROM jurisdictions WHERE level = 'federal' RETURNING id
                )
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, value_text,
                   citation, effective_from)
                SELECT id, 'security_deposit', 'deposit.interest_required', NULL,
                       'true; a formula this build does not implement',
                       'QZ Rev. Stat. 2.2 (test fixture)', DATE '2000-01-01'
                FROM state_row
                """
            )
            conn.execute(
                """
                INSERT INTO jurisdiction_rules
                  (jurisdiction_id, domain, code, value_numeric, value_text,
                   citation, effective_from)
                SELECT id, 'security_deposit', 'deposit.custodian_bond_required', NULL,
                       'true', 'QZ Rev. Stat. 2.3 (test fixture)', DATE '2000-01-01'
                FROM jurisdictions WHERE state = 'QZ' AND level = 'state'
                """
            )
        conn.commit()

    def test_an_unimplemented_interest_formula_is_a_gap_not_ohio_s_numbers(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        self._quexland(conn)
        lease = make_lease(client, state="QZ", city="Quizville", postal="00001", label="Quiz")
        panel = client.get(f"/leases/{lease}/deposit?as_of=2026-08-05").json()
        assert panel["interest"] is None
        gap = next(g for g in panel["gaps"] if g["code"] == "deposit.interest_formula")
        # The pack says interest is owed but names no formula, so nothing is
        # computed and the citation of the duty is carried into the gap.
        assert gap["reason"] == "no_formula_rule"
        assert "2.2" in gap["detail"]

    def test_a_rule_this_release_has_no_sentence_for_is_left_out(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """A pack may carry codes a later release will read. Showing a raw code
        to an owner would be worse than showing nothing."""
        self._quexland(conn)
        lease = make_lease(client, state="QZ", city="Quizville", postal="00002", label="Quiz2")
        panel = client.get(f"/leases/{lease}/deposit?as_of=2026-08-05").json()
        codes = [duty["code"] for duty in panel["duties"]]
        assert "deposit.custodian_bond_required" not in codes
        # ...and the one it does understand still reads.
        assert "deposit.interest_required" in codes


class TestMonthsHeld:
    def test_a_part_month_does_not_count(self) -> None:
        """'Six months or more' counts whole months: the 15th to the 14th is
        five, not six."""
        assert deposit._months_held(dt.date(2026, 1, 15), dt.date(2026, 7, 14)) == 5
        assert deposit._months_held(dt.date(2026, 1, 15), dt.date(2026, 7, 15)) == 6
        assert deposit._months_held(dt.date(2026, 7, 1), dt.date(2026, 1, 1)) == 0


class TestReturn:
    def test_returning_settles_the_money_the_record_and_the_deadline(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        move_out(conn, ohio_lease, "2026-08-01")
        client.post("/sweep/deadlines?as_of=2026-08-05")

        result = client.post(
            f"/leases/{ohio_lease}/deposit-return",
            json={
                "returned_on": "2026-08-20",
                "amount": "1200.00",
                "withheld_reason": "carpet replacement, itemised",
            },
        )
        assert result.status_code == 201, result.text
        body = result.json()
        assert Decimal(body["returned"]) == Decimal("1200.00")
        assert Decimal(body["withheld"]) == Decimal("250.00")
        assert body["deadline_resolved"] is True

        event = conn.execute(
            "SELECT category::text AS category, amount, lease_id::text FROM ledger_events"
            " WHERE event_uuid = %s",
            (body["ledger_event_uuid"],),
        ).fetchone()
        assert event["category"] == "deposit_returned"
        assert event["amount"] == Decimal("-1200.00")
        assert event["lease_id"] == ohio_lease

        resolved = conn.execute(
            "SELECT status::text AS status, completed_on FROM deadlines"
            " WHERE lease_id = %s AND kind::text = 'deposit_itemization'",
            (ohio_lease,),
        ).fetchone()
        assert resolved["status"] == "done"
        assert resolved["completed_on"] == dt.date(2026, 8, 20)

        # Re-sweeping raises nothing: the duty is discharged.
        client.post("/sweep/deadlines?as_of=2026-08-21")
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM deadlines WHERE lease_id = %s"
                " AND kind::text = 'deposit_itemization'",
                (ohio_lease,),
            ).fetchone()["n"]
            == 1
        )

    def test_withholding_everything_posts_no_ledger_row(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        move_out(conn, ohio_lease, "2026-08-01")
        body = client.post(
            f"/leases/{ohio_lease}/deposit-return",
            json={"returned_on": "2026-08-20", "amount": "0.00", "withheld_reason": "damages"},
        ).json()
        assert body["ledger_event_uuid"] is None
        assert Decimal(body["withheld"]) == Decimal("1450.00")

    def test_a_return_can_stay_out_of_the_ledger(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        move_out(conn, ohio_lease, "2026-08-01")
        body = client.post(
            f"/leases/{ohio_lease}/deposit-return",
            json={"amount": "100.00", "post_to_ledger": False},
        ).json()
        assert body["ledger_event_uuid"] is None
        assert body["returned_on"] == dt.date.today().isoformat()

    def test_the_open_queue_answers_which_deposits_are_unsettled(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        move_out(conn, ohio_lease, "2026-08-01")
        queue = client.get("/deposits/open?as_of=2026-08-05").json()
        assert [row["lease_id"] for row in queue] == [ohio_lease]
        client.post(
            f"/leases/{ohio_lease}/deposit-return",
            json={"returned_on": "2026-08-20", "amount": "1450.00"},
        )
        assert client.get("/deposits/open?as_of=2026-08-21").json() == []

    def test_refusals(
        self, ohio_lease: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        ghost = "00000000-0000-4000-8000-000000000000"
        assert client.get(f"/leases/{ghost}/deposit").status_code == 404
        assert (
            client.post(f"/leases/{ghost}/deposit-return", json={"amount": "1.00"}).status_code
            == 404
        )
        # Still living there: nothing to settle yet.
        still_there = client.post(f"/leases/{ohio_lease}/deposit-return", json={"amount": "1.00"})
        assert still_there.status_code == 422
        assert "move-out date first" in still_there.json()["detail"]

        move_out(conn, ohio_lease, "2026-08-01")
        too_much = client.post(f"/leases/{ohio_lease}/deposit-return", json={"amount": "5000.00"})
        assert too_much.status_code == 422
        assert "1450.00" in too_much.json()["detail"]

        client.post(f"/leases/{ohio_lease}/deposit-return", json={"amount": "1450.00"})
        again = client.post(f"/leases/{ohio_lease}/deposit-return", json={"amount": "10.00"})
        assert again.status_code == 409
