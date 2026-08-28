import { add, money, rate, toDecimalString } from '@hestia/domain';
import { type AmortizationRow, amortizationSchedule } from '@hestia/engines';
import { describe, expect, it } from 'vitest';
import { notePlans } from '../src/lib/amortize-extra';
import type { Financials } from '../src/lib/api';

const DEBT = {
  lender: 'First Federal',
  original_principal: '190000.00',
  annual_rate: '0.0625',
  term_months: 360,
  months_elapsed: 30,
};

const debts = (rows: Financials['debts']): Financials['debts'] => rows;

describe('notePlans', () => {
  it('with no extra, reproduces the engine schedule tail to the cent', () => {
    const [plan] = notePlans(debts([DEBT]), 0);
    if (plan === undefined) throw new Error('plan expected');
    expect(plan.baselineMonths).toBe(360 - 30);
    expect(plan.extraMonths).toBe(plan.baselineMonths);
    expect(plan.interestSaved).toBe('0.00');
    expect(plan.monthsSaved).toBe(0);

    // The differential proof: the walk's interest equals the engine's own
    // rows summed over the remaining term.
    const schedule = amortizationSchedule({
      principal: money(DEBT.original_principal),
      annualRate: rate(DEBT.annual_rate),
      termMonths: DEBT.term_months,
    });
    const expected = schedule.rows
      .slice(DEBT.months_elapsed)
      .reduce((total, row) => add(total, row.interest), money('0.00'));
    expect(plan.baselineInterest).toBe(toDecimalString(expected));

    // The curve starts at the engine's balance and ends retired.
    expect(plan.baselineCurve[0]?.month).toBe(0);
    expect(plan.baselineCurve[0]?.balance).toBe(
      toDecimalString((schedule.rows[DEBT.months_elapsed - 1] as AmortizationRow).balance),
    );
    expect(plan.baselineCurve.at(-1)?.balance).toBe('0.00');
  });

  it('an extra payment retires the note sooner and never accrues the saved interest', () => {
    const [plan] = notePlans(debts([DEBT]), 200);
    if (plan === undefined) throw new Error('plan expected');
    expect(plan.extraMonths).toBeLessThan(plan.baselineMonths);
    expect(plan.monthsSaved).toBe(plan.baselineMonths - plan.extraMonths);
    expect(Number(plan.interestSaved)).toBeGreaterThan(0);
    expect(plan.extraCurve.at(-1)?.balance).toBe('0.00');
    // Quarterly samples plus the retirement point.
    expect(plan.extraCurve.length).toBeGreaterThan(plan.extraMonths / 4);
  });

  it('handles a zero-rate note: no interest either way, months still bought', () => {
    const [plan] = notePlans(
      debts([
        {
          ...DEBT,
          lender: 'Family',
          original_principal: '12000.00',
          annual_rate: '0',
          term_months: 48,
          months_elapsed: 0,
        },
      ]),
      50,
    );
    if (plan === undefined) throw new Error('plan expected');
    expect(plan.baselineInterest).toBe('0.00');
    expect(plan.extraInterest).toBe('0.00');
    expect(plan.baselineMonths).toBe(48);
    expect(plan.extraMonths).toBeLessThan(48);
  });

  it('leaves retired notes out of the conversation, and names the nameless', () => {
    expect(notePlans(debts([{ ...DEBT, months_elapsed: 360 }]), 100)).toEqual([]);
    const [nameless] = notePlans(debts([{ ...DEBT, lender: null }]), 0);
    expect(nameless?.lender).toBe('Unnamed lender');
  });
});
