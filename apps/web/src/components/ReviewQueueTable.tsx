'use client';

import { useState } from 'react';
import type { StagedTransaction } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';
import { matchOffers, type NoteSplit } from '../lib/mortgage-split';
import { formatMoney } from './TransactionsTable';

const CATEGORIES = [
  'rent',
  'other_income',
  'late_fee',
  'deposit_received',
  'deposit_returned',
  'mortgage_interest',
  'mortgage_principal',
  'property_tax',
  'insurance',
  'repairs',
  'capital_improvement',
  'utilities',
  'management_fee',
  'hoa',
  'legal_professional',
  'advertising',
  'supplies',
  'travel',
  'acquisition_cost',
  'disposition_cost',
  'owner_contribution',
  'owner_distribution',
] as const;

/**
 * The review queue: every machine suggestion passes a human before the
 * ledger is touched. Accept posts; exclude dismisses; nothing is silent.
 */
export function ReviewQueueTable({
  rows,
  onAccept,
  onExclude,
  noteSplits,
  onAcceptSplit,
}: {
  rows: StagedTransaction[];
  onAccept: (txnId: string, category: string) => void;
  onExclude: (txnId: string) => void;
  /** The engine splits for a row's property, when the page has them. */
  noteSplits?: (row: StagedTransaction) => readonly NoteSplit[];
  onAcceptSplit?: (row: StagedTransaction, split: NoteSplit) => void;
}) {
  if (rows.length === 0) {
    return <p className="muted">Queue clear — every row has been reviewed.</p>;
  }
  return (
    <div className="card card--flush">
      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th style={{ textAlign: 'right' }}>Amount</th>
            <th>Category</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <QueueRow
              key={row.id}
              row={row}
              onAccept={onAccept}
              onExclude={onExclude}
              {...(noteSplits ? { noteSplits } : {})}
              {...(onAcceptSplit ? { onAcceptSplit } : {})}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the engine can offer this row, if anything — and the honest line
 * when it cannot: an impound remainder has no ledger category for money a
 * servicer merely holds, so those rows go through the note instead. */
function SplitOfferCell({
  row,
  splits,
  onAcceptSplit,
}: {
  row: StagedTransaction;
  splits: readonly NoteSplit[];
  onAcceptSplit: (row: StagedTransaction, split: NoteSplit) => void;
}) {
  const { exact, nearest } = matchOffers(row.amount, splits);
  const [chosen, setChosen] = useState(0);
  if (exact.length > 0) {
    const split = exact[Math.min(chosen, exact.length - 1)] as NoteSplit;
    return (
      <div className="review__split">
        {exact.length > 1 ? (
          <select
            aria-label={`note for ${row.description}`}
            value={chosen}
            onChange={(event) => {
              setChosen(Number(event.target.value));
            }}
          >
            {exact.map((candidate, index) => (
              <option key={candidate.debtId} value={index}>
                {candidate.lender}
              </option>
            ))}
          </select>
        ) : null}
        <div className="faint">
          engine split: {formatMoney(split.interest)} interest · {formatMoney(split.principal)}{' '}
          principal — {split.lender}
        </div>
        <button
          className="button"
          type="button"
          onClick={() => {
            onAcceptSplit(row, split);
          }}
        >
          Accept as engine split
        </button>
      </div>
    );
  }
  if (nearest?.kind === 'remainder') {
    return (
      <div className="faint">
        {formatMoney(nearest.remainder)} above {nearest.split.lender}’s scheduled payment — an
        escrow impound rides along. Record it through the note on the property page, which holds
        escrow honestly; no ledger category exists for money a servicer merely holds.
      </div>
    );
  }
  return null;
}

function QueueRow({
  row,
  onAccept,
  onExclude,
  noteSplits,
  onAcceptSplit,
}: {
  row: StagedTransaction;
  onAccept: (txnId: string, category: string) => void;
  onExclude: (txnId: string) => void;
  noteSplits?: (row: StagedTransaction) => readonly NoteSplit[];
  onAcceptSplit?: (row: StagedTransaction, split: NoteSplit) => void;
}) {
  const [category, setCategory] = useState(row.suggested_category ?? '');
  const mortgageish = category === 'mortgage_interest' || category === 'mortgage_principal';
  const splits = mortgageish && noteSplits && onAcceptSplit ? noteSplits(row) : [];
  return (
    <tr>
      <td>{formatDate(row.posted_on)}</td>
      <td>
        {row.description}
        {row.suggested_category ? (
          <div className="faint">
            suggested {titleCase(row.suggested_category)}
            {row.suggestion_confidence != null
              ? ` · ${String(Math.round(row.suggestion_confidence * 100))}%`
              : ''}
          </div>
        ) : (
          <div className="faint">no suggestion — pick a category</div>
        )}
      </td>
      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {formatMoney(row.amount)}
      </td>
      <td>
        <select
          aria-label={`category for ${row.description}`}
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
          }}
        >
          <option value="">choose…</option>
          {CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {value.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <button
          className="button"
          type="button"
          disabled={category === ''}
          onClick={() => {
            onAccept(row.id, category);
          }}
        >
          Accept
        </button>{' '}
        <button
          className="button button--quiet"
          type="button"
          onClick={() => {
            onExclude(row.id);
          }}
        >
          Exclude
        </button>
        {splits.length > 0 && onAcceptSplit ? (
          <SplitOfferCell row={row} splits={splits} onAcceptSplit={onAcceptSplit} />
        ) : null}
      </td>
    </tr>
  );
}
