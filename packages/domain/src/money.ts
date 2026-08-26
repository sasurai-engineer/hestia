import { MoneyError } from './errors.js';
import {
  assertDecimalScale,
  assertRepresentable,
  FinancialDecimal,
  MAX_EXPONENT,
  parseDecimal,
} from './numeric.js';
import { isRate, rate as makeRate, type Rate } from './rate.js';

/**
 * Currencies and the number of decimal places in their minor unit.
 * USD has two: the minor unit is the cent.
 *
 * CAD is here because a guard that cannot be exercised is not a guard. With a
 * single currency in the table, no two values this module minted could ever
 * disagree, so `assertSameCurrency` was unreachable and the tests that claimed
 * to prove it were forging plain objects instead -- which the mint registry now
 * correctly refuses. A second real currency makes the check provable, and the
 * northern border is not a hypothetical for a Great Lakes or Pacific Northwest
 * portfolio.
 */
export const CURRENCY_EXPONENT = Object.freeze({ USD: 2, CAD: 2 } as const);
export type CurrencyCode = keyof typeof CURRENCY_EXPONENT;
export const DEFAULT_CURRENCY: CurrencyCode = 'USD';

const CURRENCY_CODES = Object.keys(CURRENCY_EXPONENT) as readonly CurrencyCode[];

/**
 * Validate a currency at runtime.
 *
 * `CurrencyCode` is a literal union, so the compiler never forces this check —
 * but every value crossing a JSON body or a database row is just a string. An
 * unmapped code made `exponent` undefined, which silently defeated the
 * precision guard (`scale > undefined` is always false) and rendered 123 minor
 * units as `".123"`, formatted as `$0.12`: a hundredfold understatement with no
 * error anywhere.
 */
export const assertCurrency = (value: unknown): CurrencyCode => {
  if (typeof value !== 'string' || !Object.hasOwn(CURRENCY_EXPONENT, value)) {
    throw new MoneyError(
      `unsupported currency ${JSON.stringify(value)}; supported: ${CURRENCY_CODES.join(', ')}`,
    );
  }
  return value as CurrencyCode;
};

/**
 * How to resolve a value that falls between two minor units.
 *
 * There is no default at the call site on purpose. Every operation that can
 * produce a fraction of a cent must say what it does with it, because the
 * answer differs by context: lenders amortise half-up, the IRS and GAAP
 * assume half-even, and a fee schedule may round in the payer's favour.
 *
 * For a computation whose every step must agree — an amortisation schedule, a
 * depreciation book — use {@link withRounding} once rather than repeating the
 * mode at each of a thousand call sites.
 */
export const Rounding = Object.freeze({
  /** Banker's rounding — ties to the nearest even unit. The financial default. */
  HalfEven: 'HALF_EVEN',
  /** Ties away from zero. What most lenders use on payment schedules. */
  HalfUp: 'HALF_UP',
  /** Ties toward zero. */
  HalfDown: 'HALF_DOWN',
  /** Always away from zero. */
  Up: 'UP',
  /** Always toward zero (truncate). */
  Down: 'DOWN',
  /** Toward positive infinity. */
  Ceiling: 'CEILING',
  /** Toward negative infinity. */
  Floor: 'FLOOR',
  // Frozen: `as const` is compile-time only, and reassigning a member here
  // reinterprets every Money in the process. Setting CURRENCY_EXPONENT.USD = 0
  // turned $123.45 into $12,345.00 for every existing holder.
} as const);
export type Rounding = (typeof Rounding)[keyof typeof Rounding];

/**
 * An exact monetary amount, held as an integer count of minor units.
 *
 * Money is a bigint and never a float. A fraction of a cent is not
 * representable, so it cannot silently accumulate: every rounding decision is
 * forced to the surface as an explicit argument. `Money` is also structurally
 * distinct from {@link Rate}, so the compiler rejects adding a percentage to a
 * dollar amount.
 *
 * Instances are frozen. `readonly` is erased at compile time and does not stop
 * a JavaScript consumer reassigning a field on a value someone else still
 * holds.
 */
export interface Money {
  readonly _tag: 'Money';
  readonly minor: bigint;
  readonly currency: CurrencyCode;
  readonly toJSON: () => MoneyJson;
}

export interface MoneyJson {
  readonly minor: string;
  readonly currency: string;
}

