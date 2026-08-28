-- ===========================================================================
--  Pack test — Kentucky (seed/900_jurisdictions_kentucky.sql).
--
--  Runs after the seeds and after tests/constraints.sql. Read-only: asserts
--  the pack answers the questions it exists to answer, and pins the seeded
--  numbers against the engine constants so no copy can move alone.
-- ===========================================================================

\set ON_ERROR_STOP on

\echo ''
\echo 'kentucky pack'

DO $$
DECLARE
  newport BOOLEAN;
  campbell BOOLEAN;
  chain_len INT;
  federal_depth INT;
  calendar_key TEXT;
  conformity TEXT;
  cap NUMERIC;
  phaseout NUMERIC;
  ratio NUMERIC;
  ratio_citation TEXT;
  income_rate NUMERIC;
  income_citation TEXT;
  distinct_ratios INT;
BEGIN
  -- The load-bearing URLTA contrast: one street across the Newport line is a
  -- different legal regime.
  SELECT (r.value_text = 'true') INTO newport
  FROM jurisdiction_rules r
  JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Newport' AND j.level = 'municipality' AND r.code = 'urlta.adopted';
  SELECT (r.value_text = 'true') INTO campbell
  FROM jurisdiction_rules r
  JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Campbell County' AND j.level = 'county' AND r.code = 'urlta.adopted';
  IF newport IS DISTINCT FROM TRUE OR campbell IS DISTINCT FROM FALSE THEN
    RAISE EXCEPTION 'URLTA seed wrong: Newport=%, Campbell County=%', newport, campbell;
  END IF;
  RAISE NOTICE '  ok      Newport is URLTA; unincorporated Campbell County is not';

  -- The chain resolves Newport -> Campbell -> Kentucky -> United States.
  SELECT count(*), max(depth) INTO chain_len, federal_depth
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Newport' AND level = 'municipality'));
  IF chain_len <> 4 OR federal_depth <> 3 THEN
    RAISE EXCEPTION 'Newport chain wrong: % rows, max depth %', chain_len, federal_depth;
  END IF;
  RAISE NOTICE '  ok      the Newport chain walks four levels to the federal root';

  -- The appeal window carries its statute AND its registry key.
  IF NOT EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Kentucky' AND r.code = 'appeal.window.rule' AND r.citation LIKE '%133.045%'
  ) THEN
    RAISE EXCEPTION 'the KRS 133.045 appeal-window rule is not seeded';
  END IF;
  SELECT r.value_text INTO calendar_key
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND j.level = 'state'
    AND r.code = 'appeal.window.calendar' AND r.superseded_by IS NULL;
  IF calendar_key IS DISTINCT FROM 'us-ky.open-inspection' THEN
    RAISE EXCEPTION 'appeal.window.calendar resolves to %, expected us-ky.open-inspection',
      calendar_key;
  END IF;
  RAISE NOTICE '  ok      the appeal window carries its statute and registry key';

  -- Anti-drift pins: the seed is the authority; the engine constants
  -- (KY_2001_S179 in depreciation.ts, finance.py) and the fixture rows must
  -- match these numbers, and the fixture tests pin the engines. If this
  -- assertion moves, every copy must move with it.
  SELECT r.value_text INTO conformity
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND r.code = 'depreciation.conformity_kind'
    AND r.superseded_by IS NULL;
  SELECT r.value_numeric INTO cap
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND r.code = 'depreciation.s179_cap'
    AND r.superseded_by IS NULL;
  SELECT r.value_numeric INTO phaseout
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND r.code = 'depreciation.s179_phaseout_start'
    AND r.superseded_by IS NULL;
  IF conformity IS DISTINCT FROM 'frozen' OR cap IS DISTINCT FROM 25000::NUMERIC
     OR phaseout IS DISTINCT FROM 200000::NUMERIC THEN
    RAISE EXCEPTION 'KY conformity drifted: kind=%, cap=%, phaseout=%',
      conformity, cap, phaseout;
  END IF;
  RAISE NOTICE '  ok      frozen-2001 conformity: s179 cap 25000, phaseout 200000';

  -- The federal tier is the shared 899 seed, not part of this pack.
  IF NOT EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.level = 'federal' AND r.code = 'depreciation.bonus_percent'
      AND r.value_numeric = 1.0
  ) THEN
    RAISE EXCEPTION 'the federal 100 percent bonus row (899_federal.sql) is missing';
  END IF;
  RAISE NOTICE '  ok      the shared federal tier is installed beneath the pack';

  -- One hundred percent, and it is transcription rather than inference: KRS
  -- 132.191(1) states the standard in those words. A detector comparing an
  -- assessment against market divides by this, so an ABSENT row and a row of
  -- zero are one keystroke apart — which is why the pack now carries it.
  SELECT r.value_numeric, r.citation INTO ratio, ratio_citation
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND r.code = 'assessment.ratio' AND r.superseded_by IS NULL;
  IF ratio IS DISTINCT FROM 1.000000::NUMERIC THEN
    RAISE EXCEPTION 'Kentucky assesses at %, expected 1.0 of fair cash value', ratio;
  END IF;
  IF ratio_citation NOT LIKE '%132.191%' THEN
    RAISE EXCEPTION 'the Kentucky ratio does not cite the statute that states it '
      'as a percentage: %', ratio_citation;
  END IF;
  -- The sales-assessment ratio study's 90 percent is a COUNTY compliance band
  -- from Department of Revenue manual policy, not a parcel's standard. If it
  -- ever lands in this field every Kentucky assessment is understated by
  -- seven percent, so the value is pinned exactly rather than by a range.
  IF ratio < 1.000000 THEN
    RAISE EXCEPTION 'Kentucky ratio is below 1.0 — the ratio-study compliance '
      'band is not the assessment standard';
  END IF;
  RAISE NOTICE '  ok      Kentucky assesses at 100 percent, and cites the words';

  -- Three states, three ratios. This is the whole reason the detector cannot
  -- compare an assessment to a market value without asking the pack first.
  SELECT count(DISTINCT r.value_numeric) INTO distinct_ratios
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name IN ('Kentucky', 'Ohio', 'Tennessee')
    AND r.code = 'assessment.ratio' AND r.superseded_by IS NULL;
  IF distinct_ratios <> 3 THEN
    RAISE EXCEPTION 'expected three distinct assessment ratios, found %', distinct_ratios;
  END IF;
  RAISE NOTICE '  ok      100, 35 and 25 percent: three states, three ratios';

  -- The income_tax domain had no pin in any pack test until #8 gave it a
  -- reader. Until module 020 this same figure also sat in a tax_profiles
  -- assertion in tests/constraints.sql, where nothing compared the two; the
  -- rate now has one home and this is the assertion that keeps it there.
  SELECT r.value_numeric, r.citation INTO income_rate, income_citation
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND r.code = 'income.flat_rate' AND r.superseded_by IS NULL;
  IF income_rate IS DISTINCT FROM 0.035000::NUMERIC THEN
    RAISE EXCEPTION 'Kentucky income tax is %, expected 0.035', income_rate;
  END IF;
  IF income_citation NOT LIKE '%141.020%' THEN
    RAISE EXCEPTION 'the Kentucky income rate does not cite KRS 141.020: %',
      income_citation;
  END IF;
  -- A rate, not a percentage. jurisdiction_rules.value_numeric carries no
  -- unit, so 3.5 and 0.035 are equally storable and differ by a hundredfold.
  IF income_rate >= 1 THEN
    RAISE EXCEPTION 'the Kentucky income rate is stored in percent form: %',
      income_rate;
  END IF;
  RAISE NOTICE '  ok      Kentucky taxes income at 3.5 percent, stored as a rate';
END $$;
