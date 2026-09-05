-- ===========================================================================
--  024 — The collection calendar becomes a rule domain (issue #145).
--
--  The packs carry when a value may be APPEALED but nothing about when the
--  bill is PAID: no discount window, no penalty phase, no delinquency
--  boundary. The November free-money moment (Kentucky's 2% discount) had no
--  law under it. Collection mechanics are jurisdiction facts — cited,
--  effective-dated, chain-resolved — so they get a domain, not a column.
-- ===========================================================================

ALTER TYPE rule_domain ADD VALUE IF NOT EXISTS 'tax_collection';
