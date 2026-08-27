-- ===========================================================================
--  016 — Maintenance: vendors, work orders, and the replacement that makes
--        the capital forecast honest.
--
--  This is the last parity capability with no schema at all, and it is not
--  a ticket tracker with a real-estate coat of paint. A completed work order
--  is the moment the inventory learns something: a replaced water heater
--  turns an INFERRED install band into a KNOWN install date, and the Weibull
--  forecast stops guessing about that component for the next fifteen years.
--
--  Everything the lifecycle can refuse, it refuses here — by named
--  constraint, so the assertion suite can name it back.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Composite identity, so a child row cannot point across properties
-- ---------------------------------------------------------------------------

-- A work order names a property AND (optionally) a unit and a component.
-- Without these, nothing stops a work order on property A citing a unit of
-- property B. A composite foreign key is the cheapest honest guard; MATCH
-- SIMPLE means a NULL unit_id/component_id skips the check entirely, which
-- is exactly right for a property-level order.
ALTER TABLE units ADD CONSTRAINT units_identify_their_property UNIQUE (id, property_id);
ALTER TABLE components
  ADD CONSTRAINT components_identify_their_property UNIQUE (id, property_id);

-- ---------------------------------------------------------------------------
-- Vendors
-- ---------------------------------------------------------------------------

CREATE TYPE vendor_trade AS ENUM (
  'plumbing', 'hvac', 'electrical', 'roofing', 'appliance', 'general_contractor',
  'handyman', 'landscaping', 'pest_control', 'cleaning', 'flooring', 'painting',
  'restoration', 'inspection', 'other'
);

