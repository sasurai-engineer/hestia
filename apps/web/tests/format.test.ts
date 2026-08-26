import { describe, expect, it } from 'vitest';
import type { ComponentOut } from '../src/lib/api';
import { defectConsequences, formatDate, lifeSummary, titleCase } from '../src/lib/format';

const component = (overrides: Partial<ComponentOut>): ComponentOut => ({
  code: 'water_heater.tank',
  display_name: 'Tank water heater',
  system: 'water_heater',
  installed_year_low: 2014,
  installed_year_high: 2026,
  life_years_low: 8,
  life_years_high: 12,
  condition: 'unknown',
  provenance_kind: 'inferred',
  confidence: 0.5,
  derived_from: 'vintage',
  ...overrides,
});

describe('titleCase', () => {
  it('turns snake_case into words', () => {
    expect(titleCase('assessment_appeal_window')).toBe('Assessment Appeal Window');
    expect(titleCase('flood')).toBe('Flood');
  });
});

describe('formatDate', () => {
  it('renders ISO dates for humans', () => {
    expect(formatDate('2027-05-17')).toBe('May 17, 2027');
    expect(formatDate('2026-12-01')).toBe('Dec 1, 2026');
  });
  it('passes through anything that is not a date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date');
    expect(formatDate('2026-13-01')).toBe('2026-13-01');
  });
});

describe('lifeSummary', () => {
  it('ages from the band midpoint against the high life', () => {
    const summary = lifeSummary(component({}), 2026);
    expect(summary.age).toBe(6); // midpoint 2020
    expect(summary.spent).toBe(0.5);
    expect(summary.beyondExpected).toBe(false);
  });
  it('marks a component past its expected life and clamps the bar', () => {
    const summary = lifeSummary(
      component({ installed_year_low: 2000, installed_year_high: 2000 }),
      2026,
    );
    expect(summary.age).toBe(26);
    expect(summary.spent).toBe(1);
    expect(summary.beyondExpected).toBe(true);
  });
  it('clamps a future-dated band to zero spent', () => {
    const summary = lifeSummary(
      component({ installed_year_low: 2030, installed_year_high: 2030 }),
      2026,
    );
    expect(summary.spent).toBe(0);
  });
  it('answers null when the band or the life is unknown', () => {
    expect(lifeSummary(component({ installed_year_low: null }), 2026)).toEqual({
      age: null,
      spent: null,
      beyondExpected: false,
    });
    expect(lifeSummary(component({ installed_year_high: null }), 2026).age).toBeNull();
    const noLife = lifeSummary(component({ life_years_high: null }), 2026);
    expect(noLife.age).toBe(6);
    expect(noLife.spent).toBeNull();
    const zeroLife = lifeSummary(component({ life_years_high: 0 }), 2026);
    expect(zeroLife.spent).toBeNull();
  });
});

describe('defectConsequences', () => {
  it('lists the consequences in a stable order', () => {
    expect(
      defectConsequences({
        affects_safety: true,
        affects_insurance: false,
        affects_financing: true,
        triggers_disclosure: true,
      }),
    ).toEqual(['safety', 'financing', 'disclosure']);
    expect(
      defectConsequences({
        affects_safety: false,
        affects_insurance: true,
        affects_financing: false,
        triggers_disclosure: false,
      }),
    ).toEqual(['insurance']);
    expect(
      defectConsequences({
        affects_safety: false,
        affects_insurance: false,
        affects_financing: false,
        triggers_disclosure: false,
      }),
    ).toEqual([]);
  });
});
