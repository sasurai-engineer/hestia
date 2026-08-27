-- ===========================================================================
--  Seed — the deposit-interest formula, named by the pack
--
--  ADR 0003: states are data. Knowing that Ohio owes interest is a rule;
--  knowing HOW to compute it is a second rule naming a registered builder,
--  exactly as `appeal.window.calendar` names a registered window builder.
--  Without this the API would have to branch on a state literal, which the
--  ratchet in scripts/check_state_literals.sh exists to refuse.
--
--  The builders live in services/api/hestia_api/deposit.py and a key with no
--  builder is a named coverage gap, never a silent default — the same
--  contract calendar_key_unregistered already has.
-- ===========================================================================

INSERT INTO jurisdiction_rules
  (jurisdiction_id, domain, code, value_numeric, value_text, citation, effective_from)
SELECT id, 'security_deposit', 'deposit.interest_formula',
       NULL, 'us-oh.excess-over-month-rent',
       'ORC 5321.16(A) — 5% per annum on the excess over the greater of $50 '
       'or one month''s rent, held six months or more',
       DATE '1974-11-04'
FROM jurisdictions WHERE level = 'state' AND state = 'OH';
