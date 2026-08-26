import { isZero, money, rate, rateToString, subtractRate, toDecimalString } from '@hestia/domain';
import { describe, expect, it } from 'vitest';
import { holdingPeriodFlows, irr, MAX_PERIODS, npv } from './cashflow.js';
import { EngineError } from './errors.js';
import { loadFixtures } from './fixtures.js';

const fixtures = loadFixtures();
const flows = fixtures.cashflow.flows.map((f) => money(f));

describe('npv against the Python reference fixtures', () => {
  it('matches at 4, 5 and 6 percent', () => {
    expect(toDecimalString(npv(rate('0.04'), flows))).toBe(fixtures.cashflow.npvAt4pct);
    expect(toDecimalString(npv(rate('0.05'), flows))).toBe(fixtures.cashflow.npvAt5pct);
    expect(toDecimalString(npv(rate('0.06'), flows))).toBe(fixtures.cashflow.npvAt6pct);
  });
});

describe('irr', () => {
  it('solves the five percent bond to within the fixture tolerance', () => {
    const solved = irr(flows);
    const distance = subtractRate(solved, rate(fixtures.cashflow.irrNear));
    const tolerance = rate(fixtures.cashflow.irrTolerance);
    const abs = distance.value.abs();
    expect(abs.lessThanOrEqualTo(tolerance.value)).toBe(true);
    // The defining property: NPV at the solved rate is zero to the cent.
    expect(isZero(npv(solved, flows))).toBe(true);
  });

  it('returns the bracket edge when the root sits exactly on it', () => {
    // NPV(-99.99%) = -$100 + $0.01 x 10^4 = 0 exactly.
    expect(rateToString(irr([money('-100.00'), money('0.01')]))).toBe('-0.9999');
    // NPV(1000%) = $1 - $11/11 = 0 exactly.
    expect(rateToString(irr([money('1.00'), money('-11.00')]))).toBe('10');
  });

  it('reports a root outside the bracket honestly', () => {
    // True IRR here is 999,900% — beyond any answer worth returning.
    expect(() => irr([money('-0.01'), money('100.00')])).toThrow(/no root in/);
  });

  it('requires a sign change among the flows', () => {
    expect(() => irr([money('1.00'), money('2.00')])).toThrow(/inflow and one outflow/);
    expect(() => irr([money('-1.00'), money('-2.00')])).toThrow(EngineError);
  });

  it('validates period count before looking at signs', () => {
    expect(() => irr([money('1.00')])).toThrow(/at least two periods/);
  });

  it('honours a bounded iteration budget', () => {
    const one = irr(flows, 1);
    // One bisection of [-0.9999, 10] can only refine once; the result is the
    // midpoint of the surviving half.
    expect(rateToString(one)).toBe('1.750075');
    expect(() => irr(flows, 0)).toThrow(/maxIterations/);
    expect(() => irr(flows, 1001)).toThrow(EngineError);
  });
});

describe('cashflow validation', () => {
  it('bounds the inputs', () => {
    expect(() => npv(rate('0.05'), [money('1.00')])).toThrow(/at least two periods/);
    expect(() => npv(rate('-1'), flows)).toThrow(/greater than -100%/);
    const tooMany = Array.from({ length: MAX_PERIODS + 2 }, () => money('1.00'));
    expect(() => npv(rate('0.05'), tooMany)).toThrow(/limited to/);
    // Exactly the maximum is admissible: the bound is a ceiling, not a cliff
    // one period early.
    const atMax = Array.from({ length: MAX_PERIODS + 1 }, () => money('0.01'));
    expect(() => npv(rate('0.05'), atMax)).not.toThrow();
  });
});

describe('holdingPeriodFlows', () => {
  it('lays out buy, hold, sell', () => {
    const laid = holdingPeriodFlows({
      initialInvestment: money('100000.00'),
      annualCashFlow: money('5000.00'),
      years: 4,
      netSaleProceeds: money('100000.00'),
    });
    expect(laid.map(toDecimalString)).toEqual([
      '-100000.00',
      '5000.00',
      '5000.00',
      '5000.00',
      '105000.00',
    ]);
  });

  it('rejects a non-positive investment and a bad year count', () => {
    expect(() =>
      holdingPeriodFlows({
        initialInvestment: money('0.00'),
        annualCashFlow: money('1.00'),
        years: 2,
        netSaleProceeds: money('1.00'),
      }),
    ).toThrow(/must be positive/);
    expect(() =>
      holdingPeriodFlows({
        initialInvestment: money('1.00'),
        annualCashFlow: money('1.00'),
        years: 0,
        netSaleProceeds: money('1.00'),
      }),
    ).toThrow(/years must be an integer/);
  });
});
