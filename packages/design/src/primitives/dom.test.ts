import { describe, expect, it, vi } from 'vitest';
import { focusIfPresent, syncDialog } from './dom.js';

const fakeDialog = (open: boolean) => ({
  open,
  showModal: vi.fn(),
  close: vi.fn(),
});

describe('syncDialog', () => {
  it('does nothing before the ref mounts', () => {
    expect(() => syncDialog(null, true)).not.toThrow();
    expect(() => syncDialog(null, false)).not.toThrow();
  });

  it('shows a closed dialog asked to open, once', () => {
    const closed = fakeDialog(false);
    syncDialog(closed, true);
    expect(closed.showModal).toHaveBeenCalledTimes(1);
    expect(closed.close).not.toHaveBeenCalled();

    const alreadyOpen = fakeDialog(true);
    syncDialog(alreadyOpen, true);
    expect(alreadyOpen.showModal).not.toHaveBeenCalled();
  });

  it('closes an open dialog asked to close, once', () => {
    const opened = fakeDialog(true);
    syncDialog(opened, false);
    expect(opened.close).toHaveBeenCalledTimes(1);
    expect(opened.showModal).not.toHaveBeenCalled();

    const alreadyClosed = fakeDialog(false);
    syncDialog(alreadyClosed, false);
    expect(alreadyClosed.close).not.toHaveBeenCalled();
  });
});

describe('focusIfPresent', () => {
  it('focuses a mounted node and tolerates an unmounted one', () => {
    const node = { focus: vi.fn() };
    focusIfPresent(node);
    expect(node.focus).toHaveBeenCalledTimes(1);
    expect(() => focusIfPresent(null)).not.toThrow();
  });
});
