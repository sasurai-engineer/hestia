-- ===========================================================================
--  Hestia — foundations
--
--  Money, provenance, time, and the ownership structure everything hangs from.
--
--  Three rules govern this schema and are worth stating before the first table:
--
--  1. MONEY IS NEVER A FLOAT. Every monetary column is NUMERIC. A cent lost to
--     binary rounding is a cent that reappears in a tax filing.
--
--  2. EVERY FACT CARRIES ITS PROVENANCE. The product's central promise is that
--     the owner *corrects* rather than *enters* — which is only honest if the
--     interface can show where each value came from and how sure we are. A
--     value inferred from a building's vintage and a value read off a permit
--     are not the same claim and must not render the same.
--
--  3. RULES AND FACTS ARE EFFECTIVE-DATED. Depreciation applies the law as of
--     the placed-in-service date, not today's law. A lease term, an assessment,
--     a statutory notice period — each is true for a span, and the span is part
--     of the fact.
--
--  Renters are `residents`. In the surrounding platform `tenant` means
--  workspace, and the collision is settled here permanently in favour of
--  clarity.
-- ===========================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- For the exclusion constraint that stops two active leases overlapping on
-- one unit; GiST needs it to index the scalar half of that predicate.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- Domains
-- ---------------------------------------------------------------------------

-- Currency amounts. Scale 2 is the minor unit; the application layer holds the
-- same values as integer cents and the two must agree exactly.
CREATE DOMAIN money_amount AS NUMERIC(18, 2);

-- A general ratio expressed as a decimal: 0.0675 is 6.75%. Scale 8 carries a
-- daily periodic rate without drift over a 360-month term. Bounded only against
-- the absurd, because legitimate values here include multiples above 1 -- an
-- equity multiple, a 150% declining-balance factor. Interest rates use the
-- narrower `annual_rate` below.
CREATE DOMAIN rate_decimal AS NUMERIC(12, 8)
  CHECK (VALUE > -1000 AND VALUE < 1000);

-- An annual interest rate, which is a much narrower thing than a general
-- ratio: no mortgage, note or margin in this domain reaches 100%.
--
-- The bound is the point. Typing a rate in percent form where the column wants
-- decimal form -- 6.75 for 6.75% -- is the commonest data-entry error here, and
-- an unconstrained NUMERIC(12,8) accepted it as a 675% rate that the
-- amortisation engine then computed a payment from, hundredfold too large,
-- with no null and no error to hint at it.
CREATE DOMAIN annual_rate AS NUMERIC(12, 8)
  CHECK (VALUE > -1 AND VALUE < 1);

-- Areas in square feet, and land in acres.
CREATE DOMAIN square_feet AS NUMERIC(12, 2) CHECK (VALUE >= 0);

-- A confidence in [0,1]. Required wherever a value may be inferred.
CREATE DOMAIN confidence AS NUMERIC(4, 3)
  CHECK (VALUE >= 0 AND VALUE <= 1);

-- Any proportion in [0,1]: a bonus election, a coinsurance percentage, an
-- ownership share. Declared once so the twenty-odd hand-rolled copies of this
-- predicate cannot drift apart -- two of them already had, one tolerating NULL
-- where the other did not.
CREATE DOMAIN unit_fraction AS NUMERIC(12, 8)
  CHECK (VALUE >= 0 AND VALUE <= 1);

-- Money that cannot be negative: a basis, a principal, a rent.
CREATE DOMAIN money_nonneg AS NUMERIC(18, 2)
  CHECK (VALUE >= 0);

CREATE DOMAIN us_state AS CHAR(2)
  CHECK (VALUE ~ '^[A-Z]{2}$');

