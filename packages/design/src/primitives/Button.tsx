import type { ButtonHTMLAttributes } from 'react';
import { cx } from '../cx.js';

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Danger is madder — the confirm step of a destructive act, never the first click. */
  variant?: 'solid' | 'quiet' | 'danger';
};

const VARIANT_CLASS = {
  solid: 'button',
  quiet: 'button button--quiet',
  danger: 'button button--danger',
} as const;

export function Button({ variant = 'solid', className, type, ...rest }: ButtonProps) {
  return (
    <button type={type ?? 'button'} className={cx(VARIANT_CLASS[variant], className)} {...rest} />
  );
}
