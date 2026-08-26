import {
  greaterThan,
  greaterThanRate,
  isNegative,
  isPositive,
  isZero,
  lessThanRate,
  type Money,
  min,
  multiply,
  ONE_RATE,
  type Rate,
  Rounding,
  rate,
  ratio,
  subtract,
  ZERO_RATE,
  zero,
} from '@hestia/domain';
import { assertIntInRange, EngineError } from './errors.js';

/**
 * The coinsurance penalty — the clause nobody reads and everybody is
 * penalised by. Insure below the required share of replacement cost and the
 * carrier pays a proportionally reduced share of even a small partial loss:
 *
 *   recovery = min(limit, loss × min(1, carried / (coinsurance% × RCV)) − deductible)
 */
export interface CoinsuranceInput {
  readonly loss: Money;
  readonly carriedLimit: Money;
  readonly replacementCost: Money;
  /** e.g. 0.8 for an 80% coinsurance clause. */
  readonly coinsurancePercent: Rate;
  readonly deductible: Money;
}

export interface CoinsuranceResult {
  /** carried / required, capped at 1. */
  readonly complianceFactor: Rate;
  readonly recovery: Money;
  /** loss − recovery: what the owner absorbs. */
  readonly retained: Money;
}

export const coinsuranceRecovery = (input: CoinsuranceInput): CoinsuranceResult => {
  for (const [name, value] of [
    ['loss', input.loss],
    ['carriedLimit', input.carriedLimit],
    ['deductible', input.deductible],
  ] as const) {
    if (isNegative(value)) {
      throw new EngineError(`${name} must not be negative`);
    }
  }
  if (!isPositive(input.replacementCost)) {
    throw new EngineError('replacementCost must be positive');
  }
  if (
    lessThanRate(input.coinsurancePercent, ZERO_RATE) ||
    greaterThanRate(input.coinsurancePercent, ONE_RATE)
  ) {
    throw new EngineError('coinsurancePercent must be a fraction in [0, 1]');
  }

  const currency = input.loss.currency;
  const required = multiply(input.replacementCost, input.coinsurancePercent, Rounding.HalfUp);
  let factor: Rate;
  if (isZero(required) || !greaterThan(required, input.carriedLimit)) {
    factor = ONE_RATE;
  } else {
    factor = ratio(input.carriedLimit, required);
  }
  const covered = multiply(input.loss, factor, Rounding.HalfEven);
  const afterDeductible = subtract(covered, input.deductible);
  const recovery = isNegative(afterDeductible)
    ? zero(currency)
    : min(afterDeductible, input.carriedLimit);
  return { complianceFactor: factor, recovery, retained: subtract(input.loss, recovery) };
};

/**
 * Loss-of-rents adequacy: the months a policy pays against a realistic rebuild.
 * The cap is routinely shorter than a real rebuild after a total loss, and the
 * gap is invisible until the day it is catastrophic.
 */
export interface LossOfRentsInput {
  readonly monthlyRent: Money;
  readonly monthsCovered: number;
  readonly rebuildMonths: number;
}

export interface LossOfRentsResult {
  readonly shortfallMonths: number;
  readonly shortfall: Money;
}

export const lossOfRentsGap = (input: LossOfRentsInput): LossOfRentsResult => {
  if (isNegative(input.monthlyRent)) {
    throw new EngineError('monthlyRent must not be negative');
  }
  assertIntInRange(input.monthsCovered, 'monthsCovered', 0, 120);
  assertIntInRange(input.rebuildMonths, 'rebuildMonths', 0, 120);
  const shortfallMonths = Math.max(0, input.rebuildMonths - input.monthsCovered);
  return {
    shortfallMonths,
    shortfall: multiply(input.monthlyRent, rate(String(shortfallMonths)), Rounding.HalfEven),
  };
};
