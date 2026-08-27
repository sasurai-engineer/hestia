"""Deterministic document parsers: bytes -> typed fields with page locations.

Pure functions in the statement_parse mold: no database, no network. pypdf
reads the text layer real title-production software embeds; the line parsers
are exact-label matchers, so a value either matches at confidence 1 or
arrives flagged for review — a deterministic parser never guesses quietly.
The model-based extractor arrives later behind the same interface, which is
why every field records the model_id that produced it.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass
from decimal import Decimal

import pypdf

MODEL_ID = "deterministic/alta-v1"

# The upload cap bounds COMPRESSED bytes; a FlateDecode content stream
# amplifies hundreds of times, and pypdf's tokenizer is superlinear in the
# decompressed length. Extraction runs inside the upload's open transaction,
# so an unbounded page would pin a worker and its connection. Real closing
# packages are tens of pages of a few KB each; these caps sit far above that
# and far below anything that hurts.
MAX_PAGES = 200
MAX_CONTENT_BYTES = 8 * 1024 * 1024
# The line list is what actually lives in memory, and it is the one thing both
# branches produce. A 200-page closing package runs to a few thousand lines;
# this sits far above that and far below what would hurt.
MAX_LINES = 50_000
# One statement line is a label and an amount. Anything vastly longer is not
# a line we can read, and scanning it is work an uploader chose for us.
MAX_LINE_CHARS = 2_000

CERTAIN = Decimal("1")
# A value the parser DERIVED (summed itemized lines) rather than read: right
# in every fixture we have, but derivation is judgment, and judgment routes
# to a human.
DERIVED = Decimal("0.9")
# The statement contradicts itself or a value would not normalise: the raw
# text is preserved and the reviewer decides.
SUSPECT = Decimal("0.5")


class UnreadableDocument(Exception):
    """The bytes are not a text-bearing document this parser can read."""


@dataclass(frozen=True)
class ParsedField:
    field_path: str
    raw_value: str
    normalised_value: str
    confidence: Decimal
    page: int


def _decompressed_size(page: pypdf.PageObject) -> int:
    """Decompressed content-stream length — cheap to read, and the honest
    measure of how much work this page is about to cost."""
    contents = page.get_contents()
    return 0 if contents is None else len(contents.get_data())


def extract_lines(content: bytes) -> list[tuple[int, str]]:
    """Page-tagged text lines from a PDF's text layer, or from plain text.

    A scanned (image-only) PDF yields no lines; the caller treats an empty
    extraction as needs-everything-reviewed, never as an empty document.
    """
    if content.startswith(b"%PDF"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
            page_count = len(reader.pages)
            if page_count > MAX_PAGES:
                raise UnreadableDocument(
                    f"{page_count} pages exceeds the {MAX_PAGES}-page extraction cap"
                )
            budget = MAX_CONTENT_BYTES
            lines: list[tuple[int, str]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                budget -= _decompressed_size(page)
                if budget < 0:
                    raise UnreadableDocument(
                        "decompressed page content exceeds the"
                        f" {MAX_CONTENT_BYTES}-byte extraction budget"
                    )
                lines.extend(
                    (page_number, line) for line in (page.extract_text() or "").splitlines()
                )
                if len(lines) > MAX_LINES:
                    raise UnreadableDocument(
                        f"more than {MAX_LINES} text lines exceeds the extraction cap"
                    )
            return lines
        except UnreadableDocument:
            raise
        except Exception as error:
            raise UnreadableDocument(f"PDF could not be read: {error}") from error
    # The PDF branch bounds its work; this one bounded nothing at all, so an
    # upload just under the byte cap decoded to a str and then to a list of
    # str — hundreds of megabytes of objects, allocated inside the request's
    # open transaction.
    if len(content) > MAX_CONTENT_BYTES:
        raise UnreadableDocument(
            f"{len(content)} bytes of text exceeds the {MAX_CONTENT_BYTES}-byte extraction budget"
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnreadableDocument("neither a PDF nor UTF-8 text") from error
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise UnreadableDocument(
            f"{len(lines)} text lines exceeds the {MAX_LINES}-line extraction cap"
        )
    return [(1, line) for line in lines]


# The amount ending a charge line. ANCHORED AT THE AMOUNT on purpose: a
# label-first pattern (`^(.+?)\s{2,}\$...`) re-scans the column gap at every
# start offset, which is quadratic on a long line — and the line comes from
# whatever someone uploaded.
AMOUNT_AT_END = re.compile(r"\$(?P<amount>[\d,]+\.\d{2})\s*$")
# An identity line: 'Label: value'.
LABELED_LINE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z' ./]+?):\s*(?P<value>\S.*)$")

IDENTITY_LABELS = {
    "settlement date": "settlement.closing_date",
    "closing date": "settlement.closing_date",
    "property": "settlement.property_address",
    "parcel id": "settlement.parcel_number",
    "parcel number": "settlement.parcel_number",
    "buyer": "settlement.buyer_name",
    "borrower": "settlement.buyer_name",
    "seller": "settlement.seller_name",
}

MONEY_LABELS = {
    "sale price of property": "settlement.sale_price",
    "sale price": "settlement.sale_price",
    "contract sales price": "settlement.sale_price",
    "loan amount": "settlement.loan_amount",
    "total capitalizable closing costs": "settlement.capitalizable_closing_costs",
}

# Acquisition costs capitalize into basis (Treas. Reg. 1.263(a)-2); loan
# costs — the lender's policy, mortgage recording — do not, and are absent
# here on purpose.
CAPITALIZABLE_CHARGE_LABELS = (
    "owner's title insurance policy",
    "settlement or closing fee",
    "title search and examination",
    "recording fee: deed",
    "survey",
    "transfer tax",
    "deed preparation",
)

_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")


def match_money_line(text: str) -> tuple[str, str] | None:
    """(label, amount) for `Label   $1,200.00`, else None. The two-space run
    is the column separator every settlement statement prints."""
    found = AMOUNT_AT_END.search(text)
    if found is None:
        return None
    label = text[: found.start()]
    if len(label) - len(label.rstrip()) < 2:
        return None
    return label.strip(), found.group("amount")


def normalise_date(raw: str) -> str | None:
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalise_money(raw: str) -> str:
    return str(Decimal(raw.replace(",", "").replace("$", "")))


def parse_settlement(lines: list[tuple[int, str]]) -> list[ParsedField]:
    fields: list[ParsedField] = []
    seen: set[str] = set()
    itemized_sum = Decimal("0")
    itemized_parts: list[str] = []
    itemized_page = 1

    for page, line in lines:
        text = line.strip()[:MAX_LINE_CHARS]
        money = match_money_line(text)
        if money:
            raw_label, amount = money
            label = re.sub(r"\s*\(.*\)$", "", raw_label.rstrip(".").lower())
            path = MONEY_LABELS.get(label)
            if path and path not in seen:
                seen.add(path)
                fields.append(ParsedField(path, text, normalise_money(amount), CERTAIN, page))
            if any(label.startswith(cap) for cap in CAPITALIZABLE_CHARGE_LABELS):
                itemized_sum += Decimal(amount.replace(",", ""))
                itemized_parts.append(f"{raw_label} ${amount}")
                itemized_page = page
            continue
        labeled = LABELED_LINE.match(text)
        if labeled:
            path = IDENTITY_LABELS.get(labeled.group("label").strip().lower())
            if path and path not in seen:
                seen.add(path)
                raw = labeled.group("value").strip()
                if path == "settlement.closing_date":
                    normalised = normalise_date(raw)
                    if normalised is None:
                        fields.append(ParsedField(path, raw, raw, SUSPECT, page))
                        continue
                    fields.append(ParsedField(path, raw, normalised, CERTAIN, page))
                else:
                    fields.append(ParsedField(path, raw, raw, CERTAIN, page))

    costs_path = "settlement.capitalizable_closing_costs"
    explicit = next((f for f in fields if f.field_path == costs_path), None)
    printed_total_disagrees = (
        explicit is not None
        and bool(itemized_parts)
        and Decimal(explicit.normalised_value) != itemized_sum
    )
    if printed_total_disagrees and explicit is not None:
        # The printed total and the itemized lines disagree: show both and
        # let the reviewer settle it — never silently prefer either.
        fields[fields.index(explicit)] = ParsedField(
            costs_path,
            f"{explicit.raw_value} vs itemized sum {itemized_sum} ({'; '.join(itemized_parts)})",
            str(itemized_sum),
            SUSPECT,
            explicit.page,
        )
    elif explicit is None and itemized_parts:
        # The common real-world shape: no printed total. The sum is DERIVED,
        # arrives with its working, and always passes a human.
        fields.append(
            ParsedField(
                costs_path, "; ".join(itemized_parts), str(itemized_sum), DERIVED, itemized_page
            )
        )
    return fields


# Which parser reads which document kind. Kinds absent here upload fine and
# wait, honestly unextracted, for their parser (or the model seam) to exist.
PARSERS = {
    "settlement_statement": parse_settlement,
}


def run_extractor(kind: str, content: bytes) -> list[ParsedField] | None:
    """None when no parser exists for the kind; [] is a real, empty result."""
    parser = PARSERS.get(kind)
    if parser is None:
        return None
    return parser(extract_lines(content))
