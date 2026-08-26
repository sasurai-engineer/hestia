import {
  add,
  compareRate,
  divideRate,
  fraction,
  greaterThan,
  greaterThanRate,
  isNegative,
  isZero,
  isZeroRate,
  lessThanRate,
  type Money,
  money,
  multiply,
  multiplyRate,
  ONE_RATE,
  type Rate,
  Rounding,
  rate,
  subtract,
  subtractRate,
  sum,
  ZERO_RATE,
  zero,
} from '@hestia/domain';
import { assertIntInRange, EngineError } from './errors.js';

/**
 * MACRS depreciation, computed from the statutory formulas rather than the
 * rounded percentages in Pub 946's tables (the Pub permits either). Formulas
 * keep the dual-book cents exact; where a published table is itself exact —
 * the 5-year half-year 200DB column is — the tests assert equality with it.
 *
 * The load-bearing consumer is the DUAL BOOK: the same asset run once per book
 * with different elections. Kentucky computes under IRC §168 as in effect on
 * 31 Dec 2001 — MACRS without bonus, §179 capped at the 2001 levels — so a
 * cost-segregated asset takes 100% bonus federally and a plain 5-year 200DB
 * schedule in Kentucky, and the two never reconverge.
 */
export type DepreciationMethod = 'macrs_sl' | 'macrs_200db' | 'macrs_150db';
export type DepreciationConvention = 'mid_month' | 'half_year' | 'mid_quarter';

export interface DepreciationInput {
  readonly basis: Money;
  readonly method: DepreciationMethod;
  /** Recovery period in years: 27.5, 39, 5, 7, 15 for the common classes. */
  readonly lifeYears: number;
  readonly convention: DepreciationConvention;
  /** 1-12; required for mid_month. */
  readonly placedInServiceMonth?: number;
  /** 1-4; required for mid_quarter. */
  readonly quarter?: number;
  /** Bonus election as a fraction in [0, 1]; the book decides it. */
  readonly bonusPercent: Rate;
  /** §179 expensing taken against this asset, already capped by the book. */
  readonly section179: Money;
}

export interface DepreciationYear {
  readonly year: number;
  readonly amount: Money;
}

export interface DepreciationResult {
  readonly section179: Money;
  readonly bonus: Money;
  readonly schedule: readonly DepreciationYear[];
  /** section179 + bonus + every schedule row; always exactly the basis. */
  readonly total: Money;
}

export const MAX_LIFE_YEARS = 50;

const factorFor = (method: DepreciationMethod): Rate | null => {
  if (method === 'macrs_200db') return rate('2');
  if (method === 'macrs_150db') return rate('1.5');
  return null;
};

/** The first-year fraction each convention allows. Exact rationals. */
const firstYearFraction = (input: DepreciationInput): Rate => {
  if (input.convention === 'mid_month') {
    const month = assertIntInRange(input.placedInServiceMonth ?? 0, 'placedInServiceMonth', 1, 12);
    // (12 - m + 0.5) / 12, kept as the exact fraction (2(12-m)+1)/24.
    return fraction(2 * (12 - month) + 1, 24);
  }
  if (input.convention === 'mid_quarter') {
    const quarter = assertIntInRange(input.quarter ?? 0, 'quarter', 1, 4);
    // (4 - q + 0.5) / 4, kept as (2(4-q)+1)/8.
    return fraction(2 * (4 - quarter) + 1, 8);
  }
  return fraction(1, 2);
};

/**
 * The year-by-year percentage of the depreciable base, as exact 40-digit
 * rates. Declining balance switches to straight line the year SL on the
 * remaining basis over the remaining life first meets or beats it, which is
 * the statutory optimisation; the final year is the remainder, so the
 * percentages always sum to exactly one.
 */
const validateScheduleInput = (input: DepreciationInput): void => {
  const { lifeYears, method } = input;
  if (!Number.isFinite(lifeYears) || lifeYears <= 0 || lifeYears > MAX_LIFE_YEARS) {
    throw new EngineError(
      `lifeYears must be in (0, ${MAX_LIFE_YEARS}], received ${String(lifeYears)}`,
    );
  }
  if (method === 'macrs_sl' && input.convention !== 'mid_month') {
    throw new EngineError('straight-line MACRS here models real property, which is mid-month');
  }
  if (method !== 'macrs_sl' && input.convention === 'mid_month') {
    throw new EngineError('declining balance uses the half-year or mid-quarter convention');
  }
};

