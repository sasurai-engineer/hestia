/**
 * WCAG 2.1 contrast arithmetic — the livery's accessibility claims are
 * recomputed from these functions on every run, never trusted from the
 * token file's recorded numbers.
 *
 * Tokens are six-digit lowercase hex by law, so that is the only form
 * accepted here: a looser parser would let a malformed token slip past
 * the parity test wearing a plausible color.
 */

const SIX_DIGIT_HEX = /^#[0-9a-f]{6}$/;

/** One sRGB channel, 0–255, linearized per WCAG 2.1 §relative-luminance. */
function linearize(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Relative luminance of a `#rrggbb` color (lowercase, six digits). */
export function relativeLuminance(hex: string): number {
  if (!SIX_DIGIT_HEX.test(hex)) {
    throw new RangeError(`not a six-digit lowercase hex color: ${hex}`);
  }
  const red = linearize(Number.parseInt(hex.slice(1, 3), 16));
  const green = linearize(Number.parseInt(hex.slice(3, 5), 16));
  const blue = linearize(Number.parseInt(hex.slice(5, 7), 16));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** WCAG contrast ratio between two colors, 1–21, order-independent. */
export function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(a);
  const second = relativeLuminance(b);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}
