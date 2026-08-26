import type { LedgerEventOut } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';

const formatMoney = (amount: string): string => {
  const value = Number(amount);
  const magnitude = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return value < 0 ? `−$${magnitude}` : `$${magnitude}`;
};

/**
 * The register: append-only made visible. A reversed pair stays on the page —
 * struck through, linked, cancelling — because the position must remain
 * reconstructible exactly as it was taken.
 */
export function TransactionsTable({
  events,
  onReverse,
}: {
  events: LedgerEventOut[];
  onReverse?: (eventUuid: string) => void;
}) {
  if (events.length === 0) {
    return <p className="muted">No transactions yet — record one below.</p>;
  }
  return (
    <div className="card card--flush">
      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Category</th>
            <th>Memo</th>
            <th style={{ textAlign: 'right' }}>Amount</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <TransactionRow
              key={event.event_uuid}
              event={event}
              {...(onReverse ? { onReverse } : {})}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TransactionRow({
  event,
  onReverse,
}: {
  event: LedgerEventOut;
  onReverse?: (eventUuid: string) => void;
}) {
  const cancelled = event.reversed || event.reverses_event_uuid !== null;
  const struck = cancelled ? { textDecoration: 'line-through' as const } : undefined;
  return (
    <tr>
      <td>{formatDate(event.occurred_on)}</td>
      <td>
        <span className="pill">{titleCase(event.category)}</span>
        {event.is_capital ? (
          <span className="pill pill--flag" title={event.capitalisation_rationale ?? ''}>
            capital
          </span>
        ) : null}
      </td>
      <td className={cancelled ? 'muted' : ''}>
        <span style={struck}>{event.memo ?? '—'}</span>
        {event.counterparty ? <div className="faint">{event.counterparty}</div> : null}
        {event.reverses_event_uuid !== null ? <div className="citation">reversal</div> : null}
      </td>
      <td
        style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', ...struck }}
        className={Number(event.amount) < 0 ? 'muted' : ''}
      >
        {formatMoney(event.amount)}
      </td>
      <td>
        {onReverse && !cancelled ? (
          <button
            className="button button--quiet"
            type="button"
            onClick={() => {
              onReverse(event.event_uuid);
            }}
          >
            Reverse
          </button>
        ) : null}
      </td>
    </tr>
  );
}

export { formatMoney };
