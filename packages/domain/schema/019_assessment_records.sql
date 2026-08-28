-- ===========================================================================
--  019 — Assessment records: what a notice may say, and what it may not.
--
--  `assessments` has stood since module 004 with no comment on any of its
--  columns and no CHECK of any kind, which was defensible only because
--  nothing had ever written to it — the single reader in the whole repository
--  is the assessor-ratio land suggestion in documents._suggestion. Issue #46
--  opens the first two write paths: an owner typing the notice they were
--  mailed, and the same notice arriving as an uploaded document. The
--  preconditions ship first.
--
--  The question 004 left open is the one every constraint here turns on: do
--  the assessed_* columns hold appraised (market) value, or taxable value
--  after the assessing authority's ratio?
--
--  Fixing one unit was the obvious answer and it is wrong, because the paper
--  does not cooperate. An Ohio value notice states MARKET value and nothing
--  else — the 35% taxable figure appears on the tax BILL, not the notice
--  (ORC 5713.03 speaks of "true value in money"; ORC 5715.01(B) caps taxable
--  at thirty-five per cent). A Tennessee assessment change notice prints
--  BOTH, side by side, and says so on its own reverse. Kentucky assesses at
--  100% of fair cash value, so the two coincide except where a homestead
--  exemption parts them. Demand "taxable" and an Ohio owner has nothing to
--  type; demand "market" and a Tennessee owner must choose a column and hope.
--
--  So the unit is not fixed. It is RECORDED, per row, in value_basis, and the
--  row is meaningless without it: market and taxable differ by a factor of
--  three in Ohio and four in Tennessee, which is the largest silent error
--  available anywhere in this system. The ratio itself stays in the pack
--  (ADR 0003) where it has always been; what this column adds is the fact a
--  reader needs before deciding whether to apply it.
--
--  Three things are deliberately NOT constrained, and each absence is a
--  decision rather than an oversight.
--
--  * `assessed_land + assessed_improvement = assessed_total`. A notice
--    carries lines this table has no column for: agricultural use-value,
--    business personalty, and separately-stated exemptions. Where the total
--    is printed NET of a homestead or similar exemption and the parts are
--    printed gross, the parts legitimately sum past it. price_allocations can
--    assert its own equality (004) because it enumerates all three parts of
--    the thing; this table enumerates two of an unbounded set.
--
--  * `assessed_improvement <= assessed_total`, for the same reason. The
--    improvement line is the large one, so it is the line an exemption-netted
--    total falls below. Only the land bound survives contact with real paper,
--    and it survives because it protects a named reader (below).
--
--  * Any bound on `millage_rate` beyond non-negativity. Mills per $1,000,
--    dollars per $100 (Kentucky's own statutory convention) and a plain
--    decimal fraction all fit NUMERIC(10, 6) and are indistinguishable once
--    stored; a bound generous to one is absurd for another. The column has no
--    writer in this release and the comment below says why.
--
--  And one thing that is not expressible at all: "the notice is not dated in
--  the future". CURRENT_DATE is not IMMUTABLE and PostgreSQL refuses it in a
--  CHECK. Nor should it be a trigger — a post-dated assessor letter is real
--  paper, not a defect.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Money that cannot be negative
-- ---------------------------------------------------------------------------

-- Narrowing the DOMAIN rather than writing five named CHECKs is module 004's
-- own instruction: a restated domain predicate is a second, independently
-- editable copy of one rule. A violation therefore reports the domain's name,
-- money_nonneg_check, which is what the assertion suite has expected for this
-- case since the price-allocation block.
--
-- Zero stays legal on every one of these: a fully exempt parcel and a
-- nominal-value sliver lot are both real, and `> 0` would refuse them. The
-- one reader that divides by assessed_total carries its own `> 0` guard
-- (documents._suggestion) and keeps it.
ALTER TABLE assessments ALTER COLUMN assessed_land        TYPE money_nonneg;
ALTER TABLE assessments ALTER COLUMN assessed_improvement TYPE money_nonneg;
ALTER TABLE assessments ALTER COLUMN assessed_total       TYPE money_nonneg;
ALTER TABLE assessments ALTER COLUMN market_value_opinion TYPE money_nonneg;
ALTER TABLE assessments ALTER COLUMN tax_billed           TYPE money_nonneg;

-- ---------------------------------------------------------------------------
-- Which figure the notice printed
-- ---------------------------------------------------------------------------

-- Named for what the amounts ARE, not for the word a particular state uses
-- for them, because the words collide across states: Kentucky's "assessed
-- value" IS market value, Ohio's is 35% of it, Tennessee's is 25% or 40% of
-- appraised depending on class. Two neutral terms, and a comment mapping the
-- local vocabulary onto them, beats three states arguing over one adjective.
CREATE TYPE assessed_value_basis AS ENUM (
  -- What the assessor says the property is worth. Kentucky's "Fair Cash
  -- Value", Ohio's "true value in money" or "Market Total Value",
  -- Tennessee's "Total Market Appraisal" or "Total Appraisal".
  'market',
  -- What the tax is actually computed on, after the state's ratio and any
  -- classification. Ohio's "Assessed Value" or "35% Taxable Value",
  -- Tennessee's "Assessment" or "Total Assessment", Kentucky's "Taxable
  -- Value" (which differs from market only by an exemption, never a ratio).
  'taxable'
);

-- No DEFAULT, deliberately. A default would be a guess about which figure a
-- row already in the table holds, and a wrong guess is a threefold error that
-- reads as data. The column is NOT NULL with nothing to fall back on, so this
-- module refuses to apply at all to a database that somehow holds
-- assessments — which no writer has ever created, this being the release that
-- adds the first two.
ALTER TABLE assessments ADD COLUMN value_basis assessed_value_basis NOT NULL;

COMMENT ON COLUMN assessments.value_basis IS
  'Whether every assessed_* amount in this row is a market figure or a '
  'taxable one. Not derivable and never inferred: an Ohio notice states only '
  'market, a Tennessee notice states both, and Kentucky''s coincide at a '
  '100% ratio. A reader that wants full value from a taxable row divides by '
  'the pack''s assessment.ratio; a reader that treats this column as '
  'decoration is off by three in Ohio and four in Tennessee.';

-- ---------------------------------------------------------------------------
-- What one notice may state about itself
-- ---------------------------------------------------------------------------

-- One body, one year, one BASIS. The key 004 wrote could not know that a
-- Tennessee assessment change notice prints an appraised total and an
-- assessed total side by side, for the same parcel and the same year, and
-- that both are worth keeping: the first is what an over-assessment test
-- compares against a market opinion, the second is what the tax is actually
-- computed on. Under the old key an owner transcribing that notice had to
-- throw one away. The basis joins the key so both rows fit, and the key still
-- refuses the thing it was written to refuse — the same figure twice.
ALTER TABLE assessments
  DROP CONSTRAINT assessments_property_id_jurisdiction_id_tax_year_key;
ALTER TABLE assessments ADD CONSTRAINT one_body_one_year_one_basis
  UNIQUE (property_id, jurisdiction_id, tax_year, value_basis);

COMMENT ON CONSTRAINT one_body_one_year_one_basis ON assessments IS
  'A Tennessee notice states both bases for one parcel and one year, so both '
  'may be recorded; what may not be recorded twice is the same body''s same '
  'figure for the same year. Note this does NOT stop one notice being '
  'recorded against a county and again against a municipality: some states '
  'genuinely levy at both levels, and a key that refused it would refuse real '
  'paper.';

ALTER TABLE assessments ADD CONSTRAINT assessed_land_within_total
  CHECK (assessed_land IS NULL OR assessed_land <= assessed_total);

-- Module 008 already set this band for a tax year, on two tables, under two
-- names (plausible_tax_year on tax_profiles and again on tax_elections) —
-- because the assertion harness matches on constraint name alone and a shared
-- name leaves a case unable to say which table refused. A third name, then.
-- SMALLINT already caps at 32767; this is about catching a typed 20226.
ALTER TABLE assessments ADD CONSTRAINT plausible_assessment_year
  CHECK (tax_year BETWEEN 1990 AND 2200);

-- The LOWER half of the plausible band only. Ohio's sexennial reappraisal
-- notices go out in the autumn PRECEDING the tax year they set, so a notice
-- dated in year-1 is ordinary; and omitted-property and supplemental
-- assessments reach back several years, so a 2026 notice assessing 2022 is
-- real paper an owner would want to type in. An upper bound would refuse it.
-- This catches the transposed year — a 2016 date on a 2026 notice — and
-- claims nothing about how late a correction may arrive.
ALTER TABLE assessments ADD CONSTRAINT notice_not_before_its_year
  CHECK (notice_received_on IS NULL
         OR notice_received_on >= make_date(tax_year::int - 1, 1, 1));

ALTER TABLE assessments ADD CONSTRAINT millage_rate_nonneg
  CHECK (millage_rate IS NULL OR millage_rate >= 0);

-- ---------------------------------------------------------------------------
-- Every assessment cites its authority
-- ---------------------------------------------------------------------------

-- Nullable was defensible while nothing wrote here. It stops being defensible
-- the moment the appeal card renders these numbers: a figure the owner cannot
-- trace back to a paper notice, an upload, or a county feed is a figure they
-- cannot check. Every writer that exists or is planned — manual entry, the
-- notice path, and the county adapter of #12 — has a provenance to hand or
-- has no business writing here.
ALTER TABLE assessments ALTER COLUMN provenance_id SET NOT NULL;

-- ---------------------------------------------------------------------------
-- What the columns mean
-- ---------------------------------------------------------------------------

COMMENT ON TABLE assessments IS
  'One assessing body''s stated value for one property in one tax year, as '
  'the notice states it. The row is a transcript, not a judgement: no ratio '
  'is applied on the way in and no market comparison is drawn here. A '
  'correction arrives as a new row for a new year, or as an appeal in '
  'assessment_appeals — never by rewriting what the notice said.';

COMMENT ON COLUMN assessments.jurisdiction_id IS
  'The body that ISSUED this assessment, which is often not the property''s '
  'most specific governing body: Kentucky assesses through the county PVA, '
  'Ohio through the county Auditor, Tennessee through the county Assessor of '
  'Property, while a property commonly resolves to a municipality. Which '
  'level assesses is a jurisdiction fact and therefore pack data, not code, '
  'so the API asks the caller to name the body and validates the answer '
  'against jurisdiction_chain() rather than inferring a level. A rule code '
  'naming the assessing level per state is the fix that would remove the '
  'question; until it is seeded, the property''s own resolved jurisdiction '
  'stands in.';

COMMENT ON COLUMN assessments.assessed_total IS
  'The total the notice states, in the basis value_basis names. Never '
  'divided or multiplied by an assessment ratio on the way in: Ohio''s 35% and '
  'Tennessee''s classification live in jurisdiction_rules and are applied by '
  'the reader, so a row transcribed in one state means the same thing as a '
  'row transcribed in another. Zero is legal and meaningful — a fully exempt '
  'parcel is a real assessment.';

COMMENT ON COLUMN assessments.assessed_land IS
  'Optional, and in the SAME basis as assessed_total. It is the numerator of '
  'the assessor-ratio land split that documents._suggestion multiplies a '
  'purchase basis by, which is the whole reason assessed_land_within_total '
  'exists. Where a notice prints land at market against a total stated at a '
  'statutory ratio, or a total net of an exemption the parts are gross of, '
  'leave this blank rather than mixing units: a blank costs nothing this '
  'release promises, and a mixed unit silently corrupts an allocation.';

COMMENT ON COLUMN assessments.assessed_improvement IS
  'Optional, same basis as assessed_total. Deliberately unconstrained against '
  'the total — see the module header.';

COMMENT ON COLUMN assessments.market_value_opinion IS
  'Our view, not the assessor''s — the other side of the over-assessment '
  'test. A different fact with a different provenance from everything else in '
  'this row, which is why no writer shipped in #46 sets it.';

COMMENT ON COLUMN assessments.millage_rate IS
  'UNIT UNDEFINED, and therefore unwritten. Mills per $1,000, dollars per '
  '$100 and a plain decimal fraction all fit this column and differ by orders '
  'of magnitude, so the only honest constraint is non-negativity and no API '
  'endpoint accepts a value. The module that ships millage and tax-bill '
  'reconciliation fixes the convention by rewriting this comment and adding '
  'the real bound, before writing a single value. Compare the annual_rate '
  'domain in 001, which exists because exactly this confusion once produced a '
  'payment a hundredfold too large.';

COMMENT ON COLUMN assessments.tax_billed IS
  'What a notice or bill says is owed. Not derivable from assessed_total and '
  'millage_rate: homestead exemptions, HB 920 reduction factors and credits '
  'all sit between them and none of that is modelled yet.';

COMMENT ON COLUMN assessments.notice_received_on IS
  'When the paper arrived — the owner''s own clock on a short statutory '
  'window, and not derivable from tax_year in either direction.';

COMMENT ON CONSTRAINT assessed_land_within_total ON assessments IS
  'The only arithmetic relation between these columns that survives contact '
  'with a notice from any state. documents._suggestion divides assessed_land '
  'by assessed_total and multiplies a purchase basis by the result; a ratio '
  'above 1 puts more than the whole basis into land, which never depreciates '
  '— the precise failure the price_allocations table comment exists to '
  'prevent.';
