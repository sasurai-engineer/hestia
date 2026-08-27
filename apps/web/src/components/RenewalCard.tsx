'use client';

import { Button, DecisionCard } from '@hestia/design';
import type { RenewalContextOut } from '../lib/api';
import { type RenewalOption, renewalAdvice } from '../lib/renewal';
import { formatMoney } from './TransactionsTable';

/**
 * The renewal decision: every candidate ask with its modeled stay
 * probability and EV, the recommendation as the red entry, the flat
 * renewal as the counterfactual. Offering writes a lease_renewals row so
 * the NEXT decision runs on measured history instead of the model.
 */
export function RenewalCard({
  context,
  onOffer,
}: {
  context: RenewalContextOut;
  onOffer: (newRent: string) => void;
}) {
  const advice = renewalAdvice(context);
  // The candidate ladder opens at 0%, so the flat option always exists.
  const flat = advice.options[0] as RenewalOption;
  const scan = `${context.ends_on ? `Lease ends ${context.ends_on}.` : 'No end date on the lease.'}${
    context.market_rent
      ? ` Market ${formatMoney(context.market_rent)} (${context.market_rent_source ?? 'source unrecorded'}).`
      : ''
  }`;
  return (
    <DecisionCard
      title="Renewal offer"
      figureLabel="Recommended ask"
      figure={`+${advice.recommendedIncreasePercent}%`}
      verdict={{ label: 'raise', tone: 'flag' }}
      authority={[{ cite: 'engines/rent', detail: advice.pStayModel }]}
      counterfactual={`Hold the rent flat: expected value ${formatMoney(flat.expectedValue)} at ${flat.pStayPercent}% stay odds.`}
      scan={scan}
      study={
        <table className="table">
          <thead>
            <tr>
              <th>Ask</th>
              <th>New rent</th>
              <th>P(stay)</th>
              <th style={{ textAlign: 'right' }}>Expected value</th>
              <th aria-label="offer" />
            </tr>
          </thead>
          <tbody>
            {advice.options.map((option) => (
              <tr key={option.increasePercent}>
                <td>
                  {option.recommended ? (
                    <strong>+{option.increasePercent}%</strong>
                  ) : (
                    `+${option.increasePercent}%`
                  )}
                </td>
                <td>{formatMoney(option.newRent)}</td>
                <td>{option.pStayPercent}%</td>
                <td style={{ textAlign: 'right' }}>{formatMoney(option.expectedValue)}</td>
                <td>
                  <Button
                    variant={option.recommended ? 'solid' : 'quiet'}
                    onClick={() => {
                      onOffer(option.newRent);
                    }}
                  >
                    Offer
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
      caveat={`${advice.assumptionsSource}. ${advice.pStayModel}`}
    />
  );
}
