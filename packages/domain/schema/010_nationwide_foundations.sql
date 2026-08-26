-- ===========================================================================
--  010 — Nationwide foundations.
--
--  Kentucky is the motivating example and pack one, not the design. This
--  module removes the structural assumptions that only Kentucky's geography
--  let us get away with, so that a second state is a data pack, never a fork.
--  (ADR 0003: jurisdiction is data.)
-- ===========================================================================

-- Sub-county names are NOT unique within a state: Ohio alone has roughly
-- twenty 'Washington Township's spread across different counties, and
-- Michigan, Indiana and Pennsylvania repeat the pattern. Kentucky's names
-- happen to be unique statewide, which is why the old key seeded cleanly and
-- the defect stayed invisible. parent_id joins the key; the walk stays
-- deterministic because parent_id is NULL only for the federal row.
ALTER TABLE jurisdictions
  DROP CONSTRAINT jurisdictions_level_name_state_key;
ALTER TABLE jurisdictions
  ADD CONSTRAINT jurisdictions_level_name_state_parent_key
  UNIQUE NULLS NOT DISTINCT (level, name, state, parent_id);

-- The widened key leans on 'parent_id is NULL only for the federal root';
-- unenforced, that invariant is one careless insert from a duplicate
-- ('municipality', 'Newport', 'KY', NULL) beside the parented row, and from
-- chains that dead-end before reaching the state. Enforced both ways: the
-- federal root has no parent, everything else must.
ALTER TABLE jurisdictions
  ADD CONSTRAINT parent_required_below_federal
  CHECK ((level = 'federal') = (parent_id IS NULL));

-- One state-level row per state code: the sweep anchors properties by
-- LEFT JOIN on (level = 'state', state), and a second 'Ohio' row would fan
-- every Ohio property out to two anchors and make resolution arbitrary.
CREATE UNIQUE INDEX one_state_row_per_state
  ON jurisdictions (state) WHERE level = 'state';

-- Vocabulary a second state needs on day one. Members are append-only; a
-- pack needing genuinely novel vocabulary ships its own ALTER TYPE in a
-- numbered module beside its seed (the 007 precedent).
ALTER TYPE rule_domain ADD VALUE IF NOT EXISTS 'assessment_ratio';
ALTER TYPE rule_domain ADD VALUE IF NOT EXISTS 'exemption';

-- Function-named, assessor-neutral sibling of Kentucky's 'pva_conference'.
-- Enum members are permanent, so the KY-named member stays; new rows should
-- prefer this one. (Ohio: informal review with the county Auditor; Texas:
-- ARB informal conference; California: Prop 8 assessor review.)
ALTER TYPE deadline_kind ADD VALUE IF NOT EXISTS 'assessor_conference';

-- One chain walk, shared by the deadline sweep and the coverage report, so
-- resolution order is decided in exactly one place: most specific first.
-- The depth bound is a cycle guard; US governance never nests deeper than
-- municipality -> county -> state -> federal plus special districts.
CREATE FUNCTION jurisdiction_chain(start_id UUID)
RETURNS TABLE (jurisdiction_id UUID, depth INT)
LANGUAGE sql STABLE AS $$
  WITH RECURSIVE walk AS (
    SELECT j.id, 0 AS depth FROM jurisdictions j WHERE j.id = start_id
    UNION ALL
    SELECT j.parent_id, w.depth + 1
    FROM walk w JOIN jurisdictions j ON j.id = w.id
    WHERE j.parent_id IS NOT NULL AND w.depth < 8
  )
  SELECT id, depth FROM walk
$$;

COMMENT ON FUNCTION jurisdiction_chain (UUID) IS
  'The governing-body chain from a jurisdiction upward, depth 0 at the start. '
  'Rule resolution joins this to jurisdiction_rules and takes the smallest '
  'depth (most specific body), newest effective_from. Every reader must use '
  'this function rather than re-walking parent_id, so resolution order can '
  'never disagree between the sweep and the coverage report.';

COMMENT ON TABLE jurisdictions IS
  'A hierarchy, because a property is governed by several bodies at once and '
  'they do not agree. The platform is nationwide; each state arrives as a '
  'seed pack of rows here plus cited rules in jurisdiction_rules (ADR 0003). '
  'Kentucky is the motivating example: URLTA (KRS 383.500-715) binds only the '
  'governments that formally adopted it, so Newport is covered while '
  'unincorporated Campbell County is not — a property one street across a '
  'city line has different deposit rules, notice periods and cure rights. '
  'Resolution walks jurisdiction_chain() and takes the most specific rule.';
