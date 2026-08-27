import { ChartFrame } from './ChartFrame.js';
import { linePath } from './path.js';
import { linearScale } from './scale.js';
import { niceTicks } from './ticks.js';

/**
 * A quantity over time with an honest floor at zero. The stroke-style law
 * applies: points at or beyond `projectedFrom` draw dashed — a projection
 * never wears a fact's solid ink.
 */
export type CurvePoint = { x: number; y: number };

type BalanceCurveProps = {
  points: readonly CurvePoint[];
  label: string;
  formatX?: (x: number) => string;
  formatY?: (y: number) => string;
  projectedFrom?: number;
  width?: number;
  height?: number;
};

const PAD_LEFT = 52;
const PAD_RIGHT = 12;
const PAD_TOP = 10;
const PAD_BOTTOM = 22;

export function BalanceCurve({
  points,
  label,
  formatX = String,
  formatY = String,
  projectedFrom,
  width = 560,
  height = 180,
}: BalanceCurveProps) {
  if (points.length === 0) {
    return null;
  }
  const xValues = points.map((point) => point.x);
  const yValues = points.map((point) => point.y);
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMax = Math.max(...yValues, 0);
  const x = linearScale(xMin, xMax, PAD_LEFT, width - PAD_RIGHT);
  const y = linearScale(Math.min(...yValues, 0), yMax, height - PAD_BOTTOM, PAD_TOP);
  const xTicks = xMin === xMax ? [xMin] : niceTicks(xMin, xMax, 6);
  const yTicks = niceTicks(Math.min(...yValues, 0), yMax === 0 ? 1 : yMax, 4);
  const solid = points.filter((point) => projectedFrom === undefined || point.x <= projectedFrom);
  const dashed =
    projectedFrom === undefined ? [] : points.filter((point) => point.x >= projectedFrom);
  return (
    <ChartFrame viewWidth={width} viewHeight={height} label={label}>
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line
            className="chart__grid"
            x1={PAD_LEFT}
            x2={width - PAD_RIGHT}
            y1={y(tick)}
            y2={y(tick)}
          />
          <text className="chart__axis" x={PAD_LEFT - 6} y={y(tick) + 3} textAnchor="end">
            {formatY(tick)}
          </text>
        </g>
      ))}
      {xTicks.map((tick) => (
        <text
          key={`x-${tick}`}
          className="chart__axis"
          x={x(tick)}
          y={height - 8}
          textAnchor="middle"
        >
          {formatX(tick)}
        </text>
      ))}
      {solid.length === 0 ? null : (
        <path
          className="chart__line trace"
          pathLength={1}
          d={linePath(solid.map((point) => ({ x: x(point.x), y: y(point.y) })))}
        />
      )}
      {dashed.length === 0 ? null : (
        <path
          className="chart__line chart__line--projected"
          d={linePath(dashed.map((point) => ({ x: x(point.x), y: y(point.y) })))}
        />
      )}
    </ChartFrame>
  );
}
