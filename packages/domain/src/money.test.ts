import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { MoneyError, RateError } from './errors.js';
import {
  abs,
  add,
  allocate,
  assertCurrency,
  assertRounding,
  CURRENCY_EXPONENT,
  compare,
  divide,
  divideRound,
  equals,
  format,
  formatMinorUnits,
  fromJSON,
  fromMinor,
  greaterThan,
  isComparable,
  isMoney,
  isNegative,
  isPositive,
  isZero,
  lessThan,
  MAX_ALLOCATION_PARTS,
  type Money,
  max,
  min,
  money,
  multiply,
  negate,
  Rounding,
  ratio,
  roundToMoney,
  split,
  subtract,
  sum,
  toDecimalString,
  toJSON,
  withRounding,
  zero,
} from './money.js';
import { FinancialDecimal } from './numeric.js';
import {
  fraction,
  ONE_RATE,
  percent,
  type Rate,
  rate,
  rateToPercentString,
  ZERO_RATE,
} from './rate.js';

/** Amounts spanning roughly ±$10 trillion, well beyond Number.MAX_SAFE_INTEGER cents. */
const arbMoney = fc.bigInt({ min: -(10n ** 15n), max: 10n ** 15n }).map((m) => fromMinor(m));
const arbWeights = fc.array(fc.integer({ min: 0, max: 10_000 }), { minLength: 1, maxLength: 12 });
const allModes = Object.values(Rounding);

describe('construction', () => {
  it('parses exact decimal strings', () => {
    expect(money('1234.56').minor).toBe(123456n);
    expect(money('-1234.56').minor).toBe(-123456n);
    expect(money('0.01').minor).toBe(1n);
    expect(money('0').minor).toBe(0n);
    expect(money(1234.56).minor).toBe(123456n);
  });

  it('accepts values with fewer decimals than the minor unit', () => {
    expect(money('5').minor).toBe(500n);
    expect(money('5.1').minor).toBe(510n);
  });

  it('refuses precision it cannot hold rather than guessing', () => {
    expect(() => money('1.005')).toThrow(MoneyError);
    expect(() => money('0.001')).toThrow(
      /0\.001 carries more precision than USD can hold; round it explicitly with roundToMoney/,
    );
  });

  it('refuses non-finite amounts', () => {
    expect(() => money(Number.POSITIVE_INFINITY)).toThrow(
      /amount must be finite, received Infinity/,
    );
    expect(() => money(Number.NaN)).toThrow(/amount must be finite, received NaN/);
    expect(() => roundToMoney(Number.NaN, Rounding.HalfEven)).toThrow(
      /amount must be finite, received NaN/,
    );
  });

  it('holds amounts far beyond IEEE-754 integer safety', () => {
    // 2^53 cents is ~$90 trillion; a float would start losing pennies here.
    const huge = fromMinor(9_007_199_254_740_993n);
    expect(toDecimalString(huge)).toBe('90071992547409.93');
    expect(toDecimalString(add(huge, money('0.01')))).toBe('90071992547409.94');
  });

  it('zero is zero', () => {
    expect(isZero(zero())).toBe(true);
    expect(zero().currency).toBe('USD');
  });

  it('tags its values so a bare object cannot masquerade as money', () => {
    expect(money('1.00')._tag).toBe('Money');
    expect(fromMinor(1n)._tag).toBe('Money');
    expect(zero()._tag).toBe('Money');
    expect(roundToMoney('1.005', Rounding.HalfEven)._tag).toBe('Money');
  });
});

describe('rounding', () => {
  // The boundary is where rounding bugs live, so each mode is pinned at ±0.5.
  const cases: ReadonlyArray<[string, Rounding, string]> = [
    ['1.005', Rounding.HalfEven, '1.00'],
    ['1.015', Rounding.HalfEven, '1.02'],
    ['1.004', Rounding.HalfEven, '1.00'],
    ['1.006', Rounding.HalfEven, '1.01'],
    ['-1.004', Rounding.HalfEven, '-1.00'],
    ['-1.006', Rounding.HalfEven, '-1.01'],
    ['1.005', Rounding.HalfUp, '1.01'],
    ['1.004', Rounding.HalfUp, '1.00'],
    ['1.006', Rounding.HalfUp, '1.01'],
    ['1.005', Rounding.HalfDown, '1.00'],
    ['1.004', Rounding.HalfDown, '1.00'],
    ['1.006', Rounding.HalfDown, '1.01'],
    // Odd quotient at the tie: HalfDown keeps 1.01 where HalfEven goes to 1.02.
    // Without this the two modes agree everywhere and HalfDown is untested.
    ['1.015', Rounding.HalfDown, '1.01'],
    ['-1.015', Rounding.HalfDown, '-1.01'],
    // Below the tie with an odd quotient, distinguishing "return the quotient"
    // from "fall through to the even check".
    ['1.014', Rounding.HalfEven, '1.01'],
    ['-1.014', Rounding.HalfEven, '-1.01'],
    ['1.016', Rounding.HalfEven, '1.02'],
    ['1.001', Rounding.Up, '1.01'],
    ['1.009', Rounding.Down, '1.00'],
    ['1.001', Rounding.Ceiling, '1.01'],
    ['1.009', Rounding.Floor, '1.00'],
    ['-1.005', Rounding.HalfEven, '-1.00'],
    ['-1.015', Rounding.HalfEven, '-1.02'],
    ['-1.005', Rounding.HalfUp, '-1.01'],
    ['-1.005', Rounding.HalfDown, '-1.00'],
    ['-1.001', Rounding.Up, '-1.01'],
    ['-1.009', Rounding.Down, '-1.00'],
    ['-1.001', Rounding.Ceiling, '-1.00'],
    ['-1.001', Rounding.Floor, '-1.01'],
  ];

  for (const [input, mode, expected] of cases) {
    it(`${input} under ${mode} is ${expected}`, () => {
      expect(toDecimalString(roundToMoney(input, mode))).toBe(expected);
    });
  }

  it('leaves exact values untouched under every mode', () => {
    for (const mode of allModes) {
      expect(toDecimalString(roundToMoney('1.23', mode))).toBe('1.23');
      expect(toDecimalString(roundToMoney('-1.23', mode))).toBe('-1.23');
    }
  });

  it('scales up values carrying fewer decimals than the minor unit', () => {
    for (const mode of allModes) {
      expect(toDecimalString(roundToMoney('5', mode))).toBe('5.00');
      expect(toDecimalString(roundToMoney('5.1', mode))).toBe('5.10');
      expect(toDecimalString(roundToMoney('-5', mode))).toBe('-5.00');
    }
  });

  it('rejects division by zero', () => {
    expect(() => divideRound(1n, 0n, Rounding.HalfEven)).toThrow(/division by zero/);
  });

  it('handles a negative denominator by normalising the sign', () => {
    expect(divideRound(10n, -4n, Rounding.HalfEven)).toBe(-2n);
    expect(divideRound(-10n, -4n, Rounding.HalfEven)).toBe(2n);
  });

  it('never strays more than one unit from the exact quotient', () => {
    fc.assert(
      fc.property(
        fc.bigInt({ min: -(10n ** 12n), max: 10n ** 12n }),
        fc.bigInt({ min: 1n, max: 10n ** 6n }),
        fc.constantFrom(...allModes),
        (n, d, mode) => {
          const q = divideRound(n, d, mode);
          const diff = n - q * d;
          expect(diff < d && diff > -d).toBe(true);
        },
      ),
    );
  });
});

