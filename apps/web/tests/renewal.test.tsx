import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RenewalCard } from '../src/components/RenewalCard';
import type { RenewalContextOut } from '../src/lib/api';
import { renewalAdvice } from '../src/lib/renewal';

afterEach(cleanup);

const context = (overrides: Partial<RenewalContextOut>): RenewalContextOut => ({
  lease_id: 'l1',
  current_rent: '1450.00',
  ends_on: '2027-03-31',
  market_rent: '1550.00',
  market_rent_source: 'unit market rent as of 2026-08-01',
  turn_cost: '1450.00',
  vacancy_days: 21,
  assumptions_source: 'defaults: one month rent, 21 days',
  ...overrides,
});

describe('renewalAdvice', () => {
  it('evaluates every candidate and recommends the best expected value', () => {
    const advice = renewalAdvice(context({}));
    expect(advice.options).toHaveLength(5);
    expect(advice.options.filter((option) => option.recommended)).toHaveLength(1);
    const flat = advice.options[0];
    expect(flat?.increasePercent).toBe(0);
    expect(flat?.newRent).toBe('1450.00');
    expect(flat?.pStayPercent).toBe(92);
    // EV must be strictly ordered by the engine, not the display order.
    const recommended = advice.options.find((option) => option.recommended);
    for (const option of advice.options) {
      expect(Number(recommended?.expectedValue)).toBeGreaterThanOrEqual(
        Number(option.expectedValue),
      );
    }
  });

  it('a brutal turn cost pushes the recommendation toward keeping the resident', () => {
    const gentle = renewalAdvice(context({ turn_cost: '100.00', vacancy_days: 3 }));
    const brutal = renewalAdvice(context({ turn_cost: '6000.00', vacancy_days: 60 }));
    expect(brutal.recommendedIncreasePercent).toBeLessThanOrEqual(
      gentle.recommendedIncreasePercent,
    );
    expect(brutal.pStayModel).toContain('92%');
  });
});

describe('RenewalCard', () => {
  it('renders the EV table with the recommendation and offers on click', () => {
    const onOffer = vi.fn();
    render(<RenewalCard context={context({})} onOffer={onOffer} />);
    expect(screen.getByText('Recommended ask')).toBeDefined();
    expect(screen.getByText('raise').className).toBe('pill pill--flag');
    // The flat renewal is the counterfactual — the road not taken, priced.
    expect(screen.getByText(/Hold the rent flat/).className).toBe('decision__counterfactual');
    expect(screen.getByText(/Lease ends 2027-03-31/)).toBeDefined();
    expect(screen.getByText(/Market \$1,550\.00/)).toBeDefined();
    const offers = screen.getAllByText('Offer');
    expect(offers).toHaveLength(5);
    offers[0]?.click();
    expect(onOffer).toHaveBeenCalledWith('1450.00');
  });

  it('renders without an end date or market rent', () => {
    render(
      <RenewalCard
        context={context({ ends_on: null, market_rent: null, market_rent_source: null })}
        onOffer={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Lease ends/)).toBeNull();
    cleanup();
    // An end date WITHOUT market data: the ends-on line shows alone.
    render(
      <RenewalCard
        context={context({ market_rent: null, market_rent_source: null })}
        onOffer={vi.fn()}
      />,
    );
    expect(screen.getByText(/Lease ends 2027-03-31/)).toBeDefined();
    expect(screen.queryByText(/Market/)).toBeNull();
    cleanup();
    // Market data with a missing source label says so — never 'null'.
    render(<RenewalCard context={context({ market_rent_source: null })} onOffer={vi.fn()} />);
    expect(screen.getByText(/Market \$1,550\.00 \(source unrecorded\)/)).toBeDefined();
  });
});
