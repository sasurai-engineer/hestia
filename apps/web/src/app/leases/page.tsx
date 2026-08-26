'use client';

import { useCallback, useEffect, useState } from 'react';
import { formatMoney } from '../../components/TransactionsTable';
import { api, type LeaseSummary, type PropertySummary } from '../../lib/api';
import { formatDate } from '../../lib/format';

export default function LeasesPage() {
  const [leases, setLeases] = useState<LeaseSummary[] | null>(null);
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [propertyId, setPropertyId] = useState('');
  const [unitLabel, setUnitLabel] = useState('A');
  const [residentName, setResidentName] = useState('');
  const [startsOn, setStartsOn] = useState('');
  const [endsOn, setEndsOn] = useState('');
  const [rent, setRent] = useState('');
  const [deposit, setDeposit] = useState('');

  const load = useCallback(async () => {
    try {
      const [list, props] = await Promise.all([api.listLeases(), api.listProperties()]);
      setLeases(list);
      setProperties(props);
      setPropertyId((current) => current || (props[0]?.id ?? ''));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const unit = await api.createUnit({ property_id: propertyId, label: unitLabel });
      const residentIds: string[] = [];
      if (residentName.trim() !== '') {
        const resident = await api.createResident({ full_name: residentName.trim() });
        residentIds.push(resident.id);
      }
      await api.createLease({
        unit_id: unit.id,
        starts_on: startsOn,
        ends_on: endsOn || null,
        rent,
        rent_due_day: 1,
        security_deposit: deposit || '0',
        escalation: 'none',
        status: 'active',
        resident_ids: residentIds,
      });
      await api.sweepRentCharges();
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="page-title">Leases</h1>
      <p className="page-subtitle">
        Charges are expectations; receipts are money that moved. The monthly sweep bills every
        active lease exactly once, and late fees exist only where a cited rule authorizes them.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      {leases !== null && leases.length > 0 ? (
        <div className="card card--flush">
          <table className="table">
            <thead>
              <tr>
                <th>Property / Unit</th>
                <th>Residents</th>
                <th>Term</th>
                <th style={{ textAlign: 'right' }}>Rent</th>
                <th style={{ textAlign: 'right' }}>Balance due</th>
              </tr>
            </thead>
            <tbody>
              {leases.map((lease) => (
                <tr key={lease.id}>
                  <td>
                    <a href={`/lease/${lease.id}`}>
                      <strong>
                        {lease.property_label} · {lease.unit_label}
                      </strong>
                    </a>{' '}
                    <span className="pill">{lease.status.replaceAll('_', ' ')}</span>
                  </td>
                  <td>{lease.residents.join(', ') || '—'}</td>
                  <td className="muted">
                    {formatDate(lease.starts_on)} –{' '}
                    {lease.ends_on ? formatDate(lease.ends_on) : 'open'}
                  </td>
                  <td style={{ textAlign: 'right' }}>{formatMoney(lease.rent)}</td>
                  <td
                    style={{ textAlign: 'right' }}
                    className={Number(lease.balance_due) > 0 ? 'error-note' : 'muted'}
                  >
                    {formatMoney(lease.balance_due)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : leases !== null ? (
        <div className="empty-state">No leases yet — add the first one below.</div>
      ) : (
        <p className="muted">Loading…</p>
      )}

      <section className="section">
        <h2 className="section__title">Add a lease</h2>
        <form
          className="card"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <div className="form-row">
            <div className="field">
              <label htmlFor="ls-property">Property</label>
              <select
                id="ls-property"
                value={propertyId}
                onChange={(e) => {
                  setPropertyId(e.target.value);
                }}
              >
                {properties.map((property) => (
                  <option key={property.id} value={property.id}>
                    {property.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="ls-unit">Unit label</label>
              <input
                id="ls-unit"
                required
                value={unitLabel}
                onChange={(e) => {
                  setUnitLabel(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="ls-resident">Resident (optional)</label>
              <input
                id="ls-resident"
                value={residentName}
                onChange={(e) => {
                  setResidentName(e.target.value);
                }}
              />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label htmlFor="ls-start">Starts</label>
              <input
                id="ls-start"
                type="date"
                required
                value={startsOn}
                onChange={(e) => {
                  setStartsOn(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="ls-end">Ends (blank = month-to-month)</label>
              <input
                id="ls-end"
                type="date"
                value={endsOn}
                onChange={(e) => {
                  setEndsOn(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="ls-rent">Monthly rent</label>
              <input
                id="ls-rent"
                required
                inputMode="decimal"
                value={rent}
                onChange={(e) => {
                  setRent(e.target.value);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="ls-deposit">Security deposit</label>
              <input
                id="ls-deposit"
                inputMode="decimal"
                value={deposit}
                onChange={(e) => {
                  setDeposit(e.target.value);
                }}
              />
            </div>
          </div>
          <button className="button" type="submit" disabled={busy}>
            {busy ? 'Adding…' : 'Add lease & bill this month'}
          </button>
        </form>
      </section>
    </>
  );
}
