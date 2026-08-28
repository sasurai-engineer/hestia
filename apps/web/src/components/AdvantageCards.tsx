'use client';

import { type Authority, DecisionCard, FanChart, KeyValue, RangeField } from '@hestia/design';
import { useState } from 'react';
import { holdSellView, insuranceView } from '../lib/advantage';
import type { CapexForecastOut, Financials } from '../lib/api';
import { firstShortfall, reserveCoverage } from '../lib/reserve';
import { formatMoney } from './TransactionsTable';

const HOLDSELL_ENGINE: Authority = {
  cite: 'engines/holdsell',
  detail: 'forward year return on current equity',
};
const AMORTIZATION_ENGINE: Authority = {
  cite: 'engines/amortization',
  detail: 'note balances and year-one interest per lien',
};
const INSURANCE_ENGINE: Authority = {
  cite: 'engines/insurance',
  detail: 'coinsurance recovery on a modeled partial loss',
};

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
  const underwater = view.verdict === 'underwater';
  const verdict =
    view.verdict === 'hold'
      ? { label: 'hold', tone: 'ok' as const }
      : view.verdict === 'redeploy'
        ? { label: 'redeploy', tone: 'flag' as const }
        : { label: 'underwater', tone: 'failed' as const };
  const scan = underwater
    ? // Underwater is only reachable WITH a note, so the balance always exists.
      `The note balance ${formatMoney(view.noteBalance as string)} exceeds the equity — no forward return to compute.`
    : `Equity ${formatMoney(view.equity)} earns from cash flow ${formatMoney(view.cashFlow)}, paydown ${formatMoney(view.principalPaydown)}, and appreciation ${formatMoney(view.appreciation)}.`;
  const counterfactual = underwater
    ? 'Selling now realizes the shortfall; holding keeps servicing the note.'
    : view.verdict === 'hold'
      ? `Redeploying gives up a return that clears the ${hurdle}% hurdle by ${view.margin} pts.`
      : `Holding returns ${view.returnOnEquity}% against the ${hurdle}% hurdle (${view.margin} pts).`;
  return (
    <DecisionCard
      title="Hold vs. redeploy"
      figureLabel={underwater ? 'Equity' : 'Forward ROE'}
      figure={underwater ? formatMoney(view.equity) : `${view.returnOnEquity}%`}
      verdict={verdict}
      authority={
        view.noteBalance === null ? [HOLDSELL_ENGINE] : [HOLDSELL_ENGINE, AMORTIZATION_ENGINE]
      }
      counterfactual={counterfactual}
      scan={scan}
      study={
        <div className="form-row">
          <RangeField
            label="Appreciation"
            value={appreciation}
            min={-5}
            max={10}
            step={0.5}
            onChange={setAppreciation}
            format={(value) => `${value}%`}
          />
          <RangeField
            label="Hurdle"
            value={hurdle}
            min={2}
            max={20}
            step={0.5}
            onChange={setHurdle}
            format={(value) => `${value}%`}
          />
        </div>
      }
      audit={
        <KeyValue
          items={[
            { key: 'Equity', value: formatMoney(view.equity) },
            { key: 'Cash flow', value: formatMoney(view.cashFlow) },
            { key: 'Principal paydown', value: formatMoney(view.principalPaydown) },
            { key: `Appreciation @ ${appreciation}%`, value: formatMoney(view.appreciation) },
            ...(view.noteBalance === null
              ? []
              : [{ key: 'Note balance', value: formatMoney(view.noteBalance) }]),
          ]}
        />
      }
      caveat={view.caveat}
    />
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
    <DecisionCard
      title="Insurance adequacy"
      figureLabel="Of coinsurance requirement"
      figure={`${view.compliancePercent}%`}
      verdict={
        view.adequate ? { label: 'adequate', tone: 'ok' } : { label: 'exposed', tone: 'failed' }
      }
      authority={[INSURANCE_ENGINE]}
      counterfactual={`A ${formatMoney(view.modeledLoss)} partial loss recovers ${formatMoney(view.recovered)} — you absorb ${formatMoney(view.retained)}.`}
      scan={`${formatMoney(view.dwellingLimit)} carried${view.carrier ? ` with ${view.carrier}` : ''} against ${view.replacementBasis}.`}
      audit={
        <KeyValue
          items={[
            { key: 'Dwelling limit', value: formatMoney(view.dwellingLimit) },
            { key: 'Compared against', value: view.replacementBasis },
            { key: 'Modeled loss', value: formatMoney(view.modeledLoss) },
            { key: 'Recovered', value: formatMoney(view.recovered) },
            { key: 'Retained', value: formatMoney(view.retained) },
            {
              key: 'Loss of rents',
              value:
                view.lossOfRentsMonths != null
                  ? `${String(view.lossOfRentsMonths)} months`
                  : 'none on record',
            },
          ]}
        />
      }
      caveat={view.caveat}
    />
  );
}

/** The Weibull capex forecast as the package fan: p10–p90 band, traced p50
 * line — and the reserve line: drag a monthly figure and the years the
 * reserve cannot cover wear the failure tint. */
export function CapexFanChart({ forecast }: { forecast: CapexForecastOut }) {
  const [reserve, setReserve] = useState(200);
  if (forecast.components_simulated === 0) {
    return (
      <div className="card">
        <strong>Capital forecast</strong>
        <p className="muted">Assemble the dossier to infer the component inventory first.</p>
      </div>
    );
  }
  const bands = forecast.bands.map((band) => ({
    label: String(band.year),
    low: Number(band.p10),
    mid: Number(band.p50),
    high: Number(band.p90),
  }));
  const coverage = reserveCoverage(forecast, reserve);
  const short = firstShortfall(coverage);
  const shaded = coverage.filter((year) => !year.funded).map((year) => String(year.year));
  return (
    <div className="card">
      <strong>Capital forecast</strong>{' '}
      <span className="pill">
        {formatMoney(forecast.total_expected)} expected / {forecast.horizon_years} yrs
      </span>
      <div style={{ marginTop: 8 }}>
        <FanChart
          bands={bands}
          shaded={shaded}
          label={`Expected capital spend over ${forecast.horizon_years} years with confidence bands`}
        />
      </div>
      <div className="form-row">
        <RangeField
          label="Monthly reserve"
          value={reserve}
          min={0}
          max={1000}
          step={25}
          onChange={setReserve}
          format={(value) => `$${value}/mo`}
        />
      </div>
      <p>
        {short === null
          ? `A ${formatMoney(String(reserve))} monthly reserve funds the median plan through year ${forecast.horizon_years}.`
          : `Year ${short.year} runs ${formatMoney(short.shortfall)} short of the median plan at ${formatMoney(String(reserve))} a month.`}
      </p>
      <p className="faint">
        Weibull Monte Carlo over the live component inventory ({forecast.components_simulated}{' '}
        components); band is p10–p90, line is the median; washed years are where the cumulative
        reserve underruns the cumulative median.
        {forecast.components_without_cost.length > 0
          ? ` Not simulated (no cost on record): ${forecast.components_without_cost.join(', ')}.`
          : ''}
      </p>
    </div>
  );
}
