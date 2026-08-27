import { fireEvent, render, renderHook, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { type Command, CommandPalette, useCommandK } from './CommandPalette.js';

type Runs = { burst?: () => void; rent?: () => void; dossier?: () => void };

const commands = (runs: Runs = {}): readonly Command[] => [
  { id: 'burst', label: 'Emergency: burst pipe', hint: '⌘K burst', run: runs.burst ?? vi.fn() },
  { id: 'rent', label: 'Record rent', run: runs.rent ?? vi.fn() },
  { id: 'dossier', label: 'Assemble dossier', run: runs.dossier ?? vi.fn() },
];

const openPalette = (list: readonly Command[], onClose = vi.fn()) => {
  const view = render(<CommandPalette open onClose={onClose} commands={list} />);
  return { ...view, onClose, input: screen.getByRole('combobox') };
};

describe('CommandPalette', () => {
  it('opens focused and lists every command', () => {
    const { input } = openPalette(commands());
    expect(document.activeElement).toBe(input);
    expect(screen.getAllByRole('option')).toHaveLength(3);
    expect(screen.getByText('⌘K burst').className).toBe('palette__hint');
  });

  it('filters by fuzzy match and resets the active row on typing', () => {
    const { input } = openPalette(commands());
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.change(input, { target: { value: 'brs' } });
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]?.getAttribute('aria-selected')).toBe('true');
    expect(input.getAttribute('aria-activedescendant')).toBe(options[0]?.id);
  });

  it('says so when nothing answers, and Enter does nothing there', () => {
    const onClose = vi.fn();
    const { input } = openPalette(commands(), onClose);
    fireEvent.change(input, { target: { value: 'zzz' } });
    expect(screen.getByText('Nothing answers to that.')).toBeDefined();
    expect(input.getAttribute('aria-expanded')).toBe('false');
    expect(input.getAttribute('aria-activedescendant')).toBeNull();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('walks the list with arrows, clamped at both ends', () => {
    const { input } = openPalette(commands());
    const selected = () =>
      screen.getAllByRole('option').findIndex((o) => o.getAttribute('aria-selected') === 'true');
    expect(selected()).toBe(0);
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(selected()).toBe(0);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(selected()).toBe(2);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(selected()).toBe(2);
    fireEvent.keyDown(input, { key: 'x' });
    expect(selected()).toBe(2);
  });

  it('runs the active command on Enter and closes first', () => {
    const order: string[] = [];
    const runs = { rent: () => order.push('run') };
    const onClose = vi.fn(() => order.push('close'));
    const { input } = openPalette(commands(runs), onClose);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(order).toEqual(['close', 'run']);
  });

  it('runs a clicked command and keeps focus off the option beforehand', () => {
    const run = vi.fn();
    const { onClose } = openPalette(commands({ dossier: run }));
    const option = screen.getByText('Assemble dossier');
    const mouseDown = fireEvent.mouseDown(option);
    expect(mouseDown).toBe(false);
    fireEvent.click(option);
    expect(run).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('stays closed and empty-handed until opened', () => {
    render(<CommandPalette open={false} onClose={vi.fn()} commands={commands()} />);
    const dialog = screen.getByLabelText('Command palette', { selector: 'dialog' });
    expect(dialog.hasAttribute('open')).toBe(false);
  });

  it('relays the dialog closing', () => {
    const onClose = vi.fn();
    openPalette(commands(), onClose);
    fireEvent(screen.getByLabelText('Command palette', { selector: 'dialog' }), new Event('close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('useCommandK', () => {
  it('fires on meta+k and ctrl+k, never on bare k or other chords', () => {
    const onOpen = vi.fn();
    renderHook(() => useCommandK(onOpen));
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(onOpen).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(onOpen).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(window, { key: 'k' });
    fireEvent.keyDown(window, { key: 'j', metaKey: true });
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it('stops listening after unmount', () => {
    const onOpen = vi.fn();
    const { unmount } = renderHook(() => useCommandK(onOpen));
    unmount();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(onOpen).not.toHaveBeenCalled();
  });
});
