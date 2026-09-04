-- ===========================================================================
--  Pack test — Texas (seed/909_jurisdictions_texas.sql).
--
--  The fourth state completes the square: from ONE query shape the four
--  states give four different answers about who sets the appeal deadline —
--  two distinct computed calendars, a published county date, and a third
--  computed calendar that must never collide with the other two. It also
--  pins the facts this pack exists to protect: the cap that repeals itself
--  on schedule, the four-or-fewer boundary the portfolio's own four-plex
--  sits exactly on, the notice that must never anchor the window, and the
--  threshold that silences the franchise TAX but never the FILING.
--  Read-only.
-- ===========================================================================

\set ON_ERROR_STOP on

\echo ''
\echo 'texas pack'

CREATE OR REPLACE FUNCTION pg_temp.tx_resolve(city TEXT, rule_code TEXT)
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

CREATE OR REPLACE FUNCTION pg_temp.tx_rule(state_name TEXT, rule_code TEXT)
RETURNS jurisdiction_rules LANGUAGE sql STABLE AS $fn$
  SELECT r.* FROM jurisdiction_rules r
  JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = state_name AND j.level = 'state'
    AND r.code = rule_code AND r.superseded_by IS NULL
  LIMIT 1;
$fn$;

-- Effective-dated resolution: the rule in force on a given day, or NULL.
CREATE OR REPLACE FUNCTION pg_temp.tx_rule_as_of(rule_code TEXT, on_day DATE)
RETURNS jurisdiction_rules LANGUAGE sql STABLE AS $fn$
  SELECT r.* FROM jurisdiction_rules r
  JOIN jurisdictions j ON j.id = r.jurisdiction_id
  WHERE j.name = 'Texas' AND j.level = 'state'
    AND r.code = rule_code AND r.superseded_by IS NULL
    AND r.effective_from <= on_day
    AND (r.effective_to IS NULL OR r.effective_to > on_day)
  LIMIT 1;
$fn$;

DO $$
DECLARE
  chain_len INT;
  tx_key TEXT;
  keys TEXT[];
  distinct_keys INT;
  offset_tx NUMERIC;
  offset_oh NUMERIC;
  ratio_tx NUMERIC;
  ratio_text TEXT;
  cb_2026 jurisdiction_rules;
  cb_2027 jurisdiction_rules;
  homestead TEXT;
  harbor jurisdiction_rules;
  harbor_over TEXT;
  instructions TEXT;
  deposit_days NUMERIC;
  interest_tx TEXT;
  interest_oh TEXT;
  income_tx TEXT;
  income_tn TEXT;
  cite_tx TEXT;
  cite_tn TEXT;
  pir TEXT;
  threshold_2025 NUMERIC;
  threshold_2026 NUMERIC;
  notice_days NUMERIC;
