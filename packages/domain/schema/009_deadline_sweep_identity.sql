-- ===========================================================================
--  Hestia — sweep identity for deadlines
--
--  The sweep that turns portfolio facts into deadline rows must be safe to run
--  any number of times: the identity of a generated deadline is its kind, its
--  date, and exactly what it is anchored to. NULLS NOT DISTINCT, because most
--  anchors are null on any given row and under default semantics the dedupe
--  would never fire — the same trap already closed on jurisdictions and
--  passive_loss_carryforwards.
--
--  Consequence, accepted and documented: two hand-entered 'custom' deadlines
--  with identical anchors and dates collapse into one. Distinguish them by
--  date or anchor; the note field is not identity.
-- ===========================================================================

CREATE UNIQUE INDEX deadlines_sweep_identity
  ON deadlines (kind, due_on, property_id, entity_id, lease_id,
                policy_id, debt_id, exchange_id, appeal_id)
  NULLS NOT DISTINCT;
