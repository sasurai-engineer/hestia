import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { serverSnapshot, useReducedMotion } from './reduced.js';

type Listener = () => void;

function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<Listener>();
  const state = { matches: initialMatches };
  const queries: string[] = [];
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (media: string) => {
      queries.push(media);
      return {
        get matches() {
          return state.matches;
        },
        media,
        onchange: null,
        // Only a real 'change' subscription counts — a hook listening to the
        // wrong event name must fail these tests, not pass them by accident.
        addEventListener: (event: string, listener: Listener) => {
          if (event === 'change') {
            listeners.add(listener);
          }
        },
        removeEventListener: (event: string, listener: Listener) => {
          if (event === 'change') {
            listeners.delete(listener);
          }
        },
        dispatchEvent: () => false,
      };
    },
  });
  return {
    listeners,
    queries,
    flip(next: boolean) {
      state.matches = next;
      for (const listener of listeners) {
        listener();
      }
    },
  };
}

describe('useReducedMotion', () => {
  it('asks for the reduced-motion query by name and follows changes', () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => useReducedMotion());
    expect(media.queries).toContain('(prefers-reduced-motion: reduce)');
    expect(result.current).toBe(false);

    act(() => media.flip(true));
    expect(result.current).toBe(true);

    act(() => media.flip(false));
    expect(result.current).toBe(false);
  });

  it('unsubscribes on unmount', () => {
    const media = installMatchMedia(true);
    const { result, unmount } = renderHook(() => useReducedMotion());
    expect(result.current).toBe(true);
    expect(media.listeners.size).toBe(1);
    unmount();
    expect(media.listeners.size).toBe(0);
  });

  it('defaults to motion on the server', () => {
    expect(serverSnapshot()).toBe(false);
  });
});
