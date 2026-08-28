/**
 * The reserve line's arithmetic: does a flat monthly reserve keep pace with
 * the Weibull forecast's cumulative median? Pure money math over bands the
 * page already holds — dragging the line costs no request and rounds
 * nothing away.
 */
import {
  add,
  isPositive,
  money,
  multiply,
  Rounding,
  rate,
  subtract,
  toDecimalString,
} from '@hestia/domain';
import type { CapexForecastOut } from './api';

export interface ReserveYear {
  year: number;
  cumulativeReserve: string;
  cumulativeMedian: string;
  /** True when the reserve covers the cumulative median through this year. */
  funded: boolean;
  /** The uncovered remainder when it does not; '0.00' when funded. */
  shortfall: string;
}

const ZERO = money('0.00');

export function reserveCoverage(forecast: CapexForecastOut, monthlyReserve: number): ReserveYear[] {
  const monthly = money(String(monthlyReserve));
  const years: ReserveYear[] = [];
  let cumulativeMedian = ZERO;
  for (const band of forecast.bands) {
    cumulativeMedian = add(cumulativeMedian, money(band.p50));
    const cumulativeReserve = multiply(monthly, rate(String(band.year * 12)), Rounding.HalfEven);
    const gap = subtract(cumulativeMedian, cumulativeReserve);
    const funded = !isPositive(gap);
    years.push({
      year: band.year,
      cumulativeReserve: toDecimalString(cumulativeReserve),
      cumulativeMedian: toDecimalString(cumulativeMedian),
      funded,
      shortfall: funded ? '0.00' : toDecimalString(gap),
    });
  }
  return years;
}

/** The first year the reserve runs short, if any. */
export function firstShortfall(years: readonly ReserveYear[]): ReserveYear | null {
  return years.find((year) => !year.funded) ?? null;
}
