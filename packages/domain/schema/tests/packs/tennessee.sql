-- ===========================================================================
--  Pack test — Tennessee (seed/907_jurisdictions_tennessee.sql).
--
--  Two states can agree by accident; three cannot. This asserts the
--  three-way divergence: from ONE query shape, Newport, Cincinnati and
--  Nashville resolve to three appeal calendars, three conformity regimes and
--  three landlord-tenant adoption shapes. It also pins the two facts this
--  pack was the first to need — a county that disagrees with its state about
--  a calendar, and a state that answers "no such duty" instead of falling
--  silent. Read-only.
-- ===========================================================================

\set ON_ERROR_STOP on

\echo ''
\echo 'tennessee pack'

CREATE OR REPLACE FUNCTION pg_temp.tn_resolve(city TEXT, rule_code TEXT)
RETURNS TEXT LANGUAGE sql STABLE AS $fn$
  SELECT r.value_text
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions
      WHERE name = city AND level = 'municipality' LIMIT 1)) c
  JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
  WHERE r.code = rule_code AND r.superseded_by IS NULL
  ORDER BY c.depth ASC, r.effective_from DESC
  LIMIT 1;
$fn$;

CREATE OR REPLACE FUNCTION pg_temp.tn_rule(state_name TEXT, rule_code TEXT)
RETURNS jurisdiction_rules LANGUAGE sql STABLE AS $fn$
  SELECT r.* FROM jurisdiction_rules r
  JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = state_name AND r.code = rule_code AND r.superseded_by IS NULL
  LIMIT 1;
$fn$;

DO $$
DECLARE
  chain_len INT;
  tn_key TEXT;
  ky_key TEXT;
  oh_key TEXT;
  source_kind TEXT;
  nash_opens DATE;
  nash_closes DATE;
  memphis_closes DATE;
  ratio NUMERIC;
  oh_ratio NUMERIC;
  conformity TEXT;
  statewide TEXT;
  adopted TEXT;
  interest TEXT;
  oh_interest TEXT;
  absent TEXT;
  income TEXT;
  fonce TEXT;
  urlta_notice NUMERIC;
  covered_counties INT;
  hamiltons INT;
