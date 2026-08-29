/**
 * The split at entry: a mortgage payment reaches the bank as ONE row, but
 * Schedule E needs interest (deductible) apart from principal (equity).
 * The engine already knows the period's split — this module only decides
 * what can honestly be offered for a given bank amount. It computes no
 * arithmetic of its own beyond exact money comparison: the figures are the
 * engine's, passed through.
 */
import {
  abs,
  add,
  equals,
  isZero,
  lessThan,
  money,
  subtract,
  toDecimalString,
} from '@hestia/domain';
import type { DebtOut, LedgerEventOut, ScheduleOut } from './api';

export interface NoteSplit {
  debtId: string;
  lender: string;
  interest: string;
  principal: string;
  /** The engine's scheduled payment — interest + principal, to the cent. */
  payment: string;
  /** The engine naming itself; every offer carries its stamp. */
  citation: string;
}

export type SplitOffer =
  /** The bank row equals the scheduled payment exactly: the pair is offerable. */
  | { kind: 'exact'; split: NoteSplit }
  /** The row exceeds the payment — an escrow impound rides along. There is no
   * honest ledger category for money a servicer merely holds, so the offer
   * points at the debt-payment path, which records escrow on the note. */
  | { kind: 'remainder'; split: NoteSplit; remainder: string }
  /** The row is short of the payment; nothing is offered. */
  | { kind: 'short'; split: NoteSplit; shortfall: string };

/** The engine's split for a note's next period, or null when the note has
 * no schedule (interest-only, negative-amortizing) or nothing next. */
export function noteSplit(debt: DebtOut, schedule: ScheduleOut): NoteSplit | null {
  if (schedule.next_interest === null || schedule.next_principal === null) {
    return null;
  }
  const interest = money(schedule.next_interest);
  const principal = money(schedule.next_principal);
  return {
    debtId: debt.id,
    lender: debt.lender ?? 'Unnamed lender',
    interest: toDecimalString(interest),
    principal: toDecimalString(principal),
    payment: toDecimalString(add(interest, principal)),
    citation: schedule.citation,
  };
}

/** What can be offered for a bank-row amount against a note's split. The
 * row amount may carry either sign — an outflow is compared by magnitude. */
export function splitOffer(amount: string, split: NoteSplit): SplitOffer {
  const rowMagnitude = abs(money(amount));
  const payment = money(split.payment);
  if (equals(rowMagnitude, payment)) {
    return { kind: 'exact', split };
  }
  if (lessThan(rowMagnitude, payment)) {
    return { kind: 'short', split, shortfall: toDecimalString(subtract(payment, rowMagnitude)) };
  }
  return { kind: 'remainder', split, remainder: toDecimalString(subtract(rowMagnitude, payment)) };
}

/** Which notes a bank row can honestly settle. Exact matches identify the
 * note by the figure itself; with none, `nearest` explains the closest miss. */
export function matchOffers(
  amount: string,
  splits: readonly NoteSplit[],
): { exact: NoteSplit[]; nearest: SplitOffer | null } {
  const offers = splits.map((split) => splitOffer(amount, split));
  const exact = offers.filter((offer) => offer.kind === 'exact').map((offer) => offer.split);
  if (exact.length > 0 || offers.length === 0) {
    return { exact, nearest: null };
  }
  const magnitude = abs(money(amount));
  let nearest = offers[0] as SplitOffer;
  for (const offer of offers.slice(1)) {
    const gap = (candidate: SplitOffer) => abs(subtract(magnitude, money(candidate.split.payment)));
    if (lessThan(gap(offer), gap(nearest))) {
      nearest = offer;
    }
  }
  return { exact, nearest };
}

/** The AcceptIn splits for a row settled by a note: the engine's figures,
 * carrying the row's own sign so the pair sums to the row exactly.
 *
 * A zero leg is omitted, mirroring the server's own convention: the ledger
 * refuses a zero amount, so emitting one turned an offered accept into a 422
 * for every 0%-rate note and for a final row whose interest rounds away. The
 * surviving leg still sums to the row exactly, because the other was zero. */
export function acceptSplits(
  rowAmount: string,
  split: NoteSplit,
): { category: 'mortgage_interest' | 'mortgage_principal'; amount: string }[] {
  const outflow = lessThan(money(rowAmount), money('0'));
  const signed = (value: string) => (outflow ? `-${value}` : value);
  const legs: { category: 'mortgage_interest' | 'mortgage_principal'; amount: string }[] = [];
  for (const [category, value] of [
    ['mortgage_interest', split.interest],
    ['mortgage_principal', split.principal],
  ] as const) {
    if (!isZero(money(value))) {
      legs.push({ category, amount: signed(value) });
    }
  }
  return legs;
}

export type RegisterLine =
  | { kind: 'single'; event: LedgerEventOut }
  | { kind: 'pair'; total: string; interest: LedgerEventOut; principal: LedgerEventOut };

const liveMortgage = (event: LedgerEventOut, category: string): boolean =>
  event.category === category && !event.reversed && event.reverses_event_uuid === null;

const sameKey = (a: LedgerEventOut, b: LedgerEventOut): boolean =>
  a.occurred_on === b.occurred_on && a.memo === b.memo && a.counterparty === b.counterparty;

/** Fold a register so each mortgage interest/principal pair — same day, same
 * memo, same counterparty, both standing — reads as the one payment it was.
 * A reversed member disqualifies the pair: struck entries stand alone. */
export function pairMortgageEvents(events: readonly LedgerEventOut[]): RegisterLine[] {
  const lines: RegisterLine[] = [];
  const consumed = new Set<string>();
  for (const event of events) {
    if (consumed.has(event.event_uuid)) continue;
    if (liveMortgage(event, 'mortgage_interest') || liveMortgage(event, 'mortgage_principal')) {
      const otherCategory =
        event.category === 'mortgage_interest' ? 'mortgage_principal' : 'mortgage_interest';
      const partner = events.find(
        (candidate) =>
          !consumed.has(candidate.event_uuid) &&
          candidate.event_uuid !== event.event_uuid &&
          liveMortgage(candidate, otherCategory) &&
          sameKey(event, candidate),
      );
      if (partner) {
        consumed.add(event.event_uuid);
        consumed.add(partner.event_uuid);
        const [interest, principal] =
          event.category === 'mortgage_interest' ? [event, partner] : [partner, event];
        lines.push({
          kind: 'pair',
          total: toDecimalString(add(money(interest.amount), money(principal.amount))),
          interest,
          principal,
        });
        continue;
      }
    }
    lines.push({ kind: 'single', event });
  }
  return lines;
}
