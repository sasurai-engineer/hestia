/**
 * Extra-principal arithmetic: walk a note month by month with an extra
 * payment riding every installment, in the engines' own convention —
 * interest at annual/12, HalfUp at each row, the final payment a plug.
 * The baseline comes straight from the engines' schedule; the scenario is
 * the same walk with the extra applied; the working is the difference.
 */
import {
  add,
  divideRate,
  isPositive,
  lessThan,
  type Money,
  money,
  multiply,
  Rounding,
  rate,
  subtract,
  toDecimalString,
} from '@hestia/domain';
import {
  type AmortizationRow,
  type AmortizationTerms,
  amortizationSchedule,
} from '@hestia/engines';
import type { Financials } from './api';

export interface PayoffPoint {
  /** Months from today. */
  month: number;
  balance: string;
}

export interface NotePlan {
  lender: string;
  /** Months from today until retirement, and interest still to be paid,
   * with no extra principal. */
  baselineMonths: number;
  baselineInterest: string;
  /** The same, with the extra riding every payment. */
  extraMonths: number;
  extraInterest: string;
  interestSaved: string;
  monthsSaved: number;
  baselineCurve: PayoffPoint[];
  extraCurve: PayoffPoint[];
}

const ZERO = money('0.00');

interface Walk {
  months: number;
  interest: Money;
  curve: PayoffPoint[];
}

/** Walk the remaining term from `elapsed`, paying `payment + extra` monthly.
 * Sampled quarterly for the curve; exact at every step for the figures. */
function walk(terms: AmortizationTerms, elapsed: number, payment: Money, extra: Money): Walk {
  const monthlyRate = divideRate(terms.annualRate, rate('12'));
  // Start from the engine's own balance at `elapsed`, not a re-derivation.
  const schedule = amortizationSchedule(terms);
  // The caller filters retired notes, so 1 ≤ elapsed ≤ term when nonzero.
  let balance =
    elapsed === 0 ? terms.principal : (schedule.rows[elapsed - 1] as AmortizationRow).balance;
  let interest = ZERO;
  let months = 0;
  const curve: PayoffPoint[] = [{ month: 0, balance: toDecimalString(balance) }];
  const due = add(payment, extra);
  while (isPositive(balance)) {
    const monthInterest = multiply(balance, monthlyRate, Rounding.HalfUp);
    interest = add(interest, monthInterest);
    const withInterest = add(balance, monthInterest);
    months += 1;
    // The engine's final row is a plug in BOTH directions: at the term
    // boundary the note retires whatever residue rounding accumulated.
    const reachedTerm = elapsed + months >= terms.termMonths;
    balance = !reachedTerm && lessThan(due, withInterest) ? subtract(withInterest, due) : ZERO;
    if (months % 3 === 0 || !isPositive(balance)) {
      curve.push({ month: months, balance: toDecimalString(balance) });
    }
  }
  return { months, interest, curve };
}

export function notePlans(debts: Financials['debts'], extraMonthly: number): NotePlan[] {
  const extra = money(String(extraMonthly));
  return debts
    .filter((debt) => debt.term_months - debt.months_elapsed > 0)
    .map((debt) => {
      const terms: AmortizationTerms = {
        principal: money(debt.original_principal),
        annualRate: rate(debt.annual_rate),
        termMonths: debt.term_months,
      };
      const schedule = amortizationSchedule(terms);
      const baseline = walk(terms, debt.months_elapsed, schedule.payment, ZERO);
      const scenario = walk(terms, debt.months_elapsed, schedule.payment, extra);
      return {
        lender: debt.lender ?? 'Unnamed lender',
        baselineMonths: baseline.months,
        baselineInterest: toDecimalString(baseline.interest),
        extraMonths: scenario.months,
        extraInterest: toDecimalString(scenario.interest),
        interestSaved: toDecimalString(subtract(baseline.interest, scenario.interest)),
        monthsSaved: baseline.months - scenario.months,
        baselineCurve: baseline.curve,
        extraCurve: scenario.curve,
      };
    });
}
