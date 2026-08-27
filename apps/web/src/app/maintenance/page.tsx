'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { WorkOrderBoard } from '../../components/WorkOrderBoard';
import {
  api,
  type PropertySummary,
  type WorkOrderOut,
  type WorkOrderPriority,
} from '../../lib/api';
import { titleCase } from '../../lib/format';

const PRIORITIES: WorkOrderPriority[] = ['emergency', 'urgent', 'routine', 'planned'];

export default function MaintenancePage() {
  const [orders, setOrders] = useState<WorkOrderOut[]>([]);
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [propertyFilter, setPropertyFilter] = useState('');
  const [openOnly, setOpenOnly] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [propertyId, setPropertyId] = useState('');
  const [summary, setSummary] = useState('');
  const [priority, setPriority] = useState<WorkOrderPriority>('routine');
  const [busy, setBusy] = useState(false);

  const fetchSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++fetchSeq.current;
    try {
      const [rows, props] = await Promise.all([
        api.listWorkOrders({
          ...(propertyFilter ? { propertyId: propertyFilter } : {}),
          openOnly,
        }),
        api.listProperties(),
      ]);
      if (seq !== fetchSeq.current) return;
      setOrders(rows);
      setProperties(props);
      setError(null);
    } catch (caught) {
      if (seq !== fetchSeq.current) return;
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [propertyFilter, openOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const report = async () => {
    if (propertyId === '' || summary.trim() === '') return;
    setBusy(true);
    setError(null);
    try {
      await api.createWorkOrder({
        property_id: propertyId,
        summary: summary.trim(),
        priority,
        reported_by: 'owner',
      });
      setSummary('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="page-title">Maintenance</h1>
      <p className="page-subtitle">
        Every completed job teaches the inventory. Replacing a component retires the old one and
        installs the new with a known date — which is the moment the capital forecast stops guessing
        about it.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void report();
        }}
      >
        <div className="form-row">
          <div className="field">
            <label htmlFor="wo-property">Property</label>
            <select
              id="wo-property"
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
            <label htmlFor="wo-summary">What is wrong</label>
            <input
              id="wo-summary"
              required
              value={summary}
              onChange={(event) => {
                setSummary(event.target.value);
              }}
            />
          </div>
          <div className="field">
            <label htmlFor="wo-priority">Priority</label>
            <select
              id="wo-priority"
              value={priority}
              onChange={(event) => {
                setPriority(event.target.value as WorkOrderPriority);
              }}
            >
              {PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button className="button" type="submit" disabled={busy || propertyId === ''}>
          {busy ? 'Reporting…' : 'Report work'}
        </button>
      </form>

      <section className="section">
        <div className="form-row">
          <div className="field">
            <label htmlFor="wo-filter">Filter by property</label>
            <select
              id="wo-filter"
              value={propertyFilter}
              onChange={(event) => {
                setPropertyFilter(event.target.value);
              }}
            >
              <option value="">all properties</option>
              {properties.map((property) => (
                <option key={property.id} value={property.id}>
                  {property.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="wo-open">Show</label>
            <select
              id="wo-open"
              value={openOnly ? 'open' : 'all'}
              onChange={(event) => {
                setOpenOnly(event.target.value === 'open');
              }}
            >
              <option value="open">open work</option>
              <option value="all">everything</option>
            </select>
          </div>
        </div>
        <WorkOrderBoard orders={orders} />
      </section>
    </>
  );
}
