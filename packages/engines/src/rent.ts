import {
  add,
  divide,
  greaterThan,
  greaterThanRate,
  isNegative,
  lessThan,
  lessThanRate,
  type Money,
  multiply,
  ONE_RATE,
  type Rate,
  Rounding,
  rate,
  subtract,
  subtractRate,
  ZERO_RATE,
} from '@hestia/domain';
import { assertIntInRange, EngineError } from './errors.js';

/**
 * The renewal-offer expected value:
 *
 *   EV(Δ) = 12 × Δ × P(stay | Δ)  −  P(leave | Δ) × (turn cost + vacancy days × daily rent)
 *
 * The first half is what the increase earns if the resident stays; the second
 * is what the refusal costs if they leave. Every incumbent shows an owner the
 * market rent; none shows the half of the equation that makes chasing it
 * expensive. `pStay` per candidate is supplied by the caller — calibrated from
 * the portfolio's own lease_renewals history, not guessed here.
 */
export interface RenewalCandidate {
  /** Monthly increase offered; zero is a flat renewal. */
  readonly increase: Money;
  /** P(resident accepts) for this increase, in [0, 1]. */
  readonly pStay: Rate;
}

export interface RenewalContext {
  readonly currentRent: Money;
  readonly turnCost: Money;
  readonly vacancyDays: number;
}

export interface RenewalEvaluation {
  readonly increase: Money;
  readonly pStay: Rate;
  readonly expectedGain: Money;
  readonly expectedTurnLoss: Money;
  readonly expectedValue: Money;
}

export interface RenewalDecision {
  readonly evaluations: readonly RenewalEvaluation[];
  /** Highest expected value; ties go to the smaller increase. */
  readonly recommended: RenewalEvaluation;
}

/** Daily rent as annual/365 — the same convention loss-of-rent claims use. */
export const dailyRent = (monthlyRent: Money): Money =>
  divide(multiply(monthlyRent, rate('12'), Rounding.HalfEven), rate('365'), Rounding.HalfEven);

const validateContext = (context: RenewalContext): void => {
  if (isNegative(context.currentRent) || isNegative(context.turnCost)) {
    throw new EngineError('currentRent and turnCost must not be negative');
  }
  assertIntInRange(context.vacancyDays, 'vacancyDays', 0, 365);
};

export const evaluateRenewal = (
  context: RenewalContext,
  candidate: RenewalCandidate,
): RenewalEvaluation => {
  validateContext(context);
  if (isNegative(candidate.increase)) {
    throw new EngineError('a renewal increase must not be negative; model concessions elsewhere');
  }
  if (lessThanRate(candidate.pStay, ZERO_RATE) || greaterThanRate(candidate.pStay, ONE_RATE)) {
    throw new EngineError('pStay must be a probability in [0, 1]');
  }

  const annualGain = multiply(candidate.increase, rate('12'), Rounding.HalfEven);
  const expectedGain = multiply(annualGain, candidate.pStay, Rounding.HalfEven);

  const vacancyLoss = multiply(
    dailyRent(context.currentRent),
    rate(String(context.vacancyDays)),
    Rounding.HalfEven,
  );
  const pLeave = subtractRate(ONE_RATE, candidate.pStay);
  const expectedTurnLoss = multiply(add(context.turnCost, vacancyLoss), pLeave, Rounding.HalfEven);

  return {
    increase: candidate.increase,
    pStay: candidate.pStay,
    expectedGain,
    expectedTurnLoss,
    expectedValue: subtract(expectedGain, expectedTurnLoss),
  };
};

export const recommendRenewal = (
  context: RenewalContext,
  candidates: readonly RenewalCandidate[],
): RenewalDecision => {
  if (candidates.length === 0) {
    throw new EngineError('recommendRenewal needs at least one candidate');
  }
  const evaluations = candidates.map((c) => evaluateRenewal(context, c));
  let best = evaluations[0] as RenewalEvaluation;
  for (const current of evaluations.slice(1)) {
    const strictlyBetter = greaterThan(current.expectedValue, best.expectedValue);
    // No !strictlyBetter guard: when current is strictly better the || below
    // has already decided, so the guard was dead weight a mutant could hide in.
    const tiedButSmaller =
      !greaterThan(best.expectedValue, current.expectedValue) &&
      lessThan(current.increase, best.increase);
    if (strictlyBetter || tiedButSmaller) {
      best = current;
    }
  }
  return { evaluations, recommended: best };
};
