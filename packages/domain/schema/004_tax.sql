-- ===========================================================================
--  Hestia — tax
--
--  The load-bearing idea here is DUAL BOOKS. Federal and state depreciation
--  diverge permanently and no consumer tool models it.
--
--  Kentucky is the motivating case and the one this schema was shaped against.
--  OBBBA (P.L. 119-21, 4 Jul 2025) restored 100% bonus depreciation permanently
--  for property placed in service after 19 Jan 2025. Kentucky did not follow:
--  it requires an IRC 168(k) add-back and computes state depreciation under
--  IRC 168 as in effect on 31 December 2001. A cost segregation study therefore
--  delivers the entire federal benefit and nothing at all in Kentucky, and the
--  two schedules never reconverge for the life of the asset.
--
--  Reporting a single depreciation number to a Kentucky owner is not a
--  simplification. It is wrong.
-- ===========================================================================

CREATE TYPE tax_book AS ENUM ('federal', 'state', 'amt', 'book');

CREATE TYPE depreciation_method AS ENUM (
  'macrs_gds_sl',      -- straight line: 27.5-yr residential, 39-yr nonresidential
  'macrs_gds_200db',   -- 200% declining balance: 5- and 7-year personal property
  'macrs_gds_150db',   -- 150% declining balance: 15-year land improvements
  'macrs_ads_sl',      -- ADS straight line; forced by the 163(j) election
  'section_179',
  'bonus',
  'not_depreciable'    -- land
);

CREATE TYPE depreciation_convention AS ENUM ('half_year', 'mid_quarter', 'mid_month');

CREATE TYPE asset_class AS ENUM (
  'land',                    -- never depreciable, and the reason allocation matters
  'building',
  'land_improvement',        -- 15-year: paving, fencing, landscaping
  'personal_property_5yr',   -- appliances, carpet, decorative lighting
  'personal_property_7yr',
  'qualified_improvement',   -- QIP, 15-year
  'building_improvement'
);

-- ---------------------------------------------------------------------------
-- Purchase price allocation
-- ---------------------------------------------------------------------------

CREATE TABLE price_allocations (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id          UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  allocated_on         DATE NOT NULL,
  total_basis          money_nonneg NOT NULL,
  land_value           money_nonneg NOT NULL,
  improvement_value    money_nonneg NOT NULL,
  personal_property    money_nonneg NOT NULL DEFAULT 0,
  -- How the split was arrived at. An assessor ratio is defensible; a round
  -- number someone liked is not.
  method               TEXT NOT NULL,
  provenance_id        UUID NOT NULL REFERENCES provenance (id),
  notes                TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT allocation_sums_to_basis
    CHECK (land_value + improvement_value + personal_property = total_basis)
  -- Non-negativity is carried by the money_nonneg domain on each column, so
  -- restating it here would be a second, independently-editable copy of one
  -- rule -- which is what the domain was introduced to stop.
);

COMMENT ON TABLE price_allocations IS
  'One careless line at closing sets the depreciation life of the asset forever. '
  'Land is never depreciable, so every dollar parked there is a dollar of '
  'deduction surrendered for the whole hold -- and the split is routinely done '
  'by copying whatever ratio the assessor happened to publish. The constraint '
  'that the parts sum to the whole is the least this table can enforce.';

-- ---------------------------------------------------------------------------
-- Depreciable assets, one row per asset PER BOOK
-- ---------------------------------------------------------------------------

CREATE TABLE depreciable_assets (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- RESTRICT for the same reason as the ledger: depreciation_entries are
  -- append-only so a filing can be reproduced exactly as it was made.
  property_id           UUID NOT NULL REFERENCES properties (id) ON DELETE RESTRICT,
  component_id          UUID REFERENCES components (id) ON DELETE SET NULL,
  book                  tax_book NOT NULL,
  jurisdiction_id       UUID REFERENCES jurisdictions (id),  -- which state, when book='state'

  description           TEXT NOT NULL,
  class                 asset_class NOT NULL,
  method                depreciation_method NOT NULL,
  convention            depreciation_convention NOT NULL DEFAULT 'mid_month',
  recovery_years        NUMERIC(5, 2),

  placed_in_service_on  DATE NOT NULL,
  original_basis        money_nonneg NOT NULL,

  -- Elections taken in the placed-in-service year.
  bonus_percent         unit_fraction NOT NULL DEFAULT 0,
  section_179_amount    money_amount NOT NULL DEFAULT 0,

  -- Disposition. Which recapture section applies is decided by class, and the
  -- difference is 25% versus ordinary rates.
  disposed_on           DATE,
  disposition_proceeds  money_amount,

  cost_segregation_id   UUID,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT land_is_not_depreciated
    CHECK (class <> 'land' OR method = 'not_depreciable'),
  CONSTRAINT depreciable_assets_have_a_life
    CHECK (method = 'not_depreciable' OR recovery_years IS NOT NULL),
  CONSTRAINT state_assets_name_their_state
    CHECK (book <> 'state' OR jurisdiction_id IS NOT NULL),
  CONSTRAINT positive_basis CHECK (original_basis >= 0)
);

