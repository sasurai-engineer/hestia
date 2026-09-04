-- ===========================================================================
--  Seed — Texas: the fourth state, and half of the actual portfolio.
--
--  Two of the four v1 properties sit in the Dallas area, one of them a
--  rented four-plex, and until this pack existed POST /assessments answered
--  503 for both. Texas was researched with the prediction stated FIRST and
--  scored after (issue #129): predicted COMPUTED shape, confirmed — the
--  protest deadline is a function of the calendar (Tex. Tax Code
--  s.41.44(a)(1): not later than May 15, weekend-rolled by s.1.06), unlike
--  Tennessee, where each county's board adjournment decides.
--
--  What makes Texas structurally different from all three earlier states:
--
--    * NO assessment ratio at all: s.23.01(a) appraises everything at 100
--      percent of market value as of January 1. The notice states APPRAISED
--      (market) value, so an assessment entered from a Texas notice carries
--      value_basis = market — against Ohio's 35 percent and Tennessee's
--      classified 25/40, both of which put TAXABLE value on paper.
--    * The appraisal notice is CONDITIONAL: an unchanged value produces no
--      s.25.19 notice at all. A window anchored to notice arrival would
--      therefore silently never open in a flat year, so the pack anchors to
--      the unconditional statutory date and treats the notice-relative
--      later-leg as per-parcel data, entered from the notice when one comes.
--    * A cap that repeals ITSELF: the s.23.231 circuit breaker (20 percent
--      annual appraisal cap on modest non-homestead property) expires
--      December 31, 2026 by its own subsection (k). The row below carries
--      that sunset as effective_to, so tax year 2027 CANNOT silently
--      inherit it — if the 2027 legislature extends the cap, that is a NEW
--      row with a new citation, exactly like any other amendment.
--    * Landlord-tenant law that is genuinely statewide (Prop. Code ch. 92
--      and ch. 24) — no adoption step (Kentucky), no population threshold
--      (Tennessee). The county exists in the chain for appraisal and the
--      municipality for registration; the tenancy rules live on the state.
--    * No individual income tax, like Tennessee — but by CONSTITUTION
--      (art. VIII, s.24-a), not by repeal, and the entity-level trap is
--      different: the franchise no-tax-due threshold silences the TAX, not
--      the FILING. The Public Information Report is due May 15 regardless,
--      and a forfeited entity exposes its officers personally.
--
--  UUID block a0000000-0048-… (Texas FIPS 48, per seed/README.md).
--  Figures not yet professionally confirmed say so in their citations.
-- ===========================================================================

INSERT INTO jurisdictions (id, level, name, state, parent_id, fips_code) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'state',        'Texas', 'TX', 'a0000000-0000-4000-8000-000000000001', '48'),
  ('a0000000-0048-4000-8000-000000000021', 'county',       'Dallas County', 'TX', 'a0000000-0048-4000-8000-000000000010', '48113'),
  ('a0000000-0048-4000-8000-000000000101', 'municipality', 'Dallas', 'TX', 'a0000000-0048-4000-8000-000000000021', '4819000');

-- Depth-per-address, never breadth-per-map: Dallas County and the City of
-- Dallas are seeded because the doors are there. When an actual address
-- resolves to a suburb or a neighboring county (Collin, Denton, Tarrant),
-- THAT jurisdiction gets its own researched rows — the chain resolving past
-- an unseeded municipality to the state is the correct behavior, not a
-- shortcut, because every tenancy rule below genuinely is statewide.

