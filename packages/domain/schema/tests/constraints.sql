-- ===========================================================================
--  Schema constraint tests.
--
--  A constraint that has never been shown to reject anything is a comment.
--  Each case below asserts an outcome and raises if the schema disagrees, so
--  the file's exit status is the result.
-- ===========================================================================

\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION assert_rejected(stmt TEXT, expected TEXT, label TEXT)
  RETURNS void AS $$
DECLARE
  actual TEXT;
BEGIN
  BEGIN
    EXECUTE stmt;
  EXCEPTION
    WHEN check_violation OR unique_violation OR exclusion_violation
      OR foreign_key_violation OR not_null_violation OR restrict_violation THEN
      -- WHICH constraint fired, not merely that something did. Accepting any
      -- rejection let a case pass for the wrong reason: a row refused by an
      -- unrelated NOT NULL still reported success, so the constraint under test
      -- could have been dropped, mistyped, or never created at all.
      GET STACKED DIAGNOSTICS actual = CONSTRAINT_NAME;
      -- A trigger-raised refusal carries no constraint name, so it is named
      -- '<trigger>' explicitly rather than being waved through by a NULL.
      actual := coalesce(nullif(actual, ''), '<trigger>');
      IF actual IS DISTINCT FROM expected THEN
        RAISE EXCEPTION 'WRONG CONSTRAINT: % was rejected by %, expected %',
          label, actual, expected;
      END IF;
      RAISE NOTICE '  ok      rejected by %: %', expected, label;
      RETURN;
  END;
  -- Reached only when the statement succeeded, which is the failure.
  RAISE EXCEPTION 'CONSTRAINT DID NOT BITE: % was accepted (expected %)', label, expected;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION assert_accepted(stmt TEXT, label TEXT) RETURNS void AS $$
BEGIN
  EXECUTE stmt;
  RAISE NOTICE '  ok      accepted: %', label;
END $$ LANGUAGE plpgsql;

-- --------------------------------------------------------------------------
-- Fixtures
-- --------------------------------------------------------------------------
INSERT INTO entities (id, name, kind)
  VALUES ('11111111-1111-1111-1111-111111111111', 'Test Holdings LLC', 'llc');
INSERT INTO provenance (id, kind, confidence, derived_from)
  VALUES ('22222222-2222-2222-2222-222222222222', 'inferred', 0.6, 'year built 1962, no roof permit on file');
INSERT INTO properties (id, entity_id, label, street_1, city, state, postal_code, kind, unit_count, year_built)
  VALUES ('33333333-3333-3333-3333-333333333333', '11111111-1111-1111-1111-111111111111',
          '412 Maple', '412 Maple St', 'Newport', 'KY', '41071', 'single_family', 1, 1962);
INSERT INTO component_types (id, code, system, display_name, life_years_low, life_years_high, weibull_scale_years)
  VALUES ('44444444-4444-4444-4444-444444444444', 'roof.asphalt_shingle', 'roof',
          'Asphalt shingle roof', 15, 25, 22);
INSERT INTO units (id, property_id, label)
  VALUES ('55555555-5555-5555-5555-555555555555', '33333333-3333-3333-3333-333333333333', 'A');
INSERT INTO policies (id, property_id, kind, effective_from, effective_to)
  VALUES ('66666666-6666-6666-6666-666666666666', '33333333-3333-3333-3333-333333333333',
          'landlord_package', '2026-01-01', '2026-12-31');
INSERT INTO jurisdictions (id, level, name, state, parent_id)
  VALUES ('77777777-7777-7777-7777-777777777777', 'municipality', 'Testville', 'KY',
          (SELECT id FROM jurisdictions WHERE level = 'state' AND state = 'KY'));

\echo ''
\echo 'provenance'
SELECT assert_rejected(
  $$INSERT INTO provenance (kind, confidence) VALUES ('owner_stated', 0.8)$$,
  'stated_facts_are_certain', 'an owner-stated fact carrying less than full confidence');
SELECT assert_rejected(
  $$INSERT INTO provenance (kind, confidence) VALUES ('inferred', 0.5)$$,
  'inferences_explain_themselves', 'an inference that cannot explain itself');
SELECT assert_rejected(
  $$INSERT INTO provenance (kind, confidence, derived_from) VALUES ('inferred', 1.7, 'x')$$,
  'confidence_check', 'a confidence outside [0,1]');
SELECT assert_accepted(
  $$INSERT INTO provenance (kind, confidence) VALUES ('owner_stated', 1.0)$$,
  'an owner-stated fact at full confidence');

\echo ''
\echo 'purchase price allocation'
SELECT assert_rejected(
  $$INSERT INTO price_allocations (property_id, allocated_on, total_basis, land_value,
      improvement_value, personal_property, method, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333','2019-04-11',400000,100000,250000,0,
            'does not sum','22222222-2222-2222-2222-222222222222')$$,
  'allocation_sums_to_basis', 'an allocation whose parts do not sum to the basis');
SELECT assert_rejected(
  $$INSERT INTO price_allocations (property_id, allocated_on, total_basis, land_value,
      improvement_value, personal_property, method, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333','2019-04-11',400000,-10000,410000,0,
            'negative land','22222222-2222-2222-2222-222222222222')$$,
  'money_nonneg_check', 'a negative allocation component');
