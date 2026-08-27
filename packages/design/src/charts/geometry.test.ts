import { describe, expect, it } from 'vitest';
import { hatchTile } from './hatch.js';
import { areaPath, linePath, stepPath } from './path.js';
import { linearScale } from './scale.js';
import { niceTicks } from './ticks.js';

describe('linearScale', () => {
  it('maps the domain onto the range exactly', () => {
    expect(linearScale(0, 10, 0, 100)(5)).toBe(50);
    expect(linearScale(2, 4, 10, 20)(3)).toBe(15);
    expect(linearScale(0, 10, 100, 0)(2.5)).toBe(75);
  });

  it('pins a degenerate domain to the range midpoint', () => {
    const scale = linearScale(5, 5, 0, 10);
    expect(scale(5)).toBe(5);
    expect(scale(-999)).toBe(5);
  });

  it('refuses non-finite bounds in every position, naming the offender', () => {
    expect(() => linearScale(Number.NaN, 1, 0, 1)).toThrow('scale bounds must be finite, got NaN');
    expect(() => linearScale(0, Number.POSITIVE_INFINITY, 0, 1)).toThrow(RangeError);
    expect(() => linearScale(0, 1, Number.NaN, 1)).toThrow(RangeError);
    expect(() => linearScale(0, 1, 0, Number.NEGATIVE_INFINITY)).toThrow(RangeError);
  });
});

describe('niceTicks', () => {
  it('produces round steps of 1, 2, and 5 across magnitudes', () => {
    expect(niceTicks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(niceTicks(0, 1, 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
    expect(niceTicks(0, 4.5, 5)).toEqual([0, 1, 2, 3, 4]);
    expect(niceTicks(0, 100, 3)).toEqual([0, 50, 100]);
    expect(niceTicks(0, 7, 5)).toEqual([0, 2, 4, 6]);
    expect(niceTicks(0, 0.9, 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8]);
    expect(niceTicks(0, 45, 8)).toEqual([0, 10, 20, 30, 40]);
    // Two ticks is the legal minimum, and the span pass must NOT round —
    // a rounding span turns 0.25 into 0.2 and invents five fussy ticks.
    expect(niceTicks(0, 10, 2)).toEqual([0, 10]);
    expect(niceTicks(0, 0.25, 4)).toEqual([0, 0.2]);
  });

  it('spans negative domains and floats without drift', () => {
    expect(niceTicks(-10, 10, 5)).toEqual([-10, -5, 0, 5, 10]);
    // 0.1 accumulation drifts (0.30000000000000004) unless rounded honestly.
    expect(niceTicks(0, 0.5, 6)).toEqual([0, 0.1, 0.2, 0.3, 0.4, 0.5]);
  });

  it('collapses a degenerate domain to its single value', () => {
    expect(niceTicks(7, 7)).toEqual([7]);
  });

  it('refuses disordered, non-finite, or single-tick requests, naming each', () => {
    expect(() => niceTicks(10, 0)).toThrow('tick bounds must be ordered, got 10..0');
    expect(() => niceTicks(Number.NaN, 1)).toThrow('tick bounds must be finite, got NaN..1');
    expect(() => niceTicks(0, Number.POSITIVE_INFINITY)).toThrow(RangeError);
    expect(() => niceTicks(0, 10, 1)).toThrow('at least two ticks are needed, got 1');
  });
});

describe('paths', () => {
  it('draws a polyline and rounds to two decimals', () => {
    expect(linePath([])).toBe('');
    expect(linePath([{ x: 1.239, y: 2 }])).toBe('M1.24 2');
    expect(
      linePath([
        { x: 0, y: 10 },
        { x: 5.5, y: 20.125 },
      ]),
    ).toBe('M0 10 L5.5 20.13');
  });

  it('draws a staircase with horizontal-then-vertical runs', () => {
    expect(
      stepPath([
        { x: 0, y: 10 },
        { x: 5, y: 20 },
        { x: 9, y: 15 },
      ]),
    ).toBe('M0 10 H5 V20 H9 V15');
  });

  it('closes a band between two edges, walking the lower edge backward', () => {
    expect(
      areaPath(
        [
          { x: 0, y: 0 },
          { x: 10, y: 0 },
        ],
        [
          { x: 0, y: 5 },
          { x: 10, y: 5 },
        ],
      ),
    ).toBe('M0 0 L10 0 L10 5 L0 5 Z');
    expect(areaPath([], [{ x: 0, y: 0 }])).toBe('');
    expect(areaPath([{ x: 0, y: 0 }], [])).toBe('');
  });

  it('refuses non-finite coordinates, naming the offender', () => {
    expect(() => linePath([{ x: Number.NaN, y: 0 }])).toThrow(
      'path coordinates must be finite, got NaN',
    );
  });
});

describe('hatchTile', () => {
  it('tiles each kind deterministically', () => {
    expect(hatchTile('diagonal')).toEqual({
      size: 6,
      d: 'M0 6L6 0 M-1.5 1.5L1.5 -1.5 M4.5 7.5L7.5 4.5',
    });
    expect(hatchTile('crosshatch').d).toContain('M0 0L6 6');
    expect(hatchTile('stipple')).toEqual({ size: 6, d: 'M1.5 1.5h0.01 M4.5 4.5h0.01' });
  });
});
