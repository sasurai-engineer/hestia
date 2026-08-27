import type { TableHTMLAttributes } from 'react';
import { cx } from '../cx.js';

type LedgerTableProps = TableHTMLAttributes<HTMLTableElement> & {
  /** Compact tightens the rows for dense registers; the figures stay tabular ink. */
  density?: 'regular' | 'compact';
};

export function LedgerTable({ density = 'regular', className, ...rest }: LedgerTableProps) {
  return <table className={cx('ledger-table', className)} data-density={density} {...rest} />;
}
