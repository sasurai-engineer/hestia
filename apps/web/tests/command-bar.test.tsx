import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CommandBar } from '../src/components/CommandBar';
import { api } from '../src/lib/api';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  push.mockClear();
});

const PROPERTIES = [
  {
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
  },
];

describe('CommandBar', () => {
  it('opens on ⌘K, lists the routes, and navigates on run', async () => {
    vi.spyOn(api, 'listProperties').mockResolvedValue(PROPERTIES);
    render(<CommandBar />);
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = screen.getByRole('combobox');
    expect(input).toBeDefined();
    fireEvent.change(input, { target: { value: 'calen' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(push).toHaveBeenCalledWith('/calendar');
    // The palette closed itself before running the command.
    expect(
      screen.getByLabelText('Command palette', { selector: 'dialog' }).hasAttribute('open'),
    ).toBe(false);
  });

  it('loads properties once, on first open, and never again', async () => {
    const list = vi.spyOn(api, 'listProperties').mockResolvedValue(PROPERTIES);
    render(<CommandBar />);
    fireEvent.click(screen.getByRole('button', { name: '⌘K — open the command palette' }));
    await waitFor(() => {
      expect(screen.getByText('Property: 516 Overton St')).toBeDefined();
    });
    fireEvent.click(screen.getByText('Property: 516 Overton St'));
    expect(push).toHaveBeenCalledWith('/property/p1');

    fireEvent.click(screen.getByRole('button', { name: '⌘K — open the command palette' }));
    expect(list).toHaveBeenCalledTimes(1);
  });

  it('opens the 11pm surface from the palette and the masthead control', async () => {
    vi.spyOn(api, 'listProperties').mockResolvedValue(PROPERTIES);
    vi.spyOn(api, 'listVendors').mockResolvedValue([]);
    render(<CommandBar />);
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    fireEvent.click(screen.getByText(/Emergency: burst pipe/));
    const dispatch = screen.getByLabelText('Emergency dispatch', { selector: 'dialog' });
    expect(dispatch.hasAttribute('open')).toBe(true);
    fireEvent(dispatch, new Event('close'));
    expect(dispatch.hasAttribute('open')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Emergency' }));
    expect(dispatch.hasAttribute('open')).toBe(true);
  });

  it('stays useful when the property fetch fails, and retries next open', async () => {
    const list = vi
      .spyOn(api, 'listProperties')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(PROPERTIES);
    render(<CommandBar />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    // Routes answer even while properties are unavailable.
    expect(screen.getByText('Go: Vendors')).toBeDefined();
    await waitFor(() => {
      expect(list).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText(/Property:/)).toBeNull();

    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await waitFor(() => {
      expect(screen.getByText('Property: 516 Overton St')).toBeDefined();
    });
    expect(list).toHaveBeenCalledTimes(2);
  });
});
