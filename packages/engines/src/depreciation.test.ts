import { add, equals, money, rate, toDecimalString, ZERO_RATE, zero } from '@hestia/domain';
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  type DepreciationInput,
  type DepreciationYear,
  depreciate,
  KY_2001_S179,
  KY_2001_S179_CAP,
  KY_2001_S179_PHASEOUT_START,
  kentuckySection179Limit,
  MAX_LIFE_YEARS,
  percentSchedule,
  section179Limit,
  stateAddbackSchedule,
} from './depreciation.js';
import { EngineError } from './errors.js';
import { loadFixtures } from './fixtures.js';

const fixtures = loadFixtures();

const inputFrom = (fx: (typeof fixtures.depreciation)[number]): DepreciationInput => ({
  basis: money(fx.basis),
  method: fx.method,
  lifeYears: Number(fx.lifeYears),
  convention: fx.convention,
  bonusPercent: rate(fx.bonusPercent === '1/2' ? '0.5' : fx.bonusPercent),
  section179: money(fx.section179),
  ...(fx.placedInServiceMonth === null ? {} : { placedInServiceMonth: fx.placedInServiceMonth }),
  ...(fx.quarter === null ? {} : { quarter: fx.quarter }),
});

describe('depreciation against the Python reference fixtures', () => {
  for (const fx of fixtures.depreciation) {
    it(fx.label, () => {
      const result = depreciate(inputFrom(fx));
      expect(toDecimalString(result.bonus)).toBe(fx.bonus);
      expect(result.schedule.map((y) => toDecimalString(y.amount))).toEqual(fx.schedule);
      expect(equals(result.total, money(fx.basis))).toBe(true);
      expect(result.schedule.map((y) => y.year)).toEqual(fx.schedule.map((_, i) => i + 1));
    });
  }

  it('reproduces the exactly-exact Pub 946 five-year half-year column', () => {
    // 20 / 32 / 19.2 / 11.52 / 11.52 / 5.76 — the one table that is not rounded.
    const result = depreciate({
      basis: money('100000.00'),
      method: 'macrs_200db',
      lifeYears: 5,
      convention: 'half_year',
      bonusPercent: ZERO_RATE,
      section179: money('0.00'),
    });
    expect(result.schedule.map((y) => toDecimalString(y.amount))).toEqual([
      '20000.00',
      '32000.00',
      '19200.00',
      '11520.00',
      '11520.00',
      '5760.00',
    ]);
  });
});

describe('the dual book is the same asset under different law', () => {
  it('federal takes the year in full; Kentucky takes the schedule', () => {
    const shared = {
      basis: money('118000.00'),
      method: 'macrs_200db' as const,
      lifeYears: 5,
      convention: 'half_year' as const,
      section179: money('0.00'),
    };
    const federal = depreciate({ ...shared, bonusPercent: rate('1') });
    const kentucky = depreciate({ ...shared, bonusPercent: ZERO_RATE });
    expect(toDecimalString(federal.bonus)).toBe('118000.00');
    expect(federal.schedule).toHaveLength(0);
    expect(toDecimalString(kentucky.bonus)).toBe('0.00');
    expect(toDecimalString((kentucky.schedule[0] as DepreciationYear).amount)).toBe('23600.00');
    // Both books still recover the identical basis — only the timing differs.
    expect(equals(federal.total, kentucky.total)).toBe(true);
  });

  it('caps section 179 under each state profile in the fixtures', () => {
    for (const fx of fixtures.section179Limits) {
      const rule = { cap: fx.cap, phaseoutStart: fx.phaseoutStart };
      expect(toDecimalString(section179Limit(money(fx.totalPlacedInService), rule))).toBe(fx.limit);
    }
    expect(() => section179Limit(money('-1.00'), KY_2001_S179)).toThrow(/must not be negative/);
  });

  it('keeps the Kentucky wrapper pinned to the KY fixture rows', () => {
    const kyRows = fixtures.section179Limits.filter((fx) => fx.state === 'KY');
    expect(kyRows.length).toBeGreaterThan(0);
    for (const fx of kyRows) {
      expect(fx.cap).toBe(KY_2001_S179.cap);
      expect(fx.phaseoutStart).toBe(KY_2001_S179.phaseoutStart);
      expect(toDecimalString(kentuckySection179Limit(money(fx.totalPlacedInService)))).toBe(
        fx.limit,
      );
    }
    expect(toDecimalString(kentuckySection179Limit(money('0.00')))).toBe(KY_2001_S179_CAP);
    expect(KY_2001_S179_PHASEOUT_START).toBe('200000.00');
  });
});

