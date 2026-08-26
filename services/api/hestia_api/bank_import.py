"""The bank-import pipeline: file -> staging -> suggestion -> review -> ledger.

The ledger's append-only law is preserved by construction: everything here
mutates only the STAGING tables, and exactly one path — accept — appends
ledger rows (through hestia_api.ledger, the same door manual entries use).
Re-importing an overlapping statement dedupes at the database (unique key);
re-uploading the same file dedupes at the document (content hash).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from decimal import Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

from hestia_api import ledger as ledger_module
from hestia_api import statement_parse

Conn = psycopg.Connection[dict[str, Any]]


class DuplicateStatement(Exception):
    """This exact file was already imported (content hash match)."""


class UnknownAccount(Exception):
    pass


class UnknownTransaction(Exception):
    pass


class NotPending(Exception):
    """The row already has a disposition; review decisions are not re-made."""


class SplitMismatch(Exception):
    """Split amounts must sum to the bank row's amount exactly."""


class MatchMismatch(Exception):
    """A matched ledger event must carry the bank row's exact amount."""


class BankAccountIn(BaseModel):
    entity_id: str
    property_id: str | None = None
    nickname: str = Field(min_length=1, max_length=120)
    institution: str | None = None
    account_last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    kind: Literal["checking", "savings", "credit_card", "escrow"]


class BankAccountOut(BankAccountIn):
    id: str
    is_active: bool


class ImportSummary(BaseModel):
    batch_id: str
    format: str
    staged: int
    duplicates: int
    suggested: int


class StagedTransaction(BaseModel):
    id: str
    posted_on: dt.date
    amount: Decimal
    description: str
    suggested_category: str | None
    suggested_property_id: str | None
    suggested_is_capital: bool | None
    suggestion_confidence: float | None
    needs_review: bool
    disposition: str


class SplitIn(BaseModel):
    category: ledger_module.LedgerCategory
    amount: Decimal = Field(decimal_places=2, max_digits=18)
    memo: str | None = None
    is_capital: bool | None = None
    capitalisation_rationale: str | None = None


class AcceptIn(BaseModel):
    category: ledger_module.LedgerCategory | None = None
    property_id: str | None = None
    memo: str | None = None
    is_capital: bool | None = None
    capitalisation_rationale: str | None = None
    # A mortgage payment becomes interest + principal + escrow in one accept;
    # amounts must sum to the bank row's amount exactly.
    splits: list[SplitIn] | None = None


def create_account(conn: Conn, body: BankAccountIn) -> BankAccountOut:
    row = conn.execute(
        """
        INSERT INTO bank_accounts
          (entity_id, property_id, nickname, institution, account_last4, kind)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id::text, is_active
        """,
        (
            body.entity_id,
            body.property_id,
            body.nickname,
            body.institution,
            body.account_last4,
            body.kind,
        ),
    ).fetchone()
    return BankAccountOut(id=row["id"], is_active=row["is_active"], **body.model_dump())  # type: ignore[index]


def list_accounts(conn: Conn) -> list[BankAccountOut]:
    rows = conn.execute(
        """
        SELECT id::text, entity_id::text, property_id::text, nickname, institution,
               account_last4, kind::text, is_active
        FROM bank_accounts ORDER BY created_at
        """
    ).fetchall()
    return [BankAccountOut(**row) for row in rows]


def _dedupe_key(account_id: str, txn: statement_parse.ParsedTransaction, occurrence: int) -> str:
    if txn.fitid:
        basis = f"{account_id}|fitid|{txn.fitid}"
    else:
        basis = (
            f"{account_id}|{txn.posted_on.isoformat()}|{txn.amount}"
            f"|{statement_parse.normalise_description(txn.description)}|{occurrence}"
        )
    return hashlib.sha256(basis.encode()).hexdigest()


