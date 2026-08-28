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
  rateToPercentString,
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
 * The bisection floor, by series length. Discounting period `t` at rate `lo`
 * scales the flow by `(1 + lo)^-t`, and money arithmetic is exact up to 300
 * digits — so the floor may only be as deep as the LAST period's factor can
 * prove: `-0.9999` gives `10^4` per period (fine to 62 periods, 248 digits),
 * `-0.999` gives `10^3` (to 83), `-0.99` gives `10^2` (to 125), `-0.9` gives
 * `10` (to 250), and `-0.6` gives `10^0.398` (to 600, ~239 digits) — each
 * within 250 digits, leaving headroom for the flow itself and the sum. A
 * portfolio losing more than the floor per period is a data error, the same
 * doctrine as the 1000% ceiling. (#68: the fixed `-0.9999` floor made the
 * first bracket probe overflow beyond ~75 periods.)
 */
const BRACKET_FLOORS: readonly (readonly [number, string])[] = [
  [62, '-0.9999'],
  [83, '-0.999'],
  [125, '-0.99'],
  [250, '-0.9'],
];

export const irrBracketFloor = (periods: number): Rate =>
  rate(BRACKET_FLOORS.find(([limit]) => periods <= limit)?.[1] ?? '-0.6');

/**
 * The ceiling has the mirrored bound: at rate `hi` the last period's factor
 * is `(1 + hi)^-t`, and a rate below `1e-300` cannot be represented at all —
 * so `10` holds while `11^t` stays within 250 digits (240 periods), `4`
 * while `5^t` does (357), `2` while `3^t` does (524), and `1.5` to the full
 * 600 (`2.5^600 ≈ 10^239`). 150% per period at 600 periods is still beyond
 * any honest portfolio answer.
 */
const BRACKET_CEILINGS: readonly (readonly [number, string])[] = [
  [240, '10'],
  [357, '4'],
  [524, '2'],
];

export const irrBracketCeiling = (periods: number): Rate =>
  rate(BRACKET_CEILINGS.find(([limit]) => periods <= limit)?.[1] ?? '1.5');

/**
 * Internal rate of return by bisection — deterministic, derivative-free, and
 * immune to the divergence Newton's method suffers near sign changes. The
 * bracket is [irrBracketFloor, irrBracketCeiling] for the series' length; a
 * portfolio IRR outside it is a data error, not an answer. Requires at least
 * one sign change among the flows, since without one NPV is monotone and no
 * root exists.
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

  const floor = irrBracketFloor(flows.length - 1);
  const ceiling = irrBracketCeiling(flows.length - 1);
  let lo = floor;
  let hi = ceiling;
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
    throw new EngineError(
      `irr has no root in [${rateToPercentString(floor, 2)}, ` +
        `${rateToPercentString(ceiling, 2)}] for these flows`,
    );
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
