'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { formatMoney } from '../../../components/TransactionsTable';
import { api, type CompletionOut, type WorkOrderOut, type WorkOrderStatus } from '../../../lib/api';
import { formatDate, localIsoDate, titleCase } from '../../../lib/format';

/** The completion form: resolution, money, and the question the money raises. */
function CompletionForm({
  order,
  busy,
  onComplete,
}: {
  order: WorkOrderOut;
  busy: boolean;
  onComplete: (body: {
    completed_on: string;
    resolution: 'repaired' | 'replaced' | 'no_action';
    resolution_note: string | null;
    cost: {
      amount: string;
      relation: 'invoice';
      is_capital: boolean | null;
      capitalisation_rationale: string | null;
    } | null;
  }) => void;
}) {
  const [completedOn, setCompletedOn] = useState(localIsoDate(new Date()));
  const [resolution, setResolution] = useState<'repaired' | 'replaced' | 'no_action'>('repaired');
  const [note, setNote] = useState('');
  const [amount, setAmount] = useState('');
  const [bar, setBar] = useState<'unanswered' | 'capital' | 'expense'>('unanswered');
  const [rationale, setRationale] = useState('');

  const replacing = resolution === 'replaced';
  return (
    <div className="card">
      <div className="form-row">
        <div className="field">
          <label htmlFor="wo-completed">Completed on</label>
          <input
            id="wo-completed"
            type="date"
            value={completedOn}
            onChange={(event) => {
              setCompletedOn(event.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="wo-resolution">Resolution</label>
          <select
            id="wo-resolution"
            value={resolution}
            onChange={(event) => {
              setResolution(event.target.value as 'repaired' | 'replaced' | 'no_action');
            }}
          >
            <option value="repaired">Repaired</option>
            <option value="replaced">Replaced</option>
            <option value="no_action">No action</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="wo-note">Note</label>
          <input
            id="wo-note"
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </div>
      </div>
      {replacing && order.component_id === null ? (
        <p className="error-note">
          A replacement has to name what it replaced — attach the component to this job first.
        </p>
      ) : null}
      {replacing && order.component_id !== null ? (
        <p className="citation">
          {order.component_label} will be retired as of this date and a new one installed with a
          known install date — the capital forecast stops guessing about it.
        </p>
      ) : null}
      <div className="form-row">
        <div className="field">
          <label htmlFor="wo-amount">Invoice amount</label>
          <input
            id="wo-amount"
            placeholder="leave blank if nothing was billed"
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="wo-bar">Repair or improvement?</label>
          <select
            id="wo-bar"
            value={bar}
            onChange={(event) => {
              setBar(event.target.value as 'unanswered' | 'capital' | 'expense');
            }}
          >
            <option value="unanswered">not decided yet</option>
            <option value="expense">deductible repair</option>
            <option value="capital">capital improvement</option>
          </select>
        </div>
        {bar === 'capital' ? (
          <div className="field">
            <label htmlFor="wo-rationale">Why it is capital</label>
            <input
              id="wo-rationale"
              required
              placeholder="betterment, adaptation or restoration"
              value={rationale}
              onChange={(event) => {
                setRationale(event.target.value);
              }}
            />
          </div>
        ) : null}
      </div>
      <p className="faint">
        Treas. Reg. 1.263(a)-3: replacing a major component of a building system is a restoration
        and is capitalised. Leaving the question undecided is allowed — Schedule E will ask again.
      </p>
      <button
        className="button"
        type="button"
        disabled={busy || (bar === 'capital' && rationale.trim() === '')}
        onClick={() => {
          onComplete({
            completed_on: completedOn,
            resolution,
            resolution_note: note.trim() === '' ? null : note.trim(),
            cost:
              amount.trim() === ''
                ? null
                : {
                    amount: amount.trim(),
                    relation: 'invoice' as const,
                    is_capital: bar === 'unanswered' ? null : bar === 'capital',
                    capitalisation_rationale: bar === 'capital' ? rationale.trim() : null,
                  },
          });
        }}
      >
        {busy ? 'Completing…' : 'Complete the job'}
      </button>
    </div>
  );
}

function WorkOrderHeader({ order }: { order: WorkOrderOut }) {
  return (
    <>
      <h1 className="page-title">{order.summary}</h1>
      <p className="page-subtitle">
        {order.property_label}
        {order.unit_label ? ` · ${order.unit_label}` : ''} ·{' '}
        <span className={order.priority === 'emergency' ? 'pill pill--flag' : 'pill'}>
          {order.priority}
        </span>{' '}
        <span className="pill">{titleCase(order.status)}</span> · reported{' '}
        {formatDate(order.reported_on)}
        {order.vendor_name ? ` · ${order.vendor_name}` : ''}
      </p>
    </>
  );
}

function CompletedPanel({
  order,
  completion,
}: {
  order: WorkOrderOut;
  completion: CompletionOut | null;
}) {
  return (
    <section className="section">
      <h2 className="section__title">Completed</h2>
      <div className="card">
        <p>
          {titleCase(order.resolution ?? '')} on{' '}
          {order.completed_on ? formatDate(order.completed_on) : '—'}
          {order.resolution_note ? ` — ${order.resolution_note}` : ''}
        </p>
        {completion?.capitalisation_citation ? (
          <p className="citation">{completion.capitalisation_citation}</p>
        ) : null}
        {completion?.installed_component_id ? (
          <p className="muted">
            The old component was retired and a new one installed with a known date.
          </p>
        ) : null}
      </div>
    </section>
  );
}

function CostsTable({ order }: { order: WorkOrderOut }) {
  return (
    <>
      {order.costs.length === 0 ? (
        <p className="muted">Nothing posted against this job yet.</p>
      ) : (
        <div className="card card--flush">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Kind</th>
                <th style={{ textAlign: 'right' }}>Amount</th>
                <th>Treatment</th>
              </tr>
            </thead>
            <tbody>
              {order.costs.map((cost) => (
                <tr key={cost.ledger_event_uuid}>
                  <td>{formatDate(cost.occurred_on)}</td>
                  <td>{titleCase(cost.relation)}</td>
                  <td
                    style={{
                      textAlign: 'right',
                      textDecoration: cost.reversed ? 'line-through' : undefined,
                    }}
                  >
                    {formatMoney(cost.amount)}
                  </td>
                  <td>
                    {cost.is_capital === null
                      ? 'undecided'
                      : cost.is_capital
                        ? 'capital'
                        : 'repair'}
                    {cost.reversed ? ' · reversed' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p>
        Net cost <strong>{formatMoney(order.net_cost)}</strong>
      </p>
    </>
  );
}

export default function WorkOrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [order, setOrder] = useState<WorkOrderOut | null>(null);
  const [completion, setCompletion] = useState<CompletionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setOrder(await api.readWorkOrder(id));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!order) return <p className="muted">{error ?? 'Loading…'}</p>;

  const move = async (status: WorkOrderStatus) => {
    setBusy(true);
    setError(null);
    try {
      const scheduled = status === 'scheduled' ? { scheduled_for: localIsoDate(new Date()) } : {};
      const cancelled =
        status === 'cancelled' ? { cancelled_reason: 'closed from the work order page' } : {};
      setOrder(
        await api.transitionWorkOrder(id, {
          status: status as 'triaged' | 'scheduled' | 'in_progress' | 'cancelled',
          scheduled_for: null,
          vendor_id: null,
          cancelled_reason: null,
          ...scheduled,
          ...cancelled,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const complete = async (
    body: Parameters<Parameters<typeof CompletionForm>[0]['onComplete']>[0],
  ) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.completeWorkOrder(id, {
        ...body,
        replacement: null,
      });
      setCompletion(result);
      setOrder(result.work_order);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <WorkOrderHeader order={order} />
      {error ? <p className="error-note">{error}</p> : null}
      {order.detail ? <p>{order.detail}</p> : null}

      {order.legal_transitions.length > 0 ? (
        <p>
          {order.legal_transitions.map((status) => (
            <button
              key={status}
              className="button button--small"
              type="button"
              disabled={busy}
              style={{ marginRight: 6 }}
              onClick={() => void move(status)}
            >
              {titleCase(status)}
            </button>
          ))}
        </p>
      ) : null}

      {order.status === 'completed' ? (
        <CompletedPanel order={order} completion={completion} />
      ) : (
        <section className="section">
          <h2 className="section__title">Complete this job</h2>
          <CompletionForm
            order={order}
            busy={busy}
            onComplete={(body) => {
              void complete(body);
            }}
          />
        </section>
      )}

      <section className="section">
        <h2 className="section__title">Costs</h2>
        <CostsTable order={order} />
      </section>
    </>
  );
}
