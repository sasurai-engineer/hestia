"""The extraction loop: upload -> extract -> review -> apply.

The machine reads, the human ratifies, the database enforces. Everything
before apply mutates only the extraction tables; exactly one path — apply —
writes domain rows, in one transaction, gated by a single compare-and-set so
a concurrent double-apply loses at the database. Values the parser derived
or doubted arrive flagged; a rejected field never applies; and the numbers
the review screen shows (basis totals, the assessor-ratio land suggestion)
are computed HERE, never in the browser.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.parse
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

from hestia_api import extraction_parse
from hestia_api import ledger as ledger_module

Conn = psycopg.Connection[dict[str, Any]]

CENT = Decimal("0.01")
# money_amount is NUMERIC(18, 2): sixteen digits before the point. A value
# beyond it cannot be stored, so it is refused at the edge with a sentence
# rather than at the database with a stack trace.
MAX_MONEY = Decimal("9" * 16 + ".99")
# Multipart reads the file into memory; refuse anything implausibly large for
# a closing package before it gets there.
MAX_BYTES = 25 * 1024 * 1024


class UnknownDocument(Exception):
    pass


class UnknownProperty(Exception):
    pass


class DuplicateDocument(Exception):
    """These exact bytes were already uploaded (content hash match)."""


class DocumentTooLarge(Exception):
    pass


class UnknownField(Exception):
    """No spec defines this field path for the document's kind."""


class InvalidValue(Exception):
    """A corrected value must satisfy the spec's datatype."""


class NothingToAccept(Exception):
    """Accepting requires an extracted value; a skeleton row has none."""


class AlreadyApplied(Exception):
    pass


class NotConfirmed(Exception):
    """Apply requires every required field reviewed to a value first."""


class NotExactlyOneProperty(Exception):
    """C1 applies single-property statements only; allocation across several
    is a workflow this increment does not pretend to have."""


class InvalidAllocation(Exception):
    """Land plus personal property may not exceed the total basis."""


class FieldOut(BaseModel):
    field_path: str
    label: str
    datatype: Literal["money", "date", "text"]
    required: bool
    display_order: int
    target_hint: str | None
    raw_value: str | None
    normalised_value: str | None
    accepted_value: str | None
    confidence: Decimal | None
    page: int | None
    needs_review: bool
    reviewed_by: str | None
    reviewed_at: dt.datetime | None
    model_id: str | None
    # What apply would use today: the accepted value once reviewed, the
    # machine's value when it needed no review, nothing otherwise.
    effective_value: str | None


class ApplySuggestion(BaseModel):
    """Server-computed apply preview: the browser displays, never computes."""

    total_basis: Decimal
    suggested_land_value: Decimal | None
    suggestion_citation: str | None
    address_matches: bool | None


class DocumentSummary(BaseModel):
    id: str
    kind: str
    filename: str
    status: str
    document_date: dt.date | None
    uploaded_at: dt.datetime
    uploaded_by: str | None
    property_labels: list[str]
    # Rows the extractor produced. The detail's `fields` list is longer: it
    # carries every spec the registry defines, extracted or not.
    extracted_count: int
    open_review_count: int
    has_content: bool


class DocumentDetail(DocumentSummary):
    property_ids: list[str]
    applied_at: dt.datetime | None
    applied_by: str | None
    fields: list[FieldOut]
    suggestion: ApplySuggestion | None


class ReviewIn(BaseModel):
    action: Literal["accept", "correct", "reject"]
    value: str | None = None
    field_path: str


class ApplyIn(BaseModel):
    # The land split is the owner's decision; the suggestion block carries
    # the cited assessor-ratio default the UI offers.
    land_value: Decimal = Field(decimal_places=2, max_digits=18, ge=0)
    personal_property: Decimal = Field(default=Decimal("0"), decimal_places=2, max_digits=18, ge=0)
    method: str = "owner allocation at apply"


