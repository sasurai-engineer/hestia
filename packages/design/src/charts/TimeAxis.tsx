import type { TimeTick } from './days.js';
import type { Scale } from './scale.js';

/**
 * The horizontal time axis: one baseline, month ticks in the usual ink,
 * year ticks heavier — the surveyor's ruled edge every time surface
 * hangs its marks on.
 */
type TimeAxisProps = {
  ticks: readonly TimeTick[];
  x: Scale;
  /** Baseline y in view units. */
  y: number;
  /** Left and right extent of the baseline. */
  from: number;
  to: number;
};

export function TimeAxis({ ticks, x, y, from, to }: TimeAxisProps) {
  return (
    <g>
      <line className="chart__axis-line" x1={from} x2={to} y1={y} y2={y} />
      {ticks.map((tick) => (
        <g key={tick.day}>
          <line className="chart__tick" x1={x(tick.day)} x2={x(tick.day)} y1={y} y2={y + 5} />
          <text
            className={tick.major ? 'chart__axis chart__axis--major' : 'chart__axis'}
            x={x(tick.day)}
            y={y + 16}
            textAnchor="middle"
          >
            {tick.label}
          </text>
        </g>
      ))}
    </g>
  );
}
