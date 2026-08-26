-- ===========================================================================
--  Seed — Kentucky and the Northern Kentucky URLTA map
--
--  This is data, not structure: the rows that make the jurisdiction engine
--  answer questions instead of holding them. Every rule carries the authority
--  that creates it; where a figure still needs professional confirmation the
--  note says so and nothing downstream may present it as settled.
--
--  The load-bearing fact: Kentucky's URLTA (KRS 383.500-383.715) binds only
--  jurisdictions that formally adopt it. Newport is in; unincorporated
--  Campbell County is not; a property one street across the line lives under
--  different law.
-- ===========================================================================

-- The federal parent row comes from seed/899_federal.sql, which every state
-- pack may assume is installed.
INSERT INTO jurisdictions (id, level, name, state, parent_id, fips_code) VALUES
  ('a0000000-0000-4000-8000-000000000010', 'state',        'Kentucky', 'KY', 'a0000000-0000-4000-8000-000000000001', '21'),
  ('a0000000-0000-4000-8000-000000000021', 'county',       'Campbell County', 'KY', 'a0000000-0000-4000-8000-000000000010', '21037'),
  ('a0000000-0000-4000-8000-000000000022', 'county',       'Kenton County', 'KY', 'a0000000-0000-4000-8000-000000000010', '21117'),
  ('a0000000-0000-4000-8000-000000000023', 'county',       'Boone County', 'KY', 'a0000000-0000-4000-8000-000000000010', '21015'),
  -- Campbell County municipalities
  ('a0000000-0000-4000-8000-000000000101', 'municipality', 'Newport', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  ('a0000000-0000-4000-8000-000000000102', 'municipality', 'Bellevue', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  ('a0000000-0000-4000-8000-000000000103', 'municipality', 'Dayton', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  ('a0000000-0000-4000-8000-000000000104', 'municipality', 'Southgate', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  ('a0000000-0000-4000-8000-000000000105', 'municipality', 'Melbourne', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  ('a0000000-0000-4000-8000-000000000106', 'municipality', 'Silver Grove', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  ('a0000000-0000-4000-8000-000000000107', 'municipality', 'Woodlawn', 'KY', 'a0000000-0000-4000-8000-000000000021', NULL),
  -- Kenton County municipalities
  ('a0000000-0000-4000-8000-000000000111', 'municipality', 'Covington', 'KY', 'a0000000-0000-4000-8000-000000000022', NULL),
  ('a0000000-0000-4000-8000-000000000112', 'municipality', 'Ludlow', 'KY', 'a0000000-0000-4000-8000-000000000022', NULL),
  ('a0000000-0000-4000-8000-000000000113', 'municipality', 'Bromley', 'KY', 'a0000000-0000-4000-8000-000000000022', NULL),
  ('a0000000-0000-4000-8000-000000000114', 'municipality', 'Taylor Mill', 'KY', 'a0000000-0000-4000-8000-000000000022', NULL),
  -- Boone County
  ('a0000000-0000-4000-8000-000000000121', 'municipality', 'Florence', 'KY', 'a0000000-0000-4000-8000-000000000023', NULL);

-- ---------------------------------------------------------------------------
-- URLTA adoption — the flag every landlord-tenant rule depends on
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_text, citation, effective_from)
SELECT id, 'landlord_tenant_act', 'urlta.adopted', 'true',
       'KRS 383.500 (URLTA; binding only upon formal local adoption)', DATE '1975-01-01'
FROM jurisdictions
WHERE level = 'municipality' AND state = 'KY';

-- The counties themselves have NOT adopted: the contrast that makes the
-- one-street-over difference computable.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_text, citation, effective_from)
SELECT id, 'landlord_tenant_act', 'urlta.adopted', 'false',
       'KRS 383.500 (URLTA; no county-wide adoption in Campbell, Kenton or Boone)', DATE '1975-01-01'
FROM jurisdictions
WHERE level = 'county' AND state = 'KY';

-- ---------------------------------------------------------------------------
-- Substantive URLTA rules, held at the state level; they apply only where
-- urlta.adopted resolves true beneath them.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000010', 'notice_period', 'urlta.notice.nonpayment_days',
   7, NULL, 'KRS 383.660(2)', DATE '1975-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'notice_period', 'urlta.notice.material_noncompliance_days',
   14, NULL, 'KRS 383.660(1)', DATE '1975-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'security_deposit', 'urlta.deposit.separate_account_required',
   NULL, 'true', 'KRS 383.580(1)', DATE '1975-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'security_deposit', 'urlta.deposit.itemized_list_required',
   NULL, 'true', 'KRS 383.580', DATE '1975-01-01');

-- ---------------------------------------------------------------------------
-- Property tax: the inspection window and the conference prerequisite
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000010', 'assessment_appeal', 'appeal.window.rule',
   13, 'first Monday in May, thirteen days excluding Sundays',
   'KRS 133.045', DATE '1994-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'assessment_appeal', 'appeal.conference_required',
   NULL, 'true; PVA conference (Form 62A307) must precede filing with the county clerk',
   'KRS 133.120', DATE '1994-01-01'),
  -- The registry key: names WHICH registered window builder governs (ADR
  -- 0003). The builders are twin-implemented in packages/engines/src/
  -- deadlines.ts and services/api/hestia_api/calendar.py and anchor-tested.
  ('a0000000-0000-4000-8000-000000000010', 'assessment_appeal', 'appeal.window.calendar',
   NULL, 'us-ky.open-inspection',
   'KRS 133.045', DATE '1994-01-01'),
  -- What the sweep prints on the deadline row it emits.
  ('a0000000-0000-4000-8000-000000000010', 'assessment_appeal', 'appeal.instructions',
   NULL, 'PVA conference (Form 62A307) must occur within the window',
   'KRS 133.120', DATE '1994-01-01');

-- ---------------------------------------------------------------------------
-- Income tax and depreciation conformity — the dual-book parameters
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000010', 'income_tax', 'income.flat_rate',
   0.035, NULL, 'KRS 141.020 (as amended; 3.5% effective for tax year 2026)', DATE '2026-01-01'),
  -- The discriminator the dual-book engine dispatches on: 'frozen' means the
  -- state applies IRC as of a fixed date; 'addback_recovery' (e.g. Ohio)
  -- means federal result plus an add-back amortized back over N years.
  ('a0000000-0000-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.conformity_kind',
   NULL, 'frozen', 'KRS 141.0101 — CONFIRM WITH KY CPA', DATE '2002-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.bonus_addback',
   NULL, 'true; IRC s.168 applied as in effect 2001-12-31',
   'KRS 141.0101 — CONFIRM WITH KY CPA before filing reliance', DATE '2002-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.s179_cap',
   25000, NULL, 'KRS 141.0101 (2001-law limits) — CONFIRM WITH KY CPA', DATE '2002-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.s179_phaseout_start',
   200000, NULL, 'KRS 141.0101 (2001-law limits) — CONFIRM WITH KY CPA', DATE '2002-01-01');