class ApplyResult(BaseModel):
    price_allocation_id: str
    ledger_event_uuid: str
    total_basis: Decimal
    land_value: Decimal
    improvement_value: Decimal
    personal_property: Decimal
    acquired_on_set: bool
    parcel_number_set: bool
    notes: list[str]


def _effective(row: dict[str, Any]) -> str | None:
    """The value apply would use: human ratification wins, then unflagged
    machine reads; a rejected or still-flagged field contributes nothing."""
    if row["reviewed_at"] is not None:
        return row["accepted_value"]
    if not row["needs_review"]:
        return row["normalised_value"]
    return None


def _specs_for(conn: Conn, kind: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT field_path, label, datatype::text AS datatype, required,
               display_order, target_hint
        FROM extraction_field_specs WHERE document_kind = %s ORDER BY display_order
        """,
        (kind,),
    ).fetchall()


def _run_extraction(conn: Conn, document: dict[str, Any], content: bytes) -> None:
    """Parse, write field rows, set the document's status, log the run.

    Reviewed rows survive re-extraction — a human's ratification outlives a
    parser upgrade — while unreviewed rows are replaced wholesale.
    """
    doc_id = document["id"]
    parsed = extraction_parse.run_extractor(document["kind"], content)
    if parsed is None:
        return  # no parser for this kind yet; the document waits, honestly
    conn.execute(
        "DELETE FROM extracted_fields WHERE document_id = %s AND reviewed_at IS NULL",
        (doc_id,),
    )
    specs = {spec["field_path"]: spec for spec in _specs_for(conn, document["kind"])}
    for field in parsed:
        if field.field_path not in specs:
            continue  # a parser may only yield paths the registry defines
        conn.execute(
            """
            INSERT INTO extracted_fields
              (document_id, field_path, raw_value, normalised_value, confidence,
               page, needs_review, model_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, field_path) DO NOTHING
            """,
            (
                doc_id,
                field.field_path,
                field.raw_value,
                field.normalised_value,
                field.confidence,
                field.page,
                field.confidence < extraction_parse.CERTAIN,
                extraction_parse.MODEL_ID,
            ),
        )
    # A required field the parser could not find becomes a flagged skeleton
    # row: the reviewer sees the gap and types the value, instead of the gap
    # hiding until apply.
    for path, spec in specs.items():
        if spec["required"]:
            conn.execute(
                """
                INSERT INTO extracted_fields
                  (document_id, field_path, raw_value, normalised_value, confidence,
                   needs_review, model_id)
                VALUES (%s, %s, NULL, NULL, 0, TRUE, %s)
                ON CONFLICT (document_id, field_path) DO NOTHING
                """,
                (doc_id, path, extraction_parse.MODEL_ID),
            )
    _refresh_status(conn, doc_id, document["kind"])
    property_id = conn.execute(
        "SELECT property_id::text FROM document_properties WHERE document_id = %s LIMIT 1",
        (doc_id,),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO ingestion_runs (provider, endpoint, property_id, status, raw_response)
        VALUES (%s, %s, %s, 'ok', %s)
        """,
        (
            f"extractor:{document['kind']}",
            extraction_parse.MODEL_ID,
            property_id["property_id"] if property_id else None,
            json.dumps(
                [
                    {
                        "field_path": f.field_path,
                        "normalised_value": f.normalised_value,
                        "confidence": str(f.confidence),
                        "page": f.page,
                    }
                    for f in parsed
                ]
            ),
        ),
    )


