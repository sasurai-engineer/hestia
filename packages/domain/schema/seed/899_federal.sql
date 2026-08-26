-- ===========================================================================
--  Seed — the federal tier.
--
--  Shared by every state pack: the root of the jurisdiction hierarchy and
--  the federal rules that apply identically in all fifty states. Numbered
--  899 so it sorts before every state pack (900-949); no pack may assume any
--  other pack is installed, but every pack may assume this one is.
-- ===========================================================================

INSERT INTO jurisdictions (id, level, name, state, parent_id, fips_code) VALUES
  ('a0000000-0000-4000-8000-000000000001', 'federal', 'United States', NULL, NULL, NULL);

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000001', 'depreciation_conformity', 'depreciation.bonus_percent',
   1.0, 'permanent for property acquired and placed in service after 2025-01-19',
   'IRC s.168(k), as amended by P.L. 119-21 (2025)', DATE '2025-01-20'),
  ('a0000000-0000-4000-8000-000000000001', 'depreciation_conformity', 'depreciation.s179_cap',
   2500000, NULL, 'IRC s.179, as amended by P.L. 119-21 (2025); 2026 limit', DATE '2026-01-01'),
  ('a0000000-0000-4000-8000-000000000001', 'estimated_tax', 'estimated.individual.schedule',
   NULL, 'April 15, June 15, September 15, January 15 (following year)',
   'IRC s.6654(c)', DATE '1987-01-01');
