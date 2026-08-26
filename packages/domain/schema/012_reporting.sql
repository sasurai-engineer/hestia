-- ===========================================================================
--  012 — Reporting.
--
--  The Schedule E mapping is DATA with effectivity and citations, not code:
--  which ledger category lands on which line is tax law, and tax law gets a
--  citation and a start year. A NULL line_no is a first-class answer — it
--  says "this money is real but does not belong on Schedule E" (principal,
--  deposits, capital spend recovered through depreciation), and the report
--  shows those exclusions instead of silently dropping them.
-- ===========================================================================

CREATE TABLE schedule_e_map (
  category       ledger_category NOT NULL,
  tax_year_from  SMALLINT NOT NULL,
  line_no        SMALLINT,              -- NULL: excluded from Schedule E, says why
  line_label     TEXT NOT NULL,
  citation       TEXT NOT NULL,
  PRIMARY KEY (category, tax_year_from),
  CONSTRAINT plausible_line CHECK (line_no IS NULL OR line_no BETWEEN 1 AND 26)
);

COMMENT ON TABLE schedule_e_map IS
  'Ledger category -> Schedule E line, effectivity-dated. The report takes '
  'the newest mapping with tax_year_from <= the report year, so a form '
  'revision ships as new rows, never edits.';

CREATE TYPE report_kind AS ENUM ('schedule_e', 'p_and_l', 'cash_flow');

-- The CPA-confirm flag lives on the REPORT SNAPSHOT, never on ledger rows:
-- flagging rows would mean updating an append-only table, and what a
-- professional signs off on is a year's statement, not a transaction.
CREATE TABLE report_signoffs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id  UUID NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
  tax_year     SMALLINT NOT NULL,
  report_kind  report_kind NOT NULL,
  confirmed_by TEXT NOT NULL,
  confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  note         TEXT,
  UNIQUE (property_id, tax_year, report_kind)
);
