import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { RateError } from './errors.js';
import { FinancialDecimal } from './numeric.js';
import {
  addRate,
  compareRate,
  compound,
  divideRate,
  fraction,
  greaterThanRate,
  isNegativeRate,
  isPositiveRate,
  isRate,
  isZeroRate,
  lessThanRate,
  MAX_RENDER_DECIMALS,
  maxRate,
  minRate,
  multiplyRate,
  ONE_RATE,
  percent,
  quantizeRate,
  RATE_DB_SCALE,
  type Rate,
  rate,
  rateEquals,
  rateFromJSON,
  rateToJSON,
  rateToPercentString,
  rateToString,
  subtractRate,
  ZERO_RATE,
} from './rate.js';

const arbRate = fc
  .double({ min: -10, max: 10, noNaN: true, noDefaultInfinity: true })
  .map((n) => rate(n.toFixed(10)));

describe('construction', () => {
  it('builds from decimal form', () => {
    expect(rateToString(rate('0.0675'))).toBe('0.0675');
    expect(rateToString(rate(0.5))).toBe('0.5');
  });

  it('builds from percentage form', () => {
    expect(rateToString(percent('6.75'))).toBe('0.0675');
    expect(rateToString(percent(100))).toBe('1');
  });

  it('builds from an exact fraction', () => {
    // The annual share of a residential improvement's basis: 1/27.5.
    const annual = fraction(1, 27.5);
    expect(rateToPercentString(annual, 4)).toBe('3.6364%');
    // 1/27.5 repeats, so the round trip is correctly rounded rather than
    // exact -- and the residual is ~1e-40, far below a representable cent.
    const roundTrip = multiplyRate(annual, rate('27.5'));
    expect(rateEquals(roundTrip, ONE_RATE)).toBe(false);
    expect(subtractRate(ONE_RATE, roundTrip).value.abs().lessThan(1e-38)).toBe(true);
    // A terminating division, by contrast, is exact.
    expect(rateEquals(multiplyRate(fraction(1, 4), rate('4')), ONE_RATE)).toBe(true);
  });

  it('tags its values so a rate cannot be mistaken for money', () => {
    expect(rate('0.5')._tag).toBe('Rate');
    expect(percent('50')._tag).toBe('Rate');
    expect(fraction(1, 2)._tag).toBe('Rate');
    expect(ZERO_RATE._tag).toBe('Rate');
    expect(ONE_RATE._tag).toBe('Rate');
  });

  it('refuses non-finite and undefined rates', () => {
    expect(() => rate(Number.POSITIVE_INFINITY)).toThrow(RateError);
    expect(() => rate(Number.NaN)).toThrow(/must be finite/);
    expect(() => percent(Number.NaN)).toThrow(RateError);
    expect(() => fraction(1, 0)).toThrow(/rate denominator must not be zero/);
    expect(() => fraction(Number.NaN, 1)).toThrow(/fraction numerator must be finite/);
  });

  it('exposes a decimal configured for financial precision', () => {
    expect(FinancialDecimal.precision).toBe(40);
    expect(FinancialDecimal.rounding).toBe(6); // ROUND_HALF_EVEN
    // 40 significant digits survives a 360-period amortisation without drift.
    expect(new FinancialDecimal(1).div(3).toFixed(30)).toBe('0.333333333333333333333333333333');
  });
});

