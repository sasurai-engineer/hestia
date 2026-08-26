"""The payments seam: Stripe ACH behind an injected transport.

Test mode runs today (a Stripe test key needs no LLC); live keys drop in
when the business bank account exists — nothing else changes. CI never
touches Stripe: the transport is injected exactly like the dossier's fetch,
and webhook signatures verify against the documented HMAC scheme with an
injectable clock. The only ledger touch in this module is the receipt
appended when a payment SUCCEEDS, through the same rent.record_receipt door
a hand-typed check uses.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import psycopg
from pydantic import BaseModel

from hestia_api import rent as rent_module

Conn = psycopg.Connection[dict[str, Any]]

#: (url, headers, form fields) -> parsed JSON response.
Transport = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]

STRIPE_API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_SECONDS = 300


class PaymentsNotConfigured(Exception):
    pass


class BadSignature(Exception):
    pass


class UnknownPayment(Exception):
    pass


class OpenPaymentExists(Exception):
    """A created/processing request already exists for this lease — a retry
    or double-click must not mint a second live PaymentIntent."""


class TransportFailure(Exception):
    """Stripe could not be reached; the local request is canceled, not left
    dangling as a phantom charge-in-flight."""


def live_transport(url: str, headers: dict[str, str], form: dict[str, str]) -> dict[str, Any]:
    """The one real HTTP door; everything else is pure."""
    request = urllib.request.Request(  # noqa: S310 - stripe.com only, built above
        url, data=urllib.parse.urlencode(form).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())  # type: ignore[no-any-return]


def create_payment_intent(
    transport: Transport, secret_key: str, *, amount_cents: int, metadata: dict[str, str]
) -> dict[str, Any]:
    form: dict[str, str] = {
        "amount": str(amount_cents),
        "currency": "usd",
        "payment_method_types[]": "us_bank_account",
    }
    for key, value in metadata.items():
        form[f"metadata[{key}]"] = value
    return transport(
        f"{STRIPE_API}/payment_intents",
        {"Authorization": f"Bearer {secret_key}"},
        form,
    )


def verify_signature(
    payload: bytes, header: str, secret: str, *, now: dt.datetime
) -> dict[str, Any]:
    """Stripe's scheme: `t=<ts>,v1=<hex>` where v1 = HMAC-SHA256(secret,
    f"{t}.{payload}"). Stale timestamps are refused to kill replay."""
    timestamp = None
    signatures: list[str] = []
    for part in header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == "t":
            timestamp = value.strip()
        elif key.strip() == "v1":
            # Secret rotation sends MULTIPLE v1 signatures; any match passes.
            signatures.append(value.strip())
    if not timestamp or not signatures or not timestamp.isdigit():
        raise BadSignature("malformed Stripe-Signature header")
    # HMAC over the RAW bytes — never a decode a hostile body can crash.
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise BadSignature("signature mismatch")
    age = abs(int(now.timestamp()) - int(timestamp))
    if age > SIGNATURE_TOLERANCE_SECONDS:
        raise BadSignature(f"timestamp outside tolerance ({age}s)")
    try:
        return json.loads(payload)  # type: ignore[no-any-return]
    except ValueError as error:
        raise BadSignature("signed payload is not valid JSON") from error


class CollectOut(BaseModel):
    payment_request_id: str
    provider_ref: str
    client_secret: str | None
    amount: Decimal
    status: str


def collect(
    conn: Conn,
    lease_id: str,
    *,
    amount: Decimal | None,
    transport: Transport,
    secret_key: str,
) -> CollectOut:
    """Create the payment request and its PaymentIntent. One open request
    per lease at a time; the default amount is what is actually owed —
    outstanding charges net of open credit."""
    detail = rent_module.lease_detail(conn, lease_id)
    open_request = conn.execute(
        """
        SELECT provider_ref FROM payment_requests
        WHERE lease_id = %s AND status IN ('created', 'processing')
        FOR UPDATE
        """,
        (lease_id,),
    ).fetchone()
    if open_request is not None:
        raise OpenPaymentExists(open_request["provider_ref"] or lease_id)
    effective = amount if amount is not None else detail.balance_due - detail.open_credit
    if effective <= 0:
        raise rent_module.NothingOutstanding(lease_id)
    row = conn.execute(
        """
        INSERT INTO payment_requests (lease_id, amount, provider)
        VALUES (%s, %s, 'stripe') RETURNING id::text
        """,
        (lease_id, effective),
    ).fetchone()
    request_id: str = row["id"]  # type: ignore[index]
    try:
        intent = create_payment_intent(
            transport,
            secret_key,
            amount_cents=int(effective * 100),
            metadata={"payment_request_id": request_id, "lease_id": lease_id},
        )
    except Exception as error:  # transport is injected; any failure lands here
        # The endpoint's transaction rolls back on this raise, wiping the
        # request row itself — no phantom in-flight payment survives, and the
        # lease is immediately free to retry.
        raise TransportFailure(str(error)) from error
    conn.execute(
        "UPDATE payment_requests SET provider_ref = %s, status = 'processing' WHERE id = %s",
        (intent["id"], request_id),
    )
    return CollectOut(
        payment_request_id=request_id,
        provider_ref=intent["id"],
        # A Stripe response field NAME, not a stored value:
        client_secret=intent.get("client_secret"),  # config-audit: allow
        amount=effective,
        status="processing",
    )


def handle_event(conn: Conn, event: dict[str, Any]) -> str:
    """payment_intent.succeeded posts the receipt (idempotently — a webhook
    retry is a no-op); payment_intent.payment_failed records why. Everything
    else is acknowledged and ignored by name."""
    kind = event.get("type", "")
    if kind not in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        return f"ignored: {kind or 'untyped event'}"
    intent = event["data"]["object"]
    request = conn.execute(
        """
        SELECT id::text, lease_id::text, amount, status::text
        FROM payment_requests WHERE provider_ref = %s
        FOR UPDATE
        """,
        (intent["id"],),
    ).fetchone()
    if request is None:
        return f"ignored: no payment request for {intent['id']}"
    if kind == "payment_intent.payment_failed":
        conn.execute(
            """
            UPDATE payment_requests SET status = 'failed', failure_detail = %s
            WHERE id = %s AND status <> 'succeeded'
            """,
            (
                (intent.get("last_payment_error") or {}).get("message", "failed"),
                request["id"],
            ),
        )
        return "recorded failure"
    if request["status"] == "succeeded":
        return "already settled"
    receipt = rent_module.record_receipt(
        conn,
        request["lease_id"],
        rent_module.ReceiptIn(
            occurred_on=dt.datetime.fromtimestamp(intent.get("created", 0), tz=dt.UTC).date(),
            amount=request["amount"],
            memo=f"Stripe ACH {intent['id']}",
        ),
    )
    event_id = conn.execute(
        "SELECT id FROM ledger_events WHERE event_uuid = %s", (receipt.event_uuid,)
    ).fetchone()["id"]  # type: ignore[index]
    conn.execute(
        """
        UPDATE payment_requests SET status = 'succeeded', ledger_event_id = %s
        WHERE id = %s
        """,
        (event_id, request["id"]),
    )
    return "receipt posted"
