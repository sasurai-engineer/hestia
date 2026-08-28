import type { LedgerEventOut } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';
import { pairMortgageEvents } from '../lib/mortgage-split';

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
          {pairMortgageEvents(events).map((line) =>
            line.kind === 'pair' ? (
              <PairRow
                key={line.interest.event_uuid}
                line={line}
                {...(onReverse ? { onReverse } : {})}
              />
            ) : (
              <TransactionRow
                key={line.event.event_uuid}
                event={line.event}
                {...(onReverse ? { onReverse } : {})}
              />
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

/** One payment, visually: the pair the engine split, summed on its line
 * with the split stated beneath. It reverses as a payment — both events —
 * because half a reversed mortgage payment is not a position anyone took;
 * once either member is struck the two stand alone again in the register. */
function PairRow({
  line,
  onReverse,
}: {
  line: { total: string; interest: LedgerEventOut; principal: LedgerEventOut };
  onReverse?: (eventUuid: string) => void;
}) {
  const { interest, principal } = line;
  return (
    <tr>
      <td>{formatDate(interest.occurred_on)}</td>
      <td>
        <span className="pill">Mortgage Payment</span>
      </td>
      <td>
        <span>{interest.memo ?? '—'}</span>
        {interest.counterparty ? <div className="faint">{interest.counterparty}</div> : null}
        <div className="faint">
          interest {formatMoney(interest.amount)} · principal {formatMoney(principal.amount)}
        </div>
      </td>
      <td
        style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
        className={Number(line.total) < 0 ? 'muted' : ''}
      >
        {formatMoney(line.total)}
      </td>
      <td>
        {onReverse ? (
          <button
            className="button button--quiet"
            type="button"
            onClick={() => {
              onReverse(interest.event_uuid);
              onReverse(principal.event_uuid);
            }}
          >
            Reverse
          </button>
        ) : null}
      </td>
    </tr>
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
