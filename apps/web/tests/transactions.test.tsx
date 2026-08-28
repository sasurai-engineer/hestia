import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatMoney, TransactionsTable } from '../src/components/TransactionsTable';
import type { LedgerEventOut } from '../src/lib/api';

afterEach(cleanup);

const event = (overrides: Partial<LedgerEventOut>): LedgerEventOut => ({
  event_uuid: 'e1',
  occurred_on: '2026-08-14',
  recorded_at: '2026-08-14T12:00:00Z',
  category: 'repairs',
  amount: '-380.00',
  memo: 'water heater relief valve',
  counterparty: 'NKY Plumbing',
  is_capital: null,
  capitalisation_rationale: null,
  property_id: 'p1',
  unit_id: null,
  lease_id: null,
  entity_id: null,
  reverses_event_uuid: null,
  reversed: false,
  ...overrides,
});

describe('formatMoney', () => {
  it('renders signed dollars with a true minus sign', () => {
    expect(formatMoney('1450.00')).toBe('$1,450.00');
    expect(formatMoney('-380.00')).toBe('−$380.00');
  });
});

describe('TransactionsTable', () => {
  it('renders a row with its category, memo, counterparty, and amount', () => {
    render(<TransactionsTable events={[event({})]} />);
    expect(screen.getByText('Repairs')).toBeDefined();
    expect(screen.getByText('water heater relief valve')).toBeDefined();
    expect(screen.getByText('NKY Plumbing')).toBeDefined();
    expect(screen.getByText('−$380.00')).toBeDefined();
  });

  it('marks capital rows and carries the rationale as the tooltip', () => {
    render(
      <TransactionsTable
        events={[
          event({
            is_capital: true,
            capitalisation_rationale: 'roof: restoration under BAR',
          }),
        ]}
      />,
    );
    const flag = screen.getByText('capital');
    expect(flag.getAttribute('title')).toBe('roof: restoration under BAR');
    // A capital row whose rationale went missing still renders, empty-titled.
    cleanup();
    render(
      <TransactionsTable events={[event({ is_capital: true, capitalisation_rationale: null })]} />,
    );
    expect(screen.getByText('capital').getAttribute('title')).toBe('');
  });

  it('strikes through a reversed pair and never offers to reverse it again', () => {
    const onReverse = vi.fn();
    render(
      <TransactionsTable
        onReverse={onReverse}
        events={[
          event({ event_uuid: 'r1', amount: '380.00', reverses_event_uuid: 'e1' }),
          event({ reversed: true }),
        ]}
      />,
    );
    expect(screen.getByText('reversal')).toBeDefined();
    expect(screen.queryByText('Reverse')).toBeNull();
  });

  it('offers reversal on a live row and reports the click', () => {
    const onReverse = vi.fn();
    render(<TransactionsTable onReverse={onReverse} events={[event({})]} />);
    screen.getByText('Reverse').click();
    expect(onReverse).toHaveBeenCalledWith('e1');
  });

  it('renders read-only without the action column contents', () => {
    render(<TransactionsTable events={[event({})]} />);
    expect(screen.queryByText('Reverse')).toBeNull();
  });

  it('renders a dash for a missing memo and invites entry when empty', () => {
    render(<TransactionsTable events={[event({ memo: null, counterparty: null })]} />);
    expect(screen.getByText('—')).toBeDefined();
    cleanup();
    render(<TransactionsTable events={[]} />);
    expect(screen.getByText(/record one below/i)).toBeDefined();
  });
});

describe('the register folds a mortgage pair into one payment', () => {
  const pair = (): LedgerEventOut[] => [
    event({
      event_uuid: 'mi1',
      category: 'mortgage_interest',
      amount: '-985.61',
      memo: 'First Federal payment',
      counterparty: 'First Federal',
    }),
    event({
      event_uuid: 'mp1',
      category: 'mortgage_principal',
      amount: '-184.18',
      memo: 'First Federal payment',
      counterparty: 'First Federal',
    }),
  ];

  it('one line, the exact total, the split stated beneath', () => {
    render(<TransactionsTable events={pair()} />);
    expect(screen.getByText('Mortgage Payment')).toBeDefined();
    expect(screen.getByText('−$1,169.79')).toBeDefined();
    expect(screen.getByText(/interest −\$985\.61 · principal −\$184\.18/)).toBeDefined();
    // The pair reads as ONE payment: neither category pill stands alone.
    expect(screen.queryByText('Mortgage Interest')).toBeNull();
    expect(screen.queryByText('Mortgage Principal')).toBeNull();
  });

  it('reverses as a payment: both events, one click', () => {
    const onReverse = vi.fn();
    render(<TransactionsTable events={pair()} onReverse={onReverse} />);
    screen.getByText('Reverse').click();
    expect(onReverse).toHaveBeenCalledWith('mi1');
    expect(onReverse).toHaveBeenCalledWith('mp1');
  });

  it('a pair with no memo or counterparty still reads as one payment', () => {
    const bare = pair().map((entry) => ({ ...entry, memo: null, counterparty: null }));
    render(<TransactionsTable events={bare} />);
    expect(screen.getByText('Mortgage Payment')).toBeDefined();
    expect(screen.getByText('—')).toBeDefined();
  });

  it('an inflow pair keeps its ink: only outflows mute', () => {
    const inflow = pair().map((entry) => ({
      ...entry,
      amount: entry.amount.replace('-', ''),
    }));
    render(<TransactionsTable events={inflow} />);
    expect(screen.getByText('$1,169.79').className).not.toContain('muted');
  });

  it('a struck member unfolds the pair back into two honest rows', () => {
    const [interest, principal] = pair();
    render(
      <TransactionsTable
        events={[{ ...(interest as LedgerEventOut), reversed: true }, principal as LedgerEventOut]}
      />,
    );
    expect(screen.queryByText('Mortgage Payment')).toBeNull();
    expect(screen.getByText('Mortgage Interest')).toBeDefined();
    expect(screen.getByText('Mortgage Principal')).toBeDefined();
  });
});
