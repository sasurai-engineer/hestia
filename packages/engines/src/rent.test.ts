import { money, rate, toDecimalString } from '@hestia/domain';
import { describe, expect, it } from 'vitest';
import { EngineError } from './errors.js';
import { loadFixtures } from './fixtures.js';
import { dailyRent, evaluateRenewal, recommendRenewal } from './rent.js';

const fixtures = loadFixtures();
const context = { currentRent: money('1450.00'), turnCost: money('1800.00'), vacancyDays: 21 };

describe('renewal EV against the Python reference fixtures', () => {
  for (const fx of fixtures.rent) {
    it(`increase ${fx.increase} at pStay ${fx.pStay}`, () => {
      const evaluated = evaluateRenewal(
        {
          currentRent: money(fx.currentRent),
          turnCost: money(fx.turnCost),
          vacancyDays: fx.vacancyDays,
        },
        { increase: money(fx.increase), pStay: rate(fx.pStay) },
      );
      expect(toDecimalString(evaluated.expectedGain)).toBe(fx.expectedGain);
      expect(toDecimalString(evaluated.expectedTurnLoss)).toBe(fx.expectedTurnLoss);
      expect(toDecimalString(evaluated.expectedValue)).toBe(fx.expectedValue);
    });
  }

  it('computes daily rent on the 365 convention', () => {
    expect(toDecimalString(dailyRent(money('1450.00')))).toBe('47.67');
  });
});

describe('recommendRenewal', () => {
  it('picks the highest expected value', () => {
    const decision = recommendRenewal(context, [
      { increase: money('0.00'), pStay: rate('0.95') },
      { increase: money('50.00'), pStay: rate('0.85') },
      { increase: money('100.00'), pStay: rate('0.70') },
    ]);
    expect(decision.evaluations).toHaveLength(3);
    expect(toDecimalString(decision.recommended.increase)).toBe('50.00');
  });

  it('breaks a tie toward the smaller increase', () => {
    // pStay 0 makes EV independent of the increase: both lose the whole churn.
    const decision = recommendRenewal(context, [
      { increase: money('100.00'), pStay: rate('0') },
      { increase: money('50.00'), pStay: rate('0') },
    ]);
    expect(toDecimalString(decision.recommended.increase)).toBe('50.00');
  });

  it('keeps the first candidate when a later one ties without being smaller', () => {
    const decision = recommendRenewal(context, [
      { increase: money('50.00'), pStay: rate('0') },
      { increase: money('50.00'), pStay: rate('0') },
    ]);
    expect(decision.recommended).toBe(decision.evaluations[0]);
  });

  it('requires at least one candidate', () => {
    expect(() => recommendRenewal(context, [])).toThrow(/at least one candidate/);
  });
});

describe('rent validation', () => {
  it('rejects each inadmissible input', () => {
    const candidate = { increase: money('50.00'), pStay: rate('0.9') };
    expect(() => evaluateRenewal({ ...context, currentRent: money('-1.00') }, candidate)).toThrow(
      /must not be negative/,
    );
    expect(() => evaluateRenewal({ ...context, turnCost: money('-1.00') }, candidate)).toThrow(
      EngineError,
    );
    expect(() => evaluateRenewal({ ...context, vacancyDays: 366 }, candidate)).toThrow(
      /vacancyDays must be an integer/,
    );
    expect(() =>
      evaluateRenewal(context, { increase: money('-1.00'), pStay: rate('0.9') }),
    ).toThrow(/model concessions elsewhere/);
    expect(() => evaluateRenewal(context, { increase: money('1.00'), pStay: rate('1.1') })).toThrow(
      /probability in \[0, 1\]/,
    );
    expect(() =>
      evaluateRenewal(context, { increase: money('1.00'), pStay: rate('-0.1') }),
    ).toThrow(EngineError);
  });
});
