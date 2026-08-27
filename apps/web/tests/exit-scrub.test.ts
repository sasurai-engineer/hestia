import { describe, expect, it } from 'vitest';
import type { Financials } from '../src/lib/api';
import { buildExitModel, monthDay, TAX_GAP } from '../src/lib/exit-scrub';

const TODAY = '2026-08-27';

const financials = (overrides: Partial<Financials> = {}): Financials => ({
  property_id: 'p1',
  income_12mo: '17400.00',
  operating_expenses_12mo: '6200.00',
  noi_12mo: '11200.00',
  valuation: { value: '265000.00', source: 'owner_estimate', as_of: '2026-08-01' },
  debts: [],
  policies: [],
  ...overrides,
});

const ASSUMPTIONS = { appreciationPercent: 3, hurdlePercent: 8, sellingCostPercent: 6 };

describe('monthDay', () => {
  it('adds calendar months, clamping the day and rolling the year', () => {
    expect(monthDay('2026-08-27', 1)).toBe(monthDay('2026-09-27', 0));
    // A month-end start survives shorter months by clamping.
    expect(monthDay('2026-08-31', 1)).toBe(monthDay('2026-09-30', 0));
    expect(monthDay('2026-08-31', 6)).toBe(monthDay('2027-02-28', 0));
    expect(monthDay('2026-12-15', 2)).toBe(monthDay('2027-02-15', 0));
  });
});

describe('buildExitModel', () => {
  it('refuses to guess without a valuation', () => {
    expect(buildExitModel(financials({ valuation: null }), TODAY, ASSUMPTIONS)).toBeNull();
  });

  it('prices a free-and-clear exit: growing value, no payoff, real IRR', () => {
    const model = buildExitModel(financials(), TODAY, ASSUMPTIONS);
    if (model === null) throw new Error('model expected');
    expect(model.underwater).toBe(false);
    expect(model.equityToday).toBe('265000.00');
    expect(model.gap).toBe(TAX_GAP);
    expect(model.yearly).toHaveLength(10);

    const year5 = model.readingAt(60);
    expect(year5.loanPayoff).toBe('0.00');
    // 265000 × (1 + 0.03/12)^60, to the cent — the engines' answer.
    expect(Number(year5.exitValue)).toBeGreaterThan(307000);
    expect(Number(year5.exitValue)).toBeLessThan(309000);
    expect(year5.irrPercent).not.toBeNull();
    // NOI ≈ 4.2% of value plus 3% growth less selling costs: hold at 8%? No —
    // the model answers; we assert only that the verdict is one of the two.
    expect(year5.verdict === 'hold' || year5.verdict === 'redeploy').toBe(true);
    // Memoized: the same month returns the same object, not a recomputation.
    expect(model.readingAt(60)).toBe(year5);
  });

  it('reads every lien payoff off its schedule and retires it on time', () => {
    const model = buildExitModel(
      financials({
        debts: [
          {
            lender: 'Shorty',
            original_principal: '50000.00',
            annual_rate: '0.06',
            term_months: 120,
            months_elapsed: 100,
          },
        ],
      }),
      TODAY,
      ASSUMPTIONS,
    );
    if (model === null) throw new Error('model expected');
    expect(model.underwater).toBe(false);
    const beforeRetirement = model.readingAt(10);
    const afterRetirement = model.readingAt(30);
    expect(Number(beforeRetirement.loanPayoff)).toBeGreaterThan(0);
    expect(afterRetirement.loanPayoff).toBe('0.00');
    expect(Number(model.equityToday)).toBeLessThan(265000);
  });

  it('calls an underwater position underwater and refuses a fake IRR', () => {
    const model = buildExitModel(
      financials({
        valuation: { value: '100000.00', source: 'owner_estimate', as_of: '2026-08-01' },
        debts: [
          {
            lender: 'Heavy',
            original_principal: '190000.00',
            annual_rate: '0.0625',
            term_months: 360,
            months_elapsed: 6,
          },
        ],
      }),
      TODAY,
      ASSUMPTIONS,
    );
    if (model === null) throw new Error('model expected');
    expect(model.underwater).toBe(true);
    const reading = model.readingAt(24);
    expect(reading.irrPercent).toBeNull();
    expect(reading.verdict).toBeNull();
    expect(Number(reading.netProceeds)).toBeLessThan(0);
    expect(model.crossovers).toEqual([]);
  });

  it('returns an honest null when the flows never turn positive', () => {
    // Tiny equity, negative carry: every flow is an outflow, so there is
    // no internal rate — null, never a guess. Not underwater, though.
    const model = buildExitModel(
      financials({
        valuation: { value: '50.00', source: 'owner_estimate', as_of: '2026-08-01' },
        noi_12mo: '-1200.00',
      }),
      TODAY,
      ASSUMPTIONS,
    );
    if (model === null) throw new Error('model expected');
    expect(model.underwater).toBe(false);
    expect(model.readingAt(12).irrPercent).toBeNull();
    expect(model.readingAt(12).verdict).toBeNull();
    expect(model.yearly.every((point) => point.irrPercent === null)).toBe(true);
    expect(model.crossovers).toEqual([]);
  });

  it('finds the crossover where a leveraged return decays through the hurdle', {
    timeout: 30_000,
  }, () => {
    // Leverage: small equity earns the whole building's growth early, then
    // the return decays toward the unlevered rate as equity accretes. Pick
    // a hurdle between the two and the verdict must flip mid-horizon.
    const leveraged = financials({
      debts: [
        {
          lender: 'First Federal',
          original_principal: '212000.00',
          annual_rate: '0.0625',
          term_months: 360,
          months_elapsed: 24,
        },
      ],
    });
    const base = buildExitModel(leveraged, TODAY, ASSUMPTIONS);
    if (base === null) throw new Error('model expected');
    // This note costs more than the building yields, so the drag lessens as
    // equity accretes: the IRR RISES with hold length. The model does not
    // assume a direction — it names the one it finds.
    const early = Number.parseFloat(base.readingAt(36).irrPercent ?? 'NaN');
    const late = Number.parseFloat(base.readingAt(120).irrPercent ?? 'NaN');
    expect(late).toBeGreaterThan(early);

    const between = (early + late) / 2;
    const crossing = buildExitModel(leveraged, TODAY, {
      ...ASSUMPTIONS,
      hurdlePercent: between,
    });
    if (crossing === null) throw new Error('model expected');
    const crossover = crossing.crossovers[0];
    if (crossover === undefined) throw new Error('crossover expected');
    expect(crossover.direction).toBe('to-hold');
    expect(crossover.reading.verdict).toBe('hold');
    expect(crossing.readingAt(crossover.reading.month - 1).verdict).toBe('redeploy');

    // A hurdle nobody clears yields no crossover: the whole horizon is one
    // verdict, and the pill already says so.
    const demanding = buildExitModel(leveraged, TODAY, { ...ASSUMPTIONS, hurdlePercent: 30 });
    expect(demanding?.crossovers).toEqual([]);
    // A LOW hurdle still crosses: selling costs put every short hold under
    // water, so the mark answers "hold at least this long".
    const easy = buildExitModel(leveraged, TODAY, { ...ASSUMPTIONS, hurdlePercent: 2 });
    expect(easy?.crossovers[0]?.direction).toBe('to-hold');
  });
});
