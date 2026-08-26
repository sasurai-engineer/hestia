import { money, percent, rate, rateToPercentString, toDecimalString } from '@hestia/domain';
import { describe, expect, it } from 'vitest';
import { EngineError } from './errors.js';
import { forwardYearReturn, holdVersusSell, netSaleProceeds } from './holdsell.js';

describe('forwardYearReturn', () => {
  const base = {
    currentValue: money('420000.00'),
    appreciationRate: percent('3'),
    noiAnnual: money('27600.00'),
    taxShieldAnnual: money('3100.00'),
  };

  it('composes the four components over current equity', () => {
    const result = forwardYearReturn({
      ...base,
      note: {
        balance: money('300000.00'),
        annualRate: rate('0.0675'),
        monthlyPayment: money('1945.79'),
      },
    });
    expect(toDecimalString(result.equity)).toBe('120000.00');
    // Twelve months of the fixture note: balance falls to 296,802.83.
    expect(toDecimalString(result.principalPaydown)).toBe('3197.17');
    expect(toDecimalString(result.cashFlow)).toBe('4250.52'); // 27600 - 12x1945.79
    expect(toDecimalString(result.appreciation)).toBe('12600.00');
    expect(toDecimalString(result.totalReturn)).toBe('23147.69');
    expect(rateToPercentString(result.returnOnEquity, 2)).toBe('19.29%');
  });

  it('handles free and clear: no paydown, no debt service', () => {
    const result = forwardYearReturn(base);
    expect(toDecimalString(result.equity)).toBe('420000.00');
    expect(toDecimalString(result.principalPaydown)).toBe('0.00');
    expect(toDecimalString(result.cashFlow)).toBe('27600.00');
    expect(rateToPercentString(result.returnOnEquity, 2)).toBe('10.31%');
  });

  it('stops accruing once a small note retires mid-year', () => {
    const result = forwardYearReturn({
      ...base,
      note: { balance: money('100.00'), annualRate: rate('0'), monthlyPayment: money('60.00') },
    });
    // Month 1 takes 60, month 2 clamps to the remaining 40, months 3-12 idle.
    expect(toDecimalString(result.principalPaydown)).toBe('100.00');
    expect(toDecimalString(result.cashFlow)).toBe('27500.00');
  });

  it('rejects each inadmissible position', () => {
    expect(() => forwardYearReturn({ ...base, currentValue: money('0.00') })).toThrow(
      /currentValue must be positive/,
    );
    expect(() =>
      forwardYearReturn({
        ...base,
        note: {
          balance: money('420000.00'),
          annualRate: rate('0.06'),
          monthlyPayment: money('1.00'),
        },
      }),
    ).toThrow(/equity must be positive/);
    expect(() =>
      forwardYearReturn({
        ...base,
        note: { balance: money('-1.00'), annualRate: rate('0.06'), monthlyPayment: money('1.00') },
      }),
    ).toThrow(/balance must not be negative/);
    expect(() =>
      forwardYearReturn({
        ...base,
        note: { balance: money('1000.00'), annualRate: rate('1'), monthlyPayment: money('1.00') },
      }),
    ).toThrow(/decimal in \[0, 1\)/);
    expect(() =>
      forwardYearReturn({
        ...base,
        note: {
          balance: money('1000.00'),
          annualRate: rate('0.06'),
          monthlyPayment: money('0.00'),
        },
      }),
    ).toThrow(/monthlyPayment must be positive/);
    expect(() =>
      forwardYearReturn({
        ...base,
        note: {
          balance: money('300000.00'),
          annualRate: rate('0.0675'),
          monthlyPayment: money('100.00'),
        },
      }),
    ).toThrow(/does not amortize/);
  });
});

describe('netSaleProceeds', () => {
  it('subtracts every friction in order', () => {
    expect(
      toDecimalString(
        netSaleProceeds({
          salePrice: money('500000.00'),
          sellingCosts: money('40000.00'),
          loanPayoff: money('280000.00'),
          taxOnSale: money('41500.00'),
        }),
      ),
    ).toBe('138500.00');
  });

  it('rejects negative frictions by name', () => {
    const good = {
      salePrice: money('1.00'),
      sellingCosts: money('0.00'),
      loanPayoff: money('0.00'),
      taxOnSale: money('0.00'),
    };
    expect(() => netSaleProceeds({ ...good, sellingCosts: money('-1.00') })).toThrow(
      /sellingCosts must not be negative/,
    );
    expect(() => netSaleProceeds({ ...good, loanPayoff: money('-1.00') })).toThrow(EngineError);
    expect(() => netSaleProceeds({ ...good, taxOnSale: money('-1.00') })).toThrow(
      /taxOnSale must not be negative/,
    );
  });
});

describe('holdVersusSell', () => {
  const base = {
    currentValue: money('420000.00'),
    appreciationRate: percent('3'),
    noiAnnual: money('27600.00'),
    taxShieldAnnual: money('3100.00'),
  };
  it('holds at or above the hurdle, redeploys below it', () => {
    const forward = forwardYearReturn(base); // 10.31%
    expect(holdVersusSell(forward, percent('8')).verdict).toBe('hold');
    expect(holdVersusSell(forward, percent('12')).verdict).toBe('redeploy');
    expect(holdVersusSell(forward, forward.returnOnEquity).verdict).toBe('hold');
  });
});
