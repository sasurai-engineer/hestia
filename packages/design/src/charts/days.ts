/**
 * Calendar-day arithmetic for time axes. Dates on the spine are date-only
 * ISO strings; positioning math runs on whole days since the epoch (UTC),
 * so no operator timezone can shift a mark. Rendering a date for a HUMAN
 * is the app's business (its formatter is operator-local, deliberately).
 */

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const MS_PER_DAY = 86_400_000;

/** 'YYYY-MM-DD' → whole days since the epoch. Rejects malformed and
 * impossible dates — 2026-02-30 is a lie, not a coordinate. */
export function dayOf(iso: string): number {
  if (!DATE_ONLY.test(iso)) {
    throw new RangeError(`not a date-only ISO string: ${iso}`);
  }
  const year = Number(iso.slice(0, 4));
  const month = Number(iso.slice(5, 7));
  const day = Number(iso.slice(8, 10));
  const ms = Date.UTC(year, month - 1, day);
  const roundTrip = new Date(ms);
  // Date.UTC normalizes lies instead of refusing them. Year and day drift
  // between them catch every normalization: a month overflow rolls the
  // year, and a day overflow rolls the day — a month-only drift cannot
  // occur, so checking it would be a redundant guard.
  if (roundTrip.getUTCFullYear() !== year || roundTrip.getUTCDate() !== day) {
    throw new RangeError(`not a real calendar date: ${iso}`);
  }
  return ms / MS_PER_DAY;
}

/** Whole days since the epoch → 'YYYY-MM-DD'. */
export function isoOf(day: number): string {
  if (!Number.isInteger(day)) {
    throw new RangeError(`day numbers are whole days, got ${day}`);
  }
  return new Date(day * MS_PER_DAY).toISOString().slice(0, 10);
}

export type TimeTick = {
  day: number;
  /** Month ticks say 'Feb'; January and year-mode ticks say the year. */
  label: string;
  /** True where the label is a year — the axis renders these heavier. */
  major: boolean;
};

// January never appears here — a January tick is major and says its year.
const MONTHS = ['Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * Month boundaries across [startDay, endDay], thinned by span: every month
 * to ~2.2 years, quarters to ~6.5 years, then Januaries alone.
 */
export function timeTicks(startDay: number, endDay: number): TimeTick[] {
  if (!Number.isInteger(startDay) || !Number.isInteger(endDay)) {
    throw new RangeError(`tick bounds are whole days, got ${startDay}..${endDay}`);
  }
  if (endDay <= startDay) {
    throw new RangeError(`tick bounds must be ordered, got ${startDay}..${endDay}`);
  }
  const span = endDay - startDay;
  const stepMonths = span <= 800 ? 1 : span <= 2400 ? 3 : 12;
  const start = new Date(startDay * MS_PER_DAY);
  const firstMonth = start.getUTCFullYear() * 12 + start.getUTCMonth();
  // The first boundary at or after the start, aligned to the step so
  // quarter ticks land on Jan/Apr/Jul/Oct and year ticks on January.
  let monthIndex = Math.ceil(firstMonth / stepMonths) * stepMonths;
  if (monthIndex === firstMonth && start.getUTCDate() > 1) {
    monthIndex += stepMonths;
  }
  const ticks: TimeTick[] = [];
  for (;;) {
    const year = Math.floor(monthIndex / 12);
    const month = monthIndex % 12;
    const day = Date.UTC(year, month, 1) / MS_PER_DAY;
    if (day > endDay) {
      break;
    }
    const major = month === 0;
    ticks.push({
      day,
      label: major ? String(year) : (MONTHS[month - 1] as string),
      major,
    });
    monthIndex += stepMonths;
  }
  return ticks;
}
