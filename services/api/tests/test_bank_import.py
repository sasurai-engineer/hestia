"""The bank-import pipeline end to end: file in, review queue, ledger out."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

CSV_ONE = """Date,Description,Amount
2026-08-01,ZELLE TENANT AUGUST,1450.00
2026-08-14,DUKE ENERGY BILL PAY,-92.40
2026-08-16,HOME DEPOT #4821,-380.00
2026-08-16,HOME DEPOT #4821,-380.00
2026-08-19,MYSTERY VENDOR LLC,-55.00
"""

# Overlaps CSV_ONE (all five rows) and adds one new row.
CSV_TWO = CSV_ONE + "2026-08-28,SASURAI MORTGAGE LOAN PYMT,-1500.00\n"

OFX_ONE = """OFXHEADER:100
<OFX><BANKTRANLIST>
<STMTTRN><DTPOSTED>20260901<TRNAMT>-92.40<FITID>F-100<NAME>DUKE ENERGY
</STMTTRN>
</BANKTRANLIST></OFX>
"""


def _upload(client: TestClient, account_id: str, name: str, text: str) -> Any:
    return client.post(
        f"/bank/accounts/{account_id}/imports",
        files={"file": (name, text.encode(), "text/csv")},
    )


@pytest.fixture
def world(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "B", "kind": "llc"}).json()["id"]
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
    account = client.post(
        "/bank/accounts",
        json={
            "entity_id": entity_id,
            "property_id": property_id,
            "nickname": "Maple Operating",
            "institution": "Test Bank",
            "account_last4": "4821",
            "kind": "checking",
        },
    )
    assert account.status_code == 201
    return {"entity": entity_id, "property": property_id, "account": account.json()["id"]}


class TestAccounts:
    def test_create_and_list(self, world: dict[str, str], client: TestClient) -> None:
        accounts = client.get("/bank/accounts").json()
        assert [a["nickname"] for a in accounts] == ["Maple Operating"]
        assert accounts[0]["is_active"] is True

    def test_a_bad_entity_is_named(self, world: dict[str, str], client: TestClient) -> None:
        response = client.post(
            "/bank/accounts",
            json={"entity_id": str(uuid.uuid4()), "nickname": "X", "kind": "checking"},
        )
        assert response.status_code == 422


class TestImport:
    def test_staging_suggestions_and_occurrences(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        summary = _upload(client, world["account"], "aug.csv", CSV_ONE)
        assert summary.status_code == 201
        body = summary.json()
        # Five rows staged — the two identical Home Depot charges BOTH stage
        # (occurrence numbering), because two identical charges in one
        # statement are two real purchases.
        assert body["staged"] == 5
        assert body["duplicates"] == 0
        assert body["format"] == "csv"
        # Rules: zelle->rent, duke->utilities, home depot x2 -> repairs; the
        # mystery vendor matches nothing.
        assert body["suggested"] == 4

        queue = client.get(f"/bank/imports/{body['batch_id']}/transactions").json()
        by_desc = {}
        for row in queue:
            by_desc.setdefault(row["description"], row)
        duke = by_desc["DUKE ENERGY BILL PAY"]
        assert duke["suggested_category"] == "utilities"
        assert duke["suggested_property_id"] == world["property"]  # from the account
        assert duke["suggested_is_capital"] is False
        assert duke["suggestion_confidence"] == 0.7
        assert duke["needs_review"] is True
        depot = by_desc["HOME DEPOT #4821"]
        assert depot["suggested_category"] == "repairs"
        assert depot["suggested_is_capital"] is None  # the capital question stays OPEN
        mystery = by_desc["MYSTERY VENDOR LLC"]
        assert mystery["suggested_category"] is None

    def test_reupload_of_the_same_file_is_a_409(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        assert _upload(client, world["account"], "aug.csv", CSV_ONE).status_code == 201
        again = _upload(client, world["account"], "aug-renamed.csv", CSV_ONE)
        assert again.status_code == 409

    def test_an_overlapping_statement_stages_only_the_new_row(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        _upload(client, world["account"], "aug.csv", CSV_ONE)
        summary = _upload(client, world["account"], "aug-full.csv", CSV_TWO).json()
        assert summary["staged"] == 1
        assert summary["duplicates"] == 5
        queue = client.get(f"/bank/imports/{summary['batch_id']}/transactions").json()
        assert [row["description"] for row in queue] == ["SASURAI MORTGAGE LOAN PYMT"]

    def test_ofx_dedupes_by_fitid(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        first = _upload(client, world["account"], "sept.ofx", OFX_ONE).json()
        assert (first["format"], first["staged"]) == ("ofx", 1)
        # Same FITID inside a different file: the bank's own identity wins.
        second = _upload(client, world["account"], "sept2.ofx", OFX_ONE + "\n").json()
        assert (second["staged"], second["duplicates"]) == (0, 1)
        # An all-duplicate batch settles itself immediately.
        status = conn.execute(
            "SELECT status::text FROM bank_import_batches WHERE id = %s",
            (second["batch_id"],),
        ).fetchone()
        assert status is not None and status["status"] == "posted"

    def test_parse_failures_and_unknown_accounts(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        bad = _upload(client, world["account"], "junk.csv", "a,b\n1,2\n")
        assert bad.status_code == 422
        missing = _upload(client, str(uuid.uuid4()), "aug.csv", CSV_ONE)
        assert missing.status_code == 404


class TestRuleMatching:
    """User rules with every match kind and amount window, via a real import."""

    CSV = """Date,Description,Amount
