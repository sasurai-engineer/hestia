'use client';

import { useCallback, useEffect, useState } from 'react';
import { TransactionsTable } from '../../components/TransactionsTable';
import { api, type LedgerEntryIn, type LedgerRegister, type PropertySummary } from '../../lib/api';

const CATEGORIES = [
  'rent',
  'other_income',
  'late_fee',
  'deposit_received',
  'deposit_returned',
  'mortgage_interest',
  'mortgage_principal',
  'property_tax',
  'insurance',
  'repairs',
  'capital_improvement',
  'utilities',
  'management_fee',
  'hoa',
  'legal_professional',
  'advertising',
  'supplies',
  'travel',
  'acquisition_cost',
  'disposition_cost',
  'owner_contribution',
  'owner_distribution',
] as const;

const formatTotal = (amount: string): string =>
  `$${Math.abs(Number(amount)).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;

export default function TransactionsPage() {
  const [register, setRegister] = useState<LedgerRegister | null>(null);
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [propertyFilter, setPropertyFilter] = useState('');
  const [error, setError] = useState<string | null>(null);

  const [occurredOn, setOccurredOn] = useState('');
  const [category, setCategory] = useState<string>('rent');
  const [amount, setAmount] = useState('');
  const [direction, setDirection] = useState<'in' | 'out'>('in');
  const [memo, setMemo] = useState('');
  const [counterparty, setCounterparty] = useState('');
  const [propertyId, setPropertyId] = useState('');
  const [isCapital, setIsCapital] = useState(false);
  const [rationale, setRationale] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [reg, props] = await Promise.all([
        api.ledgerRegister(propertyFilter ? { propertyId: propertyFilter } : undefined),
        api.listProperties(),
      ]);
      setRegister(reg);
      setProperties(props);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [propertyFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const signed = direction === 'out' ? `-${amount}` : amount;
      const entry: LedgerEntryIn = {
        occurred_on: occurredOn,
        category: category as LedgerEntryIn['category'],
        amount: signed,
        memo: memo || null,
        counterparty: counterparty || null,
        property_id: propertyId || null,
        is_capital: isCapital ? true : null,
        capitalisation_rationale: isCapital ? rationale : null,
      };
      await api.appendLedger(entry);
      setAmount('');
      setMemo('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const reverse = async (eventUuid: string) => {
    setError(null);
    try {
      await api.reverseLedger(eventUuid);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <>
      <h1 className="page-title">Transactions</h1>
      <p className="page-subtitle">
        The ledger is append-only: a mistake is corrected by a reversal that stays on the page, so
        the tax position is reconstructible exactly as it was taken.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <div className="form-row" style={{ alignItems: 'end' }}>
        <div className="field">
          <label htmlFor="tx-filter">Property</label>
          <select
            id="tx-filter"
            value={propertyFilter}
            onChange={(e) => {
              setPropertyFilter(e.target.value);
            }}
          >
            <option value="">All properties</option>
            {properties.map((property) => (
              <option key={property.id} value={property.id}>
                {property.label}
              </option>
            ))}
          </select>
        </div>
        {register ? (
          <p className="muted">
            In {formatTotal(register.total_in)} · Out {formatTotal(register.total_out)} · Net{' '}
            <strong className={Number(register.net) < 0 ? 'error-note' : ''}>
              {Number(register.net) < 0 ? '−' : ''}
              {formatTotal(register.net)}
            </strong>
          </p>
        ) : null}
      </div>

      <section className="section">
        {register ? (
          <TransactionsTable
            events={register.events}
            onReverse={(uuid) => {
              void reverse(uuid);
            }}
          />
        ) : (
          <p className="muted">Loading…</p>
        )}
      </section>

      <section className="section">
        <h2 className="section__title">Record a transaction</h2>
        <form
          className="card"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="form-row">
            <div className="field">
              <label htmlFor="tx-date">Date</label>
              <input
                id="tx-date"
                type="date"
                required
                value={occurredOn}
                onChange={(e) => {
                  setOccurredOn(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="tx-category">Category</label>
              <select
                id="tx-category"
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value);
                }}
              >
                {CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {value.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="tx-direction">Direction</label>
              <select
                id="tx-direction"
                value={direction}
                onChange={(e) => {
                  setDirection(e.target.value as 'in' | 'out');
                }}
              >
                <option value="in">money in</option>
                <option value="out">money out</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="tx-amount">Amount</label>
              <input
                id="tx-amount"
                required
                inputMode="decimal"
                placeholder="0.00"
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="tx-property">Property</label>
              <select
                id="tx-property"
                required
                value={propertyId}
                onChange={(e) => {
                  setPropertyId(e.target.value);
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
          </div>
          <div className="form-row">
            <div className="field">
              <label htmlFor="tx-memo">Memo</label>
              <input
                id="tx-memo"
                value={memo}
                onChange={(e) => {
                  setMemo(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="tx-counterparty">Counterparty</label>
              <input
                id="tx-counterparty"
                value={counterparty}
                onChange={(e) => {
                  setCounterparty(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="tx-capital">Capital?</label>
              <select
                id="tx-capital"
                value={isCapital ? 'yes' : 'no'}
                onChange={(e) => {
                  setIsCapital(e.target.value === 'yes');
                }}
              >
                <option value="no">expense</option>
                <option value="yes">capital improvement</option>
              </select>
            </div>
            {isCapital ? (
              <div className="field">
                <label htmlFor="tx-rationale">Why capital (BAR)</label>
                <input
                  id="tx-rationale"
                  required
                  placeholder="betterment / adaptation / restoration…"
                  value={rationale}
                  onChange={(e) => {
                    setRationale(e.target.value);
                  }}
                />
              </div>
            ) : null}
          </div>
          <button className="button" type="submit" disabled={busy}>
            {busy ? 'Recording…' : 'Record'}
          </button>
        </form>
      </section>
    </>
  );
}