describe('arithmetic', () => {
  it('adds, subtracts, multiplies and divides', () => {
    expect(rateToString(addRate(percent('3'), percent('1.5')))).toBe('0.045');
    expect(rateToString(subtractRate(percent('3'), percent('1.5')))).toBe('0.015');
    expect(rateToString(multiplyRate(rate('0.5'), rate('0.5')))).toBe('0.25');
    expect(rateToString(divideRate(rate('1'), rate('4')))).toBe('0.25');
  });

  it('refuses division by zero', () => {
    expect(() => divideRate(ONE_RATE, ZERO_RATE)).toThrow(/divide a rate by zero/);
  });

  it('compounds over periods', () => {
    // 5% for two years is 1.1025x.
    expect(rateToString(compound(percent('5'), 2))).toBe('1.1025');
    expect(rateToString(compound(percent('5'), 0))).toBe('1');
  });

  it('refuses non-finite compounding periods', () => {
    expect(() => compound(ONE_RATE, Number.NaN)).toThrow(RateError);
    expect(() => compound(ONE_RATE, Number.POSITIVE_INFINITY)).toThrow(/must be finite/);
  });

  it('is commutative under addition', () => {
    fc.assert(
      fc.property(arbRate, arbRate, (a, b) => {
        expect(rateEquals(addRate(a, b), addRate(b, a))).toBe(true);
      }),
    );
  });

  it('subtraction undoes addition', () => {
    fc.assert(
      fc.property(arbRate, arbRate, (a, b) => {
        expect(rateEquals(subtractRate(addRate(a, b), b), a)).toBe(true);
      }),
    );
  });
});

describe('comparison and predicates', () => {
  it('orders rates', () => {
    expect(compareRate(percent('1'), percent('2'))).toBe(-1);
    expect(compareRate(percent('2'), percent('1'))).toBe(1);
    expect(compareRate(percent('1'), percent('1'))).toBe(0);
  });

  it('reports zero and sign', () => {
    expect(isZeroRate(ZERO_RATE)).toBe(true);
    expect(isZeroRate(ONE_RATE)).toBe(false);
    expect(isNegativeRate(rate('-0.01'))).toBe(true);
    expect(isNegativeRate(ZERO_RATE)).toBe(false);
    expect(isNegativeRate(ONE_RATE)).toBe(false);
  });
});

describe('rendering', () => {
  it('renders decimal and percentage forms', () => {
    expect(rateToString(percent('6.75'))).toBe('0.0675');
    expect(rateToPercentString(percent('6.75'))).toBe('6.750%');
    expect(rateToPercentString(percent('6.75'), 1)).toBe('6.8%');
    expect(rateToPercentString(ZERO_RATE, 0)).toBe('0%');
  });
});

// ---------------------------------------------------------------------------
// Regressions. Each of these was a live defect: a Rate that violated the
// invariant its own type advertises, reachable through the plain public API.
// ---------------------------------------------------------------------------

describe('the finiteness invariant holds for every Rate that exists', () => {
  it('refuses a NaN result rather than returning one', () => {
    // (1 + -2)^0.5 = (-1)^0.5. decimal.js returns NaN rather than raising, and
    // the old compound() handed that straight back as a well-formed Rate.
    expect(() => compound(rate('-2'), 0.5)).toThrow(RateError);
    expect(() => compound(rate('-2'), 0.5)).toThrow(/not a real number/);
  });

  it('refuses zero raised to a negative power', () => {
    expect(() => compound(rate('-1'), -1)).toThrow(/zero to a negative power/);
  });

  it('bounds the number of compounding periods', () => {
    // 1e15 passes Number.isFinite and produced a Decimal with exponent 2.1e13:
    // finite by every predicate, and fatal on the first attempt to render it.
    expect(() => compound(percent('5'), 1e15)).toThrow(RateError);
    expect(() => compound(percent('5'), 1e15)).toThrow(/within ±1000000/);
    // A 30-year daily schedule still resolves.
    expect(compound(percent('5'), 10_950).value.isFinite()).toBe(true);
  });

  it('refuses an overflowing product rather than yielding Infinity', () => {
    // Sitting at the representable ceiling, so one operation crosses it.
    const brink = rate('9e300');
    expect(() => multiplyRate(brink, brink)).toThrow(RateError);
    expect(() => rate('1e301')).toThrow(/beyond the representable range/);
  });

  it('keeps compareRate total, because no Rate can be NaN', () => {
    // comparedTo returns NaN for a NaN operand, which the -1|0|1 signature
    // silently mis-stated and which poisoned any sort built on it.
    const values = [percent('7'), percent('3'), percent('5')];
    const sorted = [...values].sort(compareRate).map((r) => rateToPercentString(r, 0));
    expect(sorted).toEqual(['3%', '5%', '7%']);
  });
});