describe('arithmetic', () => {
  it('adds and subtracts exactly', () => {
    expect(toDecimalString(add(money('1234.56'), money('0.44')))).toBe('1235.00');
    expect(toDecimalString(subtract(money('1000.00'), money('0.01')))).toBe('999.99');
  });

  it('refuses to mix currencies in every binary operation', () => {
    const usd = money('1.00');
    const other = money('1.00', 'CAD');
    expect(() => add(usd, other)).toThrow(/USD and CAD are not commensurable/);
    expect(() => subtract(usd, other)).toThrow(/not commensurable/);
    expect(() => compare(usd, other)).toThrow(MoneyError);
    expect(() => min(usd, other)).toThrow(MoneyError);
    expect(() => max(usd, other)).toThrow(MoneyError);
    expect(() => lessThan(usd, other)).toThrow(MoneyError);
    expect(() => greaterThan(usd, other)).toThrow(MoneyError);
  });

  it('sums a list, and an empty list is zero', () => {
    expect(toDecimalString(sum([money('1.11'), money('2.22'), money('3.33')]))).toBe('6.66');
    expect(isZero(sum([]))).toBe(true);
  });

  it('multiplies by a rate with explicit rounding', () => {
    // $1,000 at 6.75% is exactly $67.50 — no rounding required.
    expect(toDecimalString(multiply(money('1000.00'), percent('6.75'), Rounding.HalfEven))).toBe(
      '67.50',
    );
    // $100 at 1/3 is $33.333..., resolved by the mode.
    const third = rate('0.333333333333333333333333');
    expect(toDecimalString(multiply(money('100.00'), third, Rounding.Down))).toBe('33.33');
    expect(toDecimalString(multiply(money('100.00'), third, Rounding.Up))).toBe('33.34');
  });

  it('divides by a rate', () => {
    expect(toDecimalString(divide(money('67.50'), percent('6.75'), Rounding.HalfEven))).toBe(
      '1000.00',
    );
    expect(() => divide(money('1.00'), ZERO_RATE, Rounding.HalfEven)).toThrow(/zero rate/);
  });

  it('negates and takes magnitude', () => {
    expect(toDecimalString(negate(money('1.23')))).toBe('-1.23');
    expect(toDecimalString(abs(money('-1.23')))).toBe('1.23');
    expect(toDecimalString(abs(money('1.23')))).toBe('1.23');
  });

  describe('invariants', () => {
    it('addition is commutative', () => {
      fc.assert(
        fc.property(arbMoney, arbMoney, (a, b) => {
          expect(equals(add(a, b), add(b, a))).toBe(true);
        }),
      );
    });

    it('addition is associative', () => {
      fc.assert(
        fc.property(arbMoney, arbMoney, arbMoney, (a, b, c) => {
          expect(equals(add(add(a, b), c), add(a, add(b, c)))).toBe(true);
        }),
      );
    });

    it('subtraction undoes addition', () => {
      fc.assert(
        fc.property(arbMoney, arbMoney, (a, b) => {
          expect(equals(subtract(add(a, b), b), a)).toBe(true);
        }),
      );
    });

    it('an amount plus its negation is zero', () => {
      fc.assert(
        fc.property(arbMoney, (a) => {
          expect(isZero(add(a, negate(a)))).toBe(true);
        }),
      );
    });

    it('multiplying by one is the identity under every mode', () => {
      fc.assert(
        fc.property(arbMoney, fc.constantFrom(...allModes), (a, mode) => {
          expect(equals(multiply(a, ONE_RATE, mode), a)).toBe(true);
        }),
      );
    });

    it('decimal rendering round-trips without loss', () => {
      fc.assert(
        fc.property(arbMoney, (a) => {
          expect(equals(money(toDecimalString(a)), a)).toBe(true);
        }),
      );
    });
  });
});

