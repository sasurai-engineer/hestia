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

-- ---------------------------------------------------------------------------
-- The collection calendar (seed/910, issue #145): the November free-money
-- moment gets its law, the repealed section stays dead, and the sheriffs'
-- "21%" is pinned as the composite it is.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  discount RECORD;
  second RECORD;
  alt TEXT;
  campbell_kind TEXT;
  campbell_opens DATE;
  campbell_closes DATE;
  newport_due TEXT;
  newport_discount TEXT;
  roll TEXT;
BEGIN
  SELECT r.value_numeric, r.value_text, r.citation INTO discount
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND j.level = 'state'
    AND r.code = 'collection.discount' AND r.superseded_by IS NULL;
  IF discount.value_numeric IS DISTINCT FROM 0.02::NUMERIC
     OR discount.value_text NOT LIKE '%November 1 INCLUSIVE%' THEN
    RAISE EXCEPTION 'the 2%% discount row is missing its rate or its boundary: %',
      discount.value_text;
  END IF;
  -- The repeal warning travels with the calendar, or someone "corrects" the
  -- pack back to a statute that died in 2010.
  IF NOT EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Kentucky' AND j.level = 'state' AND r.code = 'collection.due'
      AND r.citation LIKE '%134.020%REPEALED%'
  ) THEN
    RAISE EXCEPTION 'the KRS 134.020 repeal warning is missing from collection.due';
  END IF;
  RAISE NOTICE '  ok      two percent through November 1 inclusive, and 134.020 stays dead';

  -- The second penalty is TEN percent. A 0.21 anywhere in the domain means
  -- somebody seeded the sheriffs' composite as a statutory rate.
  SELECT r.value_numeric, r.value_text INTO second
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND j.level = 'state'
    AND r.code = 'collection.phase.penalty_second' AND r.superseded_by IS NULL;
  IF second.value_numeric IS DISTINCT FROM 0.10::NUMERIC
     OR second.value_text NOT LIKE '%COMPOSITE%' AND second.value_text NOT LIKE '%never a statutory 21%' THEN
    RAISE EXCEPTION 'the second penalty is %, expected 0.10 with the 21-composite warning',
      second.value_numeric;
  END IF;
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'KY' AND r.domain = 'tax_collection'
      AND r.value_numeric = 0.21::NUMERIC
  ) THEN
    RAISE EXCEPTION 'a Kentucky collection row carries 0.21 — the sheriffs'' '
      'composite (10%% penalty + 10%% fee + 1%%) seeded as a statutory rate';
  END IF;
  RAISE NOTICE '  ok      the second penalty is ten percent, and no row carries the 21 composite';

  -- The alternative schedule names ITS elector: the department, never the
  -- county or the taxpayer.
  SELECT r.value_text INTO alt
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND j.level = 'state'
    AND r.code = 'collection.alternative_schedule' AND r.superseded_by IS NULL;
  IF alt IS NULL OR alt NOT LIKE '%THE DEPARTMENT%' THEN
    RAISE EXCEPTION 'the alternative schedule does not name its elector: %', alt;
  END IF;
  RAISE NOTICE '  ok      the alternative schedule is the department''s, phases anchored to mailing';

  -- Campbell runs the alternative schedule, its 2025 window is bounded by
  -- its year, and the 2026 absence has a named source.
  SELECT r.value_text INTO campbell_kind
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Campbell County' AND r.code = 'collection.schedule_kind'
    AND r.superseded_by IS NULL;
  IF campbell_kind IS NULL OR campbell_kind NOT LIKE 'alternative;%' THEN
    RAISE EXCEPTION 'Campbell County does not state its schedule kind: %', campbell_kind;
  END IF;
  SELECT opens.value_text::date, closes.value_text::date
    INTO campbell_opens, campbell_closes
  FROM jurisdiction_rules opens
  JOIN jurisdictions j ON j.id = opens.jurisdiction_id
  JOIN jurisdiction_rules closes ON closes.jurisdiction_id = opens.jurisdiction_id
   AND closes.code = 'collection.discount.closes_on'
   AND closes.effective_from = opens.effective_from
  WHERE j.name = 'Campbell County' AND opens.code = 'collection.discount.opens_on'
    AND opens.superseded_by IS NULL AND closes.superseded_by IS NULL;
  IF campbell_opens IS DISTINCT FROM DATE '2025-11-01'
     OR campbell_closes IS DISTINCT FROM DATE '2025-11-30' THEN
    RAISE EXCEPTION 'the Campbell 2025 discount window is % .. %, expected Nov 1-30',
      campbell_opens, campbell_closes;
  END IF;
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Campbell County'
      AND r.code IN ('collection.discount.opens_on', 'collection.discount.closes_on')
      AND (r.effective_to IS NULL
           OR r.value_text::date < r.effective_from
           OR r.value_text::date >= r.effective_to)
  ) THEN
    RAISE EXCEPTION 'a published Campbell discount window is unbounded or outside its year';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Campbell County' AND r.code = 'collection.schedule.source'
      AND r.value_text LIKE 'published_by_sheriff;%'
  ) THEN
    RAISE EXCEPTION 'the Campbell schedule has no named source for next year''s dates';
  END IF;
  RAISE NOTICE '  ok      Campbell 2025: November, bounded by its year, next year''s source named';

  -- Newport collects its own tax on its own calendar, and says NO discount
  -- out loud rather than by omission.
  SELECT r.value_text INTO newport_due
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Newport' AND r.code = 'collection.due' AND r.superseded_by IS NULL;
  IF newport_due IS NULL OR newport_due NOT LIKE '%October 31%' THEN
    RAISE EXCEPTION 'the Newport city due date is missing: %', newport_due;
  END IF;
  SELECT r.value_text INTO newport_discount
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Newport' AND r.code = 'collection.discount' AND r.superseded_by IS NULL;
  IF newport_discount IS NULL OR newport_discount NOT LIKE 'none;%' THEN
    RAISE EXCEPTION 'Newport does not state that it offers no discount: %', newport_discount;
  END IF;
  RAISE NOTICE '  ok      Newport: October 31, its own collector, and a stated no on the discount';

  -- The weekend question stays visibly unresolved — a roll nobody proved
  -- must never be relied on, and the row says so.
  SELECT r.value_text INTO roll
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Kentucky' AND j.level = 'state'
    AND r.code = 'collection.weekend_roll' AND r.superseded_by IS NULL;
  IF roll IS NULL OR roll NOT LIKE 'UNRESOLVED;%'
     OR roll NOT LIKE '%SUNDAY ONLY%' THEN
    RAISE EXCEPTION 'the weekend-roll row does not state its unresolved asymmetry: %', roll;
  END IF;
  RAISE NOTICE '  ok      the weekend roll is recorded as unresolved, stage-early stated';
END $$;
