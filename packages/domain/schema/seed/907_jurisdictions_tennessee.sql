-- ===========================================================================
--  Seed — Tennessee: the third state, and the honest test of ADR 0003.
--
--  Kentucky and Ohio were built together; a third state is where "states are
--  data" either holds or does not. Tennessee was chosen because it disagrees
--  with both in ways that are structural rather than cosmetic:
--
--    * NO individual income tax at all. The Hall tax on interest and
--      dividends was repealed outright, not suspended, so an individual
--      owner has no second depreciation schedule to keep. Kentucky freezes
--      2001 federal law and Ohio adds back two thirds; Tennessee asks
--      nothing. "This state has no such rule" is a finding, and it is seeded
--      as one rather than left as silence.
--    * A CLASSIFIED assessment ratio — 25% residential, 40% commercial —
--      against Kentucky's flat 100% and Ohio's flat 35%. Which class a
--      rented house falls in is the whole question, and TCA 67-5-501(11)
--      answers it by RENTAL UNIT COUNT: not more than one rental unit is
--      residential, so a rented single-family house is 25% and a fully
--      rented duplex is 40%.
--    * A landlord-tenant act that binds by COUNTY POPULATION rather than by
--      local adoption (Kentucky) or statewide fiat (Ohio). Because the
--      county is what decides, every rule that rides on the act is seeded on
--      the COUNTY rows and the non-URLTA law is seeded on the STATE row —
--      so a property in an unseeded Tennessee county resolves to the law
--      that actually governs it instead of borrowing Nashville's.
--    * A summer appeal window against Kentucky's spring and Ohio's winter,
--      and a county inside it that convenes a month early.
--
--  UUID block a0000000-0047-… (Tennessee FIPS 47, per seed/README.md).
--  Figures not yet professionally confirmed say so in their citations.
-- ===========================================================================

INSERT INTO jurisdictions (id, level, name, state, parent_id, fips_code) VALUES
  ('a0000000-0047-4000-8000-000000000010', 'state',        'Tennessee', 'TN', 'a0000000-0000-4000-8000-000000000001', '47'),
  ('a0000000-0047-4000-8000-000000000021', 'county',       'Davidson County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47037'),
  ('a0000000-0047-4000-8000-000000000022', 'county',       'Shelby County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47157'),
  -- Nashville and Davidson County are one consolidated metropolitan
  -- government. It is still modelled as a municipality beneath its county:
  -- the chain is what resolution walks, and collapsing two levels for one
  -- city would make Nashville the only place in the country whose property
  -- resolves at a different depth than everywhere else.
  ('a0000000-0047-4000-8000-000000000101', 'municipality', 'Nashville', 'TN', 'a0000000-0047-4000-8000-000000000021', '4752006'),
  ('a0000000-0047-4000-8000-000000000102', 'municipality', 'Memphis', 'TN', 'a0000000-0047-4000-8000-000000000022', '4748000');

-- The other fifteen counties the landlord-tenant act reaches. They carry no
-- municipalities yet — nobody owns there — but they must exist, because the
-- act binds by COUNTY and a county that is missing from this table is a
-- county whose landlord gets told the law of a chapter that disclaims him.
--
-- Populations are the as-enumerated 2010 figures. TCA 1-3-116(a)(8) makes the
-- 2010 CPH-1-44 publication controlling and says the figures "shall not be
-- affected by subsequent revisions by the Census Bureau", which decides
-- Anderson County: 75,129 as enumerated, 75,082 in the Bureau's later
-- estimates base, and the statute reads the first. It clears the threshold by
-- 129 people.
INSERT INTO jurisdictions (id, level, name, state, parent_id, fips_code) VALUES
  ('a0000000-0047-4000-8000-000000000023', 'county', 'Anderson County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47001'),  -- 2010: 75,129
  ('a0000000-0047-4000-8000-000000000024', 'county', 'Blount County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47009'),  -- 2010: 123,010
  ('a0000000-0047-4000-8000-000000000025', 'county', 'Bradley County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47011'),  -- 2010: 98,963
  ('a0000000-0047-4000-8000-000000000026', 'county', 'Hamilton County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47065'),  -- 2010: 336,463
  ('a0000000-0047-4000-8000-000000000027', 'county', 'Knox County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47093'),  -- 2010: 432,226
  ('a0000000-0047-4000-8000-000000000028', 'county', 'Madison County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47113'),  -- 2010: 98,294
  ('a0000000-0047-4000-8000-000000000029', 'county', 'Maury County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47119'),  -- 2010: 80,956
  ('a0000000-0047-4000-8000-000000000030', 'county', 'Montgomery County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47125'),  -- 2010: 172,331
  ('a0000000-0047-4000-8000-000000000031', 'county', 'Rutherford County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47149'),  -- 2010: 262,604
  ('a0000000-0047-4000-8000-000000000032', 'county', 'Sevier County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47155'),  -- 2010: 89,889
  ('a0000000-0047-4000-8000-000000000033', 'county', 'Sullivan County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47163'),  -- 2010: 156,823
  ('a0000000-0047-4000-8000-000000000034', 'county', 'Sumner County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47165'),  -- 2010: 160,645
  ('a0000000-0047-4000-8000-000000000035', 'county', 'Washington County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47179'),  -- 2010: 122,979
  ('a0000000-0047-4000-8000-000000000036', 'county', 'Williamson County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47187'),  -- 2010: 183,182
  ('a0000000-0047-4000-8000-000000000037', 'county', 'Wilson County', 'TN', 'a0000000-0047-4000-8000-000000000010', '47189');  -- 2010: 113,993

