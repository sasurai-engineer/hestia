import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DocumentFieldsTable } from '../src/components/DocumentFieldsTable';
import type { DocumentField } from '../src/lib/api';

afterEach(cleanup);

const field = (overrides: Partial<DocumentField>): DocumentField => ({
  field_path: 'settlement.sale_price',
  label: 'Sale price',
  datatype: 'money',
  required: true,
  display_order: 2,
  target_hint: 'price_allocations.total_basis',
  raw_value: 'Sale Price of Property   $187,500.00',
  normalised_value: '187500.00',
  accepted_value: null,
  confidence: '1',
  page: 1,
  needs_review: false,
  reviewed_by: null,
  reviewed_at: null,
  model_id: 'deterministic/alta-v1',
  effective_value: '187500.00',
  ...overrides,
});

describe('DocumentFieldsTable', () => {
  it('says when a kind has nothing extractable', () => {
    render(<DocumentFieldsTable fields={[]} disabled={false} onDecision={vi.fn()} />);
    expect(screen.getByText(/Nothing is extractable/)).toBeDefined();
  });

  it('shows the machine read with its page, hint and confidence', () => {
    render(<DocumentFieldsTable fields={[field({})]} disabled={false} onDecision={vi.fn()} />);
    expect(screen.getByText('Sale price *')).toBeDefined();
    expect(screen.getByText('price_allocations.total_basis')).toBeDefined();
    expect(screen.getByText('(p1)')).toBeDefined();
    expect(screen.getByText('100%')).toBeDefined();
  });

  it('labels every review state distinctly', () => {
    render(
      <DocumentFieldsTable
        fields={[
          field({
            field_path: 'a',
            label: 'Ratified',
            reviewed_at: '2026-08-26T00:00:00Z',
            accepted_value: '1.00',
          }),
          field({
            field_path: 'b',
            label: 'Rejected',
            reviewed_at: '2026-08-26T00:00:00Z',
            accepted_value: null,
          }),
          field({
            field_path: 'c',
            label: 'Skeleton',
            raw_value: null,
            normalised_value: null,
            confidence: '0',
            needs_review: true,
            page: null,
            required: false,
            target_hint: null,
            effective_value: null,
          }),
          field({
            field_path: 'd',
            label: 'Typed by hand',
            raw_value: 'something',
            confidence: null,
          }),
        ]}
        disabled={false}
        onDecision={vi.fn()}
      />,
    );
    expect(screen.getByText('ratified')).toBeDefined();
    expect(screen.getByText('rejected')).toBeDefined();
    expect(screen.getByText('not found')).toBeDefined();
    expect(screen.getByText('entered')).toBeDefined();
    // The skeleton row has nothing to accept and shows dashes.
    const accept = screen.getAllByRole('button', { name: 'Accept' }).at(2) as HTMLButtonElement;
    expect(accept.disabled).toBe(true);
  });

  it('routes accept, correct and reject upward', () => {
    const onDecision = vi.fn();
    render(<DocumentFieldsTable fields={[field({})]} disabled={false} onDecision={onDecision} />);
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecision).toHaveBeenCalledWith({
      fieldPath: 'settlement.sale_price',
      action: 'accept',
    });
    const correct = screen.getByRole('button', { name: 'Correct' }) as HTMLButtonElement;
    expect(correct.disabled).toBe(true); // nothing typed yet
    fireEvent.change(screen.getByLabelText('Correct Sale price'), {
      target: { value: ' 190000 ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Correct' }));
    expect(onDecision).toHaveBeenCalledWith({
      fieldPath: 'settlement.sale_price',
      action: 'correct',
      value: '190000',
    });
    // The draft clears after a correction is sent.
    expect((screen.getByLabelText('Correct Sale price') as HTMLInputElement).value).toBe('');
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    expect(onDecision).toHaveBeenCalledWith({
      fieldPath: 'settlement.sale_price',
      action: 'reject',
    });
  });

  it('freezes every control when disabled', () => {
    render(<DocumentFieldsTable fields={[field({})]} disabled={true} onDecision={vi.fn()} />);
    for (const name of ['Accept', 'Correct', 'Reject']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true);
    }
    expect((screen.getByLabelText('Correct Sale price') as HTMLInputElement).disabled).toBe(true);
  });
});
