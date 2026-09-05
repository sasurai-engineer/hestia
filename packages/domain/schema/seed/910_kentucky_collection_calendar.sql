-- ===========================================================================
--  Seed — the Kentucky collection calendar (issue #145).
--
--  Born from the mockup refutation: the widely cited KRS 134.020 was
--  REPEALED effective January 1, 2010 (2009 Ky. Acts ch. 10, s.71 — the
--  whole pre-2009 collection chapter fell in one sweep), and the calendar
--  now lives in KRS 134.015. Two schedules exist:
--
--    * The REGULAR schedule (s.134.015(2)) is COMPUTED: statutory dates,
--      a pure function of the year — 2% through November 1 (inclusive:
--      the face period begins November 2 by the statute's own words),
--      face through December 31, 5% in January, 10% after.
--    * The ALTERNATIVE schedule (s.134.015(3)) is established by THE
--      DEPARTMENT of Revenue when the regular schedule is delayed — not
--      by the county, not by the taxpayer — and every phase derives one
--      full month at a time from the MAILING DATE, which is a per-year
--      published fact. Campbell County has run this schedule in 2023,
--      2024, and 2025 (bills mail end of October; discount is the full
--      month of November), so the county rows below carry the published
--      2025 window and a source row that names where 2026's will come
--      from when it publishes (~mid-October, per the sheriff's pattern).
--
--  THE 21% TRAP, disarmed as data: sheriffs print "21% penalty" after
--  January 31 (Campbell and Warren both do), but no statute says 21. The
--  second statutory penalty is TEN percent (s.134.015(2)(d)); the sheriff
--  then adds "ten percent (10%) of the total taxes due plus ten percent
--  (10%) of the ten percent (10%) penalty" (s.134.119(7)) — 10 + 10 + 1.
--  A pack row carrying 0.21 as "the penalty" would be confidently wrong
--  twice over, and the pack test refuses one.
--
--  Prediction scored (stated on the log before research): HYBRID,
--  confirmed — regular schedule computed, alternative schedule anchored
--  to a published mailing date. Sharpened by the sources: the DEPARTMENT
--  elects, and all four phases shift together.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- The statutory calendar — state row, regular schedule.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.due',
   NULL, 'all property taxes are due and payable on or before December 31 of '
   'the assessment year; unpaid bills are delinquent thereafter (the '
   'Department''s collection-process page states they become delinquent '
   'January 1)',
   'KRS s.134.015(1) (created 2009 Ky. Acts ch. 10, s.2). BEWARE the '
   'predecessor: KRS s.134.020 was REPEALED effective January 1, 2010 by '
   '2009 Ky. Acts ch. 10, s.71 — do not "correct" this pack back to it',
   DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.discount',
   0.02, 'paid in full by November 1 of the assessment year — November 1 '
   'INCLUSIVE: the statute''s face period begins November 2, so a payment on '
   'the first still earns the discount',
   'KRS s.134.015(2)(a) (discount "by November 1"); s.134.015(2)(b) (face '
   'runs "between November 2 and December 31")', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.phase.face',
   NULL, 'November 2 through December 31: the amount reflected on the tax '
   'bill, without discount or penalty',
   'KRS s.134.015(2)(b)', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.phase.penalty_first',
   0.05, 'January 1 through January 31 of the year following the assessment '
   'year: five percent of the taxes due and unpaid',
   'KRS s.134.015(2)(c)', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.phase.penalty_second',
   0.10, 'after January 31: TEN percent of the taxes due and unpaid — the '
   '"21%" sheriffs print is this penalty PLUS the sheriff''s add-on, never a '
   'statutory 21',
   'KRS s.134.015(2)(d)', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.sheriff_addon',
   NULL, 'on delinquent taxes the sheriff is additionally entitled to ten '
   'percent of the total taxes due plus ten percent of the ten percent '
   'penalty, added to the amount due — with the s.134.015(2)(d) penalty the '
   'practical aggregate is 21 percent, which is a COMPOSITE, not a rate',
   'KRS s.134.119(7)', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.alternative_schedule',
   NULL, 'when the regular schedule is delayed, THE DEPARTMENT of Revenue '
   '(s.134.010(5)) — not the county, not the taxpayer — may establish an '
   'alternative schedule: taxes due two full months from the date bills are '
   'mailed; 2% discount for one full month from mailing; face the next full '
   'month; 5% the month after; 10% thereafter. Every phase shifts together, '
   'anchored to the mailing date — a per-year published fact carried on the '
   'county rows',
   'KRS s.134.015(3); KRS s.134.010(5) (department defined)', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.certificate_of_delinquency',
   NULL, 'unpaid claims are filed with the county clerk on April 15 (regular '
   'schedule) or three months and fifteen days from the due date (alternative '
   'schedule) and become certificates of delinquency carrying the face '
   'amount, the 10 percent penalty, and the sheriff''s commission and add-on. '
   'The two sections word the alternative period differently ("three (3) '
   'months and fifteen (15) days" vs "three (3) full months and fifteen (15) '
   'days") — recorded as found',
   'KRS s.134.122(1)(a), (2); KRS s.134.010(1)', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.omitted_property',
   NULL, 'a bill for omitted property (or an increased valuation finally '
   'determined on appeal) is due the day it is prepared and delinquent the '
   'same day; if unpaid within one full month, an additional ten percent '
   'penalty attaches — computed on the tax, fees, penalties, AND interest '
   'due, a broader base than the tax alone',
   'KRS s.134.015(6)', DATE '2010-01-01'),
  -- The weekend question, answered honestly: Kentucky's general
  -- computation-of-time statute is ASYMMETRIC, and nothing resolves whether
  -- it reaches these fixed calendar dates. The platform therefore never
  -- relies on a roll here — staged dates err early instead.
  ('a0000000-0000-4000-8000-000000000010', 'tax_collection', 'collection.weekend_roll',
   NULL, 'UNRESOLVED; KRS s.446.030(1)(a) rolls COMPUTED periods off a '
   'Saturday, Sunday, or legal holiday, but s.446.030(2) rolls acts fixed to '
   'a particular day off SUNDAY ONLY — and no section of chapter 134 carries '
   'its own roll, nor does the Department''s collection-process page mention '
   'one. Until counsel resolves which rule (if either) reaches these dates, '
   'no emitted Kentucky collection deadline may assume a roll: stage the '
   'prior business day',
   'KRS s.446.030(1)(a); s.446.030(2) — CONFIRM WITH KY COUNSEL',
   DATE '2010-01-01');

-- ---------------------------------------------------------------------------
-- Campbell County: the alternative schedule in practice, and the published
-- 2025 window. The 2026 schedule does not exist yet — the source row names
-- where it will come from, so its absence is a fact with an address.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000021', 'tax_collection', 'collection.schedule_kind',
   NULL, 'alternative; the county has run the s.134.015(3) schedule in 2023, '
   '2024, and 2025 — bills mail at the very end of October and the 2% '
   'discount runs the full month of November. Each year''s window is a '
   'published fact from the sheriff, entered when it publishes',
   'KRS s.134.015(3); Campbell County Sheriff''s Office tax pages, 2023-2025 '
   '(verified 2026-09-05)', DATE '2023-01-01'),
  ('a0000000-0000-4000-8000-000000000021', 'tax_collection', 'collection.schedule.source',
   NULL, 'published_by_sheriff; the year''s phase dates are published by the '
   'Campbell County Sheriff (~mid-October, per the three-year pattern). No '
   '2026 schedule was published as of 2026-09-05 — until it is, the 2026 '
   'window is honestly unknown and only the statutory shape is certain',
   'Campbell County Sheriff''s Office (campbellcountysheriffky.org)',
   DATE '2023-01-01'),
  ('a0000000-0000-4000-8000-000000000021', 'tax_collection', 'collection.discount.note',
   NULL, 'the 911 fee included on the county bill is not subject to the 2% '
   'discount',
   'Campbell County Sheriff''s Office, Tax Information page (verified '
   '2026-09-05)', DATE '2023-01-01');

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from, effective_to) VALUES
  ('a0000000-0000-4000-8000-000000000021', 'tax_collection', 'collection.discount.opens_on',
   NULL, '2025-11-01',
   'Campbell County Sheriff, 2025 collection: "The 2% discount period will '
   'extend from November 1 through November 30, 2025"',
   DATE '2025-01-01', DATE '2026-01-01'),
  ('a0000000-0000-4000-8000-000000000021', 'tax_collection', 'collection.discount.closes_on',
   NULL, '2025-11-30',
   'Campbell County Sheriff, 2025 collection — CONFIRM ANNUALLY, the window '
   'derives from each year''s mailing date',
   DATE '2025-01-01', DATE '2026-01-01');