def _apply_rules(conn: Conn, account: dict[str, Any], batch_id: str) -> int:
    """First matching active rule per pending row, priority order. A hit with
    an OPEN capital question (is_capital_hint NULL) keeps needs_review true;
    every suggestion is provenance-carrying (rule id + modest confidence)."""
    rules = conn.execute(
        """
        SELECT id::text, pattern, match_kind::text, min_amount, max_amount,
               category::text, is_capital_hint, property_id::text
        FROM categorization_rules
        WHERE is_active
          AND (entity_id IS NULL OR entity_id = %s)
          AND (property_id IS NULL OR property_id IN
                 (SELECT id FROM properties WHERE entity_id = %s))
        ORDER BY priority, created_at
        """,
        (account["entity_id"], account["entity_id"]),
    ).fetchall()
    pending = conn.execute(
        """
        SELECT id::text, amount, normalised_description
        FROM bank_transactions WHERE batch_id = %s AND disposition = 'pending'
        """,
        (batch_id,),
    ).fetchall()
    suggested = 0
    for row in pending:
        for rule in rules:
            if not _rule_matches(rule, row):
                continue
            conn.execute(
                """
                UPDATE bank_transactions
                SET suggested_category = %s,
                    suggested_property_id = COALESCE(%s::uuid, %s::uuid),
                    suggested_is_capital = %s,
                    suggestion_confidence = 0.7,
                    rule_id = %s,
                    needs_review = TRUE
                WHERE id = %s
                """,
                (
                    rule["category"],
                    rule["property_id"],
                    account["property_id"],
                    rule["is_capital_hint"],
                    rule["id"],
                    row["id"],
                ),
            )
            suggested += 1
            break
    return suggested


def _rule_matches(rule: dict[str, Any], row: dict[str, Any]) -> bool:
    text = row["normalised_description"]
    pattern = rule["pattern"].lower()
    if rule["match_kind"] == "exact":
        if text != pattern:
            return False
    elif rule["match_kind"] == "regex":
        if not re.search(rule["pattern"], text, re.I):
            return False
    elif pattern not in text:
        return False
    magnitude = abs(row["amount"])
    if rule["min_amount"] is not None and magnitude < rule["min_amount"]:
        return False
    return not (rule["max_amount"] is not None and magnitude > rule["max_amount"])


def import_statement(
    conn: Conn, account_id: str, *, filename: str, content: bytes, imported_by: str
) -> ImportSummary:
    account = conn.execute(
        "SELECT id::text, entity_id::text, property_id::text FROM bank_accounts WHERE id = %s",
        (account_id,),
    ).fetchone()
    if account is None:
        raise UnknownAccount(account_id)

    content_hash = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT 1 AS x FROM source_documents WHERE content_hash = %s", (content_hash,)
    ).fetchone()
    if existing is not None:
        raise DuplicateStatement(filename)

    text = content.decode("utf-8", errors="replace")
    fmt, rows = statement_parse.parse_statement(filename, text)

    document = conn.execute(
        """
        INSERT INTO source_documents (kind, filename, content_hash, byte_size, uploaded_by)
        VALUES ('bank_statement', %s, %s, %s, %s) RETURNING id::text
        """,
        (filename, content_hash, len(content), imported_by),
    ).fetchone()
    batch = conn.execute(
        """
        INSERT INTO bank_import_batches
          (bank_account_id, source_document_id, format, row_count, status, imported_by)
        VALUES (%s, %s, %s, %s, 'in_review', %s) RETURNING id::text
        """,
        (account_id, document["id"], fmt, len(rows), imported_by),  # type: ignore[index]
    ).fetchone()
    batch_id: str = batch["id"]  # type: ignore[index]

    occurrences: dict[tuple[dt.date, Decimal, str], int] = {}
    staged = 0
    duplicates = 0
    for txn in rows:
        normalised = statement_parse.normalise_description(txn.description)
        signature = (txn.posted_on, txn.amount, normalised)
        occurrences[signature] = occurrences.get(signature, 0) + 1
        inserted = conn.execute(
            """
            INSERT INTO bank_transactions
              (batch_id, bank_account_id, posted_on, amount, description,
               normalised_description, fitid, dedupe_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bank_account_id, dedupe_key) DO NOTHING
            """,
            (
                batch_id,
                account_id,
                txn.posted_on,
                txn.amount,
                txn.description,
                normalised,
                txn.fitid,
                _dedupe_key(account_id, txn, occurrences[signature]),
            ),
        )
        if inserted.rowcount == 1:
            staged += 1
        else:
            duplicates += 1

    suggested = _apply_rules(conn, account, batch_id)
    if staged == 0:
        conn.execute("UPDATE bank_import_batches SET status = 'posted' WHERE id = %s", (batch_id,))
    return ImportSummary(
        batch_id=batch_id,
        format=fmt,
        staged=staged,
        duplicates=duplicates,
        suggested=suggested,
    )


def review_queue(conn: Conn, batch_id: str, disposition: str | None) -> list[StagedTransaction]:
    rows = conn.execute(
        """
        SELECT id::text, posted_on, amount, description, suggested_category::text,
               suggested_property_id::text, suggested_is_capital,
               suggestion_confidence::float, needs_review, disposition::text
        FROM bank_transactions
        WHERE batch_id = %(batch_id)s
          AND (%(disposition)s::txn_disposition IS NULL
               OR disposition = %(disposition)s)
        ORDER BY posted_on, created_at
        """,
        {"batch_id": batch_id, "disposition": disposition},
    ).fetchall()
    return [StagedTransaction(**row) for row in rows]