SELECT assert_accepted(
  $$INSERT INTO price_allocations (property_id, allocated_on, total_basis, land_value,
      improvement_value, personal_property, method, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333','2019-04-11',400000,88000,312000,0,
            'assessor ratio 22/78','22222222-2222-2222-2222-222222222222')$$,
  'an allocation that sums exactly');

\echo ''
\echo 'depreciation, dual book'
SELECT assert_rejected(
  $$INSERT INTO depreciable_assets (property_id, book, description, class, method,
      recovery_years, placed_in_service_on, original_basis)
    VALUES ('33333333-3333-3333-3333-333333333333','federal','Land','land','macrs_gds_sl',
            27.5,'2019-04-11',88000)$$,
  'land_is_not_depreciated', 'land marked as depreciable');
SELECT assert_rejected(
  $$INSERT INTO depreciable_assets (property_id, book, description, class, method,
      recovery_years, placed_in_service_on, original_basis)
    VALUES ('33333333-3333-3333-3333-333333333333','state','Dwelling','building',
            'macrs_gds_sl',27.5,'2019-04-11',312000)$$,
  'state_assets_name_their_state', 'a state-book asset that does not name its state');
SELECT assert_rejected(
  $$INSERT INTO depreciable_assets (property_id, book, description, class, method,
      recovery_years, placed_in_service_on, original_basis, bonus_percent)
    VALUES ('33333333-3333-3333-3333-333333333333','federal','Dishwasher',
            'personal_property_5yr','macrs_gds_200db',5,'2026-01-15',900,1.5)$$,
  'unit_fraction_check', 'a bonus percentage above 100%');
SELECT assert_accepted(
  $$INSERT INTO depreciable_assets (property_id, book, description, class, method,
      recovery_years, placed_in_service_on, original_basis, bonus_percent)
    VALUES ('33333333-3333-3333-3333-333333333333','federal','Dwelling','building',
            'macrs_gds_sl',27.5,'2019-04-11',312000,0)$$,
  'the federal book for the dwelling');

\echo ''
\echo 'section 1031 clocks'
SELECT assert_rejected(
  $$INSERT INTO exchanges (relinquished_property_id, closed_relinquished_on, identify_by, acquire_by)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-03-01','2026-04-30','2026-08-28')$$,
  'identification_window_is_45_days', 'a 45-day identification window typed as 60 days');
SELECT assert_rejected(
  $$INSERT INTO exchanges (relinquished_property_id, closed_relinquished_on, identify_by, acquire_by)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-03-01','2026-04-15','2026-09-30')$$,
  'acquisition_window_within_180_days', 'a 180-day acquisition window stretched');
SELECT assert_accepted(
  $$INSERT INTO exchanges (relinquished_property_id, closed_relinquished_on, identify_by, acquire_by)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-03-01',
            DATE '2026-03-01' + 45, DATE '2026-03-01' + 180)$$,
  'both statutory clocks computed correctly');

\echo ''
\echo 'component inventory'
SELECT assert_rejected(
  $$INSERT INTO components (property_id, component_type_id, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333','44444444-4444-4444-4444-444444444444',
            '22222222-2222-2222-2222-222222222222')$$,
  'install_known_or_bounded', 'a component with neither an install date nor a credible band');
SELECT assert_rejected(
  $$INSERT INTO components (property_id, component_type_id, provenance_id,
      installed_year_low, installed_year_high)
    VALUES ('33333333-3333-3333-3333-333333333333','44444444-4444-4444-4444-444444444444',
            '22222222-2222-2222-2222-222222222222',2016,2008)$$,
  'install_band_ordered', 'an inverted install band');
SELECT assert_accepted(
  $$INSERT INTO components (property_id, component_type_id, provenance_id,
      installed_year_low, installed_year_high)
    VALUES ('33333333-3333-3333-3333-333333333333','44444444-4444-4444-4444-444444444444',
            '22222222-2222-2222-2222-222222222222',2008,2016)$$,
  'an inferred install date with an honest band');

\echo ''
\echo 'ledger'
SELECT assert_rejected(
  $$INSERT INTO ledger_events (property_id, occurred_on, category, amount, is_capital)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-06-01','capital_improvement',-18500,true)$$,
  'capital_spending_explains_itself', 'capitalised spending with no betterment/adaptation/restoration rationale');
SELECT assert_accepted(
  $$INSERT INTO ledger_events (property_id, occurred_on, category, amount, is_capital,
      capitalisation_rationale)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-06-01','capital_improvement',-18500,true,
            'Restoration: full roof replacement, not a repair of a part')$$,
  'capitalised spending that states its rationale');

\echo ''
\echo 'leases'
SELECT assert_rejected(
  $$INSERT INTO leases (unit_id, starts_on, ends_on, rent)
    VALUES ('55555555-5555-5555-5555-555555555555','2026-01-01','2025-06-01',1450)$$,
  'lease_dates_ordered', 'a lease ending before it begins');
