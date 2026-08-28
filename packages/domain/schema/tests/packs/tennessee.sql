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
  memphis_key TEXT;
  ky_key TEXT;
  oh_key TEXT;
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
  non_urlta_notice NUMERIC;
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

  -- THE THREE-REGIME ASSERT: one query shape, three states, no collisions.
  tn_key := pg_temp.tn_resolve('Nashville', 'appeal.window.calendar');
  ky_key := pg_temp.tn_resolve('Newport', 'appeal.window.calendar');
  oh_key := pg_temp.tn_resolve('Cincinnati', 'appeal.window.calendar');
  IF tn_key IS DISTINCT FROM 'us-tn.county-board' THEN
    RAISE EXCEPTION 'Nashville resolves %, expected us-tn.county-board', tn_key;
  END IF;
  IF ky_key = oh_key OR oh_key = tn_key OR ky_key = tn_key THEN
    RAISE EXCEPTION 'three-regime resolution collapsed: KY=%, OH=%, TN=%',
      ky_key, oh_key, tn_key;
  END IF;
  RAISE NOTICE '  ok      three states, three calendars: %, %, %', ky_key, oh_key, tn_key;

  -- THE COUNTY OVERRIDE, which no earlier pack needed: Shelby convenes a
  -- month before the rest of Tennessee, so the county row wins over its own
  -- state's. Nothing in the resolver changed to allow it — depth-first
  -- ordering already prefers the nearer row, and this proves it.
  memphis_key := pg_temp.tn_resolve('Memphis', 'appeal.window.calendar');
  IF memphis_key IS DISTINCT FROM 'us-tn.shelby-county-board' THEN
    RAISE EXCEPTION 'Memphis resolves %, expected the Shelby County override',
      memphis_key;
  END IF;
  IF memphis_key = tn_key THEN
    RAISE EXCEPTION 'the Shelby override collapsed into the state calendar';
  END IF;
  RAISE NOTICE '  ok      a county overrides its own state calendar: Shelby sits May 1';

  -- Every registry key a pack names must be shaped like one. A typo here is
  -- a silent coverage gap at sweep time, not an error.
  IF tn_key !~ '^us-[a-z]{2}\.[a-z0-9-]+$' OR memphis_key !~ '^us-[a-z]{2}\.[a-z0-9-]+$' THEN
    RAISE EXCEPTION 'a Tennessee calendar key is not a registry key: %, %',
      tn_key, memphis_key;
  END IF;
  RAISE NOTICE '  ok      both calendar keys are well formed';

  -- Classified assessment. The line is RENTAL UNIT COUNT, not occupancy:
  -- one rental unit is residential at 25%, two or more is commercial at 40%.
  ratio := (pg_temp.tn_rule('Tennessee', 'assessment.ratio')).value_numeric;
  oh_ratio := (pg_temp.tn_rule('Ohio', 'assessment.ratio')).value_numeric;
  IF ratio IS DISTINCT FROM 0.25::NUMERIC OR ratio = oh_ratio THEN
    RAISE EXCEPTION 'Tennessee residential ratio is % (Ohio %), expected 0.25 and distinct',
      ratio, oh_ratio;
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
  -- live. A Tennessee property in an unseeded county must resolve PAST them
  -- to the non-URLTA statute, which is the law that actually governs it.
  urlta_notice := (
    SELECT r.value_numeric
    FROM jurisdiction_chain(
      (SELECT id FROM jurisdictions WHERE name = 'Nashville' AND level = 'municipality')) c
    JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
    WHERE r.code = 'urlta.notice.nonpayment_days' AND r.superseded_by IS NULL
    ORDER BY c.depth ASC LIMIT 1);
  non_urlta_notice := (pg_temp.tn_rule('Tennessee', 'eviction.other_default_days')).value_numeric;
  IF urlta_notice IS DISTINCT FROM 14::NUMERIC OR non_urlta_notice IS DISTINCT FROM 30::NUMERIC THEN
    RAISE EXCEPTION 'Tennessee notice periods drifted: URLTA %, non-URLTA other %',
      urlta_notice, non_urlta_notice;
  END IF;
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Tennessee' AND r.code LIKE 'urlta.%'
  ) THEN
    RAISE EXCEPTION 'a URLTA rule is seeded on the Tennessee STATE row; a property '
      'in a county below the population threshold would inherit law that does not '
      'reach it';
  END IF;
  RAISE NOTICE '  ok      URLTA rules sit on the counties, non-URLTA law on the state';

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
