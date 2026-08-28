import { describe, expect, it } from 'vitest';
import type { CapexForecastOut } from '../src/lib/api';
import { firstShortfall, reserveCoverage } from '../src/lib/reserve';

const forecast: CapexForecastOut = {
  property_id: 'p1',
  horizon_years: 3,
  components_simulated: 4,
  components_without_cost: [],
  bands: [
    { year: 1, expected: '900.00', p10: '0.00', p50: '0.00', p90: '3200.00' },
    { year: 2, expected: '1400.00', p10: '0.00', p50: '850.00', p90: '4100.00' },
    { year: 3, expected: '2100.00', p10: '0.00', p50: '1500.00', p90: '6000.00' },
  ],
  total_expected: '4400.00',
};

describe('reserveCoverage', () => {
  it('funds every year when the reserve outruns the cumulative median', () => {
    const years = reserveCoverage(forecast, 200);
    expect(
      years.map((year) => `${year.year}:${year.cumulativeReserve}/${year.cumulativeMedian}`),
    ).toEqual(['1:2400.00/0.00', '2:4800.00/850.00', '3:7200.00/2350.00']);
    expect(years.every((year) => year.funded)).toBe(true);
    expect(years.every((year) => year.shortfall === '0.00')).toBe(true);
    expect(firstShortfall(years)).toBeNull();
  });

  it('names the first year a thin reserve runs short, to the cent', () => {
    const years = reserveCoverage(forecast, 25);
    expect(years.map((year) => `${year.year}:${year.funded ? 'ok' : year.shortfall}`)).toEqual([
      '1:ok',
      '2:250.00',
      '3:1450.00',
    ]);
    expect(firstShortfall(years)?.year).toBe(2);
  });

  it('a zero reserve is exactly funded while the median is zero, short after', () => {
    const years = reserveCoverage(forecast, 0);
    expect(years[0]?.funded).toBe(true);
    expect(years[1]?.shortfall).toBe('850.00');
  });
});
