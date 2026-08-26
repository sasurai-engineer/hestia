import type { Decimal } from 'decimal.js';
import { RateError } from './errors.js';
import {
  assertDecimalScale,
  assertRepresentable,
  FinancialDecimal,
  parseDecimal,
} from './numeric.js';

/**
 * A dimensionless ratio: an interest rate, a depreciation fraction, a growth
 * assumption, an ownership share.
 *
 * Deliberately *not* Money. A rate has no currency and no minor unit, and the
 * type system refuses to add one to a dollar amount. That mistake is the most
 * common source of silent financial error, so it is made unrepresentable.
 *
 * Every Rate that exists is finite and representable, because the check lives
 * in the single factory rather than in the constructors that happen to call it.
 */
export interface Rate {
  readonly _tag: 'Rate';
  readonly value: Decimal;
}

/**
 * The one funnel every Rate passes through, and therefore the only correct
 * place for the invariant.
 *
 * Putting the check in the public constructors instead left the five
 * arithmetic operators free to mint values the type promised were impossible —
 * `compound(rate('-2'), 0.5)` returned a well-formed Rate holding NaN, which
 * then surfaced as a raw `SyntaxError` from `BigInt()` two modules away, and
 * made `compareRate` return NaN through a `-1 | 0 | 1` signature.
 */
/**
 * Every Rate this module has ever minted.
 *
 * Identity by provenance, not by shape. `Decimal.isDecimal` is a duck-type --
 * decimal.js implements it as `obj instanceof Decimal || obj.toStringTag ===
 * '[object Decimal]'`, and `toStringTag` is a plain own property -- so the
 * object literal `{_tag:'Rate', value:{toStringTag:'[object Decimal]'}}`,
 * reachable from any JSON body, passed a guard whose entire purpose was to
 * reject it. A registry cannot be forged.
 */
const MINTED = new WeakSet<object>();

/**
 * Freeze the wrapper *and* the decimal it holds.
 *
 * `Object.freeze` is shallow, and a decimal.js value keeps its sign, exponent
 * and digit array as ordinary writable properties. ZERO_RATE and ONE_RATE are
 * process-wide singletons handed to every consumer, so one reach-in poisoned
 * every module that imported them -- `ONE_RATE.value.d[0] = 999` made
 * `multiply(money('100.00'), ONE_RATE, …)` return $99,900 for the rest of the
 * process, with no guard tripped.
 */
const make = (value: Decimal, subject = 'rate'): Rate => {
  const checked = assertDecimalScale(
    assertRepresentable(value, RateError, subject),
    RateError,
    subject,
  );
  if (Array.isArray((checked as unknown as { d?: unknown }).d)) {
    Object.freeze((checked as unknown as { d: unknown[] }).d);
  }
  Object.freeze(checked);
  const rate: Rate = Object.freeze({ _tag: 'Rate' as const, value: checked });
  MINTED.add(rate);
  return rate;
};

/** Build a rate from its decimal form: `0.0675` is 6.75%. */
export const rate = (value: string | number): Rate => make(parseDecimal(value, RateError, 'rate'));

/** Build a rate from a percentage: `6.75` is 6.75%. */
export const percent = (value: string | number): Rate =>
  make(parseDecimal(value, RateError, 'percentage').div(100));

/**
 * Build a rate from a fraction — `fraction(1, 27.5)` for the annual share of a
 * residential improvement's basis.
 *
 * The quotient is evaluated at 40 significant digits, so it is exact when the
 * division terminates and correctly rounded when it repeats (1/27.5 does).
 * Either way the residual is around 1e-40, some thirty-eight orders of
 * magnitude below a cent, and Money forces an explicit rounding mode before any
 * of it can reach a ledger.
 *
 * Statutory depreciation should still use the published MACRS tables rather
 * than a raw reciprocal; this helper is for modelling, not for filing.
 */
export const fraction = (numerator: string | number, denominator: string | number): Rate => {
  const den = parseDecimal(denominator, RateError, 'fraction denominator');
  if (den.isZero()) {
    throw new RateError('rate denominator must not be zero');
  }
  return make(parseDecimal(numerator, RateError, 'fraction numerator').div(den));
};

export const ZERO_RATE: Rate = make(new FinancialDecimal(0));
export const ONE_RATE: Rate = make(new FinancialDecimal(1));

/** Reject anything this module did not mint, before its methods are called. */
const use = (r: Rate, role = 'rate'): Rate => {
  if (!isRate(r)) {
    throw new RateError(`${role} must be a Rate built by this package`);
  }
  return r;
};

export const addRate = (a: Rate, b: Rate): Rate =>
  make(use(a, 'left operand').value.plus(use(b, 'right operand').value), 'rate sum');
export const subtractRate = (a: Rate, b: Rate): Rate =>
  make(use(a, 'left operand').value.minus(use(b, 'right operand').value), 'rate difference');
export const multiplyRate = (a: Rate, b: Rate): Rate =>
  make(use(a, 'left operand').value.times(use(b, 'right operand').value), 'rate product');

export const divideRate = (a: Rate, b: Rate): Rate => {
  use(a, 'left operand');
  use(b, 'right operand');
  if (b.value.isZero()) {
    throw new RateError('cannot divide a rate by zero');
  }
  return make(a.value.div(b.value), 'rate quotient');
};

