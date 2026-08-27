import { dayOf } from '@hestia/design';
import { describe, expect, it } from 'vitest';
import type {
  CapexForecastOut,
  DeadlineOut,
  Financials,
  LeaseSummary,
  LedgerEventOut,
} from '../src/lib/api';
import {
  buildSpine,
  layoutSpine,
  panned,
  type SpineEvent,
  visibleEvents,
  windowAround,
} from '../src/lib/timeline';

const TODAY = '2026-08-27';
const TODAY_DAY = dayOf(TODAY);

const ledger = (overrides: Partial<LedgerEventOut>): LedgerEventOut => ({
  event_uuid: 'e1',
  occurred_on: '2026-08-14',
  recorded_at: '2026-08-14T12:00:00Z',
  category: 'repairs',
  amount: '-380.00',
  memo: 'water heater relief valve',
  counterparty: 'NKY Plumbing',
  is_capital: null,
  capitalisation_rationale: null,
  property_id: 'p1',
  unit_id: null,
  lease_id: null,
  entity_id: null,
  reverses_event_uuid: null,
  reversed: false,
  ...overrides,
});

const deadline = (overrides: Partial<DeadlineOut>): DeadlineOut => ({
  id: 'd1',
  kind: 'property_tax_due',
  due_on: '2026-10-01',
  window_opens_on: null,
  citation: 'KRS 134.015',
  note: null,
  property_label: '516 Overton St',
  status: 'open',
  ...overrides,
});

const lease = (overrides: Partial<LeaseSummary>): LeaseSummary => ({
  id: 'l1',
  property_label: '516 Overton St',
  unit_label: 'Unit 1',
  residents: ['A. Renter'],
  rent: '1450.00',
  starts_on: '2026-04-01',
  ends_on: '2027-03-31',
  status: 'active',
  balance_due: '0.00',
  open_credit: '0.00',
  ...overrides,
});

const capex: CapexForecastOut = {
  property_id: 'p1',
  horizon_years: 2,
  components_simulated: 4,
  components_without_cost: [],
  bands: [
    { year: 1, expected: '900.00', p10: '0.00', p50: '0.00', p90: '3200.00' },
    { year: 2, expected: '1400.00', p10: '0.00', p50: '850.00', p90: '4100.00' },
  ],
  total_expected: '2300.00',
};

const debts: Financials['debts'] = [
  {
    lender: 'Heavy Lender',
    original_principal: '190000.00',
    annual_rate: '0.0625',
    term_months: 360,
    months_elapsed: 30,
  },
  {
    lender: 'Paid Off',
    original_principal: '10000.00',
    annual_rate: '0.05',
    term_months: 60,
    months_elapsed: 60,
  },
];

describe('windowAround / panned', () => {
  it('opens a year of record and eighteen months of horizon, and pans whole', () => {
    const window = windowAround(TODAY_DAY);
    expect(window).toEqual({ startDay: TODAY_DAY - 365, endDay: TODAY_DAY + 550 });
    expect(panned(window, 31)).toEqual({
      startDay: TODAY_DAY - 334,
      endDay: TODAY_DAY + 581,
    });
  });
});

