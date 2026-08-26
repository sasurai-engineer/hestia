import { equals, isZero, money, percent, rate, sum, toDecimalString } from '@hestia/domain';
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  type AmortizationRow,
  amortizationSchedule,
  balanceAfter,
  MAX_TERM_MONTHS,
  monthlyPayment,
} from './amortization.js';
import { EngineError } from './errors.js';
import { loadFixtures } from './fixtures.js';

const fixtures = loadFixtures();

describe('amortization against the Python reference fixtures', () => {
  for (const fx of fixtures.amortization) {
    it(`${fx.principal} at ${fx.annualRate} over ${fx.termMonths} months`, () => {
      const terms = {
        principal: money(fx.principal),
        annualRate: rate(fx.annualRate),
        termMonths: fx.termMonths,
      };
      const schedule = amortizationSchedule(terms);
      expect(toDecimalString(schedule.payment)).toBe(fx.payment);
      expect(toDecimalString(schedule.totalInterest)).toBe(fx.totalInterest);
      const first = schedule.rows[0] as AmortizationRow;
      const last = schedule.rows[schedule.rows.length - 1] as AmortizationRow;
      const twelfth = schedule.rows[11] as AmortizationRow;
      expect(toDecimalString(first.interest)).toBe(fx.month1Interest);
      expect(toDecimalString(first.principal)).toBe(fx.month1Principal);
      expect(toDecimalString(last.payment)).toBe(fx.finalPayment);
      expect(toDecimalString(twelfth.balance)).toBe(fx.balanceAfter12);
      expect(schedule.rows).toHaveLength(fx.termMonths);
      expect(isZero(last.balance)).toBe(true);
    });
  }
});

describe('amortization invariants', () => {
  it('retires the principal exactly, for any admissible note', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1_00, max: 100_000_000 }),
        fc.integer({ min: 0, max: 2000 }),
        fc.integer({ min: 1, max: 120 }),
        (principalCents, rateBps, termMonths) => {
          const terms = {
            principal: money(
              `${Math.floor(principalCents / 100)}.${String(principalCents % 100).padStart(2, '0')}`,
            ),
            annualRate: rate(`0.${String(rateBps).padStart(4, '0')}`),
            termMonths,
          };
          let schedule: ReturnType<typeof amortizationSchedule>;
          try {
            schedule = amortizationSchedule(terms);
          } catch (error) {
            // Tiny notes at high rates legitimately refuse to amortize.
            expect(error).toBeInstanceOf(EngineError);
            return;
          }
          const retired = sum(
            schedule.rows.map((r) => r.principal),
            'USD',
          );
          expect(equals(retired, terms.principal)).toBe(true);
          const tail = schedule.rows[schedule.rows.length - 1] as AmortizationRow;
          expect(isZero(tail.balance)).toBe(true);
        },
      ),
      { numRuns: 40 },
    );
  });

  it('clamps the tail rather than overdrawing the balance', () => {
    // Five cents over four zero-rate months: the ceil payment overshoots.
    const schedule = amortizationSchedule({
      principal: money('0.05'),
      annualRate: rate('0'),
      termMonths: 4,
    });
    expect(schedule.rows.map((r) => toDecimalString(r.principal))).toEqual([
      '0.02',
      '0.02',
      '0.01',
      '0.00',
    ]);
  });

  it('refuses a payment that does not amortize', () => {
    expect(() =>
      amortizationSchedule({
        principal: money('10.00'),
        annualRate: rate('0.15'),
        termMonths: 360,
      }),
    ).toThrow(/does not amortize/);
  });
});

describe('amortization validation', () => {
  const good = { principal: money('1000.00'), annualRate: percent('6'), termMonths: 12 };
  it('rejects each inadmissible input', () => {
    expect(() => monthlyPayment({ ...good, principal: money('0.00') })).toThrow(/must be positive/);
    expect(() => monthlyPayment({ ...good, annualRate: rate('1') })).toThrow(/decimal in \[0, 1\)/);
    expect(() => monthlyPayment({ ...good, annualRate: rate('-0.01') })).toThrow(EngineError);
    expect(() => monthlyPayment({ ...good, termMonths: 0 })).toThrow(
      /^termMonths must be an integer in \[1, 1200\]/,
    );
    expect(() => monthlyPayment({ ...good, termMonths: MAX_TERM_MONTHS + 1 })).toThrow(EngineError);
    expect(() => monthlyPayment({ ...good, termMonths: 2.5 })).toThrow(EngineError);
  });
});

describe('balanceAfter', () => {
  const terms = { principal: money('300000.00'), annualRate: rate('0.0675'), termMonths: 360 };
  it('walks the schedule', () => {
    expect(toDecimalString(balanceAfter(terms, 0))).toBe('300000.00');
    expect(toDecimalString(balanceAfter(terms, 12))).toBe('296802.83');
    expect(isZero(balanceAfter(terms, 360))).toBe(true);
    expect(() => balanceAfter(terms, 361)).toThrow(EngineError);
    expect(() => balanceAfter(terms, -1)).toThrow(/month must be an integer/);
    // Month zero still validates the terms; it must not skip straight to the
    // principal.
    expect(() => balanceAfter({ ...terms, principal: money('0.00') }, 0)).toThrow(
      /principal must be positive/,
    );
  });
});
