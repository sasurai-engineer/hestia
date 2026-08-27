import { describe, expect, it } from 'vitest';
import { contrastRatio } from '../src/contrast.js';
import { contrastPairs, tokenValues } from './contract.js';

/**
 * Every accessibility claim in the token contract is recomputed here — a
 * recorded ratio is a statement of fact, and a fact that is never re-derived
 * is a comment. Floors: 7 = AAA text, 4.5 = AA text, 3 = non-text UI.
 */
describe('the contract’s contrast claims are true', () => {
  it('records at least the committed pair set', () => {
    expect(contrastPairs.length).toBeGreaterThanOrEqual(18);
  });

  for (const { fg, bg, ratio, floor } of contrastPairs) {
    it(`${fg} on ${bg} is ${ratio} (floor ${floor})`, () => {
      const fgHex = tokenValues.get(fg);
      const bgHex = tokenValues.get(bg);
      if (fgHex === undefined || bgHex === undefined) {
        throw new Error(`pair names unknown tokens: ${fg}/${bg}`);
      }
      expect([3, 4.5, 7]).toContain(floor);
      const computed = contrastRatio(fgHex, bgHex);
      expect(Number(computed.toFixed(2))).toBe(ratio);
      expect(computed).toBeGreaterThanOrEqual(floor);
    });
  }
});