describe('buildSpine', () => {
  it('is empty on empty inputs', () => {
    expect(buildSpine({ today: TODAY })).toEqual([]);
  });

  it('turns ledger rows into past marks, keeping reversals at reduced ink', () => {
    const events = buildSpine({
      today: TODAY,
      ledger: [
        ledger({}),
        ledger({ event_uuid: 'e2', counterparty: null, memo: null, reversed: true }),
      ],
    });
    expect(events).toHaveLength(2);
    const [named, anonymous] = events as [SpineEvent, SpineEvent];
    expect(named.label).toBe('NKY Plumbing');
    expect(named.detail).toBe('water heater relief valve');
    expect(named.money).toBe('-380.00');
    expect(named.projected).toBe(false);
    expect(named.faint).toBe(false);
    expect(anonymous.label).toBe('Repairs');
    expect(anonymous.detail).toBe('Repairs');
    expect(anonymous.faint).toBe(true);
  });

  it('marks deadlines with their windows and authorities, skipping the settled', () => {
    const events = buildSpine({
      today: TODAY,
      deadlines: [
        deadline({ window_opens_on: '2026-09-01' }),
        deadline({ id: 'd2', status: 'done' }),
        deadline({ id: 'd3', status: 'dismissed' }),
        deadline({
          id: 'd4',
          citation: null,
          note: 'inspection window',
          property_label: null,
          due_on: '2026-07-01',
        }),
      ],
    });
    expect(events).toHaveLength(2);
    const [past, future] = events as [SpineEvent, SpineEvent];
    expect(future.spanStart).toBe(dayOf('2026-09-01'));
    expect(future.citation).toBe('KRS 134.015');
    expect(future.detail).toBe('516 Overton St');
    expect(future.projected).toBe(true);
    expect(past.citation).toBeUndefined();
    expect(past.detail).toBe('inspection window');
    expect(past.projected).toBe(false);
  });

  it('falls back to portfolio-wide when a deadline names nothing', () => {
    const events = buildSpine({
      today: TODAY,
      deadlines: [deadline({ note: null, property_label: null })],
    });
    expect((events[0] as SpineEvent).detail).toBe('portfolio-wide');
  });

  it('marks lease ends by unit, skipping leases without one', () => {
    const events = buildSpine({
      today: TODAY,
      leases: [
        lease({}),
        lease({ id: 'l2', ends_on: null }),
        lease({ id: 'l3', unit_label: null, residents: ['B', 'C'] }),
      ],
    });
    expect(events).toHaveLength(2);
    expect((events[0] as SpineEvent).label).toBe('Lease ends · Unit 1');
    expect((events[0] as SpineEvent).money).toBe('1450.00');
    expect((events[1] as SpineEvent).label).toBe('Lease ends · 516 Overton St');
    expect((events[1] as SpineEvent).detail).toBe('B, C');
  });

  it('marks nonzero capex medians at each forward mid-year', () => {
    const events = buildSpine({ today: TODAY, capex });
    expect(events).toHaveLength(1);
    const mark = events[0] as SpineEvent;
    expect(mark.id).toBe('capex-2');
    expect(mark.day).toBe(TODAY_DAY + Math.round(1.5 * 365.25));
    expect(mark.money).toBe('850.00');
    expect(mark.projected).toBe(true);
    expect(buildSpine({ today: TODAY, capex: null })).toEqual([]);
  });

  it('projects note maturity from remaining term, skipping retired notes', () => {
    const events = buildSpine({ today: TODAY, debts });
    expect(events).toHaveLength(1);
    const note = events[0] as SpineEvent;
    expect(note.label).toBe('Note matures · Heavy Lender');
    expect(note.day).toBe(TODAY_DAY + Math.round(330 * 30.44));
    expect(note.detail).toContain('330 payments remain');
  });

  it('sorts by day with a stable id tiebreak', () => {
    const events = buildSpine({
      today: TODAY,
      ledger: [
        ledger({ event_uuid: 'z-later', occurred_on: '2026-08-14' }),
        ledger({ event_uuid: 'a-first', occurred_on: '2026-08-14' }),
        ledger({ event_uuid: 'm-early', occurred_on: '2026-01-02' }),
      ],
    });
    expect(events.map((event) => event.id)).toEqual(['m-early', 'a-first', 'z-later']);
  });
});

describe('visibleEvents', () => {
  const window = { startDay: 100, endDay: 200 };
  const at = (day: number, spanStart?: number): SpineEvent => ({
    id: `at-${day}`,
    day,
    ...(spanStart === undefined ? {} : { spanStart }),
    kind: 'deadline',
    label: '',
    detail: '',
    projected: false,
    faint: false,
  });

  it('keeps marks inside the window and windows that reach into it', () => {
    expect(visibleEvents([at(150)], window)).toHaveLength(1);
    expect(visibleEvents([at(99)], window)).toHaveLength(0);
    expect(visibleEvents([at(201)], window)).toHaveLength(0);
    // Due beyond the view, but its open window reaches in: visible.
    expect(visibleEvents([at(250, 180)], window)).toHaveLength(1);
    // Whole span before the view: not visible.
    expect(visibleEvents([at(90, 60)], window)).toHaveLength(0);
  });
});

describe('layoutSpine', () => {
  const at = (day: number, id: string): SpineEvent => ({
    id,
    day,
    kind: 'ledger',
    label: '',
    detail: '',
    projected: false,
    faint: false,
  });

  it('spreads crowded marks across three lanes and spills back to the first', () => {
    const laid = layoutSpine([at(10, 'a'), at(11, 'b'), at(12, 'c'), at(13, 'd')], 5);
    expect(laid.map((event) => event.lane)).toEqual([0, 1, 2, 0]);
  });

  it('returns to the ground lane once the gap clears', () => {
    const laid = layoutSpine([at(10, 'a'), at(11, 'b'), at(40, 'c')], 5);
    expect(laid.map((event) => event.lane)).toEqual([0, 1, 0]);
  });
});
