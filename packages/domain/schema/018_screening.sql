-- ===========================================================================
--  018 — Screening decisions, and the notice a denial owes.
--
--  `residents` has carried screened_on and adverse_action_sent_on since 003,
--  with a comment explaining why no report contents are stored: the FCRA
--  obliges a NOTICE when a consumer report drives a denial, it does not
--  oblige anyone to warehouse the report, and holding one creates duties
--  without benefit. This module builds the workflow around those dates and
--  keeps that promise — there is nowhere here to put a score, a criminal
--  record, or a reason code from a bureau.
--
--  The duty itself: FCRA s.615(a) (15 U.S.C. 1681m(a)). If adverse action is
--  taken with respect to any consumer, BASED IN WHOLE OR IN PART on a
--  consumer report, the user of that report must notify the consumer. Both
--  halves matter, so both are recorded separately and the obligation is
--  derived from them rather than asserted alongside them.
-- ===========================================================================

CREATE TYPE screening_decision AS ENUM (
  'pending',
  'approved',
  -- Approval on worse terms — a larger deposit, a co-signer — is still
  -- adverse action under 15 U.S.C. 1681a(k)(1)(B)(ii) when a report drove it.
  'conditional',
  'denied',
  'withdrawn'   -- the applicant walked; no adverse action was taken
);

CREATE TABLE screening_requests (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  resident_id              UUID NOT NULL REFERENCES residents (id) ON DELETE CASCADE,
  -- The application is to a property; the deadline this produces needs an
  -- owner-side anchor (deadline_is_anchored, module 007).
  property_id              UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  unit_id                  UUID,

  requested_on             DATE NOT NULL DEFAULT CURRENT_DATE,
  -- 'manual' until a bureau adapter exists. Named, never inferred.
  provider                 TEXT NOT NULL DEFAULT 'manual',

  decision                 screening_decision NOT NULL DEFAULT 'pending',
  decided_on               DATE,
  -- The owner's own words for why. NOT a reason code, NOT report contents:
  -- what a person could defend in a fair-housing complaint.
  decision_basis           TEXT,

  -- The second half of the s.615(a) test, recorded as its own fact because it
  -- is a different question from what the decision was.
  based_on_consumer_report BOOLEAN NOT NULL DEFAULT FALSE,

  -- GENERATED, so the obligation can never drift from the facts that create
  -- it. A stored boolean somebody sets by hand is a claim; this is a
  -- consequence.
  adverse_action_required  BOOLEAN GENERATED ALWAYS AS (
    based_on_consumer_report AND decision IN ('denied', 'conditional')
  ) STORED,
  adverse_action_sent_on   DATE,

  notes                    TEXT,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

  FOREIGN KEY (unit_id, property_id)
    REFERENCES units (id, property_id) ON DELETE SET NULL (unit_id),

  CONSTRAINT decided_requests_say_when
    CHECK (decision = 'pending' OR decided_on IS NOT NULL),
  CONSTRAINT pending_requests_are_undecided
    CHECK (decision <> 'pending' OR decided_on IS NULL),
  CONSTRAINT decided_after_requested
    CHECK (decided_on IS NULL OR decided_on >= requested_on),
  -- A notice cannot precede the decision it is about, and cannot be sent for
  -- a decision that owes none. Written against the base columns rather than
  -- the generated one so the rule reads as the statute does.
  CONSTRAINT notice_follows_its_decision
    CHECK (adverse_action_sent_on IS NULL OR adverse_action_sent_on >= decided_on),
  CONSTRAINT notice_only_when_a_report_drove_an_adverse_decision
    CHECK (
      adverse_action_sent_on IS NULL
      OR (based_on_consumer_report AND decision IN ('denied', 'conditional'))
    )
);

CREATE INDEX screening_open_by_resident ON screening_requests (resident_id)
  WHERE decision = 'pending';
-- The queue the sweep reads: adverse action owed and not yet sent.
CREATE INDEX screening_notice_owed ON screening_requests (property_id)
  WHERE adverse_action_required AND adverse_action_sent_on IS NULL;

CREATE TRIGGER screening_requests_set_updated_at
  BEFORE UPDATE ON screening_requests
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE screening_requests IS
  'A decision and its dates. There is deliberately nowhere here to put a '
  'score, a record, or a bureau reason code: the FCRA obliges a notice, not '
  'a warehouse, and every stored attribute about an applicant is '
  'fair-housing exposure that improves no decision this system makes.';

COMMENT ON COLUMN screening_requests.adverse_action_required IS
  'Derived, never asserted: s.615(a) attaches when adverse action is taken '
  'AND a consumer report drove it in whole or in part. Conditional approval '
  'counts as adverse action (15 U.S.C. 1681a(k)(1)(B)(ii)) — a bigger '
  'deposit because of a report is exactly the case the statute is about.';

-- ---------------------------------------------------------------------------
-- The notice becomes a deadline
-- ---------------------------------------------------------------------------

ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'adverse_action_notice';

-- Without its own anchor, two applicants denied on the same day at the same
-- property would collapse into one deadline and the second notice would go
-- unsent. The vendor anchor in 016 exists for the same reason.
ALTER TABLE deadlines
  ADD COLUMN screening_request_id UUID REFERENCES screening_requests (id) ON DELETE CASCADE;

DROP INDEX deadlines_sweep_identity;
CREATE UNIQUE INDEX deadlines_sweep_identity
  ON deadlines (kind, due_on, property_id, entity_id, lease_id,
                policy_id, debt_id, exchange_id, appeal_id, vendor_id,
                screening_request_id)
  NULLS NOT DISTINCT;
