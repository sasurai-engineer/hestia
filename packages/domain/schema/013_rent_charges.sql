-- ===========================================================================
--  013 — Rent charges, receipt allocation, and payment requests.
--
--  A rent CHARGE is an expectation: schedulable, waivable, partially
--  payable — mutable state, so it lives OUTSIDE the append-only ledger.
--  Money that actually moves is a ledger_events row (cash-basis Schedule E
--  reads receipts, not billings), and rent_receipt_allocations ties the two
--  worlds together without ever mutating a ledger row. Payment requests are
--  the processor seam: a provider reference and a status machine whose only
--  ledger touch is the receipt appended on success.
-- ===========================================================================

CREATE TYPE rent_charge_kind AS ENUM ('rent', 'late_fee', 'utility_passthrough', 'other');
CREATE TYPE charge_status AS ENUM
  ('scheduled', 'due', 'partially_paid', 'paid', 'waived', 'written_off');

CREATE TABLE rent_charges (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lease_id       UUID NOT NULL REFERENCES leases (id) ON DELETE CASCADE,
  kind           rent_charge_kind NOT NULL,
  period_start   DATE NOT NULL,
  period_end     DATE,
  due_on         DATE NOT NULL,
  amount         money_nonneg NOT NULL,
  status         charge_status NOT NULL DEFAULT 'due',
  waived_reason  TEXT,
  generated_by   TEXT NOT NULL DEFAULT 'manual',   -- 'sweep' | 'manual'
  -- A generated late fee carries the rule that authorized it; the sweep
  -- refuses to invent one where no jurisdiction rule exists.
  rule_citation  TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT charges_charge_something CHECK (amount > 0),
  CONSTRAINT waived_says_why CHECK (status <> 'waived' OR waived_reason IS NOT NULL),
  CONSTRAINT period_ordered
    CHECK (period_end IS NULL OR period_end >= period_start),
  -- The rent sweep's idempotency: one charge per lease, kind, and period.
  CONSTRAINT one_charge_per_period UNIQUE (lease_id, kind, period_start)
);

CREATE TRIGGER rent_charges_set_updated_at
  BEFORE UPDATE ON rent_charges
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE rent_receipt_allocations (
  charge_id        UUID NOT NULL REFERENCES rent_charges (id) ON DELETE CASCADE,
  ledger_event_id  BIGINT NOT NULL REFERENCES ledger_events (id) ON DELETE RESTRICT,
  amount           money_nonneg NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (charge_id, ledger_event_id),
  CONSTRAINT allocations_allocate_something CHECK (amount > 0)
);

CREATE TYPE payment_status AS ENUM
  ('created', 'processing', 'succeeded', 'failed', 'canceled');

CREATE TABLE payment_requests (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lease_id         UUID NOT NULL REFERENCES leases (id) ON DELETE CASCADE,
  amount           money_nonneg NOT NULL,
  provider         TEXT NOT NULL,                 -- 'stripe'
  provider_ref     TEXT UNIQUE,                   -- the PaymentIntent id
  status           payment_status NOT NULL DEFAULT 'created',
  failure_detail   TEXT,
  -- Set exactly once, when the succeeded payment's receipt is appended.
  ledger_event_id  BIGINT UNIQUE REFERENCES ledger_events (id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT payments_collect_something CHECK (amount > 0),
  CONSTRAINT success_posts_its_receipt
    CHECK ((status = 'succeeded') = (ledger_event_id IS NOT NULL))
);

CREATE TRIGGER payment_requests_set_updated_at
  BEFORE UPDATE ON payment_requests
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
