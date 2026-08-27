import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Dialog } from './Dialog.js';
import { Disclosure } from './Disclosure.js';
import { RangeField } from './RangeField.js';

describe('RangeField', () => {
  it('reads out the raw value by default', () => {
    render(
      <RangeField label="Extra principal" value={200} min={0} max={2000} onChange={() => {}} />,
    );
    const slider = screen.getByRole('slider', { name: 'Extra principal' });
    expect(slider.getAttribute('step')).toBe('1');
    expect(slider.getAttribute('aria-valuetext')).toBe('200');
    expect(screen.getByText('200').className).toBe('range-field__readout');
  });

  it('formats the readout and reports numeric changes', () => {
    const onChange = vi.fn();
    render(
      <RangeField
        label="Reserve"
        value={350}
        min={0}
        max={1000}
        step={50}
        onChange={onChange}
        format={(v) => `$${v}/mo`}
      />,
    );
    const slider = screen.getByRole('slider', { name: 'Reserve' });
    expect(slider.getAttribute('aria-valuetext')).toBe('$350/mo');
    fireEvent.change(slider, { target: { value: '400' } });
    expect(onChange).toHaveBeenCalledWith(400);
  });
});

describe('Dialog', () => {
  it('opens and closes with the prop, rendering children only while open', () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <Dialog open={false} onClose={onClose} label="Confirm">
        <p>Are you sure?</p>
      </Dialog>,
    );
    const dialog = screen.getByLabelText('Confirm', { selector: 'dialog' });
    expect(dialog.hasAttribute('open')).toBe(false);
    expect(screen.queryByText('Are you sure?')).toBeNull();

    rerender(
      <Dialog open onClose={onClose} label="Confirm">
        <p>Are you sure?</p>
      </Dialog>,
    );
    expect(dialog.hasAttribute('open')).toBe(true);
    expect(screen.getByText('Are you sure?')).toBeDefined();

    rerender(
      <Dialog open={false} onClose={onClose} label="Confirm">
        <p>Are you sure?</p>
      </Dialog>,
    );
    expect(dialog.hasAttribute('open')).toBe(false);
    // The polyfilled close() dispatches a close event; the component relays it.
    expect(onClose).toHaveBeenCalled();
  });

  it('relays cancel (the escape key) as onClose and merges classes', () => {
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} label="Palette" className="palette">
        <p>content</p>
      </Dialog>,
    );
    const dialog = screen.getByLabelText('Palette', { selector: 'dialog' });
    expect(dialog.className).toBe('dialog palette');
    fireEvent(dialog, new Event('cancel'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Disclosure', () => {
  it('starts closed, opens on click, and closes again', () => {
    const { container } = render(
      <Disclosure summary="Show the working">
        <p>working</p>
      </Disclosure>,
    );
    const summary = screen.getByRole('button', { name: /Show the working/ });
    const panel = container.querySelector('.disclosure__panel');
    const inner = container.querySelector('.disclosure__inner');
    expect(summary.getAttribute('aria-expanded')).toBe('false');
    expect(panel?.className).toBe('disclosure__panel');
    expect(inner?.hasAttribute('inert')).toBe(true);

    fireEvent.click(summary);
    expect(summary.getAttribute('aria-expanded')).toBe('true');
    expect(panel?.className).toBe('disclosure__panel disclosure__panel--open');
    expect(inner?.hasAttribute('inert')).toBe(false);

    fireEvent.click(summary);
    expect(summary.getAttribute('aria-expanded')).toBe('false');
  });

  it('wires the summary to the panel and honors defaultOpen', () => {
    const { container } = render(
      <Disclosure summary="Audit" defaultOpen>
        <p>provenance</p>
      </Disclosure>,
    );
    const summary = screen.getByRole('button', { name: /Audit/ });
    const panel = container.querySelector('.disclosure__panel');
    expect(summary.getAttribute('aria-expanded')).toBe('true');
    expect(summary.getAttribute('aria-controls')).toBe(panel?.id);
  });
});
