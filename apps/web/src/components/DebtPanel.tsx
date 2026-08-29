'use client';

import { Button, CitationChip, Disclosure, KeyValue, Pill } from '@hestia/design';
import { rate, rateToPercentString } from '@hestia/domain';
import { useCallback, useEffect, useState } from 'react';
import { api, type DebtOut, type ScheduleOut } from '../lib/api';
import { formatDate } from '../lib/format';
import { formatMoney } from './TransactionsTable';

/**
 * The record beside the what-if: the explorer above scrubs futures, this
 * panel is what actually happened — every note with its recorded payments,
 * the engine's schedule under its citation, and a payment recorder
 * pre-filled with the engine's split for the period. A payment stating its
 * own figures records what the lender applied; one that states none takes
 * the engine's, to the cent, server-side.
 */
const KINDS = [
  'conventional_mortgage',
  'portfolio_loan',
  'dscr_loan',
  'agency_multifamily',
  'bridge',
  'hard_money',
  'heloc',
  'seller_financing',
  'private_note',
] as const;

function ScheduleTable({ schedule }: { schedule: ScheduleOut }) {
  return (
    <>
      <p>
        <CitationChip cite={schedule.citation} />{' '}
        <span className="muted">
          {formatMoney(schedule.total_interest)} of interest over the remaining term
        </span>
      </p>
      <div className="card card--flush" style={{ maxHeight: 280, overflowY: 'auto' }}>
        <table className="table">
          <thead>
            <tr>
              <th>Month</th>
              <th style={{ textAlign: 'right' }}>Payment</th>
              <th style={{ textAlign: 'right' }}>Interest</th>
              <th style={{ textAlign: 'right' }}>Principal</th>
              <th style={{ textAlign: 'right' }}>Balance</th>
            </tr>
          </thead>
          <tbody>
            {schedule.rows.map((row) => (
              <tr key={row.month}>
                <td>{row.month}</td>
                <td style={{ textAlign: 'right' }}>{formatMoney(row.payment)}</td>
                <td style={{ textAlign: 'right' }}>{formatMoney(row.interest)}</td>
                <td style={{ textAlign: 'right' }}>{formatMoney(row.principal)}</td>
                <td style={{ textAlign: 'right' }}>{formatMoney(row.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function PaymentForm({
  debt,
  amortizing,
  today,
  onRecord,
}: {
  debt: DebtOut;
  amortizing: boolean;
  today: string;
  onRecord: (debtId: string, body: Parameters<typeof api.recordDebtPayment>[1]) => void;
}) {
  const [paidOn, setPaidOn] = useState(today);
  // `null` means the operator has not touched the field, so the figure shown
  // is the engine's suggestion and travels as null — the server recomputes
  // it from paid_on and gets the same answer. A figure they typed travels
  // verbatim, because that is them stating what the lender actually applied.
  const [interest, setInterest] = useState<string | null>(null);
  const [principal, setPrincipal] = useState<string | null>(null);
  const [extraPrincipal, setExtraPrincipal] = useState('0');
  const [postToLedger, setPostToLedger] = useState(true);
  // The suggestion is fetched AS OF the date the money carries. A payment
  // dated in June is split by June's row, not by the row for the day the
  // panel happened to load (#99).
  const [suggestion, setSuggestion] = useState<ScheduleOut | null>(null);
  useEffect(() => {
    if (!amortizing || paidOn === '') return;
    api
      .debtSchedule(debt.id, paidOn)
      .then(setSuggestion)
      .catch(() => {
        setSuggestion(null);
      });
  }, [debt.id, amortizing, paidOn]);

  const stated = (value: string | null) => (value === null || value === '' ? null : value);
  const interestValue = interest ?? suggestion?.next_interest ?? '';
  const principalValue = principal ?? suggestion?.next_principal ?? '';
  return (
    <form
      className="form-row"
      onSubmit={(event) => {
        event.preventDefault();
        onRecord(debt.id, {
          paid_on: paidOn,
          interest: stated(interest),
          principal: stated(principal),
          extra_principal: extraPrincipal === '' ? '0' : extraPrincipal,
          // Escrow stays out of the v1 form; the default it means is zero.
          escrow: '0',
          post_to_ledger: postToLedger,
        });
      }}
    >
      <div className="field">
        <label htmlFor={`dp-date-${debt.id}`}>Paid on</label>
        <input
          id={`dp-date-${debt.id}`}
          type="date"
          required
          value={paidOn}
          onChange={(event) => {
            setPaidOn(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={`dp-interest-${debt.id}`}>Interest</label>
        <input
          id={`dp-interest-${debt.id}`}
          inputMode="decimal"
          value={interestValue}
          onChange={(event) => {
            setInterest(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={`dp-principal-${debt.id}`}>Principal</label>
        <input
          id={`dp-principal-${debt.id}`}
          inputMode="decimal"
          value={principalValue}
          onChange={(event) => {
            setPrincipal(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={`dp-extra-${debt.id}`}>Extra principal</label>
        <input
          id={`dp-extra-${debt.id}`}
          inputMode="decimal"
          value={extraPrincipal}
          onChange={(event) => {
            setExtraPrincipal(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={`dp-ledger-${debt.id}`}>
          <input
            id={`dp-ledger-${debt.id}`}
            type="checkbox"
            checked={postToLedger}
            onChange={(event) => {
              setPostToLedger(event.target.checked);
            }}
          />{' '}
          Post to the ledger
        </label>
      </div>
      <Button type="submit">Record the payment</Button>
    </form>
  );
}

function NoteCard({
  debt,
  today,
  onRecord,
  onPayoff,
}: {
  debt: DebtOut;
  today: string;
  onRecord: (debtId: string, body: Parameters<typeof api.recordDebtPayment>[1]) => void;
  onPayoff: (debtId: string, paidOffOn: string) => void;
}) {
  const [schedule, setSchedule] = useState<ScheduleOut | null>(null);
  const retired = debt.paid_off_on !== null;
  const amortizing = debt.scheduled_payment !== null;
  useEffect(() => {
    if (!amortizing || retired) return;
    // The schedule is a suggestion surface; the record stands without it.
    api
      .debtSchedule(debt.id)
      .then(setSchedule)
      .catch(() => {
        setSchedule(null);
      });
  }, [debt.id, amortizing, retired]);

  return (
    <div className="card">
      <p>
        <strong>{debt.lender ?? 'Unnamed lender'}</strong>{' '}
        <Pill>{debt.kind.replaceAll('_', ' ')}</Pill>{' '}
        {retired ? <Pill tone="ok">paid off {formatDate(debt.paid_off_on as string)}</Pill> : null}
      </p>
      <KeyValue
        items={[
          {
            key: 'The note',
            value: `${formatMoney(debt.original_principal)} at ${rateToPercentString(
              rate(debt.interest_rate),
            )} over ${debt.term_months} months — originated ${formatDate(debt.originated_on)}`,
          },
          {
            key: 'Scheduled payment',
            value: amortizing
              ? `${formatMoney(debt.scheduled_payment as string)}/mo`
              : `none — a ${debt.amortization.replaceAll('_', ' ')} note gets no inferred split`,
          },
          {
            key: 'Recorded',
            value: `${debt.payments_recorded} payments — ${formatMoney(
              debt.principal_paid,
            )} principal, ${formatMoney(debt.interest_paid)} interest`,
          },
        ]}
      />
      {schedule ? (
        <>
          {schedule.next_interest !== null && schedule.next_principal !== null ? (
            <p className="muted">
              Next per the engine: month {schedule.next_month} —{' '}
              {formatMoney(schedule.next_interest)} interest, {formatMoney(schedule.next_principal)}{' '}
              principal.
            </p>
          ) : null}
          <Disclosure summary="The schedule">
            <ScheduleTable schedule={schedule} />
          </Disclosure>
        </>
      ) : null}
      {retired ? null : (
        <>
          <PaymentForm debt={debt} amortizing={amortizing} today={today} onRecord={onRecord} />
          <p>
            <Button
              variant="quiet"
              type="button"
              onClick={() => {
                onPayoff(debt.id, today);
              }}
            >
              Record payoff as of {formatDate(today)}
            </Button>
          </p>
        </>
      )}
    </div>
  );
}

function EntryForm({
  onCreate,
}: {
  onCreate: (body: Parameters<typeof api.createDebt>[0]) => void;
}) {
  const [lender, setLender] = useState('');
  const [kind, setKind] = useState<(typeof KINDS)[number]>('conventional_mortgage');
  const [principal, setPrincipal] = useState('');
  const [interestRate, setInterestRate] = useState('');
  const [termMonths, setTermMonths] = useState('360');
  const [originatedOn, setOriginatedOn] = useState('');
  return (
    <form
      className="form-row"
      onSubmit={(event) => {
        event.preventDefault();
        onCreate({
          lender: lender === '' ? null : lender,
          kind,
          original_principal: principal,
          interest_rate: interestRate,
          term_months: Number(termMonths),
          originated_on: originatedOn,
          // What the form does not ask, it states as the default it means —
          // the long tail of DebtIn is deliberately out of the v1 form.
          amortization: 'fully_amortizing',
          lien_position: 1,
          is_recourse: true,
          has_due_on_sale: true,
          prepayment: 'none',
          escrows_taxes: false,
          escrows_insurance: false,
          // property_id is the panel's; it completes the body.
          property_id: '',
        });
      }}
    >
      <div className="field">
        <label htmlFor="db-lender">Lender</label>
        <input
          id="db-lender"
          value={lender}
          onChange={(event) => {
            setLender(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="db-kind">Kind</label>
        <select
          id="db-kind"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value as (typeof KINDS)[number]);
          }}
        >
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {option.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="db-principal">Original principal</label>
        <input
          id="db-principal"
          required
          inputMode="decimal"
          value={principal}
          onChange={(event) => {
            setPrincipal(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="db-rate">Annual rate (decimal, e.g. 0.0625)</label>
        <input
          id="db-rate"
          required
          inputMode="decimal"
          value={interestRate}
          onChange={(event) => {
            setInterestRate(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="db-term">Term (months)</label>
        <input
          id="db-term"
          required
          inputMode="numeric"
          value={termMonths}
          onChange={(event) => {
            setTermMonths(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="db-originated">Originated</label>
        <input
          id="db-originated"
          type="date"
          required
          value={originatedOn}
          onChange={(event) => {
            setOriginatedOn(event.target.value);
          }}
        />
      </div>
      <Button type="submit">Record the mortgage</Button>
    </form>
  );
}

type DebtPanelProps = {
  propertyId: string;
  today: string;
  onChanged?: () => void;
};

export function DebtPanel({ propertyId, today, onChanged }: DebtPanelProps) {
  const [debts, setDebts] = useState<DebtOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setDebts(await api.listDebts({ propertyId, includePaidOff: true }));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [propertyId]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      await load();
      onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <div className="debt-panel">
      {error ? <p className="error-note">{error}</p> : null}
      {debts === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          {debts.map((debt) => (
            <NoteCard
              key={debt.id}
              debt={debt}
              today={today}
              onRecord={(debtId, body) => {
                void act(() => api.recordDebtPayment(debtId, body));
              }}
              onPayoff={(debtId, paidOffOn) => {
                void act(() => api.payoffDebt(debtId, { paid_off_on: paidOffOn }));
              }}
            />
          ))}
          {debts.length === 0 ? (
            <p className="muted">No notes on record — the mortgage goes here.</p>
          ) : null}
          <div className="card">
            <strong>Record a mortgage</strong>
            <EntryForm
              onCreate={(body) => {
                void act(() => api.createDebt({ ...body, property_id: propertyId }));
              }}
            />
          </div>
        </>
      )}
    </div>
  );
}