/**
 * Every Money this module has minted. Identity by provenance, not by shape:
 * `{_tag:'Money', minor:'100', currency:'USD'}` -- what node-postgres yields
 * for a NUMERIC column, a string rather than a bigint -- satisfied every
 * structural check, and `add` then concatenated it, turning $100 + $1 into
 * $1,001.00 with no error anywhere.
 */
const MINTED = new WeakSet<object>();

/**
 * The largest number of digits a minor-unit count may carry.
 *
 * Matches {@link MAX_EXPONENT} on the decimal side. Without it every Decimal
 * path was bounded and the bigint path was not, so `multiply` by a large rate
 * twice produced a Money that `format` rendered as `$∞` -- the exact failure
 * the decimal bound exists to prevent, reached through the public API alone.
 */
export const MAX_MINOR_DIGITS = MAX_EXPONENT;

const make = (minor: bigint, currency: CurrencyCode): Money => {
  if ((minor < 0n ? -minor : minor).toString().length > MAX_MINOR_DIGITS) {
    throw new MoneyError(
      `amount exceeds ${MAX_MINOR_DIGITS} digits and could not be rendered exactly`,
    );
  }
  const value: Money = Object.freeze({
    _tag: 'Money' as const,
    minor,
    currency,
    // A method, so `JSON.stringify` finds it. As a free function alone it did
    // not, and stringifying any object graph containing a Money threw a raw
    // TypeError naming neither the field nor the type.
    toJSON(): MoneyJson {
      return { minor: minor.toString(), currency };
    },
  });
  MINTED.add(value);
  return value;
};

/** Reject anything this module did not mint, before it reaches arithmetic. */
const assertMoney = (value: Money, role = 'amount'): Money => {
  if (typeof value !== 'object' || value === null || !MINTED.has(value)) {
    throw new MoneyError(`${role} must be a Money built by this package`);
  }
  return value;
};

/**
 * Powers of ten, memoised only over the range actually used repeatedly.
 *
 * The cache is bounded on purpose: an unbounded table retains every
 * intermediate power for the process lifetime, and because each entry is
 * itself O(n) digits the retention grows as n squared. A single call with a
 * large scale would leak hundreds of megabytes on success, which is worse than
 * failing. Beyond the cache the value is computed and discarded.
 */
// Deliberately below MAX_SCALE. The cache exists for the hot path — USD's two
// decimals plus the small scales real rates carry — and a limit that merely
// equalled the scale bound would make the uncached branch unreachable, which
// is how a fallback rots without anyone noticing.
const POW10_CACHE_LIMIT = 32;
const POW10: bigint[] = [1n];
const pow10 = (n: number): bigint => {
  if (n > POW10_CACHE_LIMIT) {
    return 10n ** BigInt(n);
  }
  for (let i = POW10.length; i <= n; i += 1) {
    POW10.push((POW10[i - 1] as bigint) * 10n);
  }
  return POW10[n] as bigint;
};

const assertSameCurrency = (a: Money, b: Money): void => {
  assertMoney(a, 'left operand');
  assertMoney(b, 'right operand');
  if (a.currency !== b.currency) {
    throw new MoneyError(
      `currency mismatch: ${a.currency} and ${b.currency} are not commensurable`,
    );
  }
};

/**
 * A Rate arriving from outside this module is re-checked before it can reach
 * `BigInt()`. The Rate module guarantees finiteness at construction, but a
 * forged or rehydrated object bypasses that, and the failure mode is a raw
 * `SyntaxError` rather than a domain error.
 */
const assertUsableRate = (r: Rate, role: string): Rate => {
  // isRate, not a _tag check: a Rate that came back through JSON keeps its tag
  // but loses its prototype, so `.value.isFinite` is undefined and the guard
  // that exists to produce a domain error threw a TypeError instead.
  if (!isRate(r)) {
    throw new MoneyError(`${role} must be a Rate`);
  }
  assertRepresentable(r.value, MoneyError, role);
  return r;
};

// --------------------------------------------------------------------------
// Exact integer rounding
// --------------------------------------------------------------------------

/**
 * Whether a non-zero remainder should push the quotient away from zero.
 *
 * One predicate per mode rather than a switch, so each rule reads on a single
 * line. `twice` is twice the magnitude of the remainder, compared against the
 * denominator so that "exactly half" is an integer equality rather than a
 * division.
 */
