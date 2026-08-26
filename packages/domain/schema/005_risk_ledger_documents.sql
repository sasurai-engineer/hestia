-- ===========================================================================
--  Hestia — insurance, the money ledger, and document extraction
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Insurance
-- ---------------------------------------------------------------------------

CREATE TYPE policy_kind AS ENUM (
  'dwelling_fire', 'landlord_package', 'homeowners', 'commercial_property',
  'general_liability', 'umbrella', 'flood_nfip', 'flood_private',
  'earthquake', 'builders_risk', 'rent_guarantee'
);

CREATE TYPE valuation_basis AS ENUM ('replacement_cost', 'actual_cash_value', 'agreed_value');

CREATE TABLE policies (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id        UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  entity_id          UUID REFERENCES entities (id),
  carrier            TEXT,
  policy_number_last4 CHAR(4),
  kind               policy_kind NOT NULL,
  effective_from     DATE NOT NULL,
  effective_to       DATE NOT NULL,
  annual_premium     money_amount,
  basis              valuation_basis NOT NULL DEFAULT 'replacement_cost',
  -- Coinsurance is the clause nobody reads and everybody is penalised by: insure
  -- below the required percentage of replacement cost and the carrier pays a
  -- proportionally reduced share of even a small partial loss.
  coinsurance_percent unit_fraction,
  -- Ordinance and law is the gap that bankrupts owners of older buildings. After
  -- a loss, code compels rebuilding to current standards; a policy without this
  -- endorsement pays only to restore what was there.
  has_ordinance_and_law BOOLEAN NOT NULL DEFAULT FALSE,
  ordinance_and_law_limit money_amount,
  document_id        UUID,
  provenance_id      UUID REFERENCES provenance (id),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT policy_term_ordered CHECK (effective_to > effective_from)
);

CREATE INDEX policies_by_expiry ON policies (effective_to);

CREATE TYPE peril AS ENUM (
  'all_other', 'wind_hail', 'named_storm', 'hurricane', 'flood',
  'earthquake', 'water_damage', 'theft', 'liability'
);

CREATE TABLE coverages (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id          UUID NOT NULL REFERENCES policies (id) ON DELETE CASCADE,
  description        TEXT NOT NULL,          -- 'Coverage A - Dwelling', 'Loss of Rents'
  limit_amount       money_amount,
  peril              peril NOT NULL DEFAULT 'all_other',
  -- Wind and hail deductibles are commonly a percentage of the dwelling limit
  -- rather than a flat sum, which is a materially larger exposure than owners
  -- carry in their heads.
  deductible_amount  money_amount,
  deductible_percent unit_fraction,
  -- Loss of rents is usually capped in months, and the cap is routinely shorter
  -- than a real rebuild after a total loss.
  months_covered     SMALLINT,
  CONSTRAINT one_deductible_form
    CHECK (num_nonnulls(deductible_amount, deductible_percent) <= 1)
);

COMMENT ON TABLE coverages IS
  'The risk engine compares Coverage A against an estimated replacement cost, '
  'applies any coinsurance penalty, and checks loss-of-rents months against a '
  'realistic rebuild time for the vintage and construction type. Underinsurance '
  'is invisible until the day it is catastrophic.';

-- ---------------------------------------------------------------------------
-- Valuation
-- ---------------------------------------------------------------------------

CREATE TYPE valuation_source AS ENUM (
  'avm', 'appraisal', 'broker_opinion', 'assessor', 'purchase_price',
  'comparable_sales', 'owner_estimate', 'replacement_cost_estimate'
);

