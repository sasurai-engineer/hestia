import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EmergencyDispatch } from '../src/components/EmergencyDispatch';
import { api, type PropertySummary, type VendorOut } from '../src/lib/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PROPERTY: PropertySummary = {
  id: 'p1',
  label: '516 Overton St',
  street_1: '516 Overton St',
  city: 'Newport',
  state: 'KY',
  postal_code: '41071',
  kind: 'single_family',
  year_built: 1910,
  jurisdiction: 'us-ky-newport',
  component_count: 0,
  defect_count: 0,
  next_deadline_on: null,
};

const vendor = (overrides: Partial<VendorOut>): VendorOut => ({
  id: overrides.name ?? 'v',
  entity_id: 'e1',
  entity_name: 'Smoke Test LLC',
  name: 'Vendor',
  trade: 'plumbing',
  phone: '859-555-0100',
  email: null,
  license_number: null,
  license_expires_on: null,
  insurer: null,
  liability_expires_on: '2027-06-30',
  workers_comp_expires_on: null,
  w9_on_file: false,
  is_1099_reportable: false,
  notes: null,
  coverage_state: 'current',
  earliest_expiry: null,
  open_work_orders: 0,
  also_registered_under: [],
  retired_on: null,
  ...overrides,
});

const VENDORS = [
  vendor({ name: 'NKY Plumbing' }),
  vendor({
    name: 'Lapsed Larry',
    phone: '859-555-0199',
    coverage_state: 'expired',
    liability_expires_on: '2026-07-01',
  }),
  vendor({
    name: 'Silent Sam',
    phone: null,
    email: 'sam@example.test',
    coverage_state: 'unknown',
    liability_expires_on: null,
  }),
  vendor({
    name: 'Any Trade Tony',
    trade: 'general_contractor',
    phone: '859-555-0142',
    coverage_state: 'expiring',
  }),
  vendor({
    name: 'Mute Moe',
    phone: null,
    email: null,
    coverage_state: 'expired',
    liability_expires_on: null,
  }),
];

const openDispatch = async () => {
  vi.spyOn(api, 'listProperties').mockResolvedValue([PROPERTY]);
  vi.spyOn(api, 'listVendors').mockResolvedValue(VENDORS);
  const view = render(<EmergencyDispatch open onClose={vi.fn()} />);
  await waitFor(() => {
    expect(screen.getByRole('button', { name: '516 Overton St' })).toBeDefined();
  });
  return view;
};

