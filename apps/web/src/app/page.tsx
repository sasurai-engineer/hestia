'use client';

import { useCallback, useEffect, useState } from 'react';
import { PropertyForm } from '../components/PropertyForm';
import { api, type EntityOut, type PropertySummary } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';

export default function PortfolioPage() {
  const [properties, setProperties] = useState<PropertySummary[] | null>(null);
  const [entities, setEntities] = useState<EntityOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const [list, owners] = await Promise.all([api.listProperties(), api.listEntities()]);
      setProperties(list);
      setEntities(owners);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <h1 className="page-title">Portfolio</h1>
      <p className="page-subtitle">
        Every property is a dossier, not a form. Add an address; Hestia infers the rest and shows
        its work.
      </p>
      {error ? (
        <p className="error-note">
          {error} — is the API running? Start the stack with{' '}
          <span className="citation">scripts/dev.sh</span>
        </p>
      ) : null}
      {properties !== null && properties.length === 0 && !adding ? (
        <div className="empty-state">
          <p>No properties yet.</p>
          <button
            className="button"
            type="button"
            onClick={() => {
              setAdding(true);
            }}
          >
            Add the first property
          </button>
        </div>
      ) : null}
      <div className="grid grid--cards">
        {(properties ?? []).map((property) => (
          <a className="card" key={property.id} href={`/property/${property.id}`}>
            <strong>{property.label}</strong>
            <p className="muted">
              {property.street_1}, {property.city}, {property.state} {property.postal_code}
            </p>
            <p className="faint">
              {titleCase(property.kind)}
              {property.year_built != null ? ` · built ${String(property.year_built)}` : ''}
              {property.jurisdiction ? ` · ${property.jurisdiction}` : ''}
            </p>
            <p style={{ marginTop: 8 }}>
              <span className="pill pill--flag">{property.defect_count} flags</span>{' '}
              <span className="pill">{property.component_count} components</span>{' '}
              {property.next_deadline_on ? (
                <span className="pill pill--ok">next: {formatDate(property.next_deadline_on)}</span>
              ) : null}
            </p>
          </a>
        ))}
      </div>
      {/* PLANT (#6 acceptance): sandstone body text on paper is a genuine
          contrast violation the linter cannot see — only the axe gate can.
          This line exists to prove CI goes red, then it is removed. */}
      <p style={{ color: 'var(--sandstone)', background: 'var(--parchment)' }}>
        planted: this sentence fails the contrast gate on purpose
      </p>
      <section className="section">
        {adding || (properties !== null && properties.length > 0) ? (
          <>
            <h2 className="section__title">Add a property</h2>
            <PropertyForm
              entities={entities}
              onCreated={() => {
                setAdding(false);
                void load();
              }}
            />
          </>
        ) : null}
      </section>
    </>
  );
}
