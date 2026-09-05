-- ===========================================================================
--  Seed — the calendar keys that let the sweep emit Newport's dates
--  (issue #149).
--
--  Seeds 910/911 carry the LAW as prose with citations; these rows carry
--  the KEYS that name which registered annual-date builder computes each
--  date (the same registry pattern as appeal.window.calendar — ADR 0003).
--  One key per authority, even though both dates are October 31: a builder
--  serves exactly one citation.
-- ===========================================================================

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000101', 'tax_collection', 'collection.calendar',
   NULL, 'us-ky-newport.city-tax-oct31',
   'KRS s.91A.070(2); City of Newport Finance/Taxes page (payable on or '
   'before October 31; verified 2026-09-05); Newport Code s.37.002. No '
   'weekend roll is assumed — the s.446.030 question is open (seed 910) and '
   'staging errs early', DATE '2020-01-01'),
  ('a0000000-0000-4000-8000-000000000101', 'registration', 'registration.rental_license.calendar',
   NULL, 'us-ky-newport.rental-license-oct31',
   'Newport Code s.99.09; City form CN-17 (due on or before October 31; the '
   'page''s lone October 15 is recorded on the due row, seed 911)',
   DATE '2020-01-01');