CREATE INDEX depreciable_by_property_book
  ON depreciable_assets (property_id, book) WHERE disposed_on IS NULL;

COMMENT ON COLUMN depreciable_assets.book IS
  'The same physical asset appears once per book with different elections. A '
  'cost-segregated dishwasher is 5-year 200DB with 100% bonus federally and, in '
  'a non-conforming state such as Kentucky, 5-year 200DB with no bonus at all.';

COMMENT ON COLUMN depreciable_assets.bonus_percent IS
  'Stored rather than derived, because the rate is a function of the '
  'placed-in-service date under law that has changed repeatedly. A schedule '
  'recomputed under today''s rules would silently restate prior filings.';

-- The computed schedule. Written per year per book so a filing can be
-- reproduced exactly as it was made.
CREATE TABLE depreciation_entries (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- RESTRICT, not CASCADE: depreciation_entries are append-only, so the cascade
  -- would be performed as a DELETE the immutability trigger refuses. A filing
  -- must stay reproducible even when the asset behind it was set up wrong.
  asset_id             UUID NOT NULL REFERENCES depreciable_assets (id) ON DELETE RESTRICT,
  tax_year             SMALLINT NOT NULL,
  amount               money_nonneg NOT NULL,
  accumulated          money_nonneg NOT NULL,
  -- The rules actually applied, captured at computation time.
  law_as_of            DATE NOT NULL,
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (asset_id, tax_year)
);

COMMENT ON COLUMN depreciation_entries.law_as_of IS
  'Which vintage of the code produced this figure. Without it a restatement is '
  'indistinguishable from an error.';

-- ---------------------------------------------------------------------------
-- Cost segregation
-- ---------------------------------------------------------------------------

