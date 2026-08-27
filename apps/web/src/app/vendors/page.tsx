'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, type EntityOut, type VendorOut, type VendorTrade } from '../../lib/api';
import { formatDate, titleCase } from '../../lib/format';

const TRADES: VendorTrade[] = [
  'plumbing',
  'hvac',
  'electrical',
  'roofing',
  'appliance',
  'general_contractor',
  'handyman',
  'landscaping',
  'pest_control',
  'cleaning',
  'flooring',
  'painting',
  'restoration',
  'inspection',
  'other',
];

const COVERAGE_TONE: Record<string, string> = {
  current: 'pill pill--ok',
  expiring: 'pill',
  expired: 'pill pill--flag',
  unknown: 'pill pill--flag',
};

const COVERAGE_WORDS: Record<string, string> = {
  current: 'covered',
  expiring: 'expiring',
  expired: 'EXPIRED',
  unknown: 'none on file',
};

export default function VendorsPage() {
  const [vendors, setVendors] = useState<VendorOut[]>([]);
  const [entities, setEntities] = useState<EntityOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [entityId, setEntityId] = useState('');
  const [name, setName] = useState('');
  const [trade, setTrade] = useState<VendorTrade>('plumbing');
  const [liabilityExpires, setLiabilityExpires] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [rows, owners] = await Promise.all([api.listVendors(), api.listEntities()]);
      setVendors(rows);
      setEntities(owners);
      setEntityId((current) => current || (owners[0]?.id ?? ''));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (entityId === '' || name.trim() === '') return;
    setBusy(true);
    setError(null);
    try {
      await api.createVendor({
        entity_id: entityId,
        name: name.trim(),
        trade,
        phone: null,
        email: null,
        license_number: null,
        license_expires_on: null,
        insurer: null,
        liability_expires_on: liabilityExpires || null,
        workers_comp_expires_on: null,
        w9_on_file: false,
        is_1099_reportable: true,
        notes: null,
      });
      setName('');
      setLiabilityExpires('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="page-title">Vendors</h1>
      <p className="page-subtitle">
        A certificate of insurance is a deadline, not a note. The day it lapses is the day you
        silently reassume every risk the vendor was hired to carry — so it lands on the calendar
        like anything else that bites.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void add();
        }}
      >
        <div className="form-row">
          <div className="field">
            <label htmlFor="v-entity">Hired by</label>
            <select
              id="v-entity"
              value={entityId}
              onChange={(event) => {
                setEntityId(event.target.value);
              }}
            >
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="v-name">Name</label>
            <input
              id="v-name"
              required
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </div>
          <div className="field">
            <label htmlFor="v-trade">Trade</label>
            <select
              id="v-trade"
              value={trade}
              onChange={(event) => {
                setTrade(event.target.value as VendorTrade);
              }}
            >
              {TRADES.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="v-coi">Liability expires</label>
            <input
              id="v-coi"
              type="date"
              value={liabilityExpires}
              onChange={(event) => {
                setLiabilityExpires(event.target.value);
              }}
            />
          </div>
        </div>
        <button className="button" type="submit" disabled={busy || entityId === ''}>
          {busy ? 'Adding…' : 'Add vendor'}
        </button>
      </form>

      <section className="section">
        {vendors.length === 0 ? (
          <p className="muted">No vendors yet.</p>
        ) : (
          <div className="card card--flush">
            <table className="table">
              <thead>
                <tr>
                  <th>Vendor</th>
                  <th>Trade</th>
                  <th>Hired by</th>
                  <th>Insurance</th>
                  <th style={{ textAlign: 'right' }}>Open jobs</th>
                </tr>
              </thead>
              <tbody>
                {vendors.map((vendor) => (
                  <tr key={vendor.id}>
                    <td>
                      {vendor.name}
                      {vendor.also_registered_under > 0 ? (
                        <div className="faint">
                          also on {vendor.also_registered_under} other owner
                          {vendor.also_registered_under === 1 ? "'s" : "s'"} list
                        </div>
                      ) : null}
                    </td>
                    <td>{titleCase(vendor.trade)}</td>
                    <td>{vendor.entity_name}</td>
                    <td>
                      <span className={COVERAGE_TONE[vendor.coverage_state] ?? 'pill'}>
                        {COVERAGE_WORDS[vendor.coverage_state]}
                      </span>
                      {vendor.earliest_expiry ? (
                        <span className="faint"> {formatDate(vendor.earliest_expiry)}</span>
                      ) : null}
                    </td>
                    <td style={{ textAlign: 'right' }}>{vendor.open_work_orders}</td>
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
