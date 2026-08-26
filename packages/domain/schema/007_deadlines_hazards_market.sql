-- ===========================================================================
--  Hestia — the deadline spine, hazard facts, market observations, ingestion
--
--  The platform's first real-world test is a date: the May 2027 PVA window.
--  Every date it promises to catch — appeal windows, 1031 clocks, policy and
--  lease expirations, estimated taxes, 1099 filings — lands in one table, so
--  one query answers "what is due" and nothing alerts from a side channel.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Deadlines
-- ---------------------------------------------------------------------------

CREATE TYPE deadline_kind AS ENUM (
  'assessment_appeal_window',   -- the inspection/appeal period itself
  'pva_conference',             -- must occur within the window (KY)
  'exchange_identification',    -- §1031 45-day clock
  'exchange_acquisition',       -- §1031 replacement clock
  'lease_expiration',
  'policy_expiration',
  'loan_maturity',
  'rate_adjustment',            -- ARM reset
  'estimated_tax',
  'form_1099_nec',
  'deposit_itemization',
  'permit_expiration',
  'license_renewal',            -- STR/rental licensing
  'custom'
);

CREATE TYPE deadline_status AS ENUM (
  'upcoming', 'done', 'missed', 'dismissed', 'superseded'
);

CREATE TABLE deadlines (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind             deadline_kind NOT NULL,
  status           deadline_status NOT NULL DEFAULT 'upcoming',

  due_on           DATE NOT NULL,
  -- When action first becomes possible; the KY inspection period opens weeks
  -- before it closes, and showing only the close date hides the runway.
  window_opens_on  DATE,

  -- What the date is about. At least one owner-side anchor is required — a
  -- deadline about nothing alerts no one.
  property_id      UUID REFERENCES properties (id) ON DELETE CASCADE,
  entity_id        UUID REFERENCES entities (id) ON DELETE CASCADE,

  -- Specific anchors, so completing the underlying act can resolve the row.
  lease_id         UUID REFERENCES leases (id) ON DELETE CASCADE,
  policy_id        UUID REFERENCES policies (id) ON DELETE CASCADE,
  debt_id          UUID REFERENCES debt_instruments (id) ON DELETE CASCADE,
  exchange_id      UUID REFERENCES exchanges (id) ON DELETE CASCADE,
  appeal_id        UUID REFERENCES assessment_appeals (id) ON DELETE CASCADE,

  -- The authority that creates the date. A deadline without one is a guess,
  -- and this platform does not alert on guesses.
  citation         TEXT NOT NULL,
  note             TEXT,

  completed_on     DATE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT deadline_is_anchored
    CHECK (property_id IS NOT NULL OR entity_id IS NOT NULL),
  CONSTRAINT window_precedes_due
    CHECK (window_opens_on IS NULL OR window_opens_on <= due_on),
  CONSTRAINT done_records_when
    CHECK (status <> 'done' OR completed_on IS NOT NULL)
);

CREATE INDEX deadlines_due ON deadlines (due_on) WHERE status = 'upcoming';

CREATE TRIGGER deadlines_set_updated_at
  BEFORE UPDATE ON deadlines
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE deadlines IS
  'One table for every date the platform promises to catch. Rows are produced '
  'by the deadline engine from jurisdiction rules and portfolio facts, and by '
  'hand for the genuinely bespoke. The first pass/fail test of the whole '
  'product is whether the May 2027 Kentucky inspection window appears here '
  'with a prepared conference record behind it.';

-- ---------------------------------------------------------------------------
-- Hazard facts — onboarding step 6 finally has somewhere to land
-- ---------------------------------------------------------------------------

CREATE TYPE hazard_kind AS ENUM ('flood', 'wildfire', 'seismic', 'wind', 'radon');