describe('allocation', () => {
  it('splits without inventing or losing a cent', () => {
    // The canonical case: a dollar three ways.
    expect(split(money('1.00'), 3).map(toDecimalString)).toEqual(['0.34', '0.33', '0.33']);
  });

  it('weights allocation proportionally', () => {
    // A purchase price allocation across land and improvements.
    const parts = allocate(money('412500.00'), [22, 78]);
    expect(parts.map(toDecimalString)).toEqual(['90750.00', '321750.00']);
  });

  it('gives the remainder to the largest fractional share first', () => {
    // magnitude 10 over weights 1:2:3 leaves remainders 4, 2, 0 and one cent
    // spare -- it must land on the first share, not the last.
    expect(allocate(money('0.10'), [1, 2, 3]).map(toDecimalString)).toEqual([
      '0.02',
      '0.03',
      '0.05',
    ]);
    // Two spare cents walk down the remainder ordering 5, 4, 3.
    expect(allocate(money('0.11'), [1, 2, 3]).map(toDecimalString)).toEqual([
      '0.02',
      '0.04',
      '0.05',
    ]);
  });

  it('follows remainder magnitude rather than position', () => {
    // Mirror of the case above. The spare cent belongs to the *last* share
    // here, because remainders run 0, 2, 4 -- position must not decide it.
    expect(allocate(money('0.10'), [3, 2, 1]).map(toDecimalString)).toEqual([
      '0.05',
      '0.03',
      '0.02',
    ]);
    expect(allocate(money('0.11'), [3, 2, 1]).map(toDecimalString)).toEqual([
      '0.05',
      '0.04',
      '0.02',
    ]);
  });

  it('breaks ties by position, so allocation is deterministic', () => {
    expect(allocate(money('0.01'), [1, 1]).map(toDecimalString)).toEqual(['0.01', '0.00']);
    expect(allocate(money('0.10'), [1, 1, 1]).map(toDecimalString)).toEqual([
      '0.04',
      '0.03',
      '0.03',
    ]);
    // Every remainder ties, so the three spare cents must walk the shares in
    // index order. This pins the tie-break against any reordering of the sort.
    expect(allocate(money('0.03'), [1, 1, 1, 1, 1]).map(toDecimalString)).toEqual([
      '0.01',
      '0.01',
      '0.01',
      '0.00',
      '0.00',
    ]);
    expect(allocate(money('0.07'), [1, 1, 1, 1, 1]).map(toDecimalString)).toEqual([
      '0.02',
      '0.02',
      '0.01',
      '0.01',
      '0.01',
    ]);
  });

  it('handles negative amounts symmetrically', () => {
    expect(split(money('-1.00'), 3).map(toDecimalString)).toEqual(['-0.34', '-0.33', '-0.33']);
  });

  it('accepts fractional weights', () => {
    expect(allocate(money('100.00'), [0.5, 0.25, 0.25]).map(toDecimalString)).toEqual([
      '50.00',
      '25.00',
      '25.00',
    ]);
  });

  it('tolerates zero weights among non-zero ones', () => {
    expect(allocate(money('10.00'), [1, 0]).map(toDecimalString)).toEqual(['10.00', '0.00']);
  });

  it('rejects degenerate weightings', () => {
    expect(() => allocate(money('1.00'), [])).toThrow(/allocation requires at least one weight/);
    expect(() => allocate(money('1.00'), [0, 0])).toThrow(/weights must not sum to zero/);
    expect(() => allocate(money('1.00'), [-1, 2])).toThrow(
      /weights must be non-negative, received -1/,
    );
    expect(() => allocate(money('1.00'), [Number.NaN])).toThrow(/allocation weight must be finite/);
  });

  it('rejects a non-positive or fractional split', () => {
    expect(() => split(money('1.00'), 0)).toThrow(/positive integer/);
    expect(() => split(money('1.00'), 2.5)).toThrow(MoneyError);
  });

  describe('invariants', () => {
    it('shares always sum back to the original exactly', () => {
      fc.assert(
        fc.property(arbMoney, arbWeights, (amount, weights) => {
          fc.pre(weights.some((w) => w > 0));
          const parts = allocate(amount, weights);
          expect(equals(sum(parts), amount)).toBe(true);
          expect(parts).toHaveLength(weights.length);
        }),
      );
    });

    it('equal shares differ by at most one minor unit', () => {
      fc.assert(
        fc.property(arbMoney, fc.integer({ min: 1, max: 50 }), (amount, parts) => {
          const shares = split(amount, parts).map((s) => s.minor);
          const highest = shares.reduce((a, b) => (a > b ? a : b), shares[0] as bigint);
          const lowest = shares.reduce((a, b) => (a < b ? a : b), shares[0] as bigint);
          expect(highest - lowest <= 1n).toBe(true);
        }),
      );
    });
  });
});

