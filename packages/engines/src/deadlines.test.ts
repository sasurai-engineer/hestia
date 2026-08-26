import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  addDays,
  appealWindowBuilder,
  dayOfWeek,
  exchangeDeadlines,
  federalEstimatedTaxDueDates,
  firstMondayOfMay,
  form1099NecDueDate,
  fromEpochDays,
  kyOpenInspectionWindow,
  MAX_REMINDER_LEADS,
  MAX_YEAR,
  MIN_YEAR,
  nextWindow,
  nthWeekdayOfMonth,
  reminderSchedule,
  rollForwardFromWeekend,
  toEpochDays,
} from './deadlines.js';
import { EngineError } from './errors.js';

describe('date arithmetic', () => {
  it('round-trips epoch days exactly', () => {
    for (const iso of ['1970-01-01', '2000-02-29', '2026-08-25', '2199-12-31']) {
      expect(fromEpochDays(toEpochDays(iso))).toBe(iso);
    }
    expect(toEpochDays('1970-01-01')).toBe(0);
    expect(toEpochDays('1970-01-02')).toBe(1);
  });

  it('knows the week: 1970-01-01 was a Thursday', () => {
    expect(dayOfWeek('1970-01-01')).toBe(4);
    expect(dayOfWeek('2026-05-04')).toBe(1); // the verified 2026 opening Monday
    expect(dayOfWeek('2026-05-09')).toBe(6); // its first Saturday
    expect(dayOfWeek('2026-05-10')).toBe(0); // its first Sunday
  });

  it('adds days across month, year and leap boundaries', () => {
    expect(addDays('2024-02-28', 1)).toBe('2024-02-29');
    expect(addDays('2023-02-28', 1)).toBe('2023-03-01');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
  });

  it('rejects every malformed or impossible date', () => {
    for (const bad of [
      '2026-2-3',
      '2026-13-01',
      '2026-02-30',
      '2026-00-10',
      'garbage',
      '',
      '2026/05/04',
    ]) {
      expect(() => toEpochDays(bad)).toThrow(EngineError);
    }
    expect(() => toEpochDays('2026-02-30')).toThrow(/not a real calendar date/);
    expect(() => toEpochDays('garbage')).toThrow(/ISO YYYY-MM-DD/);
    expect(() => toEpochDays(`${MIN_YEAR - 1}-01-01`)).toThrow(/year must be an integer/);
    expect(() => toEpochDays(`${MAX_YEAR + 1}-01-01`)).toThrow(EngineError);
    expect(() => toEpochDays(undefined as unknown as string)).toThrow(EngineError);
    expect(() => addDays('2026-01-01', 1.5)).toThrow(/days must be an integer/);
  });
});

describe('weekend roll', () => {
  it('moves Saturday two days and Sunday one, never a weekday', () => {
    expect(rollForwardFromWeekend('2026-05-09')).toBe('2026-05-11'); // Sat -> Mon
    expect(rollForwardFromWeekend('2026-05-10')).toBe('2026-05-11'); // Sun -> Mon
    expect(rollForwardFromWeekend('2026-05-11')).toBe('2026-05-11'); // Mon stands
    expect(rollForwardFromWeekend('2026-05-08')).toBe('2026-05-08'); // Fri stands
  });

  it('always lands on a weekday', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 80_000 }), (days) => {
        const rolled = rollForwardFromWeekend(fromEpochDays(days));
        expect([0, 6]).not.toContain(dayOfWeek(rolled));
      }),
      { numRuns: 60 },
    );
  });
});

describe('the appeal-window registry', () => {
  it('finds nth weekdays by external anchors', () => {
    expect(nthWeekdayOfMonth(2026, 5, 1, 1)).toBe('2026-05-04'); // first Monday of May
    expect(nthWeekdayOfMonth(2026, 11, 4, 4)).toBe('2026-11-26'); // Thanksgiving
    expect(nthWeekdayOfMonth(2026, 3, 2, 5)).toBe('2026-03-31'); // a real fifth Tuesday
    expect(nthWeekdayOfMonth(2026, 1, 4, 1)).toBe('2026-01-01'); // month opens on the weekday
  });

  it('refuses a fifth occurrence that does not exist rather than rolling', () => {
    expect(() => nthWeekdayOfMonth(2026, 2, 1, 5)).toThrow(/no occurrence 5/);
    // Each bound names its own argument, so the caller knows which one is bad.
    expect(() => nthWeekdayOfMonth(2026, 13, 1, 1)).toThrow(/month/);
    expect(() => nthWeekdayOfMonth(2026, 5, 7, 1)).toThrow(/weekday/);
    expect(() => nthWeekdayOfMonth(2026, 5, 1, 0)).toThrow(/nth/);
  });

  it('agrees with firstMondayOfMay for every year', () => {
    fc.assert(
      fc.property(fc.integer({ min: MIN_YEAR, max: MAX_YEAR }), (year) => {
        expect(firstMondayOfMay(year)).toBe(nthWeekdayOfMonth(year, 5, 1, 1));
      }),
      { numRuns: 50 },
    );
  });

  it('resolves exactly the registered keys, each to its own builder', () => {
    // Pin key -> behavior, not just key -> defined: a swapped or emptied
    // registry entry must fail here, in this test, by name.
    const ky = appealWindowBuilder('us-ky.open-inspection');
    expect(ky?.(2026)).toEqual({
      opensOn: '2026-05-04',
      closesOn: '2026-05-18',
      conferenceBy: '2026-05-18',
    });
    const oh = appealWindowBuilder('us-oh.bor-complaint');
    expect(oh?.(2027)).toEqual({ opensOn: '2027-01-01', closesOn: '2027-03-31' });
    expect(appealWindowBuilder('us-zz.not-a-state')).toBeUndefined();
    expect(appealWindowBuilder('')).toBeUndefined();
  });

  it('rolls nextWindow forward only when the close has fully passed', () => {
    const ky = appealWindowBuilder('us-ky.open-inspection');
    if (!ky) throw new Error('KY builder must be registered');
    expect(nextWindow(ky, '2026-08-25').closesOn).toBe('2027-05-17');
    expect(nextWindow(ky, '2026-04-01').closesOn).toBe('2026-05-18');
    // The close date itself still counts; the day after does not.
    expect(nextWindow(ky, '2026-05-18').closesOn).toBe('2026-05-18');
    expect(nextWindow(ky, '2026-05-19').closesOn).toBe('2027-05-17');
  });
});