-- ---------------------------------------------------------------------------
-- Property tax: the computed window, and the notice that must not anchor it.
--
-- s.41.44(a)(1) makes a protest timely "not later than May 15" or the 30th
-- day after the s.25.19 notice was delivered, WHICHEVER IS LATER; s.1.06
-- extends a deadline falling on a weekend or holiday to the next business
-- day. The May 15 leg is a pure function of the year —
-- the registered builder `us-tx.protest-by-may-15` in both twins, anchored
-- at 2026-05-15 (Friday, stands) and 2027-05-15 (Saturday, rolls to Monday
-- May 17). The notice leg is per-parcel, conditional, and therefore DATA:
-- when a notice arrives late enough to extend the deadline, the extension is
-- entered from the notice itself, never assumed.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.window.calendar',
   NULL, 'us-tx.protest-by-may-15',
   'Tex. Tax Code s.41.44(a)(1) (not later than May 15 or the 30th day after '
   'the date the s.25.19 notice was delivered, whichever is later — May 15 '
   'text enacted by HB 2228, 85th Leg., ch. 357, effective January 1, 2018); '
   'Tex. Tax Code s.1.06 (a deadline falling on a Saturday, Sunday, or legal '
   'state or national holiday extends to the next regular business day)',
   DATE '2018-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.form',
   NULL, 'written notice of protest filed with the appraisal review board for '
   'the county appraisal district; Comptroller Form 50-132 is the standard '
   'vehicle — CONFIRM WITH TX COUNSEL',
   'Tex. Tax Code s.41.44', DATE '2020-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.instructions',
   NULL, 'File the protest by May 15 (weekend-rolled) even if no appraisal '
   'notice has arrived: the s.25.19 notice is CONDITIONAL — an unchanged value '
   'produces no notice at all — and the statutory date does not wait for it. '
   'Where a notice IS delivered later than April 15, the deadline extends to '
   '30 days after delivery (whichever is later); that extension is a per-parcel '
   'fact entered from the notice, never assumed in advance.',
   'Tex. Tax Code s.41.44(a)(1); Tex. Tax Code s.25.19', DATE '2020-01-01'),
  -- The protest filed in year Y contests the appraisal of year Y: everything
  -- protestable is the value "as of January 1" of the same year the ARB sits.
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.contests_tax_year_offset',
   0, 'a protest filed in calendar year Y contests tax year Y — the value '
   'protested is the one appraised as of January 1 of the year of filing; '
   'Texas is a same-year contest state',
   'Tex. Tax Code s.23.01(a) (appraised as of January 1); Tex. Tax Code '
   's.41.44 (the protest addresses that year''s appraisal records)',
   DATE '2020-01-01'),
  -- The ladder past the ARB, recorded as data so the escalation is a fact
  -- with citations rather than folklore in a UI string.
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.escalation',
   NULL, 'informal conference with the district (s.41.445) -> ARB hearing and '
   'determination (s.41.41, s.41.45, s.41.47) -> within 60 days of the ARB '
   'order, one of three forks: binding arbitration (ch. 41A; available for '
   'non-homestead property at or under $5M; deposit $450 to $1,550 by value '
   'band), district court review (ch. 42), or SOAH (ch. 2003 route, appraised '
   'value over $1M only, 30-day notice, $1,500 deposit) — CONFIRM WITH TX '
   'COUNSEL before relying on a fork''s eligibility figures',
   'Tex. Tax Code s.41.445; s.41.41; s.41.45; s.41.47; ch. 41A; ch. 42',
   DATE '2020-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.late_routes',
   NULL, 'after May 15 the door is not always shut, but every late route is '
   'narrower than the one it replaces: good cause before the appraisal records '
   'are approved (s.41.44(b)); lack of the required notice (s.41.411); the '
   'five-year correction categories — clerical error, multiple appraisal, '
   'non-existent property, unowned property (s.25.25(c)); and the '
   'pre-delinquency substantial-error route, appraised value more than one '
   'third too high (one quarter for a homestead), carrying a 10 percent '
   'late-correction penalty (s.25.25(d)) — CONFIRM WITH TX COUNSEL',
   'Tex. Tax Code s.41.44(b); s.41.411; s.25.25(c); s.25.25(d)',
   DATE '2020-01-01');

-- The conference answer has two legs because the statute does: before 2022,
-- ch. 41 simply contained no informal-conference provision; from January 1,
-- 2022, s.41.445 (HB 988, 87th Leg., ch. 644) obliges the appraisal office
-- to hold one for any protesting owner who requests it. In BOTH periods the
-- answer to "is a conference required before filing" is false — the 2022
-- right is the owner's to trigger, never a gate — but the two periods cite
-- different law, so they are two rows, one closed by the other's arrival.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from, effective_to) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.conference_required',
   NULL, 'false; ch. 41 contained no informal-conference provision at all in '
   'this period, and nothing conditioned a timely protest on a conference',
   'Tex. Tax Code ch. 41 (no conference provision before the 2022 addition '
   'of s.41.445 by HB 988, 87th Leg., ch. 644)',
   DATE '2018-01-01', DATE '2022-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'assessment_appeal', 'appeal.conference_required',
   NULL, 'false; since 2022 the appraisal office must hold an informal '
   'conference with an owner who files a protest and requests one — a right '
   'the owner triggers, never a prerequisite to a timely protest or an ARB '
   'hearing',
   'Tex. Tax Code s.41.445 (added by HB 988, 87th Leg., ch. 644, effective '
   'January 1, 2022)',
   DATE '2022-01-01', NULL);

