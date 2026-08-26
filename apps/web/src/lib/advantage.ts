/**
 * The advantage cards' arithmetic: the deterministic engines running in the
 * browser, exactly as the founding rule demands — the engines compute, the
 * UI displays, and dragging an assumption recomputes without a round trip.
 * Every function here is pure: Financials in, card view-model out.
 */
import {
  greaterThanRate,
  money,
  multiply,
  type Rate,
  Rounding,
  rate,
  toDecimalString,
} from '@hestia/domain';
import {
  balanceAfter,
  coinsuranceRecovery,
  forwardYearReturn,
  holdVersusSell,
  monthlyPayment,
} from '@hestia/engines';
import type { Financials } from './api';

export interface HoldSellView {
  equity: string;
  returnOnEquity: string; // percent, 1dp
  cashFlow: string;
  principalPaydown: string;
  appreciation: string;
  verdict: 'hold' | 'redeploy';
  margin: string; // ROE − hurdle, percent points
  noteBalance: string | null;
  caveat: string;
}

export const holdSellView = (
  financials: Financials,
  assumptions: { appreciationPercent: number; hurdlePercent: number },
): HoldSellView | null => {
  if (!financials.valuation) return null;
  const currentValue = money(financials.valuation.value);
  const noi = money(financials.noi_12mo);
  const appreciationRate = rate(String(assumptions.appreciationPercent / 100));
  const hurdle = rate(String(assumptions.hurdlePercent / 100));

  let note;
  let noteBalance: string | null = null;
  const debt = financials.debts[0];
  if (debt) {
    const terms = {
      principal: money(debt.original_principal),
      annualRate: rate(debt.annual_rate),
      termMonths: debt.term_months,
    };
    const months = Math.min(Math.max(debt.months_elapsed, 0), debt.term_months);
    const balance = balanceAfter(terms, months);
    note = {
      balance,
      annualRate: terms.annualRate,
      monthlyPayment: monthlyPayment(terms),
    };
    noteBalance = toDecimalString(balance);
  }

  const forward = forwardYearReturn({
    currentValue,
    appreciationRate,
    noiAnnual: noi,
    taxShieldAnnual: money('0.00'),
    ...(note ? { note } : {}),
  });
  const decision = holdVersusSell(forward, hurdle);
  const roePercent = ratePercent(forward.returnOnEquity);
  return {
    equity: toDecimalString(forward.equity),
    returnOnEquity: roePercent.toFixed(1),
    cashFlow: toDecimalString(forward.cashFlow),
    principalPaydown: toDecimalString(forward.principalPaydown),
    appreciation: toDecimalString(forward.appreciation),
    verdict: decision.verdict,
    margin: (roePercent - assumptions.hurdlePercent).toFixed(1),
    noteBalance,
    caveat:
      'Forward twelve months from the latest valuation; tax shield excluded ' +
      'until the tax profile phase. Assumptions are yours to drag.',
  };
};

const ratePercent = (value: Rate): number => Number(toDecimalString(multiplyRateBy100(value)));

const multiplyRateBy100 = (value: Rate) => multiply(money('100.00'), value, Rounding.HalfEven);

export interface InsuranceView {
  carrier: string | null;
  dwellingLimit: string;
  replacementBasis: string; // what number we compared against, named
  compliancePercent: string; // carried / required under the coinsurance clause
  modeledLoss: string;
  recovered: string;
  retained: string;
  lossOfRentsMonths: number | null;
  adequate: boolean;
  caveat: string;
}

export const insuranceView = (financials: Financials): InsuranceView | null => {
  const policy = financials.policies.find((entry) => entry.dwelling_limit !== null);
  if (!policy || !financials.valuation || policy.dwelling_limit === null) return null;
  const replacementCost = money(financials.valuation.value);
  const carried = money(policy.dwelling_limit);
  const coinsurance = rate(policy.coinsurance_percent ?? '0.8');
  // A one-quarter partial loss: the scenario where coinsurance penalties
  // actually bite (a total loss is capped by the limit either way).
  const modeledLoss = multiply(replacementCost, rate('0.25'), Rounding.HalfEven);
  const result = coinsuranceRecovery({
    loss: modeledLoss,
    carriedLimit: carried,
    replacementCost,
    coinsurancePercent: coinsurance,
    deductible: money('0.00'),
  });
  const compliance = Number(
    toDecimalString(multiply(money('100.00'), result.complianceFactor, Rounding.HalfEven)),
  );
  return {
    carrier: policy.carrier,
    dwellingLimit: toDecimalString(carried),
    replacementBasis: `latest ${financials.valuation.source.replaceAll('_', ' ')} valuation`,
    compliancePercent: compliance.toFixed(0),
    modeledLoss: toDecimalString(modeledLoss),
    recovered: toDecimalString(result.recovery),
    retained: toDecimalString(result.retained),
    lossOfRentsMonths: policy.loss_of_rents_months,
    adequate: !greaterThanRate(rate('1'), result.complianceFactor),
    caveat:
      'Compared against the latest valuation on record, before deductible — ' +
      'a replacement-cost appraisal sharpens this. Ordinance & law coverage ' +
      'is not yet modeled.',
  };
};