SELECT assert_rejected(
  $$INSERT INTO leases (unit_id, starts_on, rent, rent_due_day)
    VALUES ('55555555-5555-5555-5555-555555555555','2026-01-01',1450,45)$$,
  'due_day_is_a_day', 'a rent due day that is not a day of the month');
SELECT assert_rejected(
  $$INSERT INTO leases (unit_id, starts_on, rent, escalation)
    VALUES ('55555555-5555-5555-5555-555555555555','2026-01-01',1450,'fixed_percent')$$,
  'escalation_has_a_value', 'an escalation clause with no escalation value');
SELECT assert_accepted(
  $$INSERT INTO leases (unit_id, starts_on, ends_on, rent, escalation, escalation_value)
    VALUES ('55555555-5555-5555-5555-555555555555','2026-01-01','2026-12-31',1450,'fixed_percent',3.5)$$,
  'a well-formed twelve-month lease');

\echo ''
\echo 'insurance'
SELECT assert_rejected(
  $$INSERT INTO coverages (policy_id, description, limit_amount, deductible_amount, deductible_percent)
    VALUES ('66666666-6666-6666-6666-666666666666','Coverage A - Dwelling',350000,2500,0.02)$$,
  'one_deductible_form', 'a coverage stating both a flat and a percentage deductible');
SELECT assert_accepted(
  $$INSERT INTO coverages (policy_id, description, limit_amount, peril, deductible_percent)
    VALUES ('66666666-6666-6666-6666-666666666666','Coverage A - Dwelling',350000,'wind_hail',0.02)$$,
  'a percentage wind/hail deductible');

\echo ''
\echo 'jurisdiction rules'
SELECT assert_rejected(
  $$INSERT INTO jurisdiction_rules (jurisdiction_id, domain, code, citation, effective_from)
    VALUES ('77777777-7777-7777-7777-777777777777','security_deposit','deposit.return_days',
            'KRS 383.580','2026-01-01')$$,
  'rule_has_a_value', 'a rule carrying no value at all');
SELECT assert_rejected(
  $$INSERT INTO jurisdictions (level, name, parent_id)
    VALUES ('state','Kentucky',
            (SELECT id FROM jurisdictions WHERE level = 'federal'))$$,
  'state_required_below_federal', 'a sub-federal jurisdiction with no state');
SELECT assert_accepted(
  $$INSERT INTO jurisdiction_rules (jurisdiction_id, domain, code, value_numeric, citation, effective_from)
    VALUES ('77777777-7777-7777-7777-777777777777','security_deposit','deposit.return_days',
            30,'KRS 383.580 (URLTA; test fixture)','1984-07-13')$$,
  'a deposit rule with its statutory citation');

\echo ''
SELECT 'all constraint tests passed' AS result;

\echo ''
\echo 'the harness itself'
-- A helper that accepts any rejection certifies constraints that no longer
-- exist. Prove it distinguishes.
DO $$
DECLARE
  caught TEXT;
BEGIN
  BEGIN
    PERFORM assert_rejected(
      $q$INSERT INTO properties (entity_id, label, street_1, city, state, postal_code, kind)
         VALUES ('11111111-1111-1111-1111-111111111111','x','x','x','KY','41071','single_family')$q$,
      'plausible_year_built', 'a row that violates no constraint at all');
    RAISE EXCEPTION 'the harness accepted a statement that should have succeeded';
  EXCEPTION WHEN raise_exception THEN
    GET STACKED DIAGNOSTICS caught = MESSAGE_TEXT;
    IF caught NOT LIKE 'CONSTRAINT DID NOT BITE%' THEN RAISE; END IF;
    RAISE NOTICE '  ok      the harness reports a constraint that did not bite';
  END;

  BEGIN
    PERFORM assert_rejected(
      $q$INSERT INTO leases (unit_id, starts_on, ends_on, rent)
         VALUES ('55555555-5555-5555-5555-555555555555','2026-01-01','2025-06-01',1450)$q$,
      'due_day_is_a_day', 'a rejection by the wrong constraint');
    RAISE EXCEPTION 'the harness accepted the wrong constraint';
  EXCEPTION WHEN raise_exception THEN
    GET STACKED DIAGNOSTICS caught = MESSAGE_TEXT;
    IF caught NOT LIKE 'WRONG CONSTRAINT%' THEN RAISE; END IF;
    RAISE NOTICE '  ok      the harness rejects a pass for the wrong reason';
  END;
END $$;

\echo ''
\echo 'survival model parameters'
SELECT assert_rejected(
  $$INSERT INTO component_types (code, system, display_name, life_years_low, life_years_high,
      weibull_shape, weibull_scale_years)
    VALUES ('roof.x','roof','X',15,25,0.5,22)$$,
  'rising_hazard', 'a falling hazard, which no catalogued component has');
SELECT assert_rejected(
  $$INSERT INTO component_types (code, system, display_name, life_years_low, life_years_high,
      weibull_scale_years)
    VALUES ('roof.y','roof','Y',15,25,0)$$,
  'positive_characteristic_life', 'a zero characteristic life, which divides by zero');
