'use client';

import {
  ChartFrame,
  isoOf,
  KeyValue,
  linearScale,
  linePath,
  niceTicks,
  Pill,
  RangeField,
} from '@hestia/design';
import { useState } from 'react';
import { type NotePlan, notePlans } from '../lib/amortize-extra';
import type { Financials } from '../lib/api';
import { monthDay } from '../lib/exit-scrub';
import { formatDate } from '../lib/format';
import { formatMoney } from './TransactionsTable';

/**
 * The amortization explorer: scrub an extra principal payment and every
 * note redraws its payoff curve live — the engines' own convention, walked
 * month by month, with the interest saved and the months bought shown as
 * figures, not adjectives. Both curves are futures, so both are dashed.
 */
const WIDTH = 560;
const HEIGHT = 170;
const PAD_LEFT = 56;
const PAD_RIGHT = 14;
const PAD_TOP = 12;
const PAD_BOTTOM = 24;

function NoteCard({ plan, today }: { plan: NotePlan; today: string }) {
  // The walk always opens its curve at month zero on a positive balance,
  // so neither value needs a defensive floor.
  const startBalance = Number((plan.baselineCurve[0] as NotePlan['baselineCurve'][number]).balance);
  const x = linearScale(0, plan.baselineMonths, PAD_LEFT, WIDTH - PAD_RIGHT);
  const y = linearScale(0, startBalance, HEIGHT - PAD_BOTTOM, PAD_TOP);
  const toPoints = (curve: NotePlan['baselineCurve']) =>
    curve.map((point) => ({ x: x(point.month), y: y(Number(point.balance)) }));
  const monthTicks = plan.baselineMonths <= 1 ? [0, 1] : niceTicks(0, plan.baselineMonths, 6);
  return (
    <div className="card">
      <div className="explorer__head">
        <strong>{plan.lender}</strong>{' '}
        {plan.monthsSaved > 0 ? (
          <Pill tone="ok">{plan.monthsSaved} payments sooner</Pill>
        ) : (
          <Pill tone="neutral">as scheduled</Pill>
        )}
      </div>
      <ChartFrame
        viewWidth={WIDTH}
        viewHeight={HEIGHT}
        label={`${plan.lender} — balance as scheduled and with the extra payment`}
      >
        {monthTicks.map((tick) => (
          <text key={tick} className="chart__axis" x={x(tick)} y={HEIGHT - 8} textAnchor="middle">
            {tick}
          </text>
        ))}
        <path
          className="chart__line chart__line--series-3 chart__line--projected"
          d={linePath(toPoints(plan.baselineCurve))}
        />
        <path
          className="chart__line chart__line--projected trace"
          pathLength={1}
          d={linePath(toPoints(plan.extraCurve))}
        />
      </ChartFrame>
      <p className="faint">
        Months from today across the bottom; the graphite curve is the note as scheduled, the ember
        curve carries the extra.
      </p>
      <KeyValue
        items={[
          {
            key: 'As scheduled',
            value: `${plan.baselineMonths} payments — retires ${formatDate(
              isoOf(monthDay(today, plan.baselineMonths)),
            )} · ${formatMoney(plan.baselineInterest)} interest remaining`,
          },
          {
            key: 'With the extra',
            value: `${plan.extraMonths} payments — retires ${formatDate(
              isoOf(monthDay(today, plan.extraMonths)),
            )} · ${formatMoney(plan.extraInterest)} interest remaining`,
          },
          {
            key: 'The working',
            value: `${formatMoney(plan.interestSaved)} of interest never accrues, and the note retires ${plan.monthsSaved} payments early`,
          },
        ]}
      />
    </div>
  );
}

type AmortizationExplorerProps = {
  debts: Financials['debts'];
  today: string;
};

export function AmortizationExplorer({ debts, today }: AmortizationExplorerProps) {
  const [extra, setExtra] = useState(100);
  const plans = notePlans(debts, extra);
  if (plans.length === 0) {
    return null;
  }
  return (
    <div className="explorer">
      <div className="form-row">
        <RangeField
          label="Extra principal, every payment"
          value={extra}
          min={0}
          max={500}
          step={25}
          onChange={setExtra}
          format={(value) => `$${value}/mo`}
        />
      </div>
      {plans.map((plan) => (
        <NoteCard key={plan.lender} plan={plan} today={today} />
      ))}
      <p className="faint">
        The engines’ own convention: interest at annual over twelve, HalfUp at every row, the final
        payment a plug. engines/amortization prices the schedule; the walk only adds the extra.
      </p>
    </div>
  );
}
