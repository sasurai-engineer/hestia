-- ===========================================================================
--  Seed — Newport's rental dwelling license (issue #146), and the platform's
--  first source-vs-source conflict carried as data.
--
--  Born from the mockup refutation: the license lives in Newport Code
--  ch. 99 (RENTAL DWELLING LICENSE, ss.99.01-99.09) — not the ch. 156 a
--  first draft guessed — and the city disagrees with itself about the
--  date. The code (s.99.09: "due and payable by October 31") and the
--  city's own CN-17 renewal form ("DUE ON OR BEFORE Oct. 31st", with a
--  $20 penalty only AFTER October 31) say one thing; the city's Licenses
--  & Permits web page alone says October 15.
--
--  The rule for choosing, stated: two operative sources (the ordinance
--  and the form that triggers the penalty) outweigh one web page, so
--  October 31 is the emitted date — the page's claim is recorded beside
--  it, and staging by mid-October costs nothing and is the product's own
--  errs-early habit, not a legal requirement.
-- ===========================================================================

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from) VALUES
  ('a0000000-0000-4000-8000-000000000101', 'registration', 'registration.rental_license',
   NULL, 'required for anyone to rent or occupy a rental dwelling, including '
   'a property owner who lives in one unit and rents the others',
   'Newport Code ch. 99 (RENTAL DWELLING LICENSE); City of Newport Licenses '
   'and Permits page (verified 2026-09-05). The chapter predates this row''s '
   'effective_from; earlier history not loaded. Codified text is '
   'Cloudflare-gated — CONFIRM AGAINST CODIFIED TEXT', DATE '2020-01-01'),
  ('a0000000-0000-4000-8000-000000000101', 'registration', 'registration.rental_license.due',
   NULL, 'annual; the license period runs January 1 through December 31 and '
   'the fee is due and payable by OCTOBER 31 of the preceding year. THE '
   'SOURCES DISAGREE: the code (s.99.09) and the city''s own CN-17 renewal '
   'form say October 31 — the form adds its $20 penalty only AFTER October '
   '31 — while the city''s Licenses and Permits web page alone says October '
   '15. Rule for choosing: two operative sources outweigh one web page; '
   'October 31 is emitted, the page''s claim is recorded here, and staging '
   'by mid-October is the product''s errs-early habit, not a legal duty',
   'Newport Code s.99.09 ("due and payable by October 31"); City form CN-17 '
   '("DUE ON OR BEFORE Oct. 31st"; penalty "AFTER OCTOBER 31st"); City '
   'Licenses and Permits page ("due by October 15") — all verified '
   '2026-09-05', DATE '2020-01-01'),
  ('a0000000-0000-4000-8000-000000000101', 'registration', 'registration.rental_license.fee',
   NULL, 'two-part: $50 application fee per building plus $75 per rental '
   'dwelling unit (CN-17, current version covering the 2027 license year); '
   'a $20 penalty attaches per payment made after October 31. The fee '
   'structure is the form''s and may move with the annual ordinance',
   'City of Newport form CN-17 (newportky.gov DocumentCenter; verified '
   '2026-09-05) — CONFIRM ANNUALLY', DATE '2020-01-01'),
  ('a0000000-0000-4000-8000-000000000101', 'registration', 'registration.rental_license.forms',
   NULL, 'CN-25 for a first application; CN-17 for renewal',
   'City of Newport Licenses and Permits page (verified 2026-09-05)',
   DATE '2020-01-01');
