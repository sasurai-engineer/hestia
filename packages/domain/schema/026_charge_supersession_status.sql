-- ===========================================================================
--  026 — The 'superseded' charge status (issue #105, part 1 of 2).
--
--  Its own module because PostgreSQL refuses to USE an enum value in the
--  transaction that added it, and module 027's coupling CHECK does exactly
--  that. The value lands here; the machinery lands next door.
-- ===========================================================================

ALTER TYPE charge_status ADD VALUE IF NOT EXISTS 'superseded';
