-- ===========================================================================
--  023 — A receipt pays out at most once (issue #139).
--
--  Module 014 capped allocations per CHARGE: no charge can collect more
--  than its amount. Nothing capped the other side — allocations per LEDGER
--  EVENT — so two concurrent sweeps that both read a receipt's remaining
--  credit before either committed could spend the same money against two
--  different charges: per-charge cap satisfied, primary key satisfied, one
--  hundred dollars paying two hundred of rent, open_credit negative, and a
--  collection silently missed. apply_open_credit's docstring even claimed
--  the database backed this arithmetic; until this module, it did not.
--
--  Same shape as 014's trigger, pointed the other way: the event row is
--  locked, the event's existing allocations are summed, and an allocation
--  that would spend past the receipt's amount is refused loudly. Under a
--  concurrent race the loser now gets a rollback instead of the tenant's
--  money being double-counted — loud beats silently wrong, and the caller
--  simply retries against the settled books.
-- ===========================================================================

CREATE OR REPLACE FUNCTION refuse_over_crediting() RETURNS TRIGGER AS $$
DECLARE
  event_amount NUMERIC;
  spent NUMERIC;
BEGIN
  SELECT amount INTO event_amount FROM ledger_events
  WHERE id = NEW.ledger_event_id FOR UPDATE;
  SELECT coalesce(sum(amount), 0) INTO spent
  FROM rent_receipt_allocations WHERE ledger_event_id = NEW.ledger_event_id;
  IF spent + NEW.amount > event_amount THEN
    RAISE EXCEPTION 'allocation would spend the receipt twice: % + % > %',
      spent, NEW.amount, event_amount
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER rent_receipt_allocations_spend_once
  BEFORE INSERT ON rent_receipt_allocations
  FOR EACH ROW EXECUTE FUNCTION refuse_over_crediting();