CREATE TABLE valuations (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id    UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  as_of          DATE NOT NULL,
  source         valuation_source NOT NULL,
  value          money_amount NOT NULL,
  low_estimate   money_amount,
  high_estimate  money_amount,
  provenance_id  UUID NOT NULL REFERENCES provenance (id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT valuation_band_ordered
    CHECK (high_estimate IS NULL OR low_estimate IS NULL OR high_estimate >= low_estimate)
);

CREATE INDEX valuations_latest ON valuations (property_id, as_of DESC);

-- ---------------------------------------------------------------------------
-- The money ledger, append-only
-- ---------------------------------------------------------------------------

CREATE TYPE ledger_category AS ENUM (
  'rent', 'other_income', 'late_fee', 'deposit_received', 'deposit_returned',
  'mortgage_interest', 'mortgage_principal', 'property_tax', 'insurance',
  'repairs', 'capital_improvement', 'utilities', 'management_fee',
  'hoa', 'legal_professional', 'advertising', 'supplies', 'travel',
  'acquisition_cost', 'disposition_cost', 'owner_contribution', 'owner_distribution'
);

CREATE TABLE ledger_events (
  id              BIGSERIAL PRIMARY KEY,
  event_uuid      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  -- RESTRICT, not CASCADE. The ledger is the financial record of record and is
  -- append-only, so a cascade here would be a contradiction: the delete would
  -- always abort on the immutability trigger, and if it did not, disposing of a
  -- property would erase the history a filing was built on. Ownership ends with
  -- properties.disposed_on; deletion is for a property entered in error, and is
  -- refused once money has moved.
  -- Every reference here RESTRICTS. SET NULL looks harmless but is a mutation
  -- of history, and PostgreSQL performs it by issuing a real UPDATE -- which
  -- the append-only trigger refuses, aborting the delete with an error naming a
  -- table the operator never touched. Either the referential action or the
  -- immutability had to give, and immutability is the point: the ledger records
  -- what happened, so the things it names outlive their own deletion.
  property_id     UUID REFERENCES properties (id) ON DELETE RESTRICT,
  unit_id         UUID REFERENCES units (id) ON DELETE RESTRICT,
  lease_id        UUID REFERENCES leases (id) ON DELETE RESTRICT,
  entity_id       UUID REFERENCES entities (id) ON DELETE RESTRICT,

  occurred_on     DATE NOT NULL,        -- when it happened in the world
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when we learned of it

  category        ledger_category NOT NULL,
  amount          money_amount NOT NULL,  -- signed: inflow positive, outflow negative
  memo            TEXT,
  counterparty    TEXT,

  -- Repairs versus improvements is the tangible property regulations' central
  -- question (betterment, adaptation, restoration). The answer decides between
  -- an immediate deduction and a decades-long recovery.
  is_capital      BOOLEAN,
  capitalisation_rationale TEXT,

  -- Corrections append; nothing is ever updated or deleted. A tax position must
  -- be reconstructible exactly as it was taken.
  reverses_event_id BIGINT REFERENCES ledger_events (id),

  document_id     UUID,
  provenance_id   UUID REFERENCES provenance (id),

  CONSTRAINT capital_spending_explains_itself
    CHECK (is_capital IS NOT TRUE OR capitalisation_rationale IS NOT NULL),
  CONSTRAINT reversal_is_not_self CHECK (reverses_event_id IS NULL OR reverses_event_id <> id)
);

CREATE INDEX ledger_by_property_date ON ledger_events (property_id, occurred_on);
CREATE INDEX ledger_by_category ON ledger_events (category, occurred_on);

COMMENT ON TABLE ledger_events IS
  'Append-only and bitemporal. occurred_on is when it happened; recorded_at is '
  'when we learned it. A correction is a new row referencing the one it '
  'reverses, so the ledger can always answer both "what is true" and "what did '
  'we believe when we filed" -- and those two questions have different answers '
  'more often than anyone expects.';

-- ---------------------------------------------------------------------------
-- Documents and extraction
--
-- The seam is lifted wholesale from the healthcare proof of concept: the
-- problem is identical and only the nouns change. Settlement statements, leases,
-- declaration pages and assessment notices instead of clinical records.
-- ---------------------------------------------------------------------------

CREATE TYPE document_kind AS ENUM (
  'settlement_statement', 'deed', 'lease', 'lease_amendment',
  'insurance_declaration', 'mortgage_note', 'mortgage_statement',
  'assessment_notice', 'tax_bill', 'inspection_report', 'appraisal',
  'permit', 'invoice', 'receipt', 'estoppel', 'photo', 'other'
);

CREATE TYPE extraction_status AS ENUM (
  'pending', 'extracted', 'needs_review', 'confirmed', 'rejected'
);

CREATE TABLE source_documents (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind           document_kind NOT NULL,
  filename       TEXT NOT NULL,
  content_hash   CHAR(64) NOT NULL,     -- sha256; content-addressed, so re-uploads dedupe
  byte_size      BIGINT,
  mime_type      TEXT,
  document_date  DATE,
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  uploaded_by    TEXT,
  status         extraction_status NOT NULL DEFAULT 'pending',
  UNIQUE (content_hash)
);

-- Ownership is a relation, not a column. A blanket declaration page, a
-- multi-property settlement statement or an entity-level form belongs to
-- several properties at once; a property_id beside a globally unique
-- content_hash made the second such upload fail outright, and made deleting one
-- property destroy a document another property's provenance chain cites.
CREATE TABLE document_properties (
  document_id  UUID NOT NULL REFERENCES source_documents (id) ON DELETE CASCADE,
  property_id  UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  PRIMARY KEY (document_id, property_id)
);

CREATE TABLE extracted_fields (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id     UUID NOT NULL REFERENCES source_documents (id) ON DELETE CASCADE,
  field_path      TEXT NOT NULL,        -- 'property.parcel_number', 'lease.rent'
  raw_value       TEXT,
  normalised_value TEXT,
  confidence      confidence NOT NULL,
  -- Where on the page, so the owner can see what the machine read.
  page            SMALLINT,
  bounding_box    NUMERIC(6, 4)[],
  needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
  reviewed_by     TEXT,
  reviewed_at     TIMESTAMPTZ,
  accepted_value  TEXT,
  model_id        TEXT,                  -- which model produced this, for eval
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, field_path)
);

