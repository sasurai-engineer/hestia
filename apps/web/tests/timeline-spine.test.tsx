import { dayOf } from '@hestia/design';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TimelineSpine } from '../src/components/TimelineSpine';
import type { SpineEvent } from '../src/lib/timeline';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom has no PointerEvent; without one, fired pointer events carry no
// clientX and the drag math would see NaN instead of a coordinate.
if (typeof window.PointerEvent === 'undefined') {
  window.PointerEvent = class extends MouseEvent {} as typeof PointerEvent;
}

const TODAY = '2026-08-27';
const TODAY_DAY = dayOf(TODAY);

const EVENTS: readonly SpineEvent[] = [
  {
    id: 'rent',
    day: TODAY_DAY - 30,
    kind: 'ledger',
    label: 'August rent',
    detail: 'Unit 1 rent received',
    money: '1450.00',
    projected: false,
    faint: false,
  },
  {
    id: 'reversal',
    day: TODAY_DAY - 20,
    kind: 'ledger',
    label: 'Reversed entry',
    detail: 'entered twice',
    money: '-90.00',
    projected: false,
    faint: true,
  },
  {
    id: 'tax',
    day: TODAY_DAY + 35,
    spanStart: TODAY_DAY + 5,
    kind: 'deadline',
    label: 'Property Tax Due',
    detail: '516 Overton St',
    citation: 'KRS 134.015',
    projected: true,
    faint: false,
  },
  {
    id: 'lease',
    day: TODAY_DAY + 120,
    kind: 'lease-end',
    label: 'Lease ends · Unit 1',
    detail: 'A. Renter',
    money: '1450.00',
    projected: true,
    faint: false,
  },
  {
    id: 'capex-1',
    day: TODAY_DAY + 183,
    kind: 'capex',
    label: 'Capex median · year 1',
    detail: 'p10 0.00 · p90 3200.00',
    money: '850.00',
    projected: true,
    faint: false,
  },
  {
    id: 'note',
    day: TODAY_DAY + 400,
    kind: 'debt',
    label: 'Note matures · Heavy Lender',
    detail: '≈ 330 payments remain',
    projected: true,
    faint: false,
  },
];

const renderSpine = (props: Partial<Parameters<typeof TimelineSpine>[0]> = {}) =>
  render(<TimelineSpine events={EVENTS} today={TODAY} ariaLabel="Test spine" {...props} />);

const surface = () => screen.getByRole('application');

describe('TimelineSpine', () => {
  it('draws the datum, every kind of mark, spans, and honest stems', () => {
    const { container } = renderSpine();
    expect(container.querySelector('.chart__datum')).not.toBeNull();
    expect(container.querySelector('.chart__plumb')).not.toBeNull();
    expect(container.querySelectorAll('.chart__mark--deadline')).toHaveLength(1);
    expect(container.querySelectorAll('.chart__mark--lease')).toHaveLength(1);
    expect(container.querySelectorAll('.chart__mark--capex')).toHaveLength(1);
    expect(container.querySelectorAll('.chart__mark--debt')).toHaveLength(1);
    expect(container.querySelectorAll('.chart__mark--faint')).toHaveLength(1);
    expect(container.querySelector('.chart__span')).not.toBeNull();
    expect(container.querySelectorAll('.chart__stem--projected').length).toBeGreaterThan(0);
    expect(screen.getByRole('img', { name: 'Test spine' }).getAttribute('viewBox')).toBe(
      '0 0 680 158',
    );
  });

  it('widens for full-page use', () => {
    renderSpine({ wide: true });
    expect(screen.getByRole('img', { name: 'Test spine' }).getAttribute('viewBox')).toBe(
      '0 0 1080 158',
    );
  });

  it('opens a mark into its detail, toggles it closed, and closes on demand', () => {
    renderSpine();
    const tax = screen.getByRole('button', { name: /deadline: Property Tax Due/ });
    fireEvent.click(tax);
    expect(screen.getByText('KRS 134.015').className).toBe('citation-chip');
    expect(screen.getByText(/window opens/)).toBeDefined();
    fireEvent.click(tax);
    expect(screen.queryByText('KRS 134.015')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /ledger: August rent/ }));
    expect(screen.getByText(/\$1,450\.00/)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByText(/Unit 1 rent received/)).toBeNull();

    // A moneyless, citationless event renders its detail plainly.
    fireEvent.click(screen.getByRole('button', { name: /note maturity: Note matures/ }));
    expect(screen.getByText(/330 payments remain/)).toBeDefined();
    expect(document.querySelector('.citation-chip')).toBeNull();
  });

  it('pans with the arrows, a year with shift, and returns home on T', () => {
    renderSpine();
    const before = screen.getByText('TODAY');
    expect(before).toBeDefined();
    fireEvent.keyDown(surface(), { key: 'ArrowRight', shiftKey: true });
    fireEvent.keyDown(surface(), { key: 'ArrowRight', shiftKey: true });
    // Two years right: today has left the window, the datum with it.
    expect(screen.queryByText('TODAY')).toBeNull();
    fireEvent.keyDown(surface(), { key: 't' });
    expect(screen.getByText('TODAY')).toBeDefined();
    fireEvent.keyDown(surface(), { key: 'ArrowLeft' });
    expect(screen.getByText('TODAY')).toBeDefined();
    fireEvent.keyDown(surface(), { key: 'x' });
    expect(screen.getByText('TODAY')).toBeDefined();
  });

  it('pans by drag using the real surface width when the browser reports one', () => {
    renderSpine();
    const pane = surface();
    vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue({
      width: 915,
      height: 200,
      top: 0,
      left: 0,
      right: 915,
      bottom: 200,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(pane, { clientX: 500 });
    fireEvent.pointerMove(pane, { clientX: 100 });
    // 400px left over 915px of a 915-day window ≈ 400 days into the future.
    expect(screen.queryByText('TODAY')).toBeNull();
    fireEvent.pointerUp(pane);
    fireEvent.pointerMove(pane, { clientX: 900 });
    expect(screen.queryByText('TODAY')).toBeNull();
  });

  it('falls back to the view width for drag math when the rect is empty', () => {
    renderSpine();
    const pane = surface();
    fireEvent.pointerDown(pane, { clientX: 400 });
    fireEvent.pointerMove(pane, { clientX: 100 });
    expect(screen.queryByText('TODAY')).toBeNull();
    fireEvent.pointerLeave(pane);
    fireEvent.pointerMove(pane, { clientX: 0 });
  });

  it('pans on horizontal wheel and shifted vertical wheel, ignoring plain scroll', () => {
    renderSpine();
    const pane = surface();
    fireEvent.wheel(pane, { deltaX: 3000, deltaY: 0 });
    expect(screen.queryByText('TODAY')).toBeNull();
    fireEvent.keyDown(pane, { key: 'T' });
    fireEvent.wheel(pane, { deltaY: 3000, shiftKey: true });
    expect(screen.queryByText('TODAY')).toBeNull();
    fireEvent.keyDown(pane, { key: 'T' });
    fireEvent.wheel(pane, { deltaY: 3000 });
    expect(screen.getByText('TODAY')).toBeDefined();
  });

  it('says so, honestly, when the window holds nothing', () => {
    render(<TimelineSpine events={[]} today={TODAY} ariaLabel="Empty spine" />);
    expect(screen.getByText(/Nothing recorded or due in this window/)).toBeDefined();
  });
});