interface RoundingContext {
  readonly twice: bigint;
  readonly den: bigint;
  readonly quotient: bigint;
  readonly negative: boolean;
}

const ROUNDS_AWAY: Record<Rounding, (c: RoundingContext) => boolean> = {
  [Rounding.Down]: () => false,
  [Rounding.Up]: () => true,
  [Rounding.Floor]: ({ negative }) => negative,
  [Rounding.Ceiling]: ({ negative }) => !negative,
  [Rounding.HalfUp]: ({ twice, den }) => twice >= den,
  [Rounding.HalfDown]: ({ twice, den }) => twice > den,
  [Rounding.HalfEven]: ({ twice, den, quotient }) =>
    twice > den || (twice === den && quotient % 2n !== 0n),
};

/**
 * Validate a rounding mode at runtime.
 *
 * The mode is designed to travel from configuration and policy tables, so it
 * reaches this module as an unchecked string more often than as a literal. An
 * unrecognised one produced `TypeError: ROUNDS_AWAY[mode] is not a function`.
 */
export const assertRounding = (value: unknown): Rounding => {
  if (typeof value !== 'string' || !Object.hasOwn(ROUNDS_AWAY, value)) {
    throw new MoneyError(
      `unknown rounding mode ${JSON.stringify(value)}; expected one of ` +
        Object.values(Rounding).join(', '),
    );
  }
  return value as Rounding;
};

/**
 * Divide two bigints and round the quotient to an integer under `mode`.
 * Exact throughout: no float ever participates.
 */
export const divideRound = (numerator: bigint, denominator: bigint, mode: Rounding): bigint => {
  const rounding = assertRounding(mode);
  if (denominator === 0n) {
    throw new MoneyError('division by zero');
  }
  // Normalise so the denominator is positive; the sign rides on the numerator.
  const num = denominator < 0n ? -numerator : numerator;
  const den = denominator < 0n ? -denominator : denominator;

  const quotient = num / den; // bigint division truncates toward zero
  const remainder = num - quotient * den;
  if (remainder === 0n) {
    return quotient;
  }

  const negative = num < 0n;
  // The remainder always carries the numerator's sign here: the zero case
  // returned above, and the denominator was normalised positive.
  const twice = (negative ? -remainder : remainder) * 2n;

  return ROUNDS_AWAY[rounding]({ twice, den, quotient, negative })
    ? negative
      ? quotient - 1n
      : quotient + 1n
    : quotient;
};

/**
 * Decompose an exact decimal into `value = numerator / 10 ** scale`, so that
 * subsequent arithmetic can stay in bigint.
 */
const toExactFraction = (text: string): { numerator: bigint; scale: number } => {
  // No sign handling: BigInt('-1234' + '56') already yields -123456n, because
  // the leading minus survives concatenation of the whole and fractional parts.
  const separator = text.indexOf('.');
  const whole = separator === -1 ? text : text.slice(0, separator);
  const frac = separator === -1 ? '' : text.slice(separator + 1);
  return { numerator: BigInt(`${whole}${frac}`), scale: frac.length };
};

// --------------------------------------------------------------------------
// Construction
// --------------------------------------------------------------------------

/**
 * The one parse. `money` is this with a strict mode; `roundToMoney` is this
 * with a rounding mode. Keeping them as one function keeps them from drifting
 * on what counts as a valid amount.
 */
const parseToMinor = (
  amount: string | number,
  currency: CurrencyCode,
  mode: Rounding | 'strict',
): bigint => {
  const decimal = assertDecimalScale(
    parseDecimal(amount, MoneyError, 'amount'),
    MoneyError,
    'amount',
  );
  const exponent = CURRENCY_EXPONENT[currency];
  const { numerator, scale } = toExactFraction(decimal.toFixed());
  if (scale <= exponent) {
    return numerator * pow10(exponent - scale);
  }
  if (mode === 'strict') {
    throw new MoneyError(
      `${decimal.toFixed()} carries more precision than ${currency} can hold; ` +
        'round it explicitly with roundToMoney',
    );
  }
  return divideRound(numerator, pow10(scale - exponent), mode);
};