def _refresh_status(conn: Conn, doc_id: str, kind: str) -> None:
    """The machine's side of the state machine. 'needs_review' while anything
    is flagged or a required value is missing; 'extracted' once the machine
    is done but a human has not ratified every required field; 'confirmed'
    only when they have — apply gates on that, so "the human ratifies" is a
    state transition, not a slogan. 'applied' is set solely by apply's own
    compare-and-set, and callers never reach here after it."""
    rows = conn.execute(
        """
        SELECT s.required, f.normalised_value, f.accepted_value, f.needs_review,
               f.reviewed_at
        FROM extraction_field_specs s
        LEFT JOIN extracted_fields f
          ON f.document_id = %s AND f.field_path = s.field_path
        WHERE s.document_kind = %s
        """,
        (doc_id, kind),
    ).fetchall()
    if not rows:
        return  # nothing is extractable for this kind; the status stands
    if any(row["needs_review"] for row in rows) or any(
        row["required"] and row["reviewed_at"] is None and row["normalised_value"] is None
        for row in rows
    ):
        status = "needs_review"
    elif all(
        not row["required"]
        or (row["reviewed_at"] is not None and row["accepted_value"] is not None)
        for row in rows
    ):
        status = "confirmed"
    else:
        status = "extracted"
    # NEVER demote a terminal document. A review that read the row before an
    # apply committed would otherwise write 'confirmed' back over 'applied'
    # and let the same purchase apply twice into an append-only ledger.
    conn.execute(
        "UPDATE source_documents SET status = %s WHERE id = %s AND status::text <> 'applied'",
        (status, doc_id),
    )


def upload(
    conn: Conn,
    *,
    kind: str,
    property_id: str,
    filename: str,
    content: bytes,
    mime_type: str | None,
    document_date: dt.date | None,
    uploaded_by: str,
) -> DocumentDetail:
    if len(content) > MAX_BYTES:
        raise DocumentTooLarge(f"{len(content)} bytes exceeds the {MAX_BYTES} cap")
    prop = conn.execute("SELECT id::text FROM properties WHERE id = %s", (property_id,)).fetchone()
    if prop is None:
        raise UnknownProperty(property_id)
    content_hash = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id::text FROM source_documents WHERE content_hash = %s", (content_hash,)
    ).fetchone()
    if existing is not None:
        raise DuplicateDocument(existing["id"])
    try:
        document = conn.execute(
            """
            INSERT INTO source_documents
              (kind, filename, content_hash, byte_size, mime_type, document_date,
               uploaded_by, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id::text, kind::text AS kind
            """,
            (kind, filename, content_hash, len(content), mime_type, document_date, uploaded_by),
        ).fetchone()
    except psycopg.errors.UniqueViolation as error:
        # Two uploads of the same bytes, both past the check above: the
        # content-addressed unique index decides, and the loser gets the
        # same 409 the sequential case gets.
        raise DuplicateDocument(content_hash) from error
    conn.execute(
        "INSERT INTO document_blobs (content_hash, content, byte_size) VALUES (%s, %s, %s)",
        (content_hash, content, len(content)),
    )
    conn.execute(
        "INSERT INTO document_properties (document_id, property_id) VALUES (%s, %s)",
        (document["id"], property_id),
    )
    _run_extraction(conn, document, content)
    return detail(conn, document["id"])


def re_extract(conn: Conn, doc_id: str) -> DocumentDetail:
    document = conn.execute(
        """
        SELECT d.id::text, d.kind::text AS kind, d.status::text AS status, b.content
        FROM source_documents d
        LEFT JOIN document_blobs b ON b.content_hash = d.content_hash
        WHERE d.id = %s
        FOR UPDATE OF d
        """,
        (doc_id,),
    ).fetchone()
    if document is None:
        raise UnknownDocument(doc_id)
    if document["status"] == "applied":
        raise AlreadyApplied(doc_id)
    if document["content"] is None:
        return detail(conn, doc_id)  # bytes were never kept; the state stands
    _run_extraction(conn, document, bytes(document["content"]))
    return detail(conn, doc_id)


