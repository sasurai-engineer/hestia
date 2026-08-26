import { describe, expect, it } from 'vitest';
import { MoneyError, RateError } from './errors.js';
import { assertRepresentable, FinancialDecimal, MAX_EXPONENT, parseDecimal } from './numeric.js';

describe('parseDecimal', () => {
  it('accepts plain decimal numerals', () => {
    for (const text of [
      '0',
      '1',
      '-1',
      '+1',
      '1.5',
      '-1.5',
      '.5',
      '1.',
      '1e3',
      '1E-3',
      '-2.5e10',
    ]) {
      expect(parseDecimal(text, MoneyError, 'amount').isFinite()).toBe(true);
    }
    expect(parseDecimal(1.5, MoneyError, 'amount').toFixed()).toBe('1.5');
  });

  it('refuses presentation forms rather than guessing at them', () => {
    // Each of these previously escaped as a bare decimal.js Error, outside the
    // package's own error taxonomy, so a caller catching DomainError missed the
    // single most common class of bad input.
    for (const text of ['1,234.56', '$5.00', ' 1.00 ', '', '6.75%', '(100)', 'abc', '--1']) {
      expect(() => parseDecimal(text, MoneyError, 'amount')).toThrow(MoneyError);
      expect(() => parseDecimal(text, MoneyError, 'amount')).toThrow(/plain decimal number/);
    }
  });

  it('refuses alternate radix and separator literals rather than accepting them', () => {
    // decimal.js reads these as 16, 10, 15 and 1000. A ledger amount typed as
    // 0x10 is a corrupted cell, not sixteen dollars.
    for (const text of ['0x10', '0b1010', '0o17', '1_000', 'Infinity', 'NaN']) {
      expect(() => parseDecimal(text, MoneyError, 'amount')).toThrow(MoneyError);
    }
  });

  it('refuses non-finite numbers', () => {
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(() => parseDecimal(value, RateError, 'rate')).toThrow(RateError);
      expect(() => parseDecimal(value, RateError, 'rate')).toThrow(/must be finite/);
    }
  });

  it('raises the caller-supplied error type, keeping the taxonomy intact', () => {
    expect(() => parseDecimal('abc', RateError, 'rate')).toThrow(RateError);
    expect(() => parseDecimal('abc', MoneyError, 'amount')).toThrow(MoneyError);
  });
});

describe('assertRepresentable', () => {
  it('passes ordinary magnitudes through untouched', () => {
    const value = new FinancialDecimal('1234.56');
    expect(assertRepresentable(value, MoneyError, 'amount')).toBe(value);
    expect(assertRepresentable(new FinancialDecimal(0), MoneyError, 'amount').isZero()).toBe(true);
  });

  it('refuses a magnitude whose rendering would exhaust memory', () => {
    // A Decimal with a 2.1e13 exponent reports isFinite() === true, so no
    // ordinary guard rejects it — and the first toFixed() on it allocates a
    // string of some twenty-one trillion digits, which aborts the process.
    const enormous = new FinancialDecimal(10).pow(MAX_EXPONENT + 1);
    expect(() => assertRepresentable(enormous, MoneyError, 'amount')).toThrow(MoneyError);
    expect(() => assertRepresentable(enormous, MoneyError, 'amount')).toThrow(/exhaust memory/);
    const minuscule = new FinancialDecimal(10).pow(-(MAX_EXPONENT + 1));
    expect(() => assertRepresentable(minuscule, MoneyError, 'amount')).toThrow(/exhaust memory/);
  });

  it('refuses a non-finite decimal', () => {
    const nan = new FinancialDecimal(0).div(0);
    expect(() => assertRepresentable(nan, RateError, 'rate')).toThrow(RateError);
  });
});
