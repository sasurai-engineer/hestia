-- ===========================================================================
--  Correction — which tax year an appeal window contests, and the form
--  Kentucky files to open one.
--
--  A window and an assessment are two facts; WHICH TAX YEAR the window
--  contests is a third, and it is jurisdiction data. Ohio's Board of Revision
--  complaint is filed in the year FOLLOWING the tax year it contests, so a
--  window closing in 2027 contests tax year 2026 — and an owner holding a
--  2026 notice beside a 2027 window is looking at the right pair. Kentucky's
--  open inspection period runs in May on the roll "being prepared ... for the
--  current year", so a window closing in 2027 contests 2027, and that same
--  owner is looking at the WRONG pair by a year.
--
--  This repository asserts that difference twice today — in calendar.py and
--  in packages/engines/src/deadlines.ts — as a DOCSTRING, where no read model
--  can reach it. These rows are that sentence made resolvable:
--
--      contested_tax_year = year(the window closes) + offset
--
--  A RULE and not a field on the calendar registry, because only one of the
--  three window shapes has a builder to hang a field on. Tennessee's window
--  is a PUBLISHED date with no builder at all, so a registry-side offset
--  would answer for two states out of three and be structurally unable to
--  answer for the third.
--
--  TENNESSEE IS DELIBERATELY UNSEEDED. Davidson County's June adjournment
--  almost certainly contests the current tax year, but nothing in the pack
--  says so and the authorities it already cites are authorities for the
--  WINDOW, not for the year it contests. The card reports the pairing as
--  unknown and shows the window as informational, which is the honest answer
--  until somebody sources it.
-- ===========================================================================

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES

  -- Kentucky: offset 0. Verified rather than inferred — KRS 133.045(1) says
  -- the roll open for inspection is the one "being prepared by the property
  -- valuation administrator for the current year", and the Department of
  -- Revenue's own appeal form carries the field "assessed as of January 1,
  -- 20___" on its face, which the taxpayer fills with the same year they file.
  ('a0000000-0000-4000-8000-000000000010', 'assessment_appeal',
   'appeal.contests_tax_year_offset',
   0,
   'the open inspection period held in May of calendar year Y contests the '
   'assessment made as of January 1 of that same year Y — Kentucky is a '
   'same-year contest state',
   'KRS 133.045(1) (the roll open for inspection is the one being prepared '
   'for the current year); KRS 132.220(1)(a) (all taxable property listed, '
   'assessed and valued as of January 1 of each year); Kentucky Department of '
   'Revenue Form 62F031 (the appeal states the assessment "as of January 1" '
   'of the year it is filed in)',
   DATE '1994-01-01'),

  -- Ohio: offset -1, quoted from the statute the pack already cites.
  ('a0000000-0039-4000-8000-000000000010', 'assessment_appeal',
   'appeal.contests_tax_year_offset',
   -1,
   'a complaint filed in calendar year Y contests tax year Y-1: the statute '
   'speaks of a complaint against a determination "for the current tax year" '
   'filed "of the ensuing tax year"',
   'ORC 5715.19(A)(1)', DATE '1976-01-01'),

  -- The form Kentucky's pack never named. Ohio has carried DTE Form 1 since
  -- its own pack and Tennessee names its route, so the appeal card's form
  -- slot was a gap in one state and a value in the others for a difference of
  -- seeding rather than of law.
  --
  -- Two things this row is careful about. Form 62A307 is the PVA's CONFERENCE
  -- RECORD, which the owner attaches — it is not the document filed with the
  -- clerk, and the pack's conference rule already says so correctly. And the
  -- form is not mandatory: KRS 133.120(2)(b) accepts "a letter or other
  -- written petition", so this names the form the counties hand out without
  -- claiming a filing is void without it.
  ('a0000000-0000-4000-8000-000000000010', 'assessment_appeal', 'appeal.form',
   NULL,
   'Form 62F031, "Appeal to Local Board of Assessment Appeals", filed with the '
   'county clerk with Form 62A307 (the PVA conference record) attached. The '
   'statute accepts a letter or other written petition instead, so the form is '
   'the county''s convention rather than a condition of the appeal. The '
   'deadline is relative, never a fixed date: one workday after the inspection '
   'period closes, unless the Department grants an extension.',
   'KRS 133.120(2)(b); KRS 133.120(2)(c); Kentucky Department of Revenue Form '
   '62F031 (12-20). NOTE: 103 KAR 3:030, which formerly named both forms, was '
   'repealed effective 2017-03-03 — cite the Department''s form, not the '
   'regulation.',
   DATE '1994-01-01');
