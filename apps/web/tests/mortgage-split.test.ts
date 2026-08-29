import { describe, expect, it } from 'vitest';
import type { DebtOut, LedgerEventOut, ScheduleOut } from '../src/lib/api';
import {
  acceptSplits,
  matchOffers,
  type NoteSplit,
  noteSplit,
  pairMortgageEvents,
  splitOffer,
} from '../src/lib/mortgage-split';

const DEBT = { id: 'n1', lender: 'First Federal' } as DebtOut;

const SCHEDULE = {
  next_interest: '985.61',
  next_principal: '184.18',
  citation: 'engine',
} as ScheduleOut;

const SPLIT: NoteSplit = {
  debtId: 'n1',
  lender: 'First Federal',
  interest: '985.61',
  principal: '184.18',
  payment: '1169.79',
  citation: 'engine',
};

const event = (overrides: Partial<LedgerEventOut>): LedgerEventOut =>
  ({
    event_uuid: overrides.memo ?? 'e',
    occurred_on: '2026-08-28',
    category: 'rent',
    amount: '-1.00',
    memo: null,
    counterparty: null,
    property_id: 'p1',
    entity_id: 'e1',
    lease_id: null,
    unit_id: null,
    is_capital: false,
    capitalisation_rationale: null,
    recorded_at: '2026-08-28T00:00:00Z',
    reversed: false,
    reverses_event_uuid: null,
    ...overrides,
  }) as LedgerEventOut;

const pairEvents = (): LedgerEventOut[] => [
  event({
    event_uuid: 'i1',
    category: 'mortgage_interest',
    amount: '-985.61',
    memo: 'First Federal payment',
    counterparty: 'First Federal',
  }),
  event({
    event_uuid: 'p1e',
    category: 'mortgage_principal',
    amount: '-184.18',
    memo: 'First Federal payment',
    counterparty: 'First Federal',
  }),
];

describe('noteSplit', () => {
  it('carries the engine figures and their exact sum', () => {
    expect(noteSplit(DEBT, SCHEDULE)).toEqual(SPLIT);
  });

  it('a consumed or absent schedule offers nothing', () => {
    expect(noteSplit(DEBT, { ...SCHEDULE, next_interest: null })).toBeNull();
    expect(noteSplit(DEBT, { ...SCHEDULE, next_principal: null })).toBeNull();
  });

  it('names the nameless lender', () => {
    expect(noteSplit({ ...DEBT, lender: null } as DebtOut, SCHEDULE)?.lender).toBe(
      'Unnamed lender',
    );
  });
});

describe('splitOffer', () => {
  it('an exact match offers the pair, either sign', () => {
    expect(splitOffer('1169.79', SPLIT).kind).toBe('exact');
    expect(splitOffer('-1169.79', SPLIT).kind).toBe('exact');
  });

  it('a short row states its shortfall to the cent', () => {
    const offer = splitOffer('-1000.00', SPLIT);
    expect(offer).toEqual({ kind: 'short', split: SPLIT, shortfall: '169.79' });
  });

  it('a rich row names the impound remainder to the cent', () => {
    const offer = splitOffer('-1218.55', SPLIT);
    expect(offer).toEqual({ kind: 'remainder', split: SPLIT, remainder: '48.76' });
  });
});

describe('matchOffers', () => {
  const junior: NoteSplit = {
    debtId: 'n2',
    lender: 'Second Street',
    interest: '100.00',
    principal: '50.00',
    payment: '150.00',
    citation: 'engine',
  };

  it('the figure itself identifies the note', () => {
    const { exact, nearest } = matchOffers('-150.00', [SPLIT, junior]);
    expect(exact).toEqual([junior]);
    expect(nearest).toBeNull();
  });

  it('two notes sharing a payment both stand, for the operator to pick', () => {
    const twin = { ...junior, debtId: 'n3', lender: 'Third Street', payment: '1169.79' };
    const { exact } = matchOffers('1169.79', [SPLIT, twin]);
    expect(exact.map((split) => split.debtId)).toEqual(['n1', 'n3']);
  });

  it('with no exact match, the nearest note explains the miss', () => {
    const { exact, nearest } = matchOffers('-1218.55', [SPLIT, junior]);
    expect(exact).toEqual([]);
    expect(nearest?.kind).toBe('remainder');
    expect(nearest?.split.debtId).toBe('n1');
  });

  it('a later note that misses by less takes the nearest slot', () => {
    // 160 is 10 off the junior note and 1009.79 off the senior: the loop
    // must replace its opening candidate with the closer one.
    const { nearest } = matchOffers('-160.00', [SPLIT, junior]);
    expect(nearest?.split.debtId).toBe('n2');
    expect(nearest?.kind).toBe('remainder');
  });

  it('no notes, no offer', () => {
    expect(matchOffers('-100.00', [])).toEqual({ exact: [], nearest: null });
  });
});