CREATE TABLE cost_segregation_studies (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id             UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  performed_by            TEXT,
  performed_on            DATE,
  study_cost              money_amount,
  reclassified_5yr        money_amount NOT NULL DEFAULT 0,
  reclassified_7yr        money_amount NOT NULL DEFAULT 0,
  reclassified_15yr       money_amount NOT NULL DEFAULT 0,
  remaining_39_or_275     money_amount NOT NULL DEFAULT 0,
  -- Modelled before it is commissioned; the go/no-go must run to the exit.
  is_hypothetical         BOOLEAN NOT NULL DEFAULT TRUE,
  notes                   TEXT,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE cost_segregation_studies IS
  'A study is normally sold on its first-year deduction alone. That number is '
  'not the benefit. Accelerated basis returns as section 1245 recapture at '
  'ordinary rates on sale, state conformity may withhold the deduction entirely, '
  'and passive-activity limits can defer the whole thing. Hestia models the '
  'study through disposition or it does not model it.';

ALTER TABLE depreciable_assets
  ADD CONSTRAINT depreciable_assets_cost_seg_fk
  FOREIGN KEY (cost_segregation_id) REFERENCES cost_segregation_studies (id);

-- ---------------------------------------------------------------------------
-- Passive activity, material participation, and the hour logs
-- ---------------------------------------------------------------------------

CREATE TABLE passive_loss_carryforwards (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id       UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
  property_id     UUID REFERENCES properties (id) ON DELETE CASCADE,
  tax_year        SMALLINT NOT NULL,
  suspended_loss  money_amount NOT NULL,
  released_loss   money_amount NOT NULL DEFAULT 0,
  at_risk_basis   money_amount,
  notes           TEXT,
  -- NULLS NOT DISTINCT: an entity-level carryforward has no property, and
  -- under the default semantics those rows -- the normal case for a IRC 469
  -- suspended loss -- could be inserted without limit, double-counting on
  -- any later SUM.
  UNIQUE NULLS NOT DISTINCT (entity_id, property_id, tax_year)
);

CREATE TYPE participation_purpose AS ENUM (
  'reps_750_hour',        -- IRC 469(c)(7) real estate professional status
  'material_participation',
  'qbi_safe_harbor',      -- Rev. Proc. 2019-38, 250 hours
  'short_term_rental'     -- the seven-day exception
);

CREATE TABLE participation_hours (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id     UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
  property_id   UUID REFERENCES properties (id) ON DELETE CASCADE,
  purpose       participation_purpose NOT NULL,
  occurred_on   DATE NOT NULL,
  hours         NUMERIC(5, 2) NOT NULL,
  activity      TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT positive_hours CHECK (hours > 0),
  CONSTRAINT plausible_day CHECK (hours <= 24)
);

CREATE INDEX participation_by_year
  ON participation_hours (entity_id, purpose, occurred_on);

COMMENT ON TABLE participation_hours IS
  'Contemporaneous logs, which is the whole point: both REPS and the section '
  '199A safe harbour are lost on substantiation far more often than on the '
  'hours themselves. A log reconstructed in April is worth little.';

-- ---------------------------------------------------------------------------
-- Property tax: assessments and the appeal window
-- ---------------------------------------------------------------------------

CREATE TABLE assessments (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id       UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  jurisdiction_id   UUID NOT NULL REFERENCES jurisdictions (id),
  tax_year          SMALLINT NOT NULL,
  assessed_land     money_amount,
  assessed_improvement money_amount,
  assessed_total    money_amount NOT NULL,
  market_value_opinion money_amount,       -- our own estimate, for the over-assessment test
  millage_rate      NUMERIC(10, 6),
  tax_billed        money_amount,
  notice_received_on DATE,
  provenance_id     UUID REFERENCES provenance (id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (property_id, jurisdiction_id, tax_year)
);

CREATE TYPE appeal_stage AS ENUM (
  'not_filed', 'conference_requested', 'conference_held',
  'filed_with_board', 'board_heard', 'decided', 'withdrawn', 'appealed_further'
);

CREATE TABLE assessment_appeals (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id       UUID NOT NULL REFERENCES assessments (id) ON DELETE CASCADE,
  stage               appeal_stage NOT NULL DEFAULT 'not_filed',
  -- The window is short, statutory, and the single most reliable thing an owner
  -- misses. Kentucky: KRS 133.045 opens the inspection period on the first
  -- Monday in May for thirteen days, and a conference with the PVA (Form
  -- 62A307) must precede any filing with the County Clerk.
  window_opens_on     DATE,
  window_closes_on    DATE,
  conference_held_on  DATE,
  filed_on            DATE,
  opinion_of_value    money_amount,
  evidence_summary    TEXT,
  decided_on          DATE,
  resulting_value     money_amount,
  tax_saved_first_year money_amount,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT window_ordered
    CHECK (window_closes_on IS NULL OR window_opens_on IS NULL
           OR window_closes_on >= window_opens_on)
);

COMMENT ON TABLE assessment_appeals IS
  'A successful appeal compounds across the entire remaining hold, which makes '
  'it the highest-return hour an owner can spend -- and it is gated by a date '
  'most of them never see. Deferred maintenance is admissible evidence, so the '
  'component inventory feeds this directly.';

-- ---------------------------------------------------------------------------
-- Section 1031 exchanges
-- ---------------------------------------------------------------------------

CREATE TABLE exchanges (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  relinquished_property_id UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  qualified_intermediary   TEXT,
  closed_relinquished_on   DATE NOT NULL,
  -- Both clocks start on the same day and neither is extendable.
  identify_by              DATE NOT NULL,
  acquire_by               DATE NOT NULL,
  -- Why the window is shorter than 180 days, when it is: normally the
  -- unextended return due date for the year of the transfer.
  acquire_by_reason        TEXT,
  identified_on            DATE,
  boot_received            money_amount NOT NULL DEFAULT 0,
  deferred_gain            money_amount,
  is_reverse               BOOLEAN NOT NULL DEFAULT FALSE,
  failed                   BOOLEAN NOT NULL DEFAULT FALSE,
  notes                    TEXT,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT identification_window_is_45_days
    CHECK (identify_by = closed_relinquished_on + 45),
  -- IRC 1031(a)(3)(B) sets the replacement deadline at the EARLIER of 180 days
  -- or the due date of the return for the year of the transfer -- so for a
  -- late-year closing the true deadline falls short of 180 days, and an
  -- equality check admitted only the wrong date. Bounded rather than fixed,
  -- with the shortening reason recorded.
  CONSTRAINT acquisition_window_within_180_days
    CHECK (acquire_by > closed_relinquished_on
           AND acquire_by <= closed_relinquished_on + 180),
  CONSTRAINT shortened_window_says_why
    CHECK (acquire_by = closed_relinquished_on + 180 OR acquire_by_reason IS NOT NULL)
);

COMMENT ON CONSTRAINT identification_window_is_45_days ON exchanges IS
  'The statutory clocks are arithmetic, not preferences. Encoding them as check '
  'constraints means a mistyped deadline cannot be saved at all.';

CREATE TABLE exchange_replacements (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exchange_id   UUID NOT NULL REFERENCES exchanges (id) ON DELETE CASCADE,
  property_id   UUID REFERENCES properties (id),
  address       TEXT NOT NULL,
  identified_on DATE NOT NULL,
  acquired_on   DATE,
  price         money_amount
);
