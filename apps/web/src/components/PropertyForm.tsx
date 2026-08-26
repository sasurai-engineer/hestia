'use client';

import { useState } from 'react';
import { api, type EntityOut } from '../lib/api';

const KINDS = [
  'single_family',
  'duplex',
  'triplex',
  'fourplex',
  'small_multifamily',
  'condominium',
  'townhouse',
  'manufactured',
  'mixed_use',
  'land',
] as const;

/**
 * The one form in the product — and even here the owner types an address and
 * a vintage, not a dossier: everything else is inferred and corrected later.
 */
export function PropertyForm({
  entities,
  onCreated,
}: {
  entities: EntityOut[];
  onCreated: () => void;
}) {
  const [label, setLabel] = useState('');
  const [street, setStreet] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('KY');
  const [postal, setPostal] = useState('');
  const [kind, setKind] = useState<string>('single_family');
  const [yearBuilt, setYearBuilt] = useState('');
  const [entityId, setEntityId] = useState(entities[0]?.id ?? '');
  const [newEntityName, setNewEntityName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      let owner = entityId;
      if (owner === '' && newEntityName.trim() !== '') {
        const entity = await api.createEntity({ name: newEntityName.trim(), kind: 'llc' });
        owner = entity.id;
      }
      await api.createProperty({
        entity_id: owner,
        label: label || street,
        street_1: street,
        city,
        state: state.toUpperCase(),
        postal_code: postal,
        kind: kind as (typeof KINDS)[number],
        year_built: yearBuilt === '' ? null : Number(yearBuilt),
      });
      onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="form-row">
        <div className="field">
          <label htmlFor="pf-street">Street</label>
          <input
            id="pf-street"
            required
            value={street}
            onChange={(e) => {
              setStreet(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="pf-city">City</label>
          <input
            id="pf-city"
            required
            value={city}
            onChange={(e) => {
              setCity(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="pf-state">State</label>
          <input
            id="pf-state"
            required
            maxLength={2}
            value={state}
            onChange={(e) => {
              setState(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="pf-postal">Postal code</label>
          <input
            id="pf-postal"
            required
            value={postal}
            onChange={(e) => {
              setPostal(e.target.value);
            }}
          />
        </div>
      </div>
      <div className="form-row">
        <div className="field">
          <label htmlFor="pf-label">Label</label>
          <input
            id="pf-label"
            placeholder="defaults to the street"
            value={label}
            onChange={(e) => {
              setLabel(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="pf-kind">Kind</label>
          <select
            id="pf-kind"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
            }}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {value.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pf-year">Year built</label>
          <input
            id="pf-year"
            inputMode="numeric"
            placeholder="if known"
            value={yearBuilt}
            onChange={(e) => {
              setYearBuilt(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="pf-entity">Owning entity</label>
          <select
            id="pf-entity"
            value={entityId}
            onChange={(e) => {
              setEntityId(e.target.value);
            }}
          >
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.name}
              </option>
            ))}
            <option value="">+ new LLC…</option>
          </select>
        </div>
      </div>
      {entityId === '' ? (
        <div className="form-row">
          <div className="field">
            <label htmlFor="pf-new-entity">New entity name</label>
            <input
              id="pf-new-entity"
              required
              value={newEntityName}
              onChange={(e) => {
                setNewEntityName(e.target.value);
              }}
            />
          </div>
        </div>
      ) : null}
      {error ? <p className="error-note">{error}</p> : null}
      <button className="button" type="submit" disabled={busy}>
        {busy ? 'Adding…' : 'Add property'}
      </button>
    </form>
  );
}