describe('comparison', () => {
  it('orders amounts', () => {
    const a = money('1.00');
    const b = money('2.00');
    expect(compare(a, b)).toBe(-1);
    expect(compare(b, a)).toBe(1);
    expect(compare(a, money('1.00'))).toBe(0);
    expect(lessThan(a, b)).toBe(true);
    expect(lessThan(b, a)).toBe(false);
    expect(greaterThan(b, a)).toBe(true);
    expect(greaterThan(a, b)).toBe(false);
  });

  it('treats equal amounts as neither less nor greater', () => {
    const a = money('1.00');
    const same = money('1.00');
    expect(lessThan(a, same)).toBe(false);
    expect(greaterThan(a, same)).toBe(false);
    // Reference identity pins which operand a tie returns.
    expect(min(a, same)).toBe(a);
    expect(max(a, same)).toBe(a);
  });

  it('selects the extreme operand', () => {
    const a = money('1.00');
    const b = money('2.00');
    expect(min(a, b)).toBe(a);
    expect(min(b, a)).toBe(a);
    expect(max(a, b)).toBe(b);
    expect(max(b, a)).toBe(b);
  });

  it('requires both currency and amount to match, without throwing', () => {
    const usd = money('1.00');
    expect(equals(usd, money('1.00'))).toBe(true);
    // Same amount, different currency.
    expect(equals(usd, money('1.00', 'CAD'))).toBe(false);
    // Same currency, different amount.
    expect(equals(usd, money('2.00'))).toBe(false);
  });

  it('reports sign', () => {
    expect(isNegative(money('-0.01'))).toBe(true);
    expect(isNegative(zero())).toBe(false);
    expect(isNegative(money('0.01'))).toBe(false);
    expect(isPositive(money('0.01'))).toBe(true);
    expect(isPositive(zero())).toBe(false);
    expect(isPositive(money('-0.01'))).toBe(false);
    expect(isZero(zero())).toBe(true);
    expect(isZero(money('0.01'))).toBe(false);
    expect(isZero(money('-0.01'))).toBe(false);
  });
});

describe('rendering', () => {
  it('renders exact decimal strings', () => {
    expect(toDecimalString(money('1234.56'))).toBe('1234.56');
    expect(toDecimalString(money('-0.07'))).toBe('-0.07');
    expect(toDecimalString(fromMinor(7n))).toBe('0.07');
    expect(toDecimalString(zero())).toBe('0.00');
  });

  it('formats for humans without precision loss', () => {
    expect(format(money('1234.56'))).toBe('$1,234.56');
    expect(format(money('-1234.56'))).toBe('-$1,234.56');
    expect(format(fromMinor(9_007_199_254_740_993n))).toBe('$90,071,992,547,409.93');
  });
});

// ---------------------------------------------------------------------------
// Regressions. Each was a live defect reachable without a cast, and several
// rendered or crashed rather than raising a domain error.
// ---------------------------------------------------------------------------

describe('currency is checked at runtime, not only by the compiler', () => {
  const forged = 'EUR' as unknown as 'USD';

  it('refuses an unsupported currency at every constructor', () => {
    expect(() => money('1.23', forged)).toThrow(/unsupported currency "EUR"/);
    expect(() => fromMinor(123n, forged)).toThrow(MoneyError);
    expect(() => zero(forged)).toThrow(MoneyError);
    expect(() => roundToMoney('1.235', Rounding.HalfEven, forged)).toThrow(MoneyError);
  });

  it('closes the hundredfold mis-render', () => {
    // fromMinor(123n, 'EUR') used to produce a Money whose exponent lookup was
    // undefined; toDecimalString then returned ".123" and format returned
    // "€0.12" — €1.23 shown as twelve cents, with no error anywhere.
    expect(() => fromMinor(123n, forged)).toThrow(MoneyError);
  });

  it('refuses a non-bigint minor unit', () => {
    expect(() => fromMinor(123 as unknown as bigint)).toThrow(/must be a bigint/);
  });
});

describe('the rounding mode is checked at runtime', () => {
  it('refuses an unrecognised mode with a domain error', () => {
    // The mode is designed to arrive from configuration, so it reaches this
    // module as an unchecked string; an unknown one produced a TypeError.
    for (const bad of ['half_even', 'BANKERS', undefined, null, 7]) {
      expect(() => roundToMoney('1.005', bad as unknown as Rounding)).toThrow(MoneyError);
    }
    expect(() => roundToMoney('1.005', 'half_even' as unknown as Rounding)).toThrow(
      /unknown rounding mode/,
    );
    expect(() => divideRound(3n, 2n, 'nope' as unknown as Rounding)).toThrow(MoneyError);
  });
});

describe('a forged or non-finite Rate cannot reach BigInt', () => {
  it('raises a domain error rather than a SyntaxError', () => {
    const forgedRate = { _tag: 'Rate', value: new FinancialDecimal(0).div(0) } as unknown as Rate;
    expect(() => multiply(money('100.00'), forgedRate, Rounding.HalfEven)).toThrow(MoneyError);
    // divide's zero-guard is false for NaN, so it gave false assurance.
    expect(() => divide(money('100.00'), forgedRate, Rounding.HalfEven)).toThrow(MoneyError);
    expect(() => multiply(money('1.00'), null as unknown as Rate, Rounding.Down)).toThrow(
      /must be a Rate/,
    );
  });
});

describe('bounds', () => {
  it('caps allocation and split rather than exhausting memory', () => {
    // split(m, 1e7) previously built ten million Decimals, strings and BigInt
    // parses; a value from a request body could pin a core.
    expect(() => split(money('1.00'), MAX_ALLOCATION_PARTS + 1)).toThrow(/limited to 100000/);
    expect(() =>
      allocate(money('1.00'), new Array<number>(MAX_ALLOCATION_PARTS + 1).fill(1)),
    ).toThrow(/limited to 100000/);
    expect(split(money('1.00'), 3)).toHaveLength(3);
  });
});

describe('immutability and identity', () => {
  it('freezes every Money', () => {
    for (const value of [money('1.00'), zero(), fromMinor(5n), add(money('1.00'), money('2.00'))]) {
      expect(Object.isFrozen(value)).toBe(true);
    }
  });

  it('recognises its own values and rejects impostors', () => {
    expect(isMoney(money('1.00'))).toBe(true);
    // What JSON.parse actually yields: a number, not a bigint.
    expect(isMoney({ _tag: 'Money', minor: 100, currency: 'USD' })).toBe(false);
    expect(isMoney({ _tag: 'Money', minor: 100n, currency: 'CAD' })).toBe(false);
    expect(isMoney(null)).toBe(false);
    expect(isMoney('1.00')).toBe(false);
  });
});

