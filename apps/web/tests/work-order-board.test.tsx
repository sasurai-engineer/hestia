import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { BOARD_COLUMNS, WorkOrderBoard } from '../src/components/WorkOrderBoard';
import type { WorkOrderOut } from '../src/lib/api';

afterEach(cleanup);

const order = (overrides: Partial<WorkOrderOut>): WorkOrderOut => ({
  id: 'w1',
  property_id: 'p1',
  property_label: '998 Monmouth',
  unit_id: null,
  unit_label: null,
  component_id: null,
  component_label: null,
  vendor_id: null,
  vendor_name: null,
  status: 'reported',
  priority: 'routine',
  reported_by: 'owner',
  reported_on: '2026-08-01',
  summary: 'No hot water',
  detail: null,
  scheduled_for: null,
  completed_on: null,
  resolution: null,
  resolution_note: null,
  replacement_component_id: null,
  cancelled_reason: null,
  costs: [],
  net_cost: '0.00',
  legal_transitions: ['cancelled', 'in_progress', 'scheduled', 'triaged'],
  ...overrides,
});

describe('WorkOrderBoard', () => {
  it('starts honest and empty', () => {
    render(<WorkOrderBoard orders={[]} />);
    expect(screen.getByText(/starts honest and empty/)).toBeDefined();
  });

  it('files each job under its own status with a count', () => {
    render(
      <WorkOrderBoard
        orders={[
          order({}),
          order({ id: 'w2', status: 'scheduled', summary: 'Gutter clearing' }),
          order({ id: 'w3', status: 'scheduled', summary: 'Furnace service' }),
        ]}
      />,
    );
    expect(screen.getByText('No hot water')).toBeDefined();
    expect(screen.getByText('Gutter clearing')).toBeDefined();
    // Every column is rendered, even the empty ones, so the shape of the
    // week is visible rather than implied — and each carries its count.
    const headings = screen.getAllByRole('heading', { level: 3 });
    expect(headings).toHaveLength(BOARD_COLUMNS.length);
    expect(headings.map((heading) => heading.textContent)).toEqual([
      'Reported 1',
      'Triaged 0',
      'Scheduled 2',
      'In Progress 0',
      'Completed 0',
    ]);
  });

  it('flags an emergency and shows what a job has cost so far', () => {
    render(
      <WorkOrderBoard
        orders={[
          order({ priority: 'emergency', net_cost: '1850.00', vendor_name: 'Licking Valley' }),
        ]}
      />,
    );
    const flag = screen.getByText('emergency');
    expect(flag.className).toContain('pill--flag');
    expect(screen.getByText(/Licking Valley/)).toBeDefined();
    expect(screen.getByText(/\$1,850\.00/)).toBeDefined();
  });

  it('names the unit when the work is in one, and stays quiet when it is not', () => {
    render(<WorkOrderBoard orders={[order({ unit_label: 'Apt 2', net_cost: '0.00' })]} />);
    expect(screen.getByText(/998 Monmouth · Apt 2/)).toBeDefined();
    // A zero cost is not worth the ink.
    expect(screen.queryByText(/\$0\.00/)).toBeNull();
  });
});
