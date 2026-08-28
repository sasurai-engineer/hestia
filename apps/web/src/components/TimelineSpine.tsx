'use client';

import {
  Button,
  Card,
  ChartFrame,
  CitationChip,
  Datum,
  dayOf,
  isoOf,
  linearScale,
  Pill,
  TimeAxis,
  timeTicks,
} from '@hestia/design';
import {
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useRef,
  useState,
} from 'react';

import { formatDate } from '../lib/format';
import {
  layoutSpine,
  panned,
  type SpineEvent,
  type SpineWindow,
  visibleEvents,
  windowAround,
} from '../lib/timeline';
import { formatMoney } from './TransactionsTable';

/**
 * The timeline spine: the portfolio as one navigable time axis. Today is
 * the datum; everything left of it is the ledger in solid ink, everything
 * right is dashed projection. Deadline windows render as spans you can aim
 * at. Pan by drag, wheel, or arrows; T returns to today; every mark is a
 * real button that opens its detail below the axis.
 */
const HEIGHT = 158;
const AXIS_Y = 118;
// 32 units between lanes: with 24px hit targets, vertically stacked marks
// keep WCAG 2.5.8 spacing even when the surface renders narrower than the
// viewBox and everything scales down.
const LANE_Y = [98, 66, 34] as const;
const PAD = 18;
const MONTH = 31;
const YEAR = 366;

/** The three mark lanes above the axis; a lane index is always 0, 1, or 2. */
const laneHeight = (lane: number): number => LANE_Y[(lane % LANE_Y.length) as 0 | 1 | 2];

const KIND_LABEL: Record<SpineEvent['kind'], string> = {
  ledger: 'ledger',
  deadline: 'deadline',
  'lease-end': 'lease end',
  capex: 'capex median',
  debt: 'note maturity',
};

function Mark({ event, cx, cy }: { event: SpineEvent; cx: number; cy: number }) {
  const faint = event.faint ? ' chart__mark--faint' : '';
  switch (event.kind) {
    case 'ledger':
      return <circle className={`chart__mark${faint}`} cx={cx} cy={cy} r={3.5} />;
    case 'deadline':
      return (
        <path
          className={`chart__mark chart__mark--deadline${faint}`}
          d={`M${cx} ${cy - 5} L${cx + 4.5} ${cy} L${cx} ${cy + 5} L${cx - 4.5} ${cy} Z`}
        />
      );
    case 'lease-end':
      return (
        <path
          className={`chart__mark chart__mark--lease${faint}`}
          d={`M${cx} ${cy - 5} L${cx + 4.5} ${cy} L${cx} ${cy + 5} L${cx - 4.5} ${cy} Z`}
        />
      );
    case 'capex':
      return <circle className={`chart__mark chart__mark--capex${faint}`} cx={cx} cy={cy} r={4} />;
    case 'debt':
      return (
        <rect
          className={`chart__mark chart__mark--debt${faint}`}
          x={cx - 3.5}
          y={cy - 3.5}
          width={7}
          height={7}
        />
      );
  }
}

type TimelineSpineProps = {
  events: readonly SpineEvent[];
  today: string;
  wide?: boolean;
  ariaLabel: string;
};

