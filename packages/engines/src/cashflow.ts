import {
  add,
  addRate,
  compareRate,
  compound,
  divideRate,
  isNegative,
  isPositive,
  isZero,
  type Money,
  multiply,
  negate,
  type Rate,
  Rounding,
  rate,
  sum,
} from '@hestia/domain';
import { assertIntInRange, EngineError } from './errors.js';

export const MAX_PERIODS = 600;

const validateFlows = (flows: readonly Money[]): void => {
  if (flows.length < 2) {
    throw new EngineError('cash flow analysis needs at least two periods');
  }
  if (flows.length > MAX_PERIODS + 1) {
    throw new EngineError(`cash flow analysis is limited to ${MAX_PERIODS} periods`);
  }
};

/**
 * Net present value of periodic flows, `flows[0]` at time zero. Each term is
 * discounted exactly and rounded HalfEven once, at the term.
 */
export const npv = (discountRate: Rate, flows: readonly Money[]): Money => {
  validateFlows(flows);
  if (compareRate(discountRate, rate('-1')) <= 0) {
    throw new EngineError('discountRate must be greater than -100%');
  }
  const currency = (flows[0] as Money).currency;
  const terms = flows.map((flow, t) =>
    t === 0 ? flow : multiply(flow, compound(discountRate, -t), Rounding.HalfEven),
  );
  return sum(terms, currency);
};

/**
 * Internal rate of return by bisection — deterministic, derivative-free, and
 * immune to the divergence Newton's method suffers near sign changes. The
 * bracket is [-99.99%, 1000%]; a portfolio IRR outside it is a data error, not
 * an answer. Requires at least one sign change among the flows, since without
 * one NPV is monotone and no root exists.
 */
export const IRR_ITERATIONS = 120;

export const irr = (flows: readonly Money[], maxIterations: number = IRR_ITERATIONS): Rate => {
  validateFlows(flows);
  assertIntInRange(maxIterations, 'maxIterations', 1, 1000);
  const hasNegative = flows.some((f) => isNegative(f));
  const hasPositive = flows.some((f) => isPositive(f));
  if (!hasNegative || !hasPositive) {
    throw new EngineError('irr needs at least one inflow and one outflow');
  }

  let lo = rate('-0.9999');
  let hi = rate('10');
  const sign = (r: Rate): number => {
    const value = npv(r, flows);
    if (isZero(value)) return 0;
    return isNegative(value) ? -1 : 1;
  };
  const sLo = sign(lo);
  const sHi = sign(hi);
  if (sLo === 0) return lo;
  if (sHi === 0) return hi;
  if (sLo === sHi) {
    throw new EngineError('irr has no root in [-99.99%, 1000%] for these flows');
  }

  for (let i = 0; i < maxIterations; i += 1) {
    const mid = divideRate(addRate(lo, hi), rate('2'));
    const sMid = sign(mid);
    if (sMid === 0) return mid;
    if (sMid === sLo) {
      lo = mid;
    } else {
      hi = mid;
    }
  }
  return divideRate(addRate(lo, hi), rate('2'));
};

/**
 * Simple annual project: buy, hold collecting a level cash flow, sell.
 * A convenience wrapper that keeps the flow-building arithmetic tested here
 * rather than re-derived at every call site.
 */
export const holdingPeriodFlows = (input: {
  readonly initialInvestment: Money;
  readonly annualCashFlow: Money;
  readonly years: number;
  readonly netSaleProceeds: Money;
}): Money[] => {
  assertIntInRange(input.years, 'years', 1, 100);
  if (isNegative(input.initialInvestment) || isZero(input.initialInvestment)) {
    throw new EngineError('initialInvestment must be positive; the engine negates it');
  }
  const flows: Money[] = [negate(input.initialInvestment)];
  for (let y = 1; y < input.years; y += 1) {
    flows.push(input.annualCashFlow);
  }
  flows.push(add(input.annualCashFlow, input.netSaleProceeds));
  return flows;
};
