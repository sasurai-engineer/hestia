'use client';

import { Button, CitationChip, Pill, type PillTone } from '@hestia/design';
import { useState } from 'react';
import type { DecisionIn, NoticeIn, ScreeningOut } from '../lib/api';
import { formatDate } from '../lib/format';

/**
 * Applicant screening: the record, the duty, and the checklist. The server
 * decides when an adverse-action notice is owed and what the letter must
 * contain — the browser displays what it is told; it does not know the law.
 * A decision is recorded once: it is the reason someone did or did not get
 * a home, and re-deciding it would rewrite that record.
 */
const DECISION_TONE: Record<string, PillTone> = {
  pending: 'neutral',
  approved: 'ok',
  conditional: 'flag',
  denied: 'flag',
  withdrawn: 'skipped',
};

const DECISIONS = ['approved', 'conditional', 'denied', 'withdrawn'] as const;

function DecisionForm({
  screening,
  onDecide,
}: {
  screening: ScreeningOut;
  onDecide: (screeningId: string, body: DecisionIn) => void;
}) {
  const [decision, setDecision] = useState<DecisionIn['decision']>('approved');
  const [decidedOn, setDecidedOn] = useState('');
  const [basis, setBasis] = useState('');
  const [consumerReport, setConsumerReport] = useState(false);
  return (
    <form
      className="form-row"
      onSubmit={(event) => {
        event.preventDefault();
        onDecide(screening.id, {
          decision,
          decided_on: decidedOn === '' ? null : decidedOn,
          decision_basis: basis === '' ? null : basis,
          based_on_consumer_report: consumerReport,
        });
      }}
    >
      <div className="field">
        <label htmlFor={`sc-decision-${screening.id}`}>Decision</label>
        <select
          id={`sc-decision-${screening.id}`}
          value={decision}
          onChange={(event) => {
            setDecision(event.target.value as DecisionIn['decision']);
          }}
        >
          {DECISIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`sc-decided-${screening.id}`}>Decided on</label>
        <input
          id={`sc-decided-${screening.id}`}
          type="date"
          value={decidedOn}
          onChange={(event) => {
            setDecidedOn(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={`sc-basis-${screening.id}`}>Basis</label>
        <input
          id={`sc-basis-${screening.id}`}
          value={basis}
          onChange={(event) => {
            setBasis(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={`sc-report-${screening.id}`}>
          <input
            id={`sc-report-${screening.id}`}
            type="checkbox"
            checked={consumerReport}
            onChange={(event) => {
              setConsumerReport(event.target.checked);
            }}
          />{' '}
          Based on a consumer report
        </label>
      </div>
      <Button type="submit">Record the decision</Button>
    </form>
  );
}

function NoticeBlock({
  screening,
  onNotice,
}: {
  screening: ScreeningOut;
  onNotice: (screeningId: string, body: NoticeIn) => void;
}) {
  const [sentOn, setSentOn] = useState('');
  if (!screening.adverse_action_required) {
    return null;
  }
  if (screening.adverse_action_sent_on !== null) {
    return (
      <p>
        <Pill tone="ok">notice sent {formatDate(screening.adverse_action_sent_on)}</Pill>
      </p>
    );
  }
  return (
    <div className="screening__notice">
      <p>
        <Pill tone="flag">adverse-action notice owed</Pill>{' '}
        {screening.citation ? <CitationChip cite={screening.citation} /> : null}
      </p>
      <ul>
        {screening.notice_contents.map((item) => (
          <li key={item['citation']}>
            {item['requirement']}{' '}
            {item['citation'] ? <CitationChip cite={item['citation']} /> : null}
          </li>
        ))}
      </ul>
      <form
        className="form-row"
        onSubmit={(event) => {
          event.preventDefault();
          onNotice(screening.id, { sent_on: sentOn === '' ? null : sentOn });
        }}
      >
        <div className="field">
          <label htmlFor={`sc-sent-${screening.id}`}>Sent on</label>
          <input
            id={`sc-sent-${screening.id}`}
            type="date"
            value={sentOn}
            onChange={(event) => {
              setSentOn(event.target.value);
            }}
          />
        </div>
        <Button type="submit">Record the notice</Button>
      </form>
    </div>
  );
}

type ScreeningPanelProps = {
  screenings: readonly ScreeningOut[];
  onDecide: (screeningId: string, body: DecisionIn) => void;
  onNotice: (screeningId: string, body: NoticeIn) => void;
};

export function ScreeningPanel({ screenings, onDecide, onNotice }: ScreeningPanelProps) {
  if (screenings.length === 0) {
    return null;
  }
  return (
    <div className="screening">
      {screenings.map((screening) => (
        <div className="card" key={screening.id}>
          <p>
            <strong>{screening.resident_name}</strong>
            {screening.unit_label ? ` · ${screening.unit_label}` : ''} · {screening.provider} ·
            requested {formatDate(screening.requested_on)}{' '}
            <Pill tone={DECISION_TONE[screening.decision] ?? 'neutral'}>{screening.decision}</Pill>
          </p>
          {screening.decision === 'pending' ? (
            <DecisionForm screening={screening} onDecide={onDecide} />
          ) : (
            <p className="muted">
              {screening.decided_on ? `Decided ${formatDate(screening.decided_on)}` : 'Decided'}
              {screening.decision_basis ? ` — ${screening.decision_basis}` : ''}
              {screening.based_on_consumer_report ? ' · based on a consumer report' : ''}
            </p>
          )}
          <NoticeBlock screening={screening} onNotice={onNotice} />
        </div>
      ))}
    </div>
  );
}
