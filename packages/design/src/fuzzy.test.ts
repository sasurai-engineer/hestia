import { describe, expect, it } from 'vitest';
import { fuzzyMatch } from './fuzzy.js';

describe('fuzzyMatch', () => {
  it('matches subsequences', () => {
    expect(fuzzyMatch('brs', 'burst pipe')).toBe(true);
    expect(fuzzyMatch('rcd', 'record rent')).toBe(true);
  });

  it('is case-insensitive in both directions', () => {
    expect(fuzzyMatch('BRS', 'burst pipe')).toBe(true);
    expect(fuzzyMatch('brs', 'BURST PIPE')).toBe(true);
  });

  it('requires the subsequence order', () => {
    expect(fuzzyMatch('srb', 'burst pipe')).toBe(false);
  });

  it('rejects when a character never appears', () => {
    expect(fuzzyMatch('burstz', 'burst pipe')).toBe(false);
  });

  it('matches everything on the empty query and nothing on an empty candidate', () => {
    expect(fuzzyMatch('', 'anything')).toBe(true);
    expect(fuzzyMatch('a', '')).toBe(false);
  });

  it('consumes each candidate character at most once', () => {
    expect(fuzzyMatch('pp', 'pipe')).toBe(true);
    expect(fuzzyMatch('ppp', 'pipe')).toBe(false);
  });
});