-- ---------------------------------------------------------------------------
-- Property tax: the deadline no function can compute.
--
-- This is the fact that earned Tennessee its place as the third state. The
-- county board of equalization CONVENES on a statutory date -- June 1 under
-- TCA 67-1-404(a), early May in Shelby under 67-1-404(c) -- but it ADJOURNS
-- when it chooses, and adjournment is the deadline: TCA 67-5-1401 makes
-- failure to appear before final adjournment a waiver, after which the
-- assessor's value is conclusive. TCA 67-1-404(b) caps the session at
-- 6/10/15/up-to-30 days by county population and sets NO minimum, the county
-- legislative body fixes the length for every county over 35,000, and the
-- county mayor may extend it. The Comptroller's own handbook notes a board
-- can adjourn after a single day.
--
-- So the operative date is administrative, it differs by county, and it moves
-- every year: Davidson was June 14 in 2024, June 27 in 2025, June 26 in 2026.
-- The Comptroller publishes no consolidated list; each assessor publishes its
-- own. A builder here could only produce a confident wrong answer, and wrong
-- in the fatal direction -- August 1 (the SECOND-level State Board deadline
-- under TCA 67-5-1412(e)) is 36 days past Davidson's 2026 date, by which time
-- the appeal is waived. Tennessee therefore names NO calendar key. It carries
-- the dates its counties published, and where none is loaded the sweep says
-- so rather than computing one.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  -- The state-level rule that turns an absent date into a NAMED gap instead
  -- of an anonymous one: it tells the reader where the date actually lives.
  ('a0000000-0047-4000-8000-000000000010', 'assessment_appeal', 'appeal.window.source',
   NULL, 'published_by_county; the county board convenes on a statutory date but '
   'adjourns on one the county fixes administratively and revises each year, and '
   'adjournment is the deadline. Confirm the year''s date with the county assessor '
   'of property.',
   'TCA 67-1-404(a) (convening); TCA 67-1-404(b) (session length, no minimum); '
   'TCA 67-5-1401 (failure to appear before adjournment waives the objection)',
   DATE '1973-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'assessment_appeal', 'appeal.form',
   NULL, 'Appeal to the county board of equalization; from its action, appeal '
   'to the State Board of Equalization on the State Board''s form',
   'TCA 67-5-1407; TCA 67-5-1412 — CONFIRM WITH TN COUNSEL', DATE '1973-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'assessment_appeal', 'appeal.conference_required',
   NULL, 'false; an informal review with the assessor is available but is not a '
   'prerequisite to the county board',
   'TCA 67-5-1407 — CONFIRM WITH TN COUNSEL', DATE '1973-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'assessment_appeal', 'appeal.instructions',
   NULL, 'File with the COUNTY board of equalization on or before it adjourns — '
   'that is the date that matters, it is set by the county, and it moves each '
   'year. Appealing to the county board is a prerequisite (TCA 67-5-1412(b)(1)) '
   'unless the assessor never sent notice of the increase or reclassification. '
   'August 1 is the SECOND-level deadline, for appealing the county board''s '
   'action to the State Board of Equalization — it is not the date to file.',
   'TCA 67-5-1412(b)(1); TCA 67-5-1412(e)', DATE '1973-01-01'),
  -- Recorded so the pack does not imply the county board is the only way in.
  ('a0000000-0047-4000-8000-000000000010', 'assessment_appeal', 'appeal.direct_to_state_days',
   45, 'where notice of a change was sent later than ten days before the local '
   'board adjourned, the taxpayer may appeal directly to the State Board within '
   '45 days of the notice; where no notice was sent, within 45 days of the tax '
   'billing date. On a showing of reasonable cause the State Board may accept a '
   'late appeal up to March 1 of the following year — a contested safety valve, '
   'not a deadline to rely on.',
   'TCA 67-5-1412(e)', DATE '1973-01-01');