describe('addback-recovery conformity (the Ohio shape)', () => {
  it('reproduces the Python-generated fixtures to the cent', () => {
    for (const fx of fixtures.conformityAddback) {
      const result = stateAddbackSchedule(money(fx.accelerated), {
        addbackNumerator: fx.numerator,
        addbackDenominator: fx.denominator,
        recoveryYears: fx.recoveryYears,
      });
      expect(toDecimalString(result.addback)).toBe(fx.addback);
      expect(result.recovery.map((row) => toDecimalString(row.amount))).toEqual(fx.recovery);
      expect(result.recovery.map((row) => row.year)).toEqual(
        fx.recovery.map((_, index) => index + 1),
      );
    }
  });

  it('recovers the addback exactly, whatever the rounding does', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 500_000_00 }),
        fc.integer({ min: 1, max: 12 }),
        fc.integer({ min: 1, max: 40 }),
        (cents, numerator, years) => {
          const accelerated = money((cents / 100).toFixed(2));
          const result = stateAddbackSchedule(accelerated, {
            addbackNumerator: numerator,
            addbackDenominator: 12,
            recoveryYears: years,
          });
          const recovered = result.recovery.reduce(
            (acc, row) => add(acc, row.amount),
            zero(accelerated.currency),
          );
          expect(equals(recovered, result.addback)).toBe(true);
        },
      ),
      { numRuns: 60 },
    );
  });

  it('names the argument that is out of bounds', () => {
    const oh = { addbackNumerator: 2, addbackDenominator: 3, recoveryYears: 6 };
    expect(() => stateAddbackSchedule(money('-1.00'), oh)).toThrow(/must not be negative/);
    expect(() => stateAddbackSchedule(money('1.00'), { ...oh, addbackNumerator: 4 })).toThrow(
      /addbackNumerator/,
    );
    expect(() => stateAddbackSchedule(money('1.00'), { ...oh, addbackDenominator: 0 })).toThrow(
      /addbackDenominator/,
    );
    expect(() => stateAddbackSchedule(money('1.00'), { ...oh, recoveryYears: 0 })).toThrow(
      /recoveryYears/,
    );
  });
});

describe('depreciation invariants', () => {
  const methods = [
    { method: 'macrs_200db', lifeYears: 5, convention: 'half_year' },
    { method: 'macrs_200db', lifeYears: 7, convention: 'half_year' },
    { method: 'macrs_150db', lifeYears: 15, convention: 'half_year' },
    { method: 'macrs_200db', lifeYears: 5, convention: 'mid_quarter' },
    { method: 'macrs_sl', lifeYears: 27.5, convention: 'mid_month' },
    { method: 'macrs_sl', lifeYears: 39, convention: 'mid_month' },
  ] as const;

  it('always recovers exactly the basis, never a cent more or less', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100_000_000 }),
        fc.integer({ min: 0, max: methods.length - 1 }),
        fc.integer({ min: 1, max: 12 }),
        fc.integer({ min: 0, max: 100 }),
        (basisCents, methodIndex, period, bonusPct) => {
          const shape = methods[methodIndex] as (typeof methods)[number];
          const basis = money(
            `${Math.floor(basisCents / 100)}.${String(basisCents % 100).padStart(2, '0')}`,
          );
          const result = depreciate({
            basis,
            method: shape.method,
            lifeYears: shape.lifeYears,
            convention: shape.convention,
            bonusPercent: rate(`0.${String(bonusPct).padStart(3, '0')}`.slice(0, 5)),
            section179: money('0.00'),
            ...(shape.convention === 'mid_month' ? { placedInServiceMonth: period } : {}),
            ...(shape.convention === 'mid_quarter' ? { quarter: ((period - 1) % 4) + 1 } : {}),
          });
          expect(equals(result.total, basis)).toBe(true);
        },
      ),
      { numRuns: 60 },
    );
  });

  it('every yearly amount is non-negative', () => {
    const result = depreciate({
      basis: money('0.03'),
      method: 'macrs_sl',
      lifeYears: 27.5,
      convention: 'mid_month',
      placedInServiceMonth: 12,
      bonusPercent: ZERO_RATE,
      section179: money('0.00'),
    });
    for (const year of result.schedule) {
      expect(toDecimalString(year.amount) >= '0.00').toBe(true);
    }
    expect(equals(result.total, money('0.03'))).toBe(true);
  });
});

