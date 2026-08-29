'use client';

import { Button, CitationChip } from '@hestia/design';
import { useEffect, useState } from 'react';
import { api, type DebtOut } from '../lib/api';
import { type NoteSplit, noteSplit } from '../lib/mortgage-split';
import { formatMoney } from './TransactionsTable';

/**
 * The honest way to enter a mortgage payment: through the note. One entry
 * becomes the linked interest/principal pair on the ledger — the engine's
 * split for the period, to the cent — instead of two hand-computed lines.
 * Renders nothing when the property has no live amortizing note; the plain
 * form beneath always remains.
 *
 * Render it keyed by propertyId: the remount is what keeps a slow fetch for
 * one property from wearing another property's offer.
 */
type MortgagePaymentOfferProps = {
  propertyId: string;
  occurredOn: string;
  onRecorded: () => void;
};

export function MortgagePaymentOffer({
  propertyId,
  occurredOn,
  onRecorded,
}: MortgagePaymentOfferProps) {
  const [notes, setNotes] = useState<DebtOut[]>([]);
  const [splits, setSplits] = useState<NoteSplit[]>([]);
  const [chosen, setChosen] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Which notes could settle this — knowable without a date, so the path is
  // discoverable before one is picked.
  useEffect(() => {
    api
      .listDebts({ propertyId })
      .then((debts) => {
        setNotes(debts.filter((d) => d.paid_off_on === null && d.scheduled_payment !== null));
      })
      .catch(() => {
        // No offer is an honest state; the plain form still records.
        setNotes([]);
      });
  }, [propertyId]);

  // The figures, which are NOT knowable without a date: the split is fetched
  // as of the day the money carries, so what is promised here is what the
  // server will write for that date (#99).
  useEffect(() => {
    if (occurredOn === '' || notes.length === 0) {
      setSplits([]);
      return;
    }
    (async () => {
      try {
        const loaded: NoteSplit[] = [];
        for (const debt of notes) {
          const split = noteSplit(debt, await api.debtSchedule(debt.id, occurredOn));
          if (split) loaded.push(split);
        }
        setSplits(loaded);
        setChosen((current) =>
          loaded.some((l) => l.debtId === current) ? current : (loaded[0]?.debtId ?? ''),
        );
      } catch {
        setSplits([]);
      }
    })();
  }, [notes, occurredOn]);

  if (notes.length === 0) {
    return null;
  }

  const split = splits.find((candidate) => candidate.debtId === chosen);
  if (!split) {
    // Two different silences, and only one of them is worth breaking. No
    // date yet: name the path, because the operator cannot discover it
    // otherwise. A date with no split (a spent schedule, a fetch that
    // failed): say nothing — the plain form below records it honestly.
    if (occurredOn === '') {
      return (
        <div className="card">
          <p>
            <strong>This looks like a note payment.</strong> Pick the date above and the
            engine&rsquo;s split for that period appears here, ready to record as the linked pair.
          </p>
        </div>
      );
    }
    return null;
  }

  const record = async () => {
    setError(null);
    try {
      await api.recordDebtPayment(split.debtId, {
        paid_on: occurredOn,
        // No figures stated: the server takes the engine's split for the
        // period — the same figures shown here — and writes the pair.
        interest: null,
        principal: null,
        extra_principal: '0',
        escrow: '0',
        post_to_ledger: true,
      });
      onRecorded();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <div className="card">
      <p>
        <strong>This is a note payment.</strong> Record it through the note and the ledger receives
        the linked pair — {formatMoney(split.interest)} interest, {formatMoney(split.principal)}{' '}
        principal, {formatMoney(split.payment)} together. <CitationChip cite={split.citation} />
      </p>
      {splits.length > 1 ? (
        <div className="field">
          <label htmlFor="mp-note">Which note</label>
          <select
            id="mp-note"
            value={chosen}
            onChange={(event) => {
              setChosen(event.target.value);
            }}
          >
            {splits.map((candidate) => (
              <option key={candidate.debtId} value={candidate.debtId}>
                {candidate.lender} — {formatMoney(candidate.payment)}/mo
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {error ? <p className="error-note">{error}</p> : null}
      {/* A split only exists once a date does, so the button cannot be
          reached without one — the dateless case returned above. */}
      <Button
        type="button"
        onClick={() => {
          void record();
        }}
      >
        Record through {split.lender}
      </Button>
    </div>
  );
}