-- The dates themselves, one county and one year at a time, each from the
-- county that published it. The opens/closes pair is matched on
-- effective_from, which is what makes two rows one window.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from, effective_to) VALUES
  ('a0000000-0047-4000-8000-000000000021', 'assessment_appeal', 'appeal.window.opens_on',
   NULL, '2026-05-26',
   'Metropolitan Board of Equalization, tax year 2026: scheduling opens May 26, '
   '2026 (Assessor of Property, Davidson County)', DATE '2026-01-01', DATE '2027-01-01'),
  ('a0000000-0047-4000-8000-000000000021', 'assessment_appeal', 'appeal.window.closes_on',
   NULL, '2026-06-26',
   'Metropolitan Board of Equalization, tax year 2026: appointments must be '
   'scheduled by June 26, 2026 at 4:00 p.m. (Assessor of Property, Davidson '
   'County) — CONFIRM ANNUALLY, this date moves every year',
   DATE '2026-01-01', DATE '2027-01-01'),
  ('a0000000-0047-4000-8000-000000000022', 'assessment_appeal', 'appeal.window.opens_on',
   NULL, '2026-05-01',
   'Shelby County Board of Equalization, tax year 2026: accepting appeals from '
   'May 1, 2026', DATE '2026-01-01', DATE '2027-01-01'),
  ('a0000000-0047-4000-8000-000000000022', 'assessment_appeal', 'appeal.window.closes_on',
   NULL, '2026-06-30',
   'Shelby County Board of Equalization, tax year 2026 real property petition: '
   'appeal deadline June 30, 2026 — CONFIRM ANNUALLY, this date moves every year',
   DATE '2026-01-01', DATE '2027-01-01');

-- ---------------------------------------------------------------------------
-- Assessment ratio: CLASSIFIED, unlike Kentucky's flat 100% or Ohio's 35%.
--
-- The dividing line is the number of RENTAL units, not owner-occupancy: a
-- house rented to one tenant is residential at 25%, and a duplex with both
-- halves rented is commercial at 40%. Both rows are seeded, because a pack
-- carrying only the ratio its author needed would mis-assess the first
-- duplex silently.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0047-4000-8000-000000000010', 'assessment_ratio', 'assessment.ratio',
   0.25, 'residential — real property used or held for use for dwelling purposes '
   'containing not more than one rental unit',
   'TCA 67-5-801(a); TCA 67-5-501(11); Tenn. Const. art. II, s.28', DATE '1973-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'assessment_ratio', 'assessment.ratio.commercial',
   0.40, 'industrial and commercial — including dwelling property containing two '
   'or more rental units',
   'TCA 67-5-801(a); TCA 67-5-501(4); Tenn. Const. art. II, s.28', DATE '1973-01-01'),
  -- The caveat travels with the ratio. Without it the platform would tell a
  -- build-to-rent owner 25% with a confidence the law does not support.
  ('a0000000-0047-4000-8000-000000000010', 'assessment_ratio', 'assessment.ratio.caveat',
   NULL, 'No bright-line rule. Separately parceled single-family homes owned and '
   'managed as one rental enterprise may be classified commercial on all the facts '
   'and circumstances; the assessor weighs them case by case.',
   'Tenn. Att''y Gen. Op. 25-016 (issued 2025-08-25); Spring Hill, L.P. v. '
   'State Board of Equalization — CONFIRM WITH TN COUNSEL BEFORE RELIANCE',
   DATE '2025-08-25');

