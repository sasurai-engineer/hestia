'use client';

import { useState } from 'react';
import type { StagedTransaction } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';
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
}: {
  rows: StagedTransaction[];
  onAccept: (txnId: string, category: string) => void;
  onExclude: (txnId: string) => void;
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
            <QueueRow key={row.id} row={row} onAccept={onAccept} onExclude={onExclude} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function QueueRow({
  row,
  onAccept,
  onExclude,
}: {
  row: StagedTransaction;
  onAccept: (txnId: string, category: string) => void;
  onExclude: (txnId: string) => void;
}) {
  const [category, setCategory] = useState(row.suggested_category ?? '');
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
      </td>
    </tr>
  );
}
