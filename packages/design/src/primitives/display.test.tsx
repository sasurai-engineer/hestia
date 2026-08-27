import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button.js';
import { Card } from './Card.js';
import { CitationChip } from './CitationChip.js';
import { EmptyState } from './EmptyState.js';
import { Field } from './Field.js';
import { KeyValue } from './KeyValue.js';
import { LedgerTable } from './LedgerTable.js';
import { LifeBar } from './LifeBar.js';
import { Pill } from './Pill.js';
import { Skeleton } from './Skeleton.js';
import { Stat } from './Stat.js';
import { Toast } from './Toast.js';

describe('Button', () => {
  it('renders each variant with its classes', () => {
    const { rerender } = render(<Button>Go</Button>);
    const button = screen.getByRole('button', { name: 'Go' });
    expect(button.className).toBe('button');
    rerender(<Button variant="quiet">Go</Button>);
    expect(button.className).toBe('button button--quiet');
    rerender(<Button variant="danger">Go</Button>);
    expect(button.className).toBe('button button--danger');
  });

  it('defaults to type=button so forms are never submitted by accident', () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole('button').getAttribute('type')).toBe('button');
  });

  it('honors an explicit type and extra classes, and forwards clicks', () => {
    const onClick = vi.fn();
    render(
      <Button type="submit" className="wide" onClick={onClick}>
        Send
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Send' });
    expect(button.getAttribute('type')).toBe('submit');
    expect(button.className).toBe('button wide');
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('Card', () => {
  it('renders resting and flush variants', () => {
    const { container, rerender } = render(<Card>body</Card>);
    const card = container.firstElementChild;
    expect(card?.className).toBe('card');
    rerender(
      <Card flush className="tall">
        body
      </Card>,
    );
    expect(card?.className).toBe('card card--flush tall');
  });
});

describe('Pill', () => {
  it('wears one class per tone', () => {
    const { rerender, container } = render(<Pill>state</Pill>);
    const pill = container.firstElementChild;
    expect(pill?.className).toBe('pill');
    rerender(<Pill tone="ok">state</Pill>);
    expect(pill?.className).toBe('pill pill--ok');
    rerender(<Pill tone="skipped">state</Pill>);
    expect(pill?.className).toBe('pill pill--skipped');
    rerender(<Pill tone="failed">state</Pill>);
    expect(pill?.className).toBe('pill pill--failed');
    rerender(<Pill tone="flag">state</Pill>);
    expect(pill?.className).toBe('pill pill--flag');
  });
});

describe('CitationChip', () => {
  it('shows the cite and reveals the detail on hover', () => {
    render(<CitationChip cite="KRS 383.580" detail="Deposit itemization deadline" />);
    const chip = screen.getByText('KRS 383.580');
    expect(chip.className).toBe('citation-chip');
    expect(chip.getAttribute('title')).toBe('Deposit itemization deadline');
  });

  it('falls back to the cite itself as the title', () => {
    render(<CitationChip cite="26 USC §1031" />);
    expect(screen.getByText('26 USC §1031').getAttribute('title')).toBe('26 USC §1031');
  });
});

describe('Stat', () => {
  it('renders label and figure without a delta', () => {
    const { container } = render(<Stat label="Exit IRR" value="11.2%" />);
    expect(screen.getByText('Exit IRR').className).toBe('stat__label');
    expect(screen.getByText('11.2%').className).toBe('stat__value');
    expect(container.querySelector('.stat__delta')).toBeNull();
  });

  it('tones the delta: out by default, in when money arrives', () => {
    const { rerender } = render(<Stat label="Cash" value="$1,200" delta="-$80/mo" />);
    expect(screen.getByText('-$80/mo').className).toBe('stat__delta stat__delta--out');
    rerender(<Stat label="Cash" value="$1,200" delta="+$140/mo" deltaTone="in" />);
    expect(screen.getByText('+$140/mo').className).toBe('stat__delta stat__delta--in');
  });
});

describe('EmptyState', () => {
  it('renders its message', () => {
    render(<EmptyState>No plumber on file.</EmptyState>);
    expect(screen.getByText('No plumber on file.').className).toBe('empty-state');
  });
});

describe('KeyValue', () => {
  it('renders each pair as dt/dd', () => {
    render(
      <KeyValue
        items={[
          { key: 'Basis', value: '$310,000' },
          { key: 'In service', value: '2024-06-01' },
        ]}
      />,
    );
    expect(screen.getByText('Basis').tagName).toBe('DT');
    expect(screen.getByText('$310,000').tagName).toBe('DD');
    expect(screen.getByText('In service').tagName).toBe('DT');
  });
});

describe('LifeBar', () => {
  it('clamps the fraction into 0..1', () => {
    const { container, rerender } = render(<LifeBar fraction={1.4} />);
    const fill = () => container.querySelector<HTMLElement>('.lifebar__fill');
    expect(fill()?.style.width).toBe('100%');
    rerender(<LifeBar fraction={-2} />);
    expect(fill()?.style.width).toBe('0%');
    rerender(<LifeBar fraction={0.62} />);
    expect(fill()?.style.width).toBe('62%');
  });

  it('is decoration without a label and a meter with one', () => {
    const { container, rerender } = render(<LifeBar fraction={0.5} />);
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
    rerender(<LifeBar fraction={0.5} label="Roof remaining life" />);
    const meter = screen.getByRole('meter', { name: 'Roof remaining life' });
    expect(meter.getAttribute('aria-valuenow')).toBe('0.5');
  });

  it('marks a spent component', () => {
    const { container } = render(<LifeBar fraction={0.1} spent />);
    expect(container.querySelector('.lifebar__fill--spent')).not.toBeNull();
  });
});

describe('Skeleton', () => {
  it('renders one line by default and n lines on request', () => {
    const { container, rerender } = render(<Skeleton />);
    expect(container.querySelectorAll('.skeleton')).toHaveLength(1);
    rerender(<Skeleton lines={3} />);
    expect(container.querySelectorAll('.skeleton')).toHaveLength(3);
  });

  it('never renders fewer than one line and truncates fractions', () => {
    const { container, rerender } = render(<Skeleton lines={0} />);
    expect(container.querySelectorAll('.skeleton')).toHaveLength(1);
    rerender(<Skeleton lines={2.9} />);
    expect(container.querySelectorAll('.skeleton')).toHaveLength(2);
  });

  it('hides itself from assistive tech', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
  });
});

describe('Field', () => {
  it('wires the label and shows an error only when there is one', () => {
    const { container, rerender } = render(
      <Field label="Monthly rent" htmlFor="rent">
        <input id="rent" />
      </Field>,
    );
    expect(screen.getByText('Monthly rent').getAttribute('for')).toBe('rent');
    expect(container.querySelector('.error-note')).toBeNull();
    rerender(
      <Field label="Monthly rent" error="Money is entered in dollars and cents.">
        <input />
      </Field>,
    );
    expect(screen.getByText('Money is entered in dollars and cents.').className).toBe('error-note');
  });
});

describe('LedgerTable', () => {
  it('defaults to regular density and accepts compact', () => {
    const { rerender } = render(
      <LedgerTable>
        <tbody>
          <tr>
            <td>$1,200.00</td>
          </tr>
        </tbody>
      </LedgerTable>,
    );
    const table = screen.getByRole('table');
    expect(table.className).toBe('ledger-table');
    expect(table.getAttribute('data-density')).toBe('regular');
    rerender(
      <LedgerTable density="compact" className="register">
        <tbody>
          <tr>
            <td>$1,200.00</td>
          </tr>
        </tbody>
      </LedgerTable>,
    );
    expect(table.getAttribute('data-density')).toBe('compact');
    expect(table.className).toBe('ledger-table register');
  });
});

describe('Toast', () => {
  it('announces politely and tones failure', () => {
    const { rerender } = render(<Toast>Work order logged.</Toast>);
    const toast = screen.getByRole('status');
    expect(toast.className).toBe('toast');
    rerender(<Toast tone="failed">The ledger refused the entry.</Toast>);
    expect(toast.className).toBe('toast toast--failed');
  });

  it('offers dismissal only when a handler exists', () => {
    const onDismiss = vi.fn();
    const { rerender } = render(<Toast>Saved.</Toast>);
    expect(screen.queryByRole('button')).toBeNull();
    rerender(<Toast onDismiss={onDismiss}>Saved.</Toast>);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
