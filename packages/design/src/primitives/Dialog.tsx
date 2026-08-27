import { type ReactNode, useEffect, useRef } from 'react';
import { cx } from '../cx.js';
import { syncDialog } from './dom.js';

/**
 * A native <dialog>, driven declaratively. The platform supplies the focus
 * trap, the escape key, and the top layer — a hand-rolled overlay would
 * reimplement all three, worse.
 */
type DialogProps = {
  open: boolean;
  onClose: () => void;
  label: string;
  className?: string;
  children: ReactNode;
};

export function Dialog({ open, onClose, label, className, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    syncDialog(ref.current, open);
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={cx('dialog', className)}
      aria-label={label}
      onClose={onClose}
      onCancel={onClose}
    >
      {open ? children : null}
    </dialog>
  );
}