-- Where the protest is actually filed for the Dallas-area doors. DCAD's own
-- published 2026 deadline (May 15, 2026) restates the statute — the county
-- adds no calendar of its own, which is exactly what makes Texas computed
-- where Tennessee is published.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000021', 'assessment_appeal', 'appeal.filed_with',
   NULL, 'Appraisal Review Board, Dallas Central Appraisal District (DCAD). '
   'DCAD''s published 2026 protest deadline of May 15, 2026 restates the '
   'statutory date; its uFile portal opening in mid-April is administrative '
   'convenience, not a legal window',
   'Tex. Tax Code s.41.44; DCAD 2026 protest publication (verified '
   '2026-09-03)', DATE '2026-01-01');

-- ---------------------------------------------------------------------------
-- Assessment ratio: there is none, and that is a fact, not a blank.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'assessment_ratio', 'assessment.ratio',
   1.00, '100 percent of market value as of January 1; taxable value is '
   'appraised value minus exemptions. The appraisal notice states the '
   'APPRAISED (market) value, so an assessment entered from a Texas notice '
   'carries value_basis = market — never taxable',
   'Tex. Tax Code s.23.01(a)-(b); Tex. Tax Code s.25.19 (notice states '
   'appraised value)', DATE '2020-01-01');

-- ---------------------------------------------------------------------------
-- The two caps, told apart. The homestead cap is seeded as INAPPLICABLE —
-- silence would invite somebody to apply the widely known "10 percent rule"
-- to a rental, where it has never applied. The circuit breaker is the one
-- that reaches rentals, and it expires by its own text: effective_to below
-- IS s.23.231(k), carried as data.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from, effective_to) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'exemption', 'exemption.homestead_cap',
   NULL, 'inapplicable to rentals; the 10 percent annual appraisal cap of '
   's.23.23 reaches residence homesteads only, and a rented property is not '
   'one. Recorded so the platform never applies the best-known cap in Texas '
   'to the properties this system actually holds',
   'Tex. Tax Code s.23.23 (residence homesteads only)', DATE '2020-01-01', NULL),
  ('a0000000-0048-4000-8000-000000000010', 'exemption', 'exemption.circuit_breaker',
   0.20, '20 percent annual cap on appraised-value growth for non-homestead '
   'real property valued at or under an indexed ceiling: $5,000,000 for 2024, '
   '$5,160,000 for 2025, $5,320,000 for 2026 (Comptroller-indexed figures — '
   'CONFIRM WITH TX CPA). This row ENDS on December 31, 2026 because the '
   'statute repeals itself on that date; if the 2027 legislature extends the '
   'cap, that is a NEW row citing the extending act, never an edit to this one',
   'Tex. Tax Code s.23.231; s.23.231(k) (expires December 31, 2026)',
   DATE '2024-01-01', DATE '2027-01-01');