describe('EmergencyDispatch', () => {
  it('walks property → symptom → a ranked call list, lapsed shown and flagged', async () => {
    await openDispatch();
    fireEvent.click(screen.getByRole('button', { name: '516 Overton St' }));
    expect(screen.getByText('What is happening?')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: /Water — burst pipe/ }));

    const call = screen.getByRole('link', { name: 'Call 859-555-0100' });
    expect(call.getAttribute('href')).toBe('tel:859-555-0100');
    expect(screen.getByText('insured through Jun 30, 2027').className).toBe('dispatch__proof');
    // The lapsed vendor is present, demoted, and loud about why.
    expect(screen.getByText(/liability lapsed Jul 1, 2026/).className).toBe(
      'dispatch__proof dispatch__proof--bad',
    );
    // The unreachable vendor states its gap instead of pretending.
    expect(screen.getByText(/No number on file — sam@example.test/)).toBeDefined();
    expect(screen.getByText('No number on file.')).toBeDefined();
    // The general trade stands in, labeled as what it is.
    expect(screen.getByText('general contractor').className).toBe('pill');
  });

  it('carries the gas safety note above every number', async () => {
    await openDispatch();
    fireEvent.click(screen.getByRole('button', { name: '516 Overton St' }));
    fireEvent.click(screen.getByRole('button', { name: /Gas smell/ }));
    expect(screen.getByText(/gas utility’s emergency line FIRST/)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('What is happening?')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('Which property?')).toBeDefined();
  });

  it('logs the incident with the chosen vendor as an emergency work order', async () => {
    const create = vi.spyOn(api, 'createWorkOrder').mockResolvedValue({} as never);
    await openDispatch();
    fireEvent.click(screen.getByRole('button', { name: '516 Overton St' }));
    fireEvent.click(screen.getByRole('button', { name: /Water — burst pipe/ }));
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Log with this vendor' })[0] as HTMLElement,
    );
    await waitFor(() => {
      expect(screen.getByText(/is on the maintenance board as an emergency/)).toBeDefined();
    });
    expect(create).toHaveBeenCalledWith({
      property_id: 'p1',
      summary: 'Water emergency',
      detail: 'Logged from emergency dispatch: Water — burst pipe, leak, no water',
      priority: 'emergency',
      reported_by: 'owner',
      vendor_id: 'NKY Plumbing',
    });
    // Close resets the walk for the next emergency.
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Which property?')).toBeDefined();
  });

  it('logs without a vendor, and shows the refusal when the ledger says no', async () => {
    const create = vi
      .spyOn(api, 'createWorkOrder')
      .mockRejectedValueOnce(new Error('409: someone got there first'))
      .mockRejectedValueOnce('a bare string refusal')
      .mockResolvedValue({} as never);
    await openDispatch();
    fireEvent.click(screen.getByRole('button', { name: '516 Overton St' }));
    fireEvent.click(screen.getByRole('button', { name: /No heat/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Log the incident without a vendor' }));
    await waitFor(() => {
      expect(screen.getByText(/someone got there first/)).toBeDefined();
    });
    // A refusal that is not an Error still reaches the owner as text.
    fireEvent.click(screen.getByRole('button', { name: 'Log the incident without a vendor' }));
    await waitFor(() => {
      expect(screen.getByText('a bare string refusal')).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Log the incident without a vendor' }));
    await waitFor(() => {
      expect(screen.getByText(/is on the maintenance board/)).toBeDefined();
    });
    expect(create).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ vendor_id: expect.anything() }),
    );
  });

  it('skips the property honestly: numbers yes, logging no', async () => {
    await openDispatch();
    fireEvent.click(screen.getByRole('button', { name: 'Skip — just get me a number' }));
    fireEvent.click(screen.getByRole('button', { name: /Water — burst pipe/ }));
    expect(screen.getByRole('link', { name: 'Call 859-555-0100' })).toBeDefined();
    expect(screen.queryByText(/Log/)).toBeNull();
  });

  it('degrades to an honest empty state when no one answers the trade', async () => {
    // No general trades on this roster either — nobody can stand in.
    vi.spyOn(api, 'listProperties').mockResolvedValue([PROPERTY]);
    vi.spyOn(api, 'listVendors').mockResolvedValue([vendor({ name: 'Pipes Only' })]);
    render(<EmergencyDispatch open onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '516 Overton St' })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: '516 Overton St' }));
    fireEvent.click(screen.getByRole('button', { name: /Roof leak/ }));
    expect(screen.getByText(/No roofing on file/)).toBeDefined();
    expect(screen.getByRole('button', { name: 'Log the incident without a vendor' })).toBeDefined();
  });

  it('retries the fetch on the next open after a failure', async () => {
    const list = vi
      .spyOn(api, 'listProperties')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue([PROPERTY]);
    vi.spyOn(api, 'listVendors').mockResolvedValue(VENDORS);
    const onClose = vi.fn();
    const { rerender } = render(<EmergencyDispatch open onClose={onClose} />);
    await waitFor(() => {
      expect(list).toHaveBeenCalledTimes(1);
    });
    rerender(<EmergencyDispatch open={false} onClose={onClose} />);
    rerender(<EmergencyDispatch open onClose={onClose} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '516 Overton St' })).toBeDefined();
    });
    expect(list).toHaveBeenCalledTimes(2);
  });
});