SELECT assert_rejected(
  $$INSERT INTO component_types (code, system, display_name, life_years_low, life_years_high,
      weibull_scale_years)
    VALUES ('roof.z','roof','Z',25,15,22)$$,
  'life_band_ordered', 'an inverted service-life band');

\echo ''
\echo 'rates are decimals, not percentages'
SELECT assert_rejected(
  $$INSERT INTO debt_instruments (property_id, kind, original_principal, interest_rate,
      term_months, originated_on)
    VALUES ('33333333-3333-3333-3333-333333333333','conventional_mortgage',300000,6.75,360,'2019-04-11')$$,
  'annual_rate_check', 'an interest rate typed in percent form, which is a 675% rate');
SELECT assert_accepted(
  $$INSERT INTO debt_instruments (id, property_id, kind, original_principal, interest_rate,
      term_months, originated_on)
    VALUES ('88888888-8888-8888-8888-888888888888','33333333-3333-3333-3333-333333333333',
            'conventional_mortgage',300000,0.0675,360,'2019-04-11')$$,
  'the same rate in decimal form');

\echo ''
\echo 'uniqueness where the key is nullable'
SELECT assert_rejected(
  $$INSERT INTO jurisdictions (level, name) VALUES ('federal','United States');
    INSERT INTO jurisdictions (level, name) VALUES ('federal','United States')$$,
  'jurisdictions_level_name_state_parent_key',
  'a duplicate federal jurisdiction, whose state is NULL by design');
SELECT assert_rejected(
  $$INSERT INTO passive_loss_carryforwards (entity_id, tax_year, suspended_loss)
      VALUES ('11111111-1111-1111-1111-111111111111',2026,42000);
    INSERT INTO passive_loss_carryforwards (entity_id, tax_year, suspended_loss)
      VALUES ('11111111-1111-1111-1111-111111111111',2026,42000)$$,
  'passive_loss_carryforwards_entity_id_property_id_tax_year_key',
  'a duplicated entity-level carryforward, which would double-count on any SUM');

\echo ''
\echo 'the section 1031 replacement window'
SELECT assert_accepted(
  $$INSERT INTO exchanges (relinquished_property_id, closed_relinquished_on, identify_by,
      acquire_by, acquire_by_reason)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-11-15',
            DATE '2026-11-15' + 45,'2027-04-15','unextended return due date for 2026')$$,
  'a window shortened by the return due date, which is the statutory rule');
SELECT assert_rejected(
  $$INSERT INTO exchanges (relinquished_property_id, closed_relinquished_on, identify_by, acquire_by)
    VALUES ('33333333-3333-3333-3333-333333333333','2026-11-15',
            DATE '2026-11-15' + 45,'2027-04-15')$$,
  'shortened_window_says_why', 'a shortened window with no reason recorded');

\echo ''
\echo 'append-only history'
SELECT assert_rejected(
  $$UPDATE ledger_events SET amount = -1 WHERE id = (SELECT min(id) FROM ledger_events)$$,
  '<trigger>', 'an update to the ledger');
SELECT assert_rejected(
  $$DELETE FROM ledger_events WHERE id = (SELECT min(id) FROM ledger_events)$$,
  '<trigger>', 'a delete from the ledger');
SELECT assert_rejected(
  $$UPDATE jurisdiction_rules SET value_numeric = 60
    WHERE code = 'deposit.return_days'
      AND jurisdiction_id = '77777777-7777-7777-7777-777777777777'$$,
  '<trigger>', 'a rewrite of what an effective-dated rule said');
SELECT assert_accepted(
  $$UPDATE jurisdiction_rules SET effective_to = '2027-01-01'
    WHERE code = 'deposit.return_days'
      AND jurisdiction_id = '77777777-7777-7777-7777-777777777777'$$,
  'closing a rule out, which is the supported edit');

\echo ''
\echo 'updated_at is maintained'
DO $$
DECLARE
  before_at TIMESTAMPTZ;
  after_at  TIMESTAMPTZ;
BEGIN
  SELECT updated_at INTO before_at FROM properties
    WHERE id = '33333333-3333-3333-3333-333333333333';
  PERFORM pg_sleep(0.01);
  UPDATE properties SET label = 'renamed' WHERE id = '33333333-3333-3333-3333-333333333333';
  SELECT updated_at INTO after_at FROM properties
    WHERE id = '33333333-3333-3333-3333-333333333333';
  IF after_at <= before_at THEN
    RAISE EXCEPTION 'updated_at was not maintained: % is not after %', after_at, before_at;
  END IF;
  RAISE NOTICE '  ok      updated_at advances on write';
END $$;

\echo ''
\echo 'append-only survives TRUNCATE'
-- CASCADE on purpose: bank_transactions (011) now references the ledger, so
-- a bare TRUNCATE is refused by the FK before the trigger can speak. CASCADE
-- pushes past the FK and proves the append-only trigger itself still bites.
SELECT assert_rejected(
  $$TRUNCATE ledger_events CASCADE$$,
  '<trigger>', 'truncating the ledger');
SELECT assert_rejected(
  $$TRUNCATE audit_log$$,
  '<trigger>', 'truncating the audit log');

