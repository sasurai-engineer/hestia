'use client';

import { useState } from 'react';
import { holdSellView, insuranceView } from '../lib/advantage';
import type { CapexForecastOut, Financials } from '../lib/api';
import { formatMoney } from './TransactionsTable';

/** Forward return on equity with draggable assumptions — the engines run in
 * the browser, so moving a slider recomputes with no round trip. */
export function HoldSellCard({ financials }: { financials: Financials }) {
  const [appreciation, setAppreciation] = useState(3);
  const [hurdle, setHurdle] = useState(8);
  const view = holdSellView(financials, {
    appreciationPercent: appreciation,
    hurdlePercent: hurdle,
  });
  if (!view) {
    return (
      <div className="card">
        <strong>Hold vs. redeploy</strong>
        <p className="muted">Record a valuation to unlock the forward return-on-equity verdict.</p>
      </div>
    );
  }
  return (
    <div className="card">
      <strong>Hold vs. redeploy</strong>{' '}
      <span className={view.verdict === 'hold' ? 'pill pill--ok' : 'pill pill--flag'}>
        {view.verdict}
      </span>
      {view.verdict === 'underwater' ? (
        <p className="muted" style={{ margin: '8px 0 2px' }}>
          {/* Underwater is only reachable WITH a note, so the balance always exists. */}
          Equity {formatMoney(view.equity)} · note balance {formatMoney(view.noteBalance as string)}{' '}
          — no return to compute.
        </p>
      ) : (
        <>
          <p style={{ margin: '8px 0 2px' }}>
            Forward ROE <strong>{view.returnOnEquity}%</strong>{' '}
            <span className="muted">
              vs {hurdle}% hurdle ({view.margin} pts)
            </span>
          </p>
          <p className="muted">
            Equity {formatMoney(view.equity)} · cash flow {formatMoney(view.cashFlow)} · paydown{' '}
            {formatMoney(view.principalPaydown)} · appreciation {formatMoney(view.appreciation)}
            {view.noteBalance ? ` · note balance ${formatMoney(view.noteBalance)}` : ''}
          </p>
        </>
      )}
      <div className="form-row" style={{ marginTop: 10 }}>
        <div className="field">
          <label htmlFor="hs-appreciation">Appreciation {appreciation}%</label>
          <input
            id="hs-appreciation"
            type="range"
            min={-5}
            max={10}
            step={0.5}
            value={appreciation}
            onChange={(event) => {
              setAppreciation(Number(event.target.value));
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="hs-hurdle">Hurdle {hurdle}%</label>
          <input
            id="hs-hurdle"
            type="range"
            min={2}
            max={20}
            step={0.5}
            value={hurdle}
            onChange={(event) => {
              setHurdle(Number(event.target.value));
            }}
          />
        </div>
      </div>
      <p className="faint">{view.caveat}</p>
    </div>
  );
}

export function InsuranceCard({ financials }: { financials: Financials }) {
  const view = insuranceView(financials);
  if (!view) {
    return (
      <div className="card">
        <strong>Insurance adequacy</strong>
        <p className="muted">
          Record a policy with a dwelling limit and a valuation to check the coinsurance position.
        </p>
      </div>
    );
  }
  return (
    <div className="card">
      <strong>Insurance adequacy</strong>{' '}
      <span className={view.adequate ? 'pill pill--ok' : 'pill pill--failed'}>
        {view.compliancePercent}% of requirement
      </span>
      <p style={{ margin: '8px 0 2px' }}>
        {formatMoney(view.dwellingLimit)} carried
        {view.carrier ? ` with ${view.carrier}` : ''}{' '}
        <span className="muted">vs {view.replacementBasis}</span>
      </p>
      <p className="muted">
        A {formatMoney(view.modeledLoss)} partial loss recovers {formatMoney(view.recovered)}; you
        absorb {formatMoney(view.retained)}.
        {view.lossOfRentsMonths != null
          ? ` Loss of rents: ${String(view.lossOfRentsMonths)} months.`
          : ' No loss-of-rents coverage on record.'}
      </p>
      <p className="faint">{view.caveat}</p>
    </div>
  );
}

const CHART_W = 560;
const CHART_H = 150;

/** The Weibull capex forecast as an SVG fan: p10–p90 band, p50 line,
 * expected markers. No chart library — one polygon and one polyline. */
export function CapexFanChart({ forecast }: { forecast: CapexForecastOut }) {
  if (forecast.components_simulated === 0) {
    return (
      <div className="card">
        <strong>Capital forecast</strong>
        <p className="muted">Assemble the dossier to infer the component inventory first.</p>
      </div>
    );
  }
  const peak = Math.max(...forecast.bands.map((band) => Number(band.p90)), 1);
  const x = (index: number) =>
    30 + (index * (CHART_W - 50)) / Math.max(forecast.bands.length - 1, 1);
  const y = (value: number) => CHART_H - 24 - (value / peak) * (CHART_H - 40);
  const upper = forecast.bands.map((band, i) => `${x(i)},${y(Number(band.p90))}`);
  const lower = [...forecast.bands]
    .reverse()
    .map((band, i) => `${x(forecast.bands.length - 1 - i)},${y(Number(band.p10))}`);
  const median = forecast.bands.map((band, i) => `${x(i)},${y(Number(band.p50))}`).join(' ');
  return (
    <div className="card">
      <strong>Capital forecast</strong>{' '}
      <span className="pill">
        {formatMoney(forecast.total_expected)} expected / {forecast.horizon_years} yrs
      </span>
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        role="img"
        aria-label={`Expected capital spend over ${forecast.horizon_years} years with confidence bands`}
        style={{ width: '100%', height: 'auto', marginTop: 8 }}
      >
        <polygon
          points={[...upper, ...lower].join(' ')}
          fill="rgb(178 74 23 / 18%)"
          stroke="none"
        />
        <polyline points={median} fill="none" stroke="#b24a17" strokeWidth={2} />
        {forecast.bands.map((band, i) => (
          <text
            key={band.year}
            x={x(i)}
            y={CHART_H - 8}
            fontSize={9}
            fill="#6b6257"
            textAnchor="middle"
          >
            {band.year}
          </text>
        ))}
      </svg>
      <p className="faint">
        Weibull Monte Carlo over the live component inventory ({forecast.components_simulated}{' '}
        components); band is p10–p90, line is the median.
        {forecast.components_without_cost.length > 0
          ? ` Not simulated (no cost on record): ${forecast.components_without_cost.join(', ')}.`
          : ''}
      </p>
    </div>
  );
}