export function TimelineSpine({ events, today, wide = false, ariaLabel }: TimelineSpineProps) {
  const todayDay = dayOf(today);
  const [window, setWindow] = useState<SpineWindow>(() => windowAround(todayDay));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const drag = useRef<{ startX: number; window: SpineWindow } | null>(null);

  const viewW = wide ? 1080 : 680;
  const span = window.endDay - window.startDay;
  const x = linearScale(window.startDay, window.endDay, PAD, viewW - PAD);
  const visible = layoutSpine(visibleEvents(events, window), (span * 18) / viewW);
  const selected = events.find((event) => event.id === selectedId);

  // jsdom reports zero-width rects; the view width is the honest fallback.
  const surfaceWidth = (element: HTMLDivElement) => element.getBoundingClientRect().width || viewW;

  const pan = (days: number) => {
    setWindow((current) => panned(current, days));
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    drag.current = { startX: event.clientX, window };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (state === null) {
      return;
    }
    const daysPerPx = span / surfaceWidth(event.currentTarget);
    const delta = Math.round((state.startX - event.clientX) * daysPerPx);
    setWindow(panned(state.window, delta));
  };

  const onPointerEnd = () => {
    drag.current = null;
  };

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const horizontal = Math.abs(event.deltaX) > Math.abs(event.deltaY);
    const delta = horizontal ? event.deltaX : event.shiftKey ? event.deltaY : 0;
    if (delta !== 0) {
      pan(Math.round((delta * span) / surfaceWidth(event.currentTarget)));
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? YEAR : MONTH;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      pan(-step);
      return;
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      pan(step);
      return;
    }
    if (event.key === 't' || event.key === 'T') {
      event.preventDefault();
      setWindow(windowAround(todayDay));
    }
  };

  return (
    <div className="spine">
      {/* A genuine pan-and-inspect widget: role=application, keyboard-driven,
          every mark inside a real button. The tabindex rule the linter cannot
          model is off for this file alone in the app biome.json. */}
      <div
        className="spine__surface"
        role="application"
        aria-label={`${ariaLabel} — pan with the arrow keys, shift for a year, T for today`}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerLeave={onPointerEnd}
        onWheel={onWheel}
        onKeyDown={onKeyDown}
      >
        <ChartFrame viewWidth={viewW} viewHeight={HEIGHT} label={ariaLabel}>
          <TimeAxis
            ticks={timeTicks(window.startDay, window.endDay)}
            x={x}
            y={AXIS_Y}
            from={PAD - 8}
            to={viewW - PAD + 8}
          />
          {visible.map((event) => {
            const laneY = laneHeight(event.lane);
            const markX = x(event.day);
            return (
              <g key={event.id}>
                {event.spanStart === undefined ? null : (
                  <line
                    className="chart__span"
                    x1={x(Math.max(event.spanStart, window.startDay))}
                    x2={markX}
                    y1={laneY}
                    y2={laneY}
                  />
                )}
                <line
                  className={event.projected ? 'chart__stem chart__stem--projected' : 'chart__stem'}
                  x1={markX}
                  x2={markX}
                  y1={AXIS_Y}
                  y2={laneY + 6}
                />
                <Mark event={event} cx={markX} cy={laneY} />
              </g>
            );
          })}
          {todayDay >= window.startDay && todayDay <= window.endDay ? (
            <Datum x={x(todayDay)} top={8} bottom={AXIS_Y} />
          ) : null}
        </ChartFrame>
        {visible.map((event) => (
          <button
            key={event.id}
            type="button"
            className="spine__hit"
            style={{
              left: `${(x(event.day) / viewW) * 100}%`,
              top: `${((laneHeight(event.lane) - 12) / HEIGHT) * 100}%`,
            }}
            aria-label={`${KIND_LABEL[event.kind]}: ${event.label}, ${formatDate(isoOf(event.day))}`}
            onClick={() => {
              setSelectedId((current) => (current === event.id ? null : event.id));
            }}
          />
        ))}
        {visible.length === 0 ? (
          <p className="spine__empty muted">
            Nothing recorded or due in this window — pan with ← and →, or press T for today.
          </p>
        ) : null}
      </div>
      {/* muted, not faint: the legend is prose somebody reads, and faint ink
          fails the contrast gate it taught us to run. */}
      <p className="spine__legend muted">
        ● ledger · <span className="spine__legend-ember">◆</span> deadline (span = open window) ·{' '}
        <span className="spine__legend-fern">◆</span> lease end ·{' '}
        <span className="spine__legend-graphite">○</span> capex median ·{' '}
        <span className="spine__legend-umber">■</span> note maturity — solid is record, dashed is
        projection
      </p>
      {selected === undefined ? null : (
        <Card className="spine__detail">
          <div className="spine__detail-head">
            <strong>{selected.label}</strong>{' '}
            <Pill tone="neutral">{KIND_LABEL[selected.kind]}</Pill>
            <Button variant="quiet" onClick={() => setSelectedId(null)}>
              Close
            </Button>
          </div>
          <p className="muted">
            {formatDate(isoOf(selected.day))}
            {selected.spanStart === undefined
              ? ''
              : ` — window opens ${formatDate(isoOf(selected.spanStart))}`}
            {selected.money === undefined ? '' : ` · ${formatMoney(selected.money)}`}
          </p>
          <p>{selected.detail}</p>
          {selected.citation === undefined ? null : <CitationChip cite={selected.citation} />}
        </Card>
      )}
    </div>
  );
}
