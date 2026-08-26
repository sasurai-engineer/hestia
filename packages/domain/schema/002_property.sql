-- ===========================================================================
--  Hestia — the asset: properties, units, and the component inventory
-- ===========================================================================

CREATE TYPE property_kind AS ENUM (
  'single_family',
  'duplex',
  'triplex',
  'fourplex',
  'small_multifamily',   -- 5-20 units
  'condominium',
  'townhouse',
  'manufactured',
  'mixed_use',
  'land'
);

CREATE TYPE holding_purpose AS ENUM (
  'long_term_rental',
  'short_term_rental',   -- unlocks the IRC 469 seven-day exception
  'primary_residence',
  'second_home',
  'flip',
  'development',
  'land_hold'
);

CREATE TABLE properties (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id           UUID NOT NULL REFERENCES entities (id),
  label               TEXT NOT NULL,        -- '412 Maple' — how the owner refers to it

  -- Location
  street_1            TEXT NOT NULL,
  street_2            TEXT,
  city                TEXT NOT NULL,
  state               us_state NOT NULL,
  postal_code         TEXT NOT NULL,
  county              TEXT,
  latitude            NUMERIC(9, 6),
  longitude           NUMERIC(9, 6),

  -- The governing body chain is resolved at onboarding and stored, because it
  -- decides which landlord-tenant regime, appeal window and tax treatment apply.
  jurisdiction_id     UUID REFERENCES jurisdictions (id),

  -- Public record identity
  parcel_number       TEXT,                 -- APN / PIN / PVA parcel id
  legal_description   TEXT,

  -- Physical
  kind                property_kind NOT NULL,
  purpose             holding_purpose NOT NULL DEFAULT 'long_term_rental',
  year_built          SMALLINT,
  year_renovated      SMALLINT,
  building_sf         square_feet,
  lot_sf              square_feet,
  stories             SMALLINT,
  unit_count          SMALLINT NOT NULL DEFAULT 1,

  -- Hold period
  acquired_on         DATE,
  disposed_on         DATE,

  -- Provenance for the inferred physical attributes above.
  provenance_id       UUID REFERENCES provenance (id),

  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT disposed_after_acquired
    CHECK (disposed_on IS NULL OR acquired_on IS NULL OR disposed_on >= acquired_on),
  CONSTRAINT plausible_year_built
    CHECK (year_built IS NULL OR (year_built BETWEEN 1600 AND 2200)),
  CONSTRAINT renovated_after_built
    CHECK (year_renovated IS NULL OR year_built IS NULL OR year_renovated >= year_built),
  CONSTRAINT positive_unit_count CHECK (unit_count >= 1)
);

CREATE INDEX properties_by_entity ON properties (entity_id) WHERE disposed_on IS NULL;
CREATE INDEX properties_by_parcel ON properties (state, parcel_number);

COMMENT ON COLUMN properties.year_built IS
  'Load-bearing far beyond description. Vintage drives component age inference, '
  'the latent-defect register (lead paint before 1978, asbestos before 1980, '
  'aluminium branch wiring 1965-73, Orangeburg sewer 1945-72), insurance '
  'ordinance-and-law exposure, and financeability.';

-- ---------------------------------------------------------------------------
-- Units
-- ---------------------------------------------------------------------------