/** Build money directly from a count of minor units (cents for USD). */
export const fromMinor = (minor: bigint, currency: CurrencyCode = DEFAULT_CURRENCY): Money => {
  if (typeof minor !== 'bigint') {
    throw new MoneyError(`minor units must be a bigint, received ${typeof minor}`);
  }
  return make(minor, assertCurrency(currency));
};

export const zero = (currency: CurrencyCode = DEFAULT_CURRENCY): Money =>
  make(0n, assertCurrency(currency));

/**
 * Parse an exact decimal amount: `money('1234.56')` is $1,234.56.
 *
 * Rejects any value carrying more precision than the currency's minor unit.
 * `money('1.005')` is a bug — the caller has a fraction of a cent and has not
 * said how to resolve it — so it throws rather than guessing. Use
 * {@link roundToMoney} to round deliberately.
 */
export const money = (
  amount: string | number,
  currency: CurrencyCode = DEFAULT_CURRENCY,
): Money => {
  const code = assertCurrency(currency);
  return make(parseToMinor(amount, code, 'strict'), code);
};

/** Round an arbitrary-precision decimal down to an exact monetary amount. */
export const roundToMoney = (
  amount: string | number,
  mode: Rounding,
  currency: CurrencyCode = DEFAULT_CURRENCY,
): Money => {
  const code = assertCurrency(currency);
  return make(parseToMinor(amount, code, assertRounding(mode)), code);
};

// --------------------------------------------------------------------------
// Arithmetic
// --------------------------------------------------------------------------

export const add = (a: Money, b: Money): Money => {
  assertSameCurrency(a, b);
  return make(a.minor + b.minor, a.currency);
};

export const subtract = (a: Money, b: Money): Money => {
  assertSameCurrency(a, b);
  return make(a.minor - b.minor, a.currency);
};

export const negate = (a: Money): Money => make(-assertMoney(a).minor, a.currency);
export const abs = (a: Money): Money =>
  make(assertMoney(a).minor < 0n ? -a.minor : a.minor, a.currency);

/**
 * Sum a list.
 *
 * `currency` is not merely the empty-list fallback: it is asserted against
 * every element, so passing it is a genuine check rather than documentation.
 * Previously it was silently ignored for a non-empty list, and a caller who
 * supplied it precisely to be explicit received a mislabelled total.
 */
export const sum = (
  amounts: readonly Money[],
  currency: CurrencyCode = DEFAULT_CURRENCY,
): Money => {
  const code = assertCurrency(currency);
  return amounts.reduce((acc, next) => add(acc, next), zero(code));
};

/** Multiply by a rate, resolving the fractional cent under `mode`. */
export const multiply = (amount: Money, factor: Rate, mode: Rounding): Money => {
  assertMoney(amount);
  assertUsableRate(factor, 'multiplication factor');
  const { numerator, scale } = toExactFraction(factor.value.toFixed());
  return make(divideRound(amount.minor * numerator, pow10(scale), mode), amount.currency);
};

/** Divide by a rate, resolving the fractional cent under `mode`. */
export const divide = (amount: Money, divisor: Rate, mode: Rounding): Money => {
  assertMoney(amount);
  assertUsableRate(divisor, 'divisor');
  if (divisor.value.isZero()) {
    throw new MoneyError('division by a zero rate');
  }
  const { numerator, scale } = toExactFraction(divisor.value.toFixed());
  return make(divideRound(amount.minor * pow10(scale), numerator, mode), amount.currency);
};

/**
 * The ratio of two amounts, as a Rate.
 *
 * The way out of Money and back into Rate, and the shape of nearly every
 * headline figure in this domain: a cap rate is NOI over price, an LTV is loan
 * over value, an expense ratio is opex over EGI.
 */
export const ratio = (numerator: Money, denominator: Money): Rate => {
  assertSameCurrency(numerator, denominator);
  if (denominator.minor === 0n) {
    throw new MoneyError('cannot take a ratio with a zero denominator');
  }
  return makeRate(
    new FinancialDecimal(numerator.minor.toString()).div(denominator.minor.toString()).toFixed(),
  );
};

/**
 * Bind a rounding mode once, for a computation whose every step must agree.
 *
 * An amortisation schedule is a thousand operations that must share one
 * convention; repeating the literal at each call site makes a stray mode
 * invisible in review and the schedule wrong by a cent.
 */
