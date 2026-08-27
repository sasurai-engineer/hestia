/**
 * Plat hatching: past four series, Hestia does what surveyors do — pattern,
 * not new hues. Each hatch is a tile the caller renders inside an SVG
 * <pattern> stroked in an existing ink.
 */

export type HatchKind = 'diagonal' | 'crosshatch' | 'stipple';

export type HatchTile = { size: number; d: string };

const TILES: Record<HatchKind, HatchTile> = {
  // Corner strokes keep the diagonal continuous across tile seams.
  diagonal: { size: 6, d: 'M0 6L6 0 M-1.5 1.5L1.5 -1.5 M4.5 7.5L7.5 4.5' },
  crosshatch: { size: 6, d: 'M0 6L6 0 M-1.5 1.5L1.5 -1.5 M4.5 7.5L7.5 4.5 M0 0L6 6' },
  // Zero-length strokes with round caps render as dots.
  stipple: { size: 6, d: 'M1.5 1.5h0.01 M4.5 4.5h0.01' },
};

export function hatchTile(kind: HatchKind): HatchTile {
  return TILES[kind];
}
