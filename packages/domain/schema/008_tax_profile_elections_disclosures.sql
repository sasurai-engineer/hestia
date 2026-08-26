-- ===========================================================================
--  Hestia — the taxpayer profile, the elections register, disclosure execution
--
--  Without a profile, every tax card silently assumes a rate; without the
--  elections register, the ledger cannot know whether a $2,000 invoice is a
--  de-minimis expense or a capitalisation; without a disclosure log, federal
--  duties rest on memory. All three are facts about a filing year, carried
--  with the same provenance discipline as everything else.
-- ===========================================================================

CREATE TYPE filing_status AS ENUM (
  'single', 'married_filing_jointly', 'married_filing_separately', 'head_of_household'
);

-- How the entity is taxed — which entity_kind alone does not determine.
CREATE TYPE entity_tax_treatment AS ENUM (
  'disregarded', 'partnership', 's_corporation', 'c_corporation'
);

CREATE TABLE tax_profiles (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id             UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
  tax_year              SMALLINT NOT NULL,
  treatment             entity_tax_treatment NOT NULL,
  filing_status         filing_status,
  -- Estimates, and marked as such through provenance: the engines take these
  -- as inputs and cite them; they never invent a rate.
  magi_estimate         money_amount,
  federal_marginal_rate annual_rate,
  state_marginal_rate   annual_rate,
  capital_gains_rate    annual_rate,
  provenance_id         UUID REFERENCES provenance (id),
  notes                 TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT plausible_tax_year CHECK (tax_year BETWEEN 1990 AND 2200),
  UNIQUE (entity_id, tax_year)
);

CREATE TRIGGER tax_profiles_set_updated_at
  BEFORE UPDATE ON tax_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE tax_profiles IS
  'One row per entity per filing year. The engines'' worked examples hardcoded '
  '"a 32% marginal rate"; this is where that number actually lives, with '
  'provenance, so a tax-position card can cite its assumption instead of '
  'burying it.';

-- ---------------------------------------------------------------------------
-- Annual elections — statements attached to a filing year
-- ---------------------------------------------------------------------------

CREATE TYPE tax_election_kind AS ENUM (
  'de_minimis_safe_harbor',      -- Treas. Reg. 1.263(a)-1(f)
  'small_taxpayer_safe_harbor',  -- Treas. Reg. 1.263(a)-3(h)
  'routine_maintenance',         -- Treas. Reg. 1.263(a)-3(i), method position
  'bonus_election_out',          -- IRC 168(k)(7), by property class
  'reps_aggregation',            -- Treas. Reg. 1.469-9(g)
  'activity_grouping',           -- Treas. Reg. 1.469-4
  'partial_disposition'          -- Treas. Reg. 1.168(i)-8(d)
);

CREATE TABLE tax_elections (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id    UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
  tax_year     SMALLINT NOT NULL,
  kind         tax_election_kind NOT NULL,
  -- NULL property = an entity-wide election; a row per property when scoped.
  property_id  UUID REFERENCES properties (id) ON DELETE CASCADE,
  -- The election's operative parameter: '$2,500 per invoice', a class, hours.
  parameters   TEXT,
  citation     TEXT NOT NULL,
  made_on      DATE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT plausible_election_year CHECK (tax_year BETWEEN 1990 AND 2200),
  -- NULLS NOT DISTINCT: an entity-wide election is the normal case, and under
  -- default semantics it could be recorded without limit and double-read.
  UNIQUE NULLS NOT DISTINCT (entity_id, tax_year, kind, property_id)
);

COMMENT ON TABLE tax_elections IS
  'The de-minimis election changes how the ledger must categorise spending, '
  'the aggregation election changes the REPS material-participation unit, and '
  'none of them is derivable from the numbers — they are statements, so they '
  'are rows.';

-- ---------------------------------------------------------------------------
-- Disclosure execution — the duty is discharged by delivery, not by knowing
-- ---------------------------------------------------------------------------

CREATE TYPE disclosure_kind AS ENUM (
  'lead_paint', 'radon', 'mold', 'flood', 'methamphetamine', 'other'
);

CREATE TABLE disclosures (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id   UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  lease_id      UUID REFERENCES leases (id) ON DELETE SET NULL,
  kind          disclosure_kind NOT NULL,
  delivered_on  DATE NOT NULL,
  delivered_to  TEXT NOT NULL,
  method        TEXT,                      -- 'lease packet', 'hand delivery', ...
  -- RESTRICT: the stored document IS the evidence a federal duty was met;
  -- deleting it out from under the record must be a refusal.
  document_id   UUID REFERENCES source_documents (id) ON DELETE RESTRICT,
  citation      TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX disclosures_by_property ON disclosures (property_id, kind);

COMMENT ON TABLE disclosures IS
  'A pre-1978 property with a suspected lead_paint row in latent_defects and '
  'no lead_paint row here for the active lease is a compliance gap the '
  'platform can now actually see — 42 U.S.C. 4852d penalties run per '
  'violation, and "we always include the pamphlet" is not a record.';
