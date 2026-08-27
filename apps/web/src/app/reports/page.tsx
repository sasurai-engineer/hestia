'use client';

import { useCallback, useEffect, useState } from 'react';
import { ScheduleEView } from '../../components/ScheduleEView';
import { formatMoney } from '../../components/TransactionsTable';
import { api, type PropertySummary, type RentRollRow, type ScheduleEReport } from '../../lib/api';
import { formatDate } from '../../lib/format';

export default function ReportsPage() {
  const [rentRoll, setRentRoll] = useState<RentRollRow[] | null>(null);
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [propertyId, setPropertyId] = useState('');
  const [taxYear, setTaxYear] = useState(new Date().getFullYear());
  const [report, setReport] = useState<ScheduleEReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.rentRoll(), api.listProperties()])
      .then(([roll, list]) => {
        setRentRoll(roll);
        setProperties(list);
        setPropertyId(list[0]?.id ?? '');
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      });
  }, []);

  const load = useCallback(async () => {
    if (!propertyId) return;
    try {
      setReport(await api.scheduleE(propertyId, taxYear));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [propertyId, taxYear]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <h1 className="page-title">Reports</h1>
      <p className="page-subtitle">
        The ledger rolled up with its authorities attached — Schedule E per property, and the
        portfolio rent roll.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <section className="section">
        <h2 className="section__title">Rent roll</h2>
        {rentRoll === null ? (
          <p className="muted">Loading…</p>
        ) : rentRoll.length === 0 ? (
          <p className="muted">No active leases on record yet.</p>
        ) : (
          <div className="card card--flush">
            <table className="table">
              <thead>
                <tr>
                  <th>Property</th>
                  <th>Unit</th>
                  <th>Residents</th>
                  <th style={{ textAlign: 'right' }}>Rent</th>
                  <th>Term</th>
                </tr>
              </thead>
              <tbody>
                {rentRoll.map((row) => (
                  <tr key={`${row.property_label}-${row.unit_label}`}>
                    <td>{row.property_label}</td>
                    <td>{row.unit_label}</td>
                    <td>{row.residents.join(', ') || '—'}</td>
                    <td style={{ textAlign: 'right' }}>{formatMoney(row.rent)}</td>
                    <td className="muted">
                      {formatDate(row.starts_on)} –{' '}
                      {row.ends_on ? formatDate(row.ends_on) : 'month-to-month'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="section">
        <h2 className="section__title">Schedule E</h2>
        <div className="form-row">
          <div className="field">
            <label htmlFor="rep-property">Property</label>
            <select
              id="rep-property"
              value={propertyId}
              onChange={(event) => {
                setPropertyId(event.target.value);
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
            <label htmlFor="rep-year">Tax year</label>
            <input
              id="rep-year"
              inputMode="numeric"
              value={taxYear}
              onChange={(event) => {
                const year = Number(event.target.value);
                if (Number.isInteger(year)) setTaxYear(year);
              }}
            />
          </div>
        </div>
        {report && report.property_id === propertyId ? (
          <ScheduleEView report={report} />
        ) : (
          <p className="muted">Pick a property.</p>
        )}
      </section>
    </>
  );
}