def _canonicalise(datatype: str, value: str) -> str:
    if datatype == "money":
        try:
            amount = Decimal(value.replace(",", "").replace("$", ""))
        except InvalidOperation as error:
            raise InvalidValue(f"not a money amount: {value!r}") from error
        # Decimal('NaN') and Decimal('Infinity') parse happily and quantize
        # without complaint; they would then poison every total downstream
        # and make the document's own detail unrenderable.
        if not amount.is_finite():
            raise InvalidValue(f"not a money amount: {value!r}")
        # quantize() raises InvalidOperation when the result needs more digits
        # than the decimal context allows, so "1e30" reached the caller as a
        # 500 rather than a refusal. The bound is the money_amount column's
        # own precision, checked here instead of discovered in SQL.
        if abs(amount) > MAX_MONEY:
            raise InvalidValue(f"{value!r} exceeds the largest amount this records")
        return str(amount.quantize(CENT))
    if datatype == "date":
        normalised = extraction_parse.normalise_date(value)
        if normalised is None:
            raise InvalidValue(f"not a date: {value!r}")
        return normalised
    if not value.strip():
        raise InvalidValue("an empty correction is a rejection; use reject")
    return value.strip()


def review_field(conn: Conn, doc_id: str, body: ReviewIn, reviewer: str) -> DocumentDetail:
    # FOR UPDATE so the status check below is a decision, not a guess: a
    # concurrent apply or review serializes behind this lock instead of
    # racing it (the module-014 lesson).
    document = conn.execute(
        "SELECT id::text, kind::text AS kind, status::text AS status"
        " FROM source_documents WHERE id = %s FOR UPDATE",
        (doc_id,),
    ).fetchone()
    if document is None:
        raise UnknownDocument(doc_id)
    if document["status"] == "applied":
        raise AlreadyApplied("review after apply would rewrite ratified history")
    spec = conn.execute(
        """
        SELECT field_path, datatype::text AS datatype
        FROM extraction_field_specs WHERE document_kind = %s AND field_path = %s
        """,
        (document["kind"], body.field_path),
    ).fetchone()
    if spec is None:
        raise UnknownField(body.field_path)
    field = conn.execute(
        "SELECT id::text, normalised_value FROM extracted_fields"
        " WHERE document_id = %s AND field_path = %s FOR UPDATE",
        (doc_id, body.field_path),
    ).fetchone()
    if body.action == "accept":
        if field is None or field["normalised_value"] is None:
            raise NothingToAccept(body.field_path)
        # Through the SAME canonicaliser as a correction: a value the parser
        # flagged BECAUSE it would not normalise must not become a ratified
        # fact by one click. The 422 steers the reviewer to correct instead.
        accepted: str | None = _canonicalise(spec["datatype"], field["normalised_value"])
    elif body.action == "correct":
        if body.value is None:
            raise InvalidValue("correct requires a value")
        accepted = _canonicalise(spec["datatype"], body.value)
    else:
        accepted = None
    if field is None:
        # An optional field the parser never emitted: the human supplies it.
        # ON CONFLICT because two clicks can arrive together and the row is
        # unique per (document, path) — the second is a re-decision, not a 500.
        conn.execute(
            """
            INSERT INTO extracted_fields
              (document_id, field_path, raw_value, normalised_value, confidence,
               needs_review, reviewed_by, reviewed_at, accepted_value)
            VALUES (%s, %s, NULL, NULL, 1, FALSE, %s, now(), %s)
            ON CONFLICT (document_id, field_path) DO UPDATE
              SET accepted_value = EXCLUDED.accepted_value,
                  reviewed_by = EXCLUDED.reviewed_by,
                  reviewed_at = EXCLUDED.reviewed_at,
                  needs_review = FALSE
            """,
            (doc_id, body.field_path, reviewer, accepted),
        )
    else:
        conn.execute(
            """
            UPDATE extracted_fields
            SET accepted_value = %s, reviewed_by = %s, reviewed_at = now(),
                needs_review = FALSE
            WHERE id = %s
            """,
            (accepted, reviewer, field["id"]),
        )
    _refresh_status(conn, doc_id, document["kind"])
    return detail(conn, doc_id)