-- ---------------------------------------------------------------------------
-- Newport city tax: a different collector, a different calendar, and a
-- stated NO on the discount — absence as an answer, not silence.
-- ---------------------------------------------------------------------------

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000101', 'tax_collection', 'collection.due',
   NULL, 'city bills (city plus Newport Board of Education) are mailed by '
   'late September and payable on or before October 31; delinquent if '
   'postmarked after that date',
   'KRS s.91A.070(2) (a city collecting its own ad valorem taxes does so by '
   'ordinance); City of Newport Finance/Taxes page (verified 2026-09-05); '
   'Newport Code s.37.002 (the annual levy ordinance sets dates) — CONFIRM '
   'the current year''s levy ordinance', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000101', 'tax_collection', 'collection.phase.penalty_first',
   0.10, 'a 10 percent penalty is added to late bills, with interest on '
   'delinquent bills — rates set by the annual levy ordinance',
   'City of Newport Finance/Taxes page (verified 2026-09-05) — CONFIRM WITH '
   'THE ANNUAL ORDINANCE', DATE '2010-01-01'),
  ('a0000000-0000-4000-8000-000000000101', 'tax_collection', 'collection.discount',
   NULL, 'none; no early-payment discount exists for Newport city property '
   'tax — the county''s 2% is the county''s alone',
   'City of Newport Finance/Taxes page (no discount provision; verified '
   '2026-09-05) — CONFIRM WITH THE ANNUAL ORDINANCE', DATE '2010-01-01');
