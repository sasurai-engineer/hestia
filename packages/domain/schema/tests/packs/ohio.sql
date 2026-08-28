-- ===========================================================================
--  Pack test — Ohio (seed/902_jurisdictions_ohio.sql).
--
--  The cross-river proof: from the same query shapes, a Cincinnati chain and
--  a Newport chain must resolve to DIFFERENT calendars, ratios, conformity
--  regimes and citations. Read-only.
-- ===========================================================================

\set ON_ERROR_STOP on

\echo ''
\echo 'ohio pack'

DO $$
DECLARE
  chain_len INT;
  calendar_key TEXT;
  ratio NUMERIC;
  conformity TEXT;
  addback TEXT;
  recovery NUMERIC;
  ky_key TEXT;
  ky_citation TEXT;
  oh_citation TEXT;
  municipal NUMERIC;
BEGIN
  -- Cincinnati -> Hamilton County -> Ohio -> United States.
  SELECT count(*) INTO chain_len
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Cincinnati' AND level = 'municipality'));
  IF chain_len <> 4 THEN
    RAISE EXCEPTION 'Cincinnati chain wrong: % rows', chain_len;
  END IF;
  RAISE NOTICE '  ok      the Cincinnati chain walks four levels to the federal root';

  -- The state-uniform BOR window resolves through the chain.
  SELECT r.value_text, r.citation INTO calendar_key, oh_citation
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Cincinnati' AND level = 'municipality')) c
  JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
  WHERE r.code = 'appeal.window.calendar' AND r.superseded_by IS NULL
  ORDER BY c.depth ASC, r.effective_from DESC
  LIMIT 1;
  IF calendar_key IS DISTINCT FROM 'us-oh.bor-complaint' THEN
    RAISE EXCEPTION 'Cincinnati appeal calendar resolves to %, expected us-oh.bor-complaint',
      calendar_key;
  END IF;
  RAISE NOTICE '  ok      Cincinnati resolves the BOR complaint calendar';

  -- 35 percent of true value, the fractional-assessment fact.
  SELECT r.value_numeric INTO ratio
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Ohio' AND r.code = 'assessment.ratio' AND r.superseded_by IS NULL;
  IF ratio IS DISTINCT FROM 0.35::NUMERIC THEN
    RAISE EXCEPTION 'Ohio assessment ratio is %, expected 0.35', ratio;
  END IF;
  RAISE NOTICE '  ok      Ohio assesses at 35 percent of true value';

  -- The addback-recovery conformity profile, pinned to the engine fixtures.
  SELECT r.value_text INTO conformity
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Ohio' AND r.code = 'depreciation.conformity_kind' AND r.superseded_by IS NULL;
  SELECT r.value_text INTO addback
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Ohio' AND r.code = 'depreciation.addback_fraction' AND r.superseded_by IS NULL;
  SELECT r.value_numeric INTO recovery
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Ohio' AND r.code = 'depreciation.recovery_years' AND r.superseded_by IS NULL;
  IF conformity IS DISTINCT FROM 'addback_recovery' OR addback IS DISTINCT FROM '2/3'
     OR recovery IS DISTINCT FROM 6::NUMERIC THEN
    RAISE EXCEPTION 'Ohio conformity drifted: kind=%, fraction=%, years=%',
      conformity, addback, recovery;
  END IF;
  RAISE NOTICE '  ok      addback-recovery conformity: 2/3 over six years';

  -- The statewide landlord-tenant act needs no adoption row per municipality.
  IF NOT EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.name = 'Ohio' AND r.code = 'ltl.statewide' AND r.value_text = 'true'
  ) THEN
    RAISE EXCEPTION 'the statewide ORC ch. 5321 row is missing';
  END IF;
  RAISE NOTICE '  ok      ORC ch. 5321 applies statewide, no adoption map needed';

  -- THE CROSS-RIVER ASSERT: one query shape, two different regimes.
  SELECT r.value_text, r.citation INTO ky_key, ky_citation
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Newport' AND level = 'municipality')) c
  JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
  WHERE r.code = 'appeal.window.calendar' AND r.superseded_by IS NULL
  ORDER BY c.depth ASC, r.effective_from DESC
  LIMIT 1;
  IF ky_key = calendar_key OR ky_citation = oh_citation THEN
    RAISE EXCEPTION 'cross-river resolution collapsed: KY=% (%), OH=% (%)',
      ky_key, ky_citation, calendar_key, oh_citation;
  END IF;
  IF ky_key IS DISTINCT FROM 'us-ky.open-inspection' THEN
    RAISE EXCEPTION 'Newport resolves %, expected us-ky.open-inspection', ky_key;
  END IF;
  RAISE NOTICE '  ok      one bridge, two regimes: Newport and Cincinnati diverge';

  -- TWO GOVERNMENTS, ONE DOLLAR. Kentucky's chain answers income tax once;
  -- Cincinnati's answers at the city while the state row states no rate at
  -- all. A reader that collapsed the chain to one winner per code — which is
  -- right for an appeal window, where one body governs — would drop whichever
  -- of these lost, so the shape is pinned here rather than only in the API.
  IF (SELECT count(*) FROM jurisdiction_chain(
        (SELECT id FROM jurisdictions WHERE name = 'Cincinnati'
          AND level = 'municipality')) c
      JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
      WHERE r.domain = 'income_tax' AND r.superseded_by IS NULL) < 2 THEN
    RAISE EXCEPTION 'the Cincinnati chain carries fewer than two income_tax rows';
  END IF;
  SELECT r.value_numeric INTO municipal
  FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Cincinnati' AND r.code = 'income.municipal_rate'
    AND r.superseded_by IS NULL;
  IF municipal IS DISTINCT FROM 0.018000::NUMERIC THEN
    RAISE EXCEPTION 'Cincinnati municipal income tax is %, expected 0.018', municipal;
  END IF;
  -- Ohio's own state row states a KIND and no number, on purpose. A reader
  -- that treated it as a rate would be inventing one.
  IF (SELECT r.value_numeric FROM jurisdiction_rules r
      JOIN jurisdictions j ON j.id = r.jurisdiction_id
      WHERE j.name = 'Ohio' AND r.code = 'income.type'
        AND r.superseded_by IS NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'the Ohio income.type row carries a number; it states a kind';
  END IF;
  RAISE NOTICE '  ok      two governments tax one Cincinnati dollar, and only one states a rate';
END $$;