describe('serialisation', () => {
  it('round-trips exactly through JSON', () => {
    // JSON.stringify throws outright on a bigint, so without an explicit pair
    // every service would invent its own conversion — and the obvious one,
    // Number(row) * 100, is the float this module exists to forbid.
    for (const original of [
      money('1234.56'),
      money('-0.07'),
      zero(),
      fromMinor(9_007_199_254_740_993n),
    ]) {
      const wire = JSON.parse(JSON.stringify(toJSON(original))) as unknown;
      expect(equals(fromJSON(wire), original)).toBe(true);
    }
  });

  it('refuses malformed wire values', () => {
    expect(() => fromJSON(null)).toThrow(MoneyError);
    expect(() => fromJSON('nope')).toThrow(MoneyError);
    expect(() => fromJSON({ minor: 100, currency: 'USD' })).toThrow(/integer string/);
    expect(() => fromJSON({ minor: '1.5', currency: 'USD' })).toThrow(/integer string/);
    expect(() => fromJSON({ minor: '100', currency: 'EUR' })).toThrow(/unsupported currency/);
  });
});

describe('ratio', () => {
  it('is the way out of Money and back into Rate', () => {
    // A cap rate is NOI over price; there was previously no exit at all.
    const noi = money('42000.00');
    const price = money('600000.00');
    expect(rateToPercentString(ratio(noi, price), 2)).toBe('7.00%');
    expect(rateToPercentString(ratio(money('450000.00'), money('600000.00')), 2)).toBe('75.00%');
  });

  it('refuses a zero denominator and a currency mismatch', () => {
    expect(() => ratio(money('1.00'), zero())).toThrow(/zero denominator/);
    expect(() => ratio(money('1.00'), money('1.00', 'CAD'))).toThrow(/not commensurable/);
  });
});

describe('withRounding', () => {
  it('binds one convention for a whole computation', () => {
    // A 360-month schedule is a thousand operations that must agree; repeating
    // the literal at each call site makes a stray mode invisible in review.
    const lender = withRounding(Rounding.HalfUp);
    const irs = withRounding(Rounding.HalfEven);
    expect(lender.mode).toBe(Rounding.HalfUp);
    expect(toDecimalString(lender.round('1.005'))).toBe('1.01');
    expect(toDecimalString(irs.round('1.005'))).toBe('1.00');
    const third = rate('0.333333333333333333');
    expect(toDecimalString(lender.multiply(money('100.00'), third))).toBe('33.33');
    expect(toDecimalString(lender.divide(money('67.50'), percent('6.75')))).toBe('1000.00');
    expect(() => withRounding('nope' as unknown as Rounding)).toThrow(MoneyError);
  });
});

describe('sum honours the currency it is given', () => {
  it('asserts the argument against every element', () => {
    // The argument used to be read only on the empty path, so a caller who
    // supplied it precisely to be explicit received a mislabelled total.
    expect(toDecimalString(sum([money('1.11'), money('2.22')], 'USD'))).toBe('3.33');
    expect(() => sum([money('1.00', 'CAD')], 'USD')).toThrow(/not commensurable/);
    expect(() => sum([], 'EUR' as unknown as 'USD')).toThrow(/unsupported currency/);
  });
});

describe('comparability is askable', () => {
  it('lets a caller check before invoking a partial operation', () => {
    // equals is total and answers false; compare is partial and raises. Without
    // isComparable the natural idiom passes the first and throws on the second.
    const usd = money('1.00');
    const other = money('1.00', 'CAD');
    expect(isComparable(usd, money('2.00'))).toBe(true);
    expect(isComparable(usd, other)).toBe(false);
    expect(equals(usd, other)).toBe(false);
    expect(() => compare(usd, other)).toThrow(MoneyError);
  });
});

describe('unbounded scale cannot be turned into unbounded memory', () => {
  it('refuses an amount with a pathological number of decimal places', () => {
    // The memoised pow10 table would otherwise retain every intermediate power
    // for the process lifetime, and because each entry is itself O(n) digits
    // the retention grows as n squared — hundreds of megabytes, on success.
    // Magnitude is bounded first, so a value this small never reaches the
    // exact-integer path at all.
    expect(() => roundToMoney('1e-20002', Rounding.HalfEven)).toThrow(/beyond the representable/);
    expect(() => rate('1e-20002')).toThrow(RateError);
    expect(() => allocate(money('1.00'), ['1e-20002', '1'])).toThrow(MoneyError);
    // Within the magnitude bound but past the scale backstop.
    expect(() => roundToMoney(`0.${'1'.repeat(351)}`, Rounding.HalfEven)).toThrow(
      /351 decimal places, beyond the 350/,
    );
  });

  it('still handles every scale a real computation produces', () => {
    // A 40-significant-digit rate from fraction() is well inside the bound.
    expect(toDecimalString(multiply(money('100.00'), fraction(1, 3), Rounding.HalfEven))).toBe(
      '33.33',
    );
    expect(toDecimalString(roundToMoney('1.0000000001', Rounding.Down))).toBe('1.00');
  });
});

describe('a rehydrated Rate is rejected as a domain error', () => {
  it('does not throw a TypeError from inside the guard', () => {
    // JSON.parse(JSON.stringify(rate('0.5'))) keeps the _tag and loses the
    // prototype, so `.value.isFinite` is undefined.
    const rehydrated = JSON.parse(JSON.stringify(rate('0.5'))) as Rate;
    expect(() => multiply(money('100.00'), rehydrated, Rounding.HalfEven)).toThrow(MoneyError);
    expect(() => divide(money('100.00'), rehydrated, Rounding.HalfEven)).toThrow(MoneyError);
    expect(() =>
      multiply(money('1.00'), { _tag: 'Rate', value: 0.5 } as unknown as Rate, Rounding.Down),
    ).toThrow(/must be a Rate/);
  });
});

