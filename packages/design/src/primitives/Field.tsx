import type { ReactNode } from 'react';

type FieldProps = {
  label: string;
  htmlFor?: string;
  error?: string;
  children: ReactNode;
};

export function Field({ label, htmlFor, error, children }: FieldProps) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error === undefined ? null : <span className="error-note">{error}</span>}
    </div>
  );
}
