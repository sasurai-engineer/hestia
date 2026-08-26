'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { RenewalCard } from '../../../components/RenewalCard';
import { formatMoney } from '../../../components/TransactionsTable';
import { ApiError, api, type LeaseDetail, type RenewalContextOut } from '../../../lib/api';
import { formatDate, localIsoDate } from '../../../lib/format';

export default function LeasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<LeaseDetail | null>(null);
  const [context, setContext] = useState<RenewalContextOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [amount, setAmount] = useState('');
  const [occurredOn, setOccurredOn] = useState('');
  const [collecting, setCollecting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [leaseDetail, renewalContext] = await Promise.all([
        api.leaseDetail(id),
        api.renewalContext(id),
      ]);
      setDetail(leaseDetail);
      setContext(renewalContext);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!detail) return <p className="muted">{error ?? 'Loading…'}</p>;

  const receive = async () => {
    setError(null);
    try {
      const receipt = await api.recordLeaseReceipt(id, {
        occurred_on: occurredOn,
        amount,
        category: 'rent',
      });
      setNotice(
        Number(receipt.unallocated) > 0
          ? `Recorded; ${formatMoney(receipt.unallocated)} unallocated.`
          : 'Recorded and allocated.',
      );
      setAmount('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const collect = async () => {
    if (collecting) return;
    setCollecting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.collectRent(id);
      setNotice(
        `Payment request ${result.provider_ref} for ${formatMoney(result.amount)} is ` +
          'processing — the receipt posts itself when the bank settles.',
      );
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 503 || caught.status === 409)) {
        // 409: a request is already in flight — status, not failure.
        setNotice(caught.message);
      } else {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    } finally {
      setCollecting(false);
    }
  };

  const offer = async (newRent: string) => {
    setError(null);
    try {
      await api.recordRenewalOffer(id, {
        offered_on: localIsoDate(new Date()),
        offered_rent: newRent,
      });
      setNotice(
        `Renewal offered at ${formatMoney(newRent)} — outcome recording sharpens the model.`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <>
      <h1 className="page-title">
        {detail.property_label} · {detail.unit_label}
      </h1>
      <p className="page-subtitle">
        {detail.residents.join(', ') || 'No residents on record'} · {formatDate(detail.starts_on)} –{' '}
        {detail.ends_on ? formatDate(detail.ends_on) : 'month-to-month'} ·{' '}
        {formatMoney(detail.rent)}/mo · deposit {formatMoney(detail.security_deposit)}
      </p>
      {error ? <p className="error-note">{error}</p> : null}
      {notice ? <p className="citation">{notice}</p> : null}

      <p>
        <strong
          className={Number(detail.balance_due) > 0 ? 'error-note' : ''}
          style={{ fontSize: 18 }}
        >
          Balance due {formatMoney(detail.balance_due)}
        </strong>{' '}
        {Number(detail.open_credit) > 0 ? (
          <span className="pill pill--ok">credit on account {formatMoney(detail.open_credit)}</span>
        ) : null}{' '}
        <button
          className="button"
          type="button"
          disabled={collecting}
          onClick={() => void collect()}
        >
          {collecting ? 'Requesting…' : 'Collect by ACH'}
        </button>
      </p>

      <section className="section">
        <h2 className="section__title">Charges</h2>
        {detail.charges.length === 0 ? (
          <p className="muted">Nothing billed yet — the monthly sweep will.</p>
        ) : (
          <div className="card card--flush">
            <table className="table">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Kind</th>
                  <th style={{ textAlign: 'right' }}>Amount</th>
                  <th style={{ textAlign: 'right' }}>Outstanding</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {detail.charges.map((charge) => (
                  <tr key={charge.id}>
                    <td>{formatDate(charge.period_start)}</td>
                    <td>
                      {charge.kind.replaceAll('_', ' ')}
                      {charge.rule_citation ? (
                        <div className="citation">{charge.rule_citation}</div>
                      ) : null}
                      {charge.waived_reason ? (
                        <div className="faint">{charge.waived_reason}</div>
                      ) : null}
                    </td>
                    <td style={{ textAlign: 'right' }}>{formatMoney(charge.amount)}</td>
                    <td style={{ textAlign: 'right' }}>{formatMoney(charge.outstanding)}</td>
                    <td>
                      <span
                        className={
                          charge.status === 'paid'
                            ? 'pill pill--ok'
                            : charge.status === 'waived'
                              ? 'pill'
                              : 'pill pill--flag'
                        }
                      >
                        {charge.status.replaceAll('_', ' ')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="section">
        <h2 className="section__title">Record a receipt</h2>
        <form
          className="card"
          onSubmit={(event) => {
            event.preventDefault();
            void receive();
          }}
        >
          <div className="form-row">
            <div className="field">
              <label htmlFor="rc-date">Date</label>
              <input
                id="rc-date"
                type="date"
                required
                value={occurredOn}
                onChange={(e) => {
                  setOccurredOn(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="rc-amount">Amount</label>
              <input
                id="rc-amount"
                required
                inputMode="decimal"
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                }}
              />
            </div>
          </div>
          <button className="button" type="submit">
            Record receipt
          </button>
        </form>
      </section>

      {context ? (
        <section className="section">
          <h2 className="section__title">Renewal</h2>
          <RenewalCard
            context={context}
            onOffer={(newRent) => {
              void offer(newRent);
            }}
          />
        </section>
      ) : null}
    </>
  );
}
