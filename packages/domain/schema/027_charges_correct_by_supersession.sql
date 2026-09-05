-- ===========================================================================
--  027 — A wrong charge gets a correction path: supersession, never
--  mutation (issue #105).
--
--  The premise-checker's catch during vision grooming: one_charge_per_period
--  forbids a second ('rent', period) row, the sweep never revises, nothing
--  updates rent_charges.amount, and waive-and-reissue is blocked by the same
--  key — so ANY wrong rent charge (a typo, a mid-period lease amendment, a
--  late-arriving CPI figure when #44 returns) was irrecoverable in an
--  append-only system with no correction path.
--
--  The path is the house's own supersession law (module 006's append-never-
--  mutate; jurisdiction_rules' superseded_by), applied to charges:
--
--    * The old charge is never edited and never deleted. It is marked
--      superseded, pointing at its successor, and drops out of every
--      balance the way waived rows do — history, fully readable.
--    * The successor is a NEW row: same lease, kind, and period, the
--      corrected amount, carrying WHO it corrects and WHY. A correction
--      without a reason does not exist.
--    * one_charge_per_period becomes a partial unique index over LIVE rows
--      (same name, so every test that names it keeps matching): one live
--      charge per period forever, any number of superseded predecessors.
--    * The successor pointer is DEFERRABLE: the writer marks the old row
--      first (so it leaves the live index) and inserts the new row second,
--      inside one transaction; the FK proves the chain at commit.
--    * One successor per charge — a second correction corrects the LIVE
--      row, extending the chain, never forking it.
--
--  Money follows the correction: the writer releases the old charge's
--  allocations back to open credit and re-applies oldest-first, so a paid
--  charge corrected downward leaves the excess VISIBLE as credit, and one
--  corrected upward shows the true remaining balance. Nothing in the
--  ledger moves — receipts are history; only their allocation changes.
-- ===========================================================================

ALTER TABLE rent_charges
  ADD COLUMN superseded_by UUID REFERENCES rent_charges (id)
    DEFERRABLE INITIALLY DEFERRED,
  ADD COLUMN corrects_charge_id UUID REFERENCES rent_charges (id),
  ADD COLUMN correction_reason TEXT;

ALTER TABLE rent_charges DROP CONSTRAINT one_charge_per_period;
CREATE UNIQUE INDEX one_charge_per_period
  ON rent_charges (lease_id, kind, period_start)
  WHERE superseded_by IS NULL;

-- A chain, never a fork: each charge has at most one successor. (UNIQUE
-- ignores NULLs, so uncorrected charges are unconstrained.)
ALTER TABLE rent_charges
  ADD CONSTRAINT one_successor_per_charge UNIQUE (superseded_by);

-- A correction without a reason does not exist, and a reason without a
-- correction is noise.
ALTER TABLE rent_charges
  ADD CONSTRAINT correction_says_why
  CHECK ((corrects_charge_id IS NULL) = (correction_reason IS NULL));

-- The status and the pointer move together, both directions: no silently
-- dead live-looking rows, no superseded rows still wearing 'due'.
ALTER TABLE rent_charges
  ADD CONSTRAINT superseded_is_coupled
  CHECK ((status = 'superseded') = (superseded_by IS NOT NULL));

COMMENT ON COLUMN rent_charges.superseded_by IS
  'The successor charge that corrected this one. Set once, never cleared; '
  'a superseded charge is history and drops out of every balance.';
COMMENT ON COLUMN rent_charges.corrects_charge_id IS
  'The charge this row corrects. Travels with correction_reason — '
  'correction_says_why makes a why-less correction unrepresentable.';
