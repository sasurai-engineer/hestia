-- ===========================================================================
--  Seed — extraction field specs: the settlement statement
--
--  The registry rows that make a closing statement extractable. One document
--  kind ships in C1, done completely; the registry proves extensibility by
--  existing, not by speculative rows for kinds nothing parses yet.
--
--  target_hint is reviewer documentation. The apply step is code
--  (services/api/hestia_api/documents.py) and writes exactly what these
--  hints describe: basis into price_allocations, identity facts onto the
--  property, one acquisition_cost ledger event — all provenance-linked to
--  the source document.
-- ===========================================================================

INSERT INTO extraction_field_specs
  (document_kind, field_path, label, datatype, required, display_order, target_hint)
VALUES
  ('settlement_statement', 'settlement.closing_date', 'Closing date',
   'date', TRUE, 1,
   'price_allocations.allocated_on and properties.acquired_on'),
  ('settlement_statement', 'settlement.sale_price', 'Sale price',
   'money', TRUE, 2,
   'price_allocations.total_basis, with capitalizable closing costs'),
  ('settlement_statement', 'settlement.capitalizable_closing_costs',
   'Capitalizable closing costs', 'money', TRUE, 3,
   'price_allocations.total_basis, with the sale price (Treas. Reg. 1.263(a)-2: '
   'costs to acquire capitalize; loan costs do not)'),
  ('settlement_statement', 'settlement.property_address', 'Property address',
   'text', TRUE, 4,
   'checked against the linked property before apply'),
  ('settlement_statement', 'settlement.parcel_number', 'Parcel number',
   'text', FALSE, 5,
   'properties.parcel_number'),
  ('settlement_statement', 'settlement.loan_amount', 'Loan amount',
   'money', FALSE, 6,
   'not applied: a statement carries no rate or term, so debt entry stays '
   'its own workflow'),
  ('settlement_statement', 'settlement.buyer_name', 'Buyer',
   'text', FALSE, 7, NULL),
  ('settlement_statement', 'settlement.seller_name', 'Seller',
   'text', FALSE, 8, NULL);
