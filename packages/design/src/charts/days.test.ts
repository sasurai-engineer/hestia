import { describe, expect, it } from 'vitest';
import { dayOf, isoOf, timeTicks } from './days.js';

const tickShape = (tick: { day: number; label: string; major: boolean }) =>
  `${isoOf(tick.day)} ${tick.label}${tick.major ? ' *' : ''}`;

describe('dayOf / isoOf', () => {
  it('counts whole days from the epoch and round-trips', () => {
    expect(dayOf('1970-01-01')).toBe(0);
    expect(dayOf('1970-01-02')).toBe(1);
    for (const iso of ['2026-08-27', '2024-02-29', '1999-12-31']) {
      expect(isoOf(dayOf(iso))).toBe(iso);
    }
  });

  it('knows a leap year from a common one', () => {
    expect(dayOf('2024-03-01') - dayOf('2024-02-28')).toBe(2);
    expect(dayOf('2026-03-01') - dayOf('2026-02-28')).toBe(1);
  });

  it('refuses malformed and impossible dates by name', () => {
    expect(() => dayOf('2026-2-05')).toThrow('not a date-only ISO string: 2026-2-05');
    // Day overflow (day drifts) and month overflow (year drifts) each refused.
    expect(() => dayOf('2026-02-30')).toThrow('not a real calendar date: 2026-02-30');
    expect(() => dayOf('2026-13-01')).toThrow(RangeError);
    expect(() => dayOf('garbage')).toThrow(RangeError);
    // The pattern is anchored at both ends: prefix and suffix junk is
    // refused AS MALFORMED — never half-parsed into a calendar complaint.
    expect(() => dayOf('x1970-01-01')).toThrow('not a date-only ISO string: x1970-01-01');
    expect(() => dayOf('1970-01-011')).toThrow('not a date-only ISO string: 1970-01-011');
    expect(() => isoOf(1.5)).toThrow('day numbers are whole days, got 1.5');
  });
});

describe('timeTicks', () => {
  it('marks every month across a short span, January as the year', () => {
    const ticks = timeTicks(dayOf('2026-11-15'), dayOf('2027-02-10'));
    expect(ticks.map(tickShape)).toEqual(['2026-12-01 Dec', '2027-01-01 2027 *', '2027-02-01 Feb']);
  });

  it('includes a boundary the span starts on, and none it merely grazes', () => {
    const ticks = timeTicks(dayOf('2026-11-01'), dayOf('2026-12-02'));
    expect(ticks.map(tickShape)).toEqual(['2026-11-01 Nov', '2026-12-01 Dec']);
    // A start ONE day later must not claim the November boundary.
    const later = timeTicks(dayOf('2026-11-02'), dayOf('2026-12-02'));
    expect(later.map(tickShape)).toEqual(['2026-12-01 Dec']);
    // A span ENDING exactly on a boundary keeps that tick.
    const flush = timeTicks(dayOf('2026-11-15'), dayOf('2027-02-01'));
    expect(flush.map(tickShape)).toEqual(['2026-12-01 Dec', '2027-01-01 2027 *', '2027-02-01 Feb']);
  });

  it('names every month of a spring-to-autumn walk', () => {
    const ticks = timeTicks(dayOf('2027-02-15'), dayOf('2027-10-02'));
    expect(ticks.map((tick) => tick.label)).toEqual([
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
    ]);
  });

  it('thins to aligned quarters on a multi-year span', () => {
    const ticks = timeTicks(dayOf('2026-02-15'), dayOf('2028-08-01'));
    expect(ticks.map(tickShape)).toEqual([
      '2026-04-01 Apr',
      '2026-07-01 Jul',
      '2026-10-01 Oct',
      '2027-01-01 2027 *',
      '2027-04-01 Apr',
      '2027-07-01 Jul',
      '2027-10-01 Oct',
      '2028-01-01 2028 *',
      '2028-04-01 Apr',
      '2028-07-01 Jul',
    ]);
  });

  it('thins to Januaries alone on a decade', () => {
    const ticks = timeTicks(dayOf('2026-06-01'), dayOf('2036-01-05'));
    expect(ticks).toHaveLength(10);
    expect(ticks.every((tick) => tick.major)).toBe(true);
    expect(ticks.map((tick) => tick.label)).toEqual([
      '2027',
      '2028',
      '2029',
      '2030',
      '2031',
      '2032',
      '2033',
      '2034',
      '2035',
      '2036',
    ]);
  });

  it('switches density exactly at the documented spans', () => {
    // 800 days of months vs 801 of quarters, from an epoch January 1st.
    expect(timeTicks(0, 800).length).toBe(27);
    expect(timeTicks(0, 801).length).toBe(9);
    // 2400 days of quarters vs 2401 of years.
    expect(timeTicks(0, 2400).length).toBe(27);
    expect(timeTicks(0, 2401).length).toBe(7);
  });

  it('refuses fractional and disordered bounds', () => {
    expect(() => timeTicks(0.5, 10)).toThrow('tick bounds are whole days, got 0.5..10');
    expect(() => timeTicks(10, 10)).toThrow('tick bounds must be ordered, got 10..10');
    expect(() => timeTicks(11, 10)).toThrow(RangeError);
  });
});
