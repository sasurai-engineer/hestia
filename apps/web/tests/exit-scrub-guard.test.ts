import { describe, expect, it, vi } from 'vitest';
import type { Financials } from '../src/lib/api';
import { buildExitModel } from '../src/lib/exit-scrub';

// Only an EngineError means "no internal rate exists"; anything else is a
// defect and must escape. The guard is proven by injection: a poisoned irr
// in its own module graph, so the honest-null tests stay on the real one.
vi.mock('@hestia/engines', async (importOriginal) => {
  const original = await importOriginal<typeof import('@hestia/engines')>();
  return {
    ...original,
    irr: () => {
      throw new TypeError('not an engine refusal');
    },
  };
});

const FIN: Financials = {
  property_id: 'p1',
  income_12mo: '17400.00',
  operating_expenses_12mo: '6200.00',
  noi_12mo: '11200.00',
  valuation: { value: '265000.00', source: 'owner_estimate', as_of: '2026-08-01' },
  debts: [],
  policies: [],
};

describe('the irr guard', () => {
  it('lets a non-engine failure escape instead of dressing it as null', () => {
    expect(() =>
      buildExitModel(FIN, '2026-08-27', {
        appreciationPercent: 3,
        hurdlePercent: 8,
        sellingCostPercent: 6,
      }),
    ).toThrow(TypeError);
  });
});
