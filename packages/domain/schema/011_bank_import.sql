-- ===========================================================================
--  011 — Bank import.
--
--  The pipeline that turns a bank's CSV/OFX export into ledger entries
--  WITHOUT ever compromising the ledger's append-only law: statements stage
--  into a mutable review queue (this module), and only an explicit accept
--  appends a ledger_events row. Re-importing an overlapping statement is a
--  database-level no-op via the dedupe key. A Plaid-style live feed later
--  enters through these same tables — the review queue is the seam.
-- ===========================================================================

ALTER TYPE document_kind ADD VALUE IF NOT EXISTS 'bank_statement';

CREATE TYPE bank_account_kind AS ENUM ('checking', 'savings', 'credit_card', 'escrow');
CREATE TYPE import_format AS ENUM ('csv', 'ofx', 'qfx');
CREATE TYPE batch_status AS ENUM ('parsed', 'in_review', 'posted', 'discarded');
CREATE TYPE txn_disposition AS ENUM
  ('pending', 'accepted', 'excluded', 'duplicate', 'matched_existing');
CREATE TYPE rule_match_kind AS ENUM ('contains', 'exact', 'regex');

CREATE TABLE bank_accounts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id     UUID NOT NULL REFERENCES entities (id),
  -- An account dedicated to one property (the per-property operating account
  -- pattern) may say so; portfolio accounts leave it NULL.
  property_id   UUID REFERENCES properties (id),
  nickname      TEXT NOT NULL,
  institution   TEXT,
  account_last4 CHAR(4),           -- never a full account number
  kind          bank_account_kind NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (entity_id, nickname)
);

CREATE TRIGGER bank_accounts_set_updated_at
  BEFORE UPDATE ON bank_accounts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE bank_import_batches (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bank_account_id    UUID NOT NULL REFERENCES bank_accounts (id),
  -- The file itself, content-addressed: re-uploading the same statement is
  -- caught at the document layer before a single row stages.
  source_document_id UUID NOT NULL REFERENCES source_documents (id),
  format             import_format NOT NULL,
  row_count          INTEGER NOT NULL DEFAULT 0,
  status             batch_status NOT NULL DEFAULT 'parsed',
  imported_by        TEXT,
  imported_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT one_batch_per_document UNIQUE (source_document_id)
);

CREATE TABLE bank_transactions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id            UUID NOT NULL REFERENCES bank_import_batches (id) ON DELETE CASCADE,
  bank_account_id     UUID NOT NULL REFERENCES bank_accounts (id),
  posted_on           DATE NOT NULL,
  amount              money_amount NOT NULL,
  description         TEXT NOT NULL,
  normalised_description TEXT NOT NULL,
  fitid               TEXT,          -- OFX FITID, the bank's own identity, when present
  -- sha256(account | fitid)               when the bank supplies FITID, else
  -- sha256(account | date | amount | normalised description | occurrence #):
  -- identical rows in ONE statement stay distinct (occurrence #), while the
  -- same row in overlapping statements collapses.
  dedupe_key          CHAR(64) NOT NULL,
  suggested_category  ledger_category,
  suggested_property_id UUID REFERENCES properties (id),
  suggested_is_capital  BOOLEAN,
  suggestion_confidence confidence,
  rule_id             UUID,          -- FK added below; rules may be deleted freely
  needs_review        BOOLEAN NOT NULL DEFAULT TRUE,
  disposition         txn_disposition NOT NULL DEFAULT 'pending',
  -- Set exactly once, when the row becomes (or matches) a ledger event.
  ledger_event_id     BIGINT UNIQUE REFERENCES ledger_events (id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bank_rows_move_money CHECK (amount <> 0),
  CONSTRAINT statement_rows_dedupe UNIQUE (bank_account_id, dedupe_key),
  CONSTRAINT posted_rows_link_their_event
    CHECK ((disposition IN ('accepted', 'matched_existing')) = (ledger_event_id IS NOT NULL))
);

CREATE TRIGGER bank_transactions_set_updated_at
  BEFORE UPDATE ON bank_transactions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX bank_transactions_review_queue
  ON bank_transactions (batch_id, disposition);

CREATE TABLE categorization_rules (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  priority      INTEGER NOT NULL DEFAULT 100,   -- lower fires first
  pattern       TEXT NOT NULL,
  match_kind    rule_match_kind NOT NULL DEFAULT 'contains',
  min_amount    money_amount,
  max_amount    money_amount,
  category      ledger_category NOT NULL,
  is_capital_hint BOOLEAN,
  -- Scoping: a rule may bind to one property or one entity; NULL = portfolio-wide.
  property_id   UUID REFERENCES properties (id) ON DELETE CASCADE,
  entity_id     UUID REFERENCES entities (id) ON DELETE CASCADE,
  origin        TEXT NOT NULL DEFAULT 'user',   -- 'seed' | 'user'
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT rule_amount_window_ordered
    CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount),
  CONSTRAINT rule_pattern_not_empty CHECK (length(trim(pattern)) > 0)
);

ALTER TABLE bank_transactions
  ADD CONSTRAINT bank_transactions_rule_id_fkey
  FOREIGN KEY (rule_id) REFERENCES categorization_rules (id) ON DELETE SET NULL;

COMMENT ON TABLE bank_transactions IS
  'The staging queue between a bank statement and the ledger. Mutable by '
  'design — suggestions, review, and disposition all live here — because the '
  'ledger itself is append-only and is touched exactly once, on accept.';
