import {
  greaterThan,
  isNegative,
  type Money,
  multiply,
  negate,
  type Rate,
  Rounding,
  subtract,
  sum,
  zero,
} from '@hestia/domain';
import { EngineError } from './errors.js';

/**
 * The split of a disposition's gain — the part of a cost segregation study
 * nobody sells. Accelerated basis comes back at sale: §1245 recapture at
 * ordinary rates on personal property, unrecaptured §1250 at up to 25% on the
 * straight-line depreciation taken on real property, and only the remainder is
 * long-term capital gain. A study modelled to April instead of to the exit
 * reports the wrong number.
 */
export type DisposedAssetKind = 'personal_property' | 'real_property_sl';

export interface DisposalInput {
  readonly salePrice: Money;
  readonly sellingCosts: Money;
  readonly originalBasis: Money;
  readonly depreciationTaken: Money;
  readonly kind: DisposedAssetKind;
}

export interface DisposalResult {
  readonly amountRealized: Money;
  readonly adjustedBasis: Money;
  readonly gain: Money;
  /** §1231 loss when the disposition is under water; zero otherwise. */
  readonly loss: Money;
  /** §1245 — ordinary rates. Nonzero only for personal property. */
  readonly ordinaryRecapture: Money;
  /** Unrecaptured §1250 — capped at 25%. Nonzero only for real property. */
  readonly unrecaptured1250: Money;
  /** What is left for the long-term capital rate. */
  readonly capitalGain: Money;
}

const minMoney = (a: Money, b: Money): Money => (greaterThan(a, b) ? b : a);

export const disposalAnalysis = (input: DisposalInput): DisposalResult => {
  for (const [name, value] of [
    ['salePrice', input.salePrice],
    ['sellingCosts', input.sellingCosts],
    ['originalBasis', input.originalBasis],
    ['depreciationTaken', input.depreciationTaken],
  ] as const) {
    if (isNegative(value)) {
      throw new EngineError(`${name} must not be negative`);
    }
  }
  if (greaterThan(input.depreciationTaken, input.originalBasis)) {
    throw new EngineError('depreciationTaken cannot exceed the original basis');
  }

  const currency = input.salePrice.currency;
  const amountRealized = subtract(input.salePrice, input.sellingCosts);
  const adjustedBasis = subtract(input.originalBasis, input.depreciationTaken);
  const gain = subtract(amountRealized, adjustedBasis);

  if (isNegative(gain)) {
    return {
      amountRealized,
      adjustedBasis,
      gain: zero(currency),
      loss: negate(gain),
      ordinaryRecapture: zero(currency),
      unrecaptured1250: zero(currency),
      capitalGain: zero(currency),
    };
  }

  const recaptured = minMoney(gain, input.depreciationTaken);
  const capitalGain = subtract(gain, recaptured);
  const personal = input.kind === 'personal_property';
  return {
    amountRealized,
    adjustedBasis,
    gain,
    loss: zero(currency),
    ordinaryRecapture: personal ? recaptured : zero(currency),
    unrecaptured1250: personal ? zero(currency) : recaptured,
    capitalGain,
  };
};

export interface DisposalTaxRates {
  readonly ordinary: Rate;
  readonly capital: Rate;
  /** The §1250 ceiling; 25% federally, but the book supplies it. */
  readonly unrecaptured1250: Rate;
}

/** The federal tax the split implies, each piece rounded HalfEven. */
export const disposalTax = (result: DisposalResult, rates: DisposalTaxRates): Money =>
  sum(
    [
      multiply(result.ordinaryRecapture, rates.ordinary, Rounding.HalfEven),
      multiply(result.unrecaptured1250, rates.unrecaptured1250, Rounding.HalfEven),
      multiply(result.capitalGain, rates.capital, Rounding.HalfEven),
    ],
    result.gain.currency,
  );
