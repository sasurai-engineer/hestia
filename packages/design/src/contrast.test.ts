import { describe, expect, it } from 'vitest';
import { contrastRatio, relativeLuminance } from './contrast.js';

describe('relativeLuminance', () => {
  it('rates the extremes exactly', () => {
    expect(relativeLuminance('#000000')).toBe(0);
    expect(relativeLuminance('#ffffff')).toBe(1);
  });

  it('carries the WCAG channel weights exactly', () => {
    // A full single channel IS its coefficient — any weight drift shows here.
    expect(relativeLuminance('#ff0000')).toBe(0.2126);
    expect(relativeLuminance('#00ff00')).toBe(0.7152);
    expect(relativeLuminance('#0000ff')).toBe(0.0722);
  });

  it('linearizes both sides of the 0.04045 threshold', () => {
    // 10/255 ≈ 0.0392 takes the low slope; 11/255 ≈ 0.0431 takes the curve.
    expect(relativeLuminance('#0a0a0a')).toBeCloseTo(0.0030352698, 9);
    expect(relativeLuminance('#0b0b0b')).toBeCloseTo(0.0033465358, 9);
  });

  it('refuses anything but six-digit lowercase hex', () => {
    // 'x#0a0a0a' polices the ^ anchor: an unanchored pattern would accept it.
    for (const bad of ['#FAF7F2', '#fff', 'faf7f2', '#faf7f21', '#faf7g2', 'x#0a0a0a', '']) {
      expect(() => relativeLuminance(bad)).toThrow(RangeError);
    }
  });

  it('names the offender when it refuses', () => {
    expect(() => relativeLuminance('#fff')).toThrow('not a six-digit lowercase hex color: #fff');
  });
});

describe('contrastRatio', () => {
  it('is 21 for the extremes and 1 for identity', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBe(21);
    expect(contrastRatio('#6b6257', '#6b6257')).toBe(1);
  });

  it('is order-independent and never below 1', () => {
    const forward = contrastRatio('#221e19', '#faf7f2');
    const reverse = contrastRatio('#faf7f2', '#221e19');
    expect(forward).toBe(reverse);
    expect(forward).toBeGreaterThan(1);
  });

  it('reproduces the livery pairs to high precision', () => {
    expect(contrastRatio('#221e19', '#faf7f2')).toBeCloseTo(15.5007409, 6);
    expect(contrastRatio('#8f3a10', '#faf7f2')).toBeCloseTo(7.0671927, 6);
    expect(contrastRatio('#6b6257', '#faf7f2')).toBeCloseTo(5.5988793, 6);
  });
});