describe('immutability', () => {
  it('freezes every Rate, including the shared singletons', () => {
    // `readonly` is erased at compile time. Without a freeze, one reach-in on a
    // module-level singleton poisons every consumer in the process.
    expect(Object.isFrozen(ZERO_RATE)).toBe(true);
    expect(Object.isFrozen(ONE_RATE)).toBe(true);
    expect(Object.isFrozen(percent('5'))).toBe(true);
    expect(Object.isFrozen(addRate(ZERO_RATE, ONE_RATE))).toBe(true);
  });
});

describe('the fuller comparison surface', () => {
  it('orders and selects without reaching through the wrapper', () => {
    const low = percent('3');
    const high = percent('7');
    expect(lessThanRate(low, high)).toBe(true);
    expect(lessThanRate(high, low)).toBe(false);
    expect(greaterThanRate(high, low)).toBe(true);
    expect(greaterThanRate(low, high)).toBe(false);
    expect(minRate(low, high)).toBe(low);
    expect(minRate(high, low)).toBe(low);
    expect(maxRate(low, high)).toBe(high);
    expect(maxRate(high, low)).toBe(high);
  });

  it('reports a positive rate', () => {
    expect(isPositiveRate(percent('5'))).toBe(true);
    expect(isPositiveRate(ZERO_RATE)).toBe(false);
    expect(isPositiveRate(rate('-0.01'))).toBe(false);
  });

  it('recognises its own values and rejects impostors', () => {
    expect(isRate(percent('5'))).toBe(true);
    expect(isRate({ _tag: 'Rate', value: 0.05 })).toBe(false);
    expect(isRate(null)).toBe(false);
    expect(isRate('0.05')).toBe(false);
  });
});

describe('database scale', () => {
  it('quantizes to the scale the rate_decimal column can hold', () => {
    // Rate carries 40 significant digits; NUMERIC(12,8) holds eight decimals.
    // Rounding here rather than letting PostgreSQL do it silently keeps the two
    // representations in agreement, which SCHEMA.md claims and could not keep.
    const third = fraction(1, 3);
    expect(rateToString(quantizeRate(third))).toBe('0.33333333');
    expect(RATE_DB_SCALE).toBe(8);
    expect(rateToString(quantizeRate(percent('6.75')))).toBe('0.0675');
  });
});

describe('isRate does not rest on instanceof', () => {
  it('rejects a rehydrated value and accepts a genuine one', () => {
    expect(isRate(rate('0.5'))).toBe(true);
    expect(isRate(JSON.parse(JSON.stringify(rate('0.5'))))).toBe(false);
  });

  it('is not fooled by a Decimal from another clone', () => {
    // A clone carries different precision settings, so a Rate built from one
    // would compute at a precision this module never chose.
    const Other = FinancialDecimal.clone({ precision: 7 });
    expect(isRate({ _tag: 'Rate', value: new Other(0.5) })).toBe(false);
    expect(isRate({ _tag: 'Rate', value: { s: 1, e: -1, d: [5] } })).toBe(false);
  });

  it('is not fooled by the forgeable decimal.js duck-type', () => {
    // decimal.js implements isDecimal as `instanceof || toStringTag === ...`,
    // and toStringTag is a plain own property -- so this object literal, which
    // any JSON body can carry, passed the guard that existed to reject it.
    expect(isRate({ _tag: 'Rate', value: { toStringTag: '[object Decimal]' } })).toBe(false);
    expect(isRate(JSON.parse('{"_tag":"Rate","value":{"toStringTag":"[object Decimal]"}}'))).toBe(
      false,
    );
  });
});

describe('an overflowing literal is refused at construction', () => {
  it('rejects a magnitude whose rendering would exhaust memory', () => {
    // NUMERIC_TEXT admits the text and decimal.js holds it happily; it is the
    // first attempt to render such a value that aborts the process.
    expect(() => rate('1e999999999')).toThrow(RateError);
    expect(() => rate('-1e999999999')).toThrow(/beyond the representable range/);
    expect(() => percent('1e999999999')).toThrow(RateError);
  });
});