BEGIN
  -- Nashville -> Davidson County -> Tennessee -> United States. The
  -- consolidated metro government is still four levels deep, so resolution
  -- never has to know that Nashville is unusual.
  SELECT count(*) INTO chain_len
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Nashville' AND level = 'municipality'));
  IF chain_len <> 4 THEN
    RAISE EXCEPTION 'Nashville chain wrong: % rows', chain_len;
  END IF;
  RAISE NOTICE '  ok      the Nashville chain walks four levels to the federal root';

  -- THE THREE-REGIME ASSERT: one query shape, three states, three answers —
  -- and Tennessee's answer is that there is no function to name.
  ky_key := pg_temp.tn_resolve('Newport', 'appeal.window.calendar');
  oh_key := pg_temp.tn_resolve('Cincinnati', 'appeal.window.calendar');
  tn_key := pg_temp.tn_resolve('Nashville', 'appeal.window.calendar');
  IF ky_key = oh_key THEN
    RAISE EXCEPTION 'Kentucky and Ohio calendars collapsed at %', ky_key;
  END IF;
  IF tn_key IS NOT NULL THEN
    RAISE EXCEPTION 'Tennessee names calendar %, but its deadline is an '
      'administrative date no builder may compute', tn_key;
  END IF;
  RAISE NOTICE '  ok      two computed calendars, and a third state that names none';

  -- Instead it says WHY, so an absent date is a named gap and not silence.
  source_kind := pg_temp.tn_resolve('Nashville', 'appeal.window.source');
  IF source_kind IS NULL OR source_kind NOT LIKE 'published_by_county;%' THEN
    RAISE EXCEPTION 'Tennessee does not say where its appeal date comes from: %',
      source_kind;
  END IF;

  -- THE PUBLISHED WINDOW: a real date, from the county that published it,
  -- paired to its open by effective_from. This is the county-level fact no
  -- earlier pack needed, and the one a function would have got wrong.
  SELECT closes.value_text::date, opens.value_text::date
    INTO nash_closes, nash_opens
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Nashville' AND level = 'municipality')) c
  JOIN jurisdiction_rules closes ON closes.jurisdiction_id = c.jurisdiction_id
   AND closes.code = 'appeal.window.closes_on' AND closes.superseded_by IS NULL
  LEFT JOIN jurisdiction_rules opens ON opens.jurisdiction_id = closes.jurisdiction_id
   AND opens.code = 'appeal.window.opens_on' AND opens.superseded_by IS NULL
   AND opens.effective_from = closes.effective_from
  ORDER BY c.depth ASC, closes.value_text::date ASC
  LIMIT 1;
  IF nash_closes IS DISTINCT FROM DATE '2026-06-26' THEN
    RAISE EXCEPTION 'Davidson County 2026 closes %, expected 2026-06-26', nash_closes;
  END IF;
  IF nash_opens IS DISTINCT FROM DATE '2026-05-26' THEN
    RAISE EXCEPTION 'the Davidson 2026 open did not pair with its close: %', nash_opens;
  END IF;
  -- The August 1 State Board date must never masquerade as the filing
  -- deadline: it is 36 days later, and by then the objection is waived.
  IF nash_closes >= DATE '2026-08-01' THEN
    RAISE EXCEPTION 'the Davidson deadline is not earlier than the State Board date';
  END IF;
  RAISE NOTICE '  ok      Davidson 2026 closes June 26, a month before the State Board date';

  -- Shelby publishes its own, and it differs. A statewide date would have
  -- been wrong for at least one of them.
  SELECT closes.value_text::date INTO memphis_closes
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Memphis' AND level = 'municipality')) c
  JOIN jurisdiction_rules closes ON closes.jurisdiction_id = c.jurisdiction_id
   AND closes.code = 'appeal.window.closes_on' AND closes.superseded_by IS NULL
  ORDER BY c.depth ASC, closes.value_text::date ASC
  LIMIT 1;
  IF memphis_closes IS DISTINCT FROM DATE '2026-06-30' THEN
    RAISE EXCEPTION 'Shelby County 2026 closes %, expected 2026-06-30', memphis_closes;
  END IF;
  IF memphis_closes = nash_closes THEN
    RAISE EXCEPTION 'two counties in one state resolved to the same published date';
  END IF;
  RAISE NOTICE '  ok      two counties, two published dates, four days apart';

  -- Every published date is bounded by its own year: one that outlived it
  -- would go on being served as though it were still the answer.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TN' AND r.code IN ('appeal.window.opens_on', 'appeal.window.closes_on')
      AND (r.effective_to IS NULL
           OR r.value_text::date < r.effective_from
           OR r.value_text::date >= r.effective_to)
  ) THEN
    RAISE EXCEPTION 'a published Tennessee window is unbounded or outside its own year';
  END IF;
  RAISE NOTICE '  ok      every published date is bounded by the year it belongs to';

  -- Classified assessment. The line is RENTAL UNIT COUNT, not occupancy:
  -- one rental unit is residential at 25%, two or more is commercial at 40%.
  ratio := (pg_temp.tn_rule('Tennessee', 'assessment.ratio')).value_numeric;
  oh_ratio := (pg_temp.tn_rule('Ohio', 'assessment.ratio')).value_numeric;
  IF ratio IS DISTINCT FROM 0.25::NUMERIC THEN
    RAISE EXCEPTION 'Tennessee residential ratio is %, expected 0.25', ratio;
  END IF;
  -- Ohio's is pinned by its own pack test; this one only has to prove the
  -- two states do not share a row, which a mis-scoped seed would break.
  IF oh_ratio IS NULL OR ratio = oh_ratio THEN
    RAISE EXCEPTION 'Tennessee and Ohio ratios collapsed at %', ratio;
  END IF;
  IF (pg_temp.tn_rule('Tennessee', 'assessment.ratio.commercial')).value_numeric
     IS DISTINCT FROM 0.40::NUMERIC THEN
    RAISE EXCEPTION 'the Tennessee commercial ratio row is missing or wrong';
  END IF;
  -- The caveat travels WITH the ratio, or the platform states 25% with a
  -- confidence the law does not support.
  IF (pg_temp.tn_rule('Tennessee', 'assessment.ratio.caveat')).citation
     NOT LIKE '%25-016%' THEN
    RAISE EXCEPTION 'the classification caveat is missing its authority';
  END IF;
  RAISE NOTICE '  ok      25 percent residential, 40 commercial, and the caveat that qualifies them';

  -- Conformity: three regimes across three states, none of them silence.
  conformity := (pg_temp.tn_rule('Tennessee', 'depreciation.conformity_kind')).value_text;
  IF conformity IS DISTINCT FROM 'none' THEN
    RAISE EXCEPTION 'Tennessee conformity is %, expected none', conformity;
  END IF;
  IF (SELECT count(DISTINCT r.value_text)
      FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
      WHERE j.name IN ('Kentucky', 'Ohio', 'Tennessee')
        AND r.code = 'depreciation.conformity_kind' AND r.superseded_by IS NULL) <> 3 THEN
    RAISE EXCEPTION 'the three conformity regimes are not distinct';
  END IF;
  -- "None" is the OWNER's answer. The entity still meets an excise-tax
  -- addback, and folding the two into one verdict would be wrong for one
  -- reader or the other.
  IF (pg_temp.tn_rule('Tennessee', 'depreciation.entity_bonus_addback')).value_text
     NOT LIKE 'true;%' THEN
    RAISE EXCEPTION 'the entity-level bonus addback is missing';
  END IF;
  RAISE NOTICE '  ok      frozen, addback-recovery and none are three regimes';

  -- No individual income tax: recorded as a finding, not left blank.
  income := (pg_temp.tn_rule('Tennessee', 'income.type')).value_text;
  IF income IS NULL OR income NOT LIKE 'none;%' THEN
    RAISE EXCEPTION 'Tennessee income.type is %, expected a stated none', income;
  END IF;
  -- Two definitions of "residential" in one state code: four units for the
  -- FONCE exemption, one rental unit for the assessment ratio. The pack must
  -- carry both or the platform will quietly conflate them.
  fonce := (pg_temp.tn_rule('Tennessee', 'income.entity_exemption')).value_text;
  IF fonce IS NULL OR fonce NOT LIKE '%FOUR residential%' THEN
    RAISE EXCEPTION 'the FONCE four-unit definition is not recorded';
  END IF;
  RAISE NOTICE '  ok      no individual income tax, and the entity taxes that remain';

  -- THE THIRD ADOPTION SHAPE: not statewide (Ohio), not municipal opt-in
  -- (Kentucky) — the county carries it, by population, by operation of law.
  statewide := (pg_temp.tn_rule('Tennessee', 'ltl.statewide')).value_text;
  IF statewide IS NULL OR statewide NOT LIKE 'false;%' THEN
    RAISE EXCEPTION 'Tennessee ltl.statewide is %, expected a stated false', statewide;
  END IF;
  adopted := pg_temp.tn_resolve('Nashville', 'urlta.adopted');
  IF adopted IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'Nashville resolves urlta.adopted = %, expected true', adopted;
  END IF;
  -- Kentucky's counties deny what their cities adopt; Tennessee's counties
  -- are the ones that carry it. Same rule code, opposite level — which is
  -- why resolution walks a chain instead of switching on a state literal.
  IF (SELECT r.value_text
      FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
      WHERE j.name = 'Campbell County' AND r.code = 'urlta.adopted'
        AND r.superseded_by IS NULL) <> 'false' THEN
    RAISE EXCEPTION 'the Kentucky county contrast has moved; this test is stale';
  END IF;
  RAISE NOTICE '  ok      a third adoption shape: the county carries it, not the city';

  -- And because the act binds by county, the county is where its numbers
  -- live — for ALL SEVENTEEN counties the chapter reaches, not just the two
  -- with property in them. A county missing from this table is a county whose
  -- landlord would be handed the law of a chapter that disclaims him.
  SELECT count(*) INTO covered_counties
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.state = 'TN' AND j.level = 'county'
    AND r.code = 'urlta.adopted' AND r.value_text = 'true'
    AND r.superseded_by IS NULL;
  IF covered_counties <> 17 THEN
    RAISE EXCEPTION 'the URLTA county list is % rows, expected the frozen seventeen',
      covered_counties;
  END IF;
  -- Anderson clears the threshold by 129 people and Putnam misses it by
  -- 2,679 despite passing 75,000 in the 2020 census — the two counties that
  -- prove the list is read from the 2010 figures and is frozen there.
  IF NOT EXISTS (
    SELECT 1 FROM jurisdictions WHERE state = 'TN' AND name = 'Anderson County'
  ) THEN
    RAISE EXCEPTION 'Anderson County is missing; it qualifies by 129 people';
  END IF;
  -- The nineteen-county list circulating in secondary sources — including
  -- the Attorney General's own consumer-laws page — adds these two on the
  -- repealed 68,000 threshold. Whoever next "corrects" this pack against that
  -- page must fail here instead of succeeding.
  IF EXISTS (
    SELECT 1 FROM jurisdictions WHERE state = 'TN'
      AND name IN ('Putnam County', 'Greene County')
  ) THEN
    RAISE EXCEPTION 'Putnam or Greene is seeded. Both are on the widely copied '
      'nineteen-county list and neither qualifies: 2021 Pub. Ch. 182 froze the '
      'threshold at the 2010 census, where Putnam was 72,321 and Greene 68,831';
  END IF;
  RAISE NOTICE '  ok      all seventeen URLTA counties, and not the one that just missed';

  -- This pack introduces the first county name shared by two states: Hamilton
  -- County is in Ohio and in Tennessee. Anything that looks a county up by
  -- name alone now has two answers, so pin that they are distinct rows under
  -- distinct parents before something starts resolving by name.
  SELECT count(*) INTO hamiltons FROM jurisdictions WHERE name = 'Hamilton County';
  IF hamiltons <> 2 THEN
    RAISE EXCEPTION 'expected Hamilton County in two states, found %', hamiltons;
  END IF;
  IF (SELECT count(DISTINCT state) FROM jurisdictions WHERE name = 'Hamilton County') <> 2 THEN
    RAISE EXCEPTION 'the two Hamilton Counties are not in two states';
  END IF;
  IF (SELECT j.state FROM jurisdiction_chain(
        (SELECT id FROM jurisdictions WHERE name = 'Cincinnati' AND level = 'municipality')) c
      JOIN jurisdictions j ON j.id = c.jurisdiction_id
      WHERE j.level = 'county') <> 'OH' THEN
    RAISE EXCEPTION 'Cincinnati resolved through the wrong Hamilton County';
  END IF;
  RAISE NOTICE '  ok      two Hamilton Counties, and the chain still tells them apart';

  urlta_notice := (
    SELECT r.value_numeric
    FROM jurisdiction_chain(
      (SELECT id FROM jurisdictions WHERE name = 'Nashville' AND level = 'municipality')) c
    JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
    WHERE r.code = 'urlta.notice.nonpayment_days' AND r.superseded_by IS NULL
    ORDER BY c.depth ASC LIMIT 1);
  IF urlta_notice IS DISTINCT FROM 14::NUMERIC THEN
    RAISE EXCEPTION 'Tennessee URLTA nonpayment notice is %, expected 14', urlta_notice;
  END IF;
  -- Nothing act-dependent may sit on the STATE row. The two regimes disagree
  -- and TCA 66-7-109(g) disclaims itself in the covered counties, so a
  -- statewide number would be wrong for one side or the other; a property
  -- this system cannot place in a county must get a gap, not a guess.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Tennessee' AND j.level = 'state'
      AND (r.code LIKE 'urlta.%' OR r.code LIKE 'eviction.%'
           OR r.code LIKE 'deposit.return%' OR r.code = 'rent.grace_period_days')
  ) THEN
    RAISE EXCEPTION 'an act-dependent rule sits on the Tennessee STATE row; a '
      'property that cannot be placed in a county would inherit a statute that '
      'may not reach it';
  END IF;
  -- But the state must still say HOW to choose, or the gap is anonymous.
  IF (pg_temp.tn_rule('Tennessee', 'ltl.applies_by')).value_text
     NOT LIKE 'county_population;%' THEN
    RAISE EXCEPTION 'Tennessee does not say what decides which act applies';
  END IF;
  RAISE NOTICE '  ok      the counties carry the numbers, the state carries the choice';

  -- "No interest is owed" and "no deadline exists" are FINDINGS. Ohio says
  -- interest is owed, Tennessee says it is not, and neither is silence —
  -- that distinction is what lets the deposit panel tell an owner nothing is
  -- owed rather than nothing is known.
  interest := (pg_temp.tn_rule('Tennessee', 'deposit.interest_required')).value_text;
  oh_interest := (pg_temp.tn_rule('Ohio', 'deposit.interest_required')).value_text;
  IF interest NOT LIKE 'false;%' OR oh_interest NOT LIKE 'true;%' THEN
    RAISE EXCEPTION 'deposit interest: TN=%, OH=% — expected a stated false and true',
      interest, oh_interest;
  END IF;
  absent := pg_temp.tn_resolve('Nashville', 'deposit.return_deadline_exists');
  IF absent IS NULL OR absent NOT LIKE 'false;%' THEN
    RAISE EXCEPTION 'Tennessee does not state that it fixes no return deadline';
  END IF;
  -- And it must not ALSO carry a return period: the widely repeated "thirty
  -- days" belongs to the later-discovered-damage window, not to a duty to pay.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TN' AND r.code = 'deposit.return_days'
  ) THEN
    RAISE EXCEPTION 'a Tennessee deposit.return_days rule exists; no statute fixes one';
  END IF;
  RAISE NOTICE '  ok      no interest and no return deadline, both stated rather than missing';

  -- Every rule this pack seeds carries an authority. A rule without one is
  -- an opinion, and the NOT NULL alone would let an empty string through.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TN' AND btrim(r.citation) = ''
  ) THEN
    RAISE EXCEPTION 'a Tennessee rule carries an empty citation';
  END IF;
  -- Citations spell the section out. The section sign does not survive every
  -- terminal, log and PDF this text passes through, and a citation that
  -- arrives mangled is a citation nobody can follow.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TN' AND (r.citation LIKE '%' || chr(167) || '%'
                              OR r.value_text LIKE '%' || chr(167) || '%')
  ) THEN
    RAISE EXCEPTION 'a Tennessee citation uses the section sign; spell it s.NN';
  END IF;
  RAISE NOTICE '  ok      every Tennessee rule cites its authority, spelled out';
END $$;