def _load_pending(conn: Conn, txn_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT t.id::text, t.bank_account_id::text, t.batch_id::text, t.posted_on,
               t.amount, t.description, t.suggested_category::text,
               t.suggested_property_id::text, t.suggested_is_capital,
               t.disposition::text, b.source_document_id::text,
               a.entity_id::text, a.property_id::text AS account_property_id
        FROM bank_transactions t
        JOIN bank_import_batches b ON b.id = t.batch_id
        JOIN bank_accounts a ON a.id = t.bank_account_id
        WHERE t.id = %s
        """,
        (txn_id,),
    ).fetchone()
    if row is None:
        raise UnknownTransaction(txn_id)
    if row["disposition"] != "pending":
        raise NotPending(txn_id)
    return row


def _settle_batch(conn: Conn, batch_id: str) -> None:
    conn.execute(
        """
        UPDATE bank_import_batches SET status = 'posted'
        WHERE id = %s AND NOT EXISTS
          (SELECT 1 FROM bank_transactions
           WHERE batch_id = %s AND disposition = 'pending')
        """,
        (batch_id, batch_id),
    )


def accept(conn: Conn, txn_id: str, body: AcceptIn) -> list[ledger_module.LedgerEventOut]:
    """One bank row becomes one ledger event — or several, when split. Every
    event carries the statement document id; the row links the first event
    and the audit record carries them all."""
    row = _load_pending(conn, txn_id)
    property_id = body.property_id or row["suggested_property_id"] or row["account_property_id"]
    parts: list[SplitIn]
    if body.splits:
        total = sum(split.amount for split in body.splits)
        if total != row["amount"]:
            raise SplitMismatch(f"splits sum to {total}, bank row is {row['amount']}")
        parts = body.splits
    else:
        category = body.category or row["suggested_category"]
        if category is None:
            raise SplitMismatch("no category: none suggested and none provided")
        is_capital = body.is_capital if body.is_capital is not None else row["suggested_is_capital"]
        parts = [
            SplitIn(
                category=category,  # type: ignore[arg-type]
                amount=row["amount"],
                memo=body.memo or row["description"],
                is_capital=is_capital,
                capitalisation_rationale=body.capitalisation_rationale,
            )
        ]
    events: list[ledger_module.LedgerEventOut] = []
    for part in parts:
        entry = ledger_module.LedgerEntryIn(
            occurred_on=row["posted_on"],
            category=part.category,
            amount=part.amount,
            memo=part.memo or row["description"],
            counterparty=row["description"],
            is_capital=part.is_capital,
            capitalisation_rationale=part.capitalisation_rationale,
            property_id=property_id,
            entity_id=None if property_id else row["entity_id"],
            document_id=row["source_document_id"],
        )
        events.append(ledger_module.append_event(conn, entry))
    first_event = conn.execute(
        "SELECT id FROM ledger_events WHERE event_uuid = %s", (events[0].event_uuid,)
    ).fetchone()
    conn.execute(
        """
        UPDATE bank_transactions
        SET disposition = 'accepted', needs_review = FALSE, ledger_event_id = %s
        WHERE id = %s
        """,
        (first_event["id"], txn_id),  # type: ignore[index]
    )
    _settle_batch(conn, row["batch_id"])
    return events


def exclude(conn: Conn, txn_id: str) -> None:
    row = _load_pending(conn, txn_id)
    conn.execute(
        """
        UPDATE bank_transactions
        SET disposition = 'excluded', needs_review = FALSE WHERE id = %s
        """,
        (txn_id,),
    )
    _settle_batch(conn, row["batch_id"])


def match_existing(conn: Conn, txn_id: str, event_uuid: str) -> None:
    """Link a bank row to an already-recorded ledger event instead of
    double-posting — the row a manual entry already captured."""
    row = _load_pending(conn, txn_id)
    event = conn.execute(
        "SELECT id, amount FROM ledger_events WHERE event_uuid = %s", (event_uuid,)
    ).fetchone()
    if event is None:
        raise UnknownTransaction(event_uuid)
    if event["amount"] != row["amount"]:
        raise MatchMismatch(f"ledger event is {event['amount']}, bank row is {row['amount']}")
    conn.execute(
        """
        UPDATE bank_transactions
        SET disposition = 'matched_existing', needs_review = FALSE, ledger_event_id = %s
        WHERE id = %s
        """,
        (event["id"], txn_id),
    )
    _settle_batch(conn, row["batch_id"])