-- ---------------------------------------------------------------------------
-- Landlord-tenant: a THIRD adoption shape.
--
-- Kentucky's URLTA binds only where a municipality adopts it; Ohio's chapter
-- 5321 binds statewide with no adoption step; Tennessee's binds in counties
-- above a population threshold, by operation of the statute, with no local
-- choice either way. The threshold reads the 2010 federal census and ONLY
-- the 2010 census — the "or any subsequent census" language is gone, so the
-- covered list is frozen at seventeen counties and does not grow. Davidson
-- and Shelby are both well above it.
--
-- Everything that rides on the act is therefore seeded on the COUNTY rows.
-- A Tennessee property in an unseeded county resolves past them to the state
-- row, where the non-URLTA law lives — which is the law that actually
-- governs it.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0047-4000-8000-000000000010', 'landlord_tenant_act', 'ltl.statewide',
   NULL, 'false; the act binds only counties above the population threshold, by '
   'operation of the statute rather than by local adoption',
   'TCA 66-28-102(a)', DATE '1975-07-01'),
  -- Its own row, from its own date: field preemption arrived in 2021 and an
  -- as_of query before then must not resolve it.
  ('a0000000-0047-4000-8000-000000000010', 'landlord_tenant_act', 'ltl.preempts_local',
   NULL, 'true; where the chapter applies it preempts the field and bars '
   'conflicting local ordinances',
   'TCA 66-28-102(e) (2021 Tenn. Pub. Acts ch. 182)', DATE '2021-07-01');

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_text, citation, effective_from)
SELECT id, 'landlord_tenant_act', 'urlta.adopted', 'true',
       'TCA 66-28-102(a): the chapter applies in counties over 75,000 by the 2010 '
       'federal census (2012 Tenn. Pub. Acts ch. 847). 2021 Tenn. Pub. Acts ch. '
       '182, s.2 deleted "or any subsequent federal census", so the list is FROZEN '
       'at seventeen counties and can no longer grow. TCA 1-3-116(a)(8) makes the '
       'as-enumerated 2010 CPH-1-44 figures controlling, unaffected by later '
       'Census Bureau revision. BEWARE the widely copied nineteen-county list, '
       'including the one on the Attorney General consumer-laws page: it adds '
       'Greene (68,831) and Putnam (72,321) and states the repealed 68,000 '
       'threshold. Putnam passed 75,000 in the 2020 census and is still not '
       'covered. Every county seeded in this pack is one of the seventeen.',
       DATE '2012-04-27'
FROM jurisdictions
WHERE level = 'county' AND state = 'TN';

-- ---------------------------------------------------------------------------
-- Security deposit — TCA 66-28-301, and the seam a third state exposes.
--
-- Tennessee imposes NO fixed statutory deadline to return a deposit. The
-- widely repeated "thirty days" is a secondary-source artifact of subsection
-- (g), which is the window for discovering damage AFTER the tenant leaves,
-- not an obligation to pay. What the statute actually gives is a forfeiture
-- rule and a notification mechanic, and those are what is seeded.
--
-- "No deadline exists" and "no deadline is loaded" must not look alike, so
-- the absence is stated as a rule rather than left to silence.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  -- Statewide: no county in Tennessee owes interest on a deposit.
  ('a0000000-0047-4000-8000-000000000010', 'security_deposit', 'deposit.interest_required',
   NULL, 'false; Tennessee imposes no interest obligation on a residential '
   'security deposit',
   'TCA ch. 66-28 (no interest provision) — CONFIRM WITH TN COUNSEL',
   DATE '1975-07-01');

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from)
SELECT j.id, v.domain::rule_domain, v.code, v.value_numeric, v.value_text, v.citation, v.effective_from
FROM jurisdictions j
CROSS JOIN (VALUES
  ('security_deposit', 'deposit.return_deadline_exists', NULL::NUMERIC,
   'false; the chapter fixes no deadline to return a deposit. What it fixes '
   'instead is a forfeiture, and it is conjunctive: a landlord who BOTH failed '
   'to hold the deposit in a separate account AND failed to give the final '
   'damage listing may retain no part of it. Either failure alone does not '
   'trigger it.',
   'TCA 66-28-301(c) — CONFIRM WITH TN COUNSEL', DATE '1975-07-01'),
  ('security_deposit', 'urlta.deposit.separate_account_required', NULL,
   'true', 'TCA 66-28-301(a); TCA 66-28-301(h) (the tenant must be told where '
   'the account is held, though not its number)', DATE '1975-07-01'),
  ('security_deposit', 'urlta.deposit.itemized_list_required', NULL,
   'true', 'TCA 66-28-301(b)', DATE '1975-07-01'),
  ('security_deposit', 'deposit.inspection_notice_days', 5,
   'the landlord MAY tell the tenant of the right to inspect within five days '
   'of receiving notice to vacate; the statute is permissive, not a duty. Where '
   'notice is given the inspection happens on the vacate day or within four '
   'calendar days after.',
   'TCA 66-28-301(b)', DATE '1975-07-01'),
  ('security_deposit', 'deposit.unclaimed_notification_days', 60,
   'where a refund is due, the landlord sends notice to the last known address; '
   'if the tenant does not respond within sixty days the landlord may remove the '
   'deposit from the account and retain it',
   'TCA 66-28-301(f)', DATE '1975-07-01')
) AS v(domain, code, value_numeric, value_text, citation, effective_from)
WHERE j.level = 'county' AND j.state = 'TN';

