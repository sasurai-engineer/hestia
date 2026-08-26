"""Pure statement parsing: CSV and OFX/QFX in, typed rows out. Stdlib only.

No provider SaaS touches bank data — the owner exports a file from any bank
and this module reads it. Formats in the wild are messy; the parsers here are
tolerant about headers, dates, and amount notation, and loud (typed errors
with row context) about everything they cannot read. Nothing here touches the
database: staging, dedupe, and suggestion live in bank_import.py.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class StatementParseError(Exception):
    """The file could not be read as a bank statement, and why."""


@dataclass(frozen=True)
class ParsedTransaction:
    posted_on: dt.date
    amount: Decimal  # signed: deposits positive, withdrawals negative
    description: str
    fitid: str | None = None


def normalise_description(description: str) -> str:
    return re.sub(r"\s+", " ", description).strip().lower()


DATE_HEADERS = ("posted date", "post date", "transaction date", "trans date", "date")
DESCRIPTION_HEADERS = ("description", "payee", "memo", "details", "transaction")
AMOUNT_HEADERS = ("amount",)
DEBIT_HEADERS = ("debit", "withdrawal", "withdrawals")
CREDIT_HEADERS = ("credit", "deposit", "deposits")

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%m-%d-%Y")


def _parse_date(raw: str, row_number: int) -> dt.date:
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise StatementParseError(f"row {row_number}: unreadable date {raw!r}")


def _parse_amount(raw: str, row_number: int) -> Decimal:
    text = raw.strip().replace("$", "").replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if not text:
        raise StatementParseError(f"row {row_number}: empty amount")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise StatementParseError(f"row {row_number}: unreadable amount {raw!r}") from error
    return -value if negative else value


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    lowered = [header.strip().lower() for header in headers]
    for candidate in candidates:
        if candidate in lowered:
            return lowered.index(candidate)
    return None


def parse_csv(text: str) -> list[ParsedTransaction]:
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise StatementParseError("the file contains no rows")
    headers = rows[0]
    date_col = _find_column(headers, DATE_HEADERS)
    desc_col = _find_column(headers, DESCRIPTION_HEADERS)
    amount_col = _find_column(headers, AMOUNT_HEADERS)
    debit_col = _find_column(headers, DEBIT_HEADERS)
    credit_col = _find_column(headers, CREDIT_HEADERS)
    if date_col is None or desc_col is None:
        raise StatementParseError(
            "no recognizable header row: need a date column and a description column"
        )
    if amount_col is None and (debit_col is None or credit_col is None):
        raise StatementParseError("no amount column: need 'amount' or a debit/credit pair")

    parsed: list[ParsedTransaction] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) <= max(date_col, desc_col):
            raise StatementParseError(f"row {number}: too few columns")
        if amount_col is not None:
            amount = _parse_amount(row[amount_col], number)
        else:
            # Debit/credit pair: exactly one side should carry a value; a
            # debit column is money OUT even when the bank prints it unsigned.
            debit_raw = row[debit_col].strip() if debit_col < len(row) else ""  # type: ignore[operator]
            credit_raw = row[credit_col].strip() if credit_col < len(row) else ""  # type: ignore[operator]
            if debit_raw and credit_raw:
                raise StatementParseError(f"row {number}: both debit and credit present")
            if debit_raw:
                amount = -abs(_parse_amount(debit_raw, number))
            elif credit_raw:
                amount = abs(_parse_amount(credit_raw, number))
            else:
                raise StatementParseError(f"row {number}: neither debit nor credit present")
        if amount == 0:
            raise StatementParseError(f"row {number}: zero-dollar row")
        description = row[desc_col].strip()
        if not description:
            raise StatementParseError(f"row {number}: empty description")
        parsed.append(
            ParsedTransaction(
                posted_on=_parse_date(row[date_col], number),
                amount=amount,
                description=description,
            )
        )
    if not parsed:
        raise StatementParseError("the file contains a header but no transactions")
    return parsed


_STMTTRN = re.compile(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|\Z)", re.S | re.I)
_OFX_FIELD = re.compile(r"<(DTPOSTED|TRNAMT|FITID|NAME|MEMO)>([^<\r\n]*)", re.I)


def parse_ofx(text: str) -> list[ParsedTransaction]:
    """OFX 1.x SGML and OFX 2.x XML, the fields that matter. QFX is OFX with
    an Intuit wrapper; the transaction blocks are identical."""
    blocks = _STMTTRN.findall(text)
    if not blocks:
        raise StatementParseError("no STMTTRN transaction blocks found")
    parsed: list[ParsedTransaction] = []
    for number, block in enumerate(blocks, start=1):
        fields = {key.upper(): value.strip() for key, value in _OFX_FIELD.findall(block)}
        raw_date = fields.get("DTPOSTED", "")
        if len(raw_date) < 8 or not raw_date[:8].isdigit():
            raise StatementParseError(f"transaction {number}: unreadable DTPOSTED {raw_date!r}")
        posted_on = dt.date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        amount = _parse_amount(fields.get("TRNAMT", ""), number)
        if amount == 0:
            raise StatementParseError(f"transaction {number}: zero-dollar TRNAMT")
        description = fields.get("NAME") or fields.get("MEMO") or ""
        if not description:
            raise StatementParseError(f"transaction {number}: no NAME or MEMO")
        parsed.append(
            ParsedTransaction(
                posted_on=posted_on,
                amount=amount,
                description=description,
                fitid=fields.get("FITID") or None,
            )
        )
    return parsed


def detect_format(filename: str, text: str) -> str:
    """'csv' | 'ofx' | 'qfx', by extension first and content second."""
    lowered = filename.lower()
    if lowered.endswith(".qfx"):
        return "qfx"
    if lowered.endswith(".ofx"):
        return "ofx"
    if lowered.endswith(".csv"):
        return "csv"
    head = text.lstrip()[:200].upper()
    if head.startswith("OFXHEADER") or "<OFX>" in head:
        return "ofx"
    return "csv"


def parse_statement(filename: str, text: str) -> tuple[str, list[ParsedTransaction]]:
    fmt = detect_format(filename, text)
    rows = parse_csv(text) if fmt == "csv" else parse_ofx(text)
    return fmt, rows
