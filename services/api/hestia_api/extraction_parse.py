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

# The band module 019's plausible_assessment_year enforces, named here so the
# parser, the API and the database cannot come to disagree about what a tax
# year is. SMALLINT already caps the column; this catches a typed 20226.
MIN_TAX_YEAR = 1990
MAX_TAX_YEAR = 2200


def plausible_tax_year(raw: str) -> bool:
    """Whether a reviewed string is a year a notice could state.

    A reviewer may ratify anything the `text` datatype accepts, so a tax year
    arrives as free text and is checked here rather than discovered as a
    CheckViolation in the middle of a write.
    """
    stripped = raw.strip()
    if not stripped.isdigit():
        return False
    return MIN_TAX_YEAR <= int(stripped) <= MAX_TAX_YEAR


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
    # None where the parser found the field but will not propose a reading —
    # two lines claimed to be the same figure and disagreed. The review path
    # refuses to accept a field with no proposed value (NothingToAccept), so
    # the reviewer must correct it, which is the point: there is nothing here
    # a single click should be able to ratify.
    normalised_value: str | None
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


# ---------------------------------------------------------------------------
# The assessment notice
# ---------------------------------------------------------------------------

# Additive on purpose: the settlement dictionaries above are NOT reused. A
# path added to MONEY_LABELS would make parse_settlement emit a field the
# settlement registry has no spec for, and documents._run_extraction drops
# those on the floor — a silent no-op that looks like a working parser.

# The settlement matcher's twin, differing in one thing: cents are optional.
# A closing statement always prints them; an assessor prints round dollars
# ("Total Assessed Value   $150,000") about as often as not, and
# AMOUNT_AT_END reads those lines as carrying no amount at all. The dollar
# sign stays mandatory — without it `Tax Year   2026` is an amount of 2026.
NOTICE_AMOUNT_AT_END = re.compile(r"\$(?P<amount>[\d,]+(?:\.\d{2})?)\s*$")

# "Tax Year 2026", "Tax Year: 2026", "TAX YEAR 2026 PAYABLE 2027". The bounded
# gap keeps it from reaching across a table row into somebody else's column.
TAX_YEAR_IN_LINE = re.compile(r"(?i)\btax year\b\D{0,12}(?P<year>(?:19|20)\d{2})")

# Longest phrase first: 'total value' is a substring of nothing here, but
# 'land' is a substring of 'land market value', and a shorter key matching
# first would file a land line under the wrong path. Ordered tuple, not a
# dict, because the order IS the rule.
#
# Every one of these was read off a real county form or parcel record —
# Kentucky form 62A352 and Campbell County's PVA system, Hamilton and Warren
# and Miami and Clark County auditor pages in Ohio, the Tennessee state TPAD
# record and Shelby County's own card. No two states agree on wording, and
# Shelby says "Building Appraisal" where Ohio says "Improvements".
NOTICE_MONEY_LABELS: tuple[tuple[str, str], ...] = (
    ("total market appraisal", "assessment.assessed_total"),
    ("market total value", "assessment.assessed_total"),
    ("total appraisal", "assessment.assessed_total"),
    ("total assessment", "assessment.assessed_total"),
    ("current market value", "assessment.assessed_total"),
    ("proposed market value", "assessment.assessed_total"),
    ("fair cash value", "assessment.assessed_total"),
    ("appraised value", "assessment.assessed_total"),
    ("assessed value", "assessment.assessed_total"),
    ("taxable value", "assessment.assessed_total"),
    ("total value", "assessment.assessed_total"),
    ("land market value", "assessment.assessed_land"),
    ("market land value", "assessment.assessed_land"),
    ("land appraisal", "assessment.assessed_land"),
    ("land value", "assessment.assessed_land"),
    ("land", "assessment.assessed_land"),
    ("market improvement value", "assessment.assessed_improvement"),
    ("improvement value", "assessment.assessed_improvement"),
    ("building appraisal", "assessment.assessed_improvement"),
    ("improvements", "assessment.assessed_improvement"),
    ("improvement", "assessment.assessed_improvement"),
)

NOTICE_DATE_LABELS = frozenset(
    {"date", "notice date", "date mailed", "notice sent on", "date of notice"}
)

# The offices that issue these, as they sign them. Never matched against the
# jurisdiction table — this is shown to the reviewer so they can check their
# own pick against the paper, and nothing more.
ASSESSING_OFFICES = (
    "property valuation administrator",
    "county auditor",
    "assessor of property",
    "county assessor",
)