export const withRounding = (mode: Rounding) => {
  const rounding = assertRounding(mode);
  // Frozen, like every other value here. Left writable, `.mode` could be
  // reassigned to read HALF_UP on a book still computing HALF_EVEN -- exactly
  // the drift between stated and actual convention this helper exists to stop.
  return Object.freeze({
    mode: rounding,
    multiply: (amount: Money, factor: Rate): Money => multiply(amount, factor, rounding),
    divide: (amount: Money, divisor: Rate): Money => divide(amount, divisor, rounding),
    round: (amount: string | number, currency: CurrencyCode = DEFAULT_CURRENCY): Money =>
      roundToMoney(amount, rounding, currency),
  });
};

// --------------------------------------------------------------------------
// Allocation
// --------------------------------------------------------------------------

/**
 * The largest number of shares an allocation may produce. Generous against any
 * real rent roll or payment schedule, and short of the point where a value
 * arriving from a request body can exhaust memory.
 */
export const MAX_ALLOCATION_PARTS = 100_000;

const weightsToIntegers = (weights: readonly (string | number)[]): bigint[] => {
  const decimals = weights.map((w) => {
    const d = assertDecimalScale(
      parseDecimal(w, MoneyError, 'allocation weight'),
      MoneyError,
      'allocation weight',
    );
    // `isNegative()` is sign-bit based and true for -0, which is not negative
    // and arises routinely from `x * 0` or `Math.round(-0.4)`. Rejecting it
    // produced "must be non-negative, received 0", sending the reader to look
    // for a negative weight that does not exist.
    if (d.isNegative() && !d.isZero()) {
      throw new MoneyError(`allocation weights must be non-negative, received ${String(w)}`);
    }
    return d;
  });
  const scale = decimals.reduce((max, d) => Math.max(max, d.decimalPlaces()), 0);
  // Exact digit surgery, not `d.times(shift)`: decimal.js rounds the result of
  // an operation to the clone's 40 significant digits, so two weights differing
  // only past digit 40 collapsed to the same integer and allocate distributed
  // them as equal.
  return decimals.map((d) => {
    const { numerator, scale: own } = toExactFraction(d.toFixed());
    return numerator * pow10(scale - own);
  });
};

/**
 * Split an amount across weights so that the parts sum **exactly** back to the
 * original — no cent invented, none lost.
 *
 * Uses the largest-remainder method: every share takes its floor, then the
 * leftover minor units go one at a time to the shares with the largest
 * fractional part, ties broken by position. This is the allocation rule that
 * keeps a rent split, a CAM reconciliation, or a purchase price allocation
 * across land and improvements from drifting by a cent per period.
 */
export const allocate = (amount: Money, weights: readonly (string | number)[]): Money[] => {
  assertMoney(amount);
  if (weights.length === 0) {
    throw new MoneyError('allocation requires at least one weight');
  }
  if (weights.length > MAX_ALLOCATION_PARTS) {
    throw new MoneyError(
      `allocation is limited to ${MAX_ALLOCATION_PARTS} parts, received ${weights.length}`,
    );
  }
  const integerWeights = weightsToIntegers(weights);
  const total = integerWeights.reduce((acc, w) => acc + w, 0n);
  if (total === 0n) {
    throw new MoneyError('allocation weights must not sum to zero');
  }

  // Work on the magnitude so floor division behaves identically either side of
  // zero, then restore the sign at the end.
  const negative = amount.minor < 0n;
  const magnitude = negative ? -amount.minor : amount.minor;

  // One pass: each weight's share and remainder come from a single division.
  const shares: bigint[] = new Array<bigint>(integerWeights.length);
  const remainders: bigint[] = new Array<bigint>(integerWeights.length);
  let distributed = 0n;
  for (let i = 0; i < integerWeights.length; i += 1) {
    const scaled = magnitude * (integerWeights[i] as bigint);
    const share = scaled / total;
    shares[i] = share;
    remainders[i] = scaled - share * total;
    distributed += share;
  }
  let leftover = magnitude - distributed;

  // Exact division is the common case — an even split of an even amount — and
  // there is nothing to order when no unit is left to hand out.
  if (leftover > 0n) {
    // Sort by remainder, largest first. Ties keep their original position
    // because the array is built in index order and Array.prototype.sort has
    // been guaranteed stable since ES2019.
    const order = remainders
      .map((remainder, index) => ({ remainder, index }))
      .sort((a, b) => {
        if (a.remainder === b.remainder) return 0;
        return b.remainder > a.remainder ? 1 : -1;
      });
    for (const { index } of order) {
      if (leftover <= 0n) break;
      shares[index] = (shares[index] as bigint) + 1n;
      leftover -= 1n;
    }
  }

  return shares.map((s) => make(negative ? -s : s, amount.currency));
};

