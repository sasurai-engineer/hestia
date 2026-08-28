// Test-only fixture loader. Lives beside the sources so vitest resolves it,
// excluded from coverage/mutation via the *.test.ts-adjacent config? No:
// it is imported only by tests, but coverage `all: true` includes it — so it
// stays trivial and fully exercised.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface EngineFixtures {
  readonly amortization: ReadonlyArray<{
    principal: string;
    annualRate: string;
    termMonths: number;
    payment: string;
    totalInterest: string;
    month1Interest: string;
    month1Principal: string;
    finalPayment: string;
    balanceAfter12: string;
  }>;
  readonly depreciation: ReadonlyArray<{
    label: string;
    basis: string;
    method: 'macrs_sl' | 'macrs_200db' | 'macrs_150db';
    lifeYears: string;
    convention: 'mid_month' | 'half_year' | 'mid_quarter';
    bonusPercent: string;
    section179: string;
    placedInServiceMonth: number | null;
    quarter: number | null;
    bonus: string;
    schedule: string[];
  }>;
  readonly section179Limits: ReadonlyArray<{
    state: string;
    cap: string;
    phaseoutStart: string;
    totalPlacedInService: string;
    limit: string;
  }>;
  readonly conformityAddback: ReadonlyArray<{
    label: string;
    state: string;
    accelerated: string;
    numerator: number;
    denominator: number;
    recoveryYears: number;
    addback: string;
    recovery: string[];
  }>;
  readonly disposal: ReadonlyArray<{
    label: string;
    salePrice: string;
    sellingCosts: string;
    originalBasis: string;
    depreciationTaken: string;
    kind: 'personal_property' | 'real_property_sl';
    gain: string;
    loss: string;
    ordinaryRecapture: string;
    unrecaptured1250: string;
    capitalGain: string;
  }>;
  readonly cashflow: {
    flows: string[];
    npvAt4pct: string;
    npvAt5pct: string;
    npvAt6pct: string;
    irrNear: string;
    irrTolerance: string;
  };
  /** A 120-month par bond: coupon 0.5%/month priced at par, so the IRR is
   * the coupon rate by construction — analytic truth, no engine circularity.
   * The long-series case #68 made possible; the Python twin reads it too. */
  readonly cashflowMonthly: {
    flows: string[];
    irrNear: string;
    irrTolerance: string;
  };
  readonly rent: ReadonlyArray<{
    currentRent: string;
    turnCost: string;
    vacancyDays: number;
    increase: string;
    pStay: string;
    expectedGain: string;
    expectedTurnLoss: string;
    expectedValue: string;
  }>;
  readonly coinsurance: ReadonlyArray<{
    loss: string;
    carriedLimit: string;
    replacementCost: string;
    coinsurancePercent: string;
    deductible: string;
    recovery: string;
    retained: string;
  }>;
}

export const loadFixtures = (): EngineFixtures => {
  const here = dirname(fileURLToPath(import.meta.url));
  const path = join(here, '..', 'fixtures', 'engine-fixtures.json');
  return JSON.parse(readFileSync(path, 'utf8')) as EngineFixtures;
};
