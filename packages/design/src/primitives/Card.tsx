import type { HTMLAttributes } from 'react';
import { cx } from '../cx.js';

type CardProps = HTMLAttributes<HTMLDivElement> & {
  /** Flush cards let a table or chart run to the paper's edge. */
  flush?: boolean;
};

export function Card({ flush = false, className, ...rest }: CardProps) {
  return <div className={cx('card', flush && 'card--flush', className)} {...rest} />;
}
