-- ===========================================================================
--  020 — The state rate leaves the profile, because it never belonged there.
--
--  Module 008 gave tax_profiles one state_marginal_rate per entity per year.
--  A single LLC owning in Newport and in Cincinnati is reached by Kentucky,
--  by Ohio and by the city of Cincinnati, and one column could name only one
--  of them — which is the defect issue #8 opened against.
--
--  The fix is not a wider key. It is that the number was already in the
--  packs. Kentucky's rate has sat in jurisdiction_rules since the pack
--  shipped — domain income_tax, code income.flat_rate, 0.035, citing
--  "KRS 141.020 (as amended; 3.5% effective for tax year 2026)" — and
--  Cincinnati's municipal rate sits beside it at 0.018 under ORC ch. 718.
--  Neither is a fact about a taxpayer: nobody chose them, and no two
--  taxpayers on one street have different ones. ADR 0003 says in so many
--  words that a cited statutory number is data, resolved through
--  jurisdiction_chain().
--
--  A second, entity-side copy keyed by jurisdiction_id would be a THIRD copy
--  of KRS 141.020's rate — the seed, tests/constraints.sql, and now the
--  profile — and the ADR's own convention, that three copies are acceptable
--  only because CI fails when any copy moves alone, has no job comparing
--  them. Worse, that copy would carry no state literal, so
--  scripts/check_state_literals.sh would stay green while the rule it exists
--  to protect was being broken.
--
--  So this module SUBTRACTS, and the reader ships beside it:
--  GET /properties/{id}/tax-rates walks the property's own chain and answers
--  per taxing body, each with that body's own citation, or names a gap.
--
--  WHY A DROP IS LEGAL HERE. The applied-once rule polices FILE TEXT through
--  the sha256 recorded in schema_migrations. Module 008's bytes are
--  untouched and its checksum still matches; this is a new file applied
--  forward-only. Module 019 already did the harder version of this to a
--  module-004 table, dropping a shipped unique constraint and adding a NOT
--  NULL column with no default.
--
--  WHY THE DROP IS SAFE, as evidence rather than assumption. tax_profiles
--  has never had a writer OR a reader: across the repository the table
--  appears only in 008 itself, a cross-reference comment in 019's header,
--  the manifest line, four assertions in tests/constraints.sql, and
--  conftest's clean list. `state_marginal_rate` appears in exactly two
--  places: its declaration and one constraint assertion. There are no rows
--  anywhere to discard, and one test to fix.
--
--  Keeping the column was the weaker option. It is a second place a state
--  rate can live, one of them structurally unable to say WHICH state it
--  means, and the first reader to pick the wrong one prints a Kentucky
--  number on an Ohio card with a citation attached.
-- ===========================================================================

ALTER TABLE tax_profiles DROP COLUMN state_marginal_rate;

-- `capital_gains_rate` named neither a government nor a schedule. It could
-- honestly have meant the federal 0/15/20 brackets (which is NOT
-- federal_marginal_rate), a state rate, or somebody's blend of the two — and
-- the blend is the reading that silently double-counts state tax in the
-- disposal counterfactual this ticket was opened to unblock. Renamed rather
-- than merely commented, because a comment is not in the query text the next
-- reader writes. Free to rename: it has no reader in the repository.
ALTER TABLE tax_profiles RENAME COLUMN capital_gains_rate TO federal_capital_gains_rate;

COMMENT ON TABLE tax_profiles IS
  'One row per entity per filing year, carrying the facts that are true of '
  'the taxpayer wherever it owns: how it is taxed, its filing status, its '
  'MAGI, its federal rates. What is NOT here is any rate belonging to a '
  'particular government. Those are jurisdiction data (ADR 0003), cited to a '
  'statute, resolved through jurisdiction_chain() from the property that '
  'sourced the income — because an entity owning across a state line is '
  'reached by more than one government, and a column cannot say which.';

COMMENT ON COLUMN tax_profiles.federal_marginal_rate IS
  'The taxpayer''s top federal bracket rate — half statute (IRC s.1) and half '
  'this taxpayer''s own income, which is why it is an estimate carried with '
  'provenance rather than a pack row. State and local rates are NOT here: '
  'they resolve from jurisdiction_rules through the property''s own chain, '
  'per taxing body, in hestia_api/income_tax.py.';

COMMENT ON COLUMN tax_profiles.federal_capital_gains_rate IS
  'The federal long-term rate — one of the 0/15/20 brackets, a different '
  'schedule from federal_marginal_rate and not derivable from it. The 3.8 '
  'percent net investment income tax (IRC s.1411) is a fourth number again '
  'and is NOT modelled here; a reader must not fold it in. Nothing state or '
  'local belongs in this column.';