-- ---------------------------------------------------------------------------
-- Landlord-tenant: statewide by statute, the Ohio shape with Texas teeth.
-- The late-fee safe harbor carries the boundary the actual portfolio sits
-- on: a four-plex is a structure with FOUR OR FEWER units, so it takes the
-- 12 percent harbor — the direction of that inequality is pinned by the
-- pack test because flipping it mis-prices the fee on the real building.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'landlord_tenant_act', 'ltl.statewide',
   NULL, 'true', 'Tex. Prop. Code ch. 92 (residential tenancies) and ch. 24 '
   '(eviction), statewide with no adoption step — enacted by the 1983 '
   'recodification of the Property Code; CONFIRM WITH TX COUNSEL for pre-1984 '
   'history', DATE '1984-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'security_deposit', 'deposit.return_days',
   30, 'thirty days from surrender of the premises',
   'Tex. Prop. Code s.92.103(a)', DATE '1984-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'security_deposit', 'deposit.interest_required',
   NULL, 'false; chapter 92 imposes no interest obligation on a residential '
   'security deposit',
   'Tex. Prop. Code ch. 92, subch. C (no interest provision) — CONFIRM WITH '
   'TX COUNSEL', DATE '1984-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'security_deposit', 'deposit.itemized_list_required',
   NULL, 'true; a written description and itemized list of all deductions is '
   'required — excused only when the tenant owes rent at surrender AND there '
   'is no controversy about the amount owed — and NORMAL WEAR AND TEAR may '
   'not be retained against',
   'Tex. Prop. Code s.92.104(b)-(c)', DATE '1984-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'security_deposit', 'deposit.bad_faith_penalty',
   NULL, 'a landlord who retains a deposit in bad faith owes $100 plus three '
   'times the wrongfully withheld portion plus reasonable attorney fees, and '
   'bad faith is PRESUMED when neither refund nor itemization has issued '
   'within thirty days',
   'Tex. Prop. Code s.92.109', DATE '1984-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'notice_period', 'eviction.notice_days',
   3, 'notice to vacate before an eviction suit: three days by default, and '
   'the lease may provide a shorter or longer period',
   'Tex. Prop. Code s.24.005', DATE '1984-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'habitability', 'repair.presumption_days',
   7, 'a rebuttable presumption that seven days is a reasonable time for the '
   'landlord to repair after notice',
   'Tex. Prop. Code s.92.056 — CONFIRM WITH TX COUNSEL', DATE '1984-01-01');

-- Late fees. The fee itself belongs to the LEASE — s.92.019 makes one
-- enforceable only if the lease provides it, so this pack deliberately seeds
-- NO latefee.amount and NO latefee.percent: the sweep must keep reporting a
-- gap until the lease's own figure is entered, and a statewide number here
-- would invent a fee no statute sets. What the statute does fix is seeded:
-- the two-full-days grace and the reasonableness safe harbors, with the
-- four-unit boundary the portfolio's own four-plex sits exactly on.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'late_fee', 'latefee.grace_days',
   2, 'a late fee may not be charged until the rent has remained unpaid for '
   'two full days after the date it was due',
   'Tex. Prop. Code s.92.019', DATE '2019-09-01'),
  ('a0000000-0048-4000-8000-000000000010', 'late_fee', 'latefee.in_lease_required',
   NULL, 'true; a late fee is enforceable only if provided by a written lease, '
   'and it must be reasonable',
   'Tex. Prop. Code s.92.019', DATE '2019-09-01'),
  ('a0000000-0048-4000-8000-000000000010', 'late_fee', 'latefee.safe_harbor_percent',
   0.12, 'presumed reasonable at or under 12 percent of one month''s rent for '
   'a dwelling in a structure with FOUR OR FEWER dwelling units. A four-plex '
   'has exactly four and QUALIFIES for this harbor — the boundary is "four or '
   'fewer", not "fewer than four"',
   'Tex. Prop. Code s.92.019 — CONFIRM WITH TX COUNSEL', DATE '2019-09-01'),
  ('a0000000-0048-4000-8000-000000000010', 'late_fee', 'latefee.safe_harbor_percent.over_four',
   0.10, 'presumed reasonable at or under 10 percent of one month''s rent in a '
   'structure with MORE than four dwelling units',
   'Tex. Prop. Code s.92.019 — CONFIRM WITH TX COUNSEL', DATE '2019-09-01');

