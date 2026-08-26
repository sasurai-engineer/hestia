-- ===========================================================================
--  Hestia — integrity
--
--  The promises the other five modules make in prose, enforced.
--
--  Two of them were, until now, comments: nine tables declared an `updated_at`
--  column with no trigger anywhere, so it recorded creation time forever; and
--  three tables were documented as append-only with nothing stopping an UPDATE.
--  A guarantee the database does not enforce is a guarantee the first ORM bug
--  quietly breaks.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- updated_at
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_updated_at() IS
  'Maintains updated_at on write. Without it the column equals created_at for '
  'the life of the row, and every consumer that would use it -- cache '
  'invalidation, incremental sync, "what changed since the last filing" -- '
  'silently reads the wrong value.';

DO $$
DECLARE
  target TEXT;
BEGIN
  FOREACH target IN ARRAY ARRAY[
    'entities', 'properties', 'units', 'components', 'residents',
    'leases', 'debt_instruments', 'depreciable_assets', 'assessment_appeals'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER %I_set_updated_at
         BEFORE UPDATE ON %I
         FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
      target, target
    );
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- Append-only
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION refuse_mutation() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION
    '% is append-only; record a correction as a new row rather than altering %',
    TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION refuse_mutation() IS
  'The bitemporal audit story depends on history being immutable. A mutated '
  'ledger row is indistinguishable from an original, so "what did we believe '
  'on the day we filed" becomes unanswerable -- which is the question that '
  'arrives with an audit letter.';

CREATE TRIGGER ledger_events_append_only
  BEFORE UPDATE OR DELETE ON ledger_events
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();

CREATE TRIGGER depreciation_entries_append_only
  BEFORE UPDATE OR DELETE ON depreciation_entries
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();

CREATE TRIGGER audit_log_append_only
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();

-- TRUNCATE is not an UPDATE or a DELETE and fires no row-level trigger, so the
-- immutable financial record could be erased in one statement with no error at
-- all -- by a test-fixture reset, an ORM `db:reset`, or `pg_restore --clean`.
-- A statement-level trigger is the only thing that sees it.
CREATE OR REPLACE FUNCTION refuse_truncate() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION '% is append-only and cannot be truncated', TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_events_no_truncate
  BEFORE TRUNCATE ON ledger_events
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_truncate();

CREATE TRIGGER depreciation_entries_no_truncate
  BEFORE TRUNCATE ON depreciation_entries
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_truncate();

CREATE TRIGGER audit_log_no_truncate
  BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_truncate();

-- ---------------------------------------------------------------------------
-- Effective-dated rules: supersede, never rewrite
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION refuse_rule_rewrite() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'jurisdiction_rules is versioned; close the rule with effective_to instead of deleting it'
      USING ERRCODE = 'restrict_violation';
  END IF;
  -- Closing a rule out or pointing it at its successor is the supported edit.
  -- Rewriting what the rule *said* is not: a depreciation schedule computed
  -- under it could no longer be reproduced.
  IF NEW.jurisdiction_id IS DISTINCT FROM OLD.jurisdiction_id
     OR NEW.domain        IS DISTINCT FROM OLD.domain
     OR NEW.code          IS DISTINCT FROM OLD.code
     OR NEW.value_numeric IS DISTINCT FROM OLD.value_numeric
     OR NEW.value_money   IS DISTINCT FROM OLD.value_money
     OR NEW.value_text    IS DISTINCT FROM OLD.value_text
     OR NEW.citation      IS DISTINCT FROM OLD.citation
     OR NEW.effective_from IS DISTINCT FROM OLD.effective_from THEN
    RAISE EXCEPTION
      'jurisdiction_rules is versioned; supersede this rule with a new row rather than rewriting it'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jurisdiction_rules_versioned
  BEFORE UPDATE OR DELETE ON jurisdiction_rules
  FOR EACH ROW EXECUTE FUNCTION refuse_rule_rewrite();

-- ---------------------------------------------------------------------------
-- One unit, one live lease
-- ---------------------------------------------------------------------------

-- Nothing prevented two simultaneously-active leases overlapping on the same
-- unit, so a rent roll counted the unit twice and the error propagated
-- straight into NOI, DSCR and the cap rate. A partial index made the query
-- fast; only an exclusion constraint makes the state impossible.
--
-- NULL `ends_on` means month-to-month, which runs until terminated, so it is
-- treated as an open upper bound.
ALTER TABLE leases
  ADD CONSTRAINT one_live_lease_per_unit
  EXCLUDE USING gist (
    unit_id WITH =,
    daterange(starts_on, ends_on, '[)') WITH &&
  )
  WHERE (status IN ('active', 'month_to_month'));
