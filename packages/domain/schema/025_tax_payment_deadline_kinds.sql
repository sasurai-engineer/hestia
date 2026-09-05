-- ===========================================================================
--  025 — Deadline kinds for the collection calendar (issue #149).
--
--  Seeds 910/911 made payment law data; these are the kinds the sweep emits
--  it as. 'license_renewal' already exists (module 007); payment and the
--  discount close get their own, because "the day the bill is due" and "the
--  day the free money ends" are different acts with different urgency.
-- ===========================================================================

ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'tax_payment_due';
ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'tax_discount_close';
