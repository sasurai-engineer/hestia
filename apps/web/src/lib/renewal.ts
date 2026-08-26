/**
 * The renewal decision, computed in the browser by the rent engine. The
 * stay-probability model is deliberately simple and DISCLOSED: acceptance
 * starts high for a flat renewal and falls with the size of the ask; every
 * refused offer the owner records replaces this curve with measured history
 * on the API side (the context's assumptions_source says which is in play).
 */
import { money, multiply, Rounding, rate, toDecimalString } from '@hestia/domain';
import { recommendRenewal } from '@hestia/engines';
import type { RenewalContextOut } from './api';

export interface RenewalOption {
  increasePercent: number;
  increase: string;
  newRent: string;
  pStayPercent: number;
  expectedValue: string;
  recommended: boolean;
}

export interface RenewalAdvice {
  options: RenewalOption[];
  recommendedIncreasePercent: number;
  assumptionsSource: string;
  pStayModel: string;
}

const CANDIDATE_PERCENTS = [0, 2, 4, 6, 8] as const;

/** P(stay) for an increase: 92% flat, minus 6 points per +2% step. */
const pStayFor = (increasePercent: number): number => Math.max(0.2, 0.92 - 0.03 * increasePercent);

export const renewalAdvice = (context: RenewalContextOut): RenewalAdvice => {
  const currentRent = money(context.current_rent);
  const engineContext = {
    currentRent,
    turnCost: money(context.turn_cost),
    vacancyDays: context.vacancy_days,
  };
  const candidates = CANDIDATE_PERCENTS.map((percent) => ({
    increase: multiply(currentRent, rate(String(percent / 100)), Rounding.HalfEven),
    pStay: rate(String(pStayFor(percent))),
  }));
  const decision = recommendRenewal(engineContext, candidates);
  const options = decision.evaluations.map((evaluation, index) => ({
    increasePercent: CANDIDATE_PERCENTS[index] as number,
    increase: toDecimalString(evaluation.increase),
    newRent: toDecimalString(
      multiply(
        currentRent,
        rate(String(1 + (CANDIDATE_PERCENTS[index] as number) / 100)),
        Rounding.HalfEven,
      ),
    ),
    pStayPercent: Math.round(pStayFor(CANDIDATE_PERCENTS[index] as number) * 100),
    expectedValue: toDecimalString(evaluation.expectedValue),
    recommended: evaluation === decision.recommended,
  }));
  // The recommendation IS one of the evaluations (reference identity), so
  // the index lookup cannot miss — no defensive fallback to hide a mutant in.
  const recommendedIndex = decision.evaluations.indexOf(decision.recommended);
  return {
    options,
    recommendedIncreasePercent: CANDIDATE_PERCENTS[recommendedIndex] as number,
    assumptionsSource: context.assumptions_source,
    pStayModel:
      'Stay probability modeled at 92% for a flat renewal, minus 3 points ' +
      'per +1% of ask; recorded turns replace these assumptions with your ' +
      'own history.',
  };
};