describe('the Ohio pack entry — us-oh.bor-complaint (ORC 5715.19)', () => {
  // Looked up inside each test, not at describe scope: a collection-time
  // lookup executes during file load, which mutation coverage counts as
  // static and can attribute to no test.
  const oh = (year: number) => {
    const builder = appealWindowBuilder('us-oh.bor-complaint');
    if (!builder) throw new Error('OH builder must be registered');
    return builder(year);
  };

  it('opens January 1 and closes March 31, weekend-extended per ORC 1.14', () => {
    expect(oh(2027)).toEqual({ opensOn: '2027-01-01', closesOn: '2027-03-31' });
    // 2029-03-31 is a Saturday; the deadline extends to Monday April 2.
    expect(oh(2029)).toEqual({ opensOn: '2029-01-01', closesOn: '2029-04-02' });
    // No conference prerequisite exists in Ohio.
    expect(oh(2027).conferenceBy).toBeUndefined();
  });

  it('never closes on a weekend and never later than April 2', () => {
    fc.assert(
      fc.property(fc.integer({ min: MIN_YEAR, max: MAX_YEAR }), (year) => {
        const window = oh(year);
        expect(window.opensOn).toBe(`${String(year)}-01-01`);
        expect(dayOfWeek(window.closesOn)).not.toBe(0);
        expect(dayOfWeek(window.closesOn)).not.toBe(6);
        expect(
          toEpochDays(window.closesOn) - toEpochDays(`${String(year)}-03-31`),
        ).toBeLessThanOrEqual(2);
      }),
      { numRuns: 50 },
    );
  });

  it('bounds its year like every builder', () => {
    expect(() => oh(MAX_YEAR + 1)).toThrow(/year/);
  });
});

describe('the Kentucky pack entry — us-ky.open-inspection (KRS 133.045)', () => {
  it('reproduces the externally verified 2026 window: May 4 through May 18', () => {
    const window = kyOpenInspectionWindow(2026);
    expect(window.opensOn).toBe('2026-05-04');
    expect(window.closesOn).toBe('2026-05-18');
    expect(window.conferenceBy).toBe('2026-05-18');
    expect(window.citation).toBe('KRS 133.045');
  });

  it('computes 2027 — the first window this platform must actually catch', () => {
    const window = kyOpenInspectionWindow(2027);
    expect(window.opensOn).toBe('2027-05-03');
    expect(window.closesOn).toBe('2027-05-17');
  });

  it('always opens on a Monday in the first week of May and spans 15 calendar days', () => {
    fc.assert(
      fc.property(fc.integer({ min: MIN_YEAR, max: MAX_YEAR }), (year) => {
        const window = kyOpenInspectionWindow(year);
        expect(dayOfWeek(window.opensOn)).toBe(1);
        expect(window.opensOn.slice(5, 7)).toBe('05');
        expect(Number(window.opensOn.slice(8, 10))).toBeLessThanOrEqual(7);
        expect(toEpochDays(window.closesOn) - toEpochDays(window.opensOn)).toBe(14);
        // Thirteen countable days: fifteen calendar days minus two Sundays.
        let countable = 0;
        for (let d = toEpochDays(window.opensOn); d <= toEpochDays(window.closesOn); d += 1) {
          if (dayOfWeek(fromEpochDays(d)) !== 0) countable += 1;
        }
        expect(countable).toBe(13);
      }),
      { numRuns: 50 },
    );
  });

  it('bounds its year', () => {
    expect(() => firstMondayOfMay(MIN_YEAR - 1)).toThrow(EngineError);
    expect(() => kyOpenInspectionWindow(MAX_YEAR + 1)).toThrow(EngineError);
    expect(firstMondayOfMay(MIN_YEAR)).toBe('1900-05-07');
  });
});