describe('errors name the input that was wrong', () => {
  it('distinguishes each construction path', () => {
    // The subject label is the whole diagnostic value of these messages: a user
    // handed "must be a plain decimal number" needs to know which of several
    // arguments it refers to.
    expect(() => rate('x')).toThrow(/^rate must be a plain decimal number/);
    expect(() => percent('x')).toThrow(/^percentage must be a plain decimal number/);
    expect(() => fraction('x', 1)).toThrow(/^fraction numerator must be/);
    expect(() => fraction(1, 'x')).toThrow(/^fraction denominator must be/);
  });

  it('distinguishes each arithmetic result', () => {
    const brink = rate('9e300');
    expect(() => addRate(brink, brink)).toThrow(/^rate sum has magnitude/);
    expect(() => subtractRate(brink, rate('-9e300'))).toThrow(/^rate difference has magnitude/);
    expect(() => multiplyRate(brink, brink)).toThrow(/^rate product has magnitude/);
    expect(() => divideRate(brink, rate('1e-40'))).toThrow(/^rate quotient has magnitude/);
    expect(() => compound(rate('9e300'), 2)).toThrow(/^compounded rate has magnitude/);
  });
});

describe('boundaries are exact', () => {
  it('admits the largest permitted compounding period and refuses the next', () => {
    expect(compound(ZERO_RATE, 1_000_000).value.isFinite()).toBe(true);
    expect(() => compound(ZERO_RATE, 1_000_001)).toThrow(/within ±1000000/);
    expect(compound(ZERO_RATE, -1_000_000).value.isFinite()).toBe(true);
    expect(() => compound(ZERO_RATE, -1_000_001)).toThrow(/within ±1000000/);
  });

  it('separates the two conditions guarding a negative base', () => {
    // A negative base with an *integer* exponent is perfectly real.
    expect(rateToString(compound(rate('-2'), 2))).toBe('1');
    // A non-negative base with a fractional exponent is fine too.
    expect(compound(rate('3'), 0.5).value.isFinite()).toBe(true);
    // Only the conjunction is refused.
    expect(() => compound(rate('-2'), 0.5)).toThrow(/not a real number/);
  });

  it('separates the two conditions guarding zero to a negative power', () => {
    expect(rateToString(compound(rate('-1'), 2))).toBe('0');
    expect(compound(rate('1'), -1).value.isFinite()).toBe(true);
    expect(() => compound(rate('-1'), -1)).toThrow(/zero to a negative power/);
  });
});

describe('rate comparison at equality', () => {
  it('treats equal rates as neither less nor greater', () => {
    const a = percent('5');
    const same = percent('5');
    expect(lessThanRate(a, same)).toBe(false);
    expect(greaterThanRate(a, same)).toBe(false);
    expect(minRate(a, same)).toBe(a);
    expect(maxRate(a, same)).toBe(a);
  });
});

describe('isRate examines every field', () => {
  it('rejects each way a value can fail to be a Rate', () => {
    expect(isRate(undefined)).toBe(false);
    expect(isRate(42)).toBe(false);
    expect(isRate([])).toBe(false);
    expect(isRate({ value: new FinancialDecimal(1) })).toBe(false);
    expect(isRate({ _tag: 'Money', value: new FinancialDecimal(1) })).toBe(false);
    expect(isRate({ _tag: 'Rate' })).toBe(false);
  });
});

describe('a Rate is immutable all the way down', () => {
  it('freezes the decimal it holds, not merely the wrapper', () => {
    // Object.freeze is shallow, and a decimal.js value keeps its sign, exponent
    // and digit array as ordinary writable properties. ZERO_RATE and ONE_RATE
    // are process-wide singletons, so one reach-in poisoned every importer.
    expect(Object.isFrozen(ONE_RATE)).toBe(true);
    expect(Object.isFrozen(ONE_RATE.value)).toBe(true);
    expect(() => {
      (ONE_RATE.value as unknown as { e: number }).e = 2;
    }).toThrow(TypeError);
    expect(rateToString(ONE_RATE)).toBe('1');
  });
});