CREATE TABLE vendors (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- The owner's list, not a directory: vendors belong to the entity that
  -- hires them and disappear with it.
  entity_id               UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
  name                    TEXT NOT NULL,
  trade                   vendor_trade NOT NULL,
  phone                   TEXT,
  email                   TEXT,

  -- The two credentials that decide whether hiring this vendor transfers
  -- risk or keeps it. An expired COI means the owner's own policy answers
  -- for the vendor's mistake, which is the entire point of asking for one.
  license_number          TEXT,
  license_expires_on      DATE,
  insurer                 TEXT,
  liability_expires_on    DATE,      -- general liability, from the COI
  workers_comp_expires_on DATE,      -- absent = the injured worker may be the owner's problem

  -- Payments to an unincorporated vendor over the annual threshold are
  -- reportable, and the W-9 has to exist before the January that needs it.
  w9_on_file              BOOLEAN NOT NULL DEFAULT FALSE,
  is_1099_reportable      BOOLEAN NOT NULL DEFAULT TRUE,

  notes                   TEXT,
  retired_on              DATE,      -- no longer called; history stays
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT vendor_named_once_per_entity UNIQUE (entity_id, name),
  CONSTRAINT vendor_name_is_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE TRIGGER vendors_set_updated_at
  BEFORE UPDATE ON vendors
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX vendors_live_by_entity ON vendors (entity_id) WHERE retired_on IS NULL;

COMMENT ON COLUMN vendors.liability_expires_on IS
  'The certificate of insurance expiry. It is a deadline, not a note: the '
  'sweep raises it like any other, because the day it lapses is the day the '
  'owner silently reassumes every risk the vendor was hired to carry.';

-- ---------------------------------------------------------------------------
-- Work orders
-- ---------------------------------------------------------------------------

CREATE TYPE work_order_status AS ENUM (
  'reported', 'triaged', 'scheduled', 'in_progress', 'completed', 'cancelled'
);

CREATE TYPE work_order_priority AS ENUM (
  'emergency',   -- habitability or active damage; the clock is legal, not commercial
  'urgent',
  'routine',
  'planned'      -- deferred maintenance the forecast already expects
);

CREATE TYPE work_order_resolution AS ENUM ('repaired', 'replaced', 'no_action');

CREATE TYPE work_order_reporter AS ENUM ('resident', 'owner', 'inspection', 'vendor');

CREATE TABLE work_orders (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id              UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  unit_id                  UUID,
  -- What is broken, when the owner knows. This is the join that lets a
  -- completion teach the inventory.
  component_id             UUID,
  vendor_id                UUID REFERENCES vendors (id) ON DELETE SET NULL,

  status                   work_order_status NOT NULL DEFAULT 'reported',
  priority                 work_order_priority NOT NULL DEFAULT 'routine',
  reported_by              work_order_reporter NOT NULL DEFAULT 'owner',
  reported_on              DATE NOT NULL DEFAULT CURRENT_DATE,
  summary                  TEXT NOT NULL,
  detail                   TEXT,

  scheduled_for            DATE,
  completed_on             DATE,
  resolution               work_order_resolution,
  resolution_note          TEXT,
  -- Set only by the completion that installs it, and only once.
  replacement_component_id UUID REFERENCES components (id),
  cancelled_reason         TEXT,

  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- The COLUMN LIST on SET NULL is load-bearing: a bare multi-column SET NULL
  -- nulls every referencing column, including the NOT NULL property_id, so
  -- deleting a unit or component would abort with a not_null_violation naming
  -- a table nobody touched. Naming the column keeps the maintenance history
  -- alive at the property when the thing it pointed at is gone.
  FOREIGN KEY (unit_id, property_id)
    REFERENCES units (id, property_id) ON DELETE SET NULL (unit_id),
  FOREIGN KEY (component_id, property_id)
    REFERENCES components (id, property_id) ON DELETE SET NULL (component_id),

  CONSTRAINT work_order_summary_is_not_blank CHECK (length(btrim(summary)) > 0),
  CONSTRAINT scheduled_orders_carry_a_date
    CHECK (status <> 'scheduled' OR scheduled_for IS NOT NULL),
  CONSTRAINT completed_orders_say_when
    CHECK (status <> 'completed' OR completed_on IS NOT NULL),
  CONSTRAINT completed_orders_say_how
    CHECK (status <> 'completed' OR resolution IS NOT NULL),
  CONSTRAINT only_completed_orders_resolve
    CHECK (resolution IS NULL OR status = 'completed'),
  CONSTRAINT cancelled_orders_say_why
    CHECK (status <> 'cancelled' OR length(btrim(coalesce(cancelled_reason, ''))) > 0),
  -- A replacement is a claim about the inventory: it must name what was
  -- replaced, and only a 'replaced' resolution may carry the new component.
  CONSTRAINT replaced_orders_name_the_component
    CHECK (resolution <> 'replaced' OR component_id IS NOT NULL),
  CONSTRAINT replacements_belong_to_replaced_orders
    CHECK (replacement_component_id IS NULL OR resolution = 'replaced'),
  -- ...and both directions: a job that says it replaced something must show
  -- what it installed. PostgreSQL cannot defer a CHECK, so this dictates the
  -- completion's write order — install the component, THEN close the order in
  -- one statement — which is the order that leaves no half-migrated inventory
  -- behind if anything fails.
  CONSTRAINT replaced_orders_install_a_component
    CHECK (resolution <> 'replaced' OR replacement_component_id IS NOT NULL),
  CONSTRAINT completed_after_reported
    CHECK (completed_on IS NULL OR completed_on >= reported_on),
  CONSTRAINT scheduled_after_reported
    CHECK (scheduled_for IS NULL OR scheduled_for >= reported_on)
);

CREATE TRIGGER work_orders_set_updated_at
  BEFORE UPDATE ON work_orders
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX work_orders_open_by_property ON work_orders (property_id, status)
  WHERE status NOT IN ('completed', 'cancelled');
CREATE INDEX work_orders_by_component ON work_orders (component_id)
  WHERE component_id IS NOT NULL;

COMMENT ON TABLE work_orders IS
  'The forecast is only as honest as the inventory, and the inventory only '
  'learns when work completes. A replaced component with a known install '
  'date replaces a ten-year inferred band -- which is why completion is a '
  'transaction here and not a status change.';

COMMENT ON CONSTRAINT completed_orders_say_how ON work_orders IS
  'A completed order with no resolution is the shape of a maintenance log '
  'that cannot answer "what happened to it", which is the only question the '
  'capital plan asks of one.';

-- ---------------------------------------------------------------------------
-- Costs: association, never mutation
-- ---------------------------------------------------------------------------

-- Ledger rows are immutable and a correction is a reversal PAIR, so a
-- work_order_id column on ledger_events could never be set after the fact
-- and could never be corrected. The association is its own append-only fact.
-- Not every dollar attached to a job is a cost of it: a tenant chargeback and
-- a warranty credit both belong to the job's story and both move the net the
-- other way.
CREATE TYPE work_order_cost_relation AS ENUM (
  'invoice', 'materials', 'deposit', 'tenant_chargeback', 'warranty_credit', 'other'
);

CREATE TABLE work_order_ledger_events (
  work_order_id   UUID NOT NULL REFERENCES work_orders (id) ON DELETE CASCADE,
  ledger_event_id BIGINT NOT NULL REFERENCES ledger_events (id) ON DELETE RESTRICT,
  relation        work_order_cost_relation NOT NULL DEFAULT 'invoice',
  linked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by       TEXT,
  PRIMARY KEY (work_order_id, ledger_event_id)
);

CREATE INDEX work_order_costs_by_event ON work_order_ledger_events (ledger_event_id);

COMMENT ON TABLE work_order_ledger_events IS
  'Which money belongs to which job. A reversed event keeps its association: '
  'the cost of a job that was mis-posted and corrected is the NET of the '
  'pair, and hiding the reversal would make the job look cheaper than the '
  'ledger says it was.';

-- ---------------------------------------------------------------------------
-- Vendor credentials become deadlines
-- ---------------------------------------------------------------------------

-- THREE kinds, not one: liability and workers compensation are different
-- credentials that can expire on the same day, and a shared kind would make
-- them collide on the sweep's identity index — one lapse hiding the other.
ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'vendor_insurance_expiration';
ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'vendor_workers_comp_expiration';
ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'vendor_license_expiration';

-- The sweep's idempotency index is keyed on every anchor a generated
-- deadline can carry. Without a vendor anchor, two vendors of one entity
-- whose certificates expire on the same day would collapse into one row --
-- and the second vendor's lapse would be invisible.
ALTER TABLE deadlines ADD COLUMN vendor_id UUID REFERENCES vendors (id) ON DELETE CASCADE;

DROP INDEX deadlines_sweep_identity;
CREATE UNIQUE INDEX deadlines_sweep_identity
  ON deadlines (kind, due_on, property_id, entity_id, lease_id,
                policy_id, debt_id, exchange_id, appeal_id, vendor_id)
  NULLS NOT DISTINCT;

COMMENT ON COLUMN deadlines.vendor_id IS
  'The anchor that keeps two vendors expiring on one day from becoming one '
  'deadline. Every generated deadline needs an anchor distinct enough to be '
  'its own row (module 009).';
