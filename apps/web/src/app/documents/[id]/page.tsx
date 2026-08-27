'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { DocumentFieldsTable, type FieldDecision } from '../../../components/DocumentFieldsTable';
import { formatMoney } from '../../../components/TransactionsTable';
import {
  type ApplySuggestion,
  api,
  type DocumentApplyResult,
  type DocumentDetail,
} from '../../../lib/api';
import { titleCase } from '../../../lib/format';

function ApplyPanel({
  suggestion,
  status,
  busy,
  onApply,
}: {
  suggestion: ApplySuggestion;
  status: string;
  busy: boolean;
  onApply: (body: { land_value: string; personal_property: string; method: string }) => void;
}) {
  const [landValue, setLandValue] = useState('');
  const [personalProperty, setPersonalProperty] = useState('0.00');
  const [manualMethod, setManualMethod] = useState('');
  // WHERE the land figure came from, not a copy of it: a citation stored as
  // free text goes stale the moment the figure beneath it changes, and then
  // the recorded method names a ratio that does not produce the recorded
  // number. Deriving both at click time keeps them one fact.
  const [fromSuggestion, setFromSuggestion] = useState(false);
  const suggested = suggestion.suggested_land_value ?? '';
  const effectiveLand = fromSuggestion ? suggested : landValue;
  const effectiveMethod = fromSuggestion
    ? `assessor ratio: ${suggestion.suggestion_citation ?? ''}`
    : manualMethod;
  return (
    <section className="section">
      <h2 className="section__title">Apply to the books</h2>
      <div className="card">
        <p>
          Total basis <strong>{formatMoney(suggestion.total_basis)}</strong>{' '}
          <span className="muted">(sale price + capitalizable closing costs)</span>
        </p>
        {suggestion.address_matches === false ? (
          <p className="error-note">
            The statement&apos;s address does not mention this property&apos;s street — confirm the
            right property is linked before applying.
          </p>
        ) : null}
        {suggestion.suggested_land_value ? (
          <p className="citation">
            Suggested land value {formatMoney(suggestion.suggested_land_value)} —{' '}
            {suggestion.suggestion_citation}{' '}
            <button
              className="button button--small"
              type="button"
              onClick={() => {
                setFromSuggestion(true);
              }}
            >
              Use suggestion
            </button>
          </p>
        ) : (
          <p className="muted">
            No assessment on file to suggest a land split — enter the allocation and its defensible
            method.
          </p>
        )}
        <div className="form-row">
          <div className="field">
            <label htmlFor="apply-land">Land value</label>
            <input
              id="apply-land"
              required
              value={effectiveLand}
              onChange={(event) => {
                // Any hand edit drops the citation with the number it cited.
                setFromSuggestion(false);
                setLandValue(event.target.value);
              }}
            />
          </div>
          <div className="field">
            <label htmlFor="apply-personal">Personal property</label>
            <input
              id="apply-personal"
              value={personalProperty}
              onChange={(event) => {
                setPersonalProperty(event.target.value);
              }}
            />
          </div>
          <div className="field">
            <label htmlFor="apply-method">Allocation method</label>
            <input
              id="apply-method"
              placeholder="how the split was arrived at"
              readOnly={fromSuggestion}
              value={effectiveMethod}
              onChange={(event) => {
                setManualMethod(event.target.value);
              }}
            />
          </div>
        </div>
        <button
          className="button"
          type="button"
          disabled={busy || status !== 'confirmed' || effectiveLand === ''}
          onClick={() => {
            onApply({
              land_value: effectiveLand || '0.00',
              personal_property: personalProperty || '0.00',
              method:
                effectiveMethod.trim() !== ''
                  ? effectiveMethod.trim()
                  : 'owner allocation at apply',
            });
          }}
        >
          {status === 'applied'
            ? 'Applied'
            : status === 'confirmed'
              ? 'Apply'
              : 'Ratify every required field first'}
        </button>
      </div>
    </section>
  );
}

export default function DocumentReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState<DocumentApplyResult | null>(null);

  const load = useCallback(async () => {
    try {
      setDetail(await api.documentDetail(id));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!detail) return <p className="muted">{error ?? 'Loading…'}</p>;

  const decide = async (decision: FieldDecision) => {
    setBusy(true);
    setError(null);
    try {
      setDetail(
        await api.reviewDocumentField(id, {
          field_path: decision.fieldPath,
          action: decision.action,
          value: decision.value ?? null,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const reExtract = async () => {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.reExtractDocument(id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const apply = async (body: { land_value: string; personal_property: string; method: string }) => {
    setBusy(true);
    setError(null);
    try {
      setApplied(await api.applyDocument(id, body));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="page-title">{detail.filename}</h1>
      <p className="page-subtitle">
        {titleCase(detail.kind)} · {detail.property_labels.join(', ') || 'no property'} ·{' '}
        <span className={detail.status === 'needs_review' ? 'pill pill--flag' : 'pill'}>
          {titleCase(detail.status)}
        </span>{' '}
        {detail.has_content ? (
          <a href={api.documentContentUrl(id)} target="_blank" rel="noreferrer">
            original document
          </a>
        ) : null}
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <section className="section">
        <h2 className="section__title">Extracted fields</h2>
        <DocumentFieldsTable
          fields={detail.fields}
          disabled={busy || detail.status === 'applied'}
          onDecision={(decision) => {
            void decide(decision);
          }}
        />
        {detail.status !== 'applied' ? (
          <p>
            <button
              className="button"
              type="button"
              disabled={busy}
              onClick={() => void reExtract()}
            >
              Re-run extraction
            </button>{' '}
            <span className="faint">Ratified values survive a re-run.</span>
          </p>
        ) : null}
      </section>

      {detail.suggestion ? (
        <ApplyPanel
          suggestion={detail.suggestion}
          status={detail.status}
          busy={busy}
          onApply={(body) => {
            void apply(body);
          }}
        />
      ) : null}

      {applied ? (
        <section className="section">
          <h2 className="section__title">Applied</h2>
          <div className="card">
            <p>
              Basis {formatMoney(applied.total_basis)} = land {formatMoney(applied.land_value)} +
              improvements {formatMoney(applied.improvement_value)}
              {Number(applied.personal_property) > 0
                ? ` + personal property ${formatMoney(applied.personal_property)}`
                : ''}{' '}
              · ledger event recorded with this document as its source.
            </p>
            {applied.notes.map((note) => (
              <p key={note} className="muted">
                {note}
              </p>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}