\echo ''
\echo 'one live lease per unit'
-- The constraint is partial on status, so the sitting lease must be live for
-- the overlap to be a conflict at all. A draft and an active lease may coexist.
INSERT INTO leases (unit_id, starts_on, ends_on, rent, status)
  VALUES ('55555555-5555-5555-5555-555555555555','2026-01-01','2026-12-31',1450,'active');
SELECT assert_rejected(
  $$INSERT INTO leases (unit_id, starts_on, ends_on, rent, status)
    VALUES ('55555555-5555-5555-5555-555555555555','2026-06-01','2027-05-31',1600,'active')$$,
  'one_live_lease_per_unit',
  'a second active lease overlapping the first on one unit');
SELECT assert_accepted(
  $$INSERT INTO leases (unit_id, starts_on, ends_on, rent, status)
    VALUES ('55555555-5555-5555-5555-555555555555','2027-01-01','2027-12-31',1600,'active')$$,
  'a lease beginning the day the previous one ends');

\echo ''
\echo 'append-only survives referential actions'
-- A referential action is a real UPDATE or DELETE, so the immutability trigger
-- fires for it too. Declaring SET NULL or CASCADE against an append-only table
-- makes the referenced row undeletable with an error naming a table the
-- operator never touched; RESTRICT says so honestly and at the right place.
INSERT INTO units (id, property_id, label)
  VALUES ('a1111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','B');
INSERT INTO ledger_events (property_id, unit_id, occurred_on, category, amount)
  VALUES ('33333333-3333-3333-3333-333333333333','a1111111-1111-1111-1111-111111111111',
          '2026-05-01','rent',1450);
SELECT assert_rejected(
  $$DELETE FROM units WHERE id = 'a1111111-1111-1111-1111-111111111111'$$,
  'ledger_events_unit_id_fkey',
  'deleting a unit the ledger still names');

\echo ''
\echo 'disposal, not deletion'
-- A property whose money has moved cannot be erased. Two references restrict
-- it independently -- the tax books and the ledger -- so each is proven on a
-- property carrying only that one.
INSERT INTO properties (id, entity_id, label, street_1, city, state, postal_code, kind)
  VALUES ('9c999999-9999-9999-9999-999999999999','11111111-1111-1111-1111-111111111111',
          'Ledger only','2 Nowhere','Newport','KY','41071','single_family');
INSERT INTO ledger_events (property_id, occurred_on, category, amount)
  VALUES ('9c999999-9999-9999-9999-999999999999','2026-05-01','rent',1450);
SELECT assert_rejected(
  $$DELETE FROM properties WHERE id = '9c999999-9999-9999-9999-999999999999'$$,
  'ledger_events_property_id_fkey',
  'deleting a property that has ledger history');

SELECT assert_rejected(
  $$DELETE FROM properties WHERE id = '33333333-3333-3333-3333-333333333333'$$,
  'depreciable_assets_property_id_fkey',
  'deleting a property that has an open tax book');

-- One entered in error, before any money moved, still deletes cleanly -- and
-- takes its units, leases, components and renewals with it. That cascade was
-- previously dead: back-references defaulted to NO ACTION, so the delete
-- aborted the moment a property had one renewal row.
INSERT INTO properties (id, entity_id, label, street_1, city, state, postal_code, kind)
  VALUES ('99999999-9999-9999-9999-999999999999','11111111-1111-1111-1111-111111111111',
          'Entered in error','1 Nowhere','Newport','KY','41071','single_family');
INSERT INTO units (id, property_id, label)
  VALUES ('9a999999-9999-9999-9999-999999999999','99999999-9999-9999-9999-999999999999','A');
INSERT INTO leases (id, unit_id, starts_on, rent)
  VALUES ('9b999999-9999-9999-9999-999999999999','9a999999-9999-9999-9999-999999999999',
          '2026-01-01',1200);
INSERT INTO lease_renewals (prior_lease_id, offered_on, offered_rent, prior_rent)
  VALUES ('9b999999-9999-9999-9999-999999999999','2026-10-01',1275,1200);
INSERT INTO components (property_id, component_type_id, provenance_id, installed_year_low)
  VALUES ('99999999-9999-9999-9999-999999999999','44444444-4444-4444-4444-444444444444',
          '22222222-2222-2222-2222-222222222222',2010);
SELECT assert_accepted(
  $$DELETE FROM properties WHERE id = '99999999-9999-9999-9999-999999999999'$$,
  'deleting a property with units, leases and renewals but no money');

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM lease_renewals) THEN
    RAISE EXCEPTION 'the cascade left orphaned renewal rows behind';
  END IF;
  RAISE NOTICE '  ok      the cascade reached every dependent row';
END $$;

\echo ''
\echo 'the seeds answer the questions they exist to answer'
-- State-pack content assertions live beside their packs in tests/packs/;
-- only pack-independent seed content is asserted here.
DO $$
DECLARE
  catalog_count INT;
  wet BOOLEAN;
BEGIN
  SELECT count(*) INTO catalog_count FROM component_types;
  IF catalog_count < 25 THEN
    RAISE EXCEPTION 'component catalog too thin: % rows', catalog_count;
  END IF;
  SELECT causes_water_damage INTO wet FROM component_types WHERE code = 'water_heater.tank';
  IF wet IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION 'the tank water heater must carry the water-damage flag';
  END IF;
  RAISE NOTICE '  ok      component catalog seeded (% types), water heater flagged wet', catalog_count;
