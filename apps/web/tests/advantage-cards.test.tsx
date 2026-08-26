import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { CapexFanChart, HoldSellCard, InsuranceCard } from '../src/components/AdvantageCards';
import { ScheduleEView } from '../src/components/ScheduleEView';
import type { CapexForecastOut, Financials, ScheduleEReport } from '../src/lib/api';

afterEach(cleanup);

const financials: Financials = {
  property_id: 'p1',
  income_12mo: '17400.00',
  operating_expenses_12mo: '6200.00',
  noi_12mo: '11200.00',
  valuation: { value: '265000.00', source: 'owner_estimate', as_of: '2026-08-01' },
  debts: [],
  policies: [
    {
      id: 'pol1',
      kind: 'landlord_package',
      carrier: 'Test Mutual',
      effective_to: '2026-12-31',
      coinsurance_percent: '0.8',
      dwelling_limit: '210000.00',
      loss_of_rents_months: 12,
    },
  ],
};

describe('HoldSellCard', () => {
  it('shows the underwater body without a fake ROE line', () => {
    const drowned: Financials = {
      ...financials,
      valuation: { value: '100000.00', source: 'owner_estimate', as_of: '2026-08-01' },
      debts: [
        {
          lender: 'Heavy Lender',
          original_principal: '190000.00',
          annual_rate: '0.0625',
          term_months: 360,
          months_elapsed: 6,
        },
      ],
    };
    render(<HoldSellCard financials={drowned} />);
    expect(screen.getByText('underwater')).toBeDefined();
    expect(screen.getByText(/no\s+return to compute/)).toBeDefined();
    expect(screen.queryByText(/Forward ROE/)).toBeNull();
  });

  it('renders the verdict and recomputes when an assumption is dragged', () => {
    // Free and clear at 3% appreciation: ROE ≈ 7.2%, shy of the 8% default
    // hurdle — the honest verdict is redeploy until the hurdle drops.
    render(<HoldSellCard financials={financials} />);
    expect(screen.getByText('redeploy')).toBeDefined();
    fireEvent.change(screen.getByLabelText(/Hurdle/), { target: { value: '5' } });
    expect(screen.getByText('hold')).toBeDefined();
    fireEvent.change(screen.getByLabelText(/Appreciation/), { target: { value: '-5' } });
    expect(screen.getByText('redeploy')).toBeDefined();
  });

  it('shows the note balance when a mortgage exists', () => {
    render(
      <HoldSellCard
        financials={{
          ...financials,
          debts: [
            {
              lender: 'L',
              original_principal: '190000.00',
              annual_rate: '0.0625',
              term_months: 360,
              months_elapsed: 30,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/note balance/)).toBeDefined();
  });

  it('asks for a valuation when there is none', () => {
    render(<HoldSellCard financials={{ ...financials, valuation: null }} />);
    expect(screen.getByText(/Record a valuation/)).toBeDefined();
  });
});

describe('InsuranceCard', () => {
  it('renders the coinsurance position', () => {
    render(<InsuranceCard financials={financials} />);
    expect(screen.getByText('99% of requirement')).toBeDefined();
    expect(screen.getByText(/Loss of rents: 12 months/)).toBeDefined();
  });

  it('asks for inputs when the position cannot be computed', () => {
    render(<InsuranceCard financials={{ ...financials, policies: [] }} />);
    expect(screen.getByText(/Record a policy/)).toBeDefined();
  });

  it('reports adequacy, an anonymous carrier, and missing loss-of-rents', () => {
    render(
      <InsuranceCard
        financials={{
          ...financials,
          policies: [
            {
              id: 'pol2',
              kind: 'dwelling_fire',
              carrier: null,
              effective_to: '2026-12-31',
              coinsurance_percent: null,
              dwelling_limit: '265000.00',
              loss_of_rents_months: null,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('100% of requirement')).toBeDefined();
    expect(screen.getByText(/No loss-of-rents coverage on record/)).toBeDefined();
  });
});

const forecast: CapexForecastOut = {
  property_id: 'p1',
  horizon_years: 3,
  components_simulated: 11,
  components_without_cost: ['test.costless'],
  bands: [
    { year: 1, expected: '900.00', p10: '0.00', p50: '0.00', p90: '3200.00' },
    { year: 2, expected: '1400.00', p10: '0.00', p50: '850.00', p90: '4100.00' },
    { year: 3, expected: '2100.00', p10: '0.00', p50: '1500.00', p90: '6000.00' },
  ],
  total_expected: '4400.00',
};

describe('CapexFanChart', () => {
  it('renders the fan with its honesty notes', () => {
    render(<CapexFanChart forecast={forecast} />);
    expect(screen.getByText(/\$4,400\.00 expected \/ 3 yrs/)).toBeDefined();
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('3 years');
    expect(screen.getByText(/Not simulated \(no cost on record\): test.costless/)).toBeDefined();
  });

  it('stays quiet when every component carries a cost', () => {
    render(<CapexFanChart forecast={{ ...forecast, components_without_cost: [] }} />);
    expect(screen.queryByText(/Not simulated/)).toBeNull();
  });

  it('points at the dossier when the inventory is empty', () => {
    render(
      <CapexFanChart
        forecast={{ ...forecast, components_simulated: 0, bands: [], total_expected: '0.00' }}
      />,
    );
    expect(screen.getByText(/Assemble the dossier/)).toBeDefined();
  });
});

const report: ScheduleEReport = {
  property_id: 'p1',
  tax_year: 2026,
  income_lines: [
    { line_no: 3, label: 'Rents received', citation: 'Schedule E line 3', amount: '2950.00' },
  ],
  expense_lines: [
    { line_no: 14, label: 'Repairs', citation: 'Schedule E line 14', amount: '5180.00' },
  ],
  depreciation_line_18: '8000.00',
  depreciation_citation: 'Schedule E line 18; dual-book engine',
  total_income: '2950.00',
  total_expenses: '5180.00',
  net: '-10230.00',
  excluded: [
    { label: 'Excluded: principal is not deductible', citation: 'IRC s.163', amount: '411.00' },
  ],
  needs_classification: [
    {
      event_uuid: 'e1',
      occurred_on: '2026-06-20',
      memo: 'sewer line',
      amount: '4800.00',
      reason: 'de minimis threshold',
    },
  ],
  signoff: null,
  caveat: 'not tax advice',
};

describe('ScheduleEView', () => {
  it('renders lines with authorities, flags, exclusions, and the review state', () => {
    render(<ScheduleEView report={report} />);
    expect(screen.getByText('Rents received')).toBeDefined();
    expect(screen.getByText('Schedule E line 3')).toBeDefined();
    expect(screen.getByText(/1 charge\(s\) need a repair-vs-improvement answer/)).toBeDefined();
    expect(screen.getByText(/sewer line/)).toBeDefined();
    cleanup();
    render(
      <ScheduleEView
        report={{
          ...report,
          needs_classification: report.needs_classification.map((row) => ({ ...row, memo: null })),
        }}
      />,
    );
    expect(screen.getByText(/no memo/)).toBeDefined();
    expect(screen.getByText(/principal is not deductible/)).toBeDefined();
    expect(screen.getByText(/Not yet reviewed by a tax professional/)).toBeDefined();
  });

  it('shows the sign-off when one exists and stays quiet when nothing is flagged', () => {
    render(
      <ScheduleEView
        report={{
          ...report,
          needs_classification: [],
          excluded: [],
          signoff: {
            confirmed_by: 'Jane CPA',
            confirmed_at: '2027-02-01T12:00:00Z',
            note: null,
          },
        }}
      />,
    );
    expect(screen.getByText(/Signed off by Jane CPA/)).toBeDefined();
    expect(screen.queryByText(/repair-vs-improvement/)).toBeNull();
  });
});
