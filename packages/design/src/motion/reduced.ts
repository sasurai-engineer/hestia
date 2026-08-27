import { useSyncExternalStore } from 'react';

/**
 * The Plat Edition gate. Components that draw once at mount (the trace)
 * ask this before animating; the CSS side is handled by motion.css.
 */

const QUERY = '(prefers-reduced-motion: reduce)';

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(QUERY);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function snapshot(): boolean {
  return window.matchMedia(QUERY).matches;
}

/** Server rendering has no reader preference; motion is the default there. */
export function serverSnapshot(): boolean {
  return false;
}

/** True when the reader has asked for stillness. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}
