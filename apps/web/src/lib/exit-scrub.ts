/**
 * Drag-the-exit arithmetic: for any candidate exit month, the engines price
 * the whole holding period — appreciation compounding monthly at annual/12,
 * every lien's payoff read off its exact amortization schedule, monthly cash
 * flows that notice when a note retires, and the IRR of the full flow chain,
 * annualized exactly via (1+i)¹² − 1. Pure and memoized: the component asks,
 * the engines answer, nothing here touches the DOM.
 *
 * Tax on sale is deliberately zero with the gap named: pricing the exit
 * through recapture needs a recorded basis, and the platform refuses to
 * guess one.
 */
import { dayOf } from '@hestia/design';
import {
  add,
  compound,
  divide,
  divideRate,
  greaterThanRate,
  isPositive,
  type Money,
  money,
  multiply,
  negate,
  Rounding,
  rate,
  rateToPercentString,
  subtract,
  toDecimalString,
} from '@hestia/domain';
import {
  type AmortizationTerms,
  balanceAfter,
  EngineError,
  irr,
  monthlyPayment,
} from '@hestia/engines';
import type { Financials } from './api';

export interface ExitAssumptions {
  appreciationPercent: number;
  hurdlePercent: number;
  sellingCostPercent: number;
}

export interface ExitReading {
  month: number;
  /** Calendar day number of the exit date (see monthDay). */
  day: number;
  exitValue: string;
  loanPayoff: string;
  netProceeds: string;
  /** Effective annual IRR of the whole hold, percent, 1dp; null when no
   * real return exists (underwater equity, or flows that never turn). */
  irrPercent: string | null;
  verdict: 'hold' | 'redeploy' | null;
}

export interface YearPoint {
  month: number;
  day: number;
  irrPercent: string | null;
}

export interface ExitCrossover {
  reading: ExitReading;
  /** Which way the verdict flips as the hold extends past this month. */
  direction: 'to-hold' | 'to-redeploy';
}

export interface ExitModel {
  equityToday: string;
  underwater: boolean;
  horizonMonths: number;
  gap: string;
  readingAt(month: number): ExitReading;
  yearly: YearPoint[];
  /** Every verdict boundary along the horizon. The IRR curve is usually a
   * hump — a selling-cost hole, a crest, a leverage decay — so a hurdle can
   * cross it twice: hold from here, and only until there. */
  crossovers: ExitCrossover[];
}

const MS_PER_DAY = 86_400_000;
const IRR_ITERATIONS = 48;

export const TAX_GAP =
  'Tax on sale is not yet priced: record the closing statement so the basis ' +
  'is a fact, and engines/disposal takes over. Every figure here is pre-tax.';

/** Calendar month addition with day-of-month clamping, as day number. */
export function monthDay(todayIso: string, monthsAhead: number): number {
  const todayDay = dayOf(todayIso);
  const start = new Date(todayDay * MS_PER_DAY);
  const monthIndex = start.getUTCMonth() + monthsAhead;
  const year = start.getUTCFullYear() + Math.floor(monthIndex / 12);
  const month = ((monthIndex % 12) + 12) % 12;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return Date.UTC(year, month, Math.min(start.getUTCDate(), lastDay)) / MS_PER_DAY;
}

interface Note {
  terms: AmortizationTerms;
  elapsed: number;
  payment: Money;
}

const ZERO = money('0.00');