/** Split into `parts` equal shares, distributing any remainder deterministically. */
export const split = (amount: Money, parts: number): Money[] => {
  assertMoney(amount);
  if (!Number.isInteger(parts) || parts < 1) {
    throw new MoneyError(`split requires a positive integer number of parts, received ${parts}`);
  }
  if (parts > MAX_ALLOCATION_PARTS) {
    throw new MoneyError(`split is limited to ${MAX_ALLOCATION_PARTS} parts, received ${parts}`);
  }
  // Uniform shares need no decimal pipeline: one divmod answers it.
  const negative = amount.minor < 0n;
  const magnitude = negative ? -amount.minor : amount.minor;
  const divisor = BigInt(parts);
  const base = magnitude / divisor;
  const remainder = magnitude - base * divisor;
  return Array.from({ length: parts }, (_unused, index) => {
    const share = index < remainder ? base + 1n : base;
    return make(negative ? -share : share, amount.currency);
  });
};

// --------------------------------------------------------------------------
// Comparison
// --------------------------------------------------------------------------

/** Whether two amounts can be ordered at all — that is, share a currency. */
export const isComparable = (a: Money, b: Money): boolean =>
  assertMoney(a, 'left operand').currency === assertMoney(b, 'right operand').currency;

/**
 * Order two amounts. Throws when they are not commensurable.
 *
 * {@link equals} is total and answers `false` for a currency mismatch, where
 * this is partial and raises. Ask {@link isComparable} first when the operands
 * may differ.
 */
export const compare = (a: Money, b: Money): -1 | 0 | 1 => {
  assertSameCurrency(a, b);
  if (a.minor < b.minor) return -1;
  if (a.minor > b.minor) return 1;
  return 0;
};

export const equals = (a: Money, b: Money): boolean =>
  assertMoney(a, 'left operand').currency === assertMoney(b, 'right operand').currency &&
  a.minor === b.minor;

export const lessThan = (a: Money, b: Money): boolean => compare(a, b) < 0;
export const greaterThan = (a: Money, b: Money): boolean => compare(a, b) > 0;
export const min = (a: Money, b: Money): Money => (compare(a, b) <= 0 ? a : b);
export const max = (a: Money, b: Money): Money => (compare(a, b) >= 0 ? a : b);

export const isZero = (a: Money): boolean => assertMoney(a).minor === 0n;
export const isNegative = (a: Money): boolean => assertMoney(a).minor < 0n;
export const isPositive = (a: Money): boolean => assertMoney(a).minor > 0n;

/** Runtime guard for values arriving from JSON, a database row, or a cast. */
export const isMoney = (value: unknown): value is Money =>
  typeof value === 'object' && value !== null && MINTED.has(value);

// --------------------------------------------------------------------------
// Serialisation
// --------------------------------------------------------------------------

/**
 * The wire form.
 *
 * `JSON.stringify` throws outright on a bigint, so without an explicit pair
 * every service crossing an HTTP boundary would invent its own conversion —
 * and the obvious one, `Number(row.rent) * 100`, is precisely the float this
 * module exists to forbid.
 */
export const toJSON = (amount: Money): MoneyJson => ({
  minor: amount.minor.toString(),
  currency: amount.currency,
});

export const fromJSON = (value: unknown): Money => {
  if (typeof value !== 'object' || value === null) {
    throw new MoneyError(`cannot read money from ${typeof value}`);
  }
  // Own properties only. Plain access reads through the prototype chain, so
  // with Object.prototype polluted -- the downstream effect of any merge or
  // query-string gadget -- `fromJSON({})` returned an attacker-chosen amount.
  if (!Object.hasOwn(value, 'minor') || !Object.hasOwn(value, 'currency')) {
    throw new MoneyError('money must carry its own minor and currency fields');
  }
  const candidate = value as { minor?: unknown; currency?: unknown };
  if (typeof candidate.minor !== 'string' || !/^[+-]?\d+$/.test(candidate.minor)) {
    throw new MoneyError(
      `money.minor must be an integer string, received ${JSON.stringify(candidate.minor)}`,
    );
  }
  return make(BigInt(candidate.minor), assertCurrency(candidate.currency));
};

