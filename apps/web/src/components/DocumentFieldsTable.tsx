'use client';

import { useState } from 'react';
import type { DocumentField } from '../lib/api';

/** The review verdict on one field, as the table reports it upward. */
export interface FieldDecision {
  fieldPath: string;
  action: 'accept' | 'correct' | 'reject';
  value?: string;
}

const confidenceLabel = (field: DocumentField): string => {
  if (field.reviewed_at) {
    return field.accepted_value === null ? 'rejected' : 'ratified';
  }
  if (field.raw_value === null && field.normalised_value === null) {
    return 'not found';
  }
  if (field.confidence === null || field.confidence === undefined) {
    return 'entered';
  }
  const percent = Math.round(Number(field.confidence) * 100);
  return `${String(percent)}%`;
};

const rowTone = (field: DocumentField): string => {
  if (field.reviewed_at) {
    return field.accepted_value === null ? 'pill pill--flag' : 'pill pill--ok';
  }
  return field.needs_review ? 'pill pill--flag' : 'pill';
};

/**
 * One row per registry spec: what the machine read, where, how sure it was,
 * and the three verbs of ratification. The machine reads; the human decides;
 * nothing applies un-ratified.
 */
export function DocumentFieldsTable({
  fields,
  disabled,
  onDecision,
}: {
  fields: DocumentField[];
  disabled: boolean;
  onDecision: (decision: FieldDecision) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  if (fields.length === 0) {
    return <p className="muted">Nothing is extractable for this document kind yet.</p>;
  }
  return (
    <div className="card card--flush">
      <table className="table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Machine read</th>
            <th>Effective value</th>
            <th>Status</th>
            <th aria-label="review actions" />
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => {
            const draft = drafts[field.field_path] ?? '';
            return (
              <tr key={field.field_path}>
                <td>
                  {field.label}
                  {field.required ? ' *' : ''}
                  {field.target_hint ? <div className="faint">{field.target_hint}</div> : null}
                </td>
                <td>
                  {field.raw_value ?? <span className="muted">—</span>}
                  {field.page !== null && field.page !== undefined ? (
                    <span className="faint"> (p{field.page})</span>
                  ) : null}
                </td>
                <td>{field.effective_value ?? <span className="muted">—</span>}</td>
                <td>
                  <span className={rowTone(field)}>{confidenceLabel(field)}</span>
                </td>
                <td>
                  <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                    <button
                      className="button button--small"
                      type="button"
                      disabled={disabled || field.normalised_value === null}
                      onClick={() => {
                        onDecision({ fieldPath: field.field_path, action: 'accept' });
                      }}
                    >
                      Accept
                    </button>
                    <input
                      aria-label={`Correct ${field.label}`}
                      placeholder={field.datatype}
                      value={draft}
                      disabled={disabled}
                      onChange={(event) => {
                        setDrafts({ ...drafts, [field.field_path]: event.target.value });
                      }}
                    />
                    <button
                      className="button button--small"
                      type="button"
                      disabled={disabled || draft.trim() === ''}
                      onClick={() => {
                        onDecision({
                          fieldPath: field.field_path,
                          action: 'correct',
                          value: draft.trim(),
                        });
                        setDrafts({ ...drafts, [field.field_path]: '' });
                      }}
                    >
                      Correct
                    </button>
                    <button
                      className="button button--small"
                      type="button"
                      disabled={disabled}
                      onClick={() => {
                        onDecision({ fieldPath: field.field_path, action: 'reject' });
                      }}
                    >
                      Reject
                    </button>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
