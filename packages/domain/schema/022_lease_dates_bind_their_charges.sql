-- ===========================================================================
--  022 — Lease dates bind their charges (issue #140).
--
--  The rent sweep freezes each month's charge at first billing: the amount
--  is computed from starts_on/ends_on as they stood, and the idempotency
--  key (lease, kind, period_start) discards recomputation by design. That
--  is correct for a world where lease dates never move — which is the only
--  world the API offers today (nothing updates starts_on or ends_on).
--
--  This module makes that fact a CONSTRAINT instead of a coincidence, so
--  the first future lease-amendment endpoint meets a named trigger at
--  development time rather than a wrong bill at billing time:
--
--    * starts_on is immutable once any rent charge exists — moving it
--      earlier MOVES the stub month's idempotency key, and a re-sweep
--      would insert a second charge beside the first (a double bill, each
--      drawing its own late fee).
--    * ends_on may only move while every billed month lies strictly before
--      both the old and the new boundary. Cutting it into a billed month
--      leaves a full-month charge on a part-month occupancy (frozen
--      overbill); extending it past a prorated final charge leaves a
--      part-month charge on a full-month occupancy (frozen underbill).
--
--  Whoever builds amendments either supersedes the affected charges in the
--  same transaction and RELAXES this trigger with that reconciliation, or
--  keeps the refusal. Either way it is a decision, never an accident.
-- ===========================================================================

CREATE OR REPLACE FUNCTION lease_dates_bind_their_charges()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  last_billed DATE;
BEGIN
  IF NEW.starts_on IS DISTINCT FROM OLD.starts_on THEN
    IF EXISTS (SELECT 1 FROM rent_charges c
               WHERE c.lease_id = OLD.id AND c.kind = 'rent') THEN
      RAISE EXCEPTION USING
        ERRCODE = 'check_violation',
        CONSTRAINT = 'lease_dates_bind_their_charges',
        MESSAGE = 'starts_on cannot move once rent has been billed: the '
          'first month''s charge is keyed and priced by it. Amending the '
          'start requires superseding the affected charges in the same '
          'transaction (issue #140).';
    END IF;
  END IF;
  IF NEW.ends_on IS DISTINCT FROM OLD.ends_on THEN
    -- period_end is nullable on old rows: fall back to the month's own
    -- end, because a period_start-only August charge still bills August.
    SELECT max(coalesce(c.period_end,
                        (date_trunc('month', c.period_start)
                         + INTERVAL '1 month' - INTERVAL '1 day')::date))
      INTO last_billed
    FROM rent_charges c
    WHERE c.lease_id = OLD.id AND c.kind = 'rent';
    IF last_billed IS NOT NULL
       AND ((OLD.ends_on IS NOT NULL AND OLD.ends_on <= last_billed)
            OR (NEW.ends_on IS NOT NULL AND NEW.ends_on <= last_billed)) THEN
      RAISE EXCEPTION USING
        ERRCODE = 'check_violation',
        CONSTRAINT = 'lease_dates_bind_their_charges',
        MESSAGE = 'ends_on cannot cross a billed month: the charge for that '
          'month is frozen at the old occupancy and would overbill or '
          'underbill. Supersede the affected charges in the same '
          'transaction (issue #140).';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER lease_dates_bind_their_charges
  BEFORE UPDATE OF starts_on, ends_on ON leases
  FOR EACH ROW EXECUTE FUNCTION lease_dates_bind_their_charges();