def _street_mentioned(street: str, address: str) -> bool:
    """Advisory: does the statement's address name this street? Padded and
    punctuation-flattened, so `1 Main St` does not match `11 Main Street`."""

    def normalise(text: str) -> str:
        return f" {re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()} "

    return normalise(street) in normalise(address)


def _suggestion(
    conn: Conn, kind: str, property_ids: list[str], fields: list[FieldOut]
) -> ApplySuggestion | None:
    if kind != "settlement_statement" or len(property_ids) != 1:
        return None
    values = {f.field_path: f.effective_value for f in fields}
    sale = values.get("settlement.sale_price")
    costs = values.get("settlement.capitalizable_closing_costs")
    if sale is None or costs is None:
        return None
    total_basis = Decimal(sale) + Decimal(costs)
    prop = conn.execute(
        "SELECT street_1 FROM properties WHERE id = %s", (property_ids[0],)
    ).fetchone()
    address = values.get("settlement.property_address")
    address_matches = (
        None if address is None or prop is None else _street_mentioned(prop["street_1"], address)
    )
    # The defensible ratio is the one the assessor published AROUND THE
    # CLOSING, not the newest on file: a 2019 purchase allocated by a 2026
    # assessment is not a ratio anyone can defend. Nearest year wins, ties
    # break to the earlier year then the id — same inputs, same suggestion.
    closing = values.get("settlement.closing_date")
    closing_year = int(closing[:4]) if closing else None
    assessment = conn.execute(
        """
        SELECT a.tax_year, a.assessed_land, a.assessed_total, j.name AS jurisdiction
        FROM assessments a JOIN jurisdictions j ON j.id = a.jurisdiction_id
        WHERE a.property_id = %s AND a.assessed_land IS NOT NULL AND a.assessed_total > 0
        ORDER BY abs(a.tax_year - coalesce(%s, a.tax_year)) ASC, a.tax_year ASC, a.id ASC
        LIMIT 1
        """,
        (property_ids[0], closing_year),
    ).fetchone()
    suggested = None
    citation = None
    if assessment is not None:
        ratio = assessment["assessed_land"] / assessment["assessed_total"]
        suggested = (total_basis * ratio).quantize(CENT, rounding=ROUND_HALF_EVEN)
        citation = (
            f"{assessment['jurisdiction']} assessment {assessment['tax_year']}: "
            f"land {assessment['assessed_land']} / total {assessment['assessed_total']}"
        )
    return ApplySuggestion(
        total_basis=total_basis,
        suggested_land_value=suggested,
        suggestion_citation=citation,
        address_matches=address_matches,
    )


def detail(conn: Conn, doc_id: str) -> DocumentDetail:
    document = conn.execute(
        """
        SELECT d.id::text, d.kind::text AS kind, d.filename, d.status::text AS status,
               d.document_date, d.uploaded_at, d.uploaded_by, d.applied_at, d.applied_by,
               (b.content_hash IS NOT NULL) AS has_content
        FROM source_documents d
        LEFT JOIN document_blobs b ON b.content_hash = d.content_hash
        WHERE d.id = %s
        """,
        (doc_id,),
    ).fetchone()
    if document is None:
        raise UnknownDocument(doc_id)
    links = conn.execute(
        """
        SELECT p.id::text AS id, p.label
        FROM document_properties dp JOIN properties p ON p.id = dp.property_id
        WHERE dp.document_id = %s ORDER BY p.label
        """,
        (doc_id,),
    ).fetchall()
    rows = conn.execute(
        """
        SELECT s.field_path, s.label, s.datatype::text AS datatype, s.required,
               s.display_order, s.target_hint,
               f.raw_value, f.normalised_value, f.accepted_value, f.confidence,
               f.page, coalesce(f.needs_review, FALSE) AS needs_review,
               f.reviewed_by, f.reviewed_at, f.model_id,
               (f.id IS NOT NULL) AS has_row
        FROM extraction_field_specs s
        LEFT JOIN extracted_fields f
          ON f.document_id = %s AND f.field_path = s.field_path
        WHERE s.document_kind = %s
        ORDER BY s.display_order
        """,
        (doc_id, document["kind"]),
    ).fetchall()
    fields = [
        FieldOut(
            **{key: row[key] for key in FieldOut.model_fields if key != "effective_value"},
            effective_value=_effective(row) if row["has_row"] else None,
        )
        for row in rows
    ]
    return DocumentDetail(
        id=document["id"],
        kind=document["kind"],
        filename=document["filename"],
        status=document["status"],
        document_date=document["document_date"],
        uploaded_at=document["uploaded_at"],
        uploaded_by=document["uploaded_by"],
        property_labels=[link["label"] for link in links],
        property_ids=[link["id"] for link in links],
        # The same meaning the inbox uses: rows the extractor actually
        # produced, not the registry's full spec list (that is `fields`).
        extracted_count=sum(1 for f in fields if f.model_id is not None),
        open_review_count=sum(1 for f in fields if f.needs_review),
        has_content=document["has_content"],
        applied_at=document["applied_at"],
        applied_by=document["applied_by"],
        fields=fields,
        suggestion=_suggestion(conn, document["kind"], [link["id"] for link in links], fields),
    )


