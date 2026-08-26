import {
  add,
  compound,
  divideRate,
  greaterThan,
  isPositive,
  isZeroRate,
  lessThanRate,
  type Money,
  multiply,
  ONE_RATE,
  type Rate,
  Rounding,
  rate,
  split,
  subtract,
  subtractRate,
  sum,
} from '@hestia/domain';
import { assertIntInRange, EngineError } from './errors.js';

/**
 * A fully amortizing note.
 *
 * `annualRate` is the nominal annual rate; the periodic rate is annual/12,
 * which is the convention on every US residential note. Rounding is HalfUp
 * throughout — the lender convention — and the final payment is a plug, so the
 * schedule retires the principal to the exact cent rather than drifting by the
 * accumulated rounding of 360 rows.
 */
export interface AmortizationTerms {
  readonly principal: Money;
  readonly annualRate: Rate;
  readonly termMonths: number;
}

export interface AmortizationRow {
  readonly month: number;
  readonly payment: Money;
  readonly interest: Money;
  readonly principal: Money;
  readonly balance: Money;
}

export interface AmortizationSchedule {
  readonly payment: Money;
  readonly rows: readonly AmortizationRow[];
  readonly totalInterest: Money;
}

export const MAX_TERM_MONTHS = 1200;

const validateTerms = (terms: AmortizationTerms): void => {
  assertIntInRange(terms.termMonths, 'termMonths', 1, MAX_TERM_MONTHS);
  if (!isPositive(terms.principal)) {
    throw new EngineError('principal must be positive');
  }
  if (lessThanRate(terms.annualRate, rate('0')) || !lessThanRate(terms.annualRate, ONE_RATE)) {
    throw new EngineError('annualRate must be a decimal in [0, 1): 0.0675 is 6.75%');
  }
};

/** The level payment for the note, rounded HalfUp as lenders do. */
export const monthlyPayment = (terms: AmortizationTerms): Money => {
  validateTerms(terms);
  const monthly = divideRate(terms.annualRate, rate('12'));
  if (isZeroRate(monthly)) {
    // A zero-rate note divides evenly; the largest-remainder share is the
    // level payment and the schedule's plug absorbs the odd cents.
    const shares = split(terms.principal, terms.termMonths);
    return shares[0] as Money;
  }
  // payment = P * i / (1 - (1+i)^-n)
  const factor = divideRate(monthly, subtractRate(ONE_RATE, compound(monthly, -terms.termMonths)));
  return multiply(terms.principal, factor, Rounding.HalfUp);
};

/**
 * The full schedule. Invariants, enforced and tested:
 * principal parts sum exactly to the principal; every interest row is
 * round(balance x i); the final balance is exactly zero.
 */
export const amortizationSchedule = (terms: AmortizationTerms): AmortizationSchedule => {
  const payment = monthlyPayment(terms);
  const monthly = divideRate(terms.annualRate, rate('12'));
  const rows: AmortizationRow[] = [];
  let balance = terms.principal;

  for (let month = 1; month <= terms.termMonths; month += 1) {
    const interest = multiply(balance, monthly, Rounding.HalfUp);
    const isLast = month === terms.termMonths;
    let principalPart = isLast ? balance : subtract(payment, interest);
    if (!isLast && !isPositive(principalPart)) {
      throw new EngineError(
        `the payment does not amortize: month ${month} interest meets or exceeds it`,
      );
    }
    if (greaterThan(principalPart, balance)) {
      // Rounding can leave the tail a cent short of a full payment.
      principalPart = balance;
    }
    balance = subtract(balance, principalPart);
    rows.push({
      month,
      payment: add(interest, principalPart),
      interest,
      principal: principalPart,
      balance,
    });
  }

  // The invariants — principal parts sum to the principal, the final balance
  // is exactly zero — hold by construction: the last row's principal IS the
  // remaining balance. They are asserted by the test suite rather than by dead
  // defensive code here, which could never execute and would only survive as
  // unkillable mutants.
  return {
    payment,
    rows,
    totalInterest: sum(
      rows.map((r) => r.interest),
      terms.principal.currency,
    ),
  };
};

/** Remaining balance immediately after payment `month` (0 = at origination). */
export const balanceAfter = (terms: AmortizationTerms, month: number): Money => {
  assertIntInRange(month, 'month', 0, terms.termMonths);
  if (month === 0) {
    validateTerms(terms);
    return terms.principal;
  }
  const schedule = amortizationSchedule(terms);
  return (schedule.rows[month - 1] as AmortizationRow).balance;
};