// Termination is exact, not approximate: the final subtraction is always
// subtractRate(open, open), and the domain's Rate arithmetic makes x - x
// precisely zero — so both generators finish in at most ceil(life) + 1 rows.
const slSchedule = (life: Rate, first: Rate): Rate[] => {
  const full = divideRate(ONE_RATE, life);
  const pcts: Rate[] = [multiplyRate(full, first)];
  let open = subtractRate(ONE_RATE, pcts[0] as Rate);
  while (!isZeroRate(open)) {
    const ded = greaterThanRate(open, full) ? full : open;
    pcts.push(ded);
    open = subtractRate(open, ded);
  }
  return pcts;
};

const dbSchedule = (life: Rate, first: Rate, factor: Rate): Rate[] => {
  const dbRate = divideRate(factor, life);
  const pcts: Rate[] = [multiplyRate(dbRate, first)];
  let open = subtractRate(ONE_RATE, pcts[0] as Rate);
  // Remaining recovery period at the start of year 2.
  let remainingLife = subtractRate(life, first);

  while (!isZeroRate(open)) {
    if (!greaterThanRate(remainingLife, ONE_RATE)) {
      // Less than a full year of recovery remains: the plug.
      pcts.push(open);
      break;
    }
    const db = multiplyRate(open, dbRate);
    const sl = divideRate(open, remainingLife);
    // No `switched` flag: once straight line on the remaining basis meets
    // declining balance it stays ahead, so the comparison alone is the switch.
    const ded = compareRate(sl, db) >= 0 ? sl : db;
    pcts.push(ded);
    open = subtractRate(open, ded);
    remainingLife = subtractRate(remainingLife, ONE_RATE);
  }
  return pcts;
};

export const percentSchedule = (input: DepreciationInput): Rate[] => {
  validateScheduleInput(input);
  const first = firstYearFraction(input);
  const life = rate(String(input.lifeYears));
  const factor = factorFor(input.method);
  return factor === null ? slSchedule(life, first) : dbSchedule(life, first, factor);
};

/**
 * The ordering is statutory: §179 first, bonus on what remains, MACRS on the
 * rest. Every yearly amount rounds HalfEven; the final year is a Money-space
 * plug so `total` equals the basis to the cent — a depreciation schedule that
 * drifts is a filing that cannot be reconciled.
 */
const validateElections = (input: DepreciationInput): void => {
  if (isNegative(input.basis) || isZero(input.basis)) {
    throw new EngineError('basis must be positive');
  }
  if (isNegative(input.section179) || greaterThan(input.section179, input.basis)) {
    throw new EngineError('section179 must be between zero and the basis');
  }
  if (
    lessThanRate(input.bonusPercent, ZERO_RATE) ||
    greaterThanRate(input.bonusPercent, ONE_RATE)
  ) {
    throw new EngineError('bonusPercent must be a fraction in [0, 1]');
  }
};

export const depreciate = (input: DepreciationInput): DepreciationResult => {
  validateElections(input);
  const currency = input.basis.currency;
  const afterS179 = subtract(input.basis, input.section179);
  const bonus = multiply(afterS179, input.bonusPercent, Rounding.HalfEven);
  const macrsBase = subtract(afterS179, bonus);

  const schedule: DepreciationYear[] = [];
  if (!isZero(macrsBase)) {
    const pcts = percentSchedule(input);
    let accumulated = zero(currency);
    for (let i = 0; i < pcts.length; i += 1) {
      const isLast = i === pcts.length - 1;
      // The final year is a Money-space plug. It cannot go negative: the
      // accumulated half-cent drift over at most 29 rows is bounded by ~15
      // cents, and the plug year is a material fraction of the basis.
      const amount = isLast
        ? subtract(macrsBase, accumulated)
        : multiply(macrsBase, pcts[i] as Rate, Rounding.HalfEven);
      accumulated = add(accumulated, amount);
      schedule.push({ year: i + 1, amount });
    }
  }

  const total = add(
    add(input.section179, bonus),
    sum(
      schedule.map((y) => y.amount),
      currency,
    ),
  );
  // total === basis holds by construction of the plug; the suite asserts it on
  // every case and by property, where a failure can actually be seen.
  return { section179: input.section179, bonus, schedule, total };
};
/**
 * A state's §179 regime as a profile: a cap with dollar-for-dollar phaseout
 * above a threshold. The numbers come from jurisdiction_rules pack data
 * (ADR 0003); the arithmetic lives here where it is mutation-tested. The
 * caller passes total §179-eligible property placed in service in the year
 * so the phaseout can bind.
 */