export function buildExitModel(
  financials: Financials,
  today: string,
  assumptions: ExitAssumptions,
  horizonMonths = 120,
): ExitModel | null {
  if (!financials.valuation) {
    return null;
  }
  // Sliders hand over half-percent steps; the division into rate space is
  // exact decimal, never float — 3%/12 is 0.0025, not 0.0024999….
  const value0 = money(financials.valuation.value);
  const monthlyNoi = divide(money(financials.noi_12mo), rate('12'), Rounding.HalfEven);
  const monthlyGrowth = divideRate(rate(String(assumptions.appreciationPercent)), rate('1200'));
  const sellingCostRate = divideRate(rate(String(assumptions.sellingCostPercent)), rate('100'));
  const hurdle = divideRate(rate(String(assumptions.hurdlePercent)), rate('100'));

  const notes: Note[] = financials.debts.map((debt) => {
    const terms: AmortizationTerms = {
      principal: money(debt.original_principal),
      annualRate: rate(debt.annual_rate),
      termMonths: debt.term_months,
    };
    return { terms, elapsed: debt.months_elapsed, payment: monthlyPayment(terms) };
  });

  const payoffAt = (month: number): Money =>
    notes.reduce(
      (total, note) =>
        add(total, balanceAfter(note.terms, Math.min(note.elapsed + month, note.terms.termMonths))),
      ZERO,
    );

  const equity0 = subtract(value0, payoffAt(0));
  const underwater = !isPositive(equity0);

  // Monthly net cash flow, exact per month — it rises when a note retires.
  const cashFlows: Money[] = [];
  for (let month = 1; month <= horizonMonths; month += 1) {
    const debtService = notes.reduce(
      (total, note) =>
        note.elapsed + month <= note.terms.termMonths ? add(total, note.payment) : total,
      ZERO,
    );
    cashFlows.push(subtract(monthlyNoi, debtService));
  }
  const sumCashFlows = (fromExclusive: number, toInclusive: number): Money =>
    cashFlows.slice(fromExclusive, toInclusive).reduce((total, flow) => add(total, flow), ZERO);

  const readings = new Map<number, ExitReading>();
  const readingAt = (month: number): ExitReading => {
    const cached = readings.get(month);
    if (cached !== undefined) {
      return cached;
    }
    const exitValue = multiply(value0, compound(monthlyGrowth, month), Rounding.HalfEven);
    const loanPayoff = payoffAt(month);
    const netProceeds = subtract(
      subtract(exitValue, multiply(exitValue, sellingCostRate, Rounding.HalfEven)),
      loanPayoff,
    );
    let irrPercent: string | null = null;
    let verdict: 'hold' | 'redeploy' | null = null;
    if (!underwater) {
      // Annual flows — the grain the irr engine is proven at (its bisection
      // bracket overflows beyond ~75 periods; see the tracker). Whole years
      // carry their exact cash; the scrubbed month's partial year carries
      // its months-to-date plus the sale proceeds, landing in its year.
      const years = Math.ceil(month / 12);
      const flows: Money[] = [negate(equity0)];
      for (let year = 1; year < years; year += 1) {
        flows.push(sumCashFlows((year - 1) * 12, year * 12));
      }
      flows.push(add(sumCashFlows((years - 1) * 12, month), netProceeds));
      try {
        const annual = irr(flows, IRR_ITERATIONS);
        irrPercent = rateToPercentString(annual, 1);
        verdict = greaterThanRate(hurdle, annual) ? 'redeploy' : 'hold';
      } catch (caught) {
        if (!(caught instanceof EngineError)) {
          throw caught;
        }
        // Flows that never turn positive have no internal rate — an honest
        // null, never a guessed figure.
      }
    }
    const reading: ExitReading = {
      month,
      day: monthDay(today, month),
      exitValue: toDecimalString(exitValue),
      loanPayoff: toDecimalString(loanPayoff),
      netProceeds: toDecimalString(netProceeds),
      irrPercent,
      verdict,
    };
    readings.set(month, reading);
    return reading;
  };

  const yearly: YearPoint[] = [];
  for (let month = 12; month <= horizonMonths; month += 12) {
    const reading = readingAt(month);
    yearly.push({ month, day: reading.day, irrPercent: reading.irrPercent });
  }

  // The crossover: where the verdict changes as the hold extends — found at
  // year grain, refined to the month. The IRR curve can run either way
  // (selling costs amortize, leverage cuts both ways), so the direction is
  // named rather than assumed. Short holds that merely eat their selling
  // costs are not a crossover; the verdict pill already says "too early".
  const crossovers: ExitCrossover[] = [];
  // A curve with any null year is degenerate — no marks on a broken line.
  if (yearly.every((point) => readingAt(point.month).verdict !== null)) {
    for (let index = 1; index < yearly.length; index += 1) {
      const prior = readingAt((yearly[index - 1] as YearPoint).month);
      const current = readingAt((yearly[index] as YearPoint).month);
      if (prior.verdict === current.verdict) {
        continue;
      }
      for (let month = prior.month + 1; month <= current.month; month += 1) {
        const reading = readingAt(month);
        if (reading.verdict === current.verdict) {
          crossovers.push({
            reading,
            direction: current.verdict === 'hold' ? 'to-hold' : 'to-redeploy',
          });
          break;
        }
      }
    }
  }

  return {
    equityToday: toDecimalString(equity0),
    underwater,
    horizonMonths,
    gap: TAX_GAP,
    readingAt,
    yearly,
    crossovers,
  };
}
