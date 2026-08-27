-- ===========================================================================
--  015 — Document extraction.
--
--  The seam declared in module 005 finally gets its machinery: bytes worth
--  keeping, a registry saying what each document kind yields, and the marker
--  that a confirmed document's facts have landed in domain rows. The loop is
--  upload -> extract -> review -> apply; this module is everything the
--  DATABASE can guarantee about it.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Bytes, content-addressed
-- ---------------------------------------------------------------------------

-- Bank statements are parsed at upload and their bytes discarded (module 011);
-- extraction documents are the opposite: re-extraction after a parser fix and
-- "show me what the machine read" both need the original. A separate table,
-- not a column: source_documents stays light to scan, blob-less rows stay
-- legal, and backup.sh's per-table row-count restore proof covers the bytes.
CREATE TABLE document_blobs (
  content_hash  CHAR(64) PRIMARY KEY
    REFERENCES source_documents (content_hash) ON DELETE CASCADE,
  content       BYTEA NOT NULL,
  byte_size     BIGINT NOT NULL,
  stored_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Content-ADDRESSED, not content-labeled: the key is provably the sha256 of
  -- the bytes, so a blob can never sit under another document's hash.
  CONSTRAINT blob_hash_is_its_content
    CHECK (content_hash = encode(sha256(content), 'hex')),
  CONSTRAINT blob_size_is_its_content CHECK (byte_size = octet_length(content))
);

COMMENT ON TABLE document_blobs IS
  'The original, verbatim. Extraction is re-runnable and reviewable only '
  'while the bytes it read still exist; the hash CHECK makes the addressing '
  'a guarantee instead of a convention.';

-- ---------------------------------------------------------------------------
-- Lifecycle: applied
-- ---------------------------------------------------------------------------

-- The module-011 precedent for growing shared vocabulary.
ALTER TYPE extraction_status ADD VALUE IF NOT EXISTS 'applied';

ALTER TABLE source_documents ADD COLUMN applied_at TIMESTAMPTZ;
ALTER TABLE source_documents ADD COLUMN applied_by TEXT;

-- status::text, NOT the enum literal: an enum value added above cannot be
-- referenced as an enum literal inside this same transaction (the migration
-- runner applies each module in one), while a text comparison is legal now
-- and identical in meaning forever.
ALTER TABLE source_documents ADD CONSTRAINT applied_documents_say_when
  CHECK ((status::text <> 'applied') OR (applied_at IS NOT NULL AND applied_by IS NOT NULL));

-- ---------------------------------------------------------------------------
-- The field-spec registry
-- ---------------------------------------------------------------------------

CREATE TYPE field_datatype AS ENUM ('money', 'date', 'text');

-- What a document kind yields, as data: the deterministic parser reads this
-- to know what to look for, and the review UI reads it for labels, typed
-- editing, required-ness and order. target_hint is documentation for the
-- reviewer — where a confirmed value lands. The APPLY step itself is
-- deliberately per-kind code, not data: a registry row must never be able to
-- name an arbitrary table.column and have the system write there.
CREATE TABLE extraction_field_specs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_kind  document_kind NOT NULL,
  field_path     TEXT NOT NULL,          -- joins extracted_fields.field_path
  label          TEXT NOT NULL,          -- 'Sale price', for the review UI
  datatype       field_datatype NOT NULL,
  required       BOOLEAN NOT NULL DEFAULT FALSE,
  display_order  SMALLINT NOT NULL,
  target_hint    TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_kind, field_path),
  UNIQUE (document_kind, display_order)
);

COMMENT ON TABLE extraction_field_specs IS
  'A new extractable document kind is seed rows plus a parser, never a '
  'schema change. The model-based extractor (later, behind the provider '
  'seam) reads the same registry the deterministic parsers do.';
