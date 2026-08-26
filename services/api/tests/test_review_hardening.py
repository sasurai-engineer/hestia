"""Regression pins for the adversarial review of increments 2-4.

Every test here reproduces a confirmed finding's scenario and proves the
fix: the balance fan-out, the reversal/allocation disconnect, vanished
prepayment credit, race guards, sign honesty, and stale sign-offs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import payments

SECRET = "whsec_test_fixture"  # noqa: S105  # config-audit: allow — test fixture


@pytest.fixture
def world(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "RH", "kind": "llc"}).json()["id"]
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
    unit_id = client.post("/units", json={"property_id": property_id, "label": "A"}).json()["id"]
    lease_id = client.post(
        "/leases",
        json={"unit_id": unit_id, "starts_on": "2026-01-01", "rent": "1450.00"},
    ).json()["id"]
    return {"entity": entity_id, "property": property_id, "lease": lease_id}


class TestBalanceFanOut:
    def test_two_partial_payments_do_not_double_count_the_charge(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """The critical finding: sum-over-join multiplied a charge by its
        allocation count, then /collect billed the phantom balance."""
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "700.00"},
        )
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-05", "amount": "750.00"},
        )
        detail = client.get(f"/leases/{world['lease']}").json()
        assert Decimal(detail["balance_due"]) == 0
        assert Decimal(detail["open_credit"]) == 0
        (charge,) = detail["charges"]
        assert charge["status"] == "paid"
        (summary,) = [row for row in client.get("/leases").json() if row["id"] == world["lease"]]
        assert Decimal(summary["balance_due"]) == 0

    def test_waiving_a_partially_paid_charge_frees_its_allocation_from_the_balance(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "500.00"},
        )
        detail = client.get(f"/leases/{world['lease']}").json()
        (charge,) = detail["charges"]
        client.post(f"/rent-charges/{charge['id']}/waive", json={"reason": "hardship credit"})
        after = client.get(f"/leases/{world['lease']}").json()
        # Waiver semantics: forgive the UNPAID REMAINDER. The $500 already
        # paid stays applied to the waived charge (it satisfied part of a
        # then-live obligation); the balance owes nothing and no phantom
        # credit or negative balance appears.
        assert Decimal(after["balance_due"]) == 0
        assert Decimal(after["open_credit"]) == 0
        (waived,) = after["charges"]
        assert waived["status"] == "waived"
        assert Decimal(waived["allocated"]) == Decimal("500.00")


class TestReversalUnwind:
    def test_reversing_a_receipt_unpays_the_charge(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """A reversed receipt must not leave rent looking paid — the silent
        rent-forgiveness finding."""
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        receipt = client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "1450.00"},
        ).json()
        assert client.get(f"/leases/{world['lease']}").json()["charges"][0]["status"] == "paid"
        reversed_response = client.post(f"/ledger/{receipt['event_uuid']}/reverse", json={})
        assert reversed_response.status_code == 201
        after = client.get(f"/leases/{world['lease']}").json()
        (charge,) = after["charges"]
        assert charge["status"] == "due"
        assert Decimal(charge["allocated"]) == 0
        assert Decimal(after["balance_due"]) == Decimal("1450.00")
        assert Decimal(after["open_credit"]) == 0
        # The late-fee sweep can see it again (gap reported, KY has no rule).
        result = client.post("/sweep/late-fees?as_of=2026-08-20").json()
        assert any(g["lease_id"] == world["lease"] for g in result["gaps"])

    def test_the_double_reversal_race_loses_to_the_schema(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate the race: blind the advisory check, prove the
        one_reversal_per_event index converts corruption into 409."""
        event = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "1450.00",
                "property_id": world["property"],
            },
        ).json()
        assert client.post(f"/ledger/{event['event_uuid']}/reverse", json={}).status_code == 201
        real_execute = psycopg.Connection.execute

        def blind_execute(self: Any, query: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(query, str) and "WHERE reverses_event_id = %s" in query:
                return real_execute(self, "SELECT 1 AS x FROM ledger_events WHERE FALSE", ())
            return real_execute(self, query, *args, **kwargs)

        monkeypatch.setattr(psycopg.Connection, "execute", blind_execute)
        second = client.post(f"/ledger/{event['event_uuid']}/reverse", json={})
        assert second.status_code == 409
        monkeypatch.undo()
        reversals = conn.execute(
            """
            SELECT count(*) AS n FROM ledger_events r
            JOIN ledger_events o ON o.id = r.reverses_event_id
            WHERE o.event_uuid = %s
            """,
            (event["event_uuid"],),
        ).fetchone()
        assert reversals is not None and reversals["n"] == 1

    def test_register_gross_totals_exclude_reversal_pairs(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "1450.00",
                "property_id": world["property"],
            },
        )
        mistake = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-02",
                "category": "repairs",
                "amount": "-999.00",
                "property_id": world["property"],
            },
        ).json()
        client.post(f"/ledger/{mistake['event_uuid']}/reverse", json={})
        register = client.get(f"/ledger?property_id={world['property']}").json()
        # A mistake and its correction are not cash flow.
        assert Decimal(register["total_in"]) == Decimal("1450.00")
        assert Decimal(register["total_out"]) == 0
        assert Decimal(register["net"]) == Decimal("1450.00")


