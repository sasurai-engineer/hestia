'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { CapexFanChart, HoldSellCard, InsuranceCard } from '../../../components/AdvantageCards';
import { ComponentsTable } from '../../../components/ComponentsTable';
import { DeadlineList } from '../../../components/DeadlineList';
import { DefectRegister } from '../../../components/DefectRegister';
import { ExitTimeline } from '../../../components/ExitTimeline';
import { HazardCard } from '../../../components/HazardCard';
import { JurisdictionChain } from '../../../components/JurisdictionChain';
import { StatusPill } from '../../../components/StatusPill';
import { TimelineSpine } from '../../../components/TimelineSpine';
import {
  api,
  type CapexForecastOut,
  type DossierStep,
  type DossierView,
  type Financials,
  type LeaseSummary,
  type LedgerRegister,
} from '../../../lib/api';
import { localIsoDate, titleCase } from '../../../lib/format';
import { buildSpine } from '../../../lib/timeline';

export default function PropertyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [view, setView] = useState<DossierView | null>(null);
  const [financials, setFinancials] = useState<Financials | null>(null);
  const [capex, setCapex] = useState<CapexForecastOut | null>(null);
  const [ledger, setLedger] = useState<LedgerRegister | null>(null);
  const [leases, setLeases] = useState<LeaseSummary[] | null>(null);
  const [steps, setSteps] = useState<DossierStep[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [dossierView, money, forecast, register, leaseRows] = await Promise.all([
        api.readDossier(id),
        api.financials(id),
        api.capexForecast(id),
        api.ledgerRegister({ propertyId: id }),
        api.listLeases(),
      ]);
      setView(dossierView);
      setFinancials(money);
      setCapex(forecast);
      setLedger(register);
      setLeases(leaseRows);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const assemble = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.assembleDossier(id);
      setSteps(result.steps);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  if (view === null) {
    return <p className="muted">{error ?? 'Loading…'}</p>;
  }

  const nowYear = new Date().getFullYear();
  const today = localIsoDate(new Date());
  const spineEvents = buildSpine({
    today,
    ledger: ledger?.events ?? [],
    deadlines: view.deadlines,
    leases: (leases ?? []).filter((lease) => lease.property_label === view.label),
    capex,
    debts: financials?.debts ?? [],
  });

  return (
    <>
      <h1 className="page-title">{view.label}</h1>
      <p className="page-subtitle">
        {view.street_1}, {view.city}, {view.state} {view.postal_code}
        {view.county ? ` · ${view.county}` : ''}
        {view.year_built != null ? ` · built ${String(view.year_built)}` : ''}
      </p>

      <section className="section">
        <h2 className="section__title">The spine</h2>
        <TimelineSpine
          events={spineEvents}
          today={today}
          ariaLabel={`${view.label} — ledger and horizon`}
        />
      </section>

      {financials === null ? null : (
        <section className="section">
          <h2 className="section__title">The exit</h2>
          <ExitTimeline financials={financials} today={today} />
        </section>
      )}

      <button
        className="button"
        type="button"
        disabled={busy}
        onClick={() => {
          void assemble();
        }}
      >
        {busy ? 'Assembling…' : 'Assemble dossier'}
      </button>
      {error ? <p className="error-note">{error}</p> : null}

      {steps ? (
        <section className="section">
          <h2 className="section__title">Assembly report</h2>
          <div className="card">
            {steps.map((step) => (
              <p key={step.name}>
                <StatusPill status={step.status} /> <strong>{titleCase(step.name)}</strong>{' '}
                <span className="muted">{step.detail}</span>
              </p>
            ))}
          </div>
        </section>
      ) : null}

      <section className="section">
        <h2 className="section__title">Analysis</h2>
        <div className="grid" style={{ gap: 14 }}>
          {financials ? <HoldSellCard financials={financials} /> : null}
          {financials ? <InsuranceCard financials={financials} /> : null}
          {capex ? <CapexFanChart forecast={capex} /> : null}
        </div>
      </section>

      <section className="section">
        <h2 className="section__title">Governing bodies</h2>
        <JurisdictionChain chain={view.jurisdiction_chain} />
      </section>

      <section className="section">
        <h2 className="section__title">Hazards</h2>
        {view.hazards.length === 0 ? (
          <p className="muted">No hazard facts yet — assemble the dossier.</p>
        ) : (
          <div className="grid grid--cards">
            {view.hazards.map((hazard) => (
              <HazardCard key={hazard.kind} hazard={hazard} />
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <h2 className="section__title">Component inventory</h2>
        <ComponentsTable components={view.components} nowYear={nowYear} />
      </section>

      <section className="section">
        <h2 className="section__title">Latent-defect register</h2>
        <DefectRegister defects={view.defects} />
      </section>

      <section className="section">
        <h2 className="section__title">Deadlines</h2>
        <DeadlineList deadlines={view.deadlines} />
      </section>
    </>
  );
}