describe('federal tax dates', () => {
  it('emits the four estimated dates with weekend rolls applied', () => {
    // 2025: June 15 is a Sunday and rolls to the 16th.
    expect(federalEstimatedTaxDueDates(2025)).toEqual([
      '2025-04-15',
      '2025-06-16',
      '2025-09-15',
      '2026-01-15',
    ]);
    // 2026: all four land on weekdays and stand as written.
    expect(federalEstimatedTaxDueDates(2026)).toEqual([
      '2026-04-15',
      '2026-06-15',
      '2026-09-15',
      '2027-01-15',
    ]);
  });

  it('rolls the 1099-NEC date: January 31 2027 is a Sunday', () => {
    expect(form1099NecDueDate(2026)).toBe('2027-02-01');
    expect(form1099NecDueDate(2025)).toBe('2026-02-02'); // Jan 31 2026 is a Saturday
    expect(form1099NecDueDate(2024)).toBe('2025-01-31'); // a Friday, stands
  });

  it('bounds the tax year below the calendar ceiling', () => {
    expect(() => federalEstimatedTaxDueDates(MAX_YEAR)).toThrow(EngineError);
    expect(() => form1099NecDueDate(MAX_YEAR)).toThrow(EngineError);
  });
});

describe('the section 1031 clocks', () => {
  it('emits the statutory 45 and 180 day bounds', () => {
    const clocks = exchangeDeadlines('2026-11-15');
    expect(clocks.identifyBy).toBe('2026-12-30');
    expect(clocks.acquireBy).toBe('2027-05-14');
    expect(clocks.citation).toBe('IRC s.1031(a)(3)');
  });

  it('holds the exact offsets under any closing date', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 80_000 }), (days) => {
        const closed = fromEpochDays(days);
        const clocks = exchangeDeadlines(closed);
        expect(toEpochDays(clocks.identifyBy) - days).toBe(45);
        expect(toEpochDays(clocks.acquireBy) - days).toBe(180);
      }),
      { numRuns: 60 },
    );
  });
});

describe('reminder schedules', () => {
  it('deduplicates, orders ascending, and lands on the due date at lead zero', () => {
    expect(reminderSchedule('2027-05-17', [30, 7, 7, 1, 0])).toEqual([
      '2027-04-17',
      '2027-05-10',
      '2027-05-16',
      '2027-05-17',
    ]);
  });

  it('bounds the lead list', () => {
    expect(() => reminderSchedule('2027-05-17', [])).toThrow(/1 to 12 entries/);
    expect(() =>
      reminderSchedule(
        '2027-05-17',
        Array.from({ length: MAX_REMINDER_LEADS + 1 }, (_, i) => i),
      ),
    ).toThrow(EngineError);
    expect(() => reminderSchedule('2027-05-17', [366])).toThrow(/lead must be an integer/);
    expect(() => reminderSchedule('2027-05-17', [-1])).toThrow(EngineError);
    expect(
      reminderSchedule(
        '2027-05-17',
        Array.from({ length: MAX_REMINDER_LEADS }, (_, i) => i),
      ),
    ).toHaveLength(MAX_REMINDER_LEADS);
  });
});

describe('mutation-resistance: the details that must not drift', () => {
  it('anchors the regex at both ends', () => {
    // Unanchored, 'x2026-05-04' would match at offset 1 and '2026-05-041'
    // would silently truncate the day.
    expect(() => toEpochDays('x2026-05-04')).toThrow(EngineError);
    expect(() => toEpochDays('2026-05-041')).toThrow(EngineError);
    expect(() => toEpochDays('12026-05-04')).toThrow(EngineError);
    expect(() => toEpochDays(' 2026-05-04')).toThrow(EngineError);
    expect(() => toEpochDays('2026-05-04 ')).toThrow(EngineError);
  });

  it('names the bound that was violated', () => {
    expect(() => firstMondayOfMay(1899)).toThrow(/^year must be an integer in \[1900, 2200\]/);
    expect(() => federalEstimatedTaxDueDates(2200)).toThrow(
      /^taxYear must be an integer in \[1900, 2199\]/,
    );
    expect(() => form1099NecDueDate(2200)).toThrow(/^taxYear must be an integer in \[1900, 2199\]/);
    // The last admissible tax year still resolves, into the calendar ceiling.
    expect(federalEstimatedTaxDueDates(2199)[3]).toBe('2200-01-15');
    expect(form1099NecDueDate(2199)).toBe('2200-01-31');
  });

  it('sorts reminder leads regardless of the order they arrive in', () => {
    // Insertion order [1, 30, 0, 7] is neither ascending nor descending, so a
    // broken or missing sort cannot hide behind Set insertion order.
    expect(reminderSchedule('2027-05-17', [1, 30, 0, 7])).toEqual([
      '2027-04-17',
      '2027-05-10',
      '2027-05-16',
      '2027-05-17',
    ]);
  });
});
