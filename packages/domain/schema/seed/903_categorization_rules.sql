-- ===========================================================================
--  Seed — starter categorization rules for bank imports.
--
--  Planning defaults, not law: every suggestion these produce still passes
--  through the review queue, and a hit on an ambiguous payee (a hardware
--  store can be a $12 repair or a $12,000 capital improvement) deliberately
--  keeps needs_review true. Owners' own rules (origin 'user') outrank these
--  via priority.
-- ===========================================================================

INSERT INTO categorization_rules
  (priority, pattern, match_kind, category, is_capital_hint, origin) VALUES
  -- Utilities and recurring operating charges
  (50, 'duke energy',        'contains', 'utilities',          FALSE, 'seed'),
  (50, 'water works',        'contains', 'utilities',          FALSE, 'seed'),
  (50, 'sanitation district', 'contains', 'utilities',         FALSE, 'seed'),
  (50, 'spectrum',           'contains', 'utilities',          FALSE, 'seed'),
  -- Insurance carriers
  (50, 'state farm',         'contains', 'insurance',          FALSE, 'seed'),
  (50, 'allstate',           'contains', 'insurance',          FALSE, 'seed'),
  (50, 'liberty mutual',     'contains', 'insurance',          FALSE, 'seed'),
  -- Property tax
  (40, 'campbell county sheriff', 'contains', 'property_tax',  FALSE, 'seed'),
  (40, 'hamilton county treasurer', 'contains', 'property_tax', FALSE, 'seed'),
  -- Hardware / trades: category suggested, capital question left OPEN on
  -- purpose (is_capital_hint NULL) — repairs-vs-improvement is a per-charge
  -- judgment under the tangible property regulations, never a payee rule.
  (60, 'home depot',         'contains', 'repairs',            NULL,  'seed'),
  (60, 'lowe''s',            'contains', 'repairs',            NULL,  'seed'),
  (60, 'menards',            'contains', 'repairs',            NULL,  'seed'),
  -- Property management and HOA
  (50, 'hoa',                'contains', 'hoa',                FALSE, 'seed'),
  -- Mortgage servicers: flagged so the reviewer splits principal/interest/
  -- escrow at accept time instead of burying the whole payment in one bucket.
  (30, 'mortgage',           'contains', 'mortgage_interest',  FALSE, 'seed'),
  (30, 'loan pymt',          'contains', 'mortgage_interest',  FALSE, 'seed'),
  -- Rent deposits (income side)
  (30, 'zelle',              'contains', 'rent',               FALSE, 'seed'),
  (30, 'venmo',              'contains', 'rent',               FALSE, 'seed');