describe('rate serialisation', () => {
  it('round-trips through JSON', () => {
    for (const original of [percent('6.75'), fraction(1, 3), ZERO_RATE, rate('-0.5')]) {
      const wire = JSON.parse(JSON.stringify(rateToJSON(original))) as unknown;
      expect(rateEquals(rateFromJSON(wire), original)).toBe(true);
    }
  });

  it('refuses malformed wire values', () => {
    expect(() => rateFromJSON(null)).toThrow(RateError);
    expect(() => rateFromJSON('0.5')).toThrow(RateError);
    expect(() => rateFromJSON({})).toThrow(/cannot read a rate/);
    expect(() => rateFromJSON({ value: 0.5 })).toThrow(/must be a decimal string/);
    expect(() => rateFromJSON(Object.create({ value: '0.5' }))).toThrow(RateError);
  });
});

describe('rendering decimals are bounded', () => {
  it('refuses a decimal count that would exhaust memory', () => {
    // Passed straight to toFixed, 1e9 killed the process outright; a negative
    // or fractional value threw a bare decimal.js Error outside the taxonomy.
    for (const bad of [-1, 2.5, Number.NaN, 1e9, MAX_RENDER_DECIMALS + 1]) {
      expect(() => rateToPercentString(percent('5'), bad)).toThrow(RateError);
    }
    expect(rateToPercentString(percent('5'), MAX_RENDER_DECIMALS)).toContain('5.000');
  });
});

describe('the rate guards examine each clause independently', () => {
  it('rejects every non-object shape', () => {
    for (const bad of [undefined, null, 42, '0.5', true]) {
      expect(isRate(bad)).toBe(false);
    }
    expect(isRate(Object.create(null))).toBe(false);
    expect(isRate({ _tag: 'Rate', value: new FinancialDecimal(1) })).toBe(false);
  });

  it('requires the wire payload to own its value field', () => {
    expect(() => rateFromJSON(undefined)).toThrow(RateError);
    expect(() => rateFromJSON(42)).toThrow(RateError);
    expect(() => rateFromJSON([])).toThrow(/cannot read a rate/);
  });
});

describe('render decimals are exact at the boundary', () => {
  it('admits zero and the maximum, refusing either neighbour', () => {
    expect(rateToPercentString(percent('5'), 0)).toBe('5%');
    expect(() => rateToPercentString(percent('5'), -1)).toThrow(/\[0, 40\]/);
    expect(rateToPercentString(percent('5'), MAX_RENDER_DECIMALS)).toMatch(/^5\.0{40}%$/);
    expect(() => rateToPercentString(percent('5'), MAX_RENDER_DECIMALS + 1)).toThrow(/\[0, 40\]/);
  });
});

describe('rate operators refuse unminted operands', () => {
  // A forged object whose own `plus` returns something plausible previously
  // produced a value the registry then blessed as a genuine Rate.
  const forged = { _tag: 'Rate', value: new FinancialDecimal(2) } as unknown as Rate;

  it('names which operand was wrong in every binary operation', () => {
    // The label is the diagnostic: told only "must be a Rate", a caller with
    // two operands has to guess which one.
    const binary: ReadonlyArray<[string, (a: Rate, b: Rate) => unknown]> = [
      ['addRate', addRate],
      ['subtractRate', subtractRate],
      ['multiplyRate', multiplyRate],
      ['divideRate', divideRate],
      ['compareRate', compareRate],
      ['rateEquals', rateEquals],
    ];
    for (const [name, op] of binary) {
      expect(() => op(forged, ONE_RATE), name).toThrow(/^left operand must be a Rate/);
      expect(() => op(ONE_RATE, forged), name).toThrow(/^right operand must be a Rate/);
    }
  });

  it('rejects it in every unary operation', () => {
    const unary: ReadonlyArray<[string, (r: Rate) => unknown]> = [
      ['compound', (r) => compound(r, 2)],
      ['isZeroRate', isZeroRate],
      ['isNegativeRate', isNegativeRate],
      ['isPositiveRate', isPositiveRate],
      ['rateToString', rateToString],
      ['rateToJSON', rateToJSON],
      ['quantizeRate', quantizeRate],
      ['rateToPercentString', (r) => rateToPercentString(r)],
    ];
    for (const [name, op] of unary) {
      expect(() => op(forged), name).toThrow(/^rate must be a Rate built by this package/);
    }
  });
});