class TestPrepaymentCredit:
    def test_first_and_last_month_prepayment_pays_the_next_sweep(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The vanished-credit finding: prepay two months, and the September
        sweep must consume the surplus instead of billing and fining."""
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        receipt = client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "2900.00"},
        ).json()
        assert Decimal(receipt["unallocated"]) == Decimal("1450.00")
        detail = client.get(f"/leases/{world['lease']}").json()
        assert Decimal(detail["open_credit"]) == Decimal("1450.00")
        assert Decimal(detail["balance_due"]) == 0

        client.post("/sweep/rent-charges?as_of=2026-09-01")
        after = client.get(f"/leases/{world['lease']}").json()
        by_period = {c["period_start"]: c for c in after["charges"]}
        assert by_period["2026-09-01"]["status"] == "paid"
        assert Decimal(after["open_credit"]) == 0
        assert Decimal(after["balance_due"]) == 0
        # No late fee can ever accrue on the prepaid month.
        fees = client.post("/sweep/late-fees?as_of=2026-09-20").json()
        assert not any(g["lease_id"] == world["lease"] for g in fees["gaps"])


class TestTwoCreditsOneCharge:
    def test_the_second_credit_walks_past_an_exhausted_charge(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """Two prepayment receipts before any billing: the sweep's single
        application run must let the second credit skip the charge the first
        one filled."""
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-07-15", "amount": "1450.00"},
        )
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-07-20", "amount": "1450.00"},
        )
        assert Decimal(client.get(f"/leases/{world['lease']}").json()["open_credit"]) == Decimal(
            "2900.00"
        )
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        after = client.get(f"/leases/{world['lease']}").json()
        (charge,) = after["charges"]
        assert charge["status"] == "paid"
        assert Decimal(after["open_credit"]) == Decimal("1450.00")


class TestScheduleESigns:
    def test_a_net_refund_year_reads_as_recovery_not_expense(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        """The abs() finding: an insurance refund exceeding the year's
        premiums must show negative on line 9, never as fake expense."""
        client.post(
            "/ledger",
            json={
                "occurred_on": "2027-01-15",
                "category": "insurance",
                "amount": "1000.00",
                "memo": "carrier refund on cancellation",
                "property_id": world["property"],
            },
        )
        report = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2027"
        ).json()
        (line9,) = [row for row in report["expense_lines"] if row["line_no"] == 9]
        assert Decimal(line9["amount"]) == Decimal("-1000.00")
        assert Decimal(report["total_expenses"]) == Decimal("-1000.00")
        assert Decimal(report["net"]) == Decimal("1000.00")

    def test_signoff_goes_stale_when_the_numbers_move(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        client.post(
            "/ledger",
            json={
                "occurred_on": "2026-03-01",
                "category": "rent",
                "amount": "1450.00",
                "property_id": world["property"],
            },
        )
        client.post(
            "/reports/signoff",
            json={
                "property_id": world["property"],
                "tax_year": 2026,
                "report_kind": "schedule_e",
                "confirmed_by": "Jane CPA",
            },
        )
        fresh = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        assert fresh["signoff"]["stale"] is False
        # A back-dated correction lands after certification.
        client.post(
            "/ledger",
            json={
                "occurred_on": "2026-06-01",
                "category": "repairs",
                "amount": "-500.00",
                "property_id": world["property"],
            },
        )
        stale = client.get(
            f"/properties/{world['property']}/reports/schedule-e?tax_year=2026"
        ).json()
        assert stale["signoff"]["stale"] is True
        assert stale["signoff"]["confirmed_by"] == "Jane CPA"


class TestPaymentsHardening:
    @pytest.fixture(autouse=True)
    def _keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HESTIA_STRIPE_SECRET_KEY", "sk_test_fixture")
        monkeypatch.setenv("HESTIA_STRIPE_WEBHOOK_SECRET", SECRET)

    def test_collect_refuses_a_second_in_flight_request(
        self, world: dict[str, str], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        monkeypatch.setattr(
            payments, "live_transport", lambda *a: {"id": "pi_1", "client_secret": "s"}
        )
        assert client.post(f"/leases/{world['lease']}/collect", json={}).status_code == 201
        second = client.post(f"/leases/{world['lease']}/collect", json={})
        assert second.status_code == 409
        assert "in flight" in second.json()["detail"]

    def test_collect_nets_open_credit_out_of_the_default_amount(
        self, world: dict[str, str], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")
        client.post("/sweep/rent-charges?as_of=2026-09-01")
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "1450.00"},
        )
        seen: dict[str, Any] = {}

        def transport(url: str, headers: dict[str, str], form: dict[str, str]) -> dict[str, Any]:
            seen.update(form)
            return {"id": "pi_2", "client_secret": "s"}

        monkeypatch.setattr(payments, "live_transport", transport)
        response = client.post(f"/leases/{world['lease']}/collect", json={})
        assert response.status_code == 201
        assert seen["amount"] == "145000"  # September only; August was paid

    def test_transport_failure_cancels_the_request_as_a_502(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client.post("/sweep/rent-charges?as_of=2026-08-01")

        def broken(*args: Any) -> dict[str, Any]:
            raise OSError("connection refused")

        monkeypatch.setattr(payments, "live_transport", broken)
        response = client.post(f"/leases/{world['lease']}/collect", json={})
        assert response.status_code == 502
        assert "connection refused" in response.json()["detail"]
        # The transaction rolled back: NO phantom in-flight request survives.
        row = conn.execute(
            "SELECT count(*) AS n FROM payment_requests WHERE lease_id = %s",
            (world["lease"],),
        ).fetchone()
        assert row is not None and row["n"] == 0
        # And the lease is free to collect again.
        monkeypatch.setattr(
            payments, "live_transport", lambda *a: {"id": "pi_3", "client_secret": "s"}
        )
        assert client.post(f"/leases/{world['lease']}/collect", json={}).status_code == 201

    def test_signature_rotation_and_hostile_bodies(self) -> None:
        now = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
        body = json.dumps({"type": "ping"}).encode()
        stamp = int(now.timestamp())
        good = hmac.new(SECRET.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
        # Rotation: an old-secret signature first, the valid one second — and
        # Stripe's real headers also carry v0 entries and no-equals junk that
        # the parser must walk past.
        header = f"t={stamp},v0=legacy,ignored,v1={'0' * 64},v1={good}"
        assert payments.verify_signature(body, header, SECRET, now=now) == {"type": "ping"}
        # Non-UTF-8 bytes must yield a typed 400, never a crash.
        hostile = b"\xff\xfe not json"
        hostile_sig = hmac.new(
            SECRET.encode(), f"{stamp}.".encode() + hostile, hashlib.sha256
        ).hexdigest()
        with pytest.raises(payments.BadSignature, match="not valid JSON"):
            payments.verify_signature(hostile, f"t={stamp},v1={hostile_sig}", SECRET, now=now)

    def test_unconfigured_webhook_secret_is_a_503(
        self, world: dict[str, str], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HESTIA_STRIPE_WEBHOOK_SECRET", raising=False)
        response = client.post(
            "/payments/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"}
        )
        assert response.status_code == 503


class TestBankImportHardening:
    def test_deciding_twice_is_a_conflict_not_a_double_post(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        account = client.post(
            "/bank/accounts",
            json={"entity_id": world["entity"], "nickname": "Guard", "kind": "checking"},
        ).json()
        csv_text = "Date,Description,Amount\n2026-08-14,DUKE ENERGY,-92.40\n"
        summary = client.post(
            f"/bank/accounts/{account['id']}/imports",
            files={"file": ("g.csv", csv_text.encode(), "text/csv")},
        ).json()
        (row,) = client.get(f"/bank/imports/{summary['batch_id']}/transactions").json()
        assert client.post(f"/bank/transactions/{row['id']}/accept", json={}).status_code == 201
        assert client.post(f"/bank/transactions/{row['id']}/accept", json={}).status_code == 409
        events = conn.execute(
            "SELECT count(*) AS n FROM ledger_events WHERE counterparty = 'DUKE ENERGY'"
        ).fetchone()
        assert events is not None and events["n"] == 1

    def test_duplicate_nickname_and_unit_label_are_409s(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        body = {"entity_id": world["entity"], "nickname": "Dup", "kind": "checking"}
        assert client.post("/bank/accounts", json=body).status_code == 201
        assert client.post("/bank/accounts", json=body).status_code == 409
        assert (
            client.post("/units", json={"property_id": world["property"], "label": "A"}).status_code
            == 409
        )
        malformed = client.post(
            "/bank/accounts",
            json={"entity_id": "not-a-uuid", "nickname": "X", "kind": "checking"},
        )
        assert malformed.status_code == 422

    def test_inverted_credit_card_convention_and_bom(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        account = client.post(
            "/bank/accounts",
            json={
                "entity_id": world["entity"],
                "nickname": "Card",
                "kind": "credit_card",
                "invert_amounts": True,
            },
        ).json()
        # A BOM-prefixed export (Excel's signature) with charges printed
        # POSITIVE, the typical card convention.
        csv_text = "﻿Date,Description,Amount\n2026-08-16,HOME DEPOT,380.00\n"
        summary = client.post(
            f"/bank/accounts/{account['id']}/imports",
            files={"file": ("card.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        assert summary.status_code == 201
        (row,) = client.get(f"/bank/imports/{summary.json()['batch_id']}/transactions").json()
        assert Decimal(row["amount"]) == Decimal("-380.00")  # money OUT
