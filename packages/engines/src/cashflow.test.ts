import { isZero, money, rate, rateToString, subtractRate, toDecimalString } from '@hestia/domain';
import { describe, expect, it } from 'vitest';
import {
  holdingPeriodFlows,
  irr,
  irrBracketCeiling,
  irrBracketFloor,
  MAX_PERIODS,
  npv,
} from './cashflow.js';
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

describe('irr over long series (#68)', () => {
  it('solves the 120-month par bond to its exact coupon rate', () => {
    const monthly = fixtures.cashflowMonthly.flows.map((f) => money(f));
    const solved = irr(monthly);
    const distance = subtractRate(solved, rate(fixtures.cashflowMonthly.irrNear));
    expect(
      distance.value.abs().lessThanOrEqualTo(rate(fixtures.cashflowMonthly.irrTolerance).value),
    ).toBe(true);
    expect(isZero(npv(solved, monthly))).toBe(true);
  });

  // 120 bisections over 600 exact terms outlast the 5s default when verify
  // runs every package in parallel — the same lesson the exit tests learned.
  it('keeps the full promise MAX_PERIODS makes: 600 periods solve', { timeout: 30_000 }, () => {
    // A 600-period par bond at 0.1% per period — IRR is the coupon rate by
    // construction, at the very edge of what the engine advertises.
    const flows = [
      money('-100000.00'),
      ...Array.from({ length: MAX_PERIODS - 1 }, () => money('100.00')),
      money('100100.00'),
    ];
    const solved = irr(flows);
    const distance = subtractRate(solved, rate('0.001'));
    expect(distance.value.abs().lessThanOrEqualTo(rate('0.000001').value)).toBe(true);
  });

  it('lowers the ceiling exactly at each proven boundary', () => {
    const ceilingAt = (periods: number) => rateToString(irrBracketCeiling(periods));
    expect(ceilingAt(2)).toBe('10');
    expect(ceilingAt(240)).toBe('10');
    expect(ceilingAt(241)).toBe('4');
    expect(ceilingAt(357)).toBe('4');
    expect(ceilingAt(358)).toBe('2');
    expect(ceilingAt(524)).toBe('2');
    expect(ceilingAt(525)).toBe('1.5');
    expect(ceilingAt(600)).toBe('1.5');
  });

  it('widens the floor exactly at each proven boundary', () => {
    const floorAt = (periods: number) => rateToString(irrBracketFloor(periods));
    expect(floorAt(2)).toBe('-0.9999');
    expect(floorAt(62)).toBe('-0.9999');
    expect(floorAt(63)).toBe('-0.999');
    expect(floorAt(83)).toBe('-0.999');
    expect(floorAt(84)).toBe('-0.99');
    expect(floorAt(125)).toBe('-0.99');
    expect(floorAt(126)).toBe('-0.9');
    expect(floorAt(250)).toBe('-0.9');
    expect(floorAt(251)).toBe('-0.6');
    expect(floorAt(600)).toBe('-0.6');
  });

  it('reads the floor from the true period count, boundary-exact', () => {
    // 62 periods sit on the last '-0.9999' rung; a count off by even one
    // period in either direction would name '-99.90%' here instead.
    const flows = [money('100.00'), ...Array.from({ length: 62 }, () => money('-1000000.00'))];
    expect(() => irr(flows)).toThrow('irr has no root in [-99.99%, 1000.00%] for these flows');
  });

  it('reads the ceiling from the true period count, boundary-exact', () => {
    // 240 periods sit on the last '10' rung; a count off by one period
    // in either direction would name '400.00%' here instead.
    const flows = [money('100.00'), ...Array.from({ length: 240 }, () => money('-1000000.00'))];
    expect(() => irr(flows)).toThrow('irr has no root in [-90.00%, 1000.00%] for these flows');
  });

  it('names the widened bracket when a long series has no root inside it', () => {
    // The single inflow comes FIRST, so no discounting can rescue it: the
    // true IRR is ~999,900% per period, far beyond the ceiling.
    const flows = [money('100.00'), ...Array.from({ length: 100 }, () => money('-1000000.00'))];
    expect(() => irr(flows)).toThrow('irr has no root in [-99.00%, 1000.00%] for these flows');
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
