-- ===========================================================================
--  Seed — Schedule E mapping, post-TCJA form shape (2018-).
--
--  CONFIRM WITH CPA before filing reliance: this mapping is engineering
--  scaffolding for a professional's review, and the report itself carries a
--  sign-off gate (report_signoffs) for exactly that reason.
-- ===========================================================================

INSERT INTO schedule_e_map (category, tax_year_from, line_no, line_label, citation) VALUES
  -- Income
  ('rent',              2018, 3,  'Rents received',
   'Schedule E (Form 1040) line 3; IRC s.61(a)(5)'),
  ('other_income',      2018, 3,  'Rents received (other rental income)',
   'Schedule E line 3; Treas. Reg. 1.61-8'),
  ('late_fee',          2018, 3,  'Rents received (late charges)',
   'Schedule E line 3; Treas. Reg. 1.61-8(a)'),
  -- Expenses
  ('advertising',       2018, 5,  'Advertising',        'Schedule E line 5; IRC s.162'),
  ('travel',            2018, 6,  'Auto and travel',    'Schedule E line 6; IRC s.162; s.274 limits'),
  ('insurance',         2018, 9,  'Insurance',          'Schedule E line 9; IRC s.162'),
  ('legal_professional',2018, 10, 'Legal and other professional fees',
   'Schedule E line 10; IRC s.162'),
  ('management_fee',    2018, 11, 'Management fees',    'Schedule E line 11; IRC s.162'),
  ('mortgage_interest', 2018, 12, 'Mortgage interest paid to banks, etc.',
   'Schedule E line 12; IRC s.163'),
  ('repairs',           2018, 14, 'Repairs',            'Schedule E line 14; Treas. Reg. 1.162-4'),
  ('supplies',          2018, 15, 'Supplies',           'Schedule E line 15; IRC s.162'),
  ('property_tax',      2018, 16, 'Taxes',              'Schedule E line 16; IRC s.164'),
  ('utilities',         2018, 17, 'Utilities',          'Schedule E line 17; IRC s.162'),
  ('hoa',               2018, 19, 'Other (HOA dues)',   'Schedule E line 19; IRC s.162'),
  -- Real money that does NOT belong on Schedule E — shown, never dropped.
  ('mortgage_principal',2018, NULL, 'Excluded: principal is not deductible',
   'IRC s.163 reaches interest only'),
  ('capital_improvement',2018, NULL, 'Excluded: capitalized, recovered on line 18',
   'IRC s.263(a); Treas. Reg. 1.263(a)-3'),
  ('deposit_received',  2018, NULL, 'Excluded: a liability while refundable',
   'Comm. v. Indianapolis Power & Light, 493 U.S. 203 (1990)'),
  ('deposit_returned',  2018, NULL, 'Excluded: returning a liability',
   'Comm. v. Indianapolis Power & Light, 493 U.S. 203 (1990)'),
  ('owner_contribution',2018, NULL, 'Excluded: equity, not income',
   'IRC s.61; capital contributions are not gross income'),
  ('owner_distribution',2018, NULL, 'Excluded: equity, not expense',
   'distributions are not deductible'),
  ('acquisition_cost',  2018, NULL, 'Excluded: capitalized into basis',
   'IRC s.263(a); s.1012'),
  ('disposition_cost',  2018, NULL, 'Excluded: reduces amount realized at sale',
   'IRC s.1001; Treas. Reg. 1.263(a)-1(e)');