END $$;

\echo ''
\echo 'jurisdictions are nationwide machinery'
-- Duplicate sub-county names are a fact of US geography (Ohio has ~20
-- 'Washington Township's in different counties); the key must admit them
-- under different parents and still refuse a true duplicate.
INSERT INTO jurisdictions (id, level, name, state, parent_id) VALUES
  ('e0000000-0000-4000-8000-000000000001', 'state', 'Zedstate', 'ZY',
   (SELECT id FROM jurisdictions WHERE level = 'federal'));
INSERT INTO jurisdictions (id, level, name, state, parent_id) VALUES
  ('e0000000-0000-4000-8000-000000000002', 'county', 'North County', 'ZY',
   'e0000000-0000-4000-8000-000000000001'),
  ('e0000000-0000-4000-8000-000000000003', 'county', 'South County', 'ZY',
   'e0000000-0000-4000-8000-000000000001');
SELECT assert_accepted(
  $$INSERT INTO jurisdictions (id, level, name, state, parent_id) VALUES
      ('e0000000-0000-4000-8000-000000000004', 'municipality', 'Washington Township', 'ZY',
       'e0000000-0000-4000-8000-000000000002'),
      ('e0000000-0000-4000-8000-000000000005', 'municipality', 'Washington Township', 'ZY',
       'e0000000-0000-4000-8000-000000000003')$$,
  'the same township name under two different counties');
SELECT assert_rejected(
  $$INSERT INTO jurisdictions (level, name, state, parent_id) VALUES
      ('municipality', 'Washington Township', 'ZY',
       'e0000000-0000-4000-8000-000000000002')$$,
  'jurisdictions_level_name_state_parent_key',
  'a true duplicate: same name under the same parent');
SELECT assert_rejected(
  $$INSERT INTO jurisdictions (level, name, state) VALUES
      ('municipality', 'Orphanville', 'ZY')$$,
  'parent_required_below_federal',
  'a sub-federal jurisdiction with no parent, which would dead-end the chain');
SELECT assert_rejected(
  $$INSERT INTO jurisdictions (level, name, state, parent_id) VALUES
      ('state', 'State of Zedstate', 'ZY',
       (SELECT id FROM jurisdictions WHERE level = 'federal'))$$,
  'one_state_row_per_state',
  'a second state-level row for the same state code');
DO $$
DECLARE
  chain_len INT;
BEGIN
  SELECT count(*) INTO chain_len FROM jurisdiction_chain(
    'e0000000-0000-4000-8000-000000000004');
  IF chain_len <> 4 THEN
    RAISE EXCEPTION 'jurisdiction_chain walked % rows for a 4-level chain', chain_len;
  END IF;
  RAISE NOTICE '  ok      jurisdiction_chain walks township -> county -> state -> federal';
END $$;
DELETE FROM jurisdictions WHERE state = 'ZY';

-- The resolver takes DISTINCT ON (property, code) over open rules; two OPEN
-- twins of the same rule at the same effective date would make resolution
-- arbitrary. No DDL key can allow the supersede-with-same-date correction
-- workflow AND refuse this, so the guard lives here: fail the build at the
-- exact moment two packs (or a pack and a correction) contradict each other.
DO $$
DECLARE
  twins INT;
BEGIN
  SELECT count(*) INTO twins FROM (
    SELECT jurisdiction_id, domain, code, effective_from
    FROM jurisdiction_rules
    WHERE superseded_by IS NULL
    GROUP BY jurisdiction_id, domain, code, effective_from
    HAVING count(*) > 1
  ) ambiguous;
  IF twins > 0 THEN
    RAISE EXCEPTION '% open rule twins share (jurisdiction, domain, code, effective_from)', twins;
  END IF;
  RAISE NOTICE '  ok      no open rule twins: resolution is deterministic';
END $$;

\echo ''
\echo 'bank import staging'
INSERT INTO bank_accounts (id, entity_id, nickname, kind)
  VALUES ('88888888-8888-8888-8888-888888888888',
          '11111111-1111-1111-1111-111111111111', 'Test Operating', 'checking');
INSERT INTO source_documents (id, kind, filename, content_hash)
  VALUES ('99999999-9999-9999-9999-999999999999', 'bank_statement', 'test.csv',
          repeat('a', 64));
INSERT INTO bank_import_batches (id, bank_account_id, source_document_id, format)
  VALUES ('aaaaaaaa-9999-9999-9999-999999999999',
          '88888888-8888-8888-8888-888888888888',
          '99999999-9999-9999-9999-999999999999', 'csv');
SELECT assert_accepted(
  $$INSERT INTO bank_transactions
      (batch_id, bank_account_id, posted_on, amount, description,
       normalised_description, dedupe_key)
    VALUES ('aaaaaaaa-9999-9999-9999-999999999999',
            '88888888-8888-8888-8888-888888888888',
            '2026-08-01', -92.40, 'DUKE ENERGY', 'duke energy', repeat('b', 64))$$,
  'a staged bank row');
