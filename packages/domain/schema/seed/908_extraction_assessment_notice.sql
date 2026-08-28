-- ===========================================================================
--  Seed — extraction field specs: the assessment notice
--
--  The second extractable kind, and the proof of extraction_field_specs' own
--  claim that a new kind is seed rows plus a parser — never a schema change,
--  and never an edit to an applied file.
--
--  Seven rows, not thirteen. A spec exists only where the apply step writes
--  the value it names, or where a reviewer needs to see the value to check a
--  decision. millage_rate has no documented unit (module 019 says so on the
--  column), tax_billed belongs to a tax bill, which is its own document kind,
--  and market_value_opinion is our view rather than the assessor's. Seeding
--  any of them would put a field on the review screen that apply then
--  silently drops.
--
--  WHAT THESE DOCUMENTS ACTUALLY ARE, because it sets what may be promised.
--  There is no standard assessment notice in the United States and only
--  Kentucky prescribes a form (62A352). Ohio requires notice under ORC
--  5713.01(C) but fixes no fields, and at least two counties in the owner's
--  own metro satisfy it by publication and mail nothing per parcel. Tennessee
--  mails a card whose front no county publishes. Where a specimen does exist
--  the labels disagree: "Fair Cash Value", "Market Total Value", "Total
--  Market Appraisal", "Total Appraisal" all name one idea, and Campbell
--  County prints Fair Cash Value as 0.00 on ordinary residential parcels
--  while the real figure sits in Total Value.
--
--  So these rows are not a promise to read any notice. They are the registry
--  the review screen renders and the apply step writes, and a notice the
--  parser cannot read arrives as flagged skeleton rows — a typing form with
--  the original attached and the provenance still 'document'. That is the
--  honest shape for paper that mostly reaches us as a phone photograph.
--
--  target_hint is reviewer documentation. The apply step is code
--  (services/api/hestia_api/assessments.py) and writes exactly what these
--  hints describe: one assessments row, provenance-linked to this document,
--  and nothing else. No ledger event — an assessment is a statement of
--  value, not a movement of cash.
-- ===========================================================================

INSERT INTO extraction_field_specs
  (document_kind, field_path, label, datatype, required, display_order, target_hint)
VALUES
  ('assessment_notice', 'assessment.tax_year', 'Tax year',
   'text', TRUE, 1,
   'assessments.tax_year — the year assessed, which is not always the year '
   'printed on the envelope: Ohio mails a reappraisal notice in the autumn '
   'before the year it sets'),
  -- Required, and deliberately NOT something the parser may answer. The same
  -- card prints an appraised total and an assessed total that differ by a
  -- factor of three in Ohio and four in Tennessee, under labels that vary by
  -- county; a machine that guesses wrong produces a number that looks
  -- entirely reasonable and is off by 300%. A person holding the paper knows
  -- which column they read. This arrives as a flagged skeleton row on every
  -- notice, on purpose.
  ('assessment_notice', 'assessment.value_basis', 'Which figure is this',
   'text', TRUE, 2,
   'assessments.value_basis — exactly "market" or "taxable". Market is what '
   'the assessor says it is worth (Kentucky "Fair Cash Value", Ohio "true '
   'value"/"Market Total Value", Tennessee "Total Market Appraisal"); taxable '
   'is what the tax is computed on after the state ratio (Ohio "Assessed '
   'Value"/"35% Taxable Value", Tennessee "Assessment", Kentucky "Taxable '
   'Value"). Never inferred from the amounts'),
  ('assessment_notice', 'assessment.assessed_total', 'Total value',
   'money', TRUE, 3,
   'assessments.assessed_total, in the basis named above and never converted '
   'by any assessment ratio on the way in'),
  ('assessment_notice', 'assessment.assessed_land', 'Land value',
   'money', FALSE, 4,
   'assessments.assessed_land — the numerator of the land split a purchase '
   'allocation cites. Must be in the SAME basis as the total; where the '
   'notice prints land at market against a total at a ratio, leave it blank'),
  ('assessment_notice', 'assessment.assessed_improvement',
   'Improvement value', 'money', FALSE, 5,
   'assessments.assessed_improvement — printed as "Improvements" in Ohio and '
   'as "Building Appraisal" in Shelby County, Tennessee'),
  ('assessment_notice', 'assessment.notice_date', 'Notice date',
   'date', FALSE, 6,
   'assessments.notice_received_on — the printed mailing date, which is the '
   'closest thing a document can prove about when the owner was told'),
  ('assessment_notice', 'assessment.assessing_body', 'Assessing body',
   'text', FALSE, 7,
   'not applied: shown so the reviewer can confirm which governing body sent '
   'this before choosing it at apply. Never matched by name — a fuzzy match '
   'between "Campbell" and "Kenton" is how a notice lands on the wrong chain');
