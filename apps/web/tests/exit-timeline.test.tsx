import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExitTimeline } from '../src/components/ExitTimeline';
import type { Financials } from '../src/lib/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom has no PointerEvent; without one, fired pointer events carry no
// clientX and the scrub math would see NaN instead of a coordinate.
if (typeof window.PointerEvent === 'undefined') {
  window.PointerEvent = class extends MouseEvent {} as typeof PointerEvent;
}

const TODAY = '2026-08-27';

const financials = (overrides: Partial<Financials> = {}): Financials => ({
  property_id: 'p1',
  income_12mo: '17400.00',
  operating_expenses_12mo: '6200.00',
  noi_12mo: '11200.00',
  valuation: { value: '265000.00', source: 'owner_estimate', as_of: '2026-08-01' },
  debts: [],
  policies: [],
  ...overrides,
});

const renderExit = (fin: Financials = financials()) =>
  render(<ExitTimeline financials={fin} today={TODAY} />);

const slider = () => screen.getByRole('slider', { name: 'Exit month' });
const surface = () => document.querySelector('.exit__surface') as HTMLDivElement;

describe('ExitTimeline', () => {
  it('asks for a valuation before it will price an exit', () => {
    renderExit(financials({ valuation: null }));
    expect(screen.getByText(/Record a valuation to unlock the exit instrument/)).toBeDefined();
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('opens at five years with the full instrument drawn', () => {
    const { container } = renderExit();
    expect(slider().getAttribute('aria-valuenow')).toBe('60');
    expect(slider().getAttribute('aria-valuetext')).toMatch(/^exit .* — IRR -?[\d.]+%$/);
    expect(screen.getByText('Exit IRR, effective annual')).toBeDefined();
    expect(container.querySelector('.chart__line--projected')).not.toBeNull();
    expect(container.querySelector('.chart__hurdle')).not.toBeNull();
    expect(screen.getByText('hurdle 8%')).toBeDefined();
    expect(container.querySelector('.chart__datum')).not.toBeNull();
    expect(container.querySelector('.chart__exit')).not.toBeNull();
    expect(screen.getByText('Exit value')).toBeDefined();
    expect(screen.getByText('Net proceeds, pre-tax')).toBeDefined();
    expect(screen.getByText(/Every figure here is pre-tax/)).toBeDefined();
  });

  it('scrubs by keyboard: month, year, and both ends', () => {
    renderExit();
    fireEvent.keyDown(slider(), { key: 'ArrowRight' });
    expect(slider().getAttribute('aria-valuenow')).toBe('61');
    fireEvent.keyDown(slider(), { key: 'ArrowLeft', shiftKey: true });
    expect(slider().getAttribute('aria-valuenow')).toBe('49');
    fireEvent.keyDown(slider(), { key: 'Home' });
    expect(slider().getAttribute('aria-valuenow')).toBe('1');
    fireEvent.keyDown(slider(), { key: 'ArrowLeft' });
    expect(slider().getAttribute('aria-valuenow')).toBe('1');
    fireEvent.keyDown(slider(), { key: 'End' });
    expect(slider().getAttribute('aria-valuenow')).toBe('120');
    fireEvent.keyDown(slider(), { key: 'ArrowRight', shiftKey: true });
    expect(slider().getAttribute('aria-valuenow')).toBe('120');
    fireEvent.keyDown(slider(), { key: 'x' });
    expect(slider().getAttribute('aria-valuenow')).toBe('120');
  });

  it('scrubs by pointer, live while held, dead once released', () => {
    renderExit();
    const pane = surface();
    // jsdom rects are zero; the component falls back to its view width.
    fireEvent.pointerDown(pane, { clientX: 340 });
    const midMonth = Number(slider().getAttribute('aria-valuenow'));
    expect(midMonth).toBeGreaterThan(55);
    expect(midMonth).toBeLessThan(65);
    fireEvent.pointerMove(pane, { clientX: 68 });
    const earlyMonth = Number(slider().getAttribute('aria-valuenow'));
    expect(earlyMonth).toBeGreaterThanOrEqual(1);
    expect(earlyMonth).toBeLessThan(20);
    fireEvent.pointerUp(pane);
    fireEvent.pointerMove(pane, { clientX: 600 });
    expect(Number(slider().getAttribute('aria-valuenow'))).toBe(earlyMonth);
    // Pointer leaving also ends the scrub.
    fireEvent.pointerDown(pane, { clientX: 340 });
    fireEvent.pointerLeave(pane);
    fireEvent.pointerMove(pane, { clientX: 600 });
    expect(Number(slider().getAttribute('aria-valuenow'))).not.toBe(120);
  });

  it('uses the real rect when the browser reports one, clamping both ends', () => {
    renderExit();
    const pane = surface();
    vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue({
      width: 915,
      left: 100,
      right: 1015,
      top: 0,
      bottom: 200,
      height: 200,
      x: 100,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(pane, { clientX: 50 });
    expect(slider().getAttribute('aria-valuenow')).toBe('1');
    fireEvent.pointerMove(pane, { clientX: 2000 });
    expect(slider().getAttribute('aria-valuenow')).toBe('120');
    fireEvent.pointerUp(pane);
  });

  it('flips the verdict with the hurdle and marks the crossover only when one exists', () => {
    const { container } = renderExit();
    const hurdleKnob = () => screen.getByRole('slider', { name: 'Hurdle' });
    // A hurdle nobody clears: redeploy everywhere, nothing to mark.
    fireEvent.change(hurdleKnob(), { target: { value: '20' } });
    expect(screen.getByText('redeploy').className).toBe('pill pill--flag');
    expect(container.querySelector('.chart__ghost')).toBeNull();
    // A hurdle inside the rising curve: the verdict boundary gets its ghost —
    // the mark that answers "hold at least this long".
    fireEvent.change(hurdleKnob(), { target: { value: '4' } });
    expect(container.querySelector('.chart__ghost')).not.toBeNull();
    expect(screen.getByText('crossover')).toBeDefined();
    expect(screen.getByText(/the hold clears the hurdle from here/)).toBeDefined();
    // At five years the hold clears a 2% hurdle: the pill says hold, and the
    // early selling-cost hole keeps its honest to-hold mark.
    fireEvent.change(hurdleKnob(), { target: { value: '2' } });
    expect(screen.getByText('hold').className).toBe('pill pill--ok');
    expect(container.querySelector('.chart__ghost')).not.toBeNull();
  });

  it('marks a decaying leveraged return with the to-redeploy crossover', () => {
    // Cheap debt under a richer cap rate: the early return is amplified,
    // then decays as equity accretes — the other direction of the boundary.
    renderExit(
      financials({
        debts: [
          {
            lender: 'Cheap Money',
            original_principal: '212000.00',
            annual_rate: '0.03',
            term_months: 360,
            months_elapsed: 24,
          },
        ],
      }),
    );
    fireEvent.change(screen.getByRole('slider', { name: 'Hurdle' }), { target: { value: '12.5' } });
    expect(screen.getByText(/past here redeploy beats holding/)).toBeDefined();
  });

  it('calls an underwater position underwater, with no fake red entry', () => {
    renderExit(
      financials({
        valuation: { value: '100000.00', source: 'owner_estimate', as_of: '2026-08-01' },
        debts: [
          {
            lender: 'Heavy',
            original_principal: '190000.00',
            annual_rate: '0.0625',
            term_months: 360,
            months_elapsed: 6,
          },
        ],
      }),
    );
    expect(screen.getByText('underwater').className).toBe('pill pill--failed');
    expect(screen.getByText('—').className).toBe('stat__value');
  });

  it('says "no return" — and draws no curve — when the flows never turn', () => {
    const { container } = renderExit(
      financials({
        valuation: { value: '50.00', source: 'owner_estimate', as_of: '2026-08-01' },
        noi_12mo: '-1200.00',
      }),
    );
    expect(screen.getByText('no return').className).toBe('pill');
    expect(slider().getAttribute('aria-valuetext')).toMatch(/no return to report$/);
    expect(container.querySelector('.chart__line--projected')).toBeNull();
    expect(container.querySelector('.chart__hurdle')).toBeNull();
  });
});
