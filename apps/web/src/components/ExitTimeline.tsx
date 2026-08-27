'use client';

import {
  ChartFrame,
  Datum,
  dayOf,
  isoOf,
  KeyValue,
  linearScale,
  linePath,
  Pill,
  RangeField,
  Stat,
  TimeAxis,
  timeTicks,
} from '@hestia/design';
import {
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { Financials } from '../lib/api';
import { buildExitModel, monthDay } from '../lib/exit-scrub';
import { formatDate } from '../lib/format';
import { formatMoney } from './TransactionsTable';

/**
 * The exit instrument: grab the plumb-bob and scrub the exit month — the
 * engines reprice the whole holding period at every step, to the cent, in
 * the browser. The dashed curve is the effective annual IRR sampled at
 * each year mark; the readout is exact at the scrubbed month. The hurdle
 * is the bar; the ghost tick is the crossover, where redeploy starts
 * beating hold.
 */
const WIDTH = 680;
const HEIGHT = 190;
const AXIS_Y = 150;
const CURVE_TOP = 18;
const PAD = 18;
const AVERAGE_MONTH = 30.4375;

type ExitTimelineProps = {
  financials: Financials;
  today: string;
};

export function ExitTimeline({ financials, today }: ExitTimelineProps) {
  const [appreciation, setAppreciation] = useState(3);
  const [hurdle, setHurdle] = useState(8);
  const [sellingCost, setSellingCost] = useState(6);
  const [exitMonth, setExitMonth] = useState(60);
  const scrubbing = useRef(false);

  const model = useMemo(
    () =>
      buildExitModel(financials, today, {
        appreciationPercent: appreciation,
        hurdlePercent: hurdle,
        sellingCostPercent: sellingCost,
      }),
    [financials, today, appreciation, hurdle, sellingCost],
  );

  if (model === null) {
    return (
      <div className="card">
        <strong>The exit</strong>
        <p className="muted">Record a valuation to unlock the exit instrument.</p>
      </div>
    );
  }

  const todayDay = dayOf(today);
  const horizonDay = monthDay(today, model.horizonMonths);
  const reading = model.readingAt(exitMonth);
  const x = linearScale(todayDay, horizonDay, PAD, WIDTH - PAD);

  const curvePoints = model.yearly
    .filter((point) => point.irrPercent !== null)
    .map((point) => ({ day: point.day, value: Number.parseFloat(point.irrPercent as string) }));
  const valueMax = Math.max(hurdle, ...curvePoints.map((point) => point.value)) + 2;
  const valueMin = Math.min(0, ...curvePoints.map((point) => point.value)) - 1;
  const y = linearScale(valueMin, valueMax, AXIS_Y - 12, CURVE_TOP);

  const verdictPill = model.underwater ? (
    <Pill tone="failed">underwater</Pill>
  ) : reading.verdict === null ? (
    <Pill tone="neutral">no return</Pill>
  ) : reading.verdict === 'hold' ? (
    <Pill tone="ok">hold</Pill>
  ) : (
    <Pill tone="flag">redeploy</Pill>
  );

  const setMonthFromPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const width = rect.width || WIDTH;
    const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / width));
    const day = todayDay + fraction * (horizonDay - todayDay);
    setExitMonth(
      Math.min(model.horizonMonths, Math.max(1, Math.round((day - todayDay) / AVERAGE_MONTH))),
    );
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    scrubbing.current = true;
    setMonthFromPointer(event);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (scrubbing.current) {
      setMonthFromPointer(event);
    }
  };

  const onPointerEnd = () => {
    scrubbing.current = false;
  };

  const onSliderKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = event.shiftKey ? 12 : 1;
    const clamp = (month: number) => Math.min(model.horizonMonths, Math.max(1, month));
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setExitMonth((current) => clamp(current - step));
      return;
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      setExitMonth((current) => clamp(current + step));
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      setExitMonth(1);
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      setExitMonth(model.horizonMonths);
    }
  };

  const exitDate = formatDate(isoOf(reading.day));
  const valueText =
    reading.irrPercent === null
      ? `exit ${exitDate} — no return to report`
      : `exit ${exitDate} — IRR ${reading.irrPercent}`;
  const markerX = x(reading.day);

  return (
    <div className="card exit">
      <div className="exit__head">
        <strong>The exit</strong> {verdictPill}
        <Stat label="Exit IRR, effective annual" value={reading.irrPercent ?? '—'} />
      </div>
      <div
        className="exit__surface"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerLeave={onPointerEnd}
      >
        <ChartFrame
          viewWidth={WIDTH}
          viewHeight={HEIGHT}
          label="Exit IRR across the ten-year horizon"
        >
          <TimeAxis
            ticks={timeTicks(todayDay, horizonDay)}
            x={x}
            y={AXIS_Y}
            from={PAD - 8}
            to={WIDTH - PAD + 8}
          />
          {curvePoints.length === 0 ? null : (
            <>
              <line
                className="chart__hurdle"
                x1={PAD}
                x2={WIDTH - PAD}
                y1={y(hurdle)}
                y2={y(hurdle)}
              />
              <text className="chart__axis" x={WIDTH - PAD} y={y(hurdle) - 4} textAnchor="end">
                hurdle {hurdle}%
              </text>
              <path
                className="chart__line chart__line--projected"
                d={linePath(curvePoints.map((point) => ({ x: x(point.day), y: y(point.value) })))}
              />
            </>
          )}
          {model.crossovers.map((crossover) => (
            <g key={crossover.reading.month}>
              <line
                className="chart__ghost"
                x1={x(crossover.reading.day)}
                x2={x(crossover.reading.day)}
                y1={CURVE_TOP}
                y2={AXIS_Y}
              />
              <text
                className="chart__axis"
                x={x(crossover.reading.day)}
                y={CURVE_TOP - 4}
                textAnchor="middle"
              >
                crossover
              </text>
            </g>
          ))}
          <Datum x={x(todayDay)} top={8} bottom={AXIS_Y} />
          <line className="chart__exit" x1={markerX} x2={markerX} y1={CURVE_TOP} y2={AXIS_Y} />
          <path
            className="chart__exit-head"
            d={`M${markerX} ${CURVE_TOP + 8} L${markerX - 5} ${CURVE_TOP} L${markerX + 5} ${CURVE_TOP} Z`}
          />
        </ChartFrame>
        <button
          type="button"
          className="exit__grip"
          role="slider"
          aria-label="Exit month"
          aria-valuemin={1}
          aria-valuemax={model.horizonMonths}
          aria-valuenow={exitMonth}
          aria-valuetext={valueText}
          style={{ left: `${(markerX / WIDTH) * 100}%` }}
          onKeyDown={onSliderKey}
        />
      </div>
      <div className="exit__readout">
        <KeyValue
          items={[
            { key: 'Exit date', value: exitDate },
            { key: 'Exit value', value: formatMoney(reading.exitValue) },
            { key: 'Loan payoff', value: formatMoney(reading.loanPayoff) },
            { key: 'Net proceeds, pre-tax', value: formatMoney(reading.netProceeds) },
            { key: 'Equity today', value: formatMoney(model.equityToday) },
            ...model.crossovers.map((crossover) =>
              crossover.direction === 'to-hold'
                ? {
                    key: 'Hold from',
                    value: `${formatDate(isoOf(crossover.reading.day))} — the hold clears the hurdle from here`,
                  }
                : {
                    key: 'Hold until',
                    value: `${formatDate(isoOf(crossover.reading.day))} — past here redeploy beats holding`,
                  },
            ),
          ]}
        />
      </div>
      <div className="form-row exit__knobs">
        <RangeField
          label="Appreciation"
          value={appreciation}
          min={-5}
          max={10}
          step={0.5}
          onChange={setAppreciation}
          format={(value) => `${value}%/yr`}
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
        <RangeField
          label="Selling costs"
          value={sellingCost}
          min={4}
          max={10}
          step={0.5}
          onChange={setSellingCost}
          format={(value) => `${value}%`}
        />
      </div>
      <p className="faint">
        {model.gap} The curve is sampled at year marks; the readout is exact at the scrubbed month.
        Appreciation compounds monthly at the annual rate over twelve.
      </p>
    </div>
  );
}
