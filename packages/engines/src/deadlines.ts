import { assertIntInRange, EngineError } from './errors.js';

/**
 * Calendar arithmetic for the deadline spine.
 *
 * Dates are ISO `YYYY-MM-DD` strings validated at every entry, computed as
 * UTC epoch days — exact integer arithmetic, no timezones, no clocks, no
 * `Date.now()`. Assessment-appeal windows are REGISTERED per state and chosen
 * by pack data (`appeal.window.calendar` in jurisdiction_rules — ADR 0003);
 * the calendar a builder must never get wrong is its own state's, because
 * missing an appeal window costs the owner a year.
 *
 * Known limitation, stated rather than hidden: weekend due dates roll forward
 * to Monday, but federal legal holidays are not yet modelled. A date this
 * engine emits is therefore never LATER than the true deadline — errs early,
 * never late.
 */

export const MIN_YEAR = 1900;
export const MAX_YEAR = 2200;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_MS = 86_400_000;

/** Parse and validate, or raise inside the domain taxonomy. */
export const toEpochDays = (iso: string): number => {
  // RegExp.exec coerces its argument, so a non-string simply fails to match;
  // no separate typeof guard is needed or wanted.
  const match = ISO_DATE.exec(iso);
  if (!match) {
    throw new EngineError(`dates must be ISO YYYY-MM-DD, received ${JSON.stringify(iso)}`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  assertIntInRange(year, 'year', MIN_YEAR, MAX_YEAR);
  const ms = Date.UTC(year, month - 1, day);
  // Date.UTC silently normalises 2026-02-30 into March. The month comparison
  // alone detects EVERY such normalisation, provably: the regex bounds month
  // and day to two digits, so any invalid pair rolls the date by between one
  // day and a few years — and every such roll moves the month index, because
  // rolling it back onto itself would take at least twelve months of overflow
  // and 99 days cannot supply three. Comparing year and day as well was
  // redundancy where equivalent mutants breed.
  if (new Date(ms).getUTCMonth() !== month - 1) {
    throw new EngineError(`${iso} is not a real calendar date`);
  }
  return ms / DAY_MS;
};

export const fromEpochDays = (days: number): string => {
  const date = new Date(days * DAY_MS);
  // Years are bounded to [1900, 2200]; always four digits, never padded.
  const year = String(date.getUTCFullYear());
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

export const addDays = (iso: string, days: number): string => {
  assertIntInRange(days, 'days', -200_000, 200_000);
  return fromEpochDays(toEpochDays(iso) + days);
};

/** 0 = Sunday … 6 = Saturday. 1970-01-01 was a Thursday. */
export const dayOfWeek = (iso: string): number => {
  const days = toEpochDays(iso);
  return (((days + 4) % 7) + 7) % 7;
};

/** Saturday and Sunday roll forward to Monday; weekdays stand. */
export const rollForwardFromWeekend = (iso: string): string => {
  const dow = dayOfWeek(iso);
  if (dow === 6) return addDays(iso, 2);
  if (dow === 0) return addDays(iso, 1);
  return iso;
};

/**
 * The nth occurrence of a weekday in a month — 'first Monday in May',
 * 'fourth Thursday in November'. `weekday` uses this module's convention
 * (0 = Sunday … 6 = Saturday); `nth` runs 1..5, and a fifth occurrence that
 * does not exist in that month is an error, never a silent roll into the
 * next one.
 */
export const nthWeekdayOfMonth = (
  year: number,
  month: number,
  weekday: number,
  nth: number,
): string => {
  assertIntInRange(year, 'year', MIN_YEAR, MAX_YEAR);
  assertIntInRange(month, 'month', 1, 12);
  assertIntInRange(weekday, 'weekday', 0, 6);
  assertIntInRange(nth, 'nth', 1, 5);
  const first = `${String(year)}-${String(month).padStart(2, '0')}-01`;
  const offset = (weekday - dayOfWeek(first) + 7) % 7;
  const candidate = addDays(first, offset + (nth - 1) * 7);
  // A fifth occurrence that overflows lands in the next month, and the month
  // comparison alone detects every overflow: the largest offset is 34 days,
  // well short of wrapping a full year.
  if (Number(candidate.slice(5, 7)) !== month) {
    throw new EngineError(
      `${String(year)}-${String(month)} has no occurrence ${String(nth)} of weekday ${String(weekday)}`,
    );
  }
  return candidate;
};

export const firstMondayOfMay = (year: number): string => nthWeekdayOfMonth(year, 5, 1, 1);

/** What a registered appeal-window builder returns for one calendar year. */
export interface AppealWindowDates {
  readonly opensOn: string;
  readonly closesOn: string;
  /** Present only where the state makes a conference a filing prerequisite. */
  readonly conferenceBy?: string;
}

export type AppealWindowBuilder = (year: number) => AppealWindowDates;

/**
 * KRS 133.045: the open inspection period begins the first Monday in May and
 * runs thirteen days **excluding Sundays**. Starting from a Monday, thirteen
 * non-Sunday days always span fifteen calendar days — two Sundays skipped —
 * so the close is opens + 14. The 2026 period, May 4 through May 18, is the
 * externally verified anchor. The PVA conference (KRS 133.120) must happen
 * inside the window.
 */
const kyOpenInspection: AppealWindowBuilder = (year) => {
  const opensOn = firstMondayOfMay(year);
  const closesOn = addDays(opensOn, 14);
  return { opensOn, closesOn, conferenceBy: closesOn };
};

/**
 * The registry pack data points into: `appeal.window.calendar` rule rows hold
 * one of these keys (`us-<state>.<slug>`). A state whose window fits an
 * existing builder needs no code here at all; a novel window shape adds one
 * pure builder plus anchors, in this file and in the Python twin
 * (services/api/hestia_api/calendar.py). Keys are timeless function
 * identities — a statutory change is a NEW key behind a new effective-dated
 * rule row, never an edit to an existing builder.
 */
/**
 * ORC 5715.19(A): a complaint against valuation (DTE Form 1, filed with the
 * county auditor as clerk of the Board of Revision) may be filed from
 * January 1 through March 31 of the year FOLLOWING the tax year — so
 * builder(Y) is the window occurring in calendar year Y, contesting tax
 * year Y-1. ORC 1.14 extends a deadline falling on a weekend to the next
 * business day. No conference prerequisite exists. Anchors: 2027-03-31 is a
 * Wednesday and stands; 2029-03-31 is a Saturday and rolls to 2029-04-02.
 */
const ohBorComplaint: AppealWindowBuilder = (year) => {
  assertIntInRange(year, 'year', MIN_YEAR, MAX_YEAR);
  return {
    opensOn: `${String(year)}-01-01`,
    closesOn: rollForwardFromWeekend(`${String(year)}-03-31`),
  };
};

/**
 * Tennessee's assessment-contest window, in the counties that keep the
 * statewide calendar. TCA 67-1-404(a): the county board of equalization
 * meets June 1 each year; the Comptroller, which supervises the boards,
 * states the board convenes the next business day where June 1 falls on a
 * weekend, so the OPEN rolls too — unlike Ohio's, where the open is a
 * statutory date rather than a meeting. TCA 67-5-1412(e): an appeal reaches
 * the State Board of Equalization only if filed by August 1 of the tax year,
 * or within forty-five days of the notice of the local board's action if
 * that is later — a leg that depends on a notice this system has not seen,
 * so the builder returns the date an owner can rely on without one. TCA
 * 1-3-102 excludes a last day falling on a Saturday, Sunday or legal
 * holiday. Anchors: 2028-08-01 is a Tuesday and stands; 2027-08-01 is a
 * Sunday and rolls to 2027-08-02.
 */
const tnCountyBoard: AppealWindowBuilder = (year) => {
  assertIntInRange(year, 'year', MIN_YEAR, MAX_YEAR);
  return {
    opensOn: rollForwardFromWeekend(`${String(year)}-06-01`),
    closesOn: rollForwardFromWeekend(`${String(year)}-08-01`),
  };
};

/**
 * Shelby County (Memphis) convenes May 1, a month ahead of the rest of
 * Tennessee — a county-level fact, so the pack overrides the state's
 * calendar on the Shelby County row and the chain does the rest. The close
 * is unchanged: TCA 67-5-1412(e) is statewide. Authority is the
 * Comptroller's published county-board schedule rather than TCA 67-1-404
 * itself, which is why this is a separate key and not a parameter — a
 * builder whose two callers disagree about their source would be one
 * function pretending to be two rules. Anchors: 2027-05-01 is a Saturday and
 * rolls to 2027-05-03; 2028-05-01 is a Monday and stands.
 */
const tnShelbyCountyBoard: AppealWindowBuilder = (year) => {
  assertIntInRange(year, 'year', MIN_YEAR, MAX_YEAR);
  return {
    opensOn: rollForwardFromWeekend(`${String(year)}-05-01`),
    closesOn: rollForwardFromWeekend(`${String(year)}-08-01`),
  };
};

/**
 * The registered builder for a pack's calendar key, or undefined. The table
 * lives inside the function rather than at module scope so that mutation
 * testing can attribute it to covering tests — a module-scope Map is a
 * static mutant no per-test coverage can reach, and an unkillable mutant on
 * the registry would mean a silently breakable registry.
 */
export const appealWindowBuilder = (key: string): AppealWindowBuilder | undefined => {
  const registry: ReadonlyMap<string, AppealWindowBuilder> = new Map([
    ['us-ky.open-inspection', kyOpenInspection],
    ['us-oh.bor-complaint', ohBorComplaint],
    ['us-tn.county-board', tnCountyBoard],
    ['us-tn.shelby-county-board', tnShelbyCountyBoard],
  ]);
  return registry.get(key);
};

/**
 * The next window on or after `asOf`: the close date itself still counts —
 * the window is not behind the owner until it has fully passed.
 */
export const nextWindow = (builder: AppealWindowBuilder, asOf: string): AppealWindowDates => {
  const year = Number(asOf.slice(0, 4));
  const current = builder(year);
  return toEpochDays(current.closesOn) < toEpochDays(asOf) ? builder(year + 1) : current;
};

export interface InspectionWindow {
  readonly opensOn: string;
  readonly closesOn: string;
  /** Present only where a conference is a filing prerequisite (KY: PVA). */
  readonly conferenceBy?: string;
  readonly citation: string;
}

/**
 * The Kentucky window with its citation attached — the `us-ky.open-inspection`
 * registry entry, kept as a named export because the KY pack's anchor tests
 * pin it (per-state code is sanctioned here by ADR 0003).
 */
export const kyOpenInspectionWindow = (year: number): InspectionWindow => {
  const window = kyOpenInspection(year);
  return { ...window, citation: 'KRS 133.045' };
};

/**
 * IRC §6654(c): April 15, June 15, September 15, and January 15 of the
 * following year, each rolled off a weekend.
 */
export const federalEstimatedTaxDueDates = (taxYear: number): readonly string[] => {
  assertIntInRange(taxYear, 'taxYear', MIN_YEAR, MAX_YEAR - 1);
  const y = String(taxYear);
  const next = String(taxYear + 1);
  return [`${y}-04-15`, `${y}-06-15`, `${y}-09-15`, `${next}-01-15`].map(rollForwardFromWeekend);
};

/** 1099-NEC: January 31 of the following year (IRC §6071(c)), weekend-rolled. */
export const form1099NecDueDate = (taxYear: number): string => {
  assertIntInRange(taxYear, 'taxYear', MIN_YEAR, MAX_YEAR - 1);
  return rollForwardFromWeekend(`${String(taxYear + 1)}-01-31`);
};

export interface ExchangeClock {
  readonly identifyBy: string;
  readonly acquireBy: string;
  readonly citation: string;
}

/**
 * The §1031 clocks: identification at +45 days, acquisition at +180 — the
 * latter capped in practice by the return due date, which the schema records
 * with its reason; this engine emits the statutory outer bound.
 */
export const exchangeDeadlines = (closedOn: string): ExchangeClock => ({
  identifyBy: addDays(closedOn, 45),
  acquireBy: addDays(closedOn, 180),
  citation: 'IRC s.1031(a)(3)',
});

export const MAX_REMINDER_LEADS = 12;

/** Reminder dates for a deadline, deduplicated and ascending. */
export const reminderSchedule = (dueOn: string, leadDays: readonly number[]): readonly string[] => {
  if (leadDays.length === 0 || leadDays.length > MAX_REMINDER_LEADS) {
    throw new EngineError(`leadDays must hold 1 to ${MAX_REMINDER_LEADS} entries`);
  }
  for (const lead of leadDays) {
    assertIntInRange(lead, 'lead', 0, 365);
  }
  const unique = [...new Set(leadDays)].sort((a, b) => b - a);
  return unique.map((lead) => addDays(dueOn, -lead));
};