def list_documents(conn: Conn, status: str | None) -> list[DocumentSummary]:
    rows = conn.execute(
        """
        SELECT d.id::text, d.kind::text AS kind, d.filename, d.status::text AS status,
               d.document_date, d.uploaded_at, d.uploaded_by,
               (b.content_hash IS NOT NULL) AS has_content,
               -- DISTINCT because document_properties and extracted_fields are
               -- independent one-to-many joins: their cross product would
               -- multiply both counts and repeat every label.
               coalesce(array_agg(DISTINCT p.label)
                        FILTER (WHERE p.label IS NOT NULL), '{}') AS property_labels,
               count(DISTINCT f.id) AS extracted_count,
               count(DISTINCT f.id) FILTER (WHERE f.needs_review) AS open_review_count
        FROM source_documents d
        LEFT JOIN document_blobs b ON b.content_hash = d.content_hash
        LEFT JOIN document_properties dp ON dp.document_id = d.id
        LEFT JOIN properties p ON p.id = dp.property_id
        LEFT JOIN extracted_fields f ON f.document_id = d.id
        WHERE (%(status)s::text IS NULL OR d.status::text = %(status)s)
        GROUP BY d.id, b.content_hash
        ORDER BY d.uploaded_at DESC
        """,
        {"status": status},
    ).fetchall()
    return [DocumentSummary(**row) for row in rows]


# What may be rendered INLINE in the operator's browser. The uploader chooses
# the mime type, so echoing it back on an inline response would let an HTML or
# SVG upload run script on the API's own origin. Anything off this list is
# served as a download of untyped bytes instead.
INLINE_SAFE_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)


def content_disposition(filename: str, *, inline: bool) -> str:
    """RFC 6266, defensively. The filename is whatever the uploader's client
    sent: a quote would break out of the quoted-string, and a CR or LF would
    make the response unsendable (h11 refuses it) — turning a bad upload into
    a permanent 500 on that document. Both are stripped, and the real name
    rides along percent-encoded in filename* for clients that read it."""
    ascii_name = "".join(
        character
        for character in filename
        if character.isprintable() and character not in '"\\' and character.isascii()
    )
    encoded = urllib.parse.quote(filename, safe="")
    return (
        f"{'inline' if inline else 'attachment'};"
        f' filename="{ascii_name or "document"}";'
        f" filename*=UTF-8''{encoded}"
    )


