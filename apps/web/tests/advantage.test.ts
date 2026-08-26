import { describe, expect, it } from 'vitest';
import { holdSellView, insuranceView } from '../src/lib/advantage';
import type { Financials } from '../src/lib/api';

const financials = (overrides: Partial<Financials>): Financials => ({
  property_id: 'p1',
  income_12mo: '17400.00',
  operating_expenses_12mo: '6200.00',
  noi_12mo: '11200.00',
  valuation: { value: '265000.00', source: 'owner_estimate', as_of: '2026-08-01' },
  debts: [
    {
      lender: 'Test Lender',
      original_principal: '190000.00',
      annual_rate: '0.0625',
      term_months: 360,
      months_elapsed: 30,
    },
  ],
  policies: [
    {
      id: 'pol1',
      kind: 'landlord_package',
      carrier: 'Test Mutual',
      effective_to: '2026-12-31',
      coinsurance_percent: '0.80000000',
      dwelling_limit: '210000.00',
      loss_of_rents_months: 12,
    },
  ],
  ...overrides,
});

describe('holdSellView', () => {
  it('computes the forward year with the note in the browser', () => {
    const view = holdSellView(financials({}), {
      appreciationPercent: 3,
      hurdlePercent: 8,
    });
    expect(view).not.toBeNull();
    if (!view) return;
    expect(view.noteBalance).not.toBeNull();
    // Equity = value − balance; balance after 30 payments < original.
    expect(Number(view.equity)).toBeGreaterThan(265000 - 190000);
    expect(Number(view.appreciation)).toBeCloseTo(7950, 0); // 3% of 265k
    expect(['hold', 'redeploy']).toContain(view.verdict);
    expect(Number(view.margin)).toBeCloseTo(Number(view.returnOnEquity) - 8, 1);
  });

  it('handles free-and-clear ownership and responds to assumptions', () => {
    const clear = holdSellView(financials({ debts: [] }), {
      appreciationPercent: 0,
      hurdlePercent: 4,
    });
    expect(clear).not.toBeNull();
    if (!clear) return;
    expect(clear.noteBalance).toBeNull();
    expect(clear.equity).toBe('265000.00');
    // ROE with zero appreciation is NOI / value ≈ 4.2% — beats a 4% hurdle,
    // loses to 8%: the verdict must move with the assumption.
    expect(clear.verdict).toBe('hold');
    const strict = holdSellView(financials({ debts: [] }), {
      appreciationPercent: 0,
      hurdlePercent: 8,
    });
    expect(strict?.verdict).toBe('redeploy');
  });

  it('aggregates every lien, not just the first', () => {
    const junior = {
      lender: 'Second Position',
      original_principal: '40000.00',
      annual_rate: '0.0900',
      term_months: 180,
      months_elapsed: 30,
    };
    const one = holdSellView(financials({}), { appreciationPercent: 3, hurdlePercent: 8 });
    const two = holdSellView(financials({ debts: [...financials({}).debts, junior] }), {
      appreciationPercent: 3,
      hurdlePercent: 8,
    });
    expect(one).not.toBeNull();
    expect(two).not.toBeNull();
    if (!one || !two) return;
    // The junior lien shrinks equity and the blended rate sits between the
    // two note rates — neither lien is ignored.
    expect(Number(two.noteBalance)).toBeGreaterThan(Number(one.noteBalance));
    expect(Number(two.equity)).toBeLessThan(Number(one.equity));
    expect(Number(two.cashFlow)).toBeLessThan(Number(one.cashFlow));
  });

  it('treats a fully amortized note as zero balance, zero blended rate', () => {
    const view = holdSellView(
      financials({
        debts: [
          {
            lender: 'Paid Off',
            original_principal: '190000.00',
            annual_rate: '0.0625',
            term_months: 360,
            months_elapsed: 360,
          },
        ],
      }),
      { appreciationPercent: 0, hurdlePercent: 8 },
    );
    expect(view).not.toBeNull();
    if (!view) return;
    expect(view.noteBalance).toBe('0.00');
    // Nothing owed: equity equals the full valuation, same as free and clear.
    expect(view.equity).toBe('265000.00');
  });

  it('names an underwater position instead of crashing the card', () => {
    const view = holdSellView(
      financials({
        valuation: { value: '150000.00', source: 'owner_estimate', as_of: '2026-08-01' },
      }),
      { appreciationPercent: 3, hurdlePercent: 8 },
    );
    expect(view).not.toBeNull();
    if (!view) return;
    expect(view.verdict).toBe('underwater');
    expect(Number(view.equity)).toBeLessThan(0);
    expect(view.returnOnEquity).toBe('—');
    expect(view.margin).toBe('—');
    expect(view.caveat).toContain('no equity');
  });

  it('never prints a negative-zero margin', () => {
    // Sweep hurdles in 0.1-point steps across the actual ROE so one of them
    // lands within rounding distance of zero from above.
    const base = holdSellView(financials({ debts: [] }), {
      appreciationPercent: 0,
      hurdlePercent: 4,
    });
    expect(base).not.toBeNull();
    if (!base) return;
    const roe = Number(base.returnOnEquity);
    for (let delta = 0; delta <= 0.05; delta += 0.01) {
      const view = holdSellView(financials({ debts: [] }), {
        appreciationPercent: 0,
        hurdlePercent: roe + delta,
      });
      expect(view?.margin).not.toBe('-0.0');
    }
  });

  it('declines to guess without a valuation', () => {
    expect(
      holdSellView(financials({ valuation: null }), {
        appreciationPercent: 3,
        hurdlePercent: 8,
      }),
    ).toBeNull();
  });
});