SELECT assert_rejected(
  $$INSERT INTO bank_transactions
      (batch_id, bank_account_id, posted_on, amount, description,
       normalised_description, dedupe_key)
    VALUES ('aaaaaaaa-9999-9999-9999-999999999999',
            '88888888-8888-8888-8888-888888888888',
            '2026-08-01', -92.40, 'DUKE ENERGY', 'duke energy', repeat('b', 64))$$,
  'statement_rows_dedupe', 're-importing the same statement row');
SELECT assert_rejected(
  $$UPDATE bank_transactions SET disposition = 'accepted'
    WHERE dedupe_key = repeat('b', 64)$$,
  'posted_rows_link_their_event', 'an accepted row with no ledger event linked');
SELECT assert_rejected(
  $$INSERT INTO bank_transactions
      (batch_id, bank_account_id, posted_on, amount, description,
       normalised_description, dedupe_key)
    VALUES ('aaaaaaaa-9999-9999-9999-999999999999',
            '88888888-8888-8888-8888-888888888888',
            '2026-08-01', 0, 'VOID', 'void', repeat('c', 64))$$,
  'bank_rows_move_money', 'a zero-dollar bank row');
SELECT assert_rejected(
  $$INSERT INTO categorization_rules (pattern, category, min_amount, max_amount)
    VALUES ('x', 'repairs', 100, 50)$$,
  'rule_amount_window_ordered', 'an inverted rule amount window');
DELETE FROM bank_transactions WHERE bank_account_id = '88888888-8888-8888-8888-888888888888';
DELETE FROM bank_import_batches WHERE id = 'aaaaaaaa-9999-9999-9999-999999999999';
DELETE FROM source_documents WHERE id = '99999999-9999-9999-9999-999999999999';
DELETE FROM bank_accounts WHERE id = '88888888-8888-8888-8888-888888888888';

\echo ''
\echo 'reporting'
DO $$
DECLARE
  mapped INT;
  every_category INT;
BEGIN
  SELECT count(DISTINCT category) INTO mapped FROM schedule_e_map;
  SELECT count(*) INTO every_category
  FROM unnest(enum_range(NULL::ledger_category));
  IF mapped <> every_category THEN
    RAISE EXCEPTION 'schedule_e_map covers % of % ledger categories — an unmapped category silently vanishes from the report', mapped, every_category;
  END IF;
  RAISE NOTICE '  ok      every ledger category has a Schedule E answer (line or exclusion)';
END $$;
SELECT assert_rejected(
  $$INSERT INTO schedule_e_map (category, tax_year_from, line_no, line_label, citation)
    VALUES ('rent', 2030, 99, 'x', 'x')$$,
  'plausible_line', 'a Schedule E line number that does not exist');

\echo ''
\echo 'deadlines'
SELECT assert_rejected(
  $$INSERT INTO deadlines (kind, due_on, citation)
    VALUES ('custom', '2027-05-18', 'KRS 133.045')$$,
  'deadline_is_anchored', 'a deadline about nothing');
SELECT assert_rejected(
  $$INSERT INTO deadlines (kind, due_on, window_opens_on, property_id, citation)
    VALUES ('assessment_appeal_window', '2027-05-03', '2027-05-17',
            '33333333-3333-3333-3333-333333333333', 'KRS 133.045')$$,
  'window_precedes_due', 'a window that opens after it closes');
SELECT assert_rejected(
  $$INSERT INTO deadlines (kind, due_on, property_id, citation, status)
    VALUES ('custom', '2027-01-01', '33333333-3333-3333-3333-333333333333', 'test', 'done')$$,
  'done_records_when', 'a completed deadline with no completion date');
SELECT assert_accepted(
  $$INSERT INTO deadlines (kind, due_on, window_opens_on, property_id, citation, note)
    VALUES ('assessment_appeal_window', '2027-05-17', '2027-05-03',
            '33333333-3333-3333-3333-333333333333', 'KRS 133.045',
            'the first real-world test the platform must pass')$$,
  'the May 2027 inspection window, anchored and cited');

\echo ''
\echo 'hazards and market observations'
SELECT assert_rejected(
  $$INSERT INTO hazard_facts (property_id, kind, zone, base_flood_elevation_ft, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333', 'wildfire', 'B', 512,
            '22222222-2222-2222-2222-222222222222')$$,
  'flood_fields_are_flood_only', 'a wildfire fact carrying a flood elevation');
SELECT assert_accepted(
  $$INSERT INTO hazard_facts (property_id, kind, zone, in_special_flood_hazard_area, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333', 'flood', 'X', FALSE,
            '22222222-2222-2222-2222-222222222222')$$,
  'a FEMA zone X fact with provenance');
SELECT assert_rejected(
  $$INSERT INTO market_observations (property_id, metric, as_of, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333', 'rent_estimate', '2026-08-01',
            '22222222-2222-2222-2222-222222222222')$$,
  'observation_has_one_value', 'an observation with no value at all');
SELECT assert_rejected(
  $$INSERT INTO market_observations (property_id, metric, as_of, value_money, value_rate, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333', 'rent_estimate', '2026-08-01', 1450, 0.05,
            '22222222-2222-2222-2222-222222222222')$$,
  'observation_has_one_value', 'an observation claiming to be two kinds of value');