CREATE DOMAIN email_address AS TEXT
  CHECK (VALUE ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$');

-- ---------------------------------------------------------------------------
-- Provenance — how we know what we claim to know
-- ---------------------------------------------------------------------------

CREATE TYPE provenance_kind AS ENUM (
  'owner_stated',     -- the owner typed it; treat as authoritative
  'document',         -- extracted from a settlement statement, lease, policy
  'public_record',    -- assessor, recorder, permit office
  'market_data',      -- AVM, rent comps, a commercial data provider
  'inferred',         -- derived by Hestia from other facts (vintage, norms)
  'default'           -- a regional or category norm, standing in for nothing
);

COMMENT ON TYPE provenance_kind IS
  'Ordered loosely by authority. The UI must render inferred and default values '
  'differently from stated and documented ones: presenting a guess with the same '
  'confidence as a closing statement is the failure this column exists to prevent.';

-- Attached to any table carrying facts that may be inferred rather than known.
CREATE TABLE provenance (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            provenance_kind NOT NULL,
  confidence      confidence NOT NULL,
  source_label    TEXT,           -- 'Campbell County PVA', 'ALTA statement 2019-04-11'
  source_document UUID,           -- FK added in the documents module
  derived_from    TEXT,           -- prose description of the inference, when kind='inferred'
  observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT stated_facts_are_certain
    CHECK (kind <> 'owner_stated' OR confidence = 1.0),
  CONSTRAINT inferences_explain_themselves
    CHECK (kind <> 'inferred' OR derived_from IS NOT NULL)
);

COMMENT ON CONSTRAINT inferences_explain_themselves ON provenance IS
  'An inference the system cannot explain is one the owner cannot check.';

-- ---------------------------------------------------------------------------
-- Ownership structure
-- ---------------------------------------------------------------------------

CREATE TYPE entity_kind AS ENUM (
  'individual',
  'joint',
  'llc',
  'series_llc_cell',
  'limited_partnership',
  's_corporation',
  'c_corporation',
  'revocable_trust',
  'irrevocable_trust',
  'land_trust'
);

CREATE TABLE entities (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name              TEXT NOT NULL,
  kind              entity_kind NOT NULL,
  -- Formation state governs charging-order protection and franchise tax, and
  -- is frequently not the state the property sits in.
  formation_state   us_state,
  formed_on         DATE,
  dissolved_on      DATE,
  ein_last4         CHAR(4),      -- never store a full EIN
  parent_entity_id  UUID REFERENCES entities (id),
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT dissolved_after_formed CHECK (dissolved_on IS NULL OR formed_on IS NULL OR dissolved_on >= formed_on),
  CONSTRAINT no_self_parent CHECK (parent_entity_id IS NULL OR parent_entity_id <> id)
);

COMMENT ON COLUMN entities.ein_last4 IS
  'Last four digits only. The full identifier has no operational use here and '
  'storing it creates an obligation without a benefit.';

-- ---------------------------------------------------------------------------
-- Jurisdictions — the rules engine's spine
-- ---------------------------------------------------------------------------

CREATE TYPE jurisdiction_level AS ENUM (
  'federal', 'state', 'county', 'municipality', 'special_district'
);

CREATE TABLE jurisdictions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  level         jurisdiction_level NOT NULL,
  name          TEXT NOT NULL,
  state         us_state,
  parent_id     UUID REFERENCES jurisdictions (id),
  -- FIPS where one exists; the stable join key to census and assessor data.
  fips_code     TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT state_required_below_federal
    CHECK (level = 'federal' OR state IS NOT NULL),
  CONSTRAINT no_self_parent CHECK (parent_id IS NULL OR parent_id <> id),
  -- NULLS NOT DISTINCT because `state` is NULL for exactly the federal tier,
  -- and under the default semantics that is the one tier this key could not
  -- deduplicate. Duplicate federal parents make the municipality -> county ->
  -- state -> federal walk non-deterministic.
  UNIQUE NULLS NOT DISTINCT (level, name, state)
);

COMMENT ON TABLE jurisdictions IS
  'A hierarchy, because a property is governed by several bodies at once and '
  'they do not agree. Kentucky is the motivating case: URLTA (KRS 383.500-715) '
  'binds only the roughly nineteen governments that formally adopted it, so '
  'Newport and Covington are covered while unincorporated Campbell and Kenton '
  'counties are not. A property one street across a city line has different '
  'deposit rules, notice periods and cure rights. Resolution walks municipality '
  '-> county -> state -> federal and takes the most specific rule that applies.';

-- The rules themselves are effective-dated and versioned, never overwritten.
CREATE TYPE rule_domain AS ENUM (
  'security_deposit',
  'notice_period',
  'rent_regulation',
  'eviction_procedure',
  'late_fee',
  'habitability',
  'registration',
  'disclosure',
  'assessment_appeal',
  'transfer_tax',
  'occupancy_tax',
  'income_tax',
  'depreciation_conformity'
);

CREATE TABLE jurisdiction_rules (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jurisdiction_id  UUID NOT NULL REFERENCES jurisdictions (id),
  domain           rule_domain NOT NULL,
  code             TEXT NOT NULL,          -- 'deposit.return_days', 'appeal.window_days'
  -- Values are typed loosely on purpose: a rule is variously a number of days,
  -- a money cap, a multiple of rent, or a prose obligation.
  value_numeric    NUMERIC(18, 6),
  value_money      money_amount,
  value_text       TEXT,
  -- The authority. A rule without a citation is an opinion.
  citation         TEXT NOT NULL,
  effective_from   DATE NOT NULL,
  effective_to     DATE,
  superseded_by    UUID REFERENCES jurisdiction_rules (id),
  recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT effective_range_ordered
    CHECK (effective_to IS NULL OR effective_to > effective_from),
  CONSTRAINT rule_has_a_value
    CHECK (num_nonnulls(value_numeric, value_money, value_text) >= 1)
);

CREATE INDEX jurisdiction_rules_lookup
  ON jurisdiction_rules (jurisdiction_id, domain, code, effective_from DESC);

COMMENT ON COLUMN jurisdiction_rules.citation IS
  'Statute, ordinance, revenue procedure or published assessor procedure. Every '
  'recommendation Hestia makes is expected to cite one of these back to the owner.';

COMMENT ON TABLE jurisdiction_rules IS
  'Bitemporal by construction: effective_from/effective_to is when the rule was '
  'true in the world, recorded_at is when we learned it. Both are needed to '
  'answer "what did we believe on the day we filed", which is the question that '
  'arrives with an audit letter.';
