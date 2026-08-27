'use client';

import { useEffect, useState } from 'react';
import { DeadlineList } from '../../components/DeadlineList';
import { TimelineSpine } from '../../components/TimelineSpine';
import { api, type DeadlineOut, type LeaseSummary, type LedgerRegister } from '../../lib/api';
import { localIsoDate } from '../../lib/format';
import { buildSpine } from '../../lib/timeline';

export default function CalendarPage() {
  const [deadlines, setDeadlines] = useState<DeadlineOut[] | null>(null);
  const [leases, setLeases] = useState<LeaseSummary[] | null>(null);
  const [ledger, setLedger] = useState<LedgerRegister | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listDeadlines(), api.listLeases(), api.ledgerRegister()])
      .then(([deadlineRows, leaseRows, register]) => {
        setDeadlines(deadlineRows);
        setLeases(leaseRows);
        setLedger(register);
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      });
  }, []);

  const today = localIsoDate(new Date());

  return (
    <>
      <h1 className="page-title">Calendar</h1>
      <p className="page-subtitle">
        Every date on this page carries the authority that creates it. The platform does not alert
        on guesses.
      </p>
      {error ? <p className="error-note">{error}</p> : null}
      {deadlines ? (
        <>
          <section className="section">
            <h2 className="section__title">The spine</h2>
            <TimelineSpine
              events={buildSpine({
                today,
                ledger: ledger?.events ?? [],
                deadlines,
                leases: leases ?? [],
              })}
              today={today}
              wide
              ariaLabel="Portfolio — ledger and horizon"
            />
          </section>
          <DeadlineList deadlines={deadlines} />
        </>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </>
  );
}
