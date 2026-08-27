import { describe, expect, it } from 'vitest';
import { cx } from './cx.js';

describe('cx', () => {
  it('joins class parts with single spaces', () => {
    expect(cx('card', 'card--flush')).toBe('card card--flush');
  });

  it('drops false, undefined, and empty strings', () => {
    expect(cx('card', false, undefined, '', 'extra')).toBe('card extra');
  });

  it('returns an empty string when nothing survives', () => {
    expect(cx(false, undefined, '')).toBe('');
  });
});
