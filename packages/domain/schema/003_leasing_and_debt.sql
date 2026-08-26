-- ===========================================================================
--  Hestia — leasing and debt
--
--  Renters are `residents`. `tenant` is reserved for the platform's workspace
--  concept and never appears here.
-- ===========================================================================

CREATE TABLE residents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name     TEXT NOT NULL,
  email         email_address,
  phone         TEXT,
  -- Screening outcomes are retained only as a decision and a date. The FCRA
  -- obliges an adverse-action notice when a report drives a denial; it does not
  -- oblige us to warehouse the report, and holding consumer-report contents
  -- creates duties without benefit.
  screened_on             DATE,
  adverse_action_sent_on  DATE,
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE residents IS
  'Deliberately thin. Fair-housing exposure grows with every attribute stored '
  'about a person, and almost none of them improve a decision this system makes.';

CREATE TYPE lease_status AS ENUM (
  'draft', 'active', 'month_to_month', 'expired', 'terminated', 'evicted'
);

CREATE TYPE escalation_kind AS ENUM ('none', 'fixed_amount', 'fixed_percent', 'cpi');

CREATE TABLE leases (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  unit_id             UUID NOT NULL REFERENCES units (id) ON DELETE CASCADE,
  status              lease_status NOT NULL DEFAULT 'draft',

  starts_on           DATE NOT NULL,
  ends_on             DATE,                     -- NULL while month-to-month
  rent                money_nonneg NOT NULL,
  rent_due_day        SMALLINT NOT NULL DEFAULT 1,

  escalation          escalation_kind NOT NULL DEFAULT 'none',
  escalation_value    NUMERIC(12, 4),

  security_deposit    money_nonneg NOT NULL DEFAULT 0,
  -- Several states require deposits held separately and some require interest.
  -- Which ones is a jurisdiction_rules lookup, not a column.
  deposit_account     TEXT,
  deposit_returned_on DATE,
  deposit_returned    money_amount,

  -- Concessions distort effective rent and must not be lost in the headline.
  concession_months   NUMERIC(4, 2) NOT NULL DEFAULT 0,

  moved_out_on        DATE,
  terminated_reason   TEXT,
  document_id         UUID,                     -- the executed lease, once ingested
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT lease_dates_ordered CHECK (ends_on IS NULL OR ends_on > starts_on),
  CONSTRAINT due_day_is_a_day CHECK (rent_due_day BETWEEN 1 AND 31),
  CONSTRAINT escalation_has_a_value
    CHECK (escalation = 'none' OR escalation_value IS NOT NULL)
);

CREATE INDEX leases_active_by_unit ON leases (unit_id)
  WHERE status IN ('active', 'month_to_month');
CREATE INDEX leases_by_expiry ON leases (ends_on)
  WHERE status IN ('active', 'month_to_month');

COMMENT ON COLUMN leases.concession_months IS
  'Free months given at signing. Headline rent net of concession is effective '
  'rent, and the difference is what actually renews -- an owner comparing a '
  'concessioned lease to market on headline rent is comparing the wrong number.';

CREATE TABLE lease_residents (
  lease_id      UUID NOT NULL REFERENCES leases (id) ON DELETE CASCADE,
  resident_id   UUID NOT NULL REFERENCES residents (id) ON DELETE CASCADE,
  is_guarantor  BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (lease_id, resident_id)
);

-- Renewal history is the training data for the rent engine's turnover model.
CREATE TABLE lease_renewals (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prior_lease_id     UUID NOT NULL REFERENCES leases (id) ON DELETE CASCADE,
  new_lease_id       UUID REFERENCES leases (id) ON DELETE SET NULL,
  offered_on         DATE NOT NULL,
  offered_rent       money_amount NOT NULL,
  prior_rent         money_amount NOT NULL,
  accepted           BOOLEAN,
  -- What the turn actually cost when the offer was refused: the other half of
  -- the expected-value calculation, and the half nobody records.
  vacancy_days       INTEGER,
  turn_cost          money_amount,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT outcome_or_pending CHECK (accepted IS NOT NULL OR new_lease_id IS NULL)
);

