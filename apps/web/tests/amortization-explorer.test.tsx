import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { AmortizationExplorer } from '../src/components/AmortizationExplorer';
import type { Financials } from '../src/lib/api';

afterEach(cleanup);

const TODAY = '2026-08-28';

const DEBTS: Financials['debts'] = [
  {
    lender: 'First Federal',
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

describe('AmortizationExplorer', () => {
  it('renders a card per live note with both dashed futures and the working', () => {
    const { container } = render(<AmortizationExplorer debts={DEBTS} today={TODAY} />);
    expect(screen.getByText('First Federal')).toBeDefined();
    expect(screen.queryByText('Paid Off')).toBeNull();
    // Both curves are futures: dashed, per the stroke-style law.
    expect(container.querySelectorAll('.chart__line--projected')).toHaveLength(2);
    expect(container.querySelector('.chart__line--series-3')).not.toBeNull();
    expect(screen.getByText(/payments sooner/)).toBeDefined();
    expect(screen.getByText('As scheduled')).toBeDefined();
    expect(screen.getByText('The working')).toBeDefined();
    expect(screen.getByText(/interest never accrues/)).toBeDefined();
  });

  it('recomputes live as the extra scrubs, and zero extra means as-scheduled', () => {
    render(<AmortizationExplorer debts={DEBTS} today={TODAY} />);
    const knob = screen.getByRole('slider', { name: 'Extra principal, every payment' });
    const workingAt100 = screen.getByText(/interest never accrues/).textContent;
    fireEvent.change(knob, { target: { value: '500' } });
    const workingAt500 = screen.getByText(/interest never accrues/).textContent;
    expect(workingAt500).not.toBe(workingAt100);
    fireEvent.change(knob, { target: { value: '0' } });
    expect(screen.getByText('as scheduled').className).toBe('pill');
    expect(screen.getByText(/\$0\.00 of interest never accrues/)).toBeDefined();
  });

  it('handles a note with one payment left: two honest ticks, no fuss', () => {
    render(
      <AmortizationExplorer
        debts={[{ ...(DEBTS[0] as Financials['debts'][number]), months_elapsed: 359 }]}
        today={TODAY}
      />,
    );
    expect(screen.getByText('as scheduled').className).toBe('pill');
    expect(screen.getAllByText(/1 payments — retires Sep 28, 2026/)).toHaveLength(2);
  });

  it('renders nothing when every note is retired', () => {
    const { container } = render(
      <AmortizationExplorer debts={[DEBTS[1] as Financials['debts'][number]]} today={TODAY} />,
    );
    expect(container.firstElementChild).toBeNull();
  });
});