describe('formatMinorUnits', () => {
  it('omits the separator for a zero-decimal currency', () => {
    // Extracted so this branch is exercised directly rather than resting on a
    // currency the table does not yet contain.
    expect(formatMinorUnits(1234n, 0)).toBe('1234');
    expect(formatMinorUnits(-1234n, 0)).toBe('-1234');
    expect(formatMinorUnits(0n, 0)).toBe('0');
  });

  it('agrees with toDecimalString for the currencies that exist', () => {
    expect(formatMinorUnits(123456n, 2)).toBe(toDecimalString(fromMinor(123456n)));
    expect(formatMinorUnits(-7n, 2)).toBe(toDecimalString(fromMinor(-7n)));
  });

  it('handles a three-decimal minor unit', () => {
    expect(formatMinorUnits(1234n, 3)).toBe('1.234');
    expect(formatMinorUnits(-5n, 3)).toBe('-0.005');
  });
});

describe('errors name the input that was wrong', () => {
  it('distinguishes each operand', () => {
    expect(() => roundToMoney('x', Rounding.Down)).toThrow(/^amount must be a plain decimal/);
    // A Rate is scale-bounded at construction, so an over-deep factor cannot
    // reach multiply or divide at all -- it is refused where it is built.
    expect(() => rate(`0.${'1'.repeat(351)}`)).toThrow(/^rate carries 351 decimal places/);
    expect(() => allocate(money('1.00'), [`0.${'1'.repeat(351)}`])).toThrow(
      /^allocation weight carries 351 decimal places/,
    );
    expect(() => multiply(money('1.00'), {} as unknown as Rate, Rounding.Down)).toThrow(
      /^multiplication factor must be a Rate/,
    );
    expect(() => divide(money('1.00'), {} as unknown as Rate, Rounding.Down)).toThrow(
      /^divisor must be a Rate/,
    );
  });

  it('lists what it would have accepted', () => {
    expect(() => zero('GBP' as unknown as 'USD')).toThrow(/supported: USD, CAD/);
    expect(() => roundToMoney('1.005', 'x' as unknown as Rounding)).toThrow(/HALF_EVEN, HALF_UP/);
    expect(() => fromJSON(7)).toThrow(/cannot read money from number/);
    expect(() => fromJSON(null)).toThrow(/cannot read money from object/);
  });
});

describe('boundaries are exact', () => {
  it('admits the largest permitted scale and refuses the next', () => {
    const at = rate(`0.${'1'.repeat(350)}`);
    expect(() => multiply(money('1.00'), at, Rounding.Down)).not.toThrow();
    expect(() => rate(`0.${'1'.repeat(351)}`)).toThrow(/351 decimal places/);
  });

  it('crosses the pow10 cache boundary in both directions', () => {
    // 32 is cached, 33 takes the compute-and-discard path; both must agree.
    const cached = rate(`0.${'0'.repeat(31)}5`);
    const uncached = rate(`0.${'0'.repeat(32)}5`);
    expect(toDecimalString(multiply(money('1.00'), cached, Rounding.Up))).toBe('0.01');
    expect(toDecimalString(multiply(money('1.00'), uncached, Rounding.Up))).toBe('0.01');
    expect(toDecimalString(multiply(money('1.00'), cached, Rounding.Down))).toBe('0.00');
  });

  it('admits the largest permitted allocation and refuses the next', () => {
    expect(split(money('1.00'), MAX_ALLOCATION_PARTS)).toHaveLength(MAX_ALLOCATION_PARTS);
    expect(() => split(money('1.00'), MAX_ALLOCATION_PARTS + 1)).toThrow(/limited to/);
    const weights = new Array<number>(MAX_ALLOCATION_PARTS).fill(1);
    expect(allocate(money('1.00'), weights)).toHaveLength(MAX_ALLOCATION_PARTS);
  });
});

describe('allocation with nothing left over', () => {
  it('skips the ordering entirely when the division is exact', () => {
    // The common case — an even split of an even amount — must not pay for a
    // sort whose result is never read.
    expect(allocate(money('12.00'), [1, 1, 1, 1]).map(toDecimalString)).toEqual([
      '3.00',
      '3.00',
      '3.00',
      '3.00',
    ]);
    expect(allocate(money('0.00'), [1, 2, 3]).map(toDecimalString)).toEqual([
      '0.00',
      '0.00',
      '0.00',
    ]);
  });
});

describe('the guards examine every field', () => {
  it('rejects each way a value can fail to be Money', () => {
    expect(isMoney(undefined)).toBe(false);
    expect(isMoney(42)).toBe(false);
    expect(isMoney({ minor: 1n, currency: 'USD' })).toBe(false);
    expect(isMoney({ _tag: 'Rate', minor: 1n, currency: 'USD' })).toBe(false);
    expect(isMoney({ _tag: 'Money', minor: '1', currency: 'USD' })).toBe(false);
    expect(isMoney({ _tag: 'Money', minor: 1n, currency: 7 })).toBe(false);
  });

  it('rejects each way a currency can fail', () => {
    expect(() => assertCurrency(undefined)).toThrow(MoneyError);
    expect(() => assertCurrency(7)).toThrow(MoneyError);
    expect(() => assertCurrency('usd')).toThrow(MoneyError);
    expect(assertCurrency('USD')).toBe('USD');
  });

  it('rejects each way a rounding mode can fail', () => {
    expect(() => assertRounding(undefined)).toThrow(MoneyError);
    expect(() => assertRounding(7)).toThrow(MoneyError);
    expect(assertRounding('HALF_EVEN')).toBe(Rounding.HalfEven);
  });
});