export interface Section179Rule {
  readonly cap: string;
  readonly phaseoutStart: string;
}

export const section179Limit = (totalPlacedInService: Money, rule: Section179Rule): Money => {
  if (isNegative(totalPlacedInService)) {
    throw new EngineError('totalPlacedInService must not be negative');
  }
  const currency = totalPlacedInService.currency;
  const cap = money(rule.cap, currency);
  const start = money(rule.phaseoutStart, currency);
  if (!greaterThan(totalPlacedInService, start)) {
    return cap;
  }
  const excess = subtract(totalPlacedInService, start);
  const remaining = subtract(cap, excess);
  return isNegative(remaining) ? zero(currency) : remaining;
};

/**
 * Kentucky's profile: IRC §168 as of 31 Dec 2001 — no bonus of any kind, §179
 * at the 2001 levels. The authoritative copy is the seed pack row
 * (seed/900_jurisdictions_kentucky.sql); tests/packs/kentucky.sql and the
 * shared fixture rows pin the two copies together in CI.
 */
export const KY_2001_S179: Section179Rule = { cap: '25000.00', phaseoutStart: '200000.00' };
export const KY_2001_S179_CAP = KY_2001_S179.cap;
export const KY_2001_S179_PHASEOUT_START = KY_2001_S179.phaseoutStart;

export const kentuckySection179Limit = (totalPlacedInService: Money): Money =>
  section179Limit(totalPlacedInService, KY_2001_S179);

/**
 * Addback-recovery conformity — the other shape a state book takes (e.g.
 * Ohio ORC 5747.01: a 2/3 add-back of federal accelerated depreciation in
 * year one, returned in equal slices over six years). The fraction and the
 * recovery period come from jurisdiction_rules pack data (ADR 0003).
 */
export interface AddbackConformity {
  readonly addbackNumerator: number;
  readonly addbackDenominator: number;
  readonly recoveryYears: number;
}

export interface StateAddbackResult {
  readonly addback: Money;
  readonly recovery: readonly DepreciationYear[];
}

/**
 * Exact rational arithmetic, one HalfEven rounding per figure, and a
 * final-year plug in money space so the recovery slices sum to the addback
 * EXACTLY — the plug moves the last slice up or down by the accumulated
 * rounding, never a fraction of a cent lost.
 */
export const stateAddbackSchedule = (
  accelerated: Money,
  conformity: AddbackConformity,
): StateAddbackResult => {
  if (isNegative(accelerated)) {
    throw new EngineError('accelerated depreciation must not be negative');
  }
  assertIntInRange(conformity.addbackDenominator, 'addbackDenominator', 1, 1000);
  assertIntInRange(
    conformity.addbackNumerator,
    'addbackNumerator',
    1,
    conformity.addbackDenominator,
  );
  assertIntInRange(conformity.recoveryYears, 'recoveryYears', 1, 100);
  const addback = multiply(
    accelerated,
    fraction(conformity.addbackNumerator, conformity.addbackDenominator),
    Rounding.HalfEven,
  );
  const perYear = multiply(addback, fraction(1, conformity.recoveryYears), Rounding.HalfEven);
  const recovery: DepreciationYear[] = [];
  for (let year = 1; year < conformity.recoveryYears; year += 1) {
    recovery.push({ year, amount: perYear });
  }
  // No zero special case: rate(0) is a legal factor and multiplying by it is
  // exactly zero, so the one-year schedule's plug is addback minus nothing.
  const already = multiply(perYear, rate(conformity.recoveryYears - 1), Rounding.HalfEven);
  recovery.push({ year: conformity.recoveryYears, amount: subtract(addback, already) });
  return { addback, recovery };
};
