'use client';

import { Button, CitationChip } from '@hestia/design';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
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
  const [splits, setSplits] = useState<NoteSplit[]>([]);
  const [chosen, setChosen] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const debts = await api.listDebts({ propertyId });
        const live = debts.filter(
          (debt) => debt.paid_off_on === null && debt.scheduled_payment !== null,
        );
        const loaded: NoteSplit[] = [];
        for (const debt of live) {
          const split = noteSplit(debt, await api.debtSchedule(debt.id));
          if (split) loaded.push(split);
        }
        setSplits(loaded);
        setChosen(loaded[0]?.debtId ?? '');
      } catch {
        // No offer is an honest state; the plain form still records.
        setSplits([]);
      }
    })();
  }, [propertyId]);

  const split = splits.find((candidate) => candidate.debtId === chosen);
  if (!split) {
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
      <Button
        type="button"
        disabled={occurredOn === ''}
        onClick={() => {
          void record();
        }}
      >
        Record through {split.lender}
      </Button>{' '}
      {occurredOn === '' ? <span className="muted">— pick the date above first</span> : null}
    </div>
  );
}
