/**
 * The spine's arithmetic: every source the platform already holds, merged
 * onto one day-numbered axis. Pure — API rows in, positioned events out —
 * so the whole flagship surface is testable without a browser. Positioning
 * runs on UTC day numbers (see @hestia/design dayOf); only DISPLAY of a
 * date is operator-local, as format.ts insists.
 */
import { dayOf } from '@hestia/design';
import type {
  CapexForecastOut,
  DeadlineOut,
  Financials,
  LeaseSummary,
  LedgerEventOut,
} from './api';
import { titleCase } from './format';

export type SpineKind = 'ledger' | 'deadline' | 'lease-end' | 'capex' | 'debt';

export interface SpineEvent {
  id: string;
  day: number;
  /** A deadline's open window starts here; the mark sits at `day` (due). */
  spanStart?: number;
  kind: SpineKind;
  label: string;
  detail: string;
  money?: string;
  citation?: string;
  /** Strictly after today: dashed stem, kind-colored mark. */
  projected: boolean;
  /** Reversed ledger entries stay on the record, at reduced ink. */
  faint: boolean;
}

export interface SpineWindow {
  startDay: number;
  endDay: number;
}

/** A year of record behind, eighteen months of horizon ahead. */
export function windowAround(todayDay: number): SpineWindow {
  return { startDay: todayDay - 365, endDay: todayDay + 550 };
}

export function panned(window: SpineWindow, days: number): SpineWindow {
  return { startDay: window.startDay + days, endDay: window.endDay + days };
}

const AVERAGE_MONTH_DAYS = 30.44;
const AVERAGE_YEAR_DAYS = 365.25;

export interface SpineInputs {
  today: string;
  ledger?: readonly LedgerEventOut[];
  deadlines?: readonly DeadlineOut[];
  leases?: readonly LeaseSummary[];
  capex?: CapexForecastOut | null;
  debts?: Financials['debts'];
}

const ledgerEvents = (rows: readonly LedgerEventOut[], todayDay: number): SpineEvent[] =>
  rows.map((entry) => {
    const day = dayOf(entry.occurred_on);
    return {
      id: entry.event_uuid,
      day,
      kind: 'ledger' as const,
      label: entry.counterparty ?? titleCase(entry.category),
      detail: entry.memo ?? titleCase(entry.category),
      money: entry.amount,
      projected: day > todayDay,
      faint: entry.reversed,
    };
  });

const deadlineEvents = (rows: readonly DeadlineOut[], todayDay: number): SpineEvent[] =>
  rows
    // A done or dismissed deadline is history the ledger already tells.
    .filter((deadline) => deadline.status !== 'done' && deadline.status !== 'dismissed')
    .map((deadline) => {
      const day = dayOf(deadline.due_on);
      return {
        id: deadline.id,
        day,
        ...(deadline.window_opens_on == null ? {} : { spanStart: dayOf(deadline.window_opens_on) }),
        kind: 'deadline' as const,
        label: titleCase(deadline.kind),
        detail: deadline.note ?? deadline.property_label ?? 'portfolio-wide',
        ...(deadline.citation == null ? {} : { citation: deadline.citation }),
        projected: day > todayDay,
        faint: false,
      };
    });

const leaseEvents = (rows: readonly LeaseSummary[], todayDay: number): SpineEvent[] =>
  rows
    .filter((lease) => lease.ends_on != null)
    .map((lease) => {
      const day = dayOf(lease.ends_on as string);
      return {
        id: `lease-${lease.id}`,
        day,
        kind: 'lease-end' as const,
        label: `Lease ends · ${lease.unit_label ?? lease.property_label}`,
        detail: lease.residents.join(', '),
        money: lease.rent,
        projected: day > todayDay,
        faint: false,
      };
    });

const capexEvents = (
  forecast: CapexForecastOut | null | undefined,
  todayDay: number,
): SpineEvent[] =>
  (forecast?.bands ?? [])
    // A zero median is the simulation saying "probably nothing" — noise here.
    .filter((band) => Number(band.p50) !== 0)
    .map((band) => ({
      id: `capex-${band.year}`,
      day: todayDay + Math.round((band.year - 0.5) * AVERAGE_YEAR_DAYS),
      kind: 'capex' as const,
      label: `Capex median · year ${band.year}`,
      detail: `p10 ${band.p10} · p90 ${band.p90}, Weibull over the component inventory`,
      money: band.p50,
      projected: true,
      faint: false,
    }));

const debtEvents = (rows: Financials['debts'], todayDay: number): SpineEvent[] =>
  rows.flatMap((debt, index) => {
    const remaining = debt.term_months - debt.months_elapsed;
    if (remaining <= 0) {
      return [];
    }
    return [
      {
        id: `debt-${index}-${debt.lender}`,
        day: todayDay + Math.round(remaining * AVERAGE_MONTH_DAYS),
        kind: 'debt' as const,
        label: `Note matures · ${debt.lender}`,
        detail: `≈ ${remaining} payments remain on ${debt.original_principal}`,
        projected: true,
        faint: false,
      },
    ];
  });

export function buildSpine(inputs: SpineInputs): SpineEvent[] {
  const todayDay = dayOf(inputs.today);
  return [
    ...ledgerEvents(inputs.ledger ?? [], todayDay),
    ...deadlineEvents(inputs.deadlines ?? [], todayDay),
    ...leaseEvents(inputs.leases ?? [], todayDay),
    ...capexEvents(inputs.capex, todayDay),
    ...debtEvents(inputs.debts ?? [], todayDay),
  ].sort((a, b) => a.day - b.day || a.id.localeCompare(b.id));
}

/** Events whose mark or window touches the view. */
export function visibleEvents(events: readonly SpineEvent[], window: SpineWindow): SpineEvent[] {
  return events.filter(
    (event) =>
      (event.day >= window.startDay && event.day <= window.endDay) ||
      (event.spanStart !== undefined &&
        event.spanStart <= window.endDay &&
        event.day >= window.startDay),
  );
}

/**
 * Greedy lane assignment: marks closer than `gapDays` climb to the next of
 * three lanes rather than overprint — a ledger is legible or it is wrong.
 */
export function layoutSpine(
  events: readonly SpineEvent[],
  gapDays: number,
): (SpineEvent & { lane: number })[] {
  const lastDayPerLane: number[] = [];
  return events.map((event) => {
    let lane = 0;
    while (lane < lastDayPerLane.length) {
      const last = lastDayPerLane[lane] as number;
      if (event.day - last >= gapDays) {
        break;
      }
      lane += 1;
    }
    const bounded = lane % 3;
    if (lane < 3) {
      lastDayPerLane[lane] = event.day;
    } else {
      lastDayPerLane[bounded] = event.day;
    }
    return { ...event, lane: bounded };
  });
}
