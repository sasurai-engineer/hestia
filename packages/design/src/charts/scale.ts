/**
 * Chart geometry is engine work: deterministic arithmetic, mutation-tested
 * to the same bar. A scale maps a domain value onto pixel range — nothing
 * more, and never NaN.
 */

export type Scale = (value: number) => number;

/** Linear domain→range map. A degenerate domain pins to the range midpoint. */
export function linearScale(
  domainMin: number,
  domainMax: number,
  rangeMin: number,
  rangeMax: number,
): Scale {
  for (const bound of [domainMin, domainMax, rangeMin, rangeMax]) {
    if (!Number.isFinite(bound)) {
      throw new RangeError(`scale bounds must be finite, got ${bound}`);
    }
  }
  if (domainMin === domainMax) {
    const midpoint = (rangeMin + rangeMax) / 2;
    return () => midpoint;
  }
  const slope = (rangeMax - rangeMin) / (domainMax - domainMin);
  return (value) => rangeMin + (value - domainMin) * slope;
}
