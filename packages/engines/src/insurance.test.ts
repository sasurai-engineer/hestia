import { money, rate, rateToString, toDecimalString, ZERO_RATE } from '@hestia/domain';
import { describe, expect, it } from 'vitest';
import { EngineError } from './errors.js';
import { loadFixtures } from './fixtures.js';
import { coinsuranceRecovery, lossOfRentsGap } from './insurance.js';

const fixtures = loadFixtures();

describe('coinsurance against the Python reference fixtures', () => {
  for (const fx of fixtures.coinsurance) {
    it(`loss ${fx.loss} carried ${fx.carriedLimit}`, () => {
      const result = coinsuranceRecovery({
        loss: money(fx.loss),
        carriedLimit: money(fx.carriedLimit),
        replacementCost: money(fx.replacementCost),
        coinsurancePercent: rate(fx.coinsurancePercent),
        deductible: money(fx.deductible),
      });
      expect(toDecimalString(result.recovery)).toBe(fx.recovery);
      expect(toDecimalString(result.retained)).toBe(fx.retained);
    });
  }

  it('names the penalty: carried over required', () => {
    const result = coinsuranceRecovery({
      loss: money('100000.00'),
      carriedLimit: money('240000.00'),
      replacementCost: money('400000.00'),
      coinsurancePercent: rate('0.8'),
      deductible: money('2500.00'),
    });
    expect(rateToString(result.complianceFactor)).toBe('0.75');
  });

  it('caps the recovery at the carried limit', () => {
    const result = coinsuranceRecovery({
      loss: money('300000.00'),
      carriedLimit: money('100000.00'),
      replacementCost: money('100000.00'),
      coinsurancePercent: rate('0.8'),
      deductible: money('0.00'),
    });
    expect(toDecimalString(result.recovery)).toBe('100000.00');
    expect(toDecimalString(result.retained)).toBe('200000.00');
  });

  it('floors the recovery at zero when the deductible swallows the loss', () => {
    const result = coinsuranceRecovery({
      loss: money('1000.00'),
      carriedLimit: money('100000.00'),
      replacementCost: money('100000.00'),
      coinsurancePercent: rate('0.8'),
      deductible: money('5000.00'),
    });
    expect(toDecimalString(result.recovery)).toBe('0.00');
    expect(toDecimalString(result.retained)).toBe('1000.00');
  });

  it('treats a zero coinsurance clause as no penalty at all', () => {
    const result = coinsuranceRecovery({
      loss: money('10000.00'),
      carriedLimit: money('50000.00'),
      replacementCost: money('400000.00'),
      coinsurancePercent: ZERO_RATE,
      deductible: money('0.00'),
    });
    expect(rateToString(result.complianceFactor)).toBe('1');
    expect(toDecimalString(result.recovery)).toBe('10000.00');
  });
});

describe('coinsurance validation', () => {
  const good = {
    loss: money('1.00'),
    carriedLimit: money('1.00'),
    replacementCost: money('1.00'),
    coinsurancePercent: rate('0.8'),
    deductible: money('0.00'),
  };
  it('rejects each inadmissible input', () => {
    expect(() => coinsuranceRecovery({ ...good, loss: money('-1.00') })).toThrow(
      /loss must not be negative/,
    );
    expect(() => coinsuranceRecovery({ ...good, carriedLimit: money('-1.00') })).toThrow(
      /carriedLimit must not be negative/,
    );
    expect(() => coinsuranceRecovery({ ...good, deductible: money('-1.00') })).toThrow(EngineError);
    expect(() => coinsuranceRecovery({ ...good, replacementCost: money('0.00') })).toThrow(
      /replacementCost must be positive/,
    );
    expect(() => coinsuranceRecovery({ ...good, coinsurancePercent: rate('1.1') })).toThrow(
      /fraction in \[0, 1\]/,
    );
    expect(() => coinsuranceRecovery({ ...good, coinsurancePercent: rate('-0.1') })).toThrow(
      EngineError,
    );
  });
});

describe('loss of rents', () => {
  it('prices the gap between coverage and a realistic rebuild', () => {
    const result = lossOfRentsGap({
      monthlyRent: money('1450.00'),
      monthsCovered: 12,
      rebuildMonths: 18,
    });
    expect(result.shortfallMonths).toBe(6);
    expect(toDecimalString(result.shortfall)).toBe('8700.00');
  });

  it('reports no gap when coverage reaches the rebuild', () => {
    const result = lossOfRentsGap({
      monthlyRent: money('1450.00'),
      monthsCovered: 18,
      rebuildMonths: 12,
    });
    expect(result.shortfallMonths).toBe(0);
    expect(toDecimalString(result.shortfall)).toBe('0.00');
  });

  it('rejects each inadmissible input', () => {
    expect(() =>
      lossOfRentsGap({ monthlyRent: money('-1.00'), monthsCovered: 1, rebuildMonths: 1 }),
    ).toThrow(/must not be negative/);
    expect(() =>
      lossOfRentsGap({ monthlyRent: money('1.00'), monthsCovered: 121, rebuildMonths: 1 }),
    ).toThrow(/monthsCovered/);
    expect(() =>
      lossOfRentsGap({ monthlyRent: money('1.00'), monthsCovered: 1, rebuildMonths: -1 }),
    ).toThrow(/rebuildMonths/);
  });
});