CREATE TABLE units (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id     UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  label           TEXT NOT NULL,            -- 'A', '2R', 'Unit 3'
  bedrooms        NUMERIC(3, 1),            -- halves exist in the wild
  bathrooms       NUMERIC(3, 1),
  living_sf       square_feet,
  floor           SMALLINT,
  market_rent     money_amount,             -- current market estimate, not in-place rent
  market_rent_as_of DATE,
  provenance_id   UUID REFERENCES provenance (id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (property_id, label)
);

COMMENT ON COLUMN units.market_rent IS
  'What the unit would let for today, distinct from the rent in force. The gap '
  'between them is loss to lease, which the rent engine works to close without '
  'triggering a turnover that costs more than the increase earns.';

-- ---------------------------------------------------------------------------
-- Component inventory — the structure no competitor keeps
-- ---------------------------------------------------------------------------

CREATE TYPE component_system AS ENUM (
  'roof', 'exterior', 'windows_doors', 'structure', 'foundation',
  'hvac', 'plumbing', 'electrical', 'water_heater',
  'interior_finish', 'appliance', 'site', 'life_safety', 'elevator'
);

-- The catalogue: what a component of this kind normally is and how it fails.
CREATE TABLE component_types (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code                 TEXT NOT NULL UNIQUE,   -- 'roof.asphalt_shingle.architectural'
  system               component_system NOT NULL,
  display_name         TEXT NOT NULL,

  -- Service life, as a range rather than a point. The band is the honest form:
  -- a shingle roof lasts 15 years in Phoenix and 25 in Seattle.
  life_years_low       NUMERIC(5, 2) NOT NULL,
  life_years_high      NUMERIC(5, 2) NOT NULL,

  -- Weibull parameters for the survival model. Shape > 1 means the hazard rate
  -- rises with age, which is true of everything here; scale is characteristic
  -- life in years. These drive the Monte Carlo capital forecast.
  weibull_shape        NUMERIC(6, 3) NOT NULL DEFAULT 3.0,
  weibull_scale_years  NUMERIC(6, 2) NOT NULL,

  -- Replacement cost, per unit of measure, before regional adjustment.
  typical_cost         money_amount,
  cost_unit            TEXT,                   -- 'each', 'per_sf', 'per_square'

  -- Consequence of failure, which is not the same as cost of replacement.
  causes_water_damage  BOOLEAN NOT NULL DEFAULT FALSE,
  is_life_safety       BOOLEAN NOT NULL DEFAULT FALSE,
  notes                TEXT,

  CONSTRAINT life_band_ordered CHECK (life_years_high >= life_years_low),
  CONSTRAINT positive_life CHECK (life_years_low > 0),
  -- Shape strictly above 1 is what "rising hazard" means. Admitting (0,1]
  -- allowed a *falling* hazard -- a component that grows less likely to fail
  -- as it ages -- which is the opposite of everything catalogued here.
  CONSTRAINT rising_hazard CHECK (weibull_shape > 1),
  -- Characteristic life appears in the denominator of exp(-(t/scale)^shape);
  -- zero divides, negative yields no real hazard, and either silently corrupts
  -- the capital forecast for every property carrying the type.
  CONSTRAINT positive_characteristic_life CHECK (weibull_scale_years > 0)
);

COMMENT ON COLUMN component_types.causes_water_damage IS
  'A failed tank water heater is the leading source of interior water-loss '
  'claims. Its replacement cost is trivial; its failure cost is not. The capital '
  'engine weights these differently and the maintenance calendar pulls them '
  'forward.';

-- The instances actually on a property.
CREATE TYPE component_condition AS ENUM (
  'new', 'good', 'fair', 'poor', 'failed', 'unknown'
);

CREATE TABLE components (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id         UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  unit_id             UUID REFERENCES units (id) ON DELETE CASCADE,
  component_type_id   UUID NOT NULL REFERENCES component_types (id),

  -- When it went in. Usually not known, usually inferrable, always uncertain --
  -- which is exactly why provenance is mandatory on this table.
  installed_on        DATE,
  installed_year_low  SMALLINT,   -- the credible band when the date is inferred
  installed_year_high SMALLINT,
  provenance_id       UUID NOT NULL REFERENCES provenance (id),

  quantity            NUMERIC(10, 2) NOT NULL DEFAULT 1,
  condition           component_condition NOT NULL DEFAULT 'unknown',
  last_serviced_on    DATE,
  warranty_expires_on DATE,

  -- Overrides of the catalogue defaults, when something is known to differ.
  expected_life_years NUMERIC(5, 2),
  replacement_cost    money_amount,

  -- Lifecycle. A replaced component is retained, never deleted: the history is
  -- what makes the next inference better than the last.
  retired_on          DATE,
  replaced_by_id      UUID REFERENCES components (id),

  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT install_band_ordered
    CHECK (installed_year_high IS NULL OR installed_year_low IS NULL
           OR installed_year_high >= installed_year_low),
  CONSTRAINT install_known_or_bounded
    CHECK (installed_on IS NOT NULL OR installed_year_low IS NOT NULL),
  CONSTRAINT retired_after_installed
    CHECK (retired_on IS NULL OR installed_on IS NULL OR retired_on >= installed_on),
  CONSTRAINT no_self_replacement
    CHECK (replaced_by_id IS NULL OR replaced_by_id <> id)
);

CREATE INDEX components_live_by_property
  ON components (property_id) WHERE retired_on IS NULL;

COMMENT ON TABLE components IS
  'Every incumbent asks the owner to type in forty install dates they do not '
  'know, and so the table stays empty and the capital plan stays a guess. '
  'Hestia infers the inventory at onboarding from vintage, permit history and '
  'regional norms, records how confident it is in each date, and lets the owner '
  'correct what is wrong. An inferred roof age with a ten-year band still '
  'forecasts better than no roof at all.';

-- ---------------------------------------------------------------------------
-- Latent defects — vintage risk that is not wear
-- ---------------------------------------------------------------------------

CREATE TYPE defect_kind AS ENUM (
  'lead_paint',              -- pre-1978: disclosure duty and the EPA RRP rule
  'asbestos',                -- pre-1980
  'aluminium_branch_wiring', -- 1965-73
  'federal_pacific_panel',   -- Stab-Lok; a fire risk and an insurance refusal
  'zinsco_panel',
  'polybutylene_supply',
  'orangeburg_sewer',        -- 1945-72
  'galvanized_supply',
  'cast_iron_drain',
  'knob_and_tube',
  'underground_storage_tank',
  'radon',
  'mold',
  'unpermitted_work'         -- kills refinancings and sales, not just safety
);

CREATE TYPE defect_status AS ENUM (
  'suspected',    -- inferred from vintage; not yet confirmed
  'confirmed',
  'remediated',
  'ruled_out'
);

CREATE TABLE latent_defects (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id    UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  kind           defect_kind NOT NULL,
  status         defect_status NOT NULL DEFAULT 'suspected',
  provenance_id  UUID NOT NULL REFERENCES provenance (id),

  -- The four consequences, which are rarely considered together.
  affects_safety      BOOLEAN NOT NULL DEFAULT FALSE,
  affects_insurance   BOOLEAN NOT NULL DEFAULT FALSE,
  affects_financing   BOOLEAN NOT NULL DEFAULT FALSE,
  triggers_disclosure BOOLEAN NOT NULL DEFAULT FALSE,

  estimated_remediation money_amount,
  identified_on         DATE NOT NULL DEFAULT CURRENT_DATE,
  remediated_on         DATE,
  citation              TEXT,     -- the rule creating the obligation, where one does
  notes                 TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT remediated_has_a_date
    CHECK (status <> 'remediated' OR remediated_on IS NOT NULL),
  UNIQUE (property_id, kind)
);

COMMENT ON TABLE latent_defects IS
  'Each of these is simultaneously a capital event, an insurance problem, a '
  'financing obstacle and a disclosure duty -- and owners typically meet them '
  'one at a time, at the worst moment. Northern Kentucky stock is old enough '
  'that most are live risks rather than hypotheticals.';