2026-08-01,EXACTLY THIS,-10.00
2026-08-02,PATTERN 123 MATCH,-500.00
2026-08-03,PATTERN 123 MATCH,-2500.00
2026-08-04,pattern 123 match,-99999.00
2026-08-05,PATTERN 7 MATCH,-50.00
2026-08-06,NO DIGITS AT ALL,-42.00
"""

    def test_exact_regex_and_amount_windows(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        conn.execute(
            """
            INSERT INTO categorization_rules
              (priority, pattern, match_kind, category, origin, entity_id) VALUES
              (10, 'exactly this', 'exact', 'supplies', 'user', %(entity)s),
              (11, 'pattern \\d+ match', 'regex', 'repairs', 'user', %(entity)s),
              (12, 'never fires: inactive', 'contains', 'travel', 'user', NULL)
            """,
            {"entity": world["entity"]},
        )
        conn.execute(
            "UPDATE categorization_rules SET is_active = FALSE"
            " WHERE pattern = 'never fires: inactive'"
        )
        conn.execute(
            """
            UPDATE categorization_rules
            SET min_amount = 100, max_amount = 10000
            WHERE pattern = 'pattern \\d+ match'
            """
        )
        conn.commit()
        summary = _upload(client, world["account"], "rules.csv", self.CSV).json()
        queue = client.get(f"/bank/imports/{summary['batch_id']}/transactions").json()
        by_amount = {row["amount"]: row for row in queue}
        assert by_amount["-10.00"]["suggested_category"] == "supplies"  # exact
        assert by_amount["-500.00"]["suggested_category"] == "repairs"  # regex in window
        assert by_amount["-2500.00"]["suggested_category"] == "repairs"
        # Outside the amount window (above and below) or matching no rule at
        # all: no suggestion — silence, never a guess.
        assert by_amount["-99999.00"]["suggested_category"] is None
        assert by_amount["-50.00"]["suggested_category"] is None
        assert by_amount["-42.00"]["suggested_category"] is None


class TestReviewDecisions:
    @pytest.fixture
    def queue(self, world: dict[str, str], client: TestClient) -> list[dict[str, Any]]:
        # Unique bytes per test: an accepted row PINS its statement document
        # past the clean (ledger_events_document_fk), so re-uploading the
        # identical file in the next test would 409 on the content hash.
        noise = f"2026-08-30,UNIQUE NOISE {uuid.uuid4()},-1.00\n"
        summary = _upload(client, world["account"], "aug.csv", CSV_TWO + noise).json()
        rows = client.get(f"/bank/imports/{summary['batch_id']}/transactions").json()
        return [row for row in rows if "UNIQUE NOISE" not in row["description"]]

    def _row(self, queue: list[dict[str, Any]], description: str) -> dict[str, Any]:
        return next(r for r in queue if r["description"] == description)

    def test_accept_with_suggestion_appends_the_ledger(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        queue: list[dict[str, Any]],
    ) -> None:
        duke = self._row(queue, "DUKE ENERGY BILL PAY")
        request_id = f"accept-{uuid.uuid4()}"
        response = client.post(
            f"/bank/transactions/{duke['id']}/accept",
            json={},
            headers={"x-request-id": request_id},
        )
        assert response.status_code == 201
        (event,) = response.json()
        assert event["category"] == "utilities"
        assert event["amount"] == "-92.40"
        assert event["property_id"] == world["property"]
        assert event["counterparty"] == "DUKE ENERGY BILL PAY"
        # The statement document travels with the ledger row.
        row = conn.execute(
            "SELECT document_id, memo FROM ledger_events WHERE event_uuid = %s",
            (event["event_uuid"],),
        ).fetchone()
        assert row is not None and row["document_id"] is not None
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE request_id = %s ORDER BY id",
            (request_id,),
        ).fetchall()
        assert [a["action"] for a in audit] == ["bank.accept"]
        # The queue row is linked and closed.
        linked = conn.execute(
            "SELECT disposition::text, ledger_event_id FROM bank_transactions WHERE id = %s",
            (duke["id"],),
        ).fetchone()
        assert linked is not None
        assert linked["disposition"] == "accepted"
        assert linked["ledger_event_id"] is not None

    def test_accept_without_category_anywhere_is_a_422(
        self, client: TestClient, queue: list[dict[str, Any]]
    ) -> None:
        mystery = self._row(queue, "MYSTERY VENDOR LLC")
        assert client.post(f"/bank/transactions/{mystery['id']}/accept", json={}).status_code == 422

    def test_accept_with_overrides_and_capital_rationale(
        self, client: TestClient, conn: psycopg.Connection[Any], queue: list[dict[str, Any]]
    ) -> None:
        depot = self._row(queue, "HOME DEPOT #4821")
        response = client.post(
            f"/bank/transactions/{depot['id']}/accept",
            json={
                "category": "capital_improvement",
                "is_capital": True,
                "capitalisation_rationale": "water heater replacement: restoration under BAR",
                "memo": "50-gal tank water heater",
            },
        )
        assert response.status_code == 201
        (event,) = response.json()
        assert event["is_capital"] is True
        assert event["memo"] == "50-gal tank water heater"

    def test_the_mortgage_split(
        self, client: TestClient, conn: psycopg.Connection[Any], queue: list[dict[str, Any]]
    ) -> None:
        mortgage = self._row(queue, "SASURAI MORTGAGE LOAN PYMT")
        wrong = client.post(
            f"/bank/transactions/{mortgage['id']}/accept",
            json={
                "splits": [
                    {"category": "mortgage_interest", "amount": "-900.00"},
                    {"category": "mortgage_principal", "amount": "-450.00"},
                ]
            },
        )
        assert wrong.status_code == 422
        assert "sum" in wrong.json()["detail"]
        response = client.post(
            f"/bank/transactions/{mortgage['id']}/accept",
            json={
                "splits": [
                    {"category": "mortgage_interest", "amount": "-900.00"},
                    {"category": "mortgage_principal", "amount": "-450.00"},
                    {"category": "insurance", "amount": "-150.00", "memo": "escrow"},
                ]
            },
        )
        assert response.status_code == 201
        events = response.json()
        assert [e["category"] for e in events] == [
            "mortgage_interest",
            "mortgage_principal",
            "insurance",
        ]
        assert sum(Decimal(e["amount"]) for e in events) == Decimal("-1500.00")
        linked = conn.execute(
            "SELECT ledger_event_id FROM bank_transactions WHERE id = %s",
            (mortgage["id"],),
        ).fetchone()
        assert linked is not None and linked["ledger_event_id"] is not None

    def test_exclude_match_and_batch_settlement(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        queue: list[dict[str, Any]],
    ) -> None:
        batch_id = conn.execute(
            "SELECT batch_id::text FROM bank_transactions WHERE id = %s",
            (queue[0]["id"],),
        ).fetchone()["batch_id"]  # type: ignore[index]

        # A manual entry already recorded the zelle rent; match, don't re-post.
        manual = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "1450.00",
                "property_id": world["property"],
            },
        ).json()
        zelle = self._row(queue, "ZELLE TENANT AUGUST")
        bad_match = client.post(
            f"/bank/transactions/{zelle['id']}/match",
            json={"event_uuid": str(uuid.uuid4())},
        )
        assert bad_match.status_code == 404
        wrong_amount = client.post(
            "/ledger",
            json={
                "occurred_on": "2026-08-01",
                "category": "rent",
                "amount": "10.00",
                "property_id": world["property"],
            },
        ).json()
        mismatch = client.post(
            f"/bank/transactions/{zelle['id']}/match",
            json={"event_uuid": wrong_amount["event_uuid"]},
        )
        assert mismatch.status_code == 422
        good = client.post(
            f"/bank/transactions/{zelle['id']}/match",
            json={"event_uuid": manual["event_uuid"]},
        )
        assert good.status_code == 204

        # A decided row cannot be re-decided.
        again = client.post(f"/bank/transactions/{zelle['id']}/exclude")
        assert again.status_code == 409

        # Clear EVERYTHING still pending (the fixture's noise row included)
        # and watch the batch settle.
        pending = client.get(f"/bank/imports/{batch_id}/transactions?disposition=pending").json()
        for row in pending:
            client.post(f"/bank/transactions/{row['id']}/exclude")
        status = conn.execute(
            "SELECT status::text FROM bank_import_batches WHERE id = %s", (batch_id,)
        ).fetchone()
        assert status is not None and status["status"] == "posted"
        # Filtered queue reads.
        excluded = client.get(f"/bank/imports/{batch_id}/transactions?disposition=excluded").json()
        assert len(excluded) == len(pending)

    def test_unknown_transaction_is_a_404(self, clean: None, client: TestClient) -> None:
        assert client.post(f"/bank/transactions/{uuid.uuid4()}/accept", json={}).status_code == 404
