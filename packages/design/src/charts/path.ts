/**
 * SVG path builders over point lists. Coordinates round to two decimals —
 * sub-hundredth pixels are DOM weight, not precision.
 */

export type Point = { x: number; y: number };

function fmt(value: number): string {
  if (!Number.isFinite(value)) {
    throw new RangeError(`path coordinates must be finite, got ${value}`);
  }
  return String(Number(value.toFixed(2)));
}

/** A polyline: M then L per point. Empty input is an empty path. */
export function linePath(points: readonly Point[]): string {
  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${fmt(point.x)} ${fmt(point.y)}`)
    .join(' ');
}

/** A staircase: horizontal then vertical to each next point. */
export function stepPath(points: readonly Point[]): string {
  return points
    .map((point, index) =>
      index === 0 ? `M${fmt(point.x)} ${fmt(point.y)}` : `H${fmt(point.x)} V${fmt(point.y)}`,
    )
    .join(' ');
}

/** A closed band between an upper and a lower edge (both given left→right). */
export function areaPath(upper: readonly Point[], lower: readonly Point[]): string {
  if (upper.length === 0 || lower.length === 0) {
    return '';
  }
  const forward = linePath(upper);
  const backward = [...lower]
    .reverse()
    .map((point) => `L${fmt(point.x)} ${fmt(point.y)}`)
    .join(' ');
  return `${forward} ${backward} Z`;
}
