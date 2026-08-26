/**
 * The advantage cards' arithmetic: the deterministic engines running in the
 * browser, exactly as the founding rule demands — the engines compute, the
 * UI displays, and dragging an assumption recomputes without a round trip.
 * Every function here is pure: Financials in, card view-model out.
 */
import {
  add,
  greaterThanRate,
  isPositive,
  lessThan,
  type Money,
  money,
  multiply,
  type Rate,
  Rounding,
  rate,
  ratio,
  subtract,
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
  verdict: 'hold' | 'redeploy' | 'underwater';
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

  // EVERY lien counts, not just the first (the junior-debt finding): balances
  // and payments sum per lien; the blended rate is chosen so year-one
  // interest on the total equals the sum of each lien's interest.
  let note: { balance: Money; annualRate: Rate; monthlyPayment: Money } | undefined;
  let noteBalance: string | null = null;
  if (financials.debts.length > 0) {
    let balanceTotal = money('0.00');
    let paymentTotal = money('0.00');
    let interestTotal = money('0.00');
    for (const debt of financials.debts) {
      const terms = {
        principal: money(debt.original_principal),
        annualRate: rate(debt.annual_rate),
        termMonths: debt.term_months,
      };
      const months = Math.min(Math.max(debt.months_elapsed, 0), debt.term_months);
      const balance = balanceAfter(terms, months);
      balanceTotal = add(balanceTotal, balance);
      paymentTotal = add(paymentTotal, monthlyPayment(terms));
      interestTotal = add(interestTotal, multiply(balance, terms.annualRate, Rounding.HalfEven));
    }
    note = {
      balance: balanceTotal,
      annualRate: isPositive(balanceTotal) ? ratio(interestTotal, balanceTotal) : rate('0'),
      monthlyPayment: paymentTotal,
    };
    noteBalance = toDecimalString(balanceTotal);
  }

  // An underwater position (balance at or above value) has no equity for a
  // return to stand on; say so instead of letting the engine throw and take
  // the whole property page down with it.
  if (note && !lessThan(note.balance, currentValue)) {
    return {
      equity: toDecimalString(subtract(currentValue, note.balance)),
      returnOnEquity: '—',
      cashFlow: '0.00',
      principalPaydown: '0.00',
      appreciation: '0.00',
      verdict: 'underwater',
      margin: '—',
      noteBalance,
      caveat:
        'The note balance meets or exceeds the latest valuation: no equity ' +
        'to compute a return on. Update the valuation or pay the balance down.',
    };
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
  // `+ 0` folds the -0.0 that toFixed would otherwise print as "-0.0".
  const margin = Number((roePercent - assumptions.hurdlePercent).toFixed(1)) + 0;
  return {
    equity: toDecimalString(forward.equity),
    returnOnEquity: roePercent.toFixed(1),
    cashFlow: toDecimalString(forward.cashFlow),
    principalPaydown: toDecimalString(forward.principalPaydown),
    appreciation: toDecimalString(forward.appreciation),
    verdict: decision.verdict,
    margin: margin.toFixed(1),
    noteBalance,
    caveat:
      'Forward twelve months from the latest valuation; all liens aggregated ' +
      '(rate blended by balance); tax shield excluded until the tax profile ' +
      'phase. Assumptions are yours to drag.',
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
  const complianceExact = Number(
    toDecimalString(multiply(money('100.00'), result.complianceFactor, Rounding.HalfEven)),
  );
  const adequate = !greaterThanRate(rate('1'), result.complianceFactor);
  // An inadequate position must never round UP to "100%": floor it and cap at
  // 99 so the pill's number can't contradict its color.
  const compliance = adequate
    ? Math.round(complianceExact)
    : Math.min(99, Math.floor(complianceExact));
  return {
    carrier: policy.carrier,
    dwellingLimit: toDecimalString(carried),
    replacementBasis: `latest ${financials.valuation.source.replaceAll('_', ' ')} valuation`,
    compliancePercent: String(compliance),
    modeledLoss: toDecimalString(modeledLoss),
    recovered: toDecimalString(result.recovery),
    retained: toDecimalString(result.retained),
    lossOfRentsMonths: policy.loss_of_rents_months,
    adequate,
    caveat:
      'Compared against the latest valuation on record, before deductible — ' +
      'a replacement-cost appraisal sharpens this. Ordinance & law coverage ' +
      'is not yet modeled.',
  };
};
