'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api,
  type DocumentKind,
  type DocumentStatus,
  type DocumentSummary,
  type PropertySummary,
} from '../../lib/api';
import { formatDate, localIsoDate, titleCase } from '../../lib/format';

// FROM THE CONTRACT, never hand-copied: a kind the server gains appears here
// the moment `gen:api` runs, and one it loses stops being offerable.
const KINDS: DocumentKind[] = [
  'settlement_statement',
  'deed',
  'lease',
  'lease_amendment',
  'insurance_declaration',
  'mortgage_note',
  'mortgage_statement',
  'assessment_notice',
  'tax_bill',
  'inspection_report',
  'appraisal',
  'permit',
  'invoice',
  'receipt',
  'estoppel',
  'photo',
  'other',
];

const STATUSES: DocumentStatus[] = [
  'pending',
  'extracted',
  'needs_review',
  'confirmed',
  'rejected',
  'applied',
];

export default function DocumentsPage() {
  const [rows, setRows] = useState<DocumentSummary[]>([]);
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | ''>('');
  const [kind, setKind] = useState<DocumentKind>('settlement_statement');
  const [propertyId, setPropertyId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only the latest request may paint: flipping the status filter twice
  // must not let the slower response overwrite the newer one.
  const fetchSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++fetchSeq.current;
    try {
      const [documents, props] = await Promise.all([
        api.listDocuments(statusFilter || undefined),
        api.listProperties(),
      ]);
      if (seq !== fetchSeq.current) return;
      setRows(documents);
      setProperties(props);
      setError(null);
    } catch (caught) {
      if (seq !== fetchSeq.current) return;
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const upload = async () => {
    if (!file || propertyId === '') return;
    setBusy(true);
    setError(null);
    try {
      const detail = await api.uploadDocument(kind, propertyId, file);
      setFile(null);
      window.location.assign(`/documents/${detail.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="page-title">Documents</h1>
      <p className="page-subtitle">
        Drop the paper in; the machine reads it, you ratify every value, and only then does anything
        touch the books. The original stays on file behind every number it produced.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void upload();
        }}
      >
        <div className="form-row">
          <div className="field">
            <label htmlFor="doc-kind">Kind</label>
            <select
              id="doc-kind"
              value={kind}
              onChange={(event) => {
                setKind(event.target.value as DocumentKind);
              }}
            >
              {KINDS.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="doc-property">Property</label>
            <select
              id="doc-property"
              required
              value={propertyId}
              onChange={(event) => {
                setPropertyId(event.target.value);
              }}
            >
              <option value="">choose…</option>
              {properties.map((property) => (
                <option key={property.id} value={property.id}>
                  {property.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="doc-file">Document (.pdf / .txt)</label>
            <input
              id="doc-file"
              type="file"
              required
              accept=".pdf,.txt"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
              }}
            />
          </div>
        </div>
        <button className="button" type="submit" disabled={busy || !file || propertyId === ''}>
          {busy ? 'Uploading…' : 'Upload'}
        </button>
      </form>

      <section className="section">
        <div className="form-row">
          <div className="field">
            <label htmlFor="doc-status">Status</label>
            <select
              id="doc-status"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as DocumentStatus | '');
              }}
            >
              <option value="">all</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </div>
        </div>
        {rows.length === 0 ? (
          <p className="muted">No documents yet — the inbox starts honest and empty.</p>
        ) : (
          <div className="card card--flush">
            <table className="table">
              <thead>
                <tr>
                  <th>Uploaded</th>
                  <th>Document</th>
                  <th>Kind</th>
                  <th>Property</th>
                  <th style={{ textAlign: 'right' }}>Open reviews</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{formatDate(localIsoDate(new Date(row.uploaded_at)))}</td>
                    <td>
                      <Link href={`/documents/${row.id}`}>{row.filename}</Link>
                    </td>
                    <td>{titleCase(row.kind)}</td>
                    <td>{row.property_labels.join(', ') || '—'}</td>
                    <td style={{ textAlign: 'right' }}>{row.open_review_count}</td>
                    <td>
                      <span className={row.status === 'needs_review' ? 'pill pill--flag' : 'pill'}>
                        {titleCase(row.status)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
