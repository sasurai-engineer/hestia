/**
 * Nice-number axis ticks (Heckbert's algorithm): round steps of 1, 2, or 5
 * times a power of ten, covering the domain from the first nice value at or
 * above the minimum to the last at or below the maximum.
 */

function niceNum(range: number, round: boolean): number {
  const exponent = Math.floor(Math.log10(range));
  const fraction = range / 10 ** exponent;
  let niceFraction: number;
  if (round) {
    if (fraction < 1.5) {
      niceFraction = 1;
    } else if (fraction < 3) {
      niceFraction = 2;
    } else if (fraction < 7) {
      niceFraction = 5;
    } else {
      niceFraction = 10;
    }
  } else if (fraction <= 1) {
    niceFraction = 1;
  } else if (fraction <= 2) {
    niceFraction = 2;
  } else if (fraction <= 5) {
    niceFraction = 5;
  } else {
    niceFraction = 10;
  }
  return niceFraction * 10 ** exponent;
}

/** Ticks covering [min, max]; a collapsed domain yields its single value. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    throw new RangeError(`tick bounds must be finite, got ${min}..${max}`);
  }
  if (max < min) {
    throw new RangeError(`tick bounds must be ordered, got ${min}..${max}`);
  }
  if (count < 2) {
    throw new RangeError(`at least two ticks are needed, got ${count}`);
  }
  if (min === max) {
    return [min];
  }
  const step = niceNum(niceNum(max - min, false) / (count - 1), true);
  const ticks: number[] = [];
  const first = Math.ceil(min / step) * step;
  const last = Math.floor(max / step) * step;
  // Half-step tolerance keeps float drift from dropping the final tick.
  for (let value = first; value <= last + step / 2; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}