-- ---------------------------------------------------------------------------
-- Notice periods. Every one sits on a COUNTY row, because in Tennessee the
-- county is what decides which chapter applies — the same discipline Kentucky
-- uses for its municipal adoptions, reached by a different route.
--
-- Note that the fourteen-day cure / thirty-day termination structure people
-- remember is the NON-URLTA rule (TCA 66-7-109). Under the current chapter 28
-- both legs are fourteen days, with seven for a repeat of the same breach
-- inside six months.
-- ---------------------------------------------------------------------------

-- Deliberately NOT on the state row: the notice periods themselves.
--
-- The two answers differ — fourteen days to cure under TCA 66-28-505(a)(2) in
-- a covered county, against 66-7-109's fourteen-for-listed-causes and
-- thirty-for-everything-else elsewhere — and 66-7-109(g) says in as many
-- words that it does not reach the seventeen. A statewide row would hand one
-- of those answers to every Tennessee property, so the state carries only the
-- RULE FOR CHOOSING and an unplaceable property gets a gap rather than
-- somebody else's statute.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0047-4000-8000-000000000010', 'landlord_tenant_act', 'ltl.applies_by',
   NULL, 'county_population; a Tennessee property must be resolved to its county '
   'before any notice, deposit or eviction period can be answered. In the '
   'seventeen counties over 75,000 by the 2010 census the URLTA (TCA ch. 66-28) '
   'governs; everywhere else TCA 66-7-109 does — fourteen days for rent in '
   'arrears, damage beyond normal wear and tear, or a real and present danger, '
   'and thirty days for every other default.',
   'TCA 66-28-102(a); TCA 66-7-109(a)(1); TCA 66-7-109(b); TCA 66-7-109(g)',
   DATE '2012-04-27');

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from)
SELECT j.id, v.domain::rule_domain, v.code, v.value_numeric, v.value_text, v.citation, v.effective_from
FROM jurisdictions j
CROSS JOIN (VALUES
  ('notice_period', 'urlta.notice.nonpayment_days', 14::NUMERIC,
   'nonpayment is a remediable breach: the agreement terminates if it is not '
   'cured within fourteen days of receipt of the notice',
   'TCA 66-28-505(a)(2)', DATE '2021-07-01'),
  ('notice_period', 'urlta.notice.material_noncompliance_days', 14,
   'fourteen days to cure a remediable breach; for a non-remediable breach the '
   'agreement terminates on a date not less than fourteen days after receipt',
   'TCA 66-28-505(a)(2); TCA 66-28-505(a)(3)', DATE '2021-07-01'),
  ('notice_period', 'urlta.notice.repeat_violation_days', 7,
   'substantially the same breach recurring within six months terminates the '
   'agreement on seven days'' notice, with no right to cure',
   'TCA 66-28-505(a)(2)(B)', DATE '2021-07-01'),
  ('late_fee', 'rent.grace_period_days', 5,
   'no late fee before the fifth day; the fee is capped at ten percent of the '
   'past-due rent, and where day five is a Sunday or legal holiday a payment on '
   'the next business day is not late',
   'TCA 66-28-201', DATE '1975-07-01')
) AS v(domain, code, value_numeric, value_text, citation, effective_from)
WHERE j.level = 'county' AND j.state = 'TN';