COMMENT ON TABLE lease_renewals IS
  'Every renewal offer, its outcome, and the cost of the ones refused. This is '
  'what calibrates P(leave | increase) from the portfolio itself rather than '
  'from a market average that describes somebody else''s building.';

-- ---------------------------------------------------------------------------
-- Debt
-- ---------------------------------------------------------------------------

CREATE TYPE debt_kind AS ENUM (
  'conventional_mortgage', 'portfolio_loan', 'dscr_loan', 'agency_multifamily',
  'bridge', 'hard_money', 'heloc', 'seller_financing', 'private_note'
);

CREATE TYPE amortization_kind AS ENUM (
  'fully_amortizing', 'interest_only', 'balloon', 'arm', 'negative_amortizing'
);

CREATE TYPE prepayment_kind AS ENUM (
  'none', 'step_down', 'flat_percent', 'yield_maintenance', 'defeasance', 'lockout'
);

CREATE TABLE debt_instruments (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id           UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  entity_id             UUID REFERENCES entities (id),
  lender                TEXT,
  kind                  debt_kind NOT NULL,
  lien_position         SMALLINT NOT NULL DEFAULT 1,

  original_principal    money_nonneg NOT NULL,
  interest_rate         annual_rate NOT NULL,
  amortization          amortization_kind NOT NULL DEFAULT 'fully_amortizing',
  term_months           INTEGER NOT NULL,
  amortization_months   INTEGER,          -- differs from term when a balloon exists
  originated_on         DATE NOT NULL,
  first_payment_on      DATE,
  matures_on            DATE,

  -- Adjustable terms
  rate_adjusts_on       DATE,
  rate_index            TEXT,             -- 'SOFR-30A', 'CMT-1Y'
  rate_margin           annual_rate,
  rate_cap_periodic     annual_rate,
  rate_cap_lifetime     annual_rate,

  -- Exit friction, which decides whether a refinance or sale actually pencils.
  prepayment            prepayment_kind NOT NULL DEFAULT 'none',
  prepayment_terms      TEXT,
  is_recourse           BOOLEAN NOT NULL DEFAULT TRUE,
  has_due_on_sale       BOOLEAN NOT NULL DEFAULT TRUE,

  escrows_taxes         BOOLEAN NOT NULL DEFAULT FALSE,
  escrows_insurance     BOOLEAN NOT NULL DEFAULT FALSE,

  paid_off_on           DATE,
  document_id           UUID,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT principal_is_positive CHECK (original_principal > 0),
  CONSTRAINT positive_term CHECK (term_months > 0),
  CONSTRAINT amortization_at_least_term
    CHECK (amortization_months IS NULL OR amortization_months >= term_months),
  CONSTRAINT arm_has_index
    CHECK (amortization <> 'arm' OR rate_index IS NOT NULL),
  CONSTRAINT lien_position_positive CHECK (lien_position >= 1)
);

CREATE INDEX debt_live_by_property ON debt_instruments (property_id)
  WHERE paid_off_on IS NULL;
CREATE INDEX debt_by_maturity ON debt_instruments (matures_on)
  WHERE paid_off_on IS NULL;

COMMENT ON COLUMN debt_instruments.has_due_on_sale IS
  'Transferring a property into an LLC can trip this clause. Owners restructure '
  'for liability protection without reading it, and the hold/sell engine must '
  'not recommend a transfer that accelerates the note.';

COMMENT ON COLUMN debt_instruments.prepayment IS
  'Yield maintenance and defeasance can cost more than the interest saved by a '
  'refinance. A refinance recommendation that ignores exit friction is worse '
  'than no recommendation.';

-- Scheduled amortization is computed, not stored. Payments actually made are.
CREATE TABLE debt_payments (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  debt_id           UUID NOT NULL REFERENCES debt_instruments (id) ON DELETE CASCADE,
  paid_on           DATE NOT NULL,
  principal         money_amount NOT NULL DEFAULT 0,
  interest          money_amount NOT NULL DEFAULT 0,
  escrow            money_amount NOT NULL DEFAULT 0,
  extra_principal   money_amount NOT NULL DEFAULT 0,
  balance_after     money_amount,
  provenance_id     UUID REFERENCES provenance (id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (debt_id, paid_on)
);
