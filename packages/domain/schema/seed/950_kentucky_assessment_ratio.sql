-- ===========================================================================
--  Correction — Kentucky's assessment ratio, and three things that are not
--  it.
--
--  In the 950 range because seed/README.md reserves it for corrections: the
--  Kentucky pack is applied and may not be edited, and this is a row it
--  should have carried from the start.
--
--  The Kentucky pack shipped without an assessment.ratio row because Kentucky
--  assesses at full value and the omission read as harmless. It is not: a
--  detector comparing assessed value against market has to divide by
--  something, and a MISSING ratio is indistinguishable from a ratio of zero
--  unless the reader is careful. Ohio and Tennessee both carry one, so
--  Kentucky's absence made the only fully covered state the one the platform
--  could say least about.
--
--  Seeding 1.00 is a transcription, not an interpretation. KRS 132.191(1)
--  says the words: "the General Assembly recognizes that Section 172 of the
--  Constitution of Kentucky requires all property ... to be assessed at one
--  hundred percent (100%) of the fair cash value". The operative command is
--  older and plainer — Ky. Const. s.172 and KRS 132.190(3) both say "fair
--  cash value, estimated at the price it would bring at a fair voluntary
--  sale" — and 132.191(1) is the sentence that states it as a percentage.
--
--  THREE NUMBERS THAT LOOK LIKE THIS ONE AND ARE NOT, each recorded here so
--  that nobody later files them in this field:
--
--  * The 90% (or 95%-105%, or 90%-110%) figure from Kentucky's sales-assessment
--    ratio study. That is a COUNTY-level compliance band applied to a median
--    across many parcels, it comes from Department of Revenue manual policy
--    rather than statute or regulation, and KRS 133.250(4)'s only statutory
--    number is the 80% that triggers an underassessment audit. A parcel in a
--    county whose median ratio is 0.93 is still legally assessed at 100%.
--    Storing that band here would understate every Kentucky assessment by
--    seven percent.
--
--  * Agricultural and horticultural land. Ky. Const. s.172A and KRS
--    132.450(2)(d) substitute a different DEFINITION of value — the land's
--    value for agricultural use — and then assess 100% of that. It is a value
--    basis, not a ratio, and encoding it as one would be wrong in both
--    directions at once.
--
--  * The homestead exemption. Ky. Const. s.170 and KRS 132.810 subtract a
--    fixed number of dollars from assessed value ($49,100 for the 2025-2026
--    assessment period, adjusted biennially for the cost of living under KRS
--    132.810(2)(e)3). A subtraction is not a ratio. It is not seeded here
--    because nothing in this release reads it, and a figure that changes
--    every two years should arrive with the reader that needs it.
-- ===========================================================================

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from)
SELECT id, 'assessment_ratio', 'assessment.ratio',
       1.000000,
       'all real property, at one hundred percent of fair cash value — the '
       'price it would bring at a fair voluntary sale',
       'Ky. Const. s.172 (never amended since 1891); KRS 132.190(3); KRS '
       '132.191(1) (which states the standard as "one hundred percent '
       '(100%)"); Russman v. Luckett, 391 S.W.2d 694 (Ky. 1965) (assessment at '
       'a fraction of fair cash value held unconstitutional, ending a practice '
       'whose statewide median ratio was about 27 percent; the 1965 special '
       'session responded by rolling back RATES, leaving the standard itself '
       'untouched)',
       DATE '1891-08-03'
FROM jurisdictions WHERE level = 'state' AND state = 'KY';

-- Recorded as data rather than left to a comment, because the next reader of
-- assessment.ratio is a detector that will divide by it, and "why is there no
-- second ratio for farmland" is a question it should be able to answer from
-- the pack instead of from a source file.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from)
SELECT id, 'assessment_ratio', 'assessment.ratio.basis_note',
       NULL,
       'Kentucky has ONE ratio. The assessed value and the value the tax is '
       'computed on are the same number before exemptions — there is no '
       'taxable-value step, and the phrase "taxable value" does not appear in '
       'the Department of Revenue''s assessment manual at all. Agricultural '
       'and horticultural land is not an exception to the ratio but a '
       'different definition of value, assessed at 100% of ITS value.',
       'Ky. Const. s.172A; KRS 132.450(2)(d); KRS 132.020(1)(a) (the rate '
       'applies to assessed value directly)',
       DATE '1969-11-04'
FROM jurisdictions WHERE level = 'state' AND state = 'KY';