-- ---------------------------------------------------------------------------
-- Income tax: the simplest owner-side story in the union, and the reason
-- Tennessee is a good third state.
--
-- There is no individual income tax on wages or rental income, and never was
-- one on earned income; the Hall tax reached only interest and dividends and
-- was repealed for tax years beginning on or after January 1, 2021. But the
-- ENTITY that holds the property still meets the franchise and excise taxes,
-- which is a different question from the owner's own return and is recorded
-- as a different set of rules.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0047-4000-8000-000000000010', 'income_tax', 'income.type',
   NULL, 'none; no individual income tax on wages or on rental income',
   'Tenn. Const. art. II, s.28; the Hall income tax (TCA tit. 67, ch. 2) was '
   'repealed for tax years beginning on or after January 1, 2021 by 2017 Tenn. '
   'Pub. Acts ch. 181, completing the phase-out begun by 2016 Tenn. Pub. Acts '
   'ch. 1064', DATE '2021-01-01'),
  -- The entity-level taxes. An owner-operator holding Tennessee rentals in an
  -- LLC meets these whether or not there is a personal return to file.
  ('a0000000-0047-4000-8000-000000000010', 'income_tax', 'income.entity_excise_rate',
   0.065, 'excise tax on net earnings from business done in Tennessee',
   'TCA 67-4-2007(a); TCA 67-4-2006 (net earnings) — CONFIRM WITH TN CPA',
   DATE '1999-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'income_tax', 'income.entity_franchise_rate',
   0.0025, 'franchise tax at twenty-five cents per hundred dollars of net worth, '
   'apportioned to Tennessee. The former alternative property measure, which used '
   'to set a floor and fell hardest on real-estate entities, was repealed for tax '
   'years ending on or after January 1, 2024; net worth is now the sole base.',
   'TCA 67-4-2106(a); TCA 67-4-2111 (apportionment); 2024 Tenn. Pub. Acts ch. 950 '
   '(repeal of the property measure, formerly TCA 67-4-2108) — CONFIRM WITH TN CPA',
   DATE '2024-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'income_tax', 'income.entity_franchise_minimum',
   100, NULL, 'TCA 67-4-2119 — CONFIRM WITH TN CPA', DATE '1999-01-01'),
  -- The exemption an owner-operator most often qualifies for, and the trap
  -- inside it: "residential" here means four units or fewer, which is NOT the
  -- one-unit line the assessment ratio uses. Two definitions of the same word
  -- in the same code, and the platform must not conflate them.
  ('a0000000-0047-4000-8000-000000000010', 'income_tax', 'income.entity_exemption',
   NULL, 'FONCE — family-owned non-corporate entity. Both conditions must hold: '
   'at least 95 percent of the ownership units are held by members of one family, '
   'and at least two thirds of the entity''s activity produces passive investment '
   'income. Rents from residential property count as passive; COMMERCIAL rents do '
   'not, and "residential" here means property with not more than FOUR residential '
   'units, which is a different line than the assessment ratio''s one-unit test. '
   'The exemption is claimed year by year and must be renewed annually.',
   'TCA 67-4-2008(a)(11); TCA 67-4-2008(a)(11)(B)(iv) (four-unit limit); '
   'TCA 67-4-2008(f) (annual filing) — CONFIRM WITH TN CPA', DATE '1999-01-01');

-- ---------------------------------------------------------------------------
-- Depreciation conformity: nothing to compute on the owner's own return, and
-- that is the answer — not silence. The entity-level excise tax is a
-- different matter and does carry a bonus-depreciation addback, so it is
-- recorded separately rather than folded into a single "conformity" verdict
-- that would be wrong for one reader or the other.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0047-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.conformity_kind',
   NULL, 'none', 'there is no individual income tax to conform: Tenn. Const. art. '
   'II, s.28 and the repeal of the Hall income tax — CONFIRM WITH TN CPA',
   DATE '2021-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.entity_bonus_addback',
   NULL, 'true; for excise-tax purposes IRC s.168 applies as it stood under the '
   'Tax Cuts and Jobs Act of 2017, so bonus depreciation is allowed only at the '
   'TCJA phase-down percentages — 80 percent in 2023, 60 in 2024, 40 in 2025, 20 '
   'in 2026, none from 2027. Federal bonus taken above that percentage is added '
   'back and recovered under MACRS. Assets bought on or before December 31, 2022 '
   'follow the older rule, where Tennessee disallowed bonus outright.',
   'TCA 67-4-2006(a)(12) (2023 Tenn. Pub. Acts ch. 377); TCA 67-4-2006(b)(1)(H) '
   '(pre-2023 addback); TN DOR Notice 25-36 — CONFIRM WITH TN CPA',
   DATE '2023-01-01'),
  ('a0000000-0047-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.s179_addback',
   NULL, 'false; IRC s.179 flows through with its federal treatment and Tennessee '
   'imposes no section 179 addback',
   'TCA 67-4-2006 (no s.179 disallowance); TN DOR guidance ET-8 (a narrow '
   'net-earnings computation edge case, not a disallowance) — CONFIRM WITH TN CPA',
   DATE '1999-01-01');