def get_content(conn: Conn, doc_id: str) -> tuple[str, str, bytes]:
    """(content-disposition, content-type, bytes) for the stored original."""
    row = conn.execute(
        """
        SELECT d.filename, d.mime_type, b.content
        FROM source_documents d
        JOIN document_blobs b ON b.content_hash = d.content_hash
        WHERE d.id = %s
        """,
        (doc_id,),
    ).fetchone()
    if row is None:
        raise UnknownDocument(doc_id)
    declared = row["mime_type"] or ""
    inline = declared in INLINE_SAFE_TYPES
    media_type = declared if inline else "application/octet-stream"
    return (
        content_disposition(row["filename"], inline=inline),
        media_type,
        bytes(row["content"]),
    )


class WrongApplyKind(Exception):
    """This document's kind applies through another door."""


def claim_for_apply(conn: Conn, doc_id: str, actor: str) -> dict[str, Any]:
    """Flip a confirmed document to 'applied', exactly once, or say why not.

    THE compare-and-set. Of two concurrent applies exactly one sees
    'confirmed': the second blocks on the row lock, re-evaluates its WHERE
    against the committed 'applied', matches zero rows, and the miss is then
    diagnosed into three distinct errors. Any later failure in the caller
    raises, the endpoint transaction rolls back, and this UPDATE rolls back
    with it — so a refused apply leaves the document confirmed and appliable.

    Both doors come through here — the settlement statement's allocation step
    and the assessment notice's record step — so "a document's facts enter the
    domain exactly once" has one implementation rather than two.
    """
    gate = conn.execute(
        """
        UPDATE source_documents
        SET status = 'applied', applied_at = now(), applied_by = %s
        WHERE id = %s AND status = 'confirmed'
        RETURNING kind::text AS kind, filename
        """,
        (actor, doc_id),
    ).fetchone()
    if gate is None:
        current = conn.execute(
            "SELECT status::text AS status FROM source_documents WHERE id = %s", (doc_id,)
        ).fetchone()
        if current is None:
            raise UnknownDocument(doc_id)
        if current["status"] == "applied":
            raise AlreadyApplied(doc_id)
        raise NotConfirmed(current["status"])
    return gate


def effective_values(conn: Conn, doc_id: str) -> dict[str, str | None]:
    """{field_path: the value apply would use}, shared by both doors so they
    cannot come to disagree about what "the reviewed value" means."""
    rows = conn.execute(
        "SELECT field_path, normalised_value, accepted_value, needs_review, reviewed_at"
        " FROM extracted_fields WHERE document_id = %s",
        (doc_id,),
    ).fetchall()
    return {row["field_path"]: _effective(row) for row in rows}