/**
 * The largest number of periods worth compounding.
 *
 * Well past a 30-year monthly schedule (360) or a daily one (10,950), and far
 * short of the point where the result's decimal expansion becomes unrenderable.
 */
const MAX_PERIODS = 1_000_000;

/**
 * Compound growth: `(1 + r)^periods`.
 *
 * Both the input and the result are bounded. `Number.isFinite(periods)` alone
 * admitted 1e15, which produced a Decimal with exponent 2.1e13 — finite by
 * every predicate, and fatal on the first attempt to render it.
 */
export const compound = (r: Rate, periods: number): Rate => {
  use(r);
  if (!Number.isFinite(periods)) {
    throw new RateError(`compounding periods must be finite, received ${periods}`);
  }
  if (Math.abs(periods) > MAX_PERIODS) {
    throw new RateError(`compounding periods must be within ±${MAX_PERIODS}, received ${periods}`);
  }
  const base = new FinancialDecimal(1).plus(r.value);
  // A negative base under a fractional exponent has no real value; decimal.js
  // returns NaN rather than raising, so the case is named here explicitly.
  if (base.isNegative() && !Number.isInteger(periods)) {
    throw new RateError(
      `cannot raise a negative base (1 + ${r.value.toFixed()}) to the fractional ` +
        `power ${periods}; the result is not a real number`,
    );
  }
  if (base.isZero() && periods < 0) {
    throw new RateError('cannot raise zero to a negative power');
  }
  return make(base.pow(periods), 'compounded rate');
};

export const compareRate = (a: Rate, b: Rate): -1 | 0 | 1 =>
  use(a, 'left operand').value.comparedTo(use(b, 'right operand').value) as -1 | 0 | 1;

export const rateEquals = (a: Rate, b: Rate): boolean =>
  use(a, 'left operand').value.equals(use(b, 'right operand').value);
export const lessThanRate = (a: Rate, b: Rate): boolean => compareRate(a, b) < 0;
export const greaterThanRate = (a: Rate, b: Rate): boolean => compareRate(a, b) > 0;
export const minRate = (a: Rate, b: Rate): Rate => (compareRate(a, b) <= 0 ? a : b);
export const maxRate = (a: Rate, b: Rate): Rate => (compareRate(a, b) >= 0 ? a : b);

export const isZeroRate = (r: Rate): boolean => use(r).value.isZero();
export const isNegativeRate = (r: Rate): boolean => use(r).value.isNegative() && !r.value.isZero();
export const isPositiveRate = (r: Rate): boolean => use(r).value.isPositive() && !r.value.isZero();

/**
 * Runtime guard for values arriving from JSON, a database row, or a cast.
 *
 * Answers "did this module make it", which is the only question a boundary can
 * ask that a caller cannot lie about. A rehydrated Rate is correctly false;
 * rebuild it with {@link rateFromJSON}.
 */
export const isRate = (value: unknown): value is Rate =>
  typeof value === 'object' && value !== null && MINTED.has(value);

/** Decimal form, e.g. `"0.0675"`. */
export const rateToString = (r: Rate): string => use(r).value.toFixed();

/** The most decimal places a rendered percentage may carry. */
export const MAX_RENDER_DECIMALS = 40;

/**
 * Percentage form with a fixed number of decimals, e.g. `"6.750%"`.
 *
 * `decimals` is bounded: passed straight through, `toFixed` threw a bare
 * decimal.js `Error` for a negative or fractional value, and killed the
 * process outright at 1e9 -- the one public renderer in this package that was
 * not bounded like every other magnitude.
 */
export const rateToPercentString = (r: Rate, decimals = 3): string => {
  if (!Number.isInteger(decimals) || decimals < 0 || decimals > MAX_RENDER_DECIMALS) {
    throw new RateError(
      `decimals must be an integer in [0, ${MAX_RENDER_DECIMALS}], received ${decimals}`,
    );
  }
  return `${use(r).value.times(100).toFixed(decimals)}%`;
};

// ---------------------------------------------------------------------------
// Serialisation
// ---------------------------------------------------------------------------

export interface RateJson {
  readonly value: string;
}

/**
 * The wire form.
 *
 * Money has had a serialisation pair from the start; Rate had none, so every
 * service computing a cap rate, an LTV or an expense ratio -- the figures
 * {@link ratio} exists to produce -- had to invent its own rehydration, which
 * is the per-service reinvention the pair exists to forbid.
 */
export const rateToJSON = (r: Rate): RateJson => ({ value: use(r).value.toFixed() });

export const rateFromJSON = (value: unknown): Rate => {
  if (typeof value !== 'object' || value === null || !Object.hasOwn(value, 'value')) {
    throw new RateError(`cannot read a rate from ${typeof value}`);
  }
  const candidate = (value as { value: unknown }).value;
  if (typeof candidate !== 'string') {
    throw new RateError(`rate.value must be a decimal string, received ${typeof candidate}`);
  }
  return rate(candidate);
};

/**
 * Round to the scale the `rate_decimal NUMERIC(12,8)` column can hold, so the
 * database is never asked to silently re-round on write.
 */
export const RATE_DB_SCALE = 8;
export const quantizeRate = (r: Rate): Rate =>
  // No subject override: rounding to fewer places cannot increase magnitude,
  // so the representable check here can never actually fail.
  make(use(r).value.toDecimalPlaces(RATE_DB_SCALE));