describe('the formatter cache returns equal output on repeat calls', () => {
  it('is transparent to the caller', () => {
    const amount = money('1234.56');
    expect(format(amount)).toBe('$1,234.56');
    expect(format(amount)).toBe('$1,234.56');
    expect(format(amount, 'de-DE')).toBe(format(amount, 'de-DE'));
    expect(format(amount, 'de-DE')).not.toBe(format(amount, 'en-US'));
  });
});

describe('identity is by provenance, not by shape', () => {
  it('refuses a value this package did not mint', () => {
    // What node-postgres yields for a NUMERIC column is a string, and the
    // shape-based guard accepted it: `add` then concatenated, turning
    // $100 + $1 into $1,001.00 with no error anywhere.
    const forged = { _tag: 'Money', minor: '100', currency: 'USD' } as unknown as Money;
    expect(isMoney(forged)).toBe(false);
    expect(() => add(forged, money('1.00'))).toThrow(/must be a Money built by this package/);
    expect(() => add(money('1.00'), forged)).toThrow(/right operand/);
    expect(() => subtract(forged, money('1.00'))).toThrow(MoneyError);
    expect(() => compare(forged, money('1.00'))).toThrow(MoneyError);
    expect(() => negate(forged)).toThrow(MoneyError);
    expect(() => abs(forged)).toThrow(MoneyError);
    expect(() => toDecimalString(forged)).toThrow(MoneyError);
    expect(() => format(forged)).toThrow(MoneyError);
  });

  it('refuses a rehydrated Money and rebuilds it through fromJSON', () => {
    const original = money('1234.56');
    const wire = JSON.parse(JSON.stringify(original)) as unknown;
    expect(isMoney(wire)).toBe(false);
    expect(equals(fromJSON(wire), original)).toBe(true);
    expect(isMoney(fromJSON(wire))).toBe(true);
  });
});

describe('serialisation works through JSON.stringify', () => {
  it('needs no bespoke conversion at the boundary', () => {
    // As a free function alone, JSON.stringify never found it and threw a raw
    // TypeError naming neither the field nor the type.
    expect(JSON.stringify({ rent: money('1200.00') })).toBe(
      '{"rent":{"minor":"120000","currency":"USD"}}',
    );
    expect(JSON.stringify(money('-0.07'))).toBe('{"minor":"-7","currency":"USD"}');
  });

  it('refuses a payload whose fields come from the prototype chain', () => {
    // The downstream effect of any merge or query-string gadget: plain property
    // access read through the prototype and materialised an amount the caller
    // never sent.
    const polluted = Object.create({ minor: '99999', currency: 'USD' }) as unknown;
    expect(() => fromJSON(polluted)).toThrow(/own minor and currency/);
    expect(isMoney(polluted)).toBe(false);
  });
});

describe('the render path validates too', () => {
  it('bounds the minor-unit exponent', () => {
    // undefined made padStart(NaN) a no-op and slice(0, NaN) empty, printing
    // 123 minor units as ".123" -- $0.12 for $1.23.
    for (const bad of [undefined, Number.NaN, -1, 2.5, 99]) {
      expect(() => formatMinorUnits(123n, bad as unknown as number)).toThrow(MoneyError);
    }
    expect(() => formatMinorUnits(123 as unknown as bigint, 2)).toThrow(/must be a bigint/);
  });
});

describe('the formatter cache is bounded and its key canonical', () => {
  it('collapses case variants onto one entry', () => {
    expect(format(money('1234.56'), 'EN-us')).toBe(format(money('1234.56'), 'en-US'));
  });

  it('survives an unbounded stream of distinct valid locales', () => {
    // BCP-47 private-use subtags are unlimited and every one is valid, so an
    // unbounded cache keyed on a request-supplied locale grows without limit.
    const amount = money('1.00');
    for (let i = 0; i < 500; i += 1) {
      expect(typeof format(amount, `en-US-x-p${i}`)).toBe('string');
    }
  });

  it('raises a domain error for a malformed locale', () => {
    for (const bad of ['en_US', '', 'not a locale!!']) {
      expect(() => format(money('1.00'), bad)).toThrow(MoneyError);
    }
    expect(() => format(money('1.00'), 7 as unknown as string)).toThrow(/must be a string/);
  });
});

describe('withRounding is frozen', () => {
  it('cannot have its convention rewritten under a caller', () => {
    const irs = withRounding(Rounding.HalfEven);
    expect(Object.isFrozen(irs)).toBe(true);
    expect(() => {
      (irs as { mode: Rounding }).mode = Rounding.HalfUp;
    }).toThrow(TypeError);
    expect(irs.mode).toBe(Rounding.HalfEven);
  });
});

describe('allocation weights', () => {
  it('accepts negative zero, which is not a negative number', () => {
    // -0 arises from `x * 0`, `Math.round(-0.4)` and JSON.parse('[-0]');
    // rejecting it reported "received 0" and sent readers hunting for a
    // negative weight that did not exist.
    expect(allocate(money('10.00'), [-0, 1]).map(toDecimalString)).toEqual(['0.00', '10.00']);
    expect(allocate(money('10.00'), ['-0.00', '1']).map(toDecimalString)).toEqual([
      '0.00',
      '10.00',
    ]);
  });

  it('converts deep weights exactly rather than through a rounding multiply', () => {
    // decimal.js rounds the result of an operation to 40 significant digits, so
    // two weights differing only past digit 40 collapsed to the same integer
    // and were allocated as equal.
    const a = `0.${'1'.repeat(44)}`;
    const b = `0.${'1'.repeat(40)}9999`;
    const parts = allocate(money('1.00'), [a, b]);
    expect(equals(sum(parts), money('1.00'))).toBe(true);
    expect(parts[0]).not.toEqual(parts[1]);
  });
});

