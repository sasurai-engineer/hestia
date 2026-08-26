import { money, percent, toDecimalString } from '@hestia/domain';
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { disposalAnalysis, disposalTax } from './disposal.js';
import { EngineError } from './errors.js';
import { loadFixtures } from './fixtures.js';

const fixtures = loadFixtures();

describe('disposal against the Python reference fixtures', () => {
  for (const fx of fixtures.disposal) {
    it(fx.label, () => {
      const result = disposalAnalysis({
        salePrice: money(fx.salePrice),
        sellingCosts: money(fx.sellingCosts),
        originalBasis: money(fx.originalBasis),
        depreciationTaken: money(fx.depreciationTaken),
        kind: fx.kind,
      });
      expect(toDecimalString(result.gain)).toBe(fx.gain);
      expect(toDecimalString(result.loss)).toBe(fx.loss);
      expect(toDecimalString(result.ordinaryRecapture)).toBe(fx.ordinaryRecapture);
      expect(toDecimalString(result.unrecaptured1250)).toBe(fx.unrecaptured1250);
      expect(toDecimalString(result.capitalGain)).toBe(fx.capitalGain);
    });
  }

  it('prices the plan worked example: $29,500 of 25% tax plus $12,000 of capital', () => {
    const result = disposalAnalysis({
      salePrice: money('500000.00'),
      sellingCosts: money('40000.00'),
      originalBasis: money('400000.00'),
      depreciationTaken: money('118000.00'),
      kind: 'real_property_sl',
    });
    const tax = disposalTax(result, {
      ordinary: percent('32'),
      capital: percent('20'),
      unrecaptured1250: percent('25'),
    });
    expect(toDecimalString(tax)).toBe('41500.00');
  });
});

describe('disposal invariants', () => {
  it('the split always reassembles the gain, and recapture never exceeds depreciation', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 100_000_000 }),
        fc.integer({ min: 0, max: 10_000_000 }),
        fc.integer({ min: 1, max: 100_000_000 }),
        fc.integer({ min: 0, max: 100 }),
        fc.boolean(),
        (sale, costs, basis, deprPct, personal) => {
          const cents = (n: number): string =>
            `${Math.floor(n / 100)}.${String(n % 100).padStart(2, '0')}`;
          const depreciation = Math.floor((basis * deprPct) / 100);
          const result = disposalAnalysis({
            salePrice: money(cents(sale)),
            sellingCosts: money(cents(costs)),
            originalBasis: money(cents(basis)),
            depreciationTaken: money(cents(depreciation)),
            kind: personal ? 'personal_property' : 'real_property_sl',
          });
          const parts =
            BigInt(result.ordinaryRecapture.minor) +
            BigInt(result.unrecaptured1250.minor) +
            BigInt(result.capitalGain.minor);
          expect(parts).toBe(result.gain.minor);
          expect(result.ordinaryRecapture.minor <= BigInt(depreciation)).toBe(true);
          expect(result.unrecaptured1250.minor <= BigInt(depreciation)).toBe(true);
          // Exactly one of gain/loss is nonzero, never both.
          expect(result.gain.minor === 0n || result.loss.minor === 0n).toBe(true);
        },
      ),
      { numRuns: 80 },
    );
  });
});

describe('disposal validation', () => {
  const good = {
    salePrice: money('100.00'),
    sellingCosts: money('0.00'),
    originalBasis: money('50.00'),
    depreciationTaken: money('10.00'),
    kind: 'personal_property' as const,
  };
  it('rejects negatives by name and over-depreciation outright', () => {
    expect(() => disposalAnalysis({ ...good, salePrice: money('-1.00') })).toThrow(
      /salePrice must not be negative/,
    );
    expect(() => disposalAnalysis({ ...good, sellingCosts: money('-1.00') })).toThrow(
      /sellingCosts must not be negative/,
    );
    expect(() => disposalAnalysis({ ...good, originalBasis: money('-1.00') })).toThrow(EngineError);
    expect(() => disposalAnalysis({ ...good, depreciationTaken: money('-1.00') })).toThrow(
      EngineError,
    );
    expect(() => disposalAnalysis({ ...good, depreciationTaken: money('51.00') })).toThrow(
      /cannot exceed the original basis/,
    );
  });
});
