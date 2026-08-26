import {
  add,
  compareRate,
  divideRate,
  greaterThan,
  isNegative,
  isPositive,
  lessThanRate,
  type Money,
  multiply,
  ONE_RATE,
  type Rate,
  Rounding,
  rate,
  ratio,
  subtract,
  sum,
  zero,
} from '@hestia/domain';
import { EngineError } from './errors.js';

/**
 * The return-on-equity decay engine. Equity grows through paydown and
 * appreciation, so forward ROE falls monotonically absent NOI growth; the
 * question an owner actually faces is whether *next year's* total return on
 * *current* equity still clears the rate they could redeploy at. This engine
 * computes that number and its parts — it does not editorialise, and the
 * caller renders the verdict with its inputs, per the register format.
 */
export interface NotePosition {
  readonly balance: Money;
  /** Nominal annual rate as a decimal; 0.0675 is 6.75%. */
  readonly annualRate: Rate;
  readonly monthlyPayment: Money;
}

export interface ForwardYearInput {
  readonly currentValue: Money;
  readonly appreciationRate: Rate;
  readonly noiAnnual: Money;
  /** Depreciation shield and other tax effects, already computed per book. */
  readonly taxShieldAnnual: Money;
  /** Absent note = free and clear. */
  readonly note?: NotePosition;
}

export interface ForwardYearReturn {
  readonly equity: Money;
  readonly cashFlow: Money;
  readonly principalPaydown: Money;
  readonly appreciation: Money;
  readonly taxShield: Money;
  readonly totalReturn: Money;
  /** totalReturn / equity. */
  readonly returnOnEquity: Rate;
}

/** Twelve months of the note from its current balance. */
const yearOfNote = (note: NotePosition): { paydown: Money; debtService: Money } => {
  if (isNegative(note.balance)) {
    throw new EngineError('note balance must not be negative');
  }
  if (lessThanRate(note.annualRate, rate('0')) || !lessThanRate(note.annualRate, ONE_RATE)) {
    throw new EngineError('note annualRate must be a decimal in [0, 1)');
  }
  if (!isPositive(note.monthlyPayment)) {
    throw new EngineError('note monthlyPayment must be positive');
  }
  const monthly = divideRate(note.annualRate, rate('12'));
  let balance = note.balance;
  let paydown = zero(note.balance.currency);
  let debtService = zero(note.balance.currency);
  for (let month = 1; month <= 12; month += 1) {
    if (!isPositive(balance)) break;
    const interest = multiply(balance, monthly, Rounding.HalfUp);
    if (!greaterThan(note.monthlyPayment, interest)) {
      throw new EngineError(
        `the note does not amortize: month ${month} interest meets the payment`,
      );
    }
    let principal = subtract(note.monthlyPayment, interest);
    if (greaterThan(principal, balance)) {
      principal = balance;
    }
    balance = subtract(balance, principal);
    paydown = add(paydown, principal);
    debtService = add(debtService, add(interest, principal));
  }
  return { paydown, debtService };
};

export const forwardYearReturn = (input: ForwardYearInput): ForwardYearReturn => {
  if (!isPositive(input.currentValue)) {
    throw new EngineError('currentValue must be positive');
  }
  const currency = input.currentValue.currency;
  const note = input.note;
  const loanBalance = note ? note.balance : zero(currency);
  const equity = subtract(input.currentValue, loanBalance);
  if (!isPositive(equity)) {
    throw new EngineError('equity must be positive; an underwater position has no ROE');
  }

  const { paydown, debtService } = note
    ? yearOfNote(note)
    : { paydown: zero(currency), debtService: zero(currency) };
  const cashFlow = subtract(input.noiAnnual, debtService);
  const appreciation = multiply(input.currentValue, input.appreciationRate, Rounding.HalfEven);
  const totalReturn = sum([cashFlow, paydown, appreciation, input.taxShieldAnnual], currency);

  return {
    equity,
    cashFlow,
    principalPaydown: paydown,
    appreciation,
    taxShield: input.taxShieldAnnual,
    totalReturn,
    returnOnEquity: ratio(totalReturn, equity),
  };
};

/**
 * What a sale actually nets after friction: price − selling costs − payoff −
 * the tax the disposal engine computed. The number the forward ROE is
 * competing against, because only net proceeds can be redeployed.
 */
export interface SaleProceedsInput {
  readonly salePrice: Money;
  readonly sellingCosts: Money;
  readonly loanPayoff: Money;
  readonly taxOnSale: Money;
}

export const netSaleProceeds = (input: SaleProceedsInput): Money => {
  for (const [name, value] of [
    ['sellingCosts', input.sellingCosts],
    ['loanPayoff', input.loanPayoff],
    ['taxOnSale', input.taxOnSale],
  ] as const) {
    if (isNegative(value)) {
      throw new EngineError(`${name} must not be negative`);
    }
  }
  return subtract(
    subtract(subtract(input.salePrice, input.sellingCosts), input.loanPayoff),
    input.taxOnSale,
  );
};

export type HoldSellVerdict = 'hold' | 'redeploy';

export interface HoldSellDecision {
  readonly verdict: HoldSellVerdict;
  readonly forwardReturnOnEquity: Rate;
  readonly hurdle: Rate;
}

/** Forward ROE against the owner's redeployment hurdle. Ties hold. */
export const holdVersusSell = (forward: ForwardYearReturn, hurdle: Rate): HoldSellDecision => ({
  verdict: compareRate(forward.returnOnEquity, hurdle) >= 0 ? 'hold' : 'redeploy',
  forwardReturnOnEquity: forward.returnOnEquity,
  hurdle,
});
