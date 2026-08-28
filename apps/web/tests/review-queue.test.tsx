import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReviewQueueTable } from '../src/components/ReviewQueueTable';
import type { StagedTransaction } from '../src/lib/api';

afterEach(cleanup);

const staged = (overrides: Partial<StagedTransaction>): StagedTransaction => ({
  id: 't1',
  posted_on: '2026-08-14',
  amount: '-92.40',
  description: 'DUKE ENERGY BILL PAY',
  suggested_category: 'utilities',
  suggested_property_id: null,
  suggested_is_capital: false,
  suggestion_confidence: 0.7,
  needs_review: true,
  disposition: 'pending',
  ...overrides,
});

describe('ReviewQueueTable', () => {
  it('shows the suggestion with its confidence and pre-selects it', () => {
    render(<ReviewQueueTable rows={[staged({})]} onAccept={vi.fn()} onExclude={vi.fn()} />);
    expect(screen.getByText(/suggested Utilities · 70%/)).toBeDefined();
    const select = screen.getByLabelText('category for DUKE ENERGY BILL PAY') as HTMLSelectElement;
    expect(select.value).toBe('utilities');
  });

  it('shows a suggestion whose rule carried no confidence', () => {
    render(
      <ReviewQueueTable
        rows={[staged({ suggested_category: 'repairs', suggestion_confidence: null })]}
        onAccept={vi.fn()}
        onExclude={vi.fn()}
      />,
    );
    expect(screen.getByText('suggested Repairs')).toBeDefined();
  });

  it('accepts with the chosen category, including an override', () => {
    const onAccept = vi.fn();
    render(<ReviewQueueTable rows={[staged({})]} onAccept={onAccept} onExclude={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('category for DUKE ENERGY BILL PAY'), {
      target: { value: 'repairs' },
    });
    screen.getByText('Accept').click();
    expect(onAccept).toHaveBeenCalledWith('t1', 'repairs');
  });

  it('refuses to accept an unsuggested row until a category is chosen', () => {
    const onAccept = vi.fn();
    render(
      <ReviewQueueTable
        rows={[staged({ suggested_category: null, suggestion_confidence: null })]}
        onAccept={onAccept}
        onExclude={vi.fn()}
      />,
    );
    expect(screen.getByText(/no suggestion — pick a category/)).toBeDefined();
    const accept = screen.getByText('Accept') as HTMLButtonElement;
    expect(accept.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('category for DUKE ENERGY BILL PAY'), {
      target: { value: 'supplies' },
    });
    expect(accept.disabled).toBe(false);
  });

  it('excludes on demand and celebrates an empty queue', () => {
    const onExclude = vi.fn();
    render(<ReviewQueueTable rows={[staged({})]} onAccept={vi.fn()} onExclude={onExclude} />);
    screen.getByText('Exclude').click();
    expect(onExclude).toHaveBeenCalledWith('t1');
    cleanup();
    render(<ReviewQueueTable rows={[]} onAccept={vi.fn()} onExclude={vi.fn()} />);
    expect(screen.getByText(/Queue clear/)).toBeDefined();
  });
});

describe('ReviewQueueTable — the engine split offer', () => {
  const SPLIT = {
    debtId: 'n1',
    lender: 'First Federal',
    interest: '985.61',
    principal: '184.18',
    payment: '1169.79',
    citation: 'engine',
  };
  const mortgageRow = () =>
    staged({
      id: 'm1',
      description: 'FIRST FEDERAL MTG',
      amount: '-1169.79',
      suggested_category: 'mortgage_interest',
      suggested_property_id: 'p1',
    });

  it('an exact match offers the pair and hands back the note', () => {
    const onAcceptSplit = vi.fn();
    render(
      <ReviewQueueTable
        rows={[mortgageRow()]}
        onAccept={vi.fn()}
        onExclude={vi.fn()}
        noteSplits={() => [SPLIT]}
        onAcceptSplit={onAcceptSplit}
      />,
    );
    expect(
      screen.getByText(/engine split: \$985\.61 interest · \$184\.18 principal — First Federal/),
    ).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Accept as engine split' }));
    expect(onAcceptSplit).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), SPLIT);
  });

  it('two exact notes make the operator choose', () => {
    const twin = { ...SPLIT, debtId: 'n2', lender: 'Second Street' };
    const onAcceptSplit = vi.fn();
    render(
      <ReviewQueueTable
        rows={[mortgageRow()]}
        onAccept={vi.fn()}
        onExclude={vi.fn()}
        noteSplits={() => [SPLIT, twin]}
        onAcceptSplit={onAcceptSplit}
      />,
    );
    fireEvent.change(screen.getByLabelText('note for FIRST FEDERAL MTG'), {
      target: { value: '1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Accept as engine split' }));
    expect(onAcceptSplit).toHaveBeenCalledWith(expect.anything(), twin);
  });

  it('an impound remainder explains itself instead of guessing a category', () => {
    render(
      <ReviewQueueTable
        rows={[
          staged({
            id: 'm2',
            description: 'FIRST FEDERAL MTG',
            amount: '-1218.55',
            suggested_category: 'mortgage_interest',
            suggested_property_id: 'p1',
          }),
        ]}
        onAccept={vi.fn()}
        onExclude={vi.fn()}
        noteSplits={() => [SPLIT]}
        onAcceptSplit={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Accept as engine split' })).toBeNull();
    expect(screen.getByText(/\$48\.76 above First Federal.s scheduled payment/)).toBeDefined();
    expect(
      screen.getByText(/no ledger category exists for money a servicer merely holds/),
    ).toBeDefined();
  });

  it('a short row and a non-mortgage category offer nothing', () => {
    render(
      <ReviewQueueTable
        rows={[
          staged({
            id: 's1',
            description: 'SHORT ROW',
            amount: '-10.00',
            suggested_category: 'mortgage_interest',
            suggested_property_id: 'p1',
          }),
          staged({}),
        ]}
        onAccept={vi.fn()}
        onExclude={vi.fn()}
        noteSplits={() => [SPLIT]}
        onAcceptSplit={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Accept as engine split' })).toBeNull();
    expect(screen.queryByText(/engine split/)).toBeNull();
  });
});
