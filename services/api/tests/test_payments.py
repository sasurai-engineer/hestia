"""The Stripe seam, hermetically: signature law, collect, webhook settlement."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import payments

SECRET = "whsec_test_fixture"  # noqa: S105  # config-audit: allow — test fixture


def sign(payload: dict[str, Any], *, at: int, secret: str = SECRET) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    mac = hmac.new(secret.encode(), f"{at}.{body.decode()}".encode(), hashlib.sha256)
    return body, f"t={at},v1={mac.hexdigest()}"


NOW = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)


class TestSignature:
    def test_accepts_a_valid_recent_signature(self) -> None:
        body, header = sign({"type": "ping"}, at=int(NOW.timestamp()) - 10)
        assert payments.verify_signature(body, header, SECRET, now=NOW) == {"type": "ping"}

    def test_refuses_tampering_staleness_and_malformed_headers(self) -> None:
        at = int(NOW.timestamp())
        body, header = sign({"type": "ping"}, at=at)
        with pytest.raises(payments.BadSignature, match="mismatch"):
            payments.verify_signature(body + b" ", header, SECRET, now=NOW)
        with pytest.raises(payments.BadSignature, match="mismatch"):
            payments.verify_signature(body, header, "whsec_other", now=NOW)
        stale_body, stale_header = sign({"type": "ping"}, at=at - 4000)
        with pytest.raises(payments.BadSignature, match="tolerance"):
            payments.verify_signature(stale_body, stale_header, SECRET, now=NOW)
        with pytest.raises(payments.BadSignature, match="malformed"):
            payments.verify_signature(body, "v1=deadbeef", SECRET, now=NOW)
        with pytest.raises(payments.BadSignature, match="malformed"):
            payments.verify_signature(body, "t=abc,v1=deadbeef", SECRET, now=NOW)


class TestLiveTransport:
    def test_posts_form_encoded_json_against_a_local_socket(self) -> None:
        import http.server
        import threading

        received: dict[str, Any] = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                received["body"] = self.rfile.read(length).decode()
                received["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id": "pi_local"}')

            def log_message(self, *args: Any) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/v1/payment_intents"
            result = payments.live_transport(
                url, {"Authorization": "Bearer sk_test_local"}, {"amount": "145000"}
            )
            assert result == {"id": "pi_local"}
            assert received["auth"] == "Bearer sk_test_local"
            assert "amount=145000" in received["body"]
        finally:
            server.shutdown()


@pytest.fixture
def world(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "P4", "kind": "llc"}).json()["id"]
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
    client.post("/sweep/rent-charges?as_of=2026-08-01")
    return {"lease": lease_id, "property": property_id}


class TestCollect:
    def test_unconfigured_payments_say_so(
        self, world: dict[str, str], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HESTIA_STRIPE_SECRET_KEY", raising=False)
        response = client.post(f"/leases/{world['lease']}/collect", json={})
        assert response.status_code == 503
        assert "HESTIA_STRIPE_SECRET_KEY" in response.json()["detail"]

    def test_collect_creates_the_intent_from_the_balance(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HESTIA_STRIPE_SECRET_KEY", "sk_test_fixture")
        seen: dict[str, Any] = {}

        def transport(url: str, headers: dict[str, str], form: dict[str, str]) -> dict[str, Any]:
            seen.update({"url": url, "headers": headers, "form": form})
            return {"id": "pi_test_1", "client_secret": "pi_test_1_secret"}

        monkeypatch.setattr(payments, "live_transport", transport)
        response = client.post(f"/leases/{world['lease']}/collect", json={})
        assert response.status_code == 201
        body = response.json()
        assert body["provider_ref"] == "pi_test_1"
        assert Decimal(body["amount"]) == Decimal("1450.00")  # the outstanding balance
        assert body["status"] == "processing"
        assert seen["url"].endswith("/payment_intents")
        assert seen["headers"]["Authorization"] == "Bearer sk_test_fixture"
        assert seen["form"]["amount"] == "145000"
        assert seen["form"]["payment_method_types[]"] == "us_bank_account"
        assert seen["form"]["metadata[payment_request_id]"] == body["payment_request_id"]
        row = conn.execute(
            "SELECT status::text, provider_ref FROM payment_requests WHERE id = %s",
            (body["payment_request_id"],),
        ).fetchone()
        assert row is not None
        assert (row["status"], row["provider_ref"]) == ("processing", "pi_test_1")

    def test_nothing_outstanding_is_a_422_and_ghosts_404(
        self, world: dict[str, str], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HESTIA_STRIPE_SECRET_KEY", "sk_test_fixture")
        monkeypatch.setattr(
            payments, "live_transport", lambda *a: {"id": "pi_x", "client_secret": "s"}
        )
        client.post(
            f"/leases/{world['lease']}/receipts",
            json={"occurred_on": "2026-08-01", "amount": "1450.00"},
        )
        paid_off = client.post(f"/leases/{world['lease']}/collect", json={})
        assert paid_off.status_code == 422
        assert client.post(f"/leases/{uuid.uuid4()}/collect", json={}).status_code == 404


class TestWebhook:
    def _post_event(
        self, client: TestClient, event: dict[str, Any], *, at: int | None = None
    ) -> Any:
        stamp = at if at is not None else int(dt.datetime.now(tz=dt.UTC).timestamp())
        body, header = sign(event, at=stamp)
        return client.post(
            "/payments/stripe/webhook",
            content=body,
            headers={"stripe-signature": header, "content-type": "application/json"},
        )

    @pytest.fixture(autouse=True)
    def _webhook_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HESTIA_STRIPE_WEBHOOK_SECRET", SECRET)

    def _collected(
        self, world: dict[str, str], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> str:
        monkeypatch.setenv("HESTIA_STRIPE_SECRET_KEY", "sk_test_fixture")
        monkeypatch.setattr(
            payments,
            "live_transport",
            lambda *a: {"id": "pi_settle_1", "client_secret": "s"},
        )
        client.post(f"/leases/{world['lease']}/collect", json={})
        return "pi_settle_1"

    def test_succeeded_posts_the_receipt_idempotently(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ref = self._collected(world, client, monkeypatch)
        event = {
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": ref, "created": 1756209600}},  # 2026-08-26
        }
        response = self._post_event(client, event)
        assert response.status_code == 200
        assert response.json()["outcome"] == "receipt posted"
        detail = client.get(f"/leases/{world['lease']}").json()
        assert Decimal(detail["balance_due"]) == 0
        (charge,) = detail["charges"]
        assert charge["status"] == "paid"
        row = conn.execute(
            "SELECT status::text, ledger_event_id FROM payment_requests WHERE provider_ref = %s",
            (ref,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["ledger_event_id"] is not None
        ledger_row = conn.execute(
            "SELECT memo, category::text FROM ledger_events WHERE id = %s",
            (row["ledger_event_id"],),
        ).fetchone()
        assert ledger_row is not None
        assert "pi_settle_1" in ledger_row["memo"]
        # A webhook retry settles nothing twice.
        again = self._post_event(client, event)
        assert again.json()["outcome"] == "already settled"
        assert Decimal(client.get(f"/leases/{world['lease']}").json()["balance_due"]) == 0

    def test_failure_is_recorded_with_its_reason(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ref = self._collected(world, client, monkeypatch)
        response = self._post_event(
            client,
            {
                "type": "payment_intent.payment_failed",
                "data": {
                    "object": {
                        "id": ref,
                        "last_payment_error": {"message": "insufficient funds"},
                    }
                },
            },
        )
        assert response.json()["outcome"] == "recorded failure"
        row = conn.execute(
            "SELECT status::text, failure_detail FROM payment_requests WHERE provider_ref = %s",
            (ref,),
        ).fetchone()
        assert row is not None
        assert (row["status"], row["failure_detail"]) == ("failed", "insufficient funds")

    def test_unknown_refs_and_foreign_events_are_named_not_errored(
        self, world: dict[str, str], client: TestClient
    ) -> None:
        response = self._post_event(
            client,
            {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_ghost"}}},
        )
        assert response.json()["outcome"] == "ignored: no payment request for pi_ghost"
        other = self._post_event(client, {"type": "charge.refunded"})
        assert other.json()["outcome"] == "ignored: charge.refunded"

    def test_bad_signatures_bounce(self, world: dict[str, str], client: TestClient) -> None:
        body = json.dumps({"type": "ping"}).encode()
        response = client.post(
            "/payments/stripe/webhook",
            content=body,
            headers={"stripe-signature": "t=1,v1=deadbeef"},
        )
        assert response.status_code == 400
