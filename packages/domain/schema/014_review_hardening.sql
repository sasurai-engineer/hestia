-- ===========================================================================
--  014 — Review hardening.
--
--  The adversarial review of the ledger/rent/payments increments found the
--  places where application-level checks pretended to be guarantees. The
--  fixes that belong to the DATABASE land here: races become constraints,
--  and caps the code merely intended become caps the schema enforces.
-- ===========================================================================

-- One reversal per event, enforced where it cannot race: two concurrent
-- reverse calls both passing the application's existence check now lose to
-- this index instead of corrupting the append-only ledger with a double
-- negation.
CREATE UNIQUE INDEX one_reversal_per_event
  ON ledger_events (reverses_event_id)
  WHERE reverses_event_id IS NOT NULL;

-- Allocations may never exceed the charge they pay. Cross-row arithmetic
-- needs a trigger, not a CHECK; SERIALIZABLE-free concurrent receipts that
-- both saw headroom now lose here.
CREATE OR REPLACE FUNCTION refuse_over_allocation() RETURNS TRIGGER AS $$
DECLARE
  charge_amount NUMERIC;
  allocated NUMERIC;
BEGIN
  SELECT amount INTO charge_amount FROM rent_charges WHERE id = NEW.charge_id FOR UPDATE;
  SELECT coalesce(sum(amount), 0) INTO allocated
  FROM rent_receipt_allocations WHERE charge_id = NEW.charge_id;
  IF allocated + NEW.amount > charge_amount THEN
    RAISE EXCEPTION 'allocation would exceed the charge: % + % > %',
      allocated, NEW.amount, charge_amount
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER rent_receipt_allocations_capped
  BEFORE INSERT ON rent_receipt_allocations
  FOR EACH ROW EXECUTE FUNCTION refuse_over_allocation();

-- Credit-card exports disagree about sign (many issuers print charges
-- positive). The owner declares the account's convention once; the import
-- pipeline applies it. Never guessed from the account kind.
ALTER TABLE bank_accounts
  ADD COLUMN invert_amounts BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN bank_accounts.invert_amounts IS
  'TRUE when this account''s exports sign money backwards (typical for '
  'credit cards that print charges as positive). Applied at staging, '
  'declared by the owner — a convention, never an inference.';

-- A sign-off certifies NUMBERS, not a (property, year) pair. The certified
-- totals are recorded so a back-dated correction after certification is
-- visibly STALE instead of silently borrowing the CPA's name.
ALTER TABLE report_signoffs
  ADD COLUMN certified_income money_amount,
  ADD COLUMN certified_expenses money_amount,
  ADD COLUMN certified_depreciation money_amount,
  ADD COLUMN certified_net money_amount;
