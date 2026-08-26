'use client';

import type { RenewalContextOut } from '../lib/api';
import { renewalAdvice } from '../lib/renewal';
import { formatMoney } from './TransactionsTable';

/**
 * The renewal expected-value table: every candidate ask with its modeled
 * stay probability and EV, the recommendation highlighted, the assumptions
 * named. Offering writes a lease_renewals row so the NEXT decision runs on
 * measured history instead of the model.
 */
export function RenewalCard({
  context,
  onOffer,
}: {
  context: RenewalContextOut;
  onOffer: (newRent: string) => void;
}) {
  const advice = renewalAdvice(context);
  return (
    <div className="card">
      <strong>Renewal offer</strong>{' '}
      <span className="pill pill--flag">recommend +{advice.recommendedIncreasePercent}%</span>
      {context.ends_on ? (
        <p className="muted" style={{ margin: '6px 0' }}>
          Lease ends {context.ends_on}
          {context.market_rent
            ? ` · market ${formatMoney(context.market_rent)} (${context.market_rent_source ?? ''})`
            : ''}
        </p>
      ) : null}
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
                <button
                  className={option.recommended ? 'button' : 'button button--quiet'}
                  type="button"
                  onClick={() => {
                    onOffer(option.newRent);
                  }}
                >
                  Offer
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="faint">
        {advice.assumptionsSource}. {advice.pStayModel}
      </p>
    </div>
  );
}
