/** Pure display arithmetic: tested to 100%, no DOM, no network. */
import type { ComponentOut } from './api';

export const titleCase = (snake: string): string =>
  snake
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');

/**
 * Today as YYYY-MM-DD in the OPERATOR'S timezone. `toISOString().slice(0, 10)`
 * is UTC and dates a late-evening Kentucky action tomorrow.
 */
export const localIsoDate = (now: Date): string => {
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
};

export const formatDate = (iso: string): string => {
  const [year, month, day] = iso.split('-');
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  const index = Number(month) - 1;
  const name = months[index];
  if (!year || !day || name === undefined) return iso;
  return `${name} ${String(Number(day))}, ${year}`;
};

export interface LifeSummary {
  /** Midpoint age in years at `now`, from the inferred install band. */
  age: number | null;
  /** Fraction of expected life consumed, clamped to [0, 1]. */
  spent: number | null;
  /** True once the midpoint age passes the band's high life. */
  beyondExpected: boolean;
}

export const lifeSummary = (component: ComponentOut, nowYear: number): LifeSummary => {
  const { installed_year_low: low, installed_year_high: high } = component;
  if (low == null || high == null) {
    return { age: null, spent: null, beyondExpected: false };
  }
  const age = nowYear - (low + high) / 2;
  const lifeHigh = component.life_years_high;
  if (lifeHigh == null || lifeHigh <= 0) {
    return { age, spent: null, beyondExpected: false };
  }
  const spent = Math.min(1, Math.max(0, age / lifeHigh));
  return { age, spent, beyondExpected: age > lifeHigh };
};

/** The four defect consequences as short labels, in a stable order. */
export const defectConsequences = (defect: {
  affects_safety: boolean;
  affects_insurance: boolean;
  affects_financing: boolean;
  triggers_disclosure: boolean;
}): string[] => {
  const labels: string[] = [];
  if (defect.affects_safety) labels.push('safety');
  if (defect.affects_insurance) labels.push('insurance');
  if (defect.affects_financing) labels.push('financing');
  if (defect.triggers_disclosure) labels.push('disclosure');
  return labels;
};