describe('acceptSplits', () => {
  it('carries the row sign so the pair sums to the row exactly', () => {
    expect(acceptSplits('-1169.79', SPLIT)).toEqual([
      { category: 'mortgage_interest', amount: '-985.61' },
      { category: 'mortgage_principal', amount: '-184.18' },
    ]);
    expect(acceptSplits('1169.79', SPLIT)).toEqual([
      { category: 'mortgage_interest', amount: '985.61' },
      { category: 'mortgage_principal', amount: '184.18' },
    ]);
  });
});

describe('acceptSplits and the zero leg', () => {
  it('omits a zero interest leg, which the ledger refuses', () => {
    // A 0%-rate note (seller financing) has no interest in any period. The
    // old shape emitted a 0.00 leg and every offered accept 422'd (#99).
    const free: NoteSplit = { ...SPLIT, interest: '0.00', principal: '250.00', payment: '250.00' };
    expect(acceptSplits('-250.00', free)).toEqual([
      { category: 'mortgage_principal', amount: '-250.00' },
    ]);
  });

  it('omits a zero principal leg the same way', () => {
    const io: NoteSplit = { ...SPLIT, interest: '400.00', principal: '0.00', payment: '400.00' };
    expect(acceptSplits('-400.00', io)).toEqual([
      { category: 'mortgage_interest', amount: '-400.00' },
    ]);
  });

  it('the surviving leg still sums to the row exactly', () => {
    const free: NoteSplit = { ...SPLIT, interest: '0.00', principal: '250.00', payment: '250.00' };
    const legs = acceptSplits('-250.00', free);
    expect(legs.reduce((total, leg) => total + Number(leg.amount), 0)).toBe(-250);
  });
});

describe('pairMortgageEvents', () => {
  it('folds the pair into one payment with the exact total', () => {
    const lines = pairMortgageEvents(pairEvents());
    expect(lines).toHaveLength(1);
    const line = lines[0];
    if (line?.kind !== 'pair') throw new Error('pair expected');
    expect(line.total).toBe('-1169.79');
    expect(line.interest.event_uuid).toBe('i1');
    expect(line.principal.event_uuid).toBe('p1e');
  });

  it('order does not matter: principal first still pairs', () => {
    const lines = pairMortgageEvents([...pairEvents()].reverse());
    expect(lines).toHaveLength(1);
    expect(lines[0]?.kind).toBe('pair');
  });

  it('a struck member breaks the pair — both stand alone', () => {
    const [interest, principal] = pairEvents();
    const lines = pairMortgageEvents([
      { ...(interest as LedgerEventOut), reversed: true },
      principal as LedgerEventOut,
    ]);
    expect(lines.map((line) => line.kind)).toEqual(['single', 'single']);
  });

  it('a different day, memo or counterparty never pairs', () => {
    const [interest, principal] = pairEvents();
    for (const change of [
      { occurred_on: '2026-08-29' },
      { memo: 'other note payment' },
      { counterparty: 'Someone Else' },
    ]) {
      const lines = pairMortgageEvents([
        interest as LedgerEventOut,
        { ...(principal as LedgerEventOut), ...change },
      ]);
      expect(lines.map((line) => line.kind)).toEqual(['single', 'single']);
    }
  });

  it('two payments on one day pair one-to-one, nothing double-spent', () => {
    const [i1, p1] = pairEvents();
    const second = pairEvents().map((entry, index) => ({
      ...entry,
      event_uuid: `${entry.event_uuid}-b${String(index)}`,
    }));
    const lines = pairMortgageEvents([
      i1 as LedgerEventOut,
      p1 as LedgerEventOut,
      ...(second as LedgerEventOut[]),
    ]);
    expect(lines.map((line) => line.kind)).toEqual(['pair', 'pair']);
  });

  it('everything else passes through untouched', () => {
    const rent = event({ event_uuid: 'r1', category: 'rent', amount: '1450.00' });
    expect(pairMortgageEvents([rent])).toEqual([{ kind: 'single', event: rent }]);
  });
});
