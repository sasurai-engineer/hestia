-- ===========================================================================
--  Correction — Ohio's appeal instructions stated a window the statute does
--  not state. The first real pack correction, and the shape every later one
--  copies.
--
--  seed/902 has said since it shipped:
--
--      'File DTE Form 1 with the county auditor between January 1 and
--       March 31'  ... cited to ORC 5715.19(A)
--
--  Two of those claims are not in the cited section (issue #97):
--
--   1. "January 1" is not in ORC 5715.19(A) at all. The subsection sets a
--      DEADLINE, not an opening date. Counties conventionally accept
--      complaints from the first of the year, but no statute says so.
--   2. March 31 is not the flat deadline. ORC 5715.19(A)(1) reads: a
--      complaint "shall be filed with the county auditor on or before the
--      thirty-first day of March of the ensuing tax year OR the date of
--      closing of the collection for the first half of real and public
--      utility property taxes for the current tax year, WHICHEVER IS LATER."
--      In a county whose first-half collection closes after March 31, the
--      real deadline is later than the pack printed.
--
--  The emitted DEADLINE was never wrong in the dangerous direction — the
--  us-oh.bor-complaint builder closes on March 31, which is never later than
--  the true date, and calendar.py promises exactly that. What was wrong is
--  the citation: the pack asserted a window under an authority that does not
--  establish it, and an owner who followed the citation to check would not
--  find it there. That is enough to correct.
--
--  ------------------------------------------------------------------------
--  THE CORRECTION CONVENTION, which this file is the worked example of.
--
--  A pack is applied-once and its bytes may never change. A rule that turns
--  out to be wrong is corrected by SUPERSEDING it, never by editing it:
--
--    * INSERT the replacement row, carrying the SAME jurisdiction, domain,
--      code and effective_from as the row it replaces. Same effective_from
--      because this is a CORRECTION — the old text was never right, so the
--      new one governs from the same day. An AMENDMENT is the other shape: a
--      genuinely new rule with a LATER effective_from, leaving the old row
--      open and closed by effective_to.
--    * UPDATE the old row's superseded_by to point at the new row's id. The
--      old row stays in the table forever. A resolver excludes it, and
--      anyone asking what the pack said in March still gets an answer.
--
--  The two open rows exist only inside this transaction. The open-twin guard
--  in tests/constraints.sql fails the build if two OPEN rules ever share
--  (jurisdiction, domain, code, effective_from), which is exactly the state
--  a half-finished correction leaves behind.
--  ------------------------------------------------------------------------
-- ===========================================================================

WITH corrected AS (
  INSERT INTO jurisdiction_rules
    (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from)
  SELECT jurisdiction_id, domain, code, value_numeric,
         'File DTE Form 1 with the county auditor. The deadline is March 31 of '
         'the year FOLLOWING the tax year, or the close of first-half '
         'collection for that tax year, whichever is later — so in some '
         'counties it falls after March 31. No opening date is fixed by '
         'statute; counties conventionally accept complaints from January 1.',
         'ORC 5715.19(A)(1)',
         effective_from
  FROM jurisdiction_rules
  WHERE jurisdiction_id = 'a0000000-0039-4000-8000-000000000010'
    AND code = 'appeal.instructions'
    AND superseded_by IS NULL
  RETURNING id, jurisdiction_id, code, effective_from
)
UPDATE jurisdiction_rules superseded
SET superseded_by = corrected.id
FROM corrected
WHERE superseded.jurisdiction_id = corrected.jurisdiction_id
  AND superseded.code = corrected.code
  AND superseded.effective_from = corrected.effective_from
  AND superseded.superseded_by IS NULL
  AND superseded.id <> corrected.id;

-- Additive, not a correction: the eligibility bar the pack never carried. An
-- owner who appealed last year usually may not appeal again inside the same
-- three-year interim period, and finding that out after paying a filing fee
-- is the kind of surprise this platform exists to prevent.
INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0039-4000-8000-000000000010', 'assessment_appeal', 'appeal.second_complaint_barred',
   NULL,
   'true; a second complaint on the same parcel within the same interim period '
   '(the three-year cycle between reappraisals) is barred UNLESS one of four '
   'things happened after the prior lien date: an arm''s-length sale, a '
   'casualty loss, a substantial improvement, or an occupancy change of at '
   'least fifteen per cent.',
   'ORC 5715.19(A)(2)', DATE '1976-01-01');