describe('the guards examine each clause independently', () => {
  it('rejects every non-object shape', () => {
    for (const bad of [undefined, null, 42, 'money', true, Symbol('m')]) {
      expect(isMoney(bad)).toBe(false);
      expect(() => add(bad as unknown as Money, money('1.00'))).toThrow(MoneyError);
    }
    // An object of the right shape that this package did not mint.
    expect(isMoney({ _tag: 'Money', minor: 1n, currency: 'USD' })).toBe(false);
    expect(isMoney(Object.create(null))).toBe(false);
  });

  it('names which operand was wrong', () => {
    const forged = { _tag: 'Money', minor: 1n, currency: 'USD' } as unknown as Money;
    expect(() => add(forged, money('1.00'))).toThrow(/^left operand must be a Money/);
    expect(() => add(money('1.00'), forged)).toThrow(/^right operand must be a Money/);
    expect(() => negate(forged)).toThrow(/^amount must be a Money/);
  });

  it('requires each JSON field to be the payload’s own', () => {
    expect(() => fromJSON({ currency: 'USD' })).toThrow(/own minor and currency/);
    expect(() => fromJSON({ minor: '100' })).toThrow(/own minor and currency/);
    expect(() => fromJSON(Object.create({ minor: '1', currency: 'USD' }))).toThrow(MoneyError);
    expect(equals(fromJSON({ minor: '100', currency: 'USD' }), money('1.00'))).toBe(true);
  });
});

describe('render bounds are exact', () => {
  it('admits every supported minor-unit exponent and refuses the neighbours', () => {
    expect(formatMinorUnits(5n, 0)).toBe('5');
    expect(formatMinorUnits(5n, 6)).toBe('0.000005');
    expect(() => formatMinorUnits(5n, -1)).toThrow(/\[0, 6\]/);
    expect(() => formatMinorUnits(5n, 7)).toThrow(/\[0, 6\]/);
  });
});

describe('the pow10 cache boundary is transparent', () => {
  it('agrees either side of the cached range', () => {
    // 32 is cached; 33 takes the compute-and-discard path.
    for (const zeros of [30, 31, 32, 33, 34]) {
      const r = rate(`0.${'0'.repeat(zeros)}5`);
      expect(toDecimalString(multiply(money('1.00'), r, Rounding.Up))).toBe('0.01');
      expect(toDecimalString(multiply(money('1.00'), r, Rounding.Down))).toBe('0.00');
    }
  });
});

describe('the registry cannot be laundered', () => {
  const forged = { _tag: 'Money', minor: 10000n, currency: 'USD' } as unknown as Money;

  it('refuses a forged operand in every producing operation', () => {
    // Each of these previously took a forged value in and handed a *minted*
    // one back, so the registry blessed an amount it never created.
    expect(() => multiply(forged, ONE_RATE, Rounding.HalfEven)).toThrow(MoneyError);
    expect(() => divide(forged, ONE_RATE, Rounding.HalfEven)).toThrow(MoneyError);
    expect(() => allocate(forged, [1, 1])).toThrow(MoneyError);
    expect(() => split(forged, 2)).toThrow(MoneyError);
    expect(() => sum([forged])).toThrow(MoneyError);
    expect(() => ratio(forged, money('1.00'))).toThrow(MoneyError);
  });

  it('refuses a forged operand in every predicate, rather than answering wrongly', () => {
    // Reading the fields directly returned a silently wrong boolean: two
    // amounts both $100.00 compared unequal, and a reconciliation gate built
    // on that fired on every row.
    expect(() => equals(forged, money('100.00'))).toThrow(MoneyError);
    expect(() => isComparable(forged, money('1.00'))).toThrow(MoneyError);
    expect(() => isZero(forged)).toThrow(MoneyError);
    expect(() => isNegative(forged)).toThrow(MoneyError);
    expect(() => isPositive(forged)).toThrow(MoneyError);
  });
});

describe('the bigint path is bounded like the decimal path', () => {
  it('refuses an amount that could not be rendered exactly', () => {
    // Two multiplications by a large rate produced a Money that format()
    // rendered as "$∞" -- through the public API alone, no forgery needed.
    const large = rate('1e150');
    const once = multiply(money('1.00'), large, Rounding.Down);
    expect(toDecimalString(once)).toHaveLength(154);
    expect(() => multiply(once, large, Rounding.Down)).toThrow(/could not be rendered exactly/);
    // And the very first step is refused when it alone would cross the bound.
    expect(() => multiply(money('1.00'), rate('1e300'), Rounding.Down)).toThrow(MoneyError);
    expect(() => fromMinor(10n ** 400n)).toThrow(MoneyError);
    expect(() => fromJSON({ minor: `1${'0'.repeat(400)}`, currency: 'USD' })).toThrow(MoneyError);
  });

  it('still renders every amount it does accept', () => {
    expect(format(fromMinor(10n ** 20n))).not.toContain('∞');
  });
});

describe('the lookup tables are frozen', () => {
  it('cannot be reinterpreted under every existing holder', () => {
    expect(Object.isFrozen(CURRENCY_EXPONENT)).toBe(true);
    expect(Object.isFrozen(Rounding)).toBe(true);
    expect(() => {
      (CURRENCY_EXPONENT as unknown as { USD: number }).USD = 0;
    }).toThrow(TypeError);
    expect(toDecimalString(money('123.45'))).toBe('123.45');
  });
});