SELECT assert_accepted(
  $$INSERT INTO market_observations (property_id, metric, as_of, value_money, low_money, high_money, provenance_id)
    VALUES ('33333333-3333-3333-3333-333333333333', 'rent_estimate', '2026-08-01', 1495, 1400, 1590,
            '22222222-2222-2222-2222-222222222222')$$,
  'a banded rent estimate');
SELECT assert_rejected(
  $$INSERT INTO ingestion_runs (provider, status) VALUES ('rentcast', 'error')$$,
  'errors_explain_themselves', 'an ingestion error with no detail');

\echo ''
\echo 'every updated_at column has its trigger'
DO $$
DECLARE missing TEXT;
BEGIN
  SELECT string_agg(c.table_name, ', ') INTO missing
  FROM information_schema.columns c
  WHERE c.table_schema = 'public' AND c.column_name = 'updated_at'
    AND NOT EXISTS (
      SELECT 1 FROM pg_trigger t
      WHERE t.tgrelid = (quote_ident(c.table_name))::regclass
        AND NOT t.tgisinternal AND t.tgname LIKE '%set_updated_at');
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'updated_at declared but never maintained on: %', missing;
  END IF;
  RAISE NOTICE '  ok      every updated_at column has a maintaining trigger';
END $$;

\echo ''
\echo 'tax profiles, elections, disclosures'
SELECT assert_accepted(
  $$INSERT INTO tax_profiles (entity_id, tax_year, treatment, filing_status,
      magi_estimate, federal_marginal_rate, state_marginal_rate)
    VALUES ('11111111-1111-1111-1111-111111111111', 2026, 'disregarded',
            'married_filing_jointly', 165000, 0.32, 0.035)$$,
  'a profile carrying the rates every tax card must cite');
SELECT assert_rejected(
  $$INSERT INTO tax_profiles (entity_id, tax_year, treatment)
    VALUES ('11111111-1111-1111-1111-111111111111', 2026, 'partnership')$$,
  'tax_profiles_entity_id_tax_year_key', 'a second profile for the same entity-year');
SELECT assert_rejected(
  $$INSERT INTO tax_profiles (entity_id, tax_year, treatment, federal_marginal_rate)
    VALUES ('11111111-1111-1111-1111-111111111111', 2027, 'disregarded', 32)$$,
  'annual_rate_check', 'a marginal rate typed in percent form (32 for 32%)');
SELECT assert_rejected(
  $$INSERT INTO tax_profiles (entity_id, tax_year, treatment)
    VALUES ('11111111-1111-1111-1111-111111111111', 1970, 'disregarded')$$,
  'plausible_tax_year', 'a filing year before the modern code');

SELECT assert_accepted(
  $$INSERT INTO tax_elections (entity_id, tax_year, kind, parameters, citation)
    VALUES ('11111111-1111-1111-1111-111111111111', 2026, 'de_minimis_safe_harbor',
            '$2,500 per invoice', 'Treas. Reg. 1.263(a)-1(f)')$$,
  'an entity-wide de minimis election');
SELECT assert_rejected(
  $$INSERT INTO tax_elections (entity_id, tax_year, kind, citation)
    VALUES ('11111111-1111-1111-1111-111111111111', 2026, 'de_minimis_safe_harbor',
            'Treas. Reg. 1.263(a)-1(f)')$$,
  'tax_elections_entity_id_tax_year_kind_property_id_key',
  'the same entity-wide election recorded twice');

SELECT assert_accepted(
  $$INSERT INTO disclosures (property_id, kind, delivered_on, delivered_to, method, citation)
    VALUES ('33333333-3333-3333-3333-333333333333', 'lead_paint', '2026-01-01',
            'A. Resident', 'lease packet', '42 U.S.C. s.4852d')$$,
  'a delivered lead-paint disclosure with its statute');
DO $$
BEGIN
  BEGIN
    INSERT INTO disclosures (property_id, kind, delivered_on, delivered_to, citation)
    VALUES ('33333333-3333-3333-3333-333333333333', 'lead_paint', '2026-01-01', 'B. Resident', NULL);
    RAISE EXCEPTION 'CONSTRAINT DID NOT BITE: a disclosure without authority was accepted';
  EXCEPTION WHEN not_null_violation THEN
    RAISE NOTICE '  ok      rejected by NOT NULL: a disclosure without its citation';
  END;
END $$;

\echo ''
\echo 'sweep identity'
SELECT assert_rejected(
  $$INSERT INTO deadlines (kind, due_on, property_id, citation)
    VALUES ('assessment_appeal_window', '2027-05-17',
            '33333333-3333-3333-3333-333333333333', 'KRS 133.045')$$,
  'deadlines_sweep_identity',
  'the same generated deadline landing twice');
SELECT assert_accepted(
  $$INSERT INTO deadlines (kind, due_on, property_id, citation)
    VALUES ('assessment_appeal_window', '2028-05-15',
            '33333333-3333-3333-3333-333333333333', 'KRS 133.045')$$,
  'the following year is a different deadline');