def apply_document(conn: Conn, doc_id: str, body: ApplyIn, actor: str) -> ApplyResult:
    gate = claim_for_apply(conn, doc_id, actor)
    # The kind test this function never needed while one kind had registry
    # rows. Seeding assessment_notice specs makes a notice reachable to
    # 'confirmed', and without this line the settlement subscripts below are a
    # KeyError that escapes the endpoint's except list as a 500 — on what is
    # really a rule refusal. Refused before anything is written, and the gate
    # rolls back with it.
    if gate["kind"] != "settlement_statement":
        raise WrongApplyKind(f"a {gate['kind']} does not apply as a settlement statement")
    # FOR UPDATE OF p, because the acquired_on / parcel_number decisions below
    # are read-then-write: unlocked, two applies of two documents for the SAME
    # property both read NULL, both write, and the second silently clobbers the
    # fact the first recorded while BOTH report having set it. The lock makes
    # the read a decision (the module-014 lesson, as in re_extract), and
    # ORDER BY p.id fixes the lock order so a multi-property statement queues
    # behind another instead of deadlocking with it.
    links = conn.execute(
        """
        SELECT p.id::text AS id, p.entity_id::text AS entity_id, p.acquired_on,
               p.parcel_number, p.label
        FROM document_properties dp JOIN properties p ON p.id = dp.property_id
        WHERE dp.document_id = %s
        ORDER BY p.id
        FOR UPDATE OF p
        """,
        (doc_id,),
    ).fetchall()
    if len(links) != 1:
        raise NotExactlyOneProperty(str(len(links)))
    prop = links[0]
    values = effective_values(conn, doc_id)
    closing_date = dt.date.fromisoformat(values["settlement.closing_date"])  # type: ignore[arg-type]
    total_basis = Decimal(values["settlement.sale_price"]) + Decimal(  # type: ignore[arg-type]
        values["settlement.capitalizable_closing_costs"]  # type: ignore[arg-type]
    )
    if total_basis <= 0:
        raise InvalidAllocation(f"total basis {total_basis} is not a purchase")
    # Each half fits money_amount; their SUM need not. price_allocations and the
    # ledger event are both NUMERIC(18, 2), so an unbounded total reached the
    # caller as a psycopg NumericValueOutOfRange 500 — after the gate above had
    # already flipped the document to 'applied'. Refused here in a sentence,
    # before anything is written, and the gate rolls back with the refusal.
    if total_basis > MAX_MONEY:
        raise InvalidAllocation(
            f"total basis {total_basis} exceeds the largest amount this records"
        )
    improvement = total_basis - body.land_value - body.personal_property
    if improvement < 0:
        raise InvalidAllocation(
            f"land {body.land_value} + personal {body.personal_property}"
            f" exceeds total basis {total_basis}"
        )
    provenance = conn.execute(
        """
        INSERT INTO provenance (kind, confidence, source_label, source_document)
        VALUES ('document', 1.0, %s, %s) RETURNING id::text
        """,
        (f"Settlement statement {closing_date} ({gate['filename']})", doc_id),
    ).fetchone()
    allocation = conn.execute(
        """
        INSERT INTO price_allocations
          (property_id, allocated_on, total_basis, land_value, improvement_value,
           personal_property, method, provenance_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (
            prop["id"],
            closing_date,
            total_basis,
            body.land_value,
            improvement,
            body.personal_property,
            body.method,
            provenance["id"],
        ),
    ).fetchone()
    notes: list[str] = []
    acquired_on_set = prop["acquired_on"] is None
    if acquired_on_set:
        conn.execute(
            "UPDATE properties SET acquired_on = %s, updated_at = now() WHERE id = %s",
            (closing_date, prop["id"]),
        )
    elif prop["acquired_on"] != closing_date:
        notes.append(
            f"acquired_on already {prop['acquired_on']}; the statement says"
            f" {closing_date} — left as recorded"
        )
    parcel = values.get("settlement.parcel_number")
    parcel_number_set = parcel is not None and prop["parcel_number"] is None
    if parcel_number_set:
        conn.execute(
            "UPDATE properties SET parcel_number = %s, updated_at = now() WHERE id = %s",
            (parcel, prop["id"]),
        )
    elif parcel is not None and prop["parcel_number"] != parcel:
        notes.append(
            f"parcel_number already {prop['parcel_number']}; the statement says"
            f" {parcel} — left as recorded"
        )
    if values.get("settlement.loan_amount") is not None:
        notes.append(
            f"loan amount {values['settlement.loan_amount']} not applied: the"
            " statement carries no rate or term; enter the note separately"
        )
    event = ledger_module.append_event(
        conn,
        ledger_module.LedgerEntryIn(
            occurred_on=closing_date,
            category="acquisition_cost",
            amount=-total_basis,
            memo=f"Closing: {prop['label']} ({gate['filename']})",
            counterparty=values.get("settlement.seller_name"),
            property_id=prop["id"],
            entity_id=prop["entity_id"],
            document_id=doc_id,
        ),
    )
    return ApplyResult(
        price_allocation_id=allocation["id"],
        ledger_event_uuid=event.event_uuid,
        total_basis=total_basis,
        land_value=body.land_value,
        improvement_value=improvement,
        personal_property=body.personal_property,
        acquired_on_set=acquired_on_set,
        parcel_number_set=parcel_number_set,
        notes=notes,
    )