CREATE TABLE hazard_facts (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id        UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  kind               hazard_kind NOT NULL,
  -- FEMA zone designation ('X', 'AE', ...), wildfire risk class, radon zone.
  zone               TEXT,
  in_special_flood_hazard_area BOOLEAN,
  base_flood_elevation_ft      NUMERIC(7, 2),
  map_panel          TEXT,
  map_effective_on   DATE,
  provenance_id      UUID NOT NULL REFERENCES provenance (id),
  observed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- One current fact per hazard per property; a remap replaces it and the old
  -- observation survives through provenance.
  UNIQUE (property_id, kind),
  CONSTRAINT flood_fields_are_flood_only
    CHECK (kind = 'flood'
           OR (in_special_flood_hazard_area IS NULL AND base_flood_elevation_ft IS NULL))
);

COMMENT ON TABLE hazard_facts IS
  'FEMA NFHL and peer sources. Flood zone drives the lender''s insurance '
  'requirement, the premium, and a slice of the risk engine; it is a fact '
  'about the parcel, fetched once and kept with provenance.';

-- ---------------------------------------------------------------------------
-- Market observations — comps and rent estimates, distinct from valuations
-- ---------------------------------------------------------------------------

CREATE TYPE market_metric AS ENUM (
  'rent_estimate',      -- what the unit would let for, per the provider
  'rent_comp',          -- an actual comparable listing/lease
  'sale_comp',          -- a comparable sale
  'market_vacancy',     -- submarket vacancy rate
  'market_cap_rate'     -- submarket cap rate
);

CREATE TABLE market_observations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id     UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  unit_id         UUID REFERENCES units (id) ON DELETE CASCADE,
  metric          market_metric NOT NULL,
  as_of           DATE NOT NULL,
  value_money     money_amount,
  value_rate      rate_decimal,
  low_money       money_amount,
  high_money      money_amount,
  -- Comp identity, when the observation is a specific comparable.
  comp_address    TEXT,
  comp_distance_miles NUMERIC(5, 2),
  comp_bedrooms   NUMERIC(3, 1),
  comp_sf         square_feet,
  provenance_id   UUID NOT NULL REFERENCES provenance (id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT observation_has_one_value
    CHECK (num_nonnulls(value_money, value_rate) = 1),
  CONSTRAINT band_is_ordered
    CHECK (high_money IS NULL OR low_money IS NULL OR high_money >= low_money)
);

CREATE INDEX market_by_property ON market_observations (property_id, metric, as_of DESC);

COMMENT ON TABLE market_observations IS
  'Where rent comps and market stats land. Property VALUE opinions belong in '
  'valuations; this table holds the rent side and the comparables behind both. '
  'The rent engine''s loss-to-lease and the renewal recommendation read from '
  'here.';

-- ---------------------------------------------------------------------------
-- Ingestion runs — raw provider payloads, for reproducibility
-- ---------------------------------------------------------------------------

CREATE TYPE ingestion_status AS ENUM ('ok', 'error');

CREATE TABLE ingestion_runs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider      TEXT NOT NULL,        -- 'census-geocoder', 'fema-nfhl', 'rentcast', ...
  endpoint      TEXT,
  property_id   UUID REFERENCES properties (id) ON DELETE SET NULL,
  requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  status        ingestion_status NOT NULL,
  error_detail  TEXT,
  -- The payload as received. Mapping bugs get fixed by re-mapping stored
  -- payloads, not by re-fetching what the provider may no longer serve.
  raw_response  JSONB,
  CONSTRAINT errors_explain_themselves
    CHECK (status <> 'error' OR error_detail IS NOT NULL)
);

CREATE INDEX ingestion_by_property ON ingestion_runs (property_id, requested_at DESC);

-- ---------------------------------------------------------------------------
-- Rule vocabulary that the seeds need
-- ---------------------------------------------------------------------------

-- URLTA adoption is its own rule domain: Kentucky's landlord-tenant law is
-- opt-in per jurisdiction, and whether the Act binds is the first question
-- every other landlord-tenant rule depends on.
ALTER TYPE rule_domain ADD VALUE IF NOT EXISTS 'landlord_tenant_act';
ALTER TYPE rule_domain ADD VALUE IF NOT EXISTS 'estimated_tax';
