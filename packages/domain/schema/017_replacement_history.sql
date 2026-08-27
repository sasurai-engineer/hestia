-- ===========================================================================
--  017 — A completed replacement never stops naming what it replaced.
--
--  016 gave work_orders.component_id ON DELETE SET NULL, column-listed, so a
--  deleted component leaves the job alive at its property. That is right for
--  every order but the one kind that cannot survive it: a COMPLETED
--  replacement, where `replaced_orders_name_the_component` makes component_id
--  NOT NULL. Deleting such a component ran the SET NULL, the CHECK refused the
--  updated row, and the delete aborted quoting a table nobody had touched:
--
--    ERROR: new row for relation "work_orders" violates check constraint
--           "replaced_orders_name_the_component"
--
--  Both obvious repairs are wrong. Relaxing the CHECK for completed orders
--  relaxes it for every replacement there can ever be -- a replacement is
--  completed by definition (`only_completed_orders_resolve`) -- so the rule
--  would evaporate and a completion could claim it replaced something without
--  ever saying what. Widening the foreign key to ON DELETE RESTRICT protects
--  the replacement but also freezes the ordinary case 016 chose and the
--  assertion suite already proves: an open ticket outliving the component it
--  named.
--
--  So the rule goes where the lie is. Not on the delete -- on the write that
--  would make a finished job untrue. A completed replacement is the authority
--  for its new component's KNOWN install date: the forecast stops guessing
--  about that component because this job says what came out and what went in.
--  Erase either end and a derived fact is left citing nothing. Both pointers
--  are therefore frozen once the order is completed as a replacement, and the
--  refusal names the component and says what to do instead -- components are
--  RETIRED (`retired_on`), never deleted, which is what 002 has said about a
--  replaced component since the inventory existed.
--
--  Deleting the whole property still works, and that is the reason this guard
--  lives on work_orders rather than on components: the job is cascaded away in
--  the same statement, so there is no surviving history to falsify and nothing
--  to refuse. A BEFORE DELETE trigger on components cannot tell the two apart
--  -- it fires while the work order is still there -- and would make every
--  property that ever had a replacement undeletable.
-- ===========================================================================

CREATE OR REPLACE FUNCTION refuse_rewriting_a_replacement() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION
    'work order % completed as a replacement on % and must keep naming component % and its installed replacement %; retire the component (components.retired_on) rather than deleting it',
    OLD.id, OLD.completed_on, OLD.component_id, OLD.replacement_component_id
    USING ERRCODE = 'restrict_violation',
          CONSTRAINT = 'replacements_keep_naming_their_components';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION refuse_rewriting_a_replacement() IS
  'The completion is the provenance of the new component''s install date. A '
  'job that no longer names what it took out, or names a different thing as '
  'what it put in, is a maintenance history that reads true and is not.';

-- The WHEN clause IS the rule: no branch inside the function, so there is no
-- path through it that does anything but refuse.
CREATE TRIGGER work_orders_replacements_are_frozen
  BEFORE UPDATE OF component_id, replacement_component_id ON work_orders
  FOR EACH ROW
  WHEN (OLD.resolution = 'replaced'
        AND (NEW.component_id IS DISTINCT FROM OLD.component_id
             OR NEW.replacement_component_id IS DISTINCT FROM OLD.replacement_component_id))
  EXECUTE FUNCTION refuse_rewriting_a_replacement();

COMMENT ON TRIGGER work_orders_replacements_are_frozen ON work_orders IS
  'Refuses by the name replacements_keep_naming_their_components. It fires on '
  'the referential SET NULL that a component delete performs, which is how '
  'deleting a replaced component is refused without also freezing the open '
  'ticket whose component may legitimately disappear.';

-- The installed component was already protected, by the plain (NO ACTION)
-- foreign key 016 declared on replacement_component_id: deleting it raises a
-- foreign_key_violation that names itself honestly. Recorded here because an
-- unasserted referential action is one refactor away from becoming SET NULL.
COMMENT ON CONSTRAINT work_orders_replacement_component_id_fkey ON work_orders IS
  'NO ACTION on purpose. The component a completion installed is the subject '
  'of the KNOWN install date that completion created; it is retired, never '
  'deleted, and the delete is refused rather than quietly unlinked.';
