-- ===========================================================================
--  021 — escalation_value gets a unit, because the repo already proved it
--  needed one (issue #104).
--
--  leases.escalation_value is polymorphic by convention: dollars when
--  escalation = 'fixed_amount', a decimal fraction when 'fixed_percent'.
--  That convention was written down nowhere the database could enforce it,
--  and the repository's own two layers already disagreed about it:
--  tests/constraints.sql certified ('fixed_percent', 3.5) as "a well-formed
--  twelve-month lease" while services/api/tests/test_rent.py wrote 0.03 for
--  three percent. Through _escalated_rent's base * (1 + value) ** years,
--  the certified fixture is a 350 PERCENT annual increase.
--
--  Module 001 documents this exact hazard as the reason the annual_rate
--  domain is bounded: a rate typed in percent form once produced a payment
--  a hundredfold too large, with no error to hint at it. leases was the
--  table that did not use the fix. Now it does, by kind:
--
--    fixed_percent  — bounded like annual_rate: a decimal fraction,
--                     abs(value) < 1. No residential escalation clause
--                     reaches 100 percent a year; 3.5 can only be a typo
--                     for 0.035, and it now fails loudly at insert.
--    fixed_amount   — non-negative dollars. (A step-down lease, should one
--                     ever arrive, is an amendment to this constraint with
--                     its own justification — not a silent allowance today.)
--    cpi            — the value's meaning is owned by the parked CPI work
--                     (#44) and is not constrained here.
--    none           — no value is required (escalation_has_a_value already
--                     governs presence; this module governs units).
--
--  If this migration fails on an existing row, that row IS the bug being
--  hunted: a lease whose next sweep would bill an escalation two orders of
--  magnitude too large. Loud is the point; nothing here rewrites money.
-- ===========================================================================

ALTER TABLE leases
  ADD CONSTRAINT escalation_value_matches_its_kind CHECK (
    CASE escalation
      WHEN 'fixed_percent' THEN escalation_value > -1 AND escalation_value < 1
      WHEN 'fixed_amount'  THEN escalation_value >= 0
      ELSE TRUE
    END
  );

COMMENT ON COLUMN leases.escalation_value IS
  'Unit depends on escalation kind: a DECIMAL FRACTION for fixed_percent '
  '(0.035 means 3.5% — percent-form entry like 3.5 is rejected by '
  'escalation_value_matches_its_kind, the same hazard annual_rate exists '
  'for), non-negative DOLLARS for fixed_amount, and reserved for the CPI '
  'engine when escalation = cpi.';