describe('insuranceView', () => {
  it('runs the coinsurance clause against the latest valuation', () => {
    const view = insuranceView(financials({}));
    expect(view).not.toBeNull();
    if (!view) return;
    // Required = 80% × 265,000 = 212,000; carried 210,000 → 99%.
    expect(view.compliancePercent).toBe('99');
    expect(view.adequate).toBe(false);
    expect(view.modeledLoss).toBe('66250.00'); // a one-quarter loss
    expect(Number(view.recovered)).toBeLessThan(66250);
    expect(Number(view.retained)).toBeGreaterThan(0);
    expect(view.replacementBasis).toContain('owner estimate');
    expect(view.lossOfRentsMonths).toBe(12);
  });

  it('floors a barely inadequate position below 100%', () => {
    const view = insuranceView(
      financials({
        policies: [
          {
            id: 'pol1',
            kind: 'landlord_package',
            carrier: null,
            effective_to: '2026-12-31',
            coinsurance_percent: null,
            // 99.9995% of the 80% requirement: rounding would print "100%"
            // on a red pill.
            dwelling_limit: '211999.00',
            loss_of_rents_months: null,
          },
        ],
      }),
    );
    expect(view).not.toBeNull();
    if (!view) return;
    expect(view.adequate).toBe(false);
    expect(view.compliancePercent).toBe('99');
  });

  it('reports a fully compliant position as adequate', () => {
    const view = insuranceView(
      financials({
        policies: [
          {
            id: 'pol1',
            kind: 'landlord_package',
            carrier: null,
            effective_to: '2026-12-31',
            coinsurance_percent: null, // defaults to the standard 80% clause
            dwelling_limit: '265000.00',
            loss_of_rents_months: null,
          },
        ],
      }),
    );
    expect(view).not.toBeNull();
    if (!view) return;
    expect(view.adequate).toBe(true);
    expect(view.compliancePercent).toBe('100');
    expect(view.lossOfRentsMonths).toBeNull();
  });

  it('declines without a dwelling limit or a valuation', () => {
    expect(insuranceView(financials({ policies: [] }))).toBeNull();
    expect(insuranceView(financials({ valuation: null }))).toBeNull();
    expect(
      insuranceView(
        financials({
          policies: [
            {
              id: 'x',
              kind: 'umbrella',
              carrier: null,
              effective_to: '2027-01-01',
              coinsurance_percent: null,
              dwelling_limit: null,
              loss_of_rents_months: null,
            },
          ],
        }),
      ),
    ).toBeNull();
  });
});
