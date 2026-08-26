-- ===========================================================================
--  Seed — Ohio: the cross-river pack.
--
--  Cincinnati sits one bridge from Newport; one owner, one metro, two legal
--  regimes. Every Ohio difference exercises a seam the platform builds for:
--  a fixed-date appeal window with no conference (vs Kentucky's nth-weekday
--  window with a mandatory PVA conference), addback-recovery depreciation
--  conformity (vs frozen 2001 law), a 35% assessment ratio (vs 100%), a
--  statewide landlord-tenant act (vs opt-in URLTA), and municipal income
--  tax attached BELOW the state level.
--
--  UUID block a0000000-0039-… (Ohio FIPS 39, per seed/README.md). Figures
--  not yet professionally confirmed say so in their citations.
-- ===========================================================================

INSERT INTO jurisdictions (id, level, name, state, parent_id, fips_code) VALUES
  ('a0000000-0039-4000-8000-000000000010', 'state',        'Ohio', 'OH', 'a0000000-0000-4000-8000-000000000001', '39'),
  ('a0000000-0039-4000-8000-000000000021', 'county',       'Hamilton County', 'OH', 'a0000000-0039-4000-8000-000000000010', '39061'),
  ('a0000000-0039-4000-8000-000000000101', 'municipality', 'Cincinnati', 'OH', 'a0000000-0039-4000-8000-000000000021', '3915000'),
  ('a0000000-0039-4000-8000-000000000102', 'municipality', 'Norwood', 'OH', 'a0000000-0039-4000-8000-000000000021', '3957386');

-- ---------------------------------------------------------------------------
-- Property tax: the Board of Revision complaint window — state-uniform, so
-- one state-level row governs every Ohio property.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0039-4000-8000-000000000010', 'assessment_appeal', 'appeal.window.calendar',
   NULL, 'us-oh.bor-complaint',
   'ORC 5715.19(A); ORC 1.14 (weekend extension)', DATE '1976-01-01'),
  ('a0000000-0039-4000-8000-000000000010', 'assessment_appeal', 'appeal.form',
   NULL, 'DTE Form 1 (complaint against valuation), filed with the county auditor as clerk of the Board of Revision',
   'ORC 5715.19; DTE Form 1', DATE '1976-01-01'),
  ('a0000000-0039-4000-8000-000000000010', 'assessment_appeal', 'appeal.conference_required',
   NULL, 'false; no conference prerequisite — the complaint goes directly to the Board of Revision',
   'ORC 5715.19', DATE '1976-01-01'),
  ('a0000000-0039-4000-8000-000000000010', 'assessment_appeal', 'appeal.instructions',
   NULL, 'File DTE Form 1 with the county auditor between January 1 and March 31',
   'ORC 5715.19(A)', DATE '1976-01-01'),
  -- Ohio assesses at 35% of true value: comparing assessed to market without
  -- this ratio would call every Ohio property under-assessed.
  ('a0000000-0039-4000-8000-000000000010', 'assessment_ratio', 'assessment.ratio',
   0.35, NULL, 'ORC 5715.01; OAC 5703-25-05', DATE '1980-01-01');

-- ---------------------------------------------------------------------------
-- Depreciation conformity: the addback-recovery shape (vs Kentucky's frozen
-- 2001 law) — federal result, 2/3 added back, recovered over six years.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0039-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.conformity_kind',
   NULL, 'addback_recovery', 'ORC 5747.01(A) — CONFIRM WITH OH CPA', DATE '2003-01-01'),
  ('a0000000-0039-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.addback_fraction',
   0.666667, '2/3', 'ORC 5747.01(A)(17) — CONFIRM WITH OH CPA (value_text is the exact fraction)', DATE '2003-01-01'),
  ('a0000000-0039-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.recovery_years',
   6, NULL, 'ORC 5747.01(A)(18) — CONFIRM WITH OH CPA', DATE '2003-01-01');

-- ---------------------------------------------------------------------------
-- Landlord-tenant: statewide, no local adoption required — the URLTA
-- contrast that proves coverage does not require Kentucky-shaped codes.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0039-4000-8000-000000000010', 'landlord_tenant_act', 'ltl.statewide',
   NULL, 'true', 'ORC ch. 5321 (applies statewide; no local adoption step)', DATE '1974-11-04'),
  ('a0000000-0039-4000-8000-000000000010', 'security_deposit', 'deposit.interest_required',
   NULL, 'true; 5% per annum on the excess over $50 or one month''s rent, held six months or more',
   'ORC 5321.16(A)', DATE '1974-11-04'),
  ('a0000000-0039-4000-8000-000000000010', 'security_deposit', 'deposit.return_days',
   30, NULL, 'ORC 5321.16(B)', DATE '1974-11-04'),
  ('a0000000-0039-4000-8000-000000000010', 'notice_period', 'eviction.notice_days',
   3, NULL, 'ORC 1923.04', DATE '1974-11-04');

-- ---------------------------------------------------------------------------
-- Income tax: graduated at the state level (brackets deferred — the coverage
-- report says so honestly), municipal rates attached to the cities.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0039-4000-8000-000000000010', 'income_tax', 'income.type',
   NULL, 'graduated; brackets not yet loaded', 'ORC 5747.02', DATE '2024-01-01'),
  ('a0000000-0039-4000-8000-000000000101', 'income_tax', 'income.municipal_rate',
   0.018, NULL, 'ORC ch. 718; Cincinnati Mun. Code ch. 311 — CONFIRM WITH OH CPA', DATE '2021-01-01'),
  ('a0000000-0039-4000-8000-000000000102', 'income_tax', 'income.municipal_rate',
   0.02, NULL, 'ORC ch. 718 — CONFIRM WITH OH CPA', DATE '2021-01-01');
