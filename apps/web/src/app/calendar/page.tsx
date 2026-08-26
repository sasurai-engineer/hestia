'use client';

import { useEffect, useState } from 'react';
import { DeadlineList } from '../../components/DeadlineList';
import { api, type DeadlineOut } from '../../lib/api';

export default function CalendarPage() {
  const [deadlines, setDeadlines] = useState<DeadlineOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listDeadlines()
      .then(setDeadlines)
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      });
  }, []);

  return (
    <>
      <h1 className="page-title">Calendar</h1>
      <p className="page-subtitle">
        Every date on this page carries the authority that creates it. The platform does not alert
        on guesses.
      </p>
      {error ? <p className="error-note">{error}</p> : null}
      {deadlines ? <DeadlineList deadlines={deadlines} /> : <p className="muted">Loading…</p>}
    </>
  );
}