describe('depreciation validation', () => {
  const good: DepreciationInput = {
    basis: money('10000.00'),
    method: 'macrs_200db',
    lifeYears: 5,
    convention: 'half_year',
    bonusPercent: ZERO_RATE,
    section179: money('0.00'),
  };
  it('rejects each inadmissible input by name', () => {
    expect(() => depreciate({ ...good, basis: money('0.00') })).toThrow(/basis must be positive/);
    expect(() => depreciate({ ...good, basis: money('-1.00') })).toThrow(EngineError);
    expect(() => depreciate({ ...good, section179: money('-1.00') })).toThrow(
      /between zero and the basis/,
    );
    expect(() => depreciate({ ...good, section179: money('10000.01') })).toThrow(EngineError);
    expect(() => depreciate({ ...good, bonusPercent: rate('1.01') })).toThrow(
      /fraction in \[0, 1\]/,
    );
    expect(() => depreciate({ ...good, bonusPercent: rate('-0.01') })).toThrow(EngineError);
    expect(() => percentSchedule({ ...good, lifeYears: 0 })).toThrow(/lifeYears must be in/);
    expect(() => percentSchedule({ ...good, lifeYears: MAX_LIFE_YEARS + 1 })).toThrow(EngineError);
    // The maximum itself is admissible.
    expect(() => percentSchedule({ ...good, lifeYears: MAX_LIFE_YEARS })).not.toThrow();
    expect(() => percentSchedule({ ...good, lifeYears: Number.NaN })).toThrow(EngineError);
    expect(() => percentSchedule({ ...good, method: 'macrs_sl' })).toThrow(/mid-month/);
    expect(() => percentSchedule({ ...good, method: 'macrs_sl', convention: 'mid_month' })).toThrow(
      /placedInServiceMonth/,
    );
    expect(() =>
      percentSchedule({
        ...good,
        method: 'macrs_sl',
        convention: 'mid_month',
        placedInServiceMonth: 13,
      }),
    ).toThrow(EngineError);
    expect(() => percentSchedule({ ...good, convention: 'mid_month' })).toThrow(
      /half-year or mid-quarter/,
    );
    expect(() => percentSchedule({ ...good, convention: 'mid_quarter' })).toThrow(/quarter/);
    expect(() => percentSchedule({ ...good, convention: 'mid_quarter', quarter: 5 })).toThrow(
      EngineError,
    );
  });

  it('accepts a 150db schedule and a full section 179 election', () => {
    const s179All = depreciate({ ...good, section179: money('10000.00') });
    expect(s179All.schedule).toHaveLength(0);
    expect(toDecimalString(s179All.total)).toBe('10000.00');
    const db150 = depreciate({ ...good, method: 'macrs_150db', lifeYears: 15 });
    expect(toDecimalString((db150.schedule[0] as DepreciationYear).amount)).toBe('500.00');
  });
});
