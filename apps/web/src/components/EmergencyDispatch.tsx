'use client';

import { Button, Dialog, EmptyState, Pill } from '@hestia/design';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type PropertySummary, type VendorOut } from '../lib/api';
import { rankVendors, SYMPTOMS, type Symptom } from '../lib/dispatch';

/**
 * The 11pm surface. Three taps: open — property — CALL. Urgency is
 * stillness: no motion, no charts, the largest type on the page, targets
 * built for wet hands and a dying phone. An expired certificate warns but
 * never hides the number; a missing plumber degrades to an honest empty
 * state and the incident logger still works.
 */
type Step =
  | { name: 'property' }
  | { name: 'symptom'; property: PropertySummary | null }
  | { name: 'call'; property: PropertySummary | null; symptom: Symptom }
  | { name: 'logged'; summary: string };

type EmergencyDispatchProps = {
  open: boolean;
  onClose: () => void;
};

function CallStep({
  property,
  symptom,
  vendors,
  onBack,
  onLogged,
}: {
  property: PropertySummary | null;
  symptom: Symptom;
  vendors: readonly VendorOut[];
  onBack: () => void;
  onLogged: (summary: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ranked = rankVendors(vendors, symptom.trade);

  const logIncident = async (target: PropertySummary, vendorId?: string) => {
    setBusy(true);
    setError(null);
    // A symptom label always has a head before its ' — ' elaboration.
    const summary = `${symptom.label.split(' — ')[0] as string} emergency`;
    try {
      await api.createWorkOrder({
        property_id: target.id,
        summary,
        detail: `Logged from emergency dispatch: ${symptom.label}`,
        priority: 'emergency',
        reported_by: 'owner',
        ...(vendorId === undefined ? {} : { vendor_id: vendorId }),
      });
      onLogged(summary);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {symptom.note === undefined ? null : <p className="dispatch__note">{symptom.note}</p>}
      {ranked.length === 0 ? (
        <EmptyState>
          No {symptom.trade.replace('_', ' ')} on file — add one under Vendors when the water stops.
          Log the incident now so the record starts tonight.
        </EmptyState>
      ) : (
        ranked.map(({ vendor, fallback, proof, proofTone }) => (
          <div key={vendor.id} className="dispatch__vendor">
            <div className="dispatch__vendor-head">
              <strong>{vendor.name}</strong>
              {fallback ? <Pill tone="neutral">{vendor.trade.replace('_', ' ')}</Pill> : null}
            </div>
            {vendor.phone === null ? (
              <p className="muted">No number on file{vendor.email ? ` — ${vendor.email}` : ''}.</p>
            ) : (
              <a className="dispatch__call" href={`tel:${vendor.phone}`}>
                Call {vendor.phone}
              </a>
            )}
            <p
              className={
                proofTone === 'ok'
                  ? 'dispatch__proof'
                  : proofTone === 'warn'
                    ? 'dispatch__proof dispatch__proof--warn'
                    : 'dispatch__proof dispatch__proof--bad'
              }
            >
              {proof}
            </p>
            {property === null ? null : (
              <Button
                variant="quiet"
                disabled={busy}
                onClick={() => void logIncident(property, vendor.id)}
              >
                Log with this vendor
              </Button>
            )}
          </div>
        ))
      )}
      {property === null ? null : (
        <Button variant="quiet" disabled={busy} onClick={() => void logIncident(property)}>
          Log the incident without a vendor
        </Button>
      )}
      {error === null ? null : <p className="error-note">{error}</p>}
      <Button variant="quiet" onClick={onBack}>
        Back
      </Button>
    </>
  );
}

export function EmergencyDispatch({ open, onClose }: EmergencyDispatchProps) {
  const [step, setStep] = useState<Step>({ name: 'property' });
  const [properties, setProperties] = useState<readonly PropertySummary[]>([]);
  const [vendors, setVendors] = useState<readonly VendorOut[]>([]);
  const fetched = useRef(false);

  useEffect(() => {
    if (open && !fetched.current) {
      fetched.current = true;
      Promise.all([api.listProperties(), api.listVendors()])
        .then(([propertyRows, vendorRows]) => {
          setProperties(propertyRows);
          setVendors(vendorRows);
        })
        .catch(() => {
          // The overlay still renders; retry on the next open.
          fetched.current = false;
        });
    }
  }, [open]);

  const close = useCallback(() => {
    setStep({ name: 'property' });
    onClose();
  }, [onClose]);

  return (
    <Dialog open={open} onClose={close} label="Emergency dispatch" className="dispatch">
      <p className="dispatch__title">Emergency</p>

      {step.name === 'property' ? (
        <>
          <p className="dispatch__ask">Which property?</p>
          {properties.map((property) => (
            <button
              key={property.id}
              type="button"
              className="dispatch__choice"
              onClick={() => setStep({ name: 'symptom', property })}
            >
              {property.label}
            </button>
          ))}
          <button
            type="button"
            className="dispatch__choice dispatch__choice--quiet"
            onClick={() => setStep({ name: 'symptom', property: null })}
          >
            Skip — just get me a number
          </button>
        </>
      ) : null}

      {step.name === 'symptom' ? (
        <>
          <p className="dispatch__ask">What is happening?</p>
          {SYMPTOMS.map((symptom) => (
            <button
              key={symptom.id}
              type="button"
              className="dispatch__choice"
              onClick={() => setStep({ name: 'call', property: step.property, symptom })}
            >
              {symptom.label}
            </button>
          ))}
          <Button variant="quiet" onClick={() => setStep({ name: 'property' })}>
            Back
          </Button>
        </>
      ) : null}

      {step.name === 'call' ? (
        <CallStep
          property={step.property}
          symptom={step.symptom}
          vendors={vendors}
          onBack={() => setStep({ name: 'symptom', property: step.property })}
          onLogged={(summary) => setStep({ name: 'logged', summary })}
        />
      ) : null}

      {step.name === 'logged' ? (
        <>
          <p className="dispatch__ask">
            Logged. “{step.summary}” is on the maintenance board as an emergency.
          </p>
          <Button onClick={close}>Close</Button>
        </>
      ) : null}
    </Dialog>
  );
}
