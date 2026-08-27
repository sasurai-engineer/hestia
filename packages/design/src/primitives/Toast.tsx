import type { ReactNode } from 'react';

type ToastProps = {
  tone?: 'info' | 'failed';
  onDismiss?: () => void;
  children: ReactNode;
};

export function Toast({ tone = 'info', onDismiss, children }: ToastProps) {
  return (
    <div role="status" className={tone === 'failed' ? 'toast toast--failed' : 'toast'}>
      <span>{children}</span>
      {onDismiss === undefined ? null : (
        <button
          type="button"
          className="toast__dismiss"
          aria-label="Dismiss notification"
          onClick={onDismiss}
        >
          ×
        </button>
      )}
    </div>
  );
}