// --------------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------------

/**
 * Exact decimal form without grouping or symbol, e.g. `"-1234.56"`.
 *
 * This is also the wire form for a `NUMERIC` column: PostgreSQL accepts it
 * verbatim, with no float in the path.
 */
export const formatMinorUnits = (minor: bigint, exponent: number): string => {
  if (typeof minor !== 'bigint') {
    throw new MoneyError(`minor units must be a bigint, received ${typeof minor}`);
  }
  if (!Number.isInteger(exponent) || exponent < 0 || exponent > 6) {
    throw new MoneyError(
      `minor-unit exponent must be an integer in [0, 6], received ${String(exponent)}`,
    );
  }
  const negative = minor < 0n;
  const digits = (negative ? -minor : minor).toString().padStart(exponent + 1, '0');
  const whole = digits.slice(0, digits.length - exponent);
  const frac = digits.slice(digits.length - exponent);
  const sign = negative ? '-' : '';
  // A zero-decimal currency (JPY, KRW) must not emit a trailing separator.
  // Exported separately from toDecimalString so this branch is reachable by a
  // test rather than resting on a currency the table does not yet hold.
  return exponent === 0 ? `${sign}${whole}` : `${sign}${whole}.${frac}`;
};

export const toDecimalString = (amount: Money): string => {
  // The currency is re-checked here, not only at construction. The fix that
  // added assertCurrency covered the constructors and left the render path
  // alone, so an unmapped code still made `exponent` undefined and printed
  // 123 minor units as ".123" -- formatted "$0.12" for $1.23.
  assertMoney(amount);
  return formatMinorUnits(amount.minor, CURRENCY_EXPONENT[assertCurrency(amount.currency)]);
};

/**
 * Formatters are expensive to build and immutable once built, and the key space
 * is one locale times one currency. Constructing per call measured 62x slower.
 */
const FORMATTERS = new Map<string, Intl.NumberFormat>();

/**
 * The cache is bounded and its key is canonicalised, because `locale` is
 * caller-supplied and BCP-47 private-use subtags are unlimited: `en-US-x-a1`,
 * `en-US-x-a2`, … are all valid and each minted a distinct ICU formatter that
 * was never released. Twenty thousand of them retained tens of megabytes.
 */
const FORMATTER_CACHE_LIMIT = 64;

/**
 * Localised currency form, e.g. `"$1,234.56"`.
 *
 * Formats from the exact decimal string rather than a Number, so amounts
 * beyond 2^53 minor units render without precision loss. `Intl.NumberFormat`
 * has accepted a numeric string since ES2023, which `lib` already includes.
 */
export const format = (amount: Money, locale = 'en-US'): string => {
  assertMoney(amount);
  if (typeof locale !== 'string') {
    throw new MoneyError(`locale must be a string, received ${typeof locale}`);
  }
  let canonical: string;
  try {
    // Canonicalising collapses `EN-us` and `en-US` onto one cache entry, and
    // turns an invalid tag into a domain error rather than the raw RangeError
    // that escaped the taxonomy and 500'd on a malformed Accept-Language.
    // `Intl.Locale` rather than `getCanonicalLocales`, which returns an array
    // whose empty case is unreachable for a string input and so cannot be
    // tested.
    canonical = new Intl.Locale(locale).toString();
  } catch {
    throw new MoneyError(`unrecognised locale ${JSON.stringify(locale)}`);
  }
  const key = `${canonical}|${amount.currency}`;
  let formatter = FORMATTERS.get(key);
  if (formatter === undefined) {
    formatter = new Intl.NumberFormat(canonical, {
      style: 'currency',
      currency: amount.currency,
    });
    if (FORMATTERS.size < FORMATTER_CACHE_LIMIT) {
      FORMATTERS.set(key, formatter);
    }
  }
  // toDecimalString emits a bare decimal numeral, which is exactly what this
  // overload accepts; the assertion narrows `string` to the template-literal
  // type rather than lying about it being a number.
  return formatter.format(toDecimalString(amount) as Intl.StringNumericLiteral);
};