BEGIN
  -- Dallas -> Dallas County -> Texas -> United States: four levels, the
  -- same depth as every other door in the platform.
  SELECT count(*) INTO chain_len
  FROM jurisdiction_chain(
    (SELECT id FROM jurisdictions WHERE name = 'Dallas' AND level = 'municipality'));
  IF chain_len <> 4 THEN
    RAISE EXCEPTION 'the Dallas chain walks % levels, expected 4', chain_len;
  END IF;
  RAISE NOTICE '  ok      the Dallas chain walks four levels to the federal root';

  -- THE FOUR-SHAPE ASSERT: one query shape, four states, four answers.
  -- Kentucky and Ohio and Texas each name their own computed calendar;
  -- Tennessee names none, because its date is a county's yearly decision.
  tx_key := pg_temp.tx_resolve('Dallas', 'appeal.window.calendar');
  IF tx_key IS DISTINCT FROM 'us-tx.protest-by-may-15' THEN
    RAISE EXCEPTION 'Dallas resolves calendar %, expected us-tx.protest-by-may-15', tx_key;
  END IF;
  keys := ARRAY[
    pg_temp.tx_resolve('Newport', 'appeal.window.calendar'),
    pg_temp.tx_resolve('Cincinnati', 'appeal.window.calendar'),
    pg_temp.tx_resolve('Dallas', 'appeal.window.calendar')
  ];
  SELECT count(DISTINCT k) INTO distinct_keys FROM unnest(keys) AS k;
  IF distinct_keys <> 3 OR array_position(keys, NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'the three computed calendars are not three distinct keys: %', keys;
  END IF;
  IF pg_temp.tx_resolve('Nashville', 'appeal.window.calendar') IS NOT NULL THEN
    RAISE EXCEPTION 'Tennessee has grown a calendar key; the four-shape square is broken';
  END IF;
  RAISE NOTICE '  ok      four states, four answers: three computed keys and one that names none';

  -- The inverse of Tennessee, held in both directions: a computed state
  -- must carry NO published dates, or the sweep would have two truths.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TX'
      AND r.code IN ('appeal.window.opens_on', 'appeal.window.closes_on', 'appeal.window.source')
  ) THEN
    RAISE EXCEPTION 'Texas carries published-shape rows beside its computed calendar';
  END IF;
  RAISE NOTICE '  ok      computed means computed: no published dates ride beside the key';

  -- Same-year contest, and distinct from Ohio's year-behind complaint.
  offset_tx := (pg_temp.tx_rule('Texas', 'appeal.contests_tax_year_offset')).value_numeric;
  offset_oh := (pg_temp.tx_rule('Ohio', 'appeal.contests_tax_year_offset')).value_numeric;
  IF offset_tx IS DISTINCT FROM 0::NUMERIC THEN
    RAISE EXCEPTION 'Texas contests offset is %, expected 0', offset_tx;
  END IF;
  IF offset_oh IS DISTINCT FROM (-1)::NUMERIC THEN
    RAISE EXCEPTION 'the Ohio contrast has moved; this test is stale';
  END IF;
  RAISE NOTICE '  ok      a Texas protest contests its own year; Ohio stays a year behind';

  -- No ratio at all: 100 percent market, and the row says value_basis =
  -- market in as many words, because 3x and 4x silent errors are exactly
  -- what the value_basis discipline exists to prevent.
  ratio_tx := (pg_temp.tx_rule('Texas', 'assessment.ratio')).value_numeric;
  ratio_text := (pg_temp.tx_rule('Texas', 'assessment.ratio')).value_text;
  IF ratio_tx IS DISTINCT FROM 1.00::NUMERIC THEN
    RAISE EXCEPTION 'Texas ratio is %, expected 1.00', ratio_tx;
  END IF;
  IF ratio_text NOT LIKE '%value_basis = market%' THEN
    RAISE EXCEPTION 'the Texas ratio row does not pin value_basis = market';
  END IF;
  IF (SELECT count(DISTINCT r.value_numeric)
      FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
      WHERE j.level = 'state' AND j.name IN ('Ohio', 'Tennessee', 'Texas')
        AND r.code = 'assessment.ratio' AND r.superseded_by IS NULL) <> 3 THEN
    RAISE EXCEPTION 'the OH/TN/TX ratios are not three distinct values';
  END IF;
  RAISE NOTICE '  ok      100 percent market, stated as value_basis = market, distinct from OH and TN';

  -- THE SELF-REPEALING CAP. In force mid-2026; gone mid-2027 — by its own
  -- subsection (k), carried as effective_to. 2027 must NOT inherit it.
  cb_2026 := pg_temp.tx_rule_as_of('exemption.circuit_breaker', DATE '2026-06-01');
  cb_2027 := pg_temp.tx_rule_as_of('exemption.circuit_breaker', DATE '2027-06-01');
  IF cb_2026.value_numeric IS DISTINCT FROM 0.20::NUMERIC THEN
    RAISE EXCEPTION 'the circuit breaker is not in force at 20 percent in mid-2026';
  END IF;
  IF cb_2026.citation NOT LIKE '%23.231(k)%' THEN
    RAISE EXCEPTION 'the circuit breaker does not cite its own sunset';
  END IF;
  IF cb_2027.id IS NOT NULL THEN
    RAISE EXCEPTION 'the circuit breaker survived its statutory expiry: tax year '
      '2027 silently inherited a cap the legislature let die on 2026-12-31';
  END IF;
  -- And the better-known cap is recorded as INAPPLICABLE, not left silent.
  homestead := (pg_temp.tx_rule('Texas', 'exemption.homestead_cap')).value_text;
  IF homestead IS NULL OR homestead NOT LIKE 'inapplicable%' THEN
    RAISE EXCEPTION 'the homestead cap is not recorded as inapplicable to rentals: %', homestead;
  END IF;
  RAISE NOTICE '  ok      the circuit breaker dies on schedule and the homestead cap never applied';

  -- THE FOUR-PLEX BOUNDARY. The 12 percent harbor reads "four or fewer";
  -- flipping the inequality mis-prices the fee on the portfolio's own
  -- building, so the direction is pinned in text, twice.
  harbor := pg_temp.tx_rule('Texas', 'latefee.safe_harbor_percent');
  IF harbor.value_numeric IS DISTINCT FROM 0.12::NUMERIC THEN
    RAISE EXCEPTION 'the Texas late-fee safe harbor is %, expected 0.12', harbor.value_numeric;
  END IF;
  IF harbor.value_text NOT LIKE '%FOUR OR FEWER%'
     OR harbor.value_text NOT LIKE '%QUALIFIES%' THEN
    RAISE EXCEPTION 'the four-or-fewer boundary direction is not pinned: %', harbor.value_text;
  END IF;
  harbor_over := (pg_temp.tx_rule('Texas', 'latefee.safe_harbor_percent.over_four')).value_text;
  IF harbor_over IS NULL OR harbor_over NOT LIKE '%MORE than four%' THEN
    RAISE EXCEPTION 'the over-four harbor is missing or unlabeled';
  END IF;
  -- The fee itself is the lease's: a statewide latefee.amount or
  -- latefee.percent would invent a fee no statute sets, and the rent sweep
  -- must keep reporting its honest gap until the lease figure is entered.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TX' AND r.code IN ('latefee.amount', 'latefee.percent')
  ) THEN
    RAISE EXCEPTION 'a Texas latefee.amount/percent rule exists; s.92.019 sets '
      'bounds, never the fee';
  END IF;
  RAISE NOTICE '  ok      12 percent at four-or-fewer units, 10 above, and no invented fee';

  -- THE NOTICE THAT MUST NOT ANCHOR THE WINDOW. The instructions must say,
  -- in as many words, that May 15 holds with no notice in hand.
  instructions := (pg_temp.tx_rule('Texas', 'appeal.instructions')).value_text;
  IF instructions IS NULL
     OR instructions NOT LIKE '%even if no appraisal notice has arrived%'
     OR instructions NOT LIKE '%never assumed%' THEN
    RAISE EXCEPTION 'the instructions do not warn against anchoring to the notice: %',
      instructions;
  END IF;
  RAISE NOTICE '  ok      the window holds without a notice, and the pack says so out loud';

  -- Deposit: thirty days like Ohio, but each from its own statute — and no
  -- interest, where Ohio owes it. Sameness must be two citations, never one.
  deposit_days := (pg_temp.tx_rule('Texas', 'deposit.return_days')).value_numeric;
  IF deposit_days IS DISTINCT FROM 30::NUMERIC THEN
    RAISE EXCEPTION 'Texas deposit return is % days, expected 30', deposit_days;
  END IF;
  IF (pg_temp.tx_rule('Texas', 'deposit.return_days')).citation NOT LIKE '%92.103%'
     OR (pg_temp.tx_rule('Ohio', 'deposit.return_days')).citation NOT LIKE '%5321.16%' THEN
    RAISE EXCEPTION 'the TX and OH thirty-day rules do not each cite their own statute';
  END IF;
  interest_tx := (pg_temp.tx_rule('Texas', 'deposit.interest_required')).value_text;
  interest_oh := (pg_temp.tx_rule('Ohio', 'deposit.interest_required')).value_text;
  IF interest_tx NOT LIKE 'false;%' OR interest_oh NOT LIKE 'true;%' THEN
    RAISE EXCEPTION 'deposit interest: TX=%, OH=% — expected a stated false and true',
      interest_tx, interest_oh;
  END IF;
  RAISE NOTICE '  ok      thirty days by two different statutes, and no interest where Ohio owes it';

  -- Notice to vacate: three days, lease-variable, on the state row — the
  -- statewide shape, unlike Tennessee where nothing act-dependent may sit
  -- at state level.
  notice_days := (pg_temp.tx_rule('Texas', 'eviction.notice_days')).value_numeric;
  IF notice_days IS DISTINCT FROM 3::NUMERIC THEN
    RAISE EXCEPTION 'Texas notice to vacate is %, expected 3', notice_days;
  END IF;
  RAISE NOTICE '  ok      three days to vacate, statewide, on the state row where it belongs';

  -- Two states say "none" to income tax by two different routes: Tennessee
  -- by repeal, Texas by constitution. Agreement is honest only when the
  -- citations cannot be swapped.
  income_tx := (pg_temp.tx_rule('Texas', 'income.type')).value_text;
  income_tn := (pg_temp.tx_rule('Tennessee', 'income.type')).value_text;
  IF income_tx NOT LIKE 'none;%' OR income_tn NOT LIKE 'none;%' THEN
    RAISE EXCEPTION 'income.type: TX=%, TN=% — expected two stated nones', income_tx, income_tn;
  END IF;
  cite_tx := (pg_temp.tx_rule('Texas', 'income.type')).citation;
  cite_tn := (pg_temp.tx_rule('Tennessee', 'income.type')).citation;
  IF cite_tx NOT LIKE '%art. VIII%' OR cite_tn NOT LIKE '%Hall%' OR cite_tx = cite_tn THEN
    RAISE EXCEPTION 'the two nones do not each cite their own route: TX=%, TN=%',
      cite_tx, cite_tn;
  END IF;
  RAISE NOTICE '  ok      two nones, two routes: constitution in Texas, repeal in Tennessee';

  -- THE THRESHOLD THAT NEVER SILENCES THE FILING. The indexed figures are
  -- effective-dated, and the PIR row says REGARDLESS in as many words.
  threshold_2025 := (pg_temp.tx_rule_as_of('income.entity_no_tax_due_threshold',
    DATE '2025-06-01')).value_numeric;
  threshold_2026 := (pg_temp.tx_rule_as_of('income.entity_no_tax_due_threshold',
    DATE '2026-06-01')).value_numeric;
  IF threshold_2025 IS DISTINCT FROM 2470000::NUMERIC
     OR threshold_2026 IS DISTINCT FROM 2650000::NUMERIC THEN
    RAISE EXCEPTION 'the no-tax-due thresholds did not resolve by year: 2025=%, 2026=%',
      threshold_2025, threshold_2026;
  END IF;
  pir := (pg_temp.tx_rule('Texas', 'income.entity_information_report')).value_text;
  IF pir IS NULL OR pir NOT LIKE '%REGARDLESS%' OR pir NOT LIKE '%personally liable%' THEN
    RAISE EXCEPTION 'the PIR row does not carry the under-threshold trap: %', pir;
  END IF;
  RAISE NOTICE '  ok      the threshold indexes by year and the PIR survives it, liability named';

  -- Registration reaches the four-plex only INSIDE Dallas city limits: the
  -- municipality carries the program, and the county and state carry none,
  -- so a suburb resolves past it instead of inheriting Dallas fees.
  IF pg_temp.tx_resolve('Dallas', 'registration.rental_program.multi_tenant') IS NULL THEN
    RAISE EXCEPTION 'the Dallas multi-tenant registration program is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TX' AND j.level IN ('state', 'county')
      AND r.code LIKE 'registration.rental_program%'
  ) THEN
    RAISE EXCEPTION 'a Dallas registration program leaked above the municipality';
  END IF;
  RAISE NOTICE '  ok      registration lives on the city row and nowhere above it';

  -- The conference answer is false in BOTH statutory eras, each era citing
  -- its own law: before 2022 ch. 41 had no conference provision at all;
  -- from 2022, s.41.445 grants a right the owner triggers, never a gate.
  -- The refutation pass caught the first cut citing s.41.445 four years
  -- before HB 988 enacted it; this pins the repaired two-leg answer.
  IF (pg_temp.tx_rule_as_of('appeal.conference_required', DATE '2021-06-01')).citation
     NOT LIKE '%no conference provision%' THEN
    RAISE EXCEPTION 'the pre-2022 conference leg does not cite the absence';
  END IF;
  IF (pg_temp.tx_rule_as_of('appeal.conference_required', DATE '2026-06-01')).citation
     NOT LIKE '%41.445%' THEN
    RAISE EXCEPTION 'the post-2022 conference leg does not cite s.41.445';
  END IF;
  IF (pg_temp.tx_rule_as_of('appeal.conference_required', DATE '2021-06-01')).value_text
       NOT LIKE 'false;%'
     OR (pg_temp.tx_rule_as_of('appeal.conference_required', DATE '2026-06-01')).value_text
       NOT LIKE 'false;%' THEN
    RAISE EXCEPTION 'a conference era answers other than a stated false';
  END IF;
  -- And the constitutional ban is quoted as the flat prohibition it is —
  -- not the pre-2019 voter-approval regime it replaced.
  IF (pg_temp.tx_rule('Texas', 'income.type')).value_text
     NOT LIKE '%may not impose a tax on the net incomes of individuals%' THEN
    RAISE EXCEPTION 'income.type does not quote the s.24-a flat ban';
  END IF;
  RAISE NOTICE '  ok      two conference eras, both false by their own law, and the ban quoted flat';

  -- Citation hygiene, the same two gates every pack passes.
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TX' AND btrim(r.citation) = ''
  ) THEN
    RAISE EXCEPTION 'a Texas rule carries an empty citation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jurisdiction_rules r JOIN jurisdictions j ON j.id = r.jurisdiction_id
    WHERE j.state = 'TX' AND (r.citation LIKE '%' || chr(167) || '%'
                              OR r.value_text LIKE '%' || chr(167) || '%')
  ) THEN
    RAISE EXCEPTION 'a Texas citation uses the section sign; spell it s.NN';
  END IF;
  RAISE NOTICE '  ok      every Texas rule cites its authority, spelled out';
END $$;
