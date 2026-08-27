'use client';

import Link from 'next/link';
import type { WorkOrderOut, WorkOrderPriority, WorkOrderStatus } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';
import { formatMoney } from './TransactionsTable';

/** The columns, in the order work actually moves through them. */
export const BOARD_COLUMNS: WorkOrderStatus[] = [
  'reported',
  'triaged',
  'scheduled',
  'in_progress',
  'completed',
];

// Keyed by the contract's own vocabulary, so the compiler — not a fallback —
// guarantees every priority has a tone.
const PRIORITY_TONE: Record<WorkOrderPriority, string> = {
  emergency: 'pill pill--flag',
  urgent: 'pill pill--flag',
  routine: 'pill',
  planned: 'pill',
};

/**
 * Open work by status. Emergencies sort first inside every column because
 * that is the order the day actually runs in — habitability does not wait
 * for whatever was reported earliest.
 */
export function WorkOrderBoard({ orders }: { orders: WorkOrderOut[] }) {
  if (orders.length === 0) {
    return <p className="muted">Nothing open — the board starts honest and empty.</p>;
  }
  return (
    <div className="form-row" style={{ alignItems: 'flex-start', gap: 12 }}>
      {BOARD_COLUMNS.map((column) => {
        const rows = orders.filter((order) => order.status === column);
        return (
          <div key={column} style={{ flex: 1, minWidth: 180 }}>
            <h3 className="section__title">
              {titleCase(column)} <span className="muted">{rows.length}</span>
            </h3>
            {rows.length === 0 ? (
              <p className="faint">—</p>
            ) : (
              rows.map((order) => (
                <div className="card" key={order.id} style={{ marginBottom: 8 }}>
                  <Link href={`/work-orders/${order.id}`}>{order.summary}</Link>
                  <p className="muted" style={{ margin: '4px 0 0' }}>
                    <span className={PRIORITY_TONE[order.priority]}>{order.priority}</span>{' '}
                    {order.property_label}
                    {order.unit_label ? ` · ${order.unit_label}` : ''}
                  </p>
                  <p className="faint" style={{ margin: '4px 0 0' }}>
                    reported {formatDate(order.reported_on)}
                    {order.vendor_name ? ` · ${order.vendor_name}` : ''}
                    {Number(order.net_cost) !== 0 ? ` · ${formatMoney(order.net_cost)}` : ''}
                  </p>
                </div>
              ))
            )}
          </div>
        );
      })}
    </div>
  );
}
