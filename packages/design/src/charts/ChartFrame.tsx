import type { ReactNode } from 'react';
import { cx } from '../cx.js';

/**
 * The frame every chart hangs in: one viewBox, one accessible name. Charts
 * are figures, not decorations — a chart without a name does not render.
 */
type ChartFrameProps = {
  viewWidth: number;
  viewHeight: number;
  label: string;
  className?: string;
  children: ReactNode;
};

export function ChartFrame({ viewWidth, viewHeight, label, className, children }: ChartFrameProps) {
  return (
    <svg
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      role="img"
      aria-label={label}
      className={cx('chart', className)}
    >
      {children}
    </svg>
  );
}