def _notice_label(raw_label: str) -> str | None:
    """The field a notice's label names, or None. Substring matching, because
    a county prints 'Total Market Appraisal (100%)' and means 'total'."""
    label = raw_label.strip().rstrip(":").lower()
    for phrase, path in NOTICE_MONEY_LABELS:
        if phrase in label:
            return path
    return None


def _settle_candidates(path: str, found: list[tuple[str, str, int]]) -> ParsedField:
    """One field from every line that claimed to be it.

    These documents print the same idea more than once and mean different
    things by it. A Campbell County record shows Fair Cash Value 0.00 beside
    a Total Value of 600,000 on an ordinary house; a Tennessee card prints an
    appraised total beside an assessed total three or four times smaller; an
    Ohio notice prints last year's value above this year's. So agreement is
    reported as a reading and disagreement is reported as a question — never
    resolved by preferring whichever line came first.
    """
    distinct = {amount for _, amount, _ in found}
    if len(distinct) == 1:
        label, amount, page = found[0]
        return ParsedField(path, f"{label} ${amount}", normalise_money(amount), DERIVED, page)
    # No proposed value, deliberately. Offering the first reading would let a
    # reviewer ratify Campbell County's Fair Cash Value of 0.00 with one
    # click while the real figure sat in the next line.
    return ParsedField(
        path,
        "; ".join(f"{label} ${amount}" for label, amount, _ in found),
        None,
        SUSPECT,
        found[0][2],
    )


def parse_assessment_notice(lines: list[tuple[int, str]]) -> list[ParsedField]:
    """What can be read off an assessment notice, and nothing beyond it.

    Two things this deliberately does NOT do. It never emits
    `assessment.value_basis`: the same card prints a market figure and a
    taxable one that differ by a factor of three in Ohio and four in
    Tennessee, under labels that vary county by county, and a machine that
    guesses wrong produces a plausible number that is off by 300%. The
    registry marks that field required, so it arrives as a flagged skeleton
    row and a person holding the paper answers it.

    And nothing here is CERTAIN. There is no standard assessment notice —
    only Kentucky prescribes a form, Ohio fixes no fields at all and some
    counties mail nothing per parcel, and no Tennessee county publishes its
    card's front. Every value routes through a human by construction.
    """
    money: dict[str, list[tuple[str, str, int]]] = {}
    fields: list[ParsedField] = []
    seen: set[str] = set()

    for page, line in lines:
        text = line.strip()[:MAX_LINE_CHARS]
        amount_at_end = NOTICE_AMOUNT_AT_END.search(text)
        if amount_at_end is not None:
            raw_label = text[: amount_at_end.start()]
            path = _notice_label(raw_label)
            if path is not None:
                money.setdefault(path, []).append(
                    (raw_label.strip(), amount_at_end.group("amount"), page)
                )
            continue
        year = TAX_YEAR_IN_LINE.search(text)
        if year is not None and "assessment.tax_year" not in seen:
            seen.add("assessment.tax_year")
            fields.append(
                ParsedField("assessment.tax_year", text, year.group("year"), DERIVED, page)
            )
            continue
        office = next((o for o in ASSESSING_OFFICES if o in text.lower()), None)
        if office is not None and "assessment.assessing_body" not in seen:
            seen.add("assessment.assessing_body")
            fields.append(ParsedField("assessment.assessing_body", text, text, SUSPECT, page))
            continue
        labeled = LABELED_LINE.match(text)
        if labeled and labeled.group("label").strip().lower() in NOTICE_DATE_LABELS:
            if "assessment.notice_date" in seen:
                continue
            seen.add("assessment.notice_date")
            raw = labeled.group("value").strip()
            normalised = normalise_date(raw)
            if normalised is None:
                fields.append(ParsedField("assessment.notice_date", raw, raw, SUSPECT, page))
            else:
                fields.append(ParsedField("assessment.notice_date", raw, normalised, DERIVED, page))

    fields.extend(_settle_candidates(path, found) for path, found in money.items())
    return fields


# Which parser reads which document kind. Kinds absent here upload fine and
# wait, honestly unextracted, for their parser (or the model seam) to exist.
PARSERS = {
    "settlement_statement": parse_settlement,
    "assessment_notice": parse_assessment_notice,
}


def run_extractor(kind: str, content: bytes) -> list[ParsedField] | None:
    """None when no parser exists for the kind; [] is a real, empty result."""
    parser = PARSERS.get(kind)
    if parser is None:
        return None
    return parser(extract_lines(content))