-- ---------------------------------------------------------------------------
-- Income tax: none for the owner — by constitution, not by repeal — and the
-- entity-level trap is that the THRESHOLD silences the tax, never the
-- filing. Tennessee's "none" and Texas's "none" agree by two different
-- routes, and the citations must not be interchangeable.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from, effective_to) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'income_tax', 'income.type',
   NULL, 'none; no individual income tax on wages or rental income. The '
   'constitution FLATLY forbids one: "The legislature may not impose a tax on '
   'the net incomes of individuals" — an unconditional ban, repealable only by '
   'constitutional amendment, which replaced the former s.24 regime of 1993 '
   'that had merely conditioned an income tax on a statewide referendum',
   'Tex. Const. art. VIII, s.24-a (HJR 38, 86th Leg., adopted as Prop. 4 on '
   'November 5, 2019, repealing former art. VIII, s.24)',
   DATE '2019-11-05', NULL),
  ('a0000000-0048-4000-8000-000000000010', 'income_tax', 'income.entity_franchise_rate',
   0.0075, 'franchise (margin) tax on taxable entities at 0.75 percent of '
   'taxable margin for entities other than retailers and wholesalers — a '
   'rental LLC is "other"; the 0.375 percent retail/wholesale rate does not '
   'reach rentals',
   'Tex. Tax Code s.171.002 — CONFIRM WITH TX CPA', DATE '2020-01-01', NULL),
  ('a0000000-0048-4000-8000-000000000010', 'income_tax', 'income.entity_no_tax_due_threshold',
   2470000, 'no franchise tax is due at or under this annualized total '
   'revenue; the filing obligations below survive the threshold',
   'Tex. Tax Code s.171.002(d) (indexed); figure per Comptroller for '
   'report years 2024-2025 — CONFIRM WITH TX CPA',
   DATE '2024-01-01', DATE '2026-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'income_tax', 'income.entity_no_tax_due_threshold',
   2650000, 'no franchise tax is due at or under this annualized total '
   'revenue; the filing obligations below survive the threshold',
   'Tex. Tax Code s.171.002(d) (indexed); figure per Comptroller for '
   'report years 2026-2027 — CONFIRM WITH TX CPA',
   DATE '2026-01-01', DATE '2028-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'income_tax', 'income.entity_information_report',
   NULL, 'the Public Information Report (or Ownership Information Report) is '
   'due with the May 15 franchise filing REGARDLESS of the no-tax-due '
   'threshold — since 2024 a below-threshold entity files no No-Tax-Due '
   'report but still owes the PIR. Failure leads to forfeiture of the '
   'entity''s privileges, after which officers and directors can be held '
   'personally liable for entity debts',
   'Tex. Tax Code s.171.203 (PIR); ch. 171, subch. F (forfeiture; officer '
   'and director liability) — CONFIRM WITH TX CPA', DATE '2024-01-01', NULL);

-- ---------------------------------------------------------------------------
-- Depreciation conformity: nothing to conform for the owner, and the entity
-- answer is structural — the margin tax never starts from federal taxable
-- income, so there is no depreciation figure to add back.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.conformity_kind',
   NULL, 'none', 'there is no individual income tax to conform: Tex. Const. '
   'art. VIII, s.24-a — CONFIRM WITH TX CPA', DATE '2020-01-01'),
  ('a0000000-0048-4000-8000-000000000010', 'depreciation_conformity', 'depreciation.entity_franchise_addback',
   NULL, 'false; the franchise (margin) tax computes from total revenue less '
   'statutory deductions rather than from federal taxable income, so no '
   'depreciation addback exists — and a rental entity cannot elect the '
   'cost-of-goods-sold deduction where depreciation would otherwise surface',
   'Tex. Tax Code s.171.101; s.171.1012 (COGS; rentals do not qualify) — '
   'CONFIRM WITH TX CPA', DATE '2020-01-01');

-- ---------------------------------------------------------------------------
-- City of Dallas rental registration — the compliance obligation that
-- reaches the four-plex if it sits inside city limits. Seeded on the
-- MUNICIPALITY: a property in a suburb resolves past these rows, which is
-- correct, because each suburb runs (or does not run) its own program.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0048-4000-8000-000000000101', 'registration', 'registration.rental_program.multi_tenant',
   6, 'multi-tenant program, three or more units — a four-plex registers '
   'here: $6 per unit per year, renewal due 30 days before expiry, three-year '
   'graded inspection cycle, re-inspection $46 per unit, administrative '
   'failure-to-register $86 per unit, self-certification available at '
   'inspection scores of 90 or above',
   'Dallas City Code ch. 27; program facts verified 2026-09-03 against City '
   'of Dallas program pages — CONFIRM AGAINST CODIFIED TEXT (earlier history '
   'not loaded)', DATE '2026-01-01'),
  ('a0000000-0048-4000-8000-000000000101', 'registration', 'registration.rental_program.single_family',
   74, 'single-family and duplex program: $74 per unit per year with a '
   'five-year inspection cycle, in force from October 2025',
   'Dallas City Code ch. 27; program facts verified 2026-09-03 against City '
   'of Dallas program pages — CONFIRM AGAINST CODIFIED TEXT',
   DATE '2025-10-01');