CREATE INDEX extracted_needing_review ON extracted_fields (document_id)
  WHERE needs_review;

COMMENT ON TABLE extracted_fields IS
  'Every field carries a confidence and a location on the page. Low confidence '
  'routes to a human rather than into the ledger. This is what makes "the owner '
  'corrects, never enters" an honest claim instead of a slogan: the machine '
  'shows its work, and the correction is one interaction rather than a form.';

-- Now that documents exist, close every deferred reference to them. Four of
-- these were declared as bare UUIDs and never constrained at all, so a lease
-- could cite a document that had never been uploaded.
ALTER TABLE provenance
  ADD CONSTRAINT provenance_document_fk
  FOREIGN KEY (source_document) REFERENCES source_documents (id) ON DELETE SET NULL;
ALTER TABLE leases
  ADD CONSTRAINT leases_document_fk
  FOREIGN KEY (document_id) REFERENCES source_documents (id) ON DELETE SET NULL;
ALTER TABLE debt_instruments
  ADD CONSTRAINT debt_instruments_document_fk
  FOREIGN KEY (document_id) REFERENCES source_documents (id) ON DELETE SET NULL;
ALTER TABLE policies
  ADD CONSTRAINT policies_document_fk
  FOREIGN KEY (document_id) REFERENCES source_documents (id) ON DELETE SET NULL;
ALTER TABLE ledger_events
  ADD CONSTRAINT ledger_events_document_fk
  FOREIGN KEY (document_id) REFERENCES source_documents (id) ON DELETE RESTRICT;

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------

CREATE TABLE audit_log (
  id            BIGSERIAL PRIMARY KEY,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor         TEXT NOT NULL,
  action        TEXT NOT NULL,
  table_name    TEXT,
  record_id     UUID,
  before_value  JSONB,
  after_value   JSONB,
  request_id    TEXT,
  session_id    TEXT
);

CREATE INDEX audit_by_record ON audit_log (table_name, record_id, occurred_at DESC);

COMMENT ON TABLE audit_log IS
  'Correlation fields mirror the platform contract in clio/docs/PLATFORM_STAGE_'
  'PLAN.md so a figure shown in the app can be traced back through the runtime '
  'to the model call that explained it.';
