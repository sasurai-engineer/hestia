import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScreeningPanel } from '../src/components/ScreeningPanel';
import type { ScreeningOut } from '../src/lib/api';

afterEach(cleanup);

const base: ScreeningOut = {
  id: 's1',
  resident_id: 'r1',
  resident_name: 'Avery Quinn',
  property_id: 'p1',
  property_label: '998 Monmouth St',
  unit_id: null,
  unit_label: null,
  provider: 'manual',
  requested_on: '2026-08-20',
  decision: 'pending',
  decided_on: null,
  decision_basis: null,
  based_on_consumer_report: false,
  adverse_action_required: false,
  adverse_action_sent_on: null,
  citation: null,
  notice_contents: [],
  notes: null,
};

describe('ScreeningPanel', () => {
  it('renders nothing when there is nothing to screen', () => {
    const { container } = render(
      <ScreeningPanel screenings={[]} onDecide={vi.fn()} onNotice={vi.fn()} />,
    );
    expect(container.firstElementChild).toBeNull();
  });

  it('a pending screening offers the decision form and records it', () => {
    const onDecide = vi.fn();
    render(<ScreeningPanel screenings={[base]} onDecide={onDecide} onNotice={vi.fn()} />);
    expect(screen.getByText('Avery Quinn')).toBeDefined();
    expect(screen.getByText('pending').className).toBe('pill');
    fireEvent.change(screen.getByLabelText('Decision'), { target: { value: 'denied' } });
    fireEvent.change(screen.getByLabelText('Decided on'), { target: { value: '2026-08-28' } });
    fireEvent.change(screen.getByLabelText('Basis'), { target: { value: 'income threshold' } });
    fireEvent.click(screen.getByLabelText(/Based on a consumer report/));
    fireEvent.click(screen.getByRole('button', { name: 'Record the decision' }));
    expect(onDecide).toHaveBeenCalledWith('s1', {
      decision: 'denied',
      decided_on: '2026-08-28',
      decision_basis: 'income threshold',
      based_on_consumer_report: true,
    });
  });

  it('empty date and basis are sent as null, not empty strings', () => {
    const onDecide = vi.fn();
    render(<ScreeningPanel screenings={[base]} onDecide={onDecide} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Record the decision' }));
    expect(onDecide).toHaveBeenCalledWith('s1', {
      decision: 'approved',
      decided_on: null,
      decision_basis: null,
      based_on_consumer_report: false,
    });
  });

  it('a decided screening shows the record, not a form', () => {
    render(
      <ScreeningPanel
        screenings={[
          {
            ...base,
            unit_label: 'Unit B',
            decision: 'approved',
            decided_on: '2026-08-25',
            decision_basis: 'clean record',
            based_on_consumer_report: true,
          },
        ]}
        onDecide={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByText('approved').className).toBe('pill pill--ok');
    expect(screen.queryByRole('button', { name: 'Record the decision' })).toBeNull();
    expect(
      screen.getByText(/Decided Aug 25, 2026 — clean record · based on a consumer report/),
    ).toBeDefined();
    expect(screen.getByText(/Unit B/)).toBeDefined();
  });

  it('a decided screening without a date still reads as decided', () => {
    render(
      <ScreeningPanel
        screenings={[{ ...base, decision: 'withdrawn', decided_on: null }]}
        onDecide={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByText('withdrawn').className).toBe('pill pill--skipped');
    expect(screen.getByText('Decided')).toBeDefined();
  });

  it('an owed notice renders the statutory checklist and records the send', () => {
    const onNotice = vi.fn();
    render(
      <ScreeningPanel
        screenings={[
          {
            ...base,
            decision: 'denied',
            decided_on: '2026-08-26',
            based_on_consumer_report: true,
            adverse_action_required: true,
            citation: '15 U.S.C. 1681m(a)',
            notice_contents: [
              { requirement: 'State the adverse action taken', citation: '15 U.S.C. 1681m(a)' },
              {
                requirement: 'Tell the consumer of their right to dispute',
                citation: '15 U.S.C. 1681i',
              },
            ],
          },
        ]}
        onDecide={vi.fn()}
        onNotice={onNotice}
      />,
    );
    expect(screen.getByText('adverse-action notice owed').className).toBe('pill pill--flag');
    // The checklist is the server's law, item for item, each with its stamp.
    expect(screen.getByText('State the adverse action taken')).toBeDefined();
    expect(screen.getByText('Tell the consumer of their right to dispute')).toBeDefined();
    expect(screen.getAllByText('15 U.S.C. 1681m(a)')).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('Sent on'), { target: { value: '2026-08-28' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record the notice' }));
    expect(onNotice).toHaveBeenCalledWith('s1', { sent_on: '2026-08-28' });
  });

  it('an unset sent-on date goes as null so the server dates it', () => {
    const onNotice = vi.fn();
    render(
      <ScreeningPanel
        screenings={[
          {
            ...base,
            decision: 'denied',
            adverse_action_required: true,
            notice_contents: [{ requirement: 'State the adverse action taken', citation: 'x' }],
          },
        ]}
        onDecide={vi.fn()}
        onNotice={onNotice}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Record the notice' }));
    expect(onNotice).toHaveBeenCalledWith('s1', { sent_on: null });
  });

  it('a sent notice shows the date and asks for nothing more', () => {
    render(
      <ScreeningPanel
        screenings={[
          {
            ...base,
            decision: 'denied',
            adverse_action_required: true,
            adverse_action_sent_on: '2026-08-27',
          },
        ]}
        onDecide={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByText(/notice sent Aug 27, 2026/).className).toBe('pill pill--ok');
    expect(screen.queryByRole('button', { name: 'Record the notice' })).toBeNull();
  });

  it('an unknown decision word still renders, neutrally', () => {
    render(
      <ScreeningPanel
        screenings={[{ ...base, decision: 'under_review' }]}
        onDecide={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    // The contract types decision as a plain string; a word this client has
    // never met must not crash the panel or claim a tone it cannot justify.
    expect(screen.getByText('under_review').className).toBe('pill');
  });

  it('a checklist item without a citation renders bare, never a blank stamp', () => {
    render(
      <ScreeningPanel
        screenings={[
          {
            ...base,
            decision: 'denied',
            adverse_action_required: true,
            notice_contents: [{ requirement: 'State the adverse action taken' }],
          },
        ]}
        onDecide={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByText('State the adverse action taken')).toBeDefined();
    expect(document.querySelector('.citation-chip')).toBeNull();
  });

  it('no notice block appears when no notice is owed', () => {
    render(
      <ScreeningPanel
        screenings={[{ ...base, decision: 'approved', decided_on: '2026-08-25' }]}
        onDecide={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.queryByText(/adverse-action notice owed/)).toBeNull();
    expect(screen.queryByText(/notice sent/)).toBeNull();
  });
});
